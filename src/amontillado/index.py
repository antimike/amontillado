"""The SQLite index: one row per image, rebuilt from the sidecars, and the usage history.

docs/design.md, "Index and usage". The `images` table holds nothing that is not in a sidecar
(or implied by where the image lives), so `rebuild` drops and recreates it: a schema change to
it needs no migration. The `usage` table cannot be rebuilt and is never dropped.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from amontillado.library import Entry
from amontillado.metrics import Metrics

SCHEMA_VERSION = 1

_CREATE_IMAGES = """
CREATE TABLE images (
    path TEXT PRIMARY KEY,
    id TEXT NOT NULL,
    root TEXT NOT NULL,
    nsfw_root INTEGER NOT NULL,
    purity TEXT NOT NULL,
    category TEXT,
    tags TEXT NOT NULL,
    source_site TEXT,
    source_id TEXT,
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
_INSERT_IMAGE = """
INSERT INTO images VALUES (
    :path, :id, :root, :nsfw_root, :purity, :category, :tags, :source_site, :source_id,
    :width, :height, :lightness, :chroma, :colourful_share, :hue, :hue_name, :hue_share,
    :hue_spread, :warmth, :busy
)
"""
# The metric columns in Metrics field order, so that a row unpacks into Metrics.
_SELECT_IMAGES = """
SELECT path, id, purity, nsfw_root,
    lightness, chroma, colourful_share, hue, hue_name, hue_share, hue_spread, warmth, busy
FROM images ORDER BY path
"""


class IndexDatabaseError(Exception):
    """The index cannot be used; the message says why."""


@dataclass(frozen=True)
class IndexedImage:
    """An image as the index knows it."""

    path: Path
    id: str
    purity: str
    nsfw_root: bool
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
        if not _has_table(conn, "images"):
            conn.execute(_CREATE_IMAGES)
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


def rebuild(conn: sqlite3.Connection, entries: Iterable[Entry]) -> int:
    """Replace the images table with `entries`, in one transaction; returns the row count."""
    rows = [_row(entry) for entry in entries]
    conn.execute("BEGIN")
    try:
        conn.execute("DROP TABLE IF EXISTS images")
        conn.execute(_CREATE_IMAGES)
        conn.executemany(_INSERT_IMAGE, rows)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return len(rows)


def _row(entry: Entry) -> dict[str, object]:
    source = entry.sidecar.source or {}
    tags = source.get("tags")
    tags = [str(tag) for tag in tags] if isinstance(tags, list) else []
    return {
        "path": str(entry.path),
        "id": entry.sidecar.id,
        "root": str(entry.root),
        "nsfw_root": entry.nsfw_root,
        "purity": entry.purity,
        "category": _text(source.get("category")),
        "tags": json.dumps(tags),
        "source_site": _text(source.get("site")),
        "source_id": _text(source.get("id")),
        "width": entry.sidecar.width,
        "height": entry.sidecar.height,
        **{name: getattr(entry.sidecar.metrics, name) for name in Metrics.__dataclass_fields__},
    }


def _text(value: object) -> str | None:
    # A hand-edited Wallhaven id of digits only would load as an int.
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return str(value)


def images(conn: sqlite3.Connection) -> list[IndexedImage]:
    """Every indexed image, by path."""
    return [
        IndexedImage(
            path=Path(path),
            id=image_id,
            purity=purity,
            nsfw_root=bool(nsfw_root),
            metrics=Metrics(*metrics),
        )
        for path, image_id, purity, nsfw_root, *metrics in conn.execute(_SELECT_IMAGES)
    ]


def record_shown(conn: sqlite3.Connection, image_id: str, when: datetime | None = None) -> None:
    """Count one showing of the image with `image_id`, at `when` (default now, UTC)."""
    when = when or datetime.now(timezone.utc)
    conn.execute("BEGIN")
    try:
        conn.execute(_RECORD_SHOWN, (image_id, when.isoformat(timespec="seconds")))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
