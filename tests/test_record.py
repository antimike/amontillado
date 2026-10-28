from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

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
        fetched=datetime(2026, 10, 27, 18, 0, tzinfo=timezone.utc),
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
    data = yaml.safe_load(path.read_text())
    assert list(data) == ["schema", "id", "name", "source", "fetched", "files"]
    crop = data["files"]["night-city-21x9.png"]
    assert list(crop) == ["sha256", "width", "height", "derived_from", "crop", "metrics"]
    assert crop["crop"] == [0, 257, 3840, 1646]
    assert list(tmp_path.iterdir()) == [path]


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
