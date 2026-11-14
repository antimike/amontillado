"""The SQLite index: records and their files, rebuilt from the info files, and the usage history.

docs/design.md, "Index and usage". The `records` and `files` tables hold nothing that is not in
an info file (or implied by where a record lives), so `rebuild` drops and recreates them: a
schema change to them needs no migration. The `usage` table, keyed by record id, cannot be
rebuilt and is never dropped, except once when upgrading from schema 1, whose usage rows were
keyed by content hash. Each file's size and mtime are kept beside its hash, so that the next
`amo index` need not hash it again (`known_hashes`). Each record's info file is also kept whole,
as JSON (`records.info`), and the `pictures` view flattens what `amo list --where` filters on
(`matching_records`).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from logging import getLogger
from pathlib import Path

from amontillado.library import Entry
from amontillado.metrics import Metrics
from amontillado.record import ID_PATTERN, sha256_file

logger = getLogger(__name__)

SCHEMA_VERSION = 7
# `->` and `->>` came in SQLite 3.38; json_extract works before.
JSON_ARROWS = (3, 38, 0)

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
    source_id TEXT,
    thumbnail TEXT,
    license TEXT,
    author TEXT,
    title TEXT,
    info TEXT
)
"""
# What `amo list --where` sees: a record per row, flattened, with its usage and its info file.
_CREATE_PICTURES = """
CREATE VIEW pictures AS
SELECT r.id, r.name, r.directory, r.purity, r.source_site AS site, r.source_id, r.category,
    r.tags, r.license, r.author, r.title, coalesce(u.shown_count, 0) AS shown_count,
    u.last_shown, r.info
FROM records r LEFT JOIN usage u ON u.id = r.id
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
    busy REAL NOT NULL,
    bytes INTEGER,
    mtime_ns INTEGER,
    absent INTEGER NOT NULL DEFAULT 0
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
    :source_id, :thumbnail, :license, :author, :title, :info
)
"""
_INSERT_FILE = """
INSERT INTO files VALUES (
    :path, :record_id, :sha256, :is_default, :width, :height, :lightness, :chroma,
    :colourful_share, :hue, :hue_name, :hue_share, :hue_spread, :warmth, :busy, :bytes,
    :mtime_ns, :absent
)
"""
# The metric columns in Metrics field order, so that a row unpacks into Metrics.
_SELECT_FILES = """
SELECT f.path, f.record_id, r.purity, r.nsfw_root, f.is_default, f.width, f.height,
    r.thumbnail, f.absent, f.lightness, f.chroma, f.colourful_share, f.hue, f.hue_name, f.hue_share,
    f.hue_spread, f.warmth, f.busy
FROM files f JOIN records r ON r.id = f.record_id
{where}ORDER BY f.path
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
    # The record's thumbnail, if it has one.
    thumbnail: Path | None
    metrics: Metrics
    # Its git-annex content is not here: listed and measured, but not readable.
    absent: bool = False


def connect(path: Path) -> sqlite3.Connection:
    """Open the index, creating it (and its directory) if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Transactions are explicit, so that DDL in a rebuild is part of one.
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        version = _schema_version(conn, path)
        conn.execute("BEGIN")
        # Recreated below, after any upgrade: a view must not name a column being changed.
        conn.execute("DROP VIEW IF EXISTS pictures")
        if version == 1:
            # Schema 1 keyed usage by content hash; records are keyed by id now.
            logger.warning("%s: upgrading from schema 1; the usage history is discarded", path)
            conn.execute("DROP TABLE IF EXISTS images")
            conn.execute("DROP TABLE IF EXISTS usage")
        if version == 2 and _has_table(conn, "files"):
            # Schema 2 had no hash cache; the next `amo index` fills it in.
            conn.execute("ALTER TABLE files ADD COLUMN bytes INTEGER")
            conn.execute("ALTER TABLE files ADD COLUMN mtime_ns INTEGER")
        if version in (2, 3) and _has_table(conn, "records"):
            # No thumbnails before schema 4; the next `amo index` fills them in.
            conn.execute("ALTER TABLE records ADD COLUMN thumbnail TEXT")
        if version in (2, 3, 4) and _has_table(conn, "records"):
            # No provenance columns before schema 5; the next `amo index` fills them in.
            for column in ("license", "author", "title"):
                conn.execute(f"ALTER TABLE records ADD COLUMN {column} TEXT")
        if version in (2, 3, 4, 5) and _has_table(conn, "records"):
            # No info column before schema 6; the next `amo index` fills it in.
            conn.execute("ALTER TABLE records ADD COLUMN info TEXT")
        if version in (2, 3, 4, 5, 6) and _has_table(conn, "files"):
            # Absent annex content was not indexed before schema 7.
            conn.execute("ALTER TABLE files ADD COLUMN absent INTEGER NOT NULL DEFAULT 0")
        if not _has_table(conn, "records"):
            _create_tables(conn)
        conn.execute(_CREATE_USAGE)
        conn.execute(_CREATE_PICTURES)
        # PRAGMA takes no parameters; the value is a constant.
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.execute("COMMIT")
    except BaseException:
        conn.close()
        raise
    return conn


def _schema_version(conn: sqlite3.Connection, path: Path) -> int:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise IndexDatabaseError(
            f"{path} has schema {version}; this amontillado knows {SCHEMA_VERSION}"
        )
    return version


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


def add(conn: sqlite3.Connection, entry: Entry) -> None:
    """Add one record to the index, in one transaction."""
    conn.execute("BEGIN")
    try:
        _insert(conn, [entry])
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


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
        "thumbnail": _thumbnail(entry),
        "license": _text(source.get("license")),
        "author": _text(source.get("author")),
        "title": _text(source.get("title")),
        # Dates in an info file load as date or datetime objects.
        "info": json.dumps(entry.record.to_dict(), default=str, ensure_ascii=False),
    }


def _thumbnail(entry: Entry) -> str | None:
    thumbnail = entry.record.thumbnail
    if thumbnail is None or not (entry.directory / thumbnail).is_file():
        return None
    return str(entry.directory / thumbnail)


def _file_rows(entry: Entry) -> list[dict[str, object]]:
    rows = []
    for name in (*entry.present, *entry.absent):
        file = entry.record.files[name]
        assert file.metrics is not None
        size, mtime_ns = entry.stats.get(name, (None, None))
        rows.append(
            {
                "path": str(entry.directory / name),
                "record_id": entry.id,
                "sha256": file.sha256,
                "is_default": name == entry.default,
                "width": file.width,
                "height": file.height,
                **{key: getattr(file.metrics, key) for key in Metrics.__dataclass_fields__},
                "bytes": size,
                "mtime_ns": mtime_ns,
                "absent": name in entry.absent,
            }
        )
    return rows


def _text(value: object) -> str | None:
    # A hand-edited Wallhaven id of digits only would load as an int.
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return str(value)


def files(conn: sqlite3.Connection, record_id: str | None = None) -> list[IndexedFile]:
    """Every indexed file (or every file of the record `record_id`), by path."""
    if record_id is None:
        rows = conn.execute(_SELECT_FILES.format(where=""))
    else:
        rows = conn.execute(_SELECT_FILES.format(where="WHERE f.record_id = ?\n"), (record_id,))
    return [
        IndexedFile(
            path=Path(path),
            record_id=record_id,
            purity=purity,
            nsfw_root=bool(nsfw_root),
            is_default=bool(is_default),
            width=width,
            height=height,
            thumbnail=Path(thumbnail) if thumbnail is not None else None,
            metrics=Metrics(*metrics),
            absent=bool(absent),
        )
        for (
            path,
            record_id,
            purity,
            nsfw_root,
            is_default,
            width,
            height,
            thumbnail,
            absent,
            *metrics,
        ) in rows
    ]


def record_name(conn: sqlite3.Connection, record_id: str) -> str | None:
    """The name of the record `record_id`, if it has one."""
    row = conn.execute("SELECT name FROM records WHERE id = ?", (record_id,)).fetchone()
    return None if row is None else row[0]


def names(conn: sqlite3.Connection) -> set[str]:
    """The names records answer to."""
    return {name for (name,) in conn.execute("SELECT name FROM records WHERE name IS NOT NULL")}


def unnamed(conn: sqlite3.Connection, site: str) -> list[str]:
    """The ids of the indexed records fetched from `site` that answer to no name, in
    directory order."""
    query = "SELECT id FROM records WHERE source_site = ? AND name IS NULL ORDER BY directory"
    return [record_id for (record_id,) in conn.execute(query, (site,))]


def source_ids(conn: sqlite3.Connection, site: str) -> set[str]:
    """The ids, at `site`, of the indexed records fetched from it."""
    query = "SELECT source_id FROM records WHERE source_site = ? AND source_id IS NOT NULL"
    return {source_id for (source_id,) in conn.execute(query, (site,))}


def known_hashes(path: Path) -> dict[str, tuple[int, int, str]]:
    """Each indexed file's size, mtime (ns) and hash, by path, read from the index at `path`
    without changing it: empty when there is no index, or it predates the cache."""
    if not path.exists():
        return {}
    conn = sqlite3.connect(f"{path.absolute().as_uri()}?mode=ro", uri=True)
    try:
        version = _schema_version(conn, path)
        if version < 3 or not _has_table(conn, "files"):
            return {}
        query = (
            "SELECT path, bytes, mtime_ns, sha256 FROM files "
            "WHERE bytes IS NOT NULL AND mtime_ns IS NOT NULL"
        )
        return {row[0]: (row[1], row[2], row[3]) for row in conn.execute(query)}
    finally:
        conn.close()


def files_with_hash(conn: sqlite3.Connection, sha256: str) -> list[Path]:
    """The indexed files with this content, by path."""
    query = "SELECT path FROM files WHERE sha256 = ? ORDER BY path"
    return [Path(path) for (path,) in conn.execute(query, (sha256,))]


def replace(conn: sqlite3.Connection, entry: Entry) -> None:
    """Replace one record's rows with `entry`, in one transaction."""
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM files WHERE record_id = ?", (entry.id,))
        conn.execute("DELETE FROM records WHERE id = ?", (entry.id,))
        _insert(conn, [entry])
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


class QueryError(Exception):
    """An `amo list` filter cannot run; the message says why."""


# What a --where expression may do: read and call functions, nothing else.
_ALLOWED = frozenset({sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION})


def _authorize(action: int, *_: object) -> int:
    return sqlite3.SQLITE_OK if action in _ALLOWED else sqlite3.SQLITE_DENY


@dataclass(frozen=True)
class RecordFilter:
    """`amo list`'s filters over the `pictures` view; all must match."""

    # Each must be one of the record's tags.
    tags: tuple[str, ...] = ()
    site: str | None = None
    category: str | None = None
    # Case-insensitive (CC-BY-4.0 and cc-by-4.0 are one licence).
    license: str | None = None
    author: str | None = None
    # A SQL boolean expression over the view's columns.
    where: str | None = None

    def __bool__(self) -> bool:
        return self != RecordFilter()


def matching_records(conn: sqlite3.Connection, search: RecordFilter) -> set[str]:
    """The ids of the records `search` matches. The --where expression runs with the database
    read-only and an authorizer that allows only reads and function calls, in one statement.
    It can select any record: purity and the NSFW root are for the caller to apply after.
    Raises QueryError."""
    clauses, parameters = [], []
    for tag in search.tags:
        clauses.append("EXISTS (SELECT 1 FROM json_each(tags) WHERE value = ?)")
        parameters.append(tag)
    for column, value in (
        ("site", search.site),
        ("category", search.category),
        ("author", search.author),
    ):
        if value is not None:
            clauses.append(f"{column} = ?")
            parameters.append(value)
    if search.license is not None:
        clauses.append("license = ? COLLATE NOCASE")
        parameters.append(search.license)
    if search.where is not None:
        # On its own lines, so a trailing comment in it cannot swallow our parenthesis.
        clauses.append(f"(\n{search.where}\n)")
    query = "SELECT id FROM pictures WHERE " + " AND ".join(clauses or ["1"])
    conn.execute("PRAGMA query_only = ON")
    conn.set_authorizer(_authorize)
    try:
        return {record_id for (record_id,) in conn.execute(query, parameters)}
    except (sqlite3.DatabaseError, sqlite3.ProgrammingError, sqlite3.Warning) as exc:
        raise QueryError(_query_message(search.where, exc)) from exc
    finally:
        conn.set_authorizer(None)
        conn.execute("PRAGMA query_only = OFF")


def _query_message(where: str | None, exc: Exception) -> str:
    message = f"--where: {exc}"
    if where is not None and "->" in where and sqlite3.sqlite_version_info < JSON_ARROWS:
        message += (
            f" (this SQLite is {sqlite3.sqlite_version}; -> and ->> need 3.38: use "
            "json_extract(info, '$.path'))"
        )
    return message


def record_location(conn: sqlite3.Connection, record_id: str) -> tuple[Path, Path]:
    """The directory and root of an indexed record; LookupFailed if it is not indexed."""
    row = conn.execute("SELECT directory, root FROM records WHERE id = ?", (record_id,)).fetchone()
    if row is None:
        raise LookupFailed(f"{record_id}: not in the index; run `amo index`")
    return Path(row[0]), Path(row[1])


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


def usage(conn: sqlite3.Connection) -> dict[str, tuple[int, str]]:
    """Each shown record's `(shown_count, last_shown)`, by record id; none if never shown."""
    rows = conn.execute("SELECT id, shown_count, last_shown FROM usage")
    return {record_id: (count, last) for record_id, count, last in rows}


def record_shown(conn: sqlite3.Connection, record_id: str, when: datetime | None = None) -> None:
    """Count one showing of the record with `record_id`, at `when` (default now, UTC)."""
    when = when or datetime.now(UTC)
    conn.execute("BEGIN")
    try:
        conn.execute(_RECORD_SHOWN, (record_id, when.isoformat(timespec="seconds")))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
