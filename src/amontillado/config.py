"""Paths and the optional config file.

Locations follow the XDG base directory spec; docs/design.md, "Storage", has the layout.
`$XDG_CONFIG_HOME/amontillado/config.yaml` may set:

    library_roots: [~/Pictures/wallpapers]   # searched in addition to the default root
    nsfw_root: ~/private/wallpapers-nsfw     # replaces the default NSFW root
    api_key_command: pass show wallhaven/api-key   # prints the Wallhaven API key
    crop: {preview: auto, viewer: 'xdg-open "$AMO_FILE"'}   # amo crop --interactive's preview
    edit: {default_tool: gimp, tools: {gimp: {cmd: 'gimp -n "$AMO_INPUT"'}}}   # amo edit's editors
    theme: {...}                             # the theme engine (v0.2), below

`amontillado.config_keys` describes every key (the template `amo config init` writes).
`theme` is docs/design.md, "Theme engine (v0.2)", "Per-app configuration": every key is
checked here, so that a mistake fails `amo` at once with the key named, not at the next theme
switch; unknown keys warn.

Every command in the config runs under `sh -c`, its inputs in AMO_* environment variables
(`shell_command`); quoting them is the user's job.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from logging import getLogger
from pathlib import Path

from amontillado import yamlio

logger = getLogger(__name__)

APP = "amontillado"
_KNOWN_KEYS = frozenset({"library_roots", "nsfw_root", "api_key_command", "crop", "edit", "theme"})
API_KEY_VARIABLE = "WALLHAVEN_API_KEY"

SOURCES = ("builtin", "tinted", "matugen-themes", "pywal", "url", "path")
FORMATS = ("mustache", "matugen", "pywal")
GENERATORS = ("matugen", "wallust")
VARIANT_CHOICES = ("auto", "dark", "light")
CONTRAST_CHOICES = ("adjust", "report", "off")
HUES_CHOICES = ("amontillado", "generator")
RENDERERS = ("amontillado", "matugen")
PREVIEWS = ("auto", "kitty", "viewer")
_CROP_KEYS = frozenset({"preview", "viewer"})
DEFAULT_VIEWER = 'xdg-open "$AMO_FILE"'
_EDIT_KEYS = frozenset({"default_tool", "tools"})
_TOOL_KEYS = frozenset({"cmd", "description"})
_TOOL_NAME = re.compile(r"[A-Za-z0-9][\w.+-]*")
# The {placeholder} syntax before v0.4, and the variable each became: a leftover is an error.
OLD_PLACEHOLDERS = {
    "wallpaper": "AMO_WALLPAPER",
    "profile": "AMO_PROFILE",
    "dir": "AMO_DIR",
    "variant": "AMO_VARIANT",
    "file": "AMO_FILE",
}
# Names in a profile directory that amontillado writes itself.
RESERVED_OUTPUTS = frozenset({"palette.yaml", "theme.yaml", "wallpaper"})
_THEME_KEYS = frozenset(
    {"cache", "profile", "generator", "hues", "variant", "contrast", "wallpaper", "apps"}
)
_APP_KEYS = frozenset(
    {
        "source",
        "template",
        "format",
        "url",
        "sha256",
        "path",
        "output",
        "reload",
        "variant",
        "render_with",
    }
)
_OLD_PLACEHOLDER = re.compile(r"(?<!\$)\{(" + "|".join(OLD_PLACEHOLDERS) + r")\}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ConfigError(Exception):
    """The config file cannot be used; the message says why."""


def _default_cache() -> Path:
    return xdg_dir("XDG_CACHE_HOME", ".cache") / "theme"


@dataclass(frozen=True)
class AppConfig:
    """One app under `theme.apps`. None means the registry's default (or, for `variant`, the
    theme's)."""

    source: str | None = None
    template: str | None = None
    format: str | None = None
    url: str | None = None
    sha256: str | None = None
    path: Path | None = None
    output: str | None = None
    # A command line for `sh -c`, with AMO_WALLPAPER, AMO_PROFILE, AMO_DIR and AMO_VARIANT.
    reload: str | None = None
    variant: str | None = None
    render_with: str = "amontillado"


@dataclass(frozen=True)
class ThemeConfig:
    """The `theme` block."""

    cache: Path = field(default_factory=_default_cache)
    profile: str = "default"
    # None: the first installed of GENERATORS.
    generator: str | None = None
    # Who assigns base08-base0F of a picture palette.
    hues: str = "amontillado"
    variant: str = "auto"
    contrast: str = "adjust"
    wallpaper_reload: str | None = None
    apps: dict[str, AppConfig] = field(default_factory=dict)


@dataclass(frozen=True)
class CropConfig:
    """The `crop` block: how `amo crop --interactive` shows its preview."""

    # auto: kitty in a terminal that speaks its graphics protocol, else viewer.
    preview: str = "auto"
    # The viewer's command line for `sh -c`; AMO_FILE is the preview file.
    viewer: str = DEFAULT_VIEWER


@dataclass(frozen=True)
class EditTool:
    """One editor under `edit.tools`: a command line run by `sh -c`, with AMO_INPUT,
    AMO_OUTPUT and AMO_WORKDIR in its environment (`amontillado.edit`)."""

    cmd: str
    description: str | None = None


@dataclass(frozen=True)
class EditConfig:
    """The `edit` block: the editors `amo edit` can run, by name."""

    # None: amo edit needs --tool or --extcmd.
    default_tool: str | None = None
    tools: dict[str, EditTool] = field(default_factory=dict)


@dataclass(frozen=True)
class Config:
    """Where the library and its index live, and the theme engine's settings."""

    library_roots: tuple[Path, ...]
    nsfw_root: Path
    index_path: Path
    api_key_command: str | None = None
    theme: ThemeConfig = field(default_factory=ThemeConfig)
    crop: CropConfig = field(default_factory=CropConfig)
    edit: EditConfig = field(default_factory=EditConfig)


def xdg_dir(variable: str, fallback: str) -> Path:
    """An XDG base directory: the variable if set to an absolute path, else ~/<fallback>."""
    value = os.environ.get(variable, "")
    # The spec says relative values are invalid and must be ignored.
    if value and Path(value).is_absolute():
        return Path(value)
    return Path.home() / fallback


def config_path() -> Path:
    return xdg_dir("XDG_CONFIG_HOME", ".config") / APP / "config.yaml"


def load_config(path: Path | None = None) -> Config:
    """Read the config file (`path`, default config_path()) if there is one and resolve every
    location."""
    data_home = xdg_dir("XDG_DATA_HOME", ".local/share") / APP
    settings = _read_settings(config_path() if path is None else path)

    roots = [(data_home / "library").resolve()]
    for root in _path_list(settings, "library_roots"):
        if root not in roots:
            roots.append(root)
    nsfw = settings.get("nsfw_root")
    nsfw_root = _path("nsfw_root", nsfw) if nsfw is not None else data_home / "library-nsfw"
    nsfw_root = nsfw_root.resolve()

    # A recursive search of a library root must never reach NSFW images (docs/design.md).
    for root in roots:
        if nsfw_root == root or nsfw_root.is_relative_to(root) or root.is_relative_to(nsfw_root):
            raise ConfigError(f"nsfw_root {nsfw_root} overlaps library root {root}")

    command = settings.get("api_key_command")
    if command is not None and not (isinstance(command, str) and command.strip()):
        raise ConfigError("api_key_command must be a command line")

    return Config(
        library_roots=tuple(roots),
        nsfw_root=nsfw_root,
        index_path=xdg_dir("XDG_STATE_HOME", ".local/state") / APP / "index.sqlite",
        api_key_command=command,
        theme=_theme(settings.get("theme")),
        crop=_crop(settings.get("crop")),
        edit=_edit(settings.get("edit")),
    )


# What the shell exits with for a command it cannot find, or cannot run.
_SHELL_STATUSES = {126: "not executable", 127: "command not found"}


def shell_status(status: int) -> str:
    """`exit status N`, with what the shell means by 126 and 127."""
    reason = _SHELL_STATUSES.get(status)
    return f"exit status {status}" + (f" ({reason})" if reason else "")


def commands(config: Config) -> list[tuple[str, str]]:
    """Every command line in `config`, with its key: the ones `sh -c` runs."""
    found = []
    if config.api_key_command is not None:
        found.append(("api_key_command", config.api_key_command))
    found.append(("crop.viewer", config.crop.viewer))
    for name, tool in config.edit.tools.items():
        found.append((f"edit.tools.{name}.cmd", tool.cmd))
    if config.theme.wallpaper_reload is not None:
        found.append(("theme.wallpaper.reload", config.theme.wallpaper_reload))
    for name, app in config.theme.apps.items():
        if app.reload is not None:
            found.append((f"theme.apps.{name}.reload", app.reload))
    return found


def syntax_error(command: str) -> str | None:
    """What `sh -n` says is wrong with `command` (parsed, never run), or None."""
    result = subprocess.run(
        ["sh", "-n", "-c", command], capture_output=True, text=True, check=False
    )
    if result.returncode == 0:
        return None
    return result.stderr.strip() or shell_status(result.returncode)


def shellcheck(command: str) -> list[str]:
    """shellcheck's findings on `command` as a POSIX sh script, one line each (line:column:
    level: message [SCnnnn]). Raises OSError if shellcheck cannot run."""
    result = subprocess.run(
        ["shellcheck", "--shell=sh", "--format=gcc", "-"],
        input=command,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise OSError(result.stderr.strip() or f"shellcheck: {shell_status(result.returncode)}")
    # gcc format: -:LINE:COLUMN: LEVEL: MESSAGE [SCnnnn]
    return [line.removeprefix("-:") for line in result.stdout.splitlines() if line]


def api_key(config: Config) -> str | None:
    """The Wallhaven API key: WALLHAVEN_API_KEY if set, else the first line printed by
    `api_key_command` (run under `sh -c`), else None. Raises ConfigError if the command fails.

    The key is never logged and never written; neither are the command's output or errors,
    which could contain it.
    """
    key = os.environ.get(API_KEY_VARIABLE, "").strip()
    if key:
        return key
    if config.api_key_command is None:
        return None
    try:
        # Its own errors are never shown (they could hold the key), so sh -n names a syntax error.
        error = syntax_error(config.api_key_command)
        if error is not None:
            raise ConfigError(f"api_key_command: {error}")
        result = subprocess.run(
            ["sh", "-c", config.api_key_command],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise ConfigError(f"api_key_command cannot run: {exc}") from exc
    if result.returncode != 0:
        raise ConfigError(f"api_key_command failed with {shell_status(result.returncode)}")
    lines = result.stdout.strip().splitlines()
    if not lines or not lines[0].strip():
        raise ConfigError("api_key_command printed nothing")
    return lines[0].strip()


def _read_settings(path: Path) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    try:
        settings = yamlio.load(text)
    except yamlio.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if settings is None:
        return {}
    if not isinstance(settings, dict):
        raise ConfigError(f"{path} must be a mapping of settings")
    for key in sorted(settings.keys() - _KNOWN_KEYS, key=str):
        logger.warning("%s: unknown setting %r ignored", path, key)
    return settings


def _path_list(settings: dict[str, object], key: str) -> list[Path]:
    value = settings.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"{key} must be a list of paths")
    return [_path(key, item) for item in value]


def _path(key: str, value: object, *, resolve: bool = True) -> Path:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{key}: {value!r} is not a path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ConfigError(f"{key}: {path} is not an absolute path")
    # Resolved so that the overlap check sees through symlinks and "..".
    return path.resolve() if resolve else path


def _theme(value: object) -> ThemeConfig:
    """The `theme` block, checked. Raises ConfigError naming the key."""
    if value is None:
        return ThemeConfig()
    theme = _settings_mapping("theme", value, _THEME_KEYS)
    cache = theme.get("cache")
    wallpaper = _settings_mapping("theme.wallpaper", theme.get("wallpaper") or {}, {"reload"})
    apps = _settings_mapping("theme.apps", theme.get("apps") or {}, None)
    parsed = {}
    for name, app in apps.items():
        if not isinstance(name, str) or not name or "/" in name:
            raise ConfigError(f"theme.apps: {name!r} is not an app name")
        parsed[name] = _app(f"theme.apps.{name}", app)
    outputs: dict[str, str] = {}
    for name, app in parsed.items():
        if app.output is not None and app.output in outputs:
            raise ConfigError(
                f"theme.apps.{name}.output: {app.output} is also {outputs[app.output]}'s"
            )
        if app.output is not None:
            outputs[app.output] = name
    return ThemeConfig(
        cache=_default_cache() if cache is None else _path("theme.cache", cache),
        profile=check_profile(theme.get("profile", "default")),
        generator=_choice("theme.generator", theme.get("generator"), GENERATORS),
        hues=_choice("theme.hues", theme.get("hues", "amontillado"), HUES_CHOICES),
        variant=_choice("theme.variant", theme.get("variant", "auto"), VARIANT_CHOICES),
        contrast=_choice("theme.contrast", _off(theme.get("contrast", "adjust")), CONTRAST_CHOICES),
        wallpaper_reload=shell_command("theme.wallpaper.reload", wallpaper.get("reload")),
        apps=parsed,
    )


def _crop(value: object) -> CropConfig:
    """The `crop` block, checked. Raises ConfigError naming the key."""
    if value is None:
        return CropConfig()
    crop = _settings_mapping("crop", value, _CROP_KEYS)
    viewer = shell_command("crop.viewer", crop.get("viewer")) or DEFAULT_VIEWER
    if "AMO_FILE" not in viewer:
        raise ConfigError("crop.viewer: names no $AMO_FILE")
    return CropConfig(_choice("crop.preview", crop.get("preview", "auto"), PREVIEWS), viewer)


def _edit(value: object) -> EditConfig:
    """The `edit` block, checked. Raises ConfigError naming the key."""
    if value is None:
        return EditConfig()
    edit = _settings_mapping("edit", value, _EDIT_KEYS)
    tools = {}
    for name, tool in _settings_mapping("edit.tools", edit.get("tools") or {}, None).items():
        if not isinstance(name, str) or not _TOOL_NAME.fullmatch(name):
            raise ConfigError(f"edit.tools: {name!r} is not a tool name")
        tools[name] = _tool(f"edit.tools.{name}", tool)
    default = edit.get("default_tool")
    if default is not None and default not in tools:
        raise ConfigError(f"edit.default_tool: {default!r} is not one of edit.tools")
    return EditConfig(default, tools)


def _tool(where: str, value: object) -> EditTool:
    tool = _settings_mapping(where, value, _TOOL_KEYS)
    cmd = tool.get("cmd")
    if not isinstance(cmd, str) or not cmd.strip():
        raise ConfigError(f"{where}.cmd must be a command line")
    description = tool.get("description")
    if description is not None and not (isinstance(description, str) and description.strip()):
        raise ConfigError(f"{where}.description must be text")
    return EditTool(cmd, description)


def _app(where: str, value: object) -> AppConfig:
    app = _settings_mapping(where, value or {}, _APP_KEYS)
    source = _choice(f"{where}.source", app.get("source"), SOURCES)
    format_ = _choice(f"{where}.format", app.get("format"), FORMATS)
    url, sha256, path = app.get("url"), app.get("sha256"), app.get("path")
    if source == "url":
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ConfigError(f"{where}.url: source url needs an https:// URL")
        if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
            raise ConfigError(f"{where}.sha256: source url needs the file's SHA-256, as hex")
    elif url is not None or sha256 is not None:
        raise ConfigError(f"{where}: url and sha256 are for source url only")
    if source == "path":
        if path is None:
            raise ConfigError(f"{where}.path: source path needs a path")
        # Not resolved: the file may be a symlink the user swaps.
        path = _path(f"{where}.path", path, resolve=False)
    elif path is not None:
        raise ConfigError(f"{where}.path: is for source path only")
    if source in ("url", "path") and format_ is None:
        raise ConfigError(f"{where}.format: source {source} needs a format ({', '.join(FORMATS)})")
    render_with = _choice(f"{where}.render_with", app.get("render_with", "amontillado"), RENDERERS)
    if render_with == "matugen" and not (
        format_ == "matugen" or (format_ is None and source == "matugen-themes")
    ):
        raise ConfigError(f"{where}.render_with: matugen renders format matugen only")
    output = app.get("output")
    if output is not None:
        if not isinstance(output, str) or not output or "/" in output or output.startswith("."):
            raise ConfigError(f"{where}.output: {output!r} is not a file name")
        if output in RESERVED_OUTPUTS:
            raise ConfigError(f"{where}.output: {output} is amontillado's own")
    elif source in ("url", "path"):
        raise ConfigError(f"{where}.output: source {source} needs an output file name")
    return AppConfig(
        source=source,
        template=_text(f"{where}.template", app.get("template")),
        format=format_,
        url=url,
        sha256=sha256,
        path=path,
        output=output,
        reload=shell_command(f"{where}.reload", app.get("reload")),
        variant=_choice(f"{where}.variant", app.get("variant"), VARIANT_CHOICES),
        render_with=render_with,
    )


def _settings_mapping(where: str, value: object, known: frozenset[str] | set[str] | None) -> dict:
    """`value` as a mapping; keys outside `known` (unless None) warn."""
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a mapping")
    if known is not None:
        for key in sorted(value.keys() - known, key=str):
            logger.warning("unknown setting %r ignored", f"{where}.{key}")
    return value


def _choice(key: str, value: object, choices: tuple[str, ...]) -> str | None:
    if value is None or value in choices:
        return value  # type: ignore[return-value]
    raise ConfigError(f"{key}: {value!r} is not one of {', '.join(choices)}")


def _off(value: object) -> object:
    # YAML 1.1 reads an unquoted `off` as false.
    return "off" if value is False else value


def _text(key: str, value: object) -> str | None:
    if value is None or (isinstance(value, str) and value):
        return value
    raise ConfigError(f"{key}: {value!r} is not a name")


def check_profile(value: object, key: str = "theme.profile") -> str:
    """`value` if it can name a profile: a symlink in the cache beside `current` and the
    hidden `.profiles` directory. Raises ConfigError naming `key`."""
    if (
        not isinstance(value, str)
        or not value
        or "/" in value
        or value.startswith(".")
        or value == "current"
    ):
        raise ConfigError(f"{key}: {value!r} is not a profile name")
    return value


def shell_command(key: str, value: object) -> str | None:
    """A command line for `sh -c`, checked: a string that is not blank and names no {placeholder}
    of the syntax before v0.4 (the message names its AMO_* variable). Raises ConfigError."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} must be a command line")
    old = _OLD_PLACEHOLDER.search(value)
    if old is not None:
        variable = OLD_PLACEHOLDERS[old[1]]
        raise ConfigError(
            f"{key}: {{{old[1]}}} is gone: commands run under sh -c with ${variable} in their "
            f'environment (quote it: "${variable}")'
        )
    return value
