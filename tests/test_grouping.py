from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from amontillado.colour import hex_to_oklch, oklch_to_hex, srgb_to_oklab
from amontillado.grouping import (
    COLOUR_WEIGHT,
    CONTRAST_WEIGHT,
    EXTREME_WEIGHT,
    GroupError,
    Monitor,
    companions,
    distance,
)
from amontillado.index import IndexedFile
from amontillado.metrics import Metrics, Palette


def _metrics(palette: Palette, warmth: float = 0.0) -> Metrics:
    return Metrics(0.5, 0.1, 0.5, None, None, 0.0, 0.0, warmth, 0.0, palette)


def test_identical_palettes_are_zero_apart() -> None:
    picture = _metrics((("#1b2330", 0.6), ("#c9a46b", 0.4)))
    assert distance(picture, picture) == 0.0


def test_black_to_white_is_their_lightness_difference() -> None:
    black, white = _metrics((("#000000", 1.0),)), _metrics((("#ffffff", 1.0),))
    assert distance(black, white) == pytest.approx(1.0, abs=1e-6)


def test_distance_is_symmetric_and_adds_the_contrast_difference() -> None:
    black = _metrics((("#000000", 1.0),))
    mostly_black = _metrics((("#000000", 0.75), ("#ffffff", 0.25)))
    # Both colours are extremes, so their weights keep their ratio: from black's side 0, from
    # the other's white (a quarter) is 1 away; then the contrast (lightness spread) differs by
    # sqrt(0.75 * 0.25).
    expected = 0.25 / 2 + CONTRAST_WEIGHT * math.sqrt(0.75 * 0.25)
    assert distance(black, mostly_black) == pytest.approx(expected, abs=1e-6)
    assert distance(mostly_black, black) == distance(black, mostly_black)


def test_colour_counts_more_than_lightness() -> None:
    red = "#c04040"
    lightness, chroma, _ = hex_to_oklch(red)
    grey = oklch_to_hex(lightness, 0.0, 0.0)  # as light as the red
    apart = distance(_metrics(((red, 1.0),)), _metrics(((grey, 1.0),)))
    assert apart == pytest.approx(COLOUR_WEIGHT * chroma, rel=0.05)


def test_dark_pictures_are_compared_on_their_accents() -> None:
    red_on_black = _metrics((("#000000", 0.9), ("#d02020", 0.1)))
    blue_on_black = _metrics((("#000000", 0.9), ("#2040d0", 0.1)))
    # Black counts a quarter: weights 0.225 and 0.1, renormalised. Each accent's nearest colour
    # in the other palette is black (lightness and colour scaled), not the other accent.
    accent = 0.1 / (0.9 * EXTREME_WEIGHT + 0.1)
    red, blue = (srgb_to_oklab(np.array(_rgb(c), np.uint8)) for c in ("#d02020", "#2040d0"))
    scale = np.array([1.0, COLOUR_WEIGHT, COLOUR_WEIGHT])
    to_black = [float(np.linalg.norm(c * scale)) for c in (red, blue)]
    to_other = float(np.linalg.norm((red - blue) * scale))
    expected = accent * (min(to_black[0], to_other) + min(to_black[1], to_other)) / 2
    # Plus the contrast term: a two-colour palette's lightness spread is |L1 - L0| sqrt(p q).
    expected += CONTRAST_WEIGHT * abs(red[0] - blue[0]) * math.sqrt(0.9 * 0.1)
    assert distance(red_on_black, blue_on_black) == pytest.approx(expected, abs=1e-6)
    # Counted at their full share, the backgrounds would have hidden the accents.
    assert expected > 0.1 * min(to_black[0], to_other)


def _rgb(colour: str) -> list[int]:
    return [int(colour[i : i + 2], 16) for i in (1, 3, 5)]


@pytest.mark.parametrize(("other", "gated"), [(-0.9, True), (-0.3, False), (0.9, False)])
def test_warmth_gate(other: float, gated: bool) -> None:
    palette = (("#806040", 1.0),)
    apart = distance(_metrics(palette, 0.9), _metrics(palette, other))
    assert math.isinf(apart) == gated


def _file(record_id: str, colour: str, ratio: float = 16 / 9) -> IndexedFile:
    metrics = Metrics(0.5, 0.1, 0.5, None, None, 0.0, 0.0, 0.0, 0.0, ((colour, 1.0),))
    return IndexedFile(
        Path(f"/l/{record_id}.png"),
        record_id,
        "sfw",
        False,
        True,
        round(900 * ratio),
        900,
        None,
        metrics,
    )


GREYS = {"g10": "#1a1a1a", "g20": "#333333", "g30": "#4d4d4d", "g90": "#e6e6e6"}
PRIMARY = _file("g00", "#000000")
MONITORS = [Monitor("DP-2", 16 / 9, "16:9"), Monitor("HDMI-1", 16 / 9, "16:9")]


def _companions(order: list[str], **kwargs: object) -> list[tuple[str, bool]]:
    options = {"max_distance": 0.25, "nearest": False, "accept": lambda f: True, **kwargs}
    accept = options.pop("accept")
    chosen = companions(
        PRIMARY, MONITORS, order, lambda r, _: _file(r, GREYS[r]), accept, **options
    )
    return [(choice.file.record_id, choice.beyond) for choice in chosen]


def test_companions_in_the_order_given_or_nearest() -> None:
    # From black: g10 0.22, g20 0.32, g30 0.42, g90 0.92 (OKLab lightness).
    order = ["g20", "g10", "g90", "g30"]
    assert _companions(order, max_distance=0.35) == [("g20", False), ("g10", False)]
    assert _companions(order, max_distance=0.35, nearest=True) == [("g10", False), ("g20", False)]


def test_too_few_compatible_fill_with_the_nearest_beyond() -> None:
    assert _companions(["g90", "g30", "g10"], max_distance=0.25) == [("g10", False), ("g30", True)]


def test_companions_skip_the_primary_and_rejected_records() -> None:
    order = ["g00", "g10", "g20", "g30"]
    GREYS["g00"] = "#000000"
    try:
        chosen = _companions(order, accept=lambda f: f.record_id != "g10")
    finally:
        del GREYS["g00"]
    assert chosen == [("g20", True), ("g30", True)]


def test_too_few_pictures() -> None:
    with pytest.raises(GroupError, match="none left for monitor HDMI-1"):
        _companions(["g10"])
