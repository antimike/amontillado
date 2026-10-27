from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from conftest import SaveImage

from amontillado.config import Config
from amontillado.index import (
    SCHEMA_VERSION,
    IndexDatabaseError,
    connect,
    images,
    rebuild,
    record_shown,
)
from amontillado.library import heal_library
from amontillado.metrics import Metrics


def test_connect_creates_the_database(config: Config) -> None:
    conn = connect(config.index_path)
    assert config.index_path.is_file()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert images(conn) == []


def test_newer_schema_is_refused(config: Config) -> None:
    config.index_path.parent.mkdir(parents=True)
    with sqlite3.connect(config.index_path) as conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(IndexDatabaseError, match="schema"):
        connect(config.index_path)


def test_rebuild_from_sidecars(config: Config, save_image: SaveImage) -> None:
    red = save_image(config.library_roots[0] / "red.png", (255, 0, 0))
    grey = save_image(config.nsfw_root / "grey.png", (128, 128, 128))
    report = heal_library(config)
    conn = connect(config.index_path)
    assert rebuild(conn, report.entries) == 2

    rows = {image.path: image for image in images(conn)}
    assert set(rows) == {red, grey}
    by_path = {entry.path: entry for entry in report.entries}
    assert rows[red].metrics == by_path[red].sidecar.metrics
    assert rows[red].id == by_path[red].sidecar.id
    assert (rows[red].purity, rows[red].nsfw_root) == ("sfw", False)
    assert (rows[grey].purity, rows[grey].nsfw_root) == ("nsfw", True)
    assert rows[grey].metrics.hue is None


def test_rebuild_replaces_every_row(config: Config, save_image: SaveImage) -> None:
    save_image(config.library_roots[0] / "a.png")
    conn = connect(config.index_path)
    rebuild(conn, heal_library(config).entries)
    (config.library_roots[0] / "a.png").unlink()
    rebuild(conn, heal_library(config).entries)
    assert images(conn) == []


def test_source_fields(config: Config, save_image: SaveImage) -> None:
    save_image(config.library_roots[0] / "wallhaven-123456.png")
    entry = heal_library(config).entries[0]
    source = {"site": "wallhaven", "id": 123456, "category": "anime", "tags": ["night", 7]}
    entry = replace(entry, sidecar=replace(entry.sidecar, source=source))
    conn = connect(config.index_path)
    rebuild(conn, [entry])
    row = conn.execute("SELECT category, tags, source_site, source_id FROM images").fetchone()
    assert row[0] == "anime"
    assert json.loads(row[1]) == ["night", "7"]
    assert row[2:] == ("wallhaven", "123456")


def test_failed_rebuild_keeps_the_old_rows(config: Config, save_image: SaveImage) -> None:
    save_image(config.library_roots[0] / "a.png")
    entries = heal_library(config).entries
    conn = connect(config.index_path)
    rebuild(conn, entries)
    with pytest.raises(sqlite3.IntegrityError):
        rebuild(conn, entries * 2)  # the same path twice
    assert len(images(conn)) == 1


def test_metric_columns_follow_the_dataclass(config: Config) -> None:
    conn = connect(config.index_path)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(images)")]
    metric_columns = columns[columns.index("lightness") :]
    assert metric_columns == list(Metrics.__dataclass_fields__)


def _usage(conn: sqlite3.Connection) -> list[tuple[str, int, str]]:
    return conn.execute("SELECT id, shown_count, last_shown FROM usage").fetchall()


def test_record_shown_counts_and_keeps_the_latest(config: Config) -> None:
    conn = connect(config.index_path)
    record_shown(conn, "sha256:aa", datetime(2026, 10, 27, 18, 0, tzinfo=timezone.utc))
    record_shown(conn, "sha256:aa", datetime(2026, 10, 28, 9, 30, tzinfo=timezone.utc))
    record_shown(conn, "sha256:bb", datetime(2026, 10, 28, 9, 31, tzinfo=timezone.utc))
    assert sorted(_usage(conn)) == [
        ("sha256:aa", 2, "2026-10-28T09:30:00+00:00"),
        ("sha256:bb", 1, "2026-10-28T09:31:00+00:00"),
    ]


def test_record_shown_defaults_to_now(config: Config) -> None:
    conn = connect(config.index_path)
    before = datetime.now(timezone.utc).replace(microsecond=0)
    record_shown(conn, "sha256:aa")
    assert datetime.fromisoformat(_usage(conn)[0][2]) >= before


def test_usage_survives_rebuild_and_reconnect(config: Config, save_image: SaveImage) -> None:
    save_image(config.library_roots[0] / "a.png")
    conn = connect(config.index_path)
    record_shown(conn, "sha256:aa")
    rebuild(conn, heal_library(config).entries)
    conn.close()
    assert len(_usage(connect(config.index_path))) == 1
