from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml
from conftest import SaveImage, mark_record

from amontillado import library
from amontillado.config import Config
from amontillado.library import heal_library
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
    assert report.healed == [(info, "new id; a.png: added")]
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
    assert report.healed == [(info, "new id; a.png: added")]
    assert report.entries == []
    assert info.read_text() == ""


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
    assert sorted(path.name for path in info.parent.iterdir()) == ["a.png", "info.yml"]
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
        ("nsfw-in-root", "--nsfw is for other files"),
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
