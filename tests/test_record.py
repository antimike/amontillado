from __future__ import annotations

import dataclasses
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from amontillado import yamlio
from amontillado.metrics import METRICS_VERSION, Metrics
from amontillado.record import (
    FileEntry,
    Record,
    RecordError,
    info_path,
    load_raw,
    parse,
    read_record,
    sha256_file,
    write_record,
)

METRICS = Metrics(0.31, 0.042, 0.38, 262.0, "blue", 0.71, 0.18, 0.12, 0.06)
SHA = "ab" * 32
RECORD_ID = "3f2a9c1e0b7d4e8f9a6b5c4d3e2f1a0b"


def _record() -> Record:
    return Record(
        id=RECORD_ID,
        name="night-city",
        source={"site": "wallhaven", "id": "abc123", "purity": "sfw"},
        fetched=datetime(2026, 10, 27, 18, 0, tzinfo=UTC),
        files={
            "night-city.png": FileEntry(SHA, 3840, 2160, METRICS),
            "night-city-21x9.png": FileEntry(
                "cd" * 32, 3840, 1646, METRICS, "night-city.png", (0, 257, 3840, 1646)
            ),
        },
    )


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "info.yaml"
    write_record(path, _record())
    assert read_record(path) == _record()
    data = yamlio.load(path.read_text())
    assert list(data) == ["schema", "id", "name", "source", "fetched", "files"]
    crop = data["files"]["night-city-21x9.png"]
    assert list(crop) == ["sha256", "width", "height", "derived_from", "crop", "metrics"]
    assert crop["crop"] == [0, 257, 3840, 1646]
    assert list(tmp_path.iterdir()) == [path]


def test_unchanged_record_writes_the_same_text(tmp_path: Path) -> None:
    path = tmp_path / "info.yaml"
    write_record(path, _record())
    text = path.read_text()
    assert "source:\n  site: wallhaven\n" in text
    assert "fetched: 2026-10-27 18:00:00+00:00\n" in text
    write_record(path, read_record(path))
    assert path.read_text() == text


def test_null_is_spelt_out(tmp_path: Path) -> None:
    path = tmp_path / "info.yaml"
    write_record(path, Record(id=RECORD_ID, files={"a.png": FileEntry()}))
    assert "source: null\nfetched: null\n" in path.read_text()
    assert "    metrics: null\n" in path.read_text()


HAND_WRITTEN = f"""\
# A picture from a friend; keep it.
id: {RECORD_ID}   # never change this
schema: 2
source:
  site: local
  tags: [harbour, morning]   # flow style, as typed
rating: 5
files:
  a.png:
    sha256: {SHA}
    width: 3840
    height: 2160
    note: the original    # by hand
"""


def test_write_changes_only_changed_keys(tmp_path: Path) -> None:
    path = tmp_path / "info.yaml"
    path.write_text(HAND_WRITTEN)
    record = read_record(path)
    entry = dataclasses.replace(record.files["a.png"], metrics=METRICS)
    write_record(path, dataclasses.replace(record, name="harbour", files={"a.png": entry}))
    text = path.read_text()
    # Comments, key order, flow style and unknown keys stay; a new key goes after the key
    # that precedes it in the record.
    assert text.startswith(
        f"# A picture from a friend; keep it.\nid: {RECORD_ID}   # never change this\n"
        "name: harbour\nschema: 2\nsource:\n"
    )
    assert "  tags: [harbour, morning]   # flow style, as typed\nfetched: null\nrating: 5\n" in text
    assert "    height: 2160\n    metrics:\n      version:" in text
    assert text.endswith("      busy: 0.06\n    note: the original    # by hand\n")
    assert read_record(path).files["a.png"].metrics == METRICS


def test_write_removes_keys_the_record_dropped(tmp_path: Path) -> None:
    path = tmp_path / "info.yaml"
    path.write_text(HAND_WRITTEN)
    record = read_record(path)
    write_record(path, dataclasses.replace(record, extra={}, source=None))
    text = path.read_text()
    assert "rating" not in text and "harbour" not in text
    assert "# A picture from a friend; keep it.\n" in text
    assert read_record(path).source is None


def test_a_value_of_another_type_is_rewritten(tmp_path: Path) -> None:
    # 2160 == 2160.0 in Python; the file must still say what the record holds.
    path = tmp_path / "info.yaml"
    path.write_text(HAND_WRITTEN.replace("height: 2160", "height: 2160.0"))
    record = read_record(path)
    assert record.files["a.png"].height is None  # invalid: to be recomputed
    entry = dataclasses.replace(record.files["a.png"], height=2160)
    write_record(path, dataclasses.replace(record, files={"a.png": entry}))
    assert "    height: 2160\n" in path.read_text()


def test_unknown_keys_are_kept(tmp_path: Path) -> None:
    data = _record().to_dict()
    data["rating"] = 5
    data["files"]["night-city.png"]["note"] = "from a friend"
    record = parse(data)
    assert record.extra == {"rating": 5}
    assert record.files["night-city.png"].extra == {"note": "from a friend"}
    assert record.to_dict() == data


def test_empty_file_is_a_new_record(tmp_path: Path) -> None:
    path = tmp_path / "info.yaml"
    path.write_text("")
    assert read_record(path) == Record(id=None)


def test_hand_listed_file_without_fields(tmp_path: Path) -> None:
    record = parse({"files": {"a.png": None}})
    assert record.files == {"a.png": FileEntry()}
    assert not record.files["a.png"].complete


def test_duplicate_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "info.yaml"
    path.write_text("files:\n  a.png: {width: 1}\n  a.png: {width: 2}\n")
    with pytest.raises(RecordError, match=r"duplicate key 'a\.png'"):
        load_raw(path)


def test_merge_keys_still_load(tmp_path: Path) -> None:
    path = tmp_path / "info.yaml"
    path.write_text("base: &b {x: 1}\nother:\n  <<: *b\n  y: 2\n")
    assert load_raw(path)["other"] == {"x": 1, "y": 2}


def test_not_a_mapping(tmp_path: Path) -> None:
    path = tmp_path / "info.yaml"
    path.write_text("- a\n")
    with pytest.raises(RecordError, match="not a YAML mapping"):
        load_raw(path)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"schema": 1}, "schema is 1"),
        ({"id": "sha256:abc"}, "id is not"),
        ({"name": "Night City"}, "name 'Night City'"),
        ({"source": "wallhaven"}, "source is not a mapping"),
        ({"fetched": "yesterday"}, "fetched is not a timestamp"),
        ({"files": ["a.png"]}, "files is not a mapping"),
        ({"files": {"../a.png": {}}}, "not the plain name of an image"),
        ({"files": {"notes.txt": {}}}, "not the plain name of an image"),
        ({"files": {"a.png": {"derived_from": "b.png"}}}, "derived_from names no other"),
        ({"files": {"a.png": {"derived_from": "a.png"}}}, "derived_from names no other"),
        ({"files": {"a.png": {"crop": [0, 0, 0, 10]}}}, "crop is not"),
        ({"files": {"a.png": {}}, "default_file": "b.png"}, "default_file 'b.png'"),
    ],
)
def test_invalid_authored_fields(change: dict[str, object], message: str) -> None:
    with pytest.raises(RecordError, match=re.escape(message)):
        parse({"id": RECORD_ID, **change})


def test_thumbnail_round_trips_after_default_file(tmp_path: Path) -> None:
    path = tmp_path / "info.yaml"
    record = dataclasses.replace(_record(), default_file="night-city.png", thumbnail=".amo/t.jpg")
    write_record(path, record)
    assert read_record(path) == record
    data = yamlio.load(path.read_text())
    assert list(data)[:5] == ["schema", "id", "name", "default_file", "thumbnail"]
    assert record.extra == {}


@pytest.mark.parametrize(
    "value", [5, "", "/etc/thumb.jpg", "../other/t.jpg", ".amo/../t.jpg", "a//t.jpg", "a\\t.jpg"]
)
def test_a_thumbnail_outside_the_record_is_left_for_recomputation(value: object) -> None:
    assert parse({"thumbnail": value}).thumbnail is None


def test_invalid_derived_fields_are_left_for_recomputation() -> None:
    record = parse(
        {
            "files": {
                "a.png": {
                    "sha256": "sha256:" + SHA,
                    "width": True,
                    "height": -1,
                    "metrics": {**METRICS.to_dict(), "version": METRICS_VERSION - 1},
                }
            }
        }
    )
    assert record.files["a.png"] == FileEntry()


def test_default_file() -> None:
    record = _record()
    present = set(record.files)
    assert record.default(present) == "night-city.png"
    # Only the crop is present: a derived file is better than none.
    assert record.default({"night-city-21x9.png"}) == "night-city-21x9.png"
    files = {
        "b.png": FileEntry(SHA, 100, 100, METRICS),
        "a.png": FileEntry(SHA, 100, 100, METRICS),
        "small.png": FileEntry(SHA, 10, 10, METRICS),
    }
    assert Record(RECORD_ID, files=files).default(set(files)) == "a.png"
    chosen = Record(RECORD_ID, default_file="small.png", files=files)
    assert chosen.default(set(files)) == "small.png"
    assert chosen.default({"a.png", "b.png"}) == "a.png"
    assert Record(RECORD_ID).default(set()) is None


def test_info_path(tmp_path: Path) -> None:
    assert info_path(tmp_path) is None
    (tmp_path / "info.yml").write_text("")
    assert info_path(tmp_path) == tmp_path / "info.yml"
    (tmp_path / "info.yaml").write_text("")
    with pytest.raises(RecordError, match="both"):
        info_path(tmp_path)


def test_sha256_file(tmp_path: Path) -> None:
    path = tmp_path / "a"
    path.write_bytes(b"abc")
    assert sha256_file(path) == ("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
