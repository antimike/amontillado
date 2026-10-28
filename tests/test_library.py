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


def test_yml_sidecar_is_used_in_place(config: Config, save_image: SaveImage) -> None:
    root = config.library_roots[0]
    save_image(root / "a.png")
    heal_library(config)
    (root / "a.yaml").rename(root / "a.yml")
    report = heal_library(config)
    assert report.clean
    assert sorted(path.name for path in root.iterdir()) == ["a.png", "a.yml"]


def test_unparseable_yml_is_kept_aside(config: Config, save_image: SaveImage) -> None:
    root = config.library_roots[0]
    save_image(root / "a.png")
    (root / "a.yml").write_text("a: [\n")
    heal_library(config)
    assert (root / "a.yml.bad").read_text() == "a: [\n"
    assert read_sidecar(root / "a.yml").file == "a.png"


def test_yaml_and_yml_for_one_image(config: Config, save_image: SaveImage) -> None:
    root = config.library_roots[0]
    save_image(root / "a.png")
    heal_library(config)
    (root / "a.yml").write_bytes((root / "a.yaml").read_bytes())
    report = heal_library(config)
    assert report.conflicts == [[root / "a.png", root / "a.yaml", root / "a.yml"]]
    assert report.entries == []


def _set_source(sidecar: Path, source: dict[str, object]) -> None:
    data = yaml.safe_load(sidecar.read_text())
    data["source"] = source
    sidecar.write_text(yaml.safe_dump(data))


def test_renamed_image_adopts_its_sidecar(
    config: Config, save_image: SaveImage, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = config.library_roots[0]
    save_image(root / "wallhaven-x.png", (255, 0, 0))
    heal_library(config)
    _set_source(root / "wallhaven-x.yaml", {"site": "wallhaven", "id": "x"})
    (root / "sub").mkdir()
    (root / "wallhaven-x.png").rename(root / "sub" / "sunset.png")
    monkeypatch.setattr(library, "measure_file", lambda path: pytest.fail("measured"))
    report = heal_library(config)
    assert report.healed == [
        (root / "sub" / "sunset.yaml", f"re-paired with {root}/wallhaven-x.yaml")
    ]
    assert report.orphans == []
    assert not (root / "wallhaven-x.yaml").exists()
    sidecar = read_sidecar(root / "sub" / "sunset.yaml")
    assert sidecar.file == "sunset.png"
    assert sidecar.source == {"site": "wallhaven", "id": "x"}


def test_adopted_yml_keeps_its_suffix(config: Config, save_image: SaveImage) -> None:
    root = config.library_roots[0]
    save_image(root / "a.png")
    heal_library(config)
    (root / "a.yaml").rename(root / "a.yml")
    (root / "a.png").rename(root / "b.png")
    heal_library(config)
    assert read_sidecar(root / "b.yml").file == "b.png"


def test_check_reports_a_re_pairing_without_moving(config: Config, save_image: SaveImage) -> None:
    root = config.library_roots[0]
    save_image(root / "a.png")
    heal_library(config)
    (root / "a.png").rename(root / "b.png")
    report = heal_library(config, check=True)
    assert report.healed == [(root / "b.yaml", f"re-paired with {root}/a.yaml")]
    assert report.orphans == []
    assert (root / "a.yaml").exists() and not (root / "b.yaml").exists()


def test_one_orphan_is_adopted_once(config: Config, save_image: SaveImage) -> None:
    # Two copies of one image, both renamed: one adopts the sidecar, the other gets a new one.
    root = config.library_roots[0]
    save_image(root / "a.png")
    heal_library(config)
    _set_source(root / "a.yaml", {"site": "wallhaven", "id": "x"})
    (root / "a.png").rename(root / "b.png")
    (root / "c.png").write_bytes((root / "b.png").read_bytes())
    report = heal_library(config)
    assert sorted(reason for _, reason in report.healed) == [
        "no sidecar",
        f"re-paired with {root}/a.yaml",
    ]
    assert read_sidecar(root / "b.yaml").source == {"site": "wallhaven", "id": "x"}
    assert read_sidecar(root / "c.yaml").source is None


def test_orphan_of_other_content_is_not_adopted(config: Config, save_image: SaveImage) -> None:
    root = config.library_roots[0]
    save_image(root / "a.png", (255, 0, 0))
    heal_library(config)
    (root / "a.png").unlink()
    save_image(root / "b.png", (0, 0, 255))
    report = heal_library(config)
    assert report.orphans == [root / "a.yaml"]
    assert read_sidecar(root / "b.yaml").metrics.hue_name == "blue"
