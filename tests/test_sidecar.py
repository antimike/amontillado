from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from amontillado.metrics import METRICS_VERSION, Metrics
from amontillado.sidecar import (
    Sidecar,
    SidecarError,
    content_id,
    load_raw,
    parse,
    read_sidecar,
    sidecar_path,
    write_sidecar,
)

METRICS = Metrics(
    lightness=0.31,
    chroma=0.042,
    colourful_share=0.38,
    hue=262.0,
    hue_name="blue",
    hue_share=0.71,
    hue_spread=0.18,
    warmth=-0.12,
    busy=0.06,
)
SIDECAR = Sidecar(
    id="sha256:" + "0" * 64,
    file="wallhaven-abc123.jpg",
    width=3840,
    height=2160,
    source={"site": "wallhaven", "id": "abc123", "purity": "sfw", "tags": ["night"]},
    fetched=datetime(2026, 10, 27, 18, 0, tzinfo=timezone.utc),
    metrics=METRICS,
)


def test_sidecar_path() -> None:
    assert sidecar_path(Path("/w/wallhaven-abc123.jpg")) == Path("/w/wallhaven-abc123.yaml")


def test_content_id(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"x" * 3_000_000)
    assert content_id(path) == "sha256:" + hashlib.sha256(b"x" * 3_000_000).hexdigest()


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "wallhaven-abc123.yaml"
    write_sidecar(path, SIDECAR)
    assert read_sidecar(path) == SIDECAR
    assert list(tmp_path.iterdir()) == [path]  # no temporary file left behind


def test_written_in_schema_order(tmp_path: Path) -> None:
    path = tmp_path / "a.yaml"
    write_sidecar(path, SIDECAR)
    data = yaml.safe_load(path.read_text())
    assert list(data) == ["schema", "id", "file", "width", "height", "source", "fetched", "metrics"]
    assert data["metrics"]["version"] == METRICS_VERSION


def test_hand_added_image_has_no_source(tmp_path: Path) -> None:
    path = tmp_path / "a.yaml"
    sidecar = Sidecar(SIDECAR.id, "a.png", 10, 10, None, None, METRICS)
    write_sidecar(path, sidecar)
    assert read_sidecar(path) == sidecar


def test_write_replaces_existing(tmp_path: Path) -> None:
    path = tmp_path / "a.yaml"
    path.write_text("old")
    write_sidecar(path, SIDECAR)
    assert read_sidecar(path) == SIDECAR


@pytest.mark.parametrize(("text", "message"), [("a: [", "not valid YAML"), ("- a\n", "mapping")])
def test_load_raw_rejects(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "a.yaml"
    path.write_text(text)
    with pytest.raises(SidecarError, match=message):
        load_raw(path)


def _broken(**changes: object) -> dict[str, object]:
    data = yaml.safe_load(yaml.safe_dump(SIDECAR.to_dict()))
    for key, value in changes.items():
        if value is None:
            del data[key]
        else:
            data[key] = value
    return data


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (_broken(schema=2), "schema is 2"),
        (_broken(id="abc"), "id is missing"),
        (_broken(file=None), "file is missing"),
        (_broken(width=True), "width is missing"),
        (_broken(height=0), "height is missing"),
        (_broken(source=["x"]), "source is not a mapping"),
        (_broken(fetched="yesterday"), "fetched is not a timestamp"),
        (_broken(metrics=None), "metrics are missing"),
        (_broken(metrics={**METRICS.to_dict(), "version": 0}), "metrics version is 0"),
        (_broken(metrics={**METRICS.to_dict(), "busy": "high"}), r"metrics\.busy"),
        (_broken(metrics={**METRICS.to_dict(), "hue_name": "teal"}), r"metrics\.hue_name"),
    ],
)
def test_parse_rejects(data: dict[str, object], message: str) -> None:
    with pytest.raises(SidecarError, match=message):
        parse(data)
