"""The SQLite index: records and their files, rebuilt from the info files, and the usage history.

docs/design.md, "Index and usage". The `records` and `files` tables hold nothing that is not in
an info file (or implied by where a record lives), so `rebuild` drops and recreates them: a
schema change to them needs no migration. The `usage` table, keyed by record id, cannot be
rebuilt and is never dropped, except once when upgrading from schema 1, whose usage rows were
keyed by content hash.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from logging import getLogger
from pathlib import Path

from amontillado.library import Entry
from amontillado.metrics import Metrics
from amontillado.record import ID_PATTERN, sha256_file

logger = getLogger(__name__)

SCHEMA_VERSION = 2

_CREATE_RECORDS = """
CREATE TABLE records (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE,
    directory TEXT NOT NULL,
    root TEXT NOT NULL,
    nsfw_root INTEGER NOT NULL,
    purity TEXT NOT NULL,
    category TEXT,
    tags TEXT NOT NULL,
    source_site TEXT,
    source_id TEXT
)
"""
_CREATE_FILES = """
CREATE TABLE files (
    path TEXT PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES records (id),
    sha256 TEXT NOT NULL,
    is_default INTEGER NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    lightness REAL NOT NULL,
    chroma REAL NOT NULL,
    colourful_share REAL NOT NULL,
    hue REAL,
    hue_name TEXT,
    hue_share REAL NOT NULL,
    hue_spread REAL NOT NULL,
    warmth REAL NOT NULL,
    busy REAL NOT NULL
)
"""
_CREATE_FILES_SHA256 = "CREATE INDEX files_sha256 ON files (sha256)"
_CREATE_USAGE = """
CREATE TABLE IF NOT EXISTS usage (
    id TEXT PRIMARY KEY,
    shown_count INTEGER NOT NULL,
    last_shown TEXT NOT NULL
)
"""
_RECORD_SHOWN = """
INSERT INTO usage (id, shown_count, last_shown) VALUES (?, 1, ?)
ON CONFLICT (id) DO UPDATE SET shown_count = shown_count + 1, last_shown = excluded.last_shown
"""
_INSERT_RECORD = """
INSERT INTO records VALUES (
    :id, :name, :directory, :root, :nsfw_root, :purity, :category, :tags, :source_site,
    :source_id
)
"""
_INSERT_FILE = """
INSERT INTO files VALUES (
    :path, :record_id, :sha256, :is_default, :width, :height, :lightness, :chroma,
    :colourful_share, :hue, :hue_name, :hue_share, :hue_spread, :warmth, :busy
)
"""
# The metric columns in Metrics field order, so that a row unpacks into Metrics.
_SELECT_FILES = """
SELECT f.path, f.record_id, r.purity, r.nsfw_root, f.is_default, f.width, f.height,
    f.lightness, f.chroma, f.colourful_share, f.hue, f.hue_name, f.hue_share, f.hue_spread,
    f.warmth, f.busy
FROM files f JOIN records r ON r.id = f.record_id
ORDER BY f.path
"""


class IndexDatabaseError(Exception):
    """The index cannot be used; the message says why."""


class LookupFailed(Exception):
    """No single record answers to a name, id, prefix or path; the message says why."""


@dataclass(frozen=True)
class IndexedFile:
    """A file of a record, as the index knows it."""

    path: Path
    record_id: str
    purity: str
    nsfw_root: bool
    is_default: bool
    width: int
    height: int
    metrics: Metrics


def connect(path: Path) -> sqlite3.Connection:
    """Open the index, creating it (and its directory) if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Transactions are explicit, so that DDL in a rebuild is part of one.
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise IndexDatabaseError(
                f"{path} has schema {version}; this amontillado knows {SCHEMA_VERSION}"
            )
        conn.execute("BEGIN")
        if version == 1:
            # Schema 1 keyed usage by content hash; records are keyed by id now.
            logger.warning("%s: upgrading from schema 1; the usage history is discarded", path)
            conn.execute("DROP TABLE IF EXISTS images")
            conn.execute("DROP TABLE IF EXISTS usage")
        if not _has_table(conn, "records"):
            _create_tables(conn)
        conn.execute(_CREATE_USAGE)
        # PRAGMA takes no parameters; the value is a constant.
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.execute("COMMIT")
    except BaseException:
        conn.close()
        raise
    return conn


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    query = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
    return conn.execute(query, (name,)).fetchone() is not None


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_RECORDS)
    conn.execute(_CREATE_FILES)
    conn.execute(_CREATE_FILES_SHA256)


def rebuild(conn: sqlite3.Connection, entries: Iterable[Entry]) -> int:
    """Replace the records and files tables with `entries`, in one transaction; returns the
    record count."""
    entries = list(entries)
    conn.execute("BEGIN")
    try:
        conn.execute("DROP TABLE IF EXISTS files")
        conn.execute("DROP TABLE IF EXISTS records")
        _create_tables(conn)
        _insert(conn, entries)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return len(entries)


def _insert(conn: sqlite3.Connection, entries: list[Entry]) -> None:
    conn.executemany(_INSERT_RECORD, [_record_row(entry) for entry in entries])
    conn.executemany(_INSERT_FILE, [row for entry in entries for row in _file_rows(entry)])


def _record_row(entry: Entry) -> dict[str, object]:
    source = entry.record.source or {}
    tags = source.get("tags")
    tags = [str(tag) for tag in tags] if isinstance(tags, list) else []
    return {
        "id": entry.id,
        "name": entry.name,
        "directory": str(entry.directory),
        "root": str(entry.root),
        "nsfw_root": entry.nsfw_root,
        "purity": entry.purity,
        "category": _text(source.get("category")),
        "tags": json.dumps(tags),
        "source_site": _text(source.get("site")),
        "source_id": _text(source.get("id")),
    }


def _file_rows(entry: Entry) -> list[dict[str, object]]:
    rows = []
    for name in entry.present:
        file = entry.record.files[name]
        assert file.metrics is not None
        rows.append(
            {
                "path": str(entry.directory / name),
                "record_id": entry.id,
                "sha256": file.sha256,
                "is_default": name == entry.default,
                "width": file.width,
                "height": file.height,
                **{key: getattr(file.metrics, key) for key in Metrics.__dataclass_fields__},
            }
        )
    return rows


def _text(value: object) -> str | None:
    # A hand-edited Wallhaven id of digits only would load as an int.
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return str(value)


def files(conn: sqlite3.Connection) -> list[IndexedFile]:
    """Every indexed file, by path."""
    return [
        IndexedFile(
            path=Path(path),
            record_id=record_id,
            purity=purity,
            nsfw_root=bool(nsfw_root),
            is_default=bool(is_default),
            width=width,
            height=height,
            metrics=Metrics(*metrics),
        )
        for path, record_id, purity, nsfw_root, is_default, width, height, *metrics in (
            conn.execute(_SELECT_FILES)
        )
    ]


def find_record(conn: sqlite3.Connection, query: str) -> str:
    """The id of the record that `query` names: an existing file or record directory, else a
    name, an id, or a unique prefix of an id. Raises LookupFailed."""
    path = Path(query)
    if path.exists():
        return _record_at(conn, path)
    row = conn.execute(
        "SELECT id FROM records WHERE name = ? UNION ALL SELECT id FROM records WHERE id = ?",
        (query, query),
    ).fetchone()
    if row:
        return row[0]
    if query and ID_PATTERN.fullmatch(query.ljust(32, "0")):
        found = conn.execute(
            "SELECT id FROM records WHERE substr(id, 1, ?) = ? ORDER BY id LIMIT 2",
            (len(query), query),
        ).fetchall()
        if len(found) == 1:
            return found[0][0]
        if found:
            raise LookupFailed(f"{query}: more than one record id starts with it")
    raise LookupFailed(f"{query}: no such file, and no record has that name or id")


def _record_at(conn: sqlite3.Connection, path: Path) -> str:
    absolute = str(path.absolute())
    row = conn.execute(
        "SELECT record_id FROM files WHERE path = ? "
        "UNION ALL SELECT id FROM records WHERE directory = ?",
        (absolute, absolute),
    ).fetchone()
    if row:
        return row[0]
    if path.is_dir():
        raise LookupFailed(f"{path}: not an indexed record; run `amo index`")
    # Not where the index saw it: a move or a copy since, or a symlink; the content says.
    ids = {
        record_id
        for (record_id,) in conn.execute(
            "SELECT DISTINCT record_id FROM files WHERE sha256 = ?", (sha256_file(path),)
        )
    }
    if len(ids) == 1:
        return ids.pop()
    if ids:
        raise LookupFailed(f"{path}: its content is in more than one record")
    raise LookupFailed(f"{path}: not in the index; run `amo index`")


def record_shown(conn: sqlite3.Connection, record_id: str, when: datetime | None = None) -> None:
    """Count one showing of the record with `record_id`, at `when` (default now, UTC)."""
    when = when or datetime.now(timezone.utc)
    conn.execute("BEGIN")
    try:
        conn.execute(_RECORD_SHOWN, (record_id, when.isoformat(timespec="seconds")))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
