"""Records: a directory per picture, holding `info.yaml` and the picture's files.

The schema is in docs/design.md, "Records". Parsing is strict about authored fields (`id`,
`name`, `default_file`, `source`, `fetched`, the shape of `files`, `derived_from`, `crop`),
which nothing could recompute, and lenient about derived ones (`sha256`, `width`, `height`,
`metrics`), which an invalid value only marks for recomputation.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from amontillado.metrics import METRICS_VERSION, Metrics

SCHEMA = 2
INFO_NAMES = ("info.yaml", "info.yml")
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})
NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]*")
ID_PATTERN = re.compile(r"[0-9a-f]{32}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_RECORD_KEYS = ("schema", "id", "name", "default_file", "source", "fetched", "files")
_FILE_KEYS = ("sha256", "width", "height", "derived_from", "crop", "metrics")


class RecordError(Exception):
    """An info.yaml cannot be used as it is; the message says why."""


@dataclass(frozen=True)
class FileEntry:
    """One file of a record. Derived fields are None when missing, invalid or out of date."""

    sha256: str | None = None
    width: int | None = None
    height: int | None = None
    metrics: Metrics | None = None
    derived_from: str | None = None
    crop: tuple[int, int, int, int] | None = None
    extra: dict[str, object] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        """Whether every derived field is present and current."""
        return None not in (self.sha256, self.width, self.height, self.metrics)

    @property
    def pixels(self) -> int:
        return (self.width or 0) * (self.height or 0)

    def to_dict(self) -> dict[str, object]:
        """The entry as written, keys in schema order; unset optional keys left out."""
        values: dict[str, object] = {
            "sha256": self.sha256,
            "width": self.width,
            "height": self.height,
        }
        if self.derived_from is not None:
            values["derived_from"] = self.derived_from
        if self.crop is not None:
            values["crop"] = list(self.crop)
        values["metrics"] = self.metrics.to_dict() if self.metrics else None
        return {**values, **self.extra}


@dataclass(frozen=True)
class Record:
    """The contents of one info.yaml. `id` is None only for a record not yet given one."""

    id: str | None
    name: str | None = None
    default_file: str | None = None
    source: dict[str, object] | None = None
    fetched: datetime | None = None
    files: dict[str, FileEntry] = field(default_factory=dict)
    extra: dict[str, object] = field(default_factory=dict)

    def default(self, present: set[str]) -> str | None:
        """The default file among `present`: `default_file` if present, else the largest
        non-derived file by pixel count (any file if all are derived), ties broken by name."""
        if self.default_file in present:
            return self.default_file
        candidates = sorted(name for name in present if name in self.files)
        originals = [name for name in candidates if self.files[name].derived_from is None]
        pool = originals or candidates
        return max(pool, key=lambda name: self.files[name].pixels, default=None)

    def to_dict(self) -> dict[str, object]:
        """The record as written, keys in schema order; an unset name or default left out."""
        values: dict[str, object] = {"schema": SCHEMA, "id": self.id}
        if self.name is not None:
            values["name"] = self.name
        if self.default_file is not None:
            values["default_file"] = self.default_file
        values["source"] = self.source
        values["fetched"] = self.fetched
        values["files"] = {name: entry.to_dict() for name, entry in self.files.items()}
        return {**values, **self.extra}


def info_path(directory: Path) -> Path | None:
    """The info file of a record directory, or None; RecordError if it has both."""
    found = [directory / name for name in INFO_NAMES if (directory / name).is_file()]
    if len(found) > 1:
        raise RecordError(f"both {INFO_NAMES[0]} and {INFO_NAMES[1]}; remove one")
    return found[0] if found else None


def sha256_file(path: Path) -> str:
    """The SHA-256 of a file's bytes, as hex."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys instead of keeping the last one."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        seen: set[object] = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in seen
            except TypeError:
                continue  # unhashable: the base class reports it
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    None, None, f"duplicate key {key!r}", key_node.start_mark
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def load_raw(path: Path) -> dict[str, object]:
    """The parsed YAML mapping of an info file, unvalidated; an empty file is an empty mapping.

    Raises RecordError if it is not a YAML mapping, OSError if it cannot be read.
    """
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.load(text, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise RecordError(f"not valid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise RecordError("not a YAML mapping")
    return data


def parse(data: dict[str, object]) -> Record:
    """A record from an info mapping. Raises RecordError naming the first invalid authored
    field; invalid derived fields are left None, to be recomputed."""
    if data.get("schema", SCHEMA) != SCHEMA:
        raise RecordError(f"schema is {data['schema']!r}; this amontillado knows {SCHEMA}")
    record_id = data.get("id")
    if record_id is not None and not (
        isinstance(record_id, str) and ID_PATTERN.fullmatch(record_id)
    ):
        raise RecordError("id is not 32 lowercase hex digits")
    name = data.get("name")
    if name is not None and not (isinstance(name, str) and NAME_PATTERN.fullmatch(name)):
        raise RecordError(f"name {name!r} does not match {NAME_PATTERN.pattern}")
    source = data.get("source")
    if source is not None and not isinstance(source, dict):
        raise RecordError("source is not a mapping")
    fetched = data.get("fetched")
    if fetched is not None and not isinstance(fetched, datetime):
        raise RecordError("fetched is not a timestamp")
    raw_files = data.get("files")
    if raw_files is None:
        raw_files = {}
    if not isinstance(raw_files, dict):
        raise RecordError("files is not a mapping")
    files = {}
    for file_name, raw in raw_files.items():
        files[_file_name(file_name)] = _parse_file(file_name, raw)
    for file_name, entry in files.items():
        if entry.derived_from is not None and (
            entry.derived_from not in files or entry.derived_from == file_name
        ):
            raise RecordError(f"{file_name}: derived_from names no other file of the record")
    default_file = data.get("default_file")
    if default_file is not None and default_file not in files:
        raise RecordError(f"default_file {default_file!r} is not in files")
    extra = {key: value for key, value in data.items() if key not in _RECORD_KEYS}
    return Record(record_id, name, default_file, source, fetched, files, extra)


def _file_name(value: object) -> str:
    if (
        not isinstance(value, str)
        or "/" in value
        or value.startswith(".")
        or Path(value).suffix.lower() not in IMAGE_SUFFIXES
    ):
        raise RecordError(f"files: {value!r} is not the plain name of an image")
    return value


def _parse_file(file_name: str, raw: object) -> FileEntry:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise RecordError(f"{file_name}: not a mapping")
    derived_from = raw.get("derived_from")
    if derived_from is not None and not isinstance(derived_from, str):
        raise RecordError(f"{file_name}: derived_from is not a file name")
    crop = raw.get("crop")
    if crop is not None:
        if not (
            isinstance(crop, list)
            and len(crop) == 4
            and all(_is_int(value) and value >= 0 for value in crop)
            and crop[2] > 0
            and crop[3] > 0
        ):
            raise RecordError(f"{file_name}: crop is not [x, y, width, height]")
        crop = tuple(crop)
    sha256 = raw.get("sha256")
    if not (isinstance(sha256, str) and _SHA256_PATTERN.fullmatch(sha256)):
        sha256 = None
    width, height = (
        value if _is_int(value) and value > 0 else None
        for value in (raw.get("width"), raw.get("height"))
    )
    return FileEntry(
        sha256=sha256,
        width=width,
        height=height,
        metrics=_parse_metrics(raw.get("metrics")),
        derived_from=derived_from,
        crop=crop,
        extra={key: value for key, value in raw.items() if key not in _FILE_KEYS},
    )


def _parse_metrics(block: object) -> Metrics | None:
    if not isinstance(block, dict) or block.get("version") != METRICS_VERSION:
        return None
    try:
        return Metrics.from_dict(block)
    except ValueError:
        return None


def _is_int(value: object) -> bool:
    # bool is an int subclass, and never a size.
    return isinstance(value, int) and not isinstance(value, bool)


def read_record(path: Path) -> Record:
    """Read and validate an info file; raises RecordError or OSError."""
    return parse(load_raw(path))


def write_record(path: Path, record: Record) -> None:
    """Write an info file atomically: a temporary file in the same directory, then a rename."""
    text = yaml.safe_dump(record.to_dict(), sort_keys=False, allow_unicode=True)
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
