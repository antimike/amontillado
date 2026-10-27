from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

import pytest
from conftest import SaveImage

from amontillado.config import Config
from amontillado.index import (
    SCHEMA_VERSION,
    IndexDatabaseError,
    connect,
    images,
    rebuild,
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
