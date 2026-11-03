"""Applying a palette: render every app into a profile, swap it in, reload.

docs/design.md, "Theme engine (v0.2)", "Flow" and "Cache". A profile is a symlink in the cache,
`<cache>/<profile>`, to a generation directory under `<cache>/.profiles/<profile>/`; `current`
is a symlink to a profile name. Both are moved by renaming a new symlink over the old, so an
app reading during an apply sees the old theme or the new one, never a mix and never nothing.
A render error stops the apply before anything moves.
"""

from __future__ import annotations

import os
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
from amontillado.sources import resolve
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
    if app.render_with != "amontillado":
        raise ThemeError(f"theme.apps.{name}: render_with: {app.render_with} is not supported yet")
    try:
        template = resolve(name, app)
        source_text = template_text(template)
    except RegistryError as exc:
        raise ThemeError(str(exc)) from exc
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
    return Rendered(name, template.output, text, record)


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
    rendered = [render_app(name, theme.apps[name], palette, variant, picture) for name in names]
    apps = {} if not only else {k: v for k, v in old_apps.items() if k in theme.apps}
    apps.update({item.app: item.record for item in rendered})
    copy_from = None
    if only:
        if not existing.is_dir():
            raise ThemeError(f"profile {profile} has not been applied: run without --app first")
        copy_from = existing.resolve()
        wallpaper = None  # the copy keeps its link
    return Plan(profile, palette, rendered, apps, copy_from, wallpaper)


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


def reload_commands(config: Config, plan: Plan, directory: Path) -> list[tuple[str, ...]]:
    """The reload commands to run after `plan`, placeholders filled: each rendered app's, then
    the wallpaper hook. `directory` holds the written plan (the wallpaper link); `{dir}` is
    always the profile's path, so a dry run prints what a real one would run. A command
    naming {wallpaper} when there is none is left out."""
    theme = config.theme
    link = directory / WALLPAPER_LINK
    wallpaper = os.readlink(link) if link.is_symlink() else None
    values = {
        "profile": plan.profile,
        "dir": str(profile_dir(theme, plan.profile)),
        "wallpaper": wallpaper,
    }
    commands = [theme.apps[item.app].reload for item in plan.rendered]
    commands.append(theme.wallpaper_reload)
    filled = []
    for command in commands:
        if command is None:
            continue
        if wallpaper is None and any("{wallpaper}" in arg for arg in command):
            logger.info("no wallpaper: not running %s", " ".join(command))
            continue
        filled.append(tuple(_fill(arg, values) for arg in command))
    return filled


def _fill(arg: str, values: dict[str, str | None]) -> str:
    for name, value in values.items():
        if value is not None:
            arg = arg.replace(f"{{{name}}}", value)
    return arg


def run_reloads(commands: Sequence[tuple[str, ...]]) -> None:
    """Run each command; a failure is a warning (the app may not be running)."""
    for command in commands:
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, check=False, timeout=RELOAD_TIMEOUT
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("reload %s: %s", " ".join(command), exc)
            continue
        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit status {result.returncode}"
            logger.warning("reload %s: %s", " ".join(command), detail)
        else:
            logger.debug("reloaded: %s", " ".join(command))


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
