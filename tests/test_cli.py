from __future__ import annotations

import io
import json
import logging
import os
import random
import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import numpy as np
import pytest
from conftest import FakeClock, FakeWeb, mark_record
from PIL import Image
from rich.console import Console

from amontillado import __version__, cli, yamlio
from amontillado import library as library_module
from amontillado.cli import get_cli_arguments, main
from amontillado.index import connect, record_shown, usage
from amontillado.wallhaven import API, Client


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"amontillado {__version__}"


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    main([])
    assert "usage: amontillado" in capsys.readouterr().out.lower()


def _save(array: np.ndarray, path: Path) -> Path:
    Image.fromarray(array).save(path)
    return path


def test_measure_prints_yaml(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    black = _save(np.zeros((36, 64, 3), dtype=np.uint8), tmp_path / "black.png")
    red = _save(np.full((36, 64, 3), (255, 0, 0), dtype=np.uint8), tmp_path / "red.png")
    main(["measure", str(black), str(red)])
    out = yamlio.load(capsys.readouterr().out)
    assert [entry["file"] for entry in out] == [str(black), str(red)]
    assert out[0]["metrics"]["hue"] is None
    assert out[0]["classes"] == ["dark", "muted", "sparse"]
    assert out[1]["metrics"]["hue_name"] == "red"
    assert {"saturated", "monochrome", "warm", "red"} <= set(out[1]["classes"])


def test_palette_from_scheme(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ramp = ["#101010", "#202020", "#303030", "#505050", "#a0a0a0", "#d0d0d0", "#e0e0e0", "#f0f0f0"]
    accents = ["#e06060", "#e09050", "#e0c050", "#60c060", "#50c0c0", "#6090e0", "#b070e0"]
    colours = dict(
        zip([f"base{i:02X}" for i in range(16)], [*ramp, *accents, "#906040"], strict=True)
    )
    scheme = tmp_path / "s.yaml"
    scheme.write_text(yamlio.dump({"system": "base16", "name": "S", "palette": colours}))
    main(["palette", "--from-scheme", str(scheme)])
    out = yamlio.load(capsys.readouterr().out)
    assert out["name"] == "S"
    assert out["variants"]["dark"]["roles"]["accent"] == "#6090e0"
    assert len(out["variants"]["dark"]["base24"]) == 24
    with pytest.raises(SystemExit) as exc:
        main(["palette", "--from-scheme", str(tmp_path / "none.yaml")])
    assert str(exc.value.code).startswith("amontillado: ")
    assert "No such file" in str(exc.value.code)


def _palette_file(path: Path, base03: str) -> Path:
    ramp = ["#101010", "#181818", "#303030", base03, "#a0a0a0", "#e0e0e0", "#f0f0f0", "#ffffff"]
    accents = ["#ff8080", "#ffa060", "#ffe080", "#80ff80", "#80ffff", "#80b0ff", "#e0a0ff"]
    colours = dict(
        zip([f"base{i:02X}" for i in range(16)], [*ramp, *accents, "#c08060"], strict=True)
    )
    data = {"version": 1, "name": "p", "variants": {"dark": {"base24": colours}}}
    path.write_text(yamlio.dump(data))
    return path


def test_palette_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["palette", "--check", str(_palette_file(tmp_path / "good.yaml", "#707070"))])
    assert capsys.readouterr().out.splitlines()[0] == "dark: hues 6/6, distinct 13.3"
    with pytest.raises(SystemExit) as exc:
        main(["palette", "--check", str(_palette_file(tmp_path / "bad.yaml", "#202020"))])
    assert exc.value.code == "amontillado: 1 pair below the contrast minimum"
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "dark: hues 6/6, distinct 13.3"
    assert lines[1].startswith("dark: xterm's fixed colours below 4.5:1 on base00: cube ")
    assert lines[2].startswith("dark: base03 on base00: 1.")


def test_palette_check_reports_accents_without_failing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Green as a second red: off its hue and close to red, but every pair passes.
    path = _palette_file(tmp_path / "p.yaml", "#707070")
    data = yamlio.load(path.read_text())
    data["variants"]["dark"]["base24"]["base0B"] = "#ff8484"
    path.write_text(yamlio.dump(data))
    main(["palette", "--check", str(path)])
    assert capsys.readouterr().out.splitlines()[0] == "dark: hues 5/6, distinct 0.8"


def test_palette_check_tone_checks_the_toned_variant(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _palette_file(tmp_path / "p.yaml", "#707070")
    main(["palette", "--check", str(path), "--tone", "dark=dim"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("dark (dim): hues 6/6, distinct ")
    assert lines[1].startswith("dark (dim): xterm's fixed colours")
    # dim's blue is a background: no blue text pair fails.
    assert len(lines) == 2


def test_palette_check_tone_full_is_the_plain_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _palette_file(tmp_path / "p.yaml", "#707070")
    main(["palette", "--check", str(path), "--tone", "dark=full"])
    assert capsys.readouterr().out.splitlines()[0] == "dark: hues 6/6, distinct 13.3"


@pytest.mark.parametrize("value", ["dark=soft", "light=dim", "dusk=dim", "dark"])
def test_palette_tone_refuses_what_a_variant_does_not_take(
    tmp_path: Path, value: str, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _palette_file(tmp_path / "p.yaml", "#707070")
    with pytest.raises(SystemExit) as exc:
        main(["palette", "--check", str(path), "--tone", value])
    assert exc.value.code == 2
    assert "--tone" in capsys.readouterr().err


def test_palette_tone_needs_the_variant_and_check(tmp_path: Path) -> None:
    path = _palette_file(tmp_path / "p.yaml", "#707070")
    with pytest.raises(SystemExit) as exc:
        main(["palette", "--check", str(path), "--tone", "light=soft"])
    assert exc.value.code == f"amontillado: --tone: {path} has no light variant"
    with pytest.raises(SystemExit) as exc:
        main(["palette", "--from-scheme", str(path), "--tone", "dark=dim"])
    assert str(exc.value.code).startswith("amontillado: --tone needs --check")


def _scheme_file(path: Path, base03: str) -> Path:
    palette = yamlio.load(_palette_file(path, base03).read_text())
    colours = palette["variants"]["dark"]["base24"]
    path.write_text(yamlio.dump({"system": "base16", "name": "S", "palette": colours}))
    return path


@pytest.mark.parametrize(
    ("argv", "config", "adjusted"),
    [([], "", True), (["--no-adjust"], "", False), ([], "theme: {contrast: off}\n", False)],
)
def test_palette_from_scheme_contrast(
    tmp_path: Path,
    home: Path,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    config: str,
    adjusted: bool,
) -> None:
    (home / ".config/amontillado").mkdir(parents=True)
    (home / ".config/amontillado/config.yaml").write_text(config)
    scheme = _scheme_file(tmp_path / "s.yaml", "#202020")
    main(["palette", "--from-scheme", str(scheme), *argv])
    dark = yamlio.load(capsys.readouterr().out)["variants"]["dark"]
    assert (dark["base24"]["base03"] != "#202020") is adjusted
    assert ("adjusted" in dark) is adjusted


def test_measure_reports_bad_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = _save(np.zeros((36, 64, 3), dtype=np.uint8), tmp_path / "good.png")
    bad = tmp_path / "bad.png"
    bad.write_text("not an image")
    with pytest.raises(SystemExit) as exc:
        main(["measure", str(bad), str(good), str(tmp_path / "missing.png")])
    assert exc.value.code == "amontillado: 2 of 3 files could not be measured"
    out = yamlio.load(capsys.readouterr().out)
    assert [entry["file"] for entry in out] == [str(good)]


def test_loglevel_before_or_after_command() -> None:
    assert get_cli_arguments(["-l", "debug", "measure", "x"]).loglevel == "DEBUG"
    assert get_cli_arguments(["measure", "-l", "warning", "x"]).loglevel == "WARNING"
    assert get_cli_arguments(["measure", "x"]).loglevel == "INFO"


@pytest.fixture
def library(home: Path) -> Path:
    """The default library root under a temporary HOME."""
    root = home / ".local/share/amontillado/library"
    root.mkdir(parents=True)
    return root


def _index_rows(home: Path) -> list[str]:
    with sqlite3.connect(home / ".local/state/amontillado/index.sqlite") as conn:
        return [Path(row[0]).name for row in conn.execute("SELECT path FROM files ORDER BY 1")]


def _record(directory: Path, rgb: tuple[int, int, int] = (0, 0, 0), name: str = "a.png") -> Path:
    """A record holding one solid-colour image; returns the image."""
    mark_record(directory)
    return _save(np.full((36, 64, 3), rgb, dtype=np.uint8), directory / name)


def test_index_heals_and_indexes(library: Path, home: Path) -> None:
    _record(library / "r")
    main(["index"])
    assert "a.png" in yamlio.load((library / "r" / "info.yaml").read_text())["files"]
    assert _index_rows(home) == ["a.png"]


def test_index_logs_one_summary(library: Path, caplog: pytest.LogCaptureFixture) -> None:
    _record(library / "r")
    _record(library / "s")
    _save(np.zeros((36, 64, 3), dtype=np.uint8), library / "loose.png")
    main(["index"])
    assert "indexed 2 records: 2 healed, 2 files measured, 1 image outside a record" in caplog.text
    assert "healed:" not in caplog.text
    caplog.clear()
    main(["index"])
    assert "indexed 2 records: 1 image outside a record" in caplog.text


def test_index_check_logs_what_would_change(
    library: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _record(library / "r")
    with pytest.raises(SystemExit):
        main(["index", "--check"])
    assert "checked 1 record: 1 to heal, 1 file to measure" in caplog.text


def test_index_shows_progress_on_a_terminal(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _record(library / "r")
    terminal = io.StringIO()
    monkeypatch.setattr(cli, "STDERR", Console(file=terminal, force_terminal=True))
    main(["index"])
    assert "indexing" in terminal.getvalue()


def test_index_check_writes_nothing_and_fails(library: Path, home: Path) -> None:
    _record(library / "r")
    with pytest.raises(SystemExit) as exc:
        main(["index", "--check"])
    assert exc.value.code == "amontillado: 1 record to heal"
    assert (library / "r" / "info.yaml").read_text() == ""
    assert not (home / ".local/state/amontillado/index.sqlite").exists()


def test_index_hashes_only_changed_files_unless_rehashing(
    library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _record(library / "r")
    main(["index"])
    hashed: list[Path] = []
    real = library_module.sha256_file
    monkeypatch.setattr(
        library_module, "sha256_file", lambda path: hashed.append(path) or real(path)
    )
    main(["index"])
    main(["index", "--check"])
    assert hashed == []
    main(["index", "--rehash"])
    assert [path.name for path in hashed] == ["a.png"]


def test_index_check_passes_on_a_healed_library(library: Path) -> None:
    _record(library / "r")
    main(["index"])
    main(["index", "--check"])


def test_index_loose_and_missing_fail_only_a_check(library: Path) -> None:
    _save(np.zeros((36, 64, 3), dtype=np.uint8), library / "loose.png")
    _record(library / "r", name="a.png")
    _record(library / "r", name="b.png")
    main(["index"])
    (library / "r" / "a.png").unlink()
    main(["index"])
    with pytest.raises(SystemExit) as exc:
        main(["index", "--check"])
    assert exc.value.code == "amontillado: 1 image outside a record, 1 file missing"


def test_index_indexes_the_rest_when_a_record_fails(library: Path, home: Path) -> None:
    _record(library / "good")
    mark_record(library / "bad")
    (library / "bad" / "x.png").write_text("not an image")
    with pytest.raises(SystemExit) as exc:
        main(["index"])
    assert exc.value.code == "amontillado: 1 file could not be read or used"
    assert _index_rows(home) == ["a.png"]


def test_config_error_exits(home: Path) -> None:
    (home / ".config/amontillado").mkdir(parents=True)
    (home / ".config/amontillado/config.yaml").write_text("library_roots: /x\n")
    with pytest.raises(SystemExit) as exc:
        main(["index"])
    assert exc.value.code == "amontillado: library_roots must be a list of paths"


@pytest.fixture
def indexed(library: Path, home: Path) -> dict[str, Path]:
    """An indexed library of one-image records: black, white, red, grey noise, and a black
    one in the NSFW root. Images are named after their record."""
    noise = np.random.default_rng(0).integers(0, 256, size=(36, 64), dtype=np.uint8)
    nsfw = home / ".local/share/amontillado/library-nsfw"
    paths = {
        "black": _record(library / "black", (0, 0, 0), "black.png"),
        "white": _record(library / "white", (255, 255, 255), "white.png"),
        "red": _record(library / "red", (255, 0, 0), "red.png"),
        "private": _record(nsfw / "private", (0, 0, 0), "private.png"),
    }
    mark_record(library / "noise")
    paths["noise"] = _save(np.repeat(noise[..., None], 3, axis=2), library / "noise/noise.png")
    main(["index"])
    return paths


def _list(capsys: pytest.CaptureFixture[str], *args: str) -> set[str]:
    capsys.readouterr()
    main(["list", *args])
    return {Path(line).stem for line in capsys.readouterr().out.splitlines()}


def test_list_all_excludes_nsfw(
    indexed: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert _list(capsys) == {"black", "white", "red", "noise"}


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        (["--dark"], {"black"}),
        (["--light"], {"white"}),
        (["--saturated"], {"red"}),
        (["--muted", "--busy"], {"noise"}),
        (["--hue", "red"], {"red"}),
        (["--warm", "--monochrome"], {"red"}),
        (["--purity", "nsfw"], {"private"}),
        (["--purity", "sfw,nsfw", "--dark"], {"black", "private"}),
    ],
)
def test_list_filters(
    indexed: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
    flags: list[str],
    expected: set[str],
) -> None:
    assert _list(capsys, *flags) == expected


def test_list_prints_the_default_file(
    indexed: dict[str, Path], library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _save(np.zeros((18, 32, 3), dtype=np.uint8), library / "black" / "small.png")
    main(["index"])
    assert _list(capsys, "--dark") == {"black"}
    info = library / "black" / "info.yaml"
    data = yamlio.load(info.read_text())
    data["default_file"] = "small.png"
    info.write_text(yamlio.dump(data))
    main(["index"])
    assert _list(capsys, "--dark") == {"small"}


def test_list_aspect(
    indexed: dict[str, Path],
    library: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    # black: a 64x36 default (16:9), a white 64x27 crop (21:9) and a smaller 21:9 copy.
    black = library / "black"
    _save(np.full((27, 64, 3), 255, dtype=np.uint8), black / "wide.png")
    _save(np.full((18, 42, 3), 255, dtype=np.uint8), black / "wide-small.png")
    main(["index"])
    assert _list(capsys, "--aspect", "16:9", "--dark") == {"black"}
    caplog.clear()
    assert _list(capsys, "--aspect", "21:9", "--light") == {"wide", "white"}
    assert "no file of that aspect ratio for 1 picture" in caplog.text
    # Filtered on the crop's metrics: black's 21:9 file is white.
    with pytest.raises(SystemExit):
        _list(capsys, "--aspect", "21:9", "--dark")


def test_crop_then_list(
    indexed: dict[str, Path], library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    main(["crop", str(library / "red"), "1:1"])
    crop = library / "red" / "red-1x1.png"
    assert capsys.readouterr().out == f"{crop}\n"
    with Image.open(crop) as image:
        assert image.size == (36, 36)
    # The index knows it at once: no `amo index` needed.
    assert _list(capsys, "--aspect", "1:1", "--hue", "red") == {"red-1x1"}
    with pytest.raises(SystemExit, match="1:1 already; --force"):
        main(["crop", str(indexed["red"]), "1:1"])


def _old_fetched(
    library: Path,
    wallhaven_id: str,
    tags: list[str],
    categories: dict[str, str] | None = None,
    name: str | None = None,
) -> Path:
    """A record fetched before names existed: no name (or `name`), in wallhaven-<id>, its tags
    kept (with `categories` as source.tag_categories)."""
    directory = library / f"wallhaven-{wallhaven_id}"
    _record(directory, (0, 0, 255), f"wallhaven-{wallhaven_id}.png")
    source: dict[str, object] = {
        "site": "wallhaven",
        "id": wallhaven_id,
        "category": "general",
        "tags": tags,
    }
    if categories is not None:
        source["tag_categories"] = categories
    info: dict[str, object] = {"source": source}
    if name is not None:
        info["name"] = name
    (directory / "info.yaml").write_text(yamlio.dump(info))
    return directory


def test_name_from_tags(
    library: Path, home: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    old = _old_fetched(library, "x8ye3z", ["cyberpunk", "digital art", "interior"])
    _old_fetched(library, "k92q1d", ["artwork"])
    _record(library / "hand", (0, 255, 0), "hand.png")
    main(["index"])
    profile = home / ".cache/theme/.profiles/default-1"
    profile.mkdir(parents=True)
    (home / ".cache/theme/default").symlink_to(profile)
    (profile / "wallpaper").symlink_to(old / "wallhaven-x8ye3z.png")
    capsys.readouterr()
    caplog.set_level(logging.INFO)
    main(["name", "--from-tags", "--dry-run"])
    assert capsys.readouterr().out == ""
    assert f"would name {old} cyberpunk-interior-x8ye3z" in caplog.text
    assert old.is_dir()
    main(["name", "--from-tags"])
    named = [library / "general-k92q1d", library / "cyberpunk-interior-x8ye3z"]
    assert capsys.readouterr().out.split() == [str(path) for path in named]
    assert not old.exists()
    assert os.readlink(profile / "wallpaper") == str(named[1] / "wallhaven-x8ye3z.png")
    # The index knows the names at once: no `amo index` needed.
    main(["crop", "cyberpunk-interior-x8ye3z", "1:1"])
    assert capsys.readouterr().out == f"{named[1] / 'wallhaven-x8ye3z-1x1.png'}\n"
    caplog.clear()
    main(["name", "--from-tags"])
    assert "no unnamed record fetched from Wallhaven" in caplog.text
    with pytest.raises(SystemExit, match="1 of 1 record could not be named"):
        main(["name", "--from-tags", str(library / "hand")])
    assert "not fetched from Wallhaven" in caplog.text


def test_name_from_tags_force_renames_named_records(
    library: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    # Named from tags before their categories were kept: pixiv got into the name.
    categories = {"pixiv": "Companies & Logos", "sky": "Nature"}
    _old_fetched(library, "x8ye3z", ["pixiv", "sky"], categories, name="pixiv-sky-x8ye3z")
    _old_fetched(library, "k92q1d", ["artwork"], {"artwork": ""}, name="general-k92q1d")
    main(["index"])
    capsys.readouterr()
    caplog.set_level(logging.INFO)
    with pytest.raises(SystemExit, match="--force needs --from-tags"):
        main(["name", "--force", "a", "b"])
    main(["name", "--from-tags"])
    assert "no unnamed record fetched from Wallhaven" in caplog.text
    main(["name", "--from-tags", "--force"])
    assert capsys.readouterr().out == f"{library / 'sky-x8ye3z'}\n"
    assert f"{library / 'wallhaven-k92q1d'} keeps its name, general-k92q1d" in caplog.text
    assert yamlio.load((library / "sky-x8ye3z" / "info.yaml").read_text())["name"] == "sky-x8ye3z"


def test_name_takes_picture_and_name(library: Path) -> None:
    for argv in (["name"], ["name", "a"], ["name", "a", "b", "c"]):
        with pytest.raises(SystemExit, match="takes PICTURE NAME, or --from-tags"):
            main(argv)


def test_name_and_rename_by_hand(
    library: Path, home: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    nested = library / "travel" / "2024"
    _record(nested / "img-0412", (0, 0, 255), "img-0412.png")
    _record(library / "kept-here", (0, 255, 0), "kept.png")
    _record(library / "other", (255, 0, 0), "other.png")
    main(["index"])
    capsys.readouterr()
    # The directory is renamed where it is, not moved to the root.
    main(["name", str(nested / "img-0412"), "harbour-dawn"])
    assert capsys.readouterr().out == f"{nested / 'harbour-dawn'}\n"
    assert not (nested / "img-0412").exists()
    # A rename: the old name is free again, the index answers to the new one at once.
    main(["name", "harbour-dawn", "harbour-morning"])
    assert capsys.readouterr().out == f"{nested / 'harbour-morning'}\n"
    info = yamlio.load((nested / "harbour-morning" / "info.yaml").read_text())
    assert info["name"] == "harbour-morning"
    main(["name", str(library / "other"), "harbour-dawn"])
    capsys.readouterr()
    # --no-rename-directory keeps the directory.
    main(["name", "--no-rename-directory", str(library / "kept-here"), "meadow"])
    assert capsys.readouterr().out == f"{library / 'kept-here'}\n"
    assert yamlio.load((library / "kept-here" / "info.yaml").read_text())["name"] == "meadow"
    for argv, message in (
        (["meadow", "harbour-dawn"], "name 'harbour-dawn' is taken"),
        (["meadow", "meadow"], "named meadow already"),
        (["meadow", "Not A Name"], "does not match"),
    ):
        caplog.clear()
        with pytest.raises(SystemExit, match="1 of 1 record could not be named"):
            main(["name", *argv])
        assert message in caplog.text
    (library / "taken-dir").mkdir()
    caplog.clear()
    with pytest.raises(SystemExit):
        main(["name", "meadow", "taken-dir"])
    assert "taken-dir already exists" in caplog.text


def test_add_derived(
    indexed: dict[str, Path],
    library: Path,
    home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    edit = _save(np.full((36, 64, 3), (200, 0, 0), dtype=np.uint8), tmp_path / "darker.png")
    capsys.readouterr()
    caplog.set_level(logging.INFO)
    main(["add-derived", "--dry-run", str(library / "red"), str(edit)])
    assert capsys.readouterr().out == "" and edit.exists()
    assert f"would add {edit} as {library / 'red' / 'darker.png'}" in caplog.text
    main(["add-derived", str(library / "red"), str(edit), "--name", "red-darker.png"])
    assert capsys.readouterr().out == f"{library / 'red' / 'red-darker.png'}\n"
    info = yamlio.load((library / "red" / "info.yaml").read_text())
    assert info["files"]["red-darker.png"]["derived_from"] == "red.png"
    assert "crop" not in info["files"]["red-darker.png"]
    # Indexed at once; the original is still what amo list prints.
    assert "red-darker.png" in _index_rows(home)
    assert _list(capsys, "--hue", "red") == {"red"}
    with pytest.raises(SystemExit, match=r"lists red-darker\.png already"):
        main(["add-derived", str(library / "red"), str(library / "red" / "red-darker.png")])


def test_crop_unknown_picture(indexed: dict[str, Path]) -> None:
    with pytest.raises(SystemExit, match="no record has that name"):
        main(["crop", "nothing", "1:1"])


def _terminal(monkeypatch: pytest.MonkeyPatch, answer: str) -> None:
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(cli.sys.stderr, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda: answer)


def test_list_aspect_offers_crops_on_a_terminal(
    indexed: dict[str, Path],
    library: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _terminal(monkeypatch, "c")
    assert _list(capsys, "--aspect", "1:1", "--dark") == {"black-1x1"}
    assert (library / "black" / "black-1x1.png").is_file()
    assert "no file of that aspect ratio" not in caplog.text
    # Indexed: the next list finds it without asking.
    _terminal(monkeypatch, "no answer expected")
    assert _list(capsys, "--aspect", "1:1", "--dark") == {"black-1x1"}


def test_crop_interactive_needs_a_terminal(indexed: dict[str, Path]) -> None:
    with pytest.raises(SystemExit, match="--interactive needs a terminal"):
        main(["crop", "black", "1:1", "--interactive"])


def test_list_aspect_crops_interactively(
    indexed: dict[str, Path],
    library: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    placed = []

    def chooser(config: object, ratio: float, label: str) -> object:
        def choose(path: Path, width: int, height: int, box: tuple[int, ...]) -> tuple[int, ...]:
            placed.append((path.name, label, box))
            return (0, 0, 8, 8)

        return choose

    monkeypatch.setattr(cli, "chooser", chooser)
    _terminal(monkeypatch, "i")
    assert _list(capsys, "--aspect", "1:1", "--dark") == {"black-1x1"}
    assert placed and placed[0][:2] == ("black.png", "1x1")
    info = yamlio.load((library / "black" / "info.yaml").read_text())
    assert info["files"]["black-1x1.png"]["crop"] == [0, 0, 8, 8]


def test_list_aspect_declined_or_not_asked(
    indexed: dict[str, Path],
    library: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _terminal(monkeypatch, "n")
    assert _list(capsys, "--aspect", "1:1", "--dark") == {"black"}
    assert "no file of that aspect ratio for 1 picture" in caplog.text

    def never() -> str:
        raise AssertionError("asked")

    monkeypatch.setattr("builtins.input", never)
    assert _list(capsys, "--aspect", "1:1", "--dark", "--non-interactive") == {"black"}
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    assert _list(capsys, "--aspect", "1:1", "--dark") == {"black"}
    assert not (library / "black" / "black-1x1.png").exists()


def test_list_random(indexed: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    picked = _list(capsys, "--random", "2")
    assert len(picked) == 2
    assert picked <= {"black", "white", "red", "noise"}
    assert len(_list(capsys, "--random", "99")) == 4


def _shown_at(home: Path, image: Path, *days: int) -> None:
    """Record showings of `image`'s record on those days of November 2026."""
    with closing(connect(home / ".local/state/amontillado/index.sqlite")) as conn:
        for day in days:
            record_shown(conn, _id(image), datetime(2026, 11, day, tzinfo=UTC))


def _listed(capsys: pytest.CaptureFixture[str], *args: str) -> list[str]:
    capsys.readouterr()
    main(["list", *args])
    return [Path(line).stem for line in capsys.readouterr().out.splitlines()]


def test_list_order_least_shown(
    indexed: dict[str, Path], home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _shown_at(home, indexed["black"], 1, 2)
    _shown_at(home, indexed["white"], 5)
    _shown_at(home, indexed["red"], 3)
    # noise never shown; then one showing each, the oldest first; then two.
    assert _listed(capsys, "--order", "least-shown") == ["noise", "red", "white", "black"]
    assert _listed(capsys, "--order", "least-shown", "--random", "2") == ["noise", "red"]
    assert _listed(capsys, "--order", "least-shown", "--dark") == ["black"]
    assert _listed(capsys) == ["black", "noise", "red", "white"]


def test_list_order_least_shown_breaks_ties_at_random(
    indexed: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    firsts = set()
    for seed in range(20):
        random.seed(seed)
        firsts.add(_listed(capsys, "--order", "least-shown", "--random", "1")[0])
    assert firsts == {"black", "white", "red", "noise"}


def test_list_like_orders_by_palette_distance(
    indexed: dict[str, Path], library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _record(library / "maroon", (128, 0, 0), "maroon.png")
    main(["index"])
    red = str(indexed["red"])
    # Nearest first; red itself left out, given by its file or its directory.
    assert _listed(capsys, "--like", red) == ["maroon", "noise", "white", "black"]
    assert _listed(capsys, "--like", str(library / "red")) == ["maroon", "noise", "white", "black"]
    assert _listed(capsys, "--like", red, "--max-distance", "0.5") == ["maroon"]
    assert _listed(capsys, "--like", red, "--dark") == ["black"]


@pytest.mark.parametrize(
    "args",
    [
        ["--like", "x", "--order", "path"],
        ["--like", "x", "--random", "1"],
        ["--max-distance", "0.1"],
    ],
)
def test_list_like_refuses(indexed: dict[str, Path], args: list[str]) -> None:
    with pytest.raises(SystemExit, match="--like"):
        main(["list", *args])


def test_list_like_without_palettes(
    indexed: dict[str, Path],
    home: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An index not rebuilt since metrics version 3 has no palettes."""
    with sqlite3.connect(home / ".local/state/amontillado/index.sqlite") as conn:
        conn.execute("UPDATE files SET palette = NULL WHERE path NOT LIKE '%/red.png'")
    with pytest.raises(SystemExit, match="no matching pictures"):
        main(["list", "--like", str(indexed["red"])])
    assert "no palette yet: 3 pictures left out; run `amo index`" in caplog.text
    with pytest.raises(SystemExit, match=r"black\.png has no palette yet; run `amo index`"):
        main(["list", "--like", str(indexed["black"])])


def _group(capsys: pytest.CaptureFixture[str], *args: str) -> list[tuple[str, str]]:
    capsys.readouterr()
    main(["group", *args, "--non-interactive"])
    lines = capsys.readouterr().out.splitlines()
    return [(name, Path(path).stem) for name, path in (line.split("\t") for line in lines)]


@pytest.fixture
def grouped(indexed: dict[str, Path], library: Path) -> dict[str, Path]:
    """`indexed` and a maroon record, 0.36 from red (noise 0.73, white 0.74, black 0.90)."""
    indexed["maroon"] = _record(library / "maroon", (128, 0, 0), "maroon.png")
    main(["index"])
    return indexed


def test_group_picks_compatible_companions(
    grouped: dict[str, Path], capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    red = str(grouped["red"])
    monitors = ["--monitor", "DP-1=16:9", "--monitor", "HDMI-1=16:9"]
    assert _group(capsys, red, *monitors, "--max-distance", "0.5") == [
        ("DP-1", "red"),
        ("HDMI-1", "maroon"),
    ]
    assert "too few" not in caplog.text
    # Nothing within 0.05: the nearest beyond fill in, with a warning.
    three = [*monitors, "--monitor", "DP-2=16:9"]
    assert _group(capsys, red, *three, "--order", "nearest") == [
        ("DP-1", "red"),
        ("HDMI-1", "maroon"),
        ("DP-2", "noise"),
    ]
    assert "the nearest beyond for HDMI-1, DP-2" in caplog.text


def test_group_json(grouped: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    main(["group", str(grouped["red"]), "--monitor", "A=16:9", "--monitor", "B=16:9",
          "--order", "nearest", "--format", "json"])  # fmt: skip
    data = json.loads(capsys.readouterr().out)
    assert data["primary"] == "A"
    first, second = data["monitors"]
    assert first == {"name": "A", "aspect": "16:9", "path": str(grouped["red"]),
                     "record": _id(grouped["red"]), "distance": 0.0}  # fmt: skip
    assert (second["name"], second["path"]) == ("B", str(grouped["maroon"]))
    assert second["distance"] == pytest.approx(0.36, abs=0.01)


def test_group_primary_is_the_least_shown_match(
    grouped: dict[str, Path], home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("black", "white", "noise", "maroon"):
        _shown_at(home, grouped[name], 1)
    monitors = ["--monitor", "A=16:9", "--monitor", "B=16:9", "--order", "nearest"]
    assert _group(capsys, *monitors) == [("A", "red"), ("B", "maroon")]
    # Filters apply to every monitor's picture: only black is dark (private is NSFW).
    with pytest.raises(SystemExit, match="none left for monitor B"):
        _group(capsys, *monitors, "--dark")


def test_group_falls_back_to_the_default_file(
    grouped: dict[str, Path], capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    red = str(grouped["red"])
    assert _group(capsys, red, "--monitor", "UW=21:9")[0] == ("UW", "red")
    assert f"UW: no 21:9 file for {red}; using the default file" in caplog.text


@pytest.mark.parametrize(
    ("args", "error"),
    [
        (["--monitor", "A=16:9", "--monitor", "A=21:9"], "each monitor once"),
        (["--monitor", "A=16:9", "/nowhere"], "no such file"),
    ],
)
def test_group_refuses(grouped: dict[str, Path], args: list[str], error: str) -> None:
    with pytest.raises(SystemExit, match=error):
        main(["group", *args])


def test_group_passes_over_primaries_that_cannot_fill_the_set(
    grouped: dict[str, Path],
    home: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    # red is shown least, but its nearest (maroon) is 0.36 away; white's (noise) is 0.30.
    for day, name in enumerate(("white", "noise", "black", "maroon"), start=1):
        _shown_at(home, grouped[name], day)
    monitors = ["--monitor", "A=16:9", "--monitor", "B=16:9"]
    assert _group(capsys, *monitors, "--max-distance", "0.31") == [("A", "white"), ("B", "noise")]
    assert "no matching picture has" not in caplog.text
    # None can: the least shown, with the nearest beyond.
    assert _group(capsys, *monitors, "--max-distance", "0.2") == [("A", "red"), ("B", "maroon")]
    assert "no matching picture has 1 companion within 0.2" in caplog.text
    # A PICTURE given is used as it is.
    assert _group(capsys, str(grouped["red"]), *monitors, "--max-distance", "0.31")[0] == (
        "A",
        "red",
    )


def _categorise(pictures: dict[str, Path], **by_name: str) -> None:
    for name, category in by_name.items():
        info = pictures[name].parent / "info.yaml"
        data = yamlio.load(info.read_text())
        data["source"] = {"site": "wallhaven", "category": category}
        info.write_text(yamlio.dump(data))
    main(["index"])


def test_group_keep_category(grouped: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    # maroon is red's nearest, but a drawing: the photo noise is the nearest photo.
    _categorise(grouped, red="general", maroon="anime", noise="general", white="anime")
    red = str(grouped["red"])
    args = [red, "--monitor", "A=16:9", "--monitor", "B=16:9", "--order", "nearest"]
    assert _group(capsys, *args)[1] == ("B", "maroon")
    assert _group(capsys, *args, "--keep-category") == [("A", "red"), ("B", "noise")]
    # A filter, not a preference: no third general picture.
    with pytest.raises(SystemExit, match=r"none left for monitor C.*general pictures only"):
        _group(capsys, *args, "--monitor", "C=16:9", "--keep-category")
    # black has no category: refused as the primary, never a companion.
    with pytest.raises(SystemExit, match="has no category; --keep-category needs one"):
        _group(capsys, str(grouped["black"]), "--monitor", "A=16:9", "--keep-category")


def _predicates(home: Path, **predicates: str) -> None:
    config = home / ".config/amontillado/config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    entries = {name: {"cmd": cmd, "description": f"{name}!"} for name, cmd in predicates.items()}
    config.write_text(yamlio.dump({"group": {"predicates": entries}}))


@pytest.mark.skipif(shutil.which("jq") is None, reason="needs jq")
def test_group_predicate(
    grouped: dict[str, Path],
    home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = tmp_path / "asked"
    monkeypatch.setenv("MAROON_DIR", str(grouped["maroon"].parent))
    # Logs each candidate, rejects maroon (red's nearest) by its record directory, and checks
    # that the primary's JSON is red's.
    reject_maroon = (
        f'basename "$(jq -r .file.path "$AMO_CANDIDATE")" >> {log}; '
        '[ "$(jq -r .record.directory "$AMO_CANDIDATE")" = "$MAROON_DIR" ] && exit 1; '
        f'jq -e \'.record.id == "{_id(grouped["red"])}"\' "$AMO_PRIMARY" >/dev/null'
    )
    _predicates(home, no_maroon=reject_maroon, everything="true")
    args = [str(grouped["red"]), "--monitor", "A=16:9", "--monitor", "B=16:9"]
    args += ["--order", "nearest"]
    assert _group(capsys, *args)[1] == ("B", "maroon")
    assert _group(capsys, *args, "--predicate", "no_maroon", "--predicate", "everything") == [
        ("A", "red"),
        ("B", "noise"),
    ]
    # Asked lazily, nearest first: maroon (rejected), then noise (accepted); no more.
    assert log.read_text() == "maroon.png\nnoise.png\n"
    # A filter: nothing accepted is an error, even beyond the bound.
    with pytest.raises(SystemExit, match="no picture accepted by the predicates for monitor B"):
        _group(capsys, *args, "--predicate-cmd", "exit 1")


@pytest.mark.skipif(shutil.which("jq") is None, reason="needs jq")
def test_group_predicate_passes_over_primaries_left_alone(
    grouped: dict[str, Path],
    home: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for day, name in enumerate(("white", "noise", "black", "maroon"), start=1):
        _shown_at(home, grouped[name], day)
    monitors = ["--monitor", "A=16:9", "--monitor", "B=16:9", "--max-distance", "0.5"]
    assert _group(capsys, *monitors) == [("A", "red"), ("B", "maroon")]
    # Nothing goes with red once maroon is rejected: the next least shown, white, is primary.
    monkeypatch.setenv("MAROON_DIR", str(grouped["maroon"].parent))
    reject = '[ "$(jq -r .record.directory "$AMO_CANDIDATE")" != "$MAROON_DIR" ]'
    assert _group(capsys, *monitors, "--predicate-cmd", reject) == [("A", "white"), ("B", "noise")]


def test_group_predicate_errors(
    grouped: dict[str, Path], home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _predicates(home, broken="exit 3")
    args = ["group", str(grouped["red"]), "--monitor", "A=16:9", "--monitor", "B=16:9"]
    with pytest.raises(SystemExit, match="predicate broken failed: exit status 3"):
        main([*args, "--predicate", "broken"])
    with pytest.raises(SystemExit, match=r"no predicate 'nope' under group\.predicates"):
        main([*args, "--predicate", "nope"])
    with pytest.raises(SystemExit, match="--predicate-cmd is empty"):
        main([*args, "--predicate-cmd", " "])
    with pytest.raises(SystemExit, match="at least one --monitor"):
        main(["group"])
    capsys.readouterr()
    main(["group", "--list-predicates"])
    assert capsys.readouterr().out == "broken  broken!\n"


def _setter(home: Path, command: str) -> None:
    config = home / ".config/amontillado/config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(yamlio.dump({"group": {"setter": command}}))


def _shown_counts(home: Path) -> dict[str, int]:
    with closing(connect(home / ".local/state/amontillado/index.sqlite")) as conn:
        return {record_id: count for record_id, (count, _) in usage(conn).items()}


def test_group_apply_runs_the_setter_per_monitor(
    grouped: dict[str, Path], home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "set.log"
    _setter(home, f'echo noise; printf "%s %s\\n" "$AMO_MONITOR" "$AMO_WALLPAPER" >> {log}')
    red = str(grouped["red"])
    args = [red, "--monitor", "A=16:9", "--monitor", "B=16:9", "--order", "nearest"]
    capsys.readouterr()
    main(["group", *args, "--apply", "--dry-run", "--non-interactive"])
    assert not log.exists() and _shown_counts(home) == {}
    main(["group", *args, "--apply", "--non-interactive"])
    out = capsys.readouterr().out
    assert "noise" not in out  # the setter's output goes to stderr
    assert log.read_text() == f"A {red}\nB {grouped['maroon']}\n"
    assert _shown_counts(home) == {_id(grouped["red"]): 1, _id(grouped["maroon"]): 1}


def test_group_apply_fails_after_trying_every_monitor(grouped: dict[str, Path], home: Path) -> None:
    _setter(home, 'test "$AMO_MONITOR" = A && : "$AMO_WALLPAPER"')
    args = ["group", str(grouped["red"]), "--monitor", "A=16:9", "--monitor", "B=16:9"]
    with pytest.raises(SystemExit, match=r"group\.setter failed for B: exit status 1"):
        main([*args, "--apply", "--non-interactive"])
    assert _shown_counts(home) == {_id(grouped["red"]): 1}


def test_group_apply_needs_a_setter(grouped: dict[str, Path]) -> None:
    with pytest.raises(SystemExit, match=r"--apply needs group\.setter"):
        main(["group", "--monitor", "A=16:9", "--apply"])


@pytest.mark.parametrize("monitor", ["16:9", "=16:9", "A=wide"])
def test_group_monitor_syntax(grouped: dict[str, Path], monitor: str) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["group", "--monitor", monitor])
    assert raised.value.code == 2


def _stale_warning(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> str | None:
    caplog.clear()
    _list(capsys)
    lines = [r.getMessage() for r in caplog.records if "changed since the last" in r.getMessage()]
    return lines[0] if lines else None


def test_list_warns_when_the_library_changed_since_amo_index(
    indexed: dict[str, Path],
    library: Path,
    home: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert _stale_warning(capsys, caplog) is None
    # What amo does itself keeps the index current: no warning.
    loose = _save(np.full((36, 64, 3), (0, 0, 255), dtype=np.uint8), library / "blue.png")
    main(["add", str(loose)])
    main(["crop", str(library / "red"), "1:1"])
    main(["name", str(library / "white"), "snow"])
    assert _stale_warning(capsys, caplog) is None
    # Done by hand, it is reported, never re-indexed.
    _record(library / "green", (0, 255, 0))
    shutil.rmtree(indexed["black"].parent)
    _save(np.full((36, 64, 3), (9, 9, 9), dtype=np.uint8), library / "noise" / "more.png")
    assert _stale_warning(capsys, caplog) == (
        "the library has changed since the last `amo index` (1 record added, 1 record removed, "
        "1 record changed); run `amo index`"
    )
    main(["index"])
    assert _stale_warning(capsys, caplog) is None


def test_list_stale_check_can_be_turned_off(
    indexed: dict[str, Path],
    library: Path,
    home: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _record(library / "green", (0, 255, 0))
    assert _stale_warning(capsys, caplog) is not None
    config = home / ".config/amontillado/config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("check_stale_index: false\n")
    assert _stale_warning(capsys, caplog) is None


def test_list_format_rofi(
    indexed: dict[str, Path], library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (library / "white" / ".amo" / "thumbnail.jpg").unlink()
    capsys.readouterr()
    main(["list", "--format", "rofi", "--dark"])
    black = indexed["black"]
    thumbnail = black.parent / ".amo/thumbnail.jpg"
    # rofi shows the record's directory name and returns the path.
    assert capsys.readouterr().out == f"{black}\0icon\x1f{thumbnail}\x1fdisplay\x1fblack\n"
    # A record without a thumbnail (gone since the last index) still gets its label.
    main(["list", "--format", "rofi", "--light"])
    assert capsys.readouterr().out == f"{indexed['white']}\0display\x1fwhite\n"


def test_list_format_rofi_labels_files_of_a_record_with_several(
    indexed: dict[str, Path], library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["crop", str(library / "red"), "1:1"])
    capsys.readouterr()
    main(["list", "--format", "rofi", "--hue", "red"])
    out = capsys.readouterr().out
    assert out.endswith("\x1fdisplay\x1fred.png\n")
    main(["list", "--format", "rofi", "--hue", "red", "--aspect", "1:1"])
    assert capsys.readouterr().out.endswith("\x1fdisplay\x1fred-1x1.png\n")


def test_list_no_match_fails(indexed: dict[str, Path]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["list", "--hue", "green"])
    assert exc.value.code == "amontillado: no matching pictures"


def test_list_skips_missing_files(
    indexed: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    indexed["white"].unlink()
    assert _list(capsys) == {"black", "red", "noise"}
    assert "missing from disk or its annex content dropped: 1 file" in caplog.text


def test_list_excludes_the_current_nsfw_root(
    library: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Indexed while ~/walls was a library root; then the config makes it the NSFW root.
    config = home / ".config/amontillado/config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(f"library_roots: [{home}/walls]\n")
    _record(library / "plain", name="plain.png")
    _record(home / "walls" / "private", name="private.png")
    main(["index"])
    assert _list(capsys) == {"plain", "private"}
    config.write_text(f"nsfw_root: {home}/walls\n")
    assert _list(capsys) == {"plain"}


@pytest.mark.parametrize(
    ("flags", "message"),
    [
        (["--dark", "--light"], "not allowed with argument"),
        (["--purity", "sfw,lewd"], "unknown purity: lewd"),
        (["--random", "0"], "must be at least 1"),
        (["--hue", "teal"], "invalid choice"),
        (["--aspect", "21"], "must be W:H"),
        (["--aspect", "21:0"], "must be W:H"),
    ],
)
def test_list_bad_arguments(
    indexed: dict[str, Path], capsys: pytest.CaptureFixture[str], flags: list[str], message: str
) -> None:
    with pytest.raises(SystemExit):
        main(["list", *flags])
    assert message in capsys.readouterr().err


def test_list_without_an_index(library: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["list"])
    assert "run `amo index` first" in exc.value.code


def _usage(home: Path) -> list[tuple[str, int]]:
    with sqlite3.connect(home / ".local/state/amontillado/index.sqlite") as conn:
        return conn.execute("SELECT id, shown_count FROM usage ORDER BY id").fetchall()


def _id(image: Path) -> str:
    return yamlio.load((image.parent / "info.yaml").read_text())["id"]


def test_shown_records_by_record_id(indexed: dict[str, Path], home: Path) -> None:
    black, red = indexed["black"], indexed["red"]
    black_id = _id(black)
    main(["shown", str(black), str(red)])
    main(["shown", black_id[:12], str(black.parent)])
    red_id = _id(red)
    moved = red.rename(home / "elsewhere.png")
    main(["shown", str(moved)])
    assert dict(_usage(home)) == {black_id: 3, red_id: 2}


def test_shown_by_name(indexed: dict[str, Path], home: Path) -> None:
    info = indexed["red"].parent / "info.yaml"
    data = yamlio.load(info.read_text())
    data["name"] = "sunset"
    info.write_text(yamlio.dump(data))
    main(["index"])
    main(["shown", "sunset"])
    assert _usage(home) == [(data["id"], 1)]


def test_shown_dry_run_records_nothing(indexed: dict[str, Path], home: Path) -> None:
    main(["shown", "--dry-run", str(indexed["black"])])
    assert _usage(home) == []


def test_shown_unknown_picture_records_nothing(indexed: dict[str, Path], home: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["shown", str(indexed["black"]), "nothing"])
    assert exc.value.code == "amontillado: nothing: no such file, and no record has that name or id"
    assert _usage(home) == []


def test_shown_without_an_index(library: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["shown", "x"])
    assert "run `amo index` first" in exc.value.code


def test_usage_survives_reindexing(indexed: dict[str, Path], home: Path) -> None:
    main(["shown", str(indexed["red"])])
    main(["index"])
    assert len(_usage(home)) == 1


def test_add_indexes_and_refuses_duplicates(
    library: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["index"])
    loose = _save(np.zeros((36, 64, 3), dtype=np.uint8), library / "a.png")
    copy = home / "copy.png"
    copy.write_bytes(loose.read_bytes())
    main(["add", "--name", "night", str(loose)])
    assert _index_rows(home) == ["a.png"]
    assert _list(capsys) == {"a"}
    main(["shown", "night"])
    with pytest.raises(SystemExit) as exc:
        main(["add", str(copy)])
    assert exc.value.code == "amontillado: 1 of 1 files could not be added"
    assert copy.exists()
    main(["add", "--force", str(copy)])
    assert sorted(_index_rows(home)) == ["a.png", "copy.png"]
    main(["index", "--check"])


def _letterboxed(path: Path) -> Path:
    """A 400x200 noisy picture between black bars of 30 rows above and 20 below."""
    pixels = np.zeros((200, 400, 3), dtype=np.uint8)
    pixels[30:180] = np.random.default_rng(0).integers(60, 230, (150, 400, 3), dtype=np.uint8)
    return _save(pixels, path)


def test_add_warns_of_a_letterbox_and_crop_cuts_it_off(
    library: Path,
    home: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    main(["index"])
    main(["add", "--name", "film", str(_letterboxed(home / "film.png"))])
    directory = library / "film"
    assert f"`amo crop {directory} --letterbox` crops the bars off" in caplog.text
    assert not (directory / "film-content.png").exists()
    caplog.clear()
    with caplog.at_level(logging.INFO):
        main(["index"])
    assert "1 letterboxed (amo crop --letterbox)" in caplog.text
    with pytest.raises(SystemExit, match="W:H or --letterbox"):
        main(["crop", "film"])
    with pytest.raises(SystemExit, match="W:H or --letterbox"):
        main(["crop", "film", "1:1", "--letterbox"])
    capsys.readouterr()
    main(["crop", "film", "--letterbox"])
    assert capsys.readouterr().out == f"{directory / 'film-content.png'}\n"
    assert _list(capsys) == {"film-content"}  # the default file now
    caplog.clear()
    with caplog.at_level(logging.INFO):
        main(["index"])
    assert "letterboxed" not in caplog.text


def test_add_offers_the_letterbox_crop_on_a_terminal(
    library: Path, home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    main(["index"])
    _terminal(monkeypatch, "")
    main(["add", "--name", "film", str(_letterboxed(home / "film.png"))])
    assert _list(capsys) == {"film-content"}
    _terminal(monkeypatch, "n")
    main(["add", "--name", "other", str(_letterboxed(home / "other.jpg"))])
    assert not (library / "other" / "other-content.jpg").exists()
    # --non-interactive never asks.
    monkeypatch.setattr("builtins.input", lambda: pytest.fail("asked"))
    main(
        [
            "add",
            "--non-interactive",
            "--force",
            "--name",
            "third",
            str(_letterboxed(home / "third.png")),
        ]
    )
    assert not (library / "third" / "third-content.png").exists()


def test_add_refuses_a_taken_name(library: Path, home: Path) -> None:
    main(["add", "--name", "night", str(_save(np.zeros((36, 64, 3), np.uint8), home / "a.png"))])
    other = _save(np.full((36, 64, 3), 9, np.uint8), home / "b.png")
    with pytest.raises(SystemExit):
        main(["add", "--name", "night", str(other)])
    assert other.exists()


def test_add_records_provenance(library: Path, home: Path) -> None:
    image = _save(np.zeros((36, 64, 3), dtype=np.uint8), home / "sunset.png")
    main(
        [
            "add",
            "--name",
            "sunset",
            "--source-url",
            "https://commons.wikimedia.org/wiki/File:Sunset.png",
            "--site",
            "wikimedia-commons",
            "--license",
            "CC0-1.0",
            "--author",
            "A. Painter",
            "--title",
            "Sunset",
            "--tags",
            "sunset, sea",
            str(image),
        ]
    )
    info = yamlio.load((library / "sunset" / "info.yaml").read_text())
    assert info["source"] == {
        "site": "wikimedia-commons",
        "url": "https://commons.wikimedia.org/wiki/File:Sunset.png",
        "title": "Sunset",
        "author": "A. Painter",
        "license": "CC0-1.0",
        "tags": ["sunset", "sea"],
    }
    assert info["fetched"] is None
    with sqlite3.connect(home / ".local/state/amontillado/index.sqlite") as conn:
        row = conn.execute("SELECT license, author, title, source_site FROM records").fetchone()
    assert row == ("CC0-1.0", "A. Painter", "Sunset", "wikimedia-commons")
    # Healing keeps it: source is authored.
    main(["index"])
    assert yamlio.load((library / "sunset" / "info.yaml").read_text())["source"] == info["source"]


def test_add_from_json(library: Path, home: Path) -> None:
    for name, value in (("a", 0), ("b", 255)):
        _save(np.full((36, 64, 3), value, dtype=np.uint8), home / f"{name}.png")
    seeds = home / "seeds.json"
    seeds.write_text(
        '[{"file": "a.png", "name": "first", "license": "CC0-1.0"},'
        ' {"file": "b.png", "author": "B", "purity": "sketchy"}]'
    )
    main(["add", "--from-json", str(seeds)])
    first = yamlio.load((library / "first" / "info.yaml").read_text())
    assert (first["name"], first["source"]) == ("first", {"license": "CC0-1.0"})
    nsfw = home / ".local/share/amontillado/library-nsfw"
    second = yamlio.load((nsfw / "b" / "info.yaml").read_text())
    assert second["source"] == {"author": "B", "purity": "sketchy"}


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--source-url", "https://x.org/", "a.png", "b.png"], "--source-url takes one FILE"),
        (["--from-json", "x.json", "a.png"], "--from-json takes no FILEs"),
        (["--license", "CC0-1.0"], "no FILE"),
        (["--uploaded", "yesterday", "a.png"], "not an ISO 8601"),
    ],
)
def test_add_provenance_usage_errors(library: Path, args: list[str], message: str) -> None:
    with pytest.raises(SystemExit, match=message):
        main(["add", *args])


def test_add_dry_run_changes_nothing(library: Path, home: Path) -> None:
    loose = _save(np.zeros((36, 64, 3), dtype=np.uint8), library / "a.png")
    main(["add", "--dry-run", str(loose)])
    assert loose.exists()
    assert not (library / "a").exists()
    assert _index_rows(home) == []


def test_add_name_takes_one_file(library: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["add", "--name", "x", "a.png", "b.png"])
    assert exc.value.code == "amontillado: --name takes one FILE"


@pytest.fixture
def web(wallhaven: FakeWeb, monkeypatch: pytest.MonkeyPatch) -> FakeWeb:
    """`amo fetch` talks to the fake Wallhaven, and never sleeps."""
    clock = FakeClock()

    def client(api_key: str | None) -> Client:
        return Client(api_key, get=wallhaven.get, sleep=clock.sleep, clock=clock)

    monkeypatch.setattr("amontillado.cli.Client", client)
    monkeypatch.delenv("WALLHAVEN_API_KEY", raising=False)
    return wallhaven


def test_fetch_prints_and_indexes_what_it_keeps(
    library: Path, web: FakeWeb, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["fetch", "--dark"])
    kept = library / "night-sky-aaa111" / "wallhaven-aaa111.jpg"
    assert capsys.readouterr().out.splitlines() == [str(kept)]
    assert _list(capsys, "--dark") == {"wallhaven-aaa111"}
    main(["index", "--check"])


def test_fetch_reports_its_writes_to_on_change(library: Path, home: Path, web: FakeWeb) -> None:
    _write_config(home, {"on_change": 'cat > "$HOME/payload.json"'})
    main(["fetch", "--dark"])
    payload = json.loads((home / "payload.json").read_text())
    assert payload["command"] == "fetch"
    assert [(c["type"], c["path"]) for c in payload["changes"]] == [
        ("info", "night-sky-aaa111/info.yaml"),
        ("file", "night-sky-aaa111/wallhaven-aaa111.jpg"),
        ("file", "night-sky-aaa111/.amo/thumbnail.jpg"),
    ]
    assert payload["changes"][0]["before"] is None


def test_fetch_fails_when_short_of_count(library: Path, web: FakeWeb) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["fetch", "--dark", "--count", "3"])
    assert exc.value.code == "amontillado: 1 of 3 wanted"


def test_fetch_dry_run_prints_pages(
    library: Path, web: FakeWeb, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["fetch", "--light", "--dry-run"])
    assert capsys.readouterr().out.splitlines() == ["https://wallhaven.cc/w/bbb222"]
    assert list(library.iterdir()) == []


def test_fetch_passes_wallhaven_filters(library: Path, web: FakeWeb) -> None:
    args = ["--tags", "+night", "--category", "general,people", "--atleast", "2560x1440"]
    args += ["--ratio", "16:9,21x9", "--color", "#42415A", "--dry-run"]
    with pytest.raises(SystemExit):
        main(["fetch", *args])
    query = dict(parse_qsl(urlsplit(web.urls()[0]).query))
    assert query == {
        "sorting": "random",
        "purity": "100",
        "q": "+night",
        "categories": "101",
        "atleast": "2560x1440",
        "ratios": "16x9,21x9",
        # Not a swatch: replaced by the nearest one.
        "colors": "424153",
        "page": "1",
    }


@pytest.mark.parametrize(
    "args",
    [
        ["--ratio", "21/9"],
        ["--atleast", "2560"],
        ["--color", "red"],
        ["--category", "cats"],
        ["--purity", "sfw,lewd"],
        ["--busy-from", "both"],
        ["--dark", "--light"],
    ],
)
def test_fetch_rejects_bad_arguments(args: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        get_cli_arguments(["fetch", *args])
    assert exc.value.code == 2


def test_fetch_nsfw_needs_an_api_key(library: Path, web: FakeWeb) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["fetch", "--purity", "sfw,nsfw"])
    assert "nsfw needs a Wallhaven API key" in str(exc.value.code)
    assert web.requests == []


def test_fetch_nsfw_sends_the_api_key(
    library: Path, web: FakeWeb, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WALLHAVEN_API_KEY", "secret-key")
    main(["fetch", "--purity", "sfw,nsfw"])
    assert all(headers.get("X-API-Key") == "secret-key" for _, headers in web.requests)


def test_fetch_sfw_never_looks_up_the_key(
    library: Path, web: FakeWeb, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WALLHAVEN_API_KEY", "secret-key")
    main(["fetch"])
    assert all("X-API-Key" not in headers for _, headers in web.requests)


def test_fetch_refresh_tags(
    library: Path,
    web: FakeWeb,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    old = _old_fetched(library, "aaa111", ["night sky"])
    changed = _old_fetched(library, "bbb222", ["old tag"])
    current = _old_fetched(library, "ccc333", ["cave"], {"cave": "Nature"})
    _record(library / "hand", (0, 255, 0), "hand.png")
    main(["index"])
    capsys.readouterr()
    caplog.set_level(logging.INFO)
    main(["fetch", "--refresh-tags", "--dry-run"])
    assert capsys.readouterr().out == ""
    assert f"would write the tags of {old}" in caplog.text
    assert "tag_categories" not in (old / "info.yaml").read_text()
    # ccc333 has its categories: not asked for.
    assert sorted(web.urls()) == [f"{API}/w/aaa111", f"{API}/w/bbb222"]
    web.requests.clear()
    main(["fetch", "--refresh-tags"])
    assert capsys.readouterr().out.split() == [str(old), str(changed)]
    assert "Wallhaven's tags changed: added snow; removed old tag" in caplog.text
    assert yamlio.load((old / "info.yaml").read_text())["source"]["tag_categories"] == {
        "night sky": "Nature"
    }
    # The index has the new tag list at once.
    assert _list(capsys, "--tag", "snow") == {"wallhaven-bbb222"}
    web.requests.clear()
    main(["fetch", "--refresh-tags"])
    assert web.requests == []
    # A PICTURE given is asked for whatever its info file has.
    main(["fetch", "--refresh-tags", str(current)])
    assert web.urls() == [f"{API}/w/ccc333"]
    assert capsys.readouterr().out == ""
    web.routes.pop(f"{API}/w/ccc333")
    with pytest.raises(SystemExit, match="1 of 1 record could not be refreshed"):
        main(["fetch", "--refresh-tags", str(current)])


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--refresh-tags", "--dark"], "--refresh-tags takes no look filters"),
        (["--refresh-tags", "--count", "2", "--tags", "x"], "takes no --tags, --count"),
        (["somewhere"], "fetch takes PICTUREs only with --refresh-tags"),
    ],
)
def test_fetch_refresh_tags_takes_only_pictures(
    library: Path, web: FakeWeb, args: list[str], message: str
) -> None:
    with pytest.raises(SystemExit, match=message):
        main(["fetch", *args])
    assert web.requests == []


def test_fetch_exits_when_the_search_fails(library: Path, web: FakeWeb) -> None:
    web.routes.clear()
    with pytest.raises(SystemExit) as exc:
        main(["fetch"])
    assert str(exc.value.code).startswith("amontillado: https://wallhaven.cc/api/v1/search?")
    assert str(exc.value.code).endswith("HTTP 404")


def test_fetch_keeps_mismatches_without_printing_them(
    library: Path, web: FakeWeb, capsys: pytest.CaptureFixture[str]
) -> None:
    noise = np.random.default_rng(0).integers(0, 256, size=(243, 432, 3), dtype=np.uint8)
    web.add("https://th.wallhaven.cc/lg/aa/aaa111.jpg", _encode(noise))
    with pytest.raises(SystemExit):
        main(["fetch", "--busy", "--max-candidates", "1", "--discard-mismatches"])
    assert list(library.iterdir()) == []
    with pytest.raises(SystemExit) as exc:
        main(["fetch", "--busy", "--max-candidates", "1"])
    assert exc.value.code == "amontillado: 0 of 1 wanted"
    assert capsys.readouterr().out == ""
    assert (library / "night-sky-aaa111" / "wallhaven-aaa111.jpg").is_file()


def _encode(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, "PNG")
    return buffer.getvalue()


def test_fetch_test_set_prints_buckets_and_fails_when_one_is_empty(
    library: Path, web: FakeWeb, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["fetch", "--test-set"])
    assert exc.value.code == (
        "amontillado: empty buckets: muted, saturated, busy, sparse, monochrome, multi-hue"
    )
    assert capsys.readouterr().out.splitlines() == [
        f"dark\t{library / 'night-sky-aaa111' / 'wallhaven-aaa111.jpg'}",
        f"light\t{library / 'snow-bbb222' / 'wallhaven-bbb222.png'}",
    ]


def test_fetch_test_set_dry_run_prints_pages(
    library: Path, web: FakeWeb, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        main(["fetch", "--test-set", "--dry-run"])
    assert capsys.readouterr().out.splitlines() == [
        "dark\thttps://wallhaven.cc/w/aaa111",
        "light\thttps://wallhaven.cc/w/bbb222",
    ]


@pytest.mark.parametrize("args", [["--dark"], ["--hue", "red"], ["--count", "2"]])
def test_fetch_test_set_takes_no_look_filters_or_count(
    library: Path, web: FakeWeb, args: list[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["fetch", "--test-set", *args])
    assert exc.value.code == "amontillado: --test-set takes no look filters or --count"
    assert web.requests == []


def _write_config(home: Path, data: dict[str, object]) -> None:
    path = home / ".config" / "amontillado" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yamlio.dump(data))


def test_palette_from_a_picture(
    indexed: dict[str, Path], fake_matugen: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    red = indexed["red"]
    main(["palette", str(red.parent), "--hues", "generator", "--no-adjust"])
    palette = yamlio.load(capsys.readouterr().out)
    assert palette["name"] == _id(red)
    source = palette["source"]
    assert (source["picture"], source["file"], source["lightness"]) == (_id(red), "red.png", 0.628)
    assert (source["generator"], source["hues"]) == ("matugen 4.2.0", "generator")
    assert set(palette["variants"]) == {"dark", "light"}
    dark = palette["variants"]["dark"]
    assert dark["roles"]["accent"] == "#99ccfa"
    assert dark["base24"]["base00"] == "#0f1113"
    assert len(dark["base24"]) == 24
    # matugen ran on the record's default file.
    assert f"image {red} " in fake_matugen.read_text()


def test_palette_from_a_picture_is_contrast_checked(
    indexed: dict[str, Path], fake_matugen: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["palette", str(indexed["red"]), "--hues", "generator"])
    palette = yamlio.load(capsys.readouterr().out)
    # matugen's base16 block is near-black on this picture; adjusting moves what it can.
    assert palette["variants"]["dark"]["adjusted"]


def test_palette_hues_from_the_config(
    indexed: dict[str, Path], home: Path, fake_matugen: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["palette", str(indexed["red"])])
    palette = yamlio.load(capsys.readouterr().out)
    assert palette["source"]["hues"] == "amontillado"
    # Named hues pass the contrast check as they are.
    assert "adjusted" not in palette["variants"]["dark"]
    _write_config(home, {"theme": {"hues": "generator"}})
    main(["palette", str(indexed["red"]), "--no-adjust"])
    assert yamlio.load(capsys.readouterr().out)["source"]["hues"] == "generator"


def test_palette_from_a_picture_errors(
    library: Path, home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["palette", "x"])
    assert "run `amo index` first" in exc.value.code
    main(["index"])
    with pytest.raises(SystemExit) as exc:
        main(["palette", "nothing", "--hues", "generator"])
    assert exc.value.code == "amontillado: nothing: no such file, and no record has that name or id"
    image = _record(library / "a")
    main(["index"])
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(SystemExit) as exc:
        main(["palette", str(image), "--hues", "generator"])
    assert exc.value.code == (
        "amontillado: no palette generator installed: install one of matugen, wallust"
    )


def test_theme_apply_a_picture(indexed: dict[str, Path], home: Path, fake_matugen: Path) -> None:
    _write_config(home, {"theme": {"hues": "generator", "apps": {"json": {}}}})
    red = indexed["red"]
    main(["theme", "apply", _id(red)[:10]])
    profile = home / ".cache" / "theme" / "default"
    assert Path(profile / "wallpaper").readlink() == red
    palette = yamlio.load((profile / "palette.yaml").read_text())
    assert palette["source"]["picture"] == _id(red)
    assert (profile / "palette.json").is_file()
    assert _usage(home) == [(_id(red), 1)]
    # Re-rendering keeps the picture.
    main(["theme", "apply"])
    assert Path(profile / "wallpaper").readlink() == red
    assert _usage(home) == [(_id(red), 1)]
    # Behind an inactive profile the picture is not shown.
    main(["theme", "apply", str(red), "--profile", "other", "--no-activate"])
    assert Path(home / ".cache/theme/other/wallpaper").readlink() == red
    assert _usage(home) == [(_id(red), 1)]
    with pytest.raises(SystemExit) as exc:
        main(["theme", "apply", str(red), "--app", "json"])
    assert exc.value.code == "amontillado: PICTURE with --app: a new picture re-renders every app"
    with pytest.raises(SystemExit):
        main(["theme", "apply", str(red), "--palette", "p"])


def test_theme_apply_dry_run_records_nothing(
    indexed: dict[str, Path], home: Path, fake_matugen: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_config(home, {"theme": {"hues": "generator"}})
    main(["theme", "apply", str(indexed["red"]), "--dry-run"])
    directory = Path(capsys.readouterr().out.splitlines()[0])
    assert Path(directory / "wallpaper").readlink() == indexed["red"]
    assert _usage(home) == []


@pytest.fixture
def sourced(indexed: dict[str, Path], home: Path) -> dict[str, Path]:
    """`indexed`, with provenance: black and the NSFW private one from Wallhaven, red from
    Commons; white and noise say nothing. Black was shown once."""
    sources = {
        "black": {"site": "wallhaven", "category": "general", "tags": ["night", "city"],
                  "license": "CC-BY-4.0", "author": "Ann", "uploaded": "2024-05-01"},
        "private": {"site": "wallhaven", "category": "general", "tags": ["night", "city"]},
        "red": {"site": "wikimedia-commons", "tags": ["night"], "license": "cc0-1.0",
                "author": "Bo", "title": "Red"},
    }  # fmt: skip
    for name, source in sources.items():
        info = indexed[name].parent / "info.yaml"
        data = yamlio.load(info.read_text())
        data["source"] = source
        info.write_text(yamlio.dump(data))
    main(["index"])
    main(["shown", str(indexed["black"])])
    return indexed


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        (["--tag", "night"], {"black", "red"}),
        (["--tag", "night", "--tag", "city"], {"black"}),
        (["--site", "wikimedia-commons"], {"red"}),
        (["--category", "general"], {"black"}),
        (["--license", "CC0-1.0"], {"red"}),
        (["--author", "Ann"], {"black"}),
        (["--tag", "night", "--dark"], {"black"}),
        (["--where", "shown_count = 0 AND site IS NOT NULL"], {"red"}),
        (["--where", "title IS NULL", "--tag", "night"], {"black"}),
        (["--where", "json_extract(info, '$.source.uploaded') >= '2024'"], {"black"}),
        (["--where", "info ->> '$.source.author' = 'Bo'"], {"red"}),
        (["--where", "EXISTS (SELECT 1 FROM json_each(tags) WHERE value = 'city')"], {"black"}),
        (["--where", "name IS NULL -- every record"], {"black", "white", "red", "noise"}),
        # The NSFW one matches, but only --purity lets it through.
        (["--site", "wallhaven", "--purity", "sfw,nsfw"], {"black", "private"}),
    ],
)
def test_list_search(
    sourced: dict[str, Path], capsys: pytest.CaptureFixture[str], flags: list[str], expected: set
) -> None:
    assert _list(capsys, *flags) == expected


def test_list_where_cannot_widen_purity_or_write(
    sourced: dict[str, Path], home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Every record, the NSFW one included, matches: it is still not printed.
    assert _list(capsys, "--where", "1 OR purity = 'nsfw'") == {"black", "white", "red", "noise"}
    assert "private" not in _list(capsys, "--where", "id IN (SELECT id FROM records)")
    for query, message in [
        ("1); DELETE FROM usage; SELECT (1", "one statement"),
        ("(SELECT count(*) FROM pragma_table_info('records')) > 0", "not authorized"),
        ("no_such_column = 1", "no such column"),
        ("1 = load_extension('x')", "not authorized"),
    ]:
        with pytest.raises(SystemExit, match=rf"--where: .*{message}"):
            main(["list", "--where", query])
    with sqlite3.connect(home / ".local/state/amontillado/index.sqlite") as conn:
        assert conn.execute("SELECT shown_count FROM usage").fetchall() == [(1,)]
        # The connection is writable again after a query.
        conn.execute("SELECT 1")
    main(["shown", str(sourced["red"])])


def _edit_tools(home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Config with two tools, green (the default) and blue, which save an edit over the copy."""
    for name, rgb in (("green", (0, 200, 0)), ("blue", (0, 0, 200))):
        _save(np.full((36, 64, 3), rgb, dtype=np.uint8), tmp_path / f"{name}.png")
    monkeypatch.setenv("EDITS", str(tmp_path))
    _write_config(
        home,
        {
            "edit": {
                "default_tool": "green",
                "tools": {
                    "green": {
                        "cmd": 'cp "$EDITS/green.png" "$AMO_INPUT"',
                        "description": "go green",
                    },
                    "blue": {"cmd": 'cp "$EDITS/blue.png" "$AMO_INPUT"'},
                },
            }
        },
    )
    return tmp_path


def test_edit(
    indexed: dict[str, Path],
    library: Path,
    home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _edit_tools(home, monkeypatch, tmp_path)
    capsys.readouterr()
    caplog.set_level(logging.INFO)
    red = str(library / "red")
    main(["edit", "--dry-run", red])
    assert capsys.readouterr().out == ""
    assert "would run cp " in caplog.text and str(library / "red" / "red.png") in caplog.text
    main(["edit", red])
    assert capsys.readouterr().out == f"{library / 'red' / 'red-edit.png'}\n"
    main(["edit", red, "--tool", "blue", "--name", "red-blue.png"])
    assert capsys.readouterr().out == f"{library / 'red' / 'red-blue.png'}\n"
    command = 'magick -size 64x36 xc:yellow "$AMO_OUTPUT"'
    if shutil.which("magick"):
        main(["edit", red, "--extcmd", command, "--from", "red-edit.png"])
        assert capsys.readouterr().out == f"{library / 'red' / 'red-edit-edit.png'}\n"
    info = yamlio.load((library / "red" / "info.yaml").read_text())
    assert info["files"]["red-edit.png"]["derived_from"] == "red.png"
    assert info["files"]["red-blue.png"]["derived_from"] == "red.png"
    assert {"red-edit.png", "red-blue.png"} <= set(_index_rows(home))
    assert _list(capsys, "--hue", "red") == {"red"}


def test_edit_reports_its_writes_to_on_change(
    indexed: dict[str, Path],
    library: Path,
    home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _edit_tools(home, monkeypatch, tmp_path)
    config = yamlio.load((home / ".config/amontillado/config.yaml").read_text())
    _write_config(home, {**config, "on_change": 'cat > "$HOME/payload.json"'})
    main(["edit", str(library / "red")])
    payload = json.loads((home / "payload.json").read_text())
    assert payload["command"] == "edit"
    # Moved out of the record's .amo/edit-* working directory: a new file, not a rename.
    kinds = [(c["type"], c["path"]) for c in payload["changes"]]
    assert kinds == [
        ("info", "red/info.yaml"),
        ("file", "red/red-edit.png"),
    ]


def test_edit_list_tools(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _edit_tools(home, monkeypatch, tmp_path)
    main(["edit", "--list-tools"])
    assert capsys.readouterr().out == "green  go green (default)\nblue\n"


@pytest.mark.parametrize(
    ("argv", "config", "message"),
    [
        (["edit"], True, "edit needs a PICTURE"),
        (["edit", "RED", "--list-tools"], True, "--list-tools takes no PICTURE"),
        (
            ["edit", "RED", "--tool", "gimp"],
            True,
            r"no tool 'gimp' under edit.tools \(tools: green, blue\)",
        ),
        (["edit", "RED"], False, "no editor: pass --tool or --extcmd"),
        (["edit", "RED", "--extcmd", " "], False, "--extcmd is empty"),
        (["edit", "RED", "--extcmd", "true"], False, "saved no image; it returned after"),
        (["edit", "RED", "--from", "none.png"], True, "no file none.png"),
        (["edit", "nothing"], True, "no record has that name"),
    ],
)
def test_edit_refusals(
    indexed: dict[str, Path],
    home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    config: bool,
    message: str,
) -> None:
    if config:
        _edit_tools(home, monkeypatch, tmp_path)
    red = str(indexed["red"].parent)
    with pytest.raises(SystemExit, match=message):
        main([red if arg == "RED" else arg for arg in argv])


def test_edit_names_what_it_keeps(
    indexed: dict[str, Path],
    library: Path,
    home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _edit_tools(home, monkeypatch, tmp_path)
    with pytest.raises(
        SystemExit, match=r"failed with exit status 1; what it saved is in .*/red/\.amo/edit-"
    ):
        main(
            ["edit", str(library / "red"), "--extcmd", 'cp "$EDITS/green.png" "$AMO_INPUT"; false']
        )
