"""Each app's template, wherever it comes from, and `amo theme sync`, which fetches them.

docs/design.md, "Theme engine (v0.2)", "Template sources" and "Per-app configuration". An app
names a source (default: the first in the registry with its template) and a template (default:
its own name); `url` and `path` name one file. Only `amo theme sync` uses the network: one GET
per file, at a pinned commit or a configured URL, checked against its sha256 before it is kept.
`amo theme apply` reads what sync kept and fails, naming sync, when a file is missing.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path

from amontillado.config import AppConfig, Config
from amontillado.registry import (
    FETCHED,
    RegistryError,
    cached_path,
    find,
    read_synced,
    sources_dir,
)
from amontillado.registry import (
    text as registry_text,
)
from amontillado.wallhaven import Response

logger = getLogger(__name__)


@dataclass(frozen=True)
class Template:
    """The template an app renders, resolved from its config and the registry."""

    app: str
    source: str
    # The registry name, or the configured path or URL.
    name: str
    format: str
    output: str
    # None for a url or path template: only the registry knows.
    complete: bool | None
    url: str | None = None
    sha256: str | None = None
    # The registry's pinned commit, for a fetched registry template.
    commit: str | None = None
    path: Path | None = None

    @property
    def fetched(self) -> bool:
        return self.url is not None


def resolve(app_name: str, app: AppConfig) -> Template:
    """`app`'s template. Raises RegistryError for one the registry does not have."""
    where = f"theme.apps.{app_name}"
    if app.source == "url":
        # The config requires url, sha256, format and output for these two sources.
        return Template(
            app_name, "url", app.url, app.format, app.output, None, url=app.url, sha256=app.sha256
        )
    if app.source == "path":
        return Template(
            app_name, "path", str(app.path), app.format, app.output, None, path=app.path
        )
    try:
        entry = find(app.source, app.template or app_name)
    except RegistryError as exc:
        raise RegistryError(f"{where}: {exc}") from exc
    if app.format is not None and app.format != entry.format:
        raise RegistryError(f"{where}.format: {entry.source} templates are {entry.format}")
    fetched = entry.source in FETCHED
    return Template(
        app_name,
        entry.source,
        entry.name,
        entry.format,
        app.output or entry.output,
        entry.complete,
        url=entry.url if fetched else None,
        sha256=entry.sha256 if fetched else None,
        commit=entry.commit if fetched else None,
    )


def text(template: Template) -> str:
    """The template's text. Raises RegistryError when it cannot be read (not synced)."""
    what = f"theme.apps.{template.app}"
    if template.path is not None:
        try:
            return template.path.read_text()
        except OSError as exc:
            raise RegistryError(f"{what}: {exc}") from exc
    if template.fetched:
        if template.sha256 is None:
            raise RegistryError(f"{what}: {template.source} {template.name} is not pinned")
        return read_synced(template.sha256, f"{what} ({template.source} {template.name})")
    return registry_text(find("builtin", template.name))


def check_apps(config: Config) -> list[str]:
    """A problem per app whose template cannot be found or read (a fetched one not yet
    synced), and per output file two apps would both write."""
    problems = []
    outputs: dict[str, str] = {}
    for name, app in config.theme.apps.items():
        try:
            template = resolve(name, app)
            text(template)
        except RegistryError as exc:
            problems.append(str(exc))
            continue
        other = outputs.setdefault(template.output, name)
        if other != name:
            problems.append(f"theme.apps.{name}: output {template.output} is also {other}'s")
    return problems


def needed(config: Config) -> list[Template]:
    """The fetched templates the config's apps use, each file once."""
    templates: dict[str, Template] = {}
    for name, app in config.theme.apps.items():
        template = resolve(name, app)
        if template.fetched and template.sha256 is not None:
            templates.setdefault(template.sha256, template)
    return list(templates.values())


Get = Callable[[str, Mapping[str, str]], Response]


def sync(templates: list[Template], get: Get, headers: Mapping[str, str]) -> list[str]:
    """Fetch every template not yet kept (or kept but changed) and keep those matching their
    hash. Returns a problem per template that could not be kept; the others are kept."""
    problems = []
    directory = sources_dir()
    directory.mkdir(parents=True, exist_ok=True)
    for template in templates:
        sha256 = template.sha256
        if _kept(sha256):
            logger.debug("%s: already synced", template.url)
            continue
        response = get(template.url, headers)
        if response.status != 200:
            problems.append(f"{template.url}: HTTP {response.status}")
            continue
        actual = hashlib.sha256(response.body).hexdigest()
        if actual != sha256:
            problems.append(f"{template.url}: sha256 is {actual}, expected {sha256}")
            continue
        _keep(directory, sha256, response.body)
        logger.info("synced %s (%s)", template.name, template.app)
    return problems


def check(templates: list[Template]) -> list[str]:
    """A problem per template that is not kept, or no longer matches its hash."""
    problems = []
    for template in templates:
        try:
            read_synced(template.sha256, template.url)
        except RegistryError as exc:
            problems.append(str(exc))
    return problems


def _kept(sha256: str) -> bool:
    path = cached_path(sha256)
    return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == sha256


def _keep(directory: Path, sha256: str, body: bytes) -> None:
    # Written beside its final name and renamed, so a file named by a hash always has it.
    descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".sync-")
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(body)
    os.replace(temporary, cached_path(sha256))
