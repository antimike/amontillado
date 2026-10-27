"""Sidecars: `<image>.yaml` next to each image, the library's source of truth.

The schema is in docs/design.md, "Sidecars". A sidecar holds only facts that do not change
about the image; usage history lives in the index, so sidecars stay stable under sync tools.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from amontillado.metrics import METRICS_VERSION, Metrics

SCHEMA = 1
ID_PREFIX = "sha256:"


class SidecarError(Exception):
    """A sidecar cannot be used as it is; the message says why."""


@dataclass(frozen=True)
class Sidecar:
    """The contents of one sidecar."""

    id: str
    file: str
    width: int
    height: int
    source: dict[str, object] | None
    fetched: datetime | None
    metrics: Metrics

    def to_dict(self) -> dict[str, object]:
        """The sidecar as written, keys in schema order."""
        return {
            "schema": SCHEMA,
            "id": self.id,
            "file": self.file,
            "width": self.width,
            "height": self.height,
            "source": self.source,
            "fetched": self.fetched,
            "metrics": self.metrics.to_dict(),
        }


def sidecar_path(image: Path) -> Path:
    """Where the sidecar of `image` lives: `wallhaven-abc123.jpg` -> `wallhaven-abc123.yaml`."""
    return image.with_suffix(".yaml")


def content_id(path: Path) -> str:
    """The local id of an image: the SHA-256 of its bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
    return ID_PREFIX + digest.hexdigest()


def load_raw(path: Path) -> dict[str, object]:
    """The parsed YAML mapping of a sidecar, unvalidated.

    Raises SidecarError if it is not a YAML mapping, OSError if it cannot be read.
    """
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SidecarError(f"not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise SidecarError("not a YAML mapping")
    return data


def parse(data: dict[str, object]) -> Sidecar:
    """Validate a sidecar mapping. Raises SidecarError naming the first problem.

    Metrics of an older version are a problem: they must be recomputed.
    """
    if data.get("schema") != SCHEMA:
        raise SidecarError(f"schema is {data.get('schema')!r}, expected {SCHEMA}")
    image_id = data.get("id")
    if not isinstance(image_id, str) or not image_id.startswith(ID_PREFIX):
        raise SidecarError("id is missing or invalid")
    file = data.get("file")
    if not isinstance(file, str) or not file:
        raise SidecarError("file is missing or invalid")
    width, height = data.get("width"), data.get("height")
    for name, value in (("width", width), ("height", height)):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise SidecarError(f"{name} is missing or invalid")
    source = data.get("source")
    if source is not None and not isinstance(source, dict):
        raise SidecarError("source is not a mapping")
    fetched = data.get("fetched")
    if fetched is not None and not isinstance(fetched, datetime):
        raise SidecarError("fetched is not a timestamp")
    block = data.get("metrics")
    if not isinstance(block, dict):
        raise SidecarError("metrics are missing")
    if block.get("version") != METRICS_VERSION:
        raise SidecarError(
            f"metrics version is {block.get('version')!r}, current {METRICS_VERSION}"
        )
    try:
        metrics = Metrics.from_dict(block)
    except ValueError as exc:
        raise SidecarError(str(exc)) from exc
    return Sidecar(image_id, file, width, height, source, fetched, metrics)


def read_sidecar(path: Path) -> Sidecar:
    """Read and validate a sidecar; raises SidecarError or OSError."""
    return parse(load_raw(path))


def write_sidecar(path: Path, sidecar: Sidecar) -> None:
    """Write a sidecar atomically: a temporary file in the same directory, then a rename."""
    text = yaml.safe_dump(sidecar.to_dict(), sort_keys=False, allow_unicode=True)
    _write_atomic(path, text)


def _write_atomic(path: Path, text: str) -> None:
    """Replace `path` with `text` so that readers see the old file or the new one, never part."""
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
