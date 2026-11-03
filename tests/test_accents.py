from __future__ import annotations

import pytest

from amontillado.accents import (
    ANSI_ACCENTS,
    AccentScore,
    accent_colours,
    distinctness,
    hue_fidelity,
    nominal_hues,
    on_hue,
    score,
)
from amontillado.colour import hex_to_oklch, oklch_to_hex

# Colours 1-6 at their nominal hues, at lightnesses and a chroma a dark theme might use. Yellow
# and green promise hues 33 deg apart, so at one lightness they sit under 8 (6.8 at L 0.75).
LIGHTNESS = (0.70, 0.75, 0.85, 0.70, 0.70, 0.80)
ON_HUE = [
    oklch_to_hex(lightness, 0.13, hue)
    for lightness, hue in zip(LIGHTNESS, nominal_hues(), strict=True)
]


def _base24(accents: list[str]) -> dict[str, str]:
    return {key: colour for (_, key, _), colour in zip(ANSI_ACCENTS, accents, strict=True)}


def test_accents_follow_the_ansi_order() -> None:
    assert [name for name, _, _ in ANSI_ACCENTS] == [
        "red",
        "green",
        "yellow",
        "blue",
        "magenta",
        "cyan",
    ]
    base24 = {"base08": "r", "base0B": "g", "base0A": "y", "base0D": "b", "base0E": "m"}
    assert accent_colours({**base24, "base0C": "c"}) == ["r", "g", "y", "b", "m", "c"]


def test_on_hue_accents_score_six() -> None:
    assert hue_fidelity(ON_HUE) == 6


@pytest.mark.parametrize("offset", [50.0, -50.0, 180.0])
def test_an_accent_off_its_hue_is_not_counted(offset: float) -> None:
    lightness, chroma, hue = hex_to_oklch(ON_HUE[3])
    accents = [*ON_HUE[:3], oklch_to_hex(lightness, chroma, hue + offset), *ON_HUE[4:]]
    assert hue_fidelity(accents) == 5


def test_a_grey_has_no_hue() -> None:
    red = nominal_hues()[0]
    assert not on_hue("#808080", red)
    assert not on_hue(oklch_to_hex(0.7, 0.02, red), red)
    assert on_hue(oklch_to_hex(0.7, 0.05, red + 40), red)


def test_distinct_accents_are_far_apart() -> None:
    assert distinctness(ON_HUE) > 8.0


def test_near_duplicate_accents_score_low() -> None:
    lightness, chroma, hue = hex_to_oklch(ON_HUE[0])
    near = oklch_to_hex(lightness + 0.01, chroma, hue + 2)
    assert distinctness([ON_HUE[0], near, *ON_HUE[2:]]) < 3.0
    assert distinctness([ON_HUE[0], ON_HUE[0], *ON_HUE[2:]]) == 0.0


def test_score_and_its_text() -> None:
    result = score(_base24(ON_HUE))
    assert result.hues == 6
    assert result == AccentScore(6, distinctness(ON_HUE))
    assert str(AccentScore(4, 7.25)) == "hues 4/6, distinct 7.2"
