"""Paths and the optional config file.

Locations follow the XDG base directory spec; docs/design.md, "Storage", has the layout.
`$XDG_CONFIG_HOME/amontillado/config.yaml` may set:

    library_roots: [~/Pictures/wallpapers]   # searched in addition to the default root
    nsfw_root: ~/private/wallpapers-nsfw     # replaces the default NSFW root
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path

import yaml

logger = getLogger(__name__)

APP = "amontillado"
_KNOWN_KEYS = frozenset({"library_roots", "nsfw_root"})


class ConfigError(Exception):
    """The config file cannot be used; the message says why."""


@dataclass(frozen=True)
class Config:
    """Where the library and its index live."""

    library_roots: tuple[Path, ...]
    nsfw_root: Path
    index_path: Path


def xdg_dir(variable: str, fallback: str) -> Path:
    """An XDG base directory: the variable if set to an absolute path, else ~/<fallback>."""
    value = os.environ.get(variable, "")
    # The spec says relative values are invalid and must be ignored.
    if value and Path(value).is_absolute():
        return Path(value)
    return Path.home() / fallback


def config_path() -> Path:
    return xdg_dir("XDG_CONFIG_HOME", ".config") / APP / "config.yaml"


def load_config() -> Config:
    """Read the config file if there is one and resolve every location."""
    data_home = xdg_dir("XDG_DATA_HOME", ".local/share") / APP
    settings = _read_settings(config_path())

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

    return Config(
        library_roots=tuple(roots),
        nsfw_root=nsfw_root,
        index_path=xdg_dir("XDG_STATE_HOME", ".local/state") / APP / "index.sqlite",
    )


def _read_settings(path: Path) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    try:
        settings = yaml.safe_load(text)
    except yaml.YAMLError as exc:
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


def _path(key: str, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{key}: {value!r} is not a path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ConfigError(f"{key}: {path} is not an absolute path")
    # Resolved so that the overlap check sees through symlinks and "..".
    return path.resolve()
