from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from conftest import SaveImage, mark_record

from amontillado.config import Config
from amontillado.index import (
    SCHEMA_VERSION,
    IndexDatabaseError,
    LookupFailed,
    connect,
    files,
    find_record,
    rebuild,
    record_shown,
)
from amontillado.library import heal_library
from amontillado.metrics import Metrics


def test_connect_creates_the_database(config: Config) -> None:
    conn = connect(config.index_path)
    assert config.index_path.is_file()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert files(conn) == []


def test_newer_schema_is_refused(config: Config) -> None:
    config.index_path.parent.mkdir(parents=True)
    with sqlite3.connect(config.index_path) as conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(IndexDatabaseError, match="schema"):
        connect(config.index_path)


def test_schema_1_is_upgraded_and_its_usage_discarded(
    config: Config, caplog: pytest.LogCaptureFixture
) -> None:
    config.index_path.parent.mkdir(parents=True)
    with sqlite3.connect(config.index_path) as conn:
        conn.execute("CREATE TABLE images (path TEXT)")
        conn.execute("CREATE TABLE usage (id TEXT, shown_count INTEGER, last_shown TEXT)")
        conn.execute("INSERT INTO usage VALUES ('sha256:aa', 1, '2026-10-27')")
        conn.execute("PRAGMA user_version = 1")
    conn = connect(config.index_path)
    assert _usage(conn) == []
    assert files(conn) == []
    assert "usage history is discarded" in caplog.text


def _two_records(config: Config, save_image: SaveImage) -> tuple[Path, Path]:
    red = mark_record(config.library_roots[0] / "red").parent
    save_image(red / "big.png", (255, 0, 0), (64, 36))
    save_image(red / "small.png", (255, 0, 0), (32, 18))
    grey = mark_record(config.nsfw_root / "grey").parent
    save_image(grey / "a.png", (128, 128, 128))
    return red, grey


def test_rebuild_from_records(config: Config, save_image: SaveImage) -> None:
    red, grey = _two_records(config, save_image)
    report = heal_library(config)
    conn = connect(config.index_path)
    assert rebuild(conn, report.entries) == 2

    rows = {row.path: row for row in files(conn)}
    assert set(rows) == {red / "big.png", red / "small.png", grey / "a.png"}
    by_dir = {entry.directory: entry for entry in report.entries}
    assert rows[red / "big.png"].metrics == by_dir[red].record.files["big.png"].metrics
    assert rows[red / "big.png"].record_id == by_dir[red].id
    assert (rows[red / "big.png"].is_default, rows[red / "small.png"].is_default) == (True, False)
    assert (rows[red / "small.png"].width, rows[red / "small.png"].height) == (32, 18)
    assert (rows[red / "big.png"].purity, rows[red / "big.png"].nsfw_root) == ("sfw", False)
    assert (rows[grey / "a.png"].purity, rows[grey / "a.png"].nsfw_root) == ("nsfw", True)
    assert rows[grey / "a.png"].metrics.hue is None


def test_rebuild_replaces_every_row(config: Config, save_image: SaveImage) -> None:
    info = mark_record(config.library_roots[0] / "r")
    save_image(info.parent / "a.png")
    conn = connect(config.index_path)
    rebuild(conn, heal_library(config).entries)
    (info.parent / "a.png").unlink()
    rebuild(conn, heal_library(config).entries)
    assert files(conn) == []


def test_source_fields(config: Config, save_image: SaveImage) -> None:
    save_image(mark_record(config.library_roots[0] / "r").parent / "a.png")
    entry = heal_library(config).entries[0]
    source = {"site": "wallhaven", "id": 123456, "category": "anime", "tags": ["night", 7]}
    entry = replace(entry, record=replace(entry.record, source=source), name="night")
    conn = connect(config.index_path)
    rebuild(conn, [entry])
    row = conn.execute(
        "SELECT name, category, tags, source_site, source_id FROM records"
    ).fetchone()
    assert row[:2] == ("night", "anime")
    assert json.loads(row[2]) == ["night", "7"]
    assert row[3:] == ("wallhaven", "123456")


def test_failed_rebuild_keeps_the_old_rows(config: Config, save_image: SaveImage) -> None:
    save_image(mark_record(config.library_roots[0] / "r").parent / "a.png")
    entries = heal_library(config).entries
    conn = connect(config.index_path)
    rebuild(conn, entries)
    with pytest.raises(sqlite3.IntegrityError):
        rebuild(conn, entries * 2)  # the same record twice
    assert len(files(conn)) == 1


def test_metric_columns_follow_the_dataclass(config: Config) -> None:
    conn = connect(config.index_path)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(files)")]
    metric_columns = columns[columns.index("lightness") :]
    assert metric_columns == list(Metrics.__dataclass_fields__)


@pytest.fixture
def indexed(config: Config, save_image: SaveImage) -> tuple[sqlite3.Connection, dict[str, str]]:
    """Two records, one named; returns the connection and the ids by directory name."""
    _two_records(config, save_image)
    (config.library_roots[0] / "red" / "info.yaml").write_text("name: night-city\n")
    entries = heal_library(config).entries
    conn = connect(config.index_path)
    rebuild(conn, entries)
    return conn, {entry.directory.name: entry.id for entry in entries}


def test_find_record_by_name_id_and_prefix(
    indexed: tuple[sqlite3.Connection, dict[str, str]],
) -> None:
    conn, ids = indexed
    assert find_record(conn, "night-city") == ids["red"]
    assert find_record(conn, ids["grey"]) == ids["grey"]
    prefix = next(
        ids["grey"][:n] for n in range(1, 33) if not ids["red"].startswith(ids["grey"][:n])
    )
    assert find_record(conn, prefix) == ids["grey"]
    with pytest.raises(LookupFailed, match="no record has that name or id"):
        find_record(conn, "nothing")


def test_find_record_by_ambiguous_prefix(config: Config, save_image: SaveImage) -> None:
    root = config.library_roots[0]
    for name, record_id in (("a", "ab" + "0" * 30), ("b", "ab" + "1" * 30)):
        info = mark_record(root / name)
        info.write_text(f"id: {record_id}\n")
        save_image(info.parent / "x.png", (int(name == "b"), 0, 0))
    conn = connect(config.index_path)
    rebuild(conn, heal_library(config).entries)
    with pytest.raises(LookupFailed, match="more than one"):
        find_record(conn, "ab")
    assert find_record(conn, "ab1") == "ab" + "1" * 30


def test_find_record_by_path(
    config: Config, indexed: tuple[sqlite3.Connection, dict[str, str]], tmp_path: Path
) -> None:
    conn, ids = indexed
    red = config.library_roots[0] / "red"
    assert find_record(conn, str(red / "small.png")) == ids["red"]
    assert find_record(conn, str(red)) == ids["red"]
    # Moved since the last index: found by content.
    moved = (red / "small.png").rename(tmp_path / "moved.png")
    assert find_record(conn, str(moved)) == ids["red"]
    stranger = tmp_path / "stranger.png"
    stranger.write_bytes(b"other")
    with pytest.raises(LookupFailed, match="not in the index"):
        find_record(conn, str(stranger))


def _usage(conn: sqlite3.Connection) -> list[tuple[str, int, str]]:
    return conn.execute("SELECT id, shown_count, last_shown FROM usage").fetchall()


def test_record_shown_counts_and_keeps_the_latest(config: Config) -> None:
    conn = connect(config.index_path)
    record_shown(conn, "aa", datetime(2026, 10, 27, 18, 0, tzinfo=timezone.utc))
    record_shown(conn, "aa", datetime(2026, 10, 28, 9, 30, tzinfo=timezone.utc))
    record_shown(conn, "bb", datetime(2026, 10, 28, 9, 31, tzinfo=timezone.utc))
    assert sorted(_usage(conn)) == [
        ("aa", 2, "2026-10-28T09:30:00+00:00"),
        ("bb", 1, "2026-10-28T09:31:00+00:00"),
    ]


def test_record_shown_defaults_to_now(config: Config) -> None:
    conn = connect(config.index_path)
    before = datetime.now(timezone.utc).replace(microsecond=0)
    record_shown(conn, "aa")
    assert datetime.fromisoformat(_usage(conn)[0][2]) >= before


def test_usage_survives_rebuild_and_reconnect(config: Config, save_image: SaveImage) -> None:
    save_image(mark_record(config.library_roots[0] / "r").parent / "a.png")
    conn = connect(config.index_path)
    record_shown(conn, "aa")
    rebuild(conn, heal_library(config).entries)
    conn.close()
    assert len(_usage(connect(config.index_path))) == 1
