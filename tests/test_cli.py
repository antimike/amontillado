from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

from amontillado import __version__
from amontillado.cli import get_cli_arguments, main


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
    out = yaml.safe_load(capsys.readouterr().out)
    assert [entry["file"] for entry in out] == [str(black), str(red)]
    assert out[0]["metrics"]["hue"] is None
    assert out[0]["classes"] == ["dark", "muted", "sparse"]
    assert out[1]["metrics"]["hue_name"] == "red"
    assert {"saturated", "monochrome", "warm", "red"} <= set(out[1]["classes"])


def test_measure_reports_bad_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = _save(np.zeros((36, 64, 3), dtype=np.uint8), tmp_path / "good.png")
    bad = tmp_path / "bad.png"
    bad.write_text("not an image")
    with pytest.raises(SystemExit) as exc:
        main(["measure", str(bad), str(good), str(tmp_path / "missing.png")])
    assert exc.value.code == "amontillado: 2 of 3 files could not be measured"
    out = yaml.safe_load(capsys.readouterr().out)
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
        return [Path(row[0]).name for row in conn.execute("SELECT path FROM images ORDER BY 1")]


def test_index_heals_and_indexes(library: Path, home: Path) -> None:
    _save(np.zeros((36, 64, 3), dtype=np.uint8), library / "a.png")
    main(["index"])
    assert (library / "a.yaml").is_file()
    assert _index_rows(home) == ["a.png"]


def test_index_check_writes_nothing_and_fails(library: Path, home: Path) -> None:
    _save(np.zeros((36, 64, 3), dtype=np.uint8), library / "a.png")
    with pytest.raises(SystemExit) as exc:
        main(["index", "--check"])
    assert exc.value.code == "amontillado: 1 sidecar to heal"
    assert not (library / "a.yaml").exists()
    assert not (home / ".local/state/amontillado/index.sqlite").exists()


def test_index_check_passes_on_a_healed_library(library: Path) -> None:
    _save(np.zeros((36, 64, 3), dtype=np.uint8), library / "a.png")
    main(["index"])
    main(["index", "--check"])


def test_index_orphans_fail_only_a_check(library: Path) -> None:
    (library / "gone.yaml").write_text("schema: 1\n")
    main(["index"])
    with pytest.raises(SystemExit) as exc:
        main(["index", "--check"])
    assert exc.value.code == "amontillado: 1 sidecar without an image"


def test_index_indexes_the_rest_when_an_image_fails(library: Path, home: Path) -> None:
    _save(np.zeros((36, 64, 3), dtype=np.uint8), library / "good.png")
    (library / "bad.png").write_text("not an image")
    with pytest.raises(SystemExit) as exc:
        main(["index"])
    assert exc.value.code == "amontillado: 1 image could not be read"
    assert _index_rows(home) == ["good.png"]


def test_config_error_exits(home: Path) -> None:
    (home / ".config/amontillado").mkdir(parents=True)
    (home / ".config/amontillado/config.yaml").write_text("library_roots: /x\n")
    with pytest.raises(SystemExit) as exc:
        main(["index"])
    assert exc.value.code == "amontillado: library_roots must be a list of paths"
