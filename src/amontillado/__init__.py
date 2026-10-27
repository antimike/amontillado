"""amontillado: a local wallpaper library that knows what its images look like."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("amontillado")
except PackageNotFoundError:
    __version__ = "0+unknown"
