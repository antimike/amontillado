from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from amontillado.colour import srgb_to_oklab
from amontillado.letterbox import Bars, find_bars
from amontillado.metrics import measure, measure_file


def _picture(width: int, height: int, seed: int = 0) -> np.ndarray:
    """A lit, busy picture: colour noise around mid grey."""
    rng = np.random.default_rng(seed)
    return rng.integers(60, 230, (height, width, 3), dtype=np.uint8)


def _boxed(width: int, height: int, top: int, bottom: int, left: int = 0, right: int = 0):
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[top : height - bottom, left : width - right] = _picture(
        width - left - right, height - top - bottom
    )
    return frame


def _lightness(rgb: np.ndarray) -> np.ndarray:
    return srgb_to_oklab(rgb)[..., 0]


def test_a_letterbox() -> None:
    assert find_bars(_lightness(_boxed(400, 225, 25, 30))) == Bars(25, 30, 0, 0)
    assert Bars(25, 30, 0, 0).content(400, 225) == (0, 25, 400, 170)


def test_a_pillarbox() -> None:
    assert find_bars(_lightness(_boxed(400, 225, 0, 0, 50, 50))) == Bars(0, 0, 50, 50)


def test_no_bars() -> None:
    assert find_bars(_lightness(_picture(400, 225))) is None
    # One bar only, or bars thinner than MIN_BAR (3% of the height: 7 rows here).
    assert find_bars(_lightness(_boxed(400, 225, 30, 0))) is None
    assert find_bars(_lightness(_boxed(400, 225, 5, 5))) is None
    # All dark.
    assert find_bars(_lightness(np.zeros((225, 400, 3), dtype=np.uint8))) is None


def test_a_logo_on_black_is_not_a_letterbox() -> None:
    """Uniform dark rows at both edges, but the middle is dark too."""
    frame = np.zeros((225, 400, 3), dtype=np.uint8)
    frame[80:145, 160:240] = _picture(80, 65)
    assert find_bars(_lightness(frame)) is None


def test_measure_reports_the_box_in_its_pixels() -> None:
    assert measure(_boxed(400, 225, 25, 30)).letterbox == (0, 25, 400, 170)
    assert measure(_picture(400, 225)).letterbox is None


def test_measure_file_finds_the_box_at_full_size(tmp_path: Path) -> None:
    """Measured at 432 px wide, a 1600 x 900 file's bars would be 3.7 rows off at worst."""
    path = tmp_path / "boxed.png"
    Image.fromarray(_boxed(1600, 900, 111, 97)).save(path)
    assert measure_file(path).letterbox == (0, 111, 1600, 692)
    path = tmp_path / "pillar.png"
    Image.fromarray(_boxed(1600, 900, 0, 0, 203, 197)).save(path)
    assert measure_file(path).letterbox == (203, 0, 1200, 900)
    with path.open("rb") as file:
        assert measure_file(file).letterbox == (203, 0, 1200, 900)
