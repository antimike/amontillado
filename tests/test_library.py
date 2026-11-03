from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path

import numpy as np
import pytest
import yaml
from conftest import SaveImage, mark_record
from PIL import Image

from amontillado import library
from amontillado.config import Config
from amontillado.library import (
    THUMBNAIL_SIZE,
    AddError,
    CropError,
    add_picture,
    additions_from_json,
    crop_box,
    crop_picture,
    hand_source,
    heal_library,
    place,
)
from amontillado.metrics import METRICS_VERSION
from amontillado.record import ID_PATTERN, read_record, sha256_file


def _edit(path: Path, **changes: object) -> None:
    data = yaml.safe_load(path.read_text()) or {}
    data.update(changes)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def _no_measuring(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(library, "measure_file", lambda path: pytest.fail(f"measured {path}"))


def test_empty_info_file_is_filled_in(config: Config, save_image: SaveImage) -> None:
    directory = config.library_roots[0] / "sub" / "sunset"
    info = mark_record(directory)
    image = save_image(directory / "a.png", (255, 0, 0), (80, 40))
    report = heal_library(config)
    record = read_record(info)
    assert record.id is not None and ID_PATTERN.fullmatch(record.id)
    entry = record.files["a.png"]
    assert entry.sha256 == sha256_file(image)
    assert (entry.width, entry.height) == (80, 40)
    assert entry.metrics is not None and entry.metrics.hue_name == "red"
    assert record.source is None
    assert report.healed == [(info, "new id; a.png: added; thumbnail")]
    [indexed] = report.entries
    assert (indexed.directory, indexed.present, indexed.default) == (directory, ("a.png",), "a.png")
    assert not report.clean


def test_second_pass_is_clean_and_keeps_the_id(config: Config, save_image: SaveImage) -> None:
    info = mark_record(config.library_roots[0] / "r")
    save_image(info.parent / "a.png")
    heal_library(config)
    first = read_record(info).id
    report = heal_library(config)
    assert report.clean
    assert read_record(info).id == first
    assert len(report.entries) == 1


def test_check_writes_nothing(config: Config, save_image: SaveImage) -> None:
    info = mark_record(config.library_roots[0] / "r")
    save_image(info.parent / "a.png")
    report = heal_library(config, check=True)
    assert report.healed == [(info, "new id; a.png: added; thumbnail")]
    assert report.entries == []
    assert info.read_text() == ""
    assert not (info.parent / ".amo").exists()


def test_loose_images_are_reported_not_moved(config: Config, save_image: SaveImage) -> None:
    root = config.library_roots[0]
    loose = save_image(root / "sub" / "a.png")
    report = heal_library(config)
    assert report.loose == [loose]
    assert report.entries == []
    assert sorted(path.name for path in (root / "sub").iterdir()) == ["a.png"]


def test_info_file_in_a_root_is_ignored(
    config: Config, save_image: SaveImage, caplog: pytest.LogCaptureFixture
) -> None:
    root = config.library_roots[0]
    mark_record(root)
    save_image(root / "a.png")
    report = heal_library(config)
    assert report.loose == [root / "a.png"]
    assert "info file directly in a root is ignored" in caplog.text


def test_records_do_not_nest(config: Config, save_image: SaveImage) -> None:
    outer = mark_record(config.library_roots[0] / "outer").parent
    save_image(outer / "a.png")
    save_image(outer / "inner" / "b.png")
    mark_record(outer / "inner")
    report = heal_library(config)
    assert [entry.directory for entry in report.entries] == [outer]
    assert report.loose == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("files: [\n", "not valid YAML"),
        ("files:\n  a.png: {}\n  a.png: {}\n", "duplicate key"),
        ("schema: 3\n", "schema is 3"),
        ("name: Not Valid\n", "name 'Not Valid'"),
    ],
)
def test_unusable_info_file_is_reported_and_left_alone(
    config: Config, save_image: SaveImage, text: str, message: str
) -> None:
    info = mark_record(config.library_roots[0] / "r")
    info.write_text(text)
    save_image(info.parent / "a.png")
    report = heal_library(config)
    [(path, reason)] = report.failed
    assert path == info and message in reason
    assert info.read_text() == text
    assert report.entries == []


def test_old_metrics_are_recomputed_and_source_kept(config: Config, save_image: SaveImage) -> None:
    info = mark_record(config.library_roots[0] / "r")
    save_image(info.parent / "a.png")
    heal_library(config)
    data = yaml.safe_load(info.read_text())
    data["files"]["a.png"]["metrics"] = {"version": METRICS_VERSION - 1, "lightness": 0.9}
    data["source"] = {"site": "wallhaven", "id": "abc123", "purity": "sfw"}
    data["name"] = "night-city"
    info.write_text(yaml.safe_dump(data))
    report = heal_library(config)
    assert report.healed == [(info, "a.png: measured")]
    record = read_record(info)
    assert record.files["a.png"].metrics.lightness == pytest.approx(0.0, abs=1e-3)
    assert record.source == {"site": "wallhaven", "id": "abc123", "purity": "sfw"}
    assert (record.id, record.name) == (data["id"], "night-city")


def test_changed_content_is_measured_again(config: Config, save_image: SaveImage) -> None:
    info = mark_record(config.library_roots[0] / "r")
    image = save_image(info.parent / "a.png", (255, 0, 0))
    heal_library(config)
    save_image(image, (0, 0, 255))
    report = heal_library(config)
    assert report.healed == [(info, "a.png: content changed")]
    entry = read_record(info).files["a.png"]
    assert entry.sha256 == sha256_file(image)
    assert entry.metrics.hue_name == "blue"


def test_routine_heals_log_at_debug_and_renames_at_info(
    config: Config, save_image: SaveImage, caplog: pytest.LogCaptureFixture
) -> None:
    info = mark_record(config.library_roots[0] / "r")
    save_image(info.parent / "a.png")
    with caplog.at_level(logging.DEBUG, logger="amontillado"):
        heal_library(config)
        assert [r.levelno for r in caplog.records if "healed:" in r.message] == [logging.DEBUG]
        caplog.clear()
        (info.parent / "a.png").rename(info.parent / "b.png")
        heal_library(config)
    assert [r.levelno for r in caplog.records if "healed:" in r.message] == [logging.INFO]


def test_report_counts_records_measured_and_renamed(config: Config, save_image: SaveImage) -> None:
    first = mark_record(config.library_roots[0] / "r")
    save_image(first.parent / "a.png")
    save_image(first.parent / "b.png", (9, 9, 9))
    second = mark_record(config.library_roots[0] / "s")
    save_image(second.parent / "c.png")
    report = heal_library(config, check=True)
    assert (report.records, report.measured, report.renamed) == (2, 3, 0)
    report = heal_library(config)
    assert (report.records, report.measured, report.renamed) == (2, 3, 0)
    (first.parent / "a.png").rename(first.parent / "d.png")
    report = heal_library(config)
    assert (report.records, report.measured, report.renamed) == (2, 0, 1)


def test_track_wraps_the_records_found(config: Config, save_image: SaveImage) -> None:
    info = mark_record(config.library_roots[0] / "r")
    save_image(info.parent / "a.png")
    seen = []

    def track(items: list) -> list:
        seen.extend(found.directory for found in items)
        return items

    heal_library(config, track=track)
    assert seen == [info.parent]


def _known(config: Config) -> dict[str, tuple[int, int, str]]:
    """The hash cache an index of the library as it is now would hold."""
    return {
        str(entry.directory / name): (*entry.stats[name], entry.record.files[name].sha256 or "")
        for entry in heal_library(config).entries
        for name in entry.present
    }


def test_unchanged_file_is_not_hashed_again(
    config: Config, save_image: SaveImage, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_image(mark_record(config.library_roots[0] / "r").parent / "a.png")
    known = _known(config)
    monkeypatch.setattr(library, "sha256_file", lambda path: pytest.fail(f"hashed {path}"))
    report = heal_library(config, known=known)
    assert report.clean
    assert len(report.entries) == 1


def test_file_with_a_new_mtime_is_hashed_again(config: Config, save_image: SaveImage) -> None:
    image = save_image(mark_record(config.library_roots[0] / "r").parent / "a.png")
    known = _known(config)
    # Same size, new content and mtime: the cache must not hide the change.
    save_image(image, (0, 0, 255))
    os.utime(image, ns=(image.stat().st_atime_ns, image.stat().st_mtime_ns + 1))
    report = heal_library(config, known=known)
    assert report.healed == [(image.parent / "info.yaml", "a.png: content changed")]


def test_renamed_file_keeps_its_entry_without_measuring(
    config: Config, save_image: SaveImage, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = mark_record(config.library_roots[0] / "r")
    directory = info.parent
    save_image(directory / "a.png", size=(64, 36))
    save_image(directory / "a-crop.png", (9, 9, 9), (32, 36))
    heal_library(config)
    _edit(info, default_file="a.png")
    data = yaml.safe_load(info.read_text())
    data["files"]["a-crop.png"].update(derived_from="a.png", crop=[0, 0, 32, 36])
    info.write_text(yaml.safe_dump(data))
    (directory / "a.png").rename(directory / "b.png")
    _no_measuring(monkeypatch)
    report = heal_library(config)
    assert report.healed == [(info, "b.png: renamed from a.png")]
    record = read_record(info)
    assert set(record.files) == {"b.png", "a-crop.png"}
    assert record.default_file == "b.png"
    assert record.files["a-crop.png"].derived_from == "b.png"
    assert record.files["a-crop.png"].crop == (0, 0, 32, 36)


def test_moved_record_needs_no_healing(
    config: Config, save_image: SaveImage, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = config.library_roots[0]
    info = mark_record(root / "r")
    save_image(info.parent / "a.png")
    heal_library(config)
    (root / "elsewhere").mkdir()
    info.parent.rename(root / "elsewhere" / "renamed")
    _no_measuring(monkeypatch)
    report = heal_library(config)
    assert report.clean
    assert report.entries[0].directory == root / "elsewhere" / "renamed"


def test_missing_file_keeps_its_entry(
    config: Config, save_image: SaveImage, caplog: pytest.LogCaptureFixture
) -> None:
    info = mark_record(config.library_roots[0] / "r")
    save_image(info.parent / "a.png", size=(64, 36))
    save_image(info.parent / "b.png", size=(32, 18))
    heal_library(config)
    _edit(info, default_file="a.png")
    (info.parent / "a.png").unlink()
    report = heal_library(config)
    assert report.missing == [info.parent / "a.png"]
    assert set(read_record(info).files) == {"a.png", "b.png"}
    [entry] = report.entries
    assert (entry.present, entry.default) == (("b.png",), "b.png")
    assert "default_file a.png is missing" in caplog.text


def test_broken_symlink_counts_as_missing(config: Config, save_image: SaveImage) -> None:
    # git-annex leaves a broken symlink where content was dropped.
    info = mark_record(config.library_roots[0] / "r")
    save_image(info.parent / "a.png")
    save_image(info.parent / "b.png")
    heal_library(config)
    (info.parent / "a.png").unlink()
    (info.parent / "a.png").symlink_to(".git/annex/objects/gone")
    report = heal_library(config)
    assert report.missing == [info.parent / "a.png"]
    assert "a.png" in read_record(info).files


def test_record_without_files_is_not_indexed(config: Config) -> None:
    info = mark_record(config.library_roots[0] / "r")
    report = heal_library(config)
    assert report.missing == [info.parent]
    assert report.entries == []


def test_unreadable_image_fails_its_record_and_others_continue(
    config: Config, save_image: SaveImage
) -> None:
    root = config.library_roots[0]
    bad = mark_record(root / "bad")
    (bad.parent / "x.png").write_text("not an image")
    good = mark_record(root / "good")
    save_image(good.parent / "a.png")
    report = heal_library(config)
    assert [path for path, _ in report.failed] == [bad.parent / "x.png"]
    assert [entry.directory for entry in report.entries] == [good.parent]
    assert bad.read_text() == ""


def test_both_info_files_is_a_conflict(config: Config, save_image: SaveImage) -> None:
    info = mark_record(config.library_roots[0] / "r")
    (info.parent / "info.yml").write_text("")
    save_image(info.parent / "a.png")
    report = heal_library(config)
    assert report.conflicts == [[info, info.parent / "info.yml"]]
    assert report.entries == []


def test_info_yml_is_used_in_place(config: Config, save_image: SaveImage) -> None:
    info = mark_record(config.library_roots[0] / "r").rename(
        config.library_roots[0] / "r" / "info.yml"
    )
    save_image(info.parent / "a.png")
    heal_library(config)
    assert sorted(path.name for path in info.parent.iterdir()) == [".amo", "a.png", "info.yml"]
    assert "a.png" in read_record(info).files


def test_copied_record_is_a_conflict(config: Config, save_image: SaveImage) -> None:
    root = config.library_roots[0]
    info = mark_record(root / "a")
    save_image(info.parent / "a.png")
    heal_library(config)
    copy = mark_record(root / "b")
    copy.write_bytes(info.read_bytes())
    save_image(copy.parent / "a.png")
    report = heal_library(config)
    assert report.conflicts == [[info, copy]]
    assert report.entries == []
    _edit(copy, id=None)
    report = heal_library(config)
    assert len(report.entries) == 2


def test_duplicate_name_answers_to_neither(config: Config, save_image: SaveImage) -> None:
    root = config.library_roots[0]
    for directory in ("a", "b"):
        info = mark_record(root / directory)
        info.write_text("name: night\n")
        save_image(info.parent / "x.png")
    report = heal_library(config)
    assert report.conflicts == [[root / "a" / "info.yaml", root / "b" / "info.yaml"]]
    assert [entry.name for entry in report.entries] == [None, None]
    assert read_record(root / "a" / "info.yaml").name == "night"


def test_same_content_twice_is_a_warning(
    config: Config, save_image: SaveImage, caplog: pytest.LogCaptureFixture
) -> None:
    root = config.library_roots[0]
    for directory in ("a", "b"):
        save_image(mark_record(root / directory).parent / "x.png")
    with caplog.at_level(logging.WARNING):
        report = heal_library(config)
    assert "same content" in caplog.text
    assert len(report.entries) == 2


def test_purity(config: Config, save_image: SaveImage, caplog: pytest.LogCaptureFixture) -> None:
    save_image(mark_record(config.library_roots[0] / "plain").parent / "a.png")
    save_image(mark_record(config.nsfw_root / "private").parent / "a.png")
    sketchy = mark_record(config.library_roots[0] / "sketchy")
    save_image(sketchy.parent / "a.png")
    sketchy.write_text("source: {site: wallhaven, id: x, purity: sketchy}\n")
    with caplog.at_level(logging.WARNING):
        report = heal_library(config)
    purity = {entry.directory.name: entry.purity for entry in report.entries}
    assert purity == {"plain": "sfw", "sketchy": "sketchy", "private": "nsfw"}
    assert "sketchy record outside the NSFW root" in caplog.text


def test_symlinked_directory_is_not_followed(config: Config, save_image: SaveImage) -> None:
    save_image(mark_record(config.nsfw_root / "private").parent / "a.png")
    (config.library_roots[0] / "link").symlink_to(config.nsfw_root)
    report = heal_library(config)
    assert [entry.directory for entry in report.entries] == [config.nsfw_root / "private"]
    assert report.entries[0].nsfw_root


def test_missing_root_is_skipped(tmp_path: Path) -> None:
    config = Config((tmp_path / "none",), tmp_path / "nsfw", tmp_path / "index.sqlite")
    assert heal_library(config).clean


def test_add_wraps_a_loose_image_in_place(config: Config, save_image: SaveImage) -> None:
    root = config.library_roots[0]
    loose = save_image(root / "sub" / "sunset.png", (255, 0, 0))
    digest = sha256_file(loose)
    placement = library.place(config, loose, name=None, nsfw=False)
    assert placement.directory == root / "sub" / "sunset"
    entry = library.add_picture(config, placement, name=None)
    assert not loose.exists()
    record = read_record(root / "sub" / "sunset" / "info.yaml")
    assert record.files["sunset.png"].sha256 == digest
    assert record.files["sunset.png"].metrics.hue_name == "red"
    assert (entry.id, entry.default, entry.root) == (record.id, "sunset.png", root)
    assert heal_library(config).clean


def test_add_from_outside_the_roots(config: Config, save_image: SaveImage, tmp_path: Path) -> None:
    file = save_image(tmp_path / "downloads" / "x.png")
    placement = library.place(config, file, name="night", nsfw=False)
    assert placement.directory == config.library_roots[0] / "night"
    entry = library.add_picture(config, placement, name="night")
    assert read_record(placement.directory / "info.yaml").name == "night"
    assert not entry.nsfw_root
    other = save_image(tmp_path / "downloads" / "y.png")
    nsfw = library.place(config, other, name=None, nsfw=True)
    assert nsfw.directory == config.nsfw_root / "y"
    assert library.add_picture(config, nsfw, name=None).nsfw_root


def test_measuring_failure_moves_nothing(config: Config, tmp_path: Path) -> None:
    bad = tmp_path / "bad.png"
    bad.write_text("not an image")
    placement = library.place(config, bad, name=None, nsfw=False)
    with pytest.raises(OSError):
        library.add_picture(config, placement, name=None)
    assert bad.exists()
    assert not placement.directory.exists()


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("not-image", "not an image file"),
        ("in-record", "already in the record"),
        ("in-nested-record", "already in the record"),
        ("exists", "already exists"),
        ("bad-name", "does not match"),
        ("nsfw-in-root", "under the library root .* to add it as non-sfw"),
    ],
)
def test_add_refuses(config: Config, save_image: SaveImage, case: str, message: str) -> None:
    root = config.library_roots[0]
    name, nsfw = ("Bad Name" if case == "bad-name" else None), case == "nsfw-in-root"
    if case == "not-image":
        file = root / "notes.txt"
        file.write_text("")
    elif case == "in-record":
        file = save_image(mark_record(root / "r").parent / "a.png")
    elif case == "in-nested-record":
        mark_record(root / "r")
        file = save_image(root / "r" / "deeper" / "a.png")
    else:
        file = save_image(root / "a.png")
        if case == "exists":
            (root / "a").mkdir()
    with pytest.raises(library.AddError, match=message):
        library.place(config, file, name=name, nsfw=nsfw)


def test_healing_makes_a_thumbnail_of_the_default_file(
    config: Config, save_image: SaveImage
) -> None:
    info = mark_record(config.library_roots[0] / "r")
    save_image(info.parent / "small.png", (0, 0, 255), (80, 40))
    save_image(info.parent / "big.png", (255, 0, 0), (1200, 600))
    heal_library(config)
    record = read_record(info)
    assert record.thumbnail == ".amo/thumbnail.jpg"
    with Image.open(info.parent / record.thumbnail) as thumbnail:
        assert thumbnail.format == "JPEG"
        assert thumbnail.size == (THUMBNAIL_SIZE, THUMBNAIL_SIZE // 2)
        red, green, blue = thumbnail.getpixel((10, 10))
        assert red > 200 and green < 50 and blue < 50  # of big.png, the default
    # Never one of the picture's files, nor a loose image.
    report = heal_library(config)
    assert report.clean
    assert sorted(read_record(info).files) == ["big.png", "small.png"]


def test_a_missing_thumbnail_is_made_again(config: Config, save_image: SaveImage) -> None:
    info = mark_record(config.library_roots[0] / "r")
    save_image(info.parent / "a.png")
    heal_library(config)
    (info.parent / ".amo" / "thumbnail.jpg").unlink()
    report = heal_library(config)
    assert report.healed == [(info, "thumbnail")]
    assert (info.parent / ".amo" / "thumbnail.jpg").is_file()


def test_a_thumbnail_set_by_hand_is_kept(config: Config, save_image: SaveImage) -> None:
    info = mark_record(config.library_roots[0] / "r")
    save_image(info.parent / "a.png")
    save_image(info.parent / "previews" / "mine.png")
    info.write_text("thumbnail: previews/mine.png\n")
    heal_library(config)
    assert read_record(info).thumbnail == "previews/mine.png"
    assert not (info.parent / ".amo").exists()


def test_a_thumbnail_that_fails_warns_and_keeps_the_record(
    config: Config, save_image: SaveImage, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(library, "write_thumbnail", fail)
    info = mark_record(config.library_roots[0] / "r")
    save_image(info.parent / "a.png")
    report = heal_library(config)
    assert report.failed == []
    assert len(report.entries) == 1
    assert read_record(info).thumbnail is None


def test_add_makes_a_thumbnail(config: Config, save_image: SaveImage, tmp_path: Path) -> None:
    image = save_image(tmp_path / "sunset.png", (255, 128, 0), (100, 50))
    entry = add_picture(config, place(config, image, name=None, nsfw=False), name=None)
    assert entry.record.thumbnail == ".amo/thumbnail.jpg"
    assert (entry.directory / ".amo" / "thumbnail.jpg").is_file()
    assert read_record(entry.directory / "info.yaml").thumbnail == ".amo/thumbnail.jpg"


@pytest.mark.parametrize(
    ("size", "ratio", "at", "box"),
    [
        ((3840, 2160), 21 / 9, 0.5, (0, 257, 3840, 1646)),  # design.md's example
        ((3840, 2160), 21 / 9, 0.0, (0, 0, 3840, 1646)),
        ((3840, 2160), 21 / 9, 1.0, (0, 514, 3840, 1646)),
        ((3840, 2160), 1.0, 0.5, (840, 0, 2160, 2160)),
        ((1080, 1920), 16 / 9, 0.5, (0, 656, 1080, 608)),
    ],
)
def test_crop_box(size: tuple[int, int], ratio: float, at: float, box: tuple[int, ...]) -> None:
    assert crop_box(*size, ratio, at) == box


def _halves(path: Path) -> Path:
    """A 200x100 image, red on the left half and blue on the right."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pixels = np.zeros((100, 200, 3), dtype=np.uint8)
    pixels[:, :100] = (255, 0, 0)
    pixels[:, 100:] = (0, 0, 255)
    Image.fromarray(pixels).save(path)
    return path


def _crop(config: Config, directory: Path, **options: object) -> str:
    entry, name = crop_picture(config, directory, config.library_roots[0], 1.0, "1x1", **options)  # type: ignore[arg-type]
    assert entry.default == "pic.png"
    return name


def test_crop_picture_records_the_crop(config: Config) -> None:
    info = mark_record(config.library_roots[0] / "r")
    _halves(info.parent / "pic.png")
    heal_library(config)
    assert _crop(config, info.parent, at=0.0) == "pic-1x1.png"
    record = read_record(info)
    crop = record.files["pic-1x1.png"]
    assert (crop.derived_from, crop.crop, crop.width, crop.height) == (
        "pic.png",
        (0, 0, 100, 100),
        100,
        100,
    )
    assert crop.metrics is not None and crop.metrics.hue_name == "red"
    with Image.open(info.parent / "pic-1x1.png") as image:
        assert image.format == "PNG"
    # Nothing left to heal, and the original stays the default.
    report = heal_library(config)
    assert report.clean
    [entry] = report.entries
    assert entry.default == "pic.png"


def test_crop_picture_at_the_end(config: Config) -> None:
    info = mark_record(config.library_roots[0] / "r")
    _halves(info.parent / "pic.png")
    heal_library(config)
    _crop(config, info.parent, at=1.0)
    crop = read_record(info).files["pic-1x1.png"]
    assert crop.crop == (100, 0, 100, 100)
    assert crop.metrics is not None and crop.metrics.hue_name == "blue"


def test_crop_picture_keeps_the_format(config: Config) -> None:
    info = mark_record(config.library_roots[0] / "r")
    Image.open(_halves(info.parent / "x.png")).save(info.parent / "pic.jpg", quality=90)
    (info.parent / "x.png").unlink()
    heal_library(config)
    _, name = crop_picture(config, info.parent, config.library_roots[0], 1.0, "1x1")
    assert name == "pic-1x1.jpg"
    with Image.open(info.parent / name) as image:
        assert (image.format, image.size) == ("JPEG", (100, 100))


def test_crop_picture_refusals(config: Config, save_image: SaveImage) -> None:
    info = mark_record(config.library_roots[0] / "r")
    _halves(info.parent / "pic.png")
    with pytest.raises(CropError, match="run `amo index` first"):
        _crop(config, info.parent)
    heal_library(config)
    with pytest.raises(CropError, match="already 2:1"):
        crop_picture(config, info.parent, config.library_roots[0], 2.0, "2x1")
    _crop(config, info.parent)
    with pytest.raises(CropError, match="1:1 already; --force"):
        _crop(config, info.parent)
    # --force replaces the earlier crop of the same name.
    _crop(config, info.parent, at=1.0, force=True)
    assert read_record(info).files["pic-1x1.png"].crop == (100, 0, 100, 100)
    # Never a file that is not a crop.
    other = mark_record(config.library_roots[0] / "s")
    _halves(other.parent / "pic.png")
    save_image(other.parent / "pic-1x1.png", size=(50, 50))
    heal_library(config)
    with pytest.raises(CropError, match="not a crop"):
        _crop(config, other.parent, force=True)


def test_crop_picture_dry_run_writes_nothing(config: Config) -> None:
    info = mark_record(config.library_roots[0] / "r")
    _halves(info.parent / "pic.png")
    heal_library(config)
    before = info.read_text()
    assert _crop(config, info.parent, dry_run=True) == "pic-1x1.png"
    assert info.read_text() == before
    assert not (info.parent / "pic-1x1.png").exists()


def test_crop_picture_keeps_exif_and_resets_the_orientation(config: Config) -> None:
    info = mark_record(config.library_roots[0] / "r")
    stored = Image.open(_halves(info.parent / "x.png"))
    exif = Image.Exif()
    exif[0x0112] = 6  # stored 200x100, displayed 100x200
    exif[0x013B] = "A. Painter"  # Artist
    stored.save(info.parent / "pic.jpg", exif=exif, quality=95)
    (info.parent / "x.png").unlink()
    heal_library(config)
    _, name = crop_picture(config, info.parent, config.library_roots[0], 1.0, "1x1")
    assert read_record(info).files[name].crop == (0, 50, 100, 100)
    with Image.open(info.parent / name) as image:
        assert image.size == (100, 100)
        assert image.getexif().get(0x0112) == 1
        assert image.getexif().get(0x013B) == "A. Painter"


def test_hand_source_orders_fields_and_derives_the_site() -> None:
    source = hand_source(
        {
            "license": "CC0-1.0",
            "url": "https://commons.wikimedia.org/wiki/File:Sunset.jpg",
            "author": "A. Painter",
            "tags": ["sunset", "sea"],
            "uploaded": "2019-06-02",
            "title": None,
        }
    )
    assert source == {
        "site": "commons.wikimedia.org",
        "url": "https://commons.wikimedia.org/wiki/File:Sunset.jpg",
        "author": "A. Painter",
        "license": "CC0-1.0",
        "tags": ["sunset", "sea"],
        "uploaded": date(2019, 6, 2),
    }
    assert list(source) == ["site", "url", "author", "license", "tags", "uploaded"]
    assert hand_source({"url": "https://www.example.org/a"})["site"] == "example.org"  # type: ignore[index]
    assert hand_source({"site": "mine", "url": "https://x.org/"})["site"] == "mine"  # type: ignore[index]
    assert hand_source({"title": ""}) is None


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"url": "commons.wikimedia.org/x"}, "not an http"),
        ({"purity": "spicy"}, "not one of"),
        ({"tags": "a,b"}, "not a list"),
        ({"uploaded": "June"}, "not an ISO 8601"),
        ({"author": 5}, "author: not a string"),
    ],
)
def test_hand_source_refuses(fields: dict[str, object], message: str) -> None:
    with pytest.raises(AddError, match=message):
        hand_source(fields)


def test_additions_from_json(tmp_path: Path) -> None:
    path = tmp_path / "seeds" / "pictures.json"
    path.parent.mkdir()
    path.write_text(
        '[{"file": "a.jpg", "name": "a", "license": "CC0-1.0"},'
        ' {"file": "/abs/b.png", "nsfw": true}]'
    )
    first, second = additions_from_json(path)
    assert (first.file, first.name, first.nsfw) == (path.parent / "a.jpg", "a", False)
    assert first.fields == {"license": "CC0-1.0"}
    assert (second.file, second.nsfw, second.fields) == (Path("/abs/b.png"), True, {})


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{", "not JSON"),
        ('{"file": "a.jpg"}', "not a list"),
        ('[{"name": "a"}]', "picture 1: no file"),
        (
            '[{"file": "a.jpg"}, {"file": "b.jpg", "licence": "x"}]',
            "picture 2: unknown keys licence",
        ),
        ('[{"file": "a.jpg", "purity": "x"}]', "picture 1: purity"),
    ],
)
def test_additions_from_json_refuses(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "pictures.json"
    path.write_text(text)
    with pytest.raises(AddError, match=message):
        additions_from_json(path)


def test_a_non_sfw_purity_goes_to_the_nsfw_root(
    config: Config, save_image: SaveImage, tmp_path: Path
) -> None:
    image = save_image(tmp_path / "a.png")
    placement = place(config, image, name=None, nsfw=False, purity="sketchy")
    assert placement.directory == config.nsfw_root / "a"
    with pytest.raises(AddError, match="--nsfw with purity sfw"):
        place(config, image, name=None, nsfw=True, purity="sfw")
    inside = save_image(config.library_roots[0] / "b.png")
    with pytest.raises(AddError, match="to add it as non-sfw"):
        place(config, inside, name=None, nsfw=False, purity="nsfw")
