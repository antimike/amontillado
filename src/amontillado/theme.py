"""Applying a palette: render every app into a profile, swap it in, reload.

docs/design.md, "Theme engine (v0.2)", "Flow" and "Cache". A profile is a symlink in the cache,
`<cache>/<profile>`, to a generation directory under `<cache>/.profiles/<profile>/`; `current`
is a symlink to a profile name. Both are moved by renaming a new symlink over the old, so an
app reading during an apply sees the old theme or the new one, never a mix and never nothing.
A render error stops the apply before anything moves.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from logging import getLogger
from pathlib import Path

import yaml

from amontillado.classes import LIGHT_MIN
from amontillado.config import AppConfig, Config, ThemeConfig, xdg_dir
from amontillado.contrast import apply_contrast
from amontillado.generators import GeneratorError, matugen_render
from amontillado.matugen import MatugenError, material_view, render_matugen
from amontillado.palette import Palette, dump_palette, load_palette
from amontillado.registry import RegistryError
from amontillado.render import (
    RenderError,
    mustache_view,
    pywal_view,
    render_mustache,
    render_pywal,
)
from amontillado.sources import Template, resolve
from amontillado.sources import text as template_text

logger = getLogger(__name__)

PALETTE_FILE = "palette.yaml"
THEME_FILE = "theme.yaml"
WALLPAPER_LINK = "wallpaper"
CURRENT = "current"
GENERATIONS = ".profiles"
# A reload command that hangs must not hold up the theme switch.
RELOAD_TIMEOUT = 30


class ThemeError(Exception):
    """A theme cannot be applied; the message says why. Nothing was changed."""


@dataclass(frozen=True)
class Rendered:
    """One app's file, ready to write, and what theme.yaml records about it."""

    app: str
    output: str
    text: str
    record: dict[str, str]


def palettes_dir() -> Path:
    return xdg_dir("XDG_CONFIG_HOME", ".config") / "amontillado" / "palettes"


def find_palette(value: str) -> Path:
    """`--palette` NAME or FILE: a value naming an existing file is that file, else the preset
    `<palettes dir>/<value>.yaml`."""
    path = Path(value).expanduser()
    if path.is_file():
        return path
    preset = palettes_dir() / f"{value}.yaml"
    if preset.is_file():
        return preset
    raise ThemeError(f"no palette file {value} and no preset {preset}")


def profile_dir(theme: ThemeConfig, profile: str) -> Path:
    """The path apps include from: the profile's symlink."""
    return theme.cache / profile


def current_profile(theme: ThemeConfig) -> str:
    """The profile `current` points to, or the configured one when nothing is applied."""
    link = theme.cache / CURRENT
    return os.readlink(link) if link.is_symlink() else theme.profile


def applied_palette(theme: ThemeConfig, profile: str) -> Palette:
    """The palette last applied to `profile`."""
    path = profile_dir(theme, profile) / PALETTE_FILE
    if not path.is_file():
        raise ThemeError(f"profile {profile} has no palette yet: give --palette")
    return load_palette(path)


def choose_variant(palette: Palette, wanted: str) -> str:
    """`wanted` (auto, dark or light) as a variant `palette` has; a missing one warns."""
    if wanted == "auto":
        lightness = palette.source.get("lightness")
        if isinstance(lightness, (int, float)) and not isinstance(lightness, bool):
            wanted = "light" if lightness > LIGHT_MIN else "dark"
        else:
            wanted = "dark" if "dark" in palette.variants else "light"
    if wanted in palette.variants:
        return wanted
    (only,) = palette.variants
    logger.warning("palette %s has no %s variant: using %s", palette.name, wanted, only)
    return only


def render_app(
    name: str, app: AppConfig, palette: Palette, variant: str, wallpaper: Path | None = None
) -> Rendered:
    """`app` rendered from `palette`. Raises ThemeError for what cannot be rendered (yet), and
    for a fetched template `amo theme sync` has not kept."""
    if app.render_with == "matugen":
        (rendered,) = render_with_matugen({name: app}, palette, variant, wallpaper)
        return rendered
    template, source_text = _template(name, app)
    variant = choose_variant(palette, app.variant or variant)
    try:
        if template.format == "pywal":
            text = render_pywal(source_text, pywal_view(palette, variant, wallpaper))
        elif template.format == "matugen":
            text = render_matugen(source_text, material_view(palette, variant, wallpaper))
        else:
            text = render_mustache(source_text, mustache_view(palette, variant))
    except (RenderError, MatugenError) as exc:
        raise ThemeError(f"theme.apps.{name}: {template.name}: {exc}") from exc
    return Rendered(name, template.output, text, _record(template, variant, palette))


def render_with_matugen(
    apps: dict[str, AppConfig], palette: Palette, variant: str, wallpaper: Path | None = None
) -> list[Rendered]:
    """`apps` (all `render_with: matugen`) rendered by matugen itself, in `apps`' order: one
    run per variant they ask for, from `wallpaper`, or from the variant's accent without one.
    matugen's colours, not the palette's (docs/design.md, "Per-app configuration")."""
    templates = {name: _template(name, app) for name, app in apps.items()}
    variants = {name: choose_variant(palette, app.variant or variant) for name, app in apps.items()}
    rendered = {}
    for mode in dict.fromkeys(variants.values()):
        names = [name for name in apps if variants[name] == mode]
        accent = palette.variants[mode].roles["accent"]
        try:
            label, texts = matugen_render(
                {name: templates[name][1] for name in names},
                mode=mode,
                picture=wallpaper,
                accent=accent,
            )
        except GeneratorError as exc:
            raise ThemeError(f"theme.apps.{', '.join(names)}: render_with: {exc}") from exc
        for name in names:
            template = templates[name][0]
            record = {**_record(template, mode, palette), "renderer": label}
            rendered[name] = Rendered(name, template.output, texts[name], record)
    return [rendered[name] for name in apps]


def _template(name: str, app: AppConfig) -> tuple[Template, str]:
    try:
        template = resolve(name, app)
        return template, template_text(template)
    except RegistryError as exc:
        raise ThemeError(str(exc)) from exc


def _record(template: Template, variant: str, palette: Palette) -> dict[str, str]:
    """What theme.yaml records about one app."""
    record = {
        "source": template.source,
        "template": template.name,
        "output": template.output,
        "variant": variant,
        "palette": palette.name,
    }
    if template.commit is not None:
        record["commit"] = template.commit
    if template.sha256 is not None:
        record["sha256"] = template.sha256
    return record


@dataclass(frozen=True)
class Plan:
    """What an apply does, fixed before anything is written."""

    profile: str
    palette: Palette
    rendered: list[Rendered]
    # Every app's record: the rendered ones, and under --app the others' from theme.yaml.
    apps: dict[str, dict[str, str]]
    # Start from a copy of the profile's current generation (--app).
    copy_from: Path | None
    # The picture the wallpaper link points to, if any.
    wallpaper: Path | None
    # The variant of an app without its own (auto resolved): the wallpaper hook's AMO_VARIANT.
    variant: str


def plan(
    config: Config,
    palette: Palette | None,
    *,
    profile: str,
    variant: str,
    contrast: str,
    only: Sequence[str] = (),
    wallpaper: Path | None = None,
) -> Plan:
    """Render the apps (all, or `only`) of `config` for `profile`, after the contrast check
    (`contrast`: adjust, report or off). `palette` None re-renders the profile's own palette.
    `wallpaper` is the picture `palette` was made from, for the profile's wallpaper link.
    Raises ThemeError before anything is written."""
    theme = config.theme
    unknown = [name for name in only if name not in theme.apps]
    if unknown:
        raise ThemeError(f"--app {', '.join(unknown)}: not under theme.apps")
    existing = profile_dir(theme, profile)
    old_apps = _applied_apps(existing)
    link = existing / WALLPAPER_LINK
    current_wallpaper = Path(os.readlink(link)) if link.is_symlink() else None
    if palette is None:
        palette = applied_palette(theme, profile)
        wallpaper = current_wallpaper
    palette = apply_contrast(palette, contrast)
    names = list(only) or list(theme.apps)
    if not names:
        logger.warning("no apps under theme.apps: only the palette is written")
    # The picture the profile will hold: under --app the copy keeps the current one.
    picture = current_wallpaper if only else wallpaper
    # Every render_with: matugen app in one matugen run per variant, in config order.
    by_matugen = {n: theme.apps[n] for n in names if theme.apps[n].render_with == "matugen"}
    from_matugen = {}
    if by_matugen:
        matugen_apps = render_with_matugen(by_matugen, palette, variant, picture)
        from_matugen = {item.app: item for item in matugen_apps}
    rendered = [
        from_matugen.get(name) or render_app(name, theme.apps[name], palette, variant, picture)
        for name in names
    ]
    apps = {} if not only else {k: v for k, v in old_apps.items() if k in theme.apps}
    apps.update({item.app: item.record for item in rendered})
    copy_from = None
    if only:
        if not existing.is_dir():
            raise ThemeError(f"profile {profile} has not been applied: run without --app first")
        copy_from = existing.resolve()
        wallpaper = None  # the copy keeps its link
    resolved = choose_variant(palette, variant)
    return Plan(profile, palette, rendered, apps, copy_from, wallpaper, resolved)


def _applied_apps(directory: Path) -> dict[str, dict[str, str]]:
    try:
        data = yaml.safe_load((directory / THEME_FILE).read_text())
    except FileNotFoundError:
        return {}
    except (OSError, yaml.YAMLError) as exc:
        raise ThemeError(f"{directory / THEME_FILE}: {exc}") from exc
    apps = data.get("apps") if isinstance(data, dict) else None
    return apps if isinstance(apps, dict) else {}


def write(plan: Plan, directory: Path) -> None:
    """Every file of `plan` into `directory` (empty, or a copy of the profile under --app)."""
    for item in plan.rendered:
        (directory / item.output).write_text(item.text)
    (directory / PALETTE_FILE).write_text(dump_palette(plan.palette))
    if plan.wallpaper is not None:
        (directory / WALLPAPER_LINK).symlink_to(plan.wallpaper)
    theme = {
        "applied": datetime.now(UTC).isoformat(timespec="seconds"),
        "palette": plan.palette.name,
        "apps": plan.apps,
    }
    (directory / THEME_FILE).write_text(yaml.safe_dump(theme, sort_keys=False))


def apply(config: Config, plan: Plan, *, activate: bool) -> Path:
    """Write `plan` as a new generation of its profile and swap it in; point `current` at the
    profile if `activate`. Returns the profile's path."""
    theme = config.theme
    generations = theme.cache / GENERATIONS / plan.profile
    generations.mkdir(parents=True, exist_ok=True)
    link = profile_dir(theme, plan.profile)
    if link.exists() and not link.is_symlink():
        raise ThemeError(f"{link} is not amontillado's: move it away and apply again")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S-")
    new = Path(tempfile.mkdtemp(prefix=stamp, dir=generations))
    try:
        if plan.copy_from is not None:
            shutil.copytree(plan.copy_from, new, symlinks=True, dirs_exist_ok=True)
        new.chmod(0o755)
        write(plan, new)
        old = link.resolve() if link.is_symlink() else None
        _replace_link(link, new.relative_to(theme.cache))
    except BaseException:
        shutil.rmtree(new, ignore_errors=True)
        raise
    # The previous generation stays for a reader still inside it; older ones go.
    for path in generations.iterdir():
        if path not in (new, old):
            shutil.rmtree(path)
    if activate:
        _replace_link(theme.cache / CURRENT, Path(plan.profile))
    return link


def _replace_link(link: Path, target: Path) -> None:
    """Point `link` at `target` by renaming a new symlink over it: atomic, unlike `ln -sfn`."""
    temporary = link.with_name(f".{link.name}.link")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    os.replace(temporary, link)


def repoint_wallpapers(theme: ThemeConfig, old: Path, new: Path) -> list[str]:
    """Point every profile's wallpaper link that is inside the directory `old` at the same
    file inside `new` (a record directory that moved); returns those profiles. The link holds
    an absolute path, so a move would otherwise leave it dangling for the next re-render and
    the wallpaper hook."""
    if not theme.cache.is_dir():
        return []
    moved = []
    for profile in sorted(theme.cache.iterdir()):
        if profile.name == CURRENT or profile.name.startswith(".") or not profile.is_symlink():
            continue
        link = profile / WALLPAPER_LINK
        if not link.is_symlink():
            continue
        target = Path(os.readlink(link))
        if target.is_relative_to(old):
            _replace_link(link, new / target.relative_to(old))
            moved.append(profile.name)
    return moved


@dataclass(frozen=True)
class Reload:
    """A reload command line for `sh -c` and the AMO_* variables it runs with."""

    command: str
    env: dict[str, str]

    def __str__(self) -> str:
        """How a shell would run it: the variables, then `sh -c` and the command line."""
        assignments = [f"{name}={shlex.quote(value)}" for name, value in sorted(self.env.items())]
        return " ".join([*assignments, "sh", "-c", shlex.quote(self.command)])


def reload_commands(config: Config, plan: Plan, directory: Path) -> list[Reload]:
    """The reload commands to run after `plan`: each rendered app's, then the wallpaper hook.
    `directory` holds the written plan (the wallpaper link); AMO_DIR is always the profile's
    path, so a dry run prints what a real one would run. AMO_VARIANT is the variant the app was
    rendered in; for the wallpaper hook, the plan's. With no wallpaper, AMO_WALLPAPER is unset
    and a command naming it is left out."""
    theme = config.theme
    link = directory / WALLPAPER_LINK
    wallpaper = os.readlink(link) if link.is_symlink() else None
    values = {"AMO_PROFILE": plan.profile, "AMO_DIR": str(profile_dir(theme, plan.profile))}
    if wallpaper is not None:
        values["AMO_WALLPAPER"] = wallpaper
    commands = [(theme.apps[item.app].reload, item.record["variant"]) for item in plan.rendered]
    commands.append((theme.wallpaper_reload, plan.variant))
    reloads = []
    for command, variant in commands:
        if command is None:
            continue
        if wallpaper is None and "AMO_WALLPAPER" in command:
            logger.info("no wallpaper: not running %s", command)
            continue
        reloads.append(Reload(command, {**values, "AMO_VARIANT": variant}))
    return reloads


def run_reloads(reloads: Sequence[Reload]) -> None:
    """Run each command under `sh -c`; a failure is a warning (the app may not be running)."""
    for reload in reloads:
        # AMO_* from amo's own environment would be stale: only this run's are set.
        env = {k: v for k, v in os.environ.items() if not k.startswith("AMO_")} | reload.env
        try:
            result = subprocess.run(
                ["sh", "-c", reload.command],
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=RELOAD_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("reload %s: %s", reload.command, exc)
            continue
        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit status {result.returncode}"
            logger.warning("reload %s: %s", reload.command, detail)
        else:
            logger.debug("reloaded: %s", reload.command)


def describe(theme: ThemeConfig, profile: str) -> tuple[dict[str, str], list[str]]:
    """What `profile` holds (profile, palette, picture, applied time) and the palettes its
    apps were rendered from, when they differ (an --app apply with a new palette)."""
    directory = profile_dir(theme, profile)
    try:
        data = yaml.safe_load((directory / THEME_FILE).read_text())
    except FileNotFoundError as exc:
        raise ThemeError(f"profile {profile} has not been applied") from exc
    except (OSError, yaml.YAMLError) as exc:
        raise ThemeError(f"{directory / THEME_FILE}: {exc}") from exc
    if not isinstance(data, dict):
        raise ThemeError(f"{directory / THEME_FILE}: not a mapping")
    link = directory / WALLPAPER_LINK
    info = {
        "profile": profile,
        "palette": str(data.get("palette", "")),
        "picture": os.readlink(link) if link.is_symlink() else "",
        "applied": str(data.get("applied", "")),
    }
    apps = data.get("apps") if isinstance(data.get("apps"), dict) else {}
    palettes = sorted({str(app.get("palette")) for app in apps.values() if isinstance(app, dict)})
    return info, palettes if len(palettes) > 1 else []
