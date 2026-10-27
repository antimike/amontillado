from __future__ import annotations

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
