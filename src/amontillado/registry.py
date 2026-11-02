"""The template registry: which template each source has, and where a fetched one lives.

docs/design.md, "Theme engine (v0.2)", "Template sources". `registry.yaml`, shipped in the
package, names per source its templates (by the app they are for), each with its output file
and whether it is a complete theme or variables only; a fetched source's entry also has its
repository, path, pinned commit and sha256. Built-in templates are package files. Fetched ones
are kept by `amo theme sync` in `$XDG_CACHE_HOME/amontillado/sources/`, named by their hash, so a
file there is the right one if its name matches its content.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path

import yaml

from amontillado.config import xdg_dir

# The registry's sources in the order a default source is chosen ("Per-app configuration").
FETCHED = ("tinted", "matugen-themes", "pywal")
ORDER = ("builtin", *FETCHED)
FORMAT = {
    "builtin": "mustache",
    "tinted": "mustache",
    "matugen-themes": "matugen",
    "pywal": "pywal",
}
# A mustache tag's name; sections ({{#x}}, {{^x}}) and their ends ({{/x}}) name a variable too.
_TAG = re.compile(r"\{\{\s*[#^/&]?\s*([\w.-]+)\s*\}\}")


class RegistryError(Exception):
    """A template is not in the registry, or not where it should be; the message says why."""


@dataclass(frozen=True)
class Entry:
    """One template of one source."""

    source: str
    name: str
    output: str
    complete: bool
    description: str = ""
    repository: str | None = None
    path: str | None = None
    commit: str | None = None
    sha256: str | None = None

    @property
    def format(self) -> str:
        return FORMAT[self.source]

    @property
    def url(self) -> str:
        """Where `amo theme sync` fetches the file: the path at the pinned commit."""
        return f"https://raw.githubusercontent.com/{self.repository}/{self.commit}/{self.path}"

    @property
    def summary(self) -> str:
        return self.description or f"{self.repository}: {self.path}"


def sources_dir() -> Path:
    return xdg_dir("XDG_CACHE_HOME", ".cache") / "amontillado" / "sources"


@cache
def registry() -> dict[str, dict[str, Entry]]:
    """Every entry of the shipped registry, by source and template name."""
    data = yaml.safe_load((files("amontillado") / "registry.yaml").read_text())
    return parse(data)


def parse(data: object) -> dict[str, dict[str, Entry]]:
    """Registry data as entries. Raises RegistryError for an entry that cannot be used (the
    registry is shipped: a test loads it, so this guards the tool that edits it)."""
    if not isinstance(data, dict) or data.get("version") != 1:
        raise RegistryError("registry: not a version 1 registry")
    commits = {name: (repo or {}).get("commit") for name, repo in data["repositories"].items()}
    entries: dict[str, dict[str, Entry]] = {}
    for source, templates in data["sources"].items():
        if source not in ORDER:
            raise RegistryError(f"registry: unknown source {source}")
        entries[source] = {}
        for name, entry in templates.items():
            where = f"registry: sources.{source}.{name}"
            repository = entry.get("repository")
            if source != "builtin" and (repository not in commits or not entry.get("path")):
                raise RegistryError(f"{where}: needs a listed repository and a path")
            entries[source][name] = Entry(
                source=source,
                name=name,
                output=entry["output"],
                complete=bool(entry["complete"]),
                description=entry.get("description", ""),
                repository=repository,
                path=entry.get("path"),
                commit=commits.get(repository),
                sha256=entry.get("sha256"),
            )
    return entries


def find(source: str | None, name: str) -> Entry:
    """Template `name` of `source`, or of the first source that has one (builtin, tinted,
    matugen-themes, pywal) when `source` is None."""
    entries = registry()
    if source is None:
        for candidate in ORDER:
            if name in entries[candidate]:
                return entries[candidate][name]
        raise RegistryError(f"no source has a template {name!r} (amo theme templates lists them)")
    entry = entries.get(source, {}).get(name)
    if entry is None:
        raise RegistryError(f"{source} has no template {name!r} (amo theme templates lists them)")
    return entry


def cached_path(sha256: str) -> Path:
    return sources_dir() / sha256


def text(entry: Entry) -> str:
    """The template's text: a package file, or the synced file (checked against its hash)."""
    if entry.source == "builtin":
        return (files("amontillado") / "templates" / f"{entry.name}.mustache").read_text()
    if entry.sha256 is None:
        raise RegistryError(f"{entry.source} {entry.name}: not pinned in the registry")
    return read_synced(entry.sha256, f"{entry.source} {entry.name}")


def read_synced(sha256: str, what: str) -> str:
    """A synced file's text. Raises RegistryError, naming `amo theme sync`, if it is missing
    or no longer matches its hash."""
    path = cached_path(sha256)
    try:
        content = path.read_bytes()
    except FileNotFoundError as exc:
        raise RegistryError(f"{what}: not synced (run amo theme sync)") from exc
    if hashlib.sha256(content).hexdigest() != sha256:
        raise RegistryError(f"{what}: {path} does not match its hash (run amo theme sync)")
    return content.decode()


def variables(template: str) -> list[str]:
    """The mustache variables `template` uses, in order of first use."""
    return list(dict.fromkeys(_TAG.findall(template)))
