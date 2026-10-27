from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml
from conftest import SaveImage

from amontillado import library
from amontillado.config import Config
from amontillado.library import heal_library
from amontillado.metrics import METRICS_VERSION
from amontillado.sidecar import content_id, read_sidecar


def test_image_without_sidecar_gets_one(config: Config, save_image: SaveImage) -> None:
    image = save_image(config.library_roots[0] / "sub" / "a.png", (255, 0, 0), (80, 40))
    report = heal_library(config)
    sidecar = read_sidecar(image.with_suffix(".yaml"))
    assert sidecar.id == content_id(image)
    assert (sidecar.file, sidecar.width, sidecar.height) == ("a.png", 80, 40)
    assert sidecar.source is None
    assert sidecar.metrics.hue_name == "red"
    assert report.healed == [(image.with_suffix(".yaml"), "no sidecar")]
    assert [entry.path for entry in report.entries] == [image]
    assert not report.clean


def test_second_pass_is_clean(config: Config, save_image: SaveImage) -> None:
    save_image(config.library_roots[0] / "a.png")
    heal_library(config)
    report = heal_library(config)
    assert report.clean
    assert len(report.entries) == 1


def test_check_writes_nothing(config: Config, save_image: SaveImage) -> None:
    image = save_image(config.library_roots[0] / "a.png")
    report = heal_library(config, check=True)
    assert report.healed == [(image.with_suffix(".yaml"), "no sidecar")]
    assert report.entries == []
    assert not image.with_suffix(".yaml").exists()


def test_unparseable_sidecar_is_kept_aside(config: Config, save_image: SaveImage) -> None:
    image = save_image(config.library_roots[0] / "a.png")
    sidecar = image.with_suffix(".yaml")
    sidecar.write_text("source: [unclosed\n")
    report = heal_library(config)
    assert report.healed[0][1].startswith("not valid YAML")
    assert (config.library_roots[0] / "a.yaml.bad").read_text() == "source: [unclosed\n"
    assert read_sidecar(sidecar).id == content_id(image)


def test_old_metrics_are_recomputed_and_source_kept(config: Config, save_image: SaveImage) -> None:
    image = save_image(config.library_roots[0] / "wallhaven-abc123.png")
    heal_library(config)
    path = image.with_suffix(".yaml")
    data = yaml.safe_load(path.read_text())
    data["metrics"] = {"version": METRICS_VERSION - 1, "lightness": 0.9}
    data["source"] = {"site": "wallhaven", "id": "abc123", "purity": "sfw"}
    path.write_text(yaml.safe_dump(data))
    report = heal_library(config)
    assert "metrics version" in report.healed[0][1]
    sidecar = read_sidecar(path)
    assert sidecar.metrics.lightness == pytest.approx(0.0, abs=1e-3)
    assert sidecar.source == {"site": "wallhaven", "id": "abc123", "purity": "sfw"}


def test_changed_content_is_measured_again(config: Config, save_image: SaveImage) -> None:
    image = save_image(config.library_roots[0] / "a.png", (255, 0, 0))
    heal_library(config)
    save_image(image, (0, 0, 255))
    report = heal_library(config)
    assert report.healed[0][1] == "content changed"
    sidecar = read_sidecar(image.with_suffix(".yaml"))
    assert sidecar.id == content_id(image)
    assert sidecar.metrics.hue_name == "blue"


def test_rename_updates_file_without_measuring(
    config: Config, save_image: SaveImage, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = config.library_roots[0]
    save_image(root / "a.png")
    heal_library(config)
    (root / "a.png").rename(root / "b.png")
    (root / "a.yaml").rename(root / "b.yaml")
    monkeypatch.setattr(library, "measure_file", lambda path: pytest.fail("measured"))
    report = heal_library(config)
    assert report.healed == [(root / "b.yaml", "file was 'a.png'")]
    assert read_sidecar(root / "b.yaml").file == "b.png"


def test_orphan_sidecar_is_reported_not_deleted(config: Config, save_image: SaveImage) -> None:
    root = config.library_roots[0]
    save_image(root / "a.png")
    heal_library(config)
    (root / "a.png").unlink()
    report = heal_library(config)
    assert report.orphans == [root / "a.yaml"]
    assert (root / "a.yaml").exists()


def test_images_sharing_a_sidecar(config: Config, save_image: SaveImage) -> None:
    root = config.library_roots[0]
    save_image(root / "a.png")
    save_image(root / "a.jpg")
    report = heal_library(config)
    assert report.conflicts == [[root / "a.jpg", root / "a.png"]]
    assert report.entries == []
    assert not (root / "a.yaml").exists()


def test_unreadable_image_fails_and_others_continue(config: Config, save_image: SaveImage) -> None:
    root = config.library_roots[0]
    (root / "bad.png").write_text("not an image")
    save_image(root / "good.png")
    report = heal_library(config)
    assert [path for path, _ in report.failed] == [root / "bad.png"]
    assert [entry.path for entry in report.entries] == [root / "good.png"]


def test_purity(config: Config, save_image: SaveImage, caplog: pytest.LogCaptureFixture) -> None:
    save_image(config.library_roots[0] / "plain.png")
    save_image(config.nsfw_root / "private.png")
    wallhaven = save_image(config.library_roots[0] / "wallhaven-x.png")
    heal_library(config)
    path = wallhaven.with_suffix(".yaml")
    data = yaml.safe_load(path.read_text())
    data["source"] = {"site": "wallhaven", "id": "x", "purity": "sketchy"}
    path.write_text(yaml.safe_dump(data))
    with caplog.at_level(logging.WARNING):
        report = heal_library(config)
    purity = {entry.path.name: entry.purity for entry in report.entries}
    assert purity == {"plain.png": "sfw", "wallhaven-x.png": "sketchy", "private.png": "nsfw"}
    assert "sketchy image outside the NSFW root" in caplog.text


def test_symlinked_directory_is_not_followed(config: Config, save_image: SaveImage) -> None:
    save_image(config.nsfw_root / "private.png")
    (config.library_roots[0] / "link").symlink_to(config.nsfw_root)
    report = heal_library(config)
    assert [entry.path for entry in report.entries] == [config.nsfw_root / "private.png"]
    assert report.entries[0].nsfw_root


def test_missing_root_is_skipped(tmp_path: Path, save_image: SaveImage) -> None:
    config = Config((tmp_path / "none",), tmp_path / "nsfw", tmp_path / "index.sqlite")
    assert heal_library(config).clean
