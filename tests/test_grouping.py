from __future__ import annotations

import pytest

from amontillado.grouping import palette_distance


def test_identical_palettes_are_zero_apart() -> None:
    palette = (("#1b2330", 0.6), ("#c9a46b", 0.4))
    assert palette_distance(palette, palette) == 0.0


def test_distance_is_symmetric_and_weighted_by_share() -> None:
    black, white = ("#000000", 1.0), ("#ffffff", 1.0)
    # Black to white is 1 in OKLab (lightness 0 to 1).
    assert palette_distance((black,), (white,)) == pytest.approx(1.0, abs=1e-6)
    mostly_black = (("#000000", 0.75), ("#ffffff", 0.25))
    # From black's side 0; from the other's, white (a quarter) is 1 from black: (0 + 0.25) / 2.
    assert palette_distance((black,), mostly_black) == pytest.approx(0.125, abs=1e-6)
    assert palette_distance(mostly_black, (black,)) == palette_distance((black,), mostly_black)
