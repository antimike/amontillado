from __future__ import annotations

import pytest

from amontillado.accents import ANSI_ACCENTS, distinctness, hue_fidelity, score
from amontillado.colour import contrast_ratio, hex_to_oklch, hue_distance, oklch_to_hex
from amontillado.hues import (
    CHROMA_MAX,
    CHROMA_MIN,
    LIGHTNESS,
    NOMINAL_HUES,
    accent_chroma,
    named_hues,
)
from amontillado.palette import BASE16_KEYS

# The calibration ramps' base00, base01 and base05 (matugen neutral tones 5, 10, 95 for dark;
# 98, 95, 10 for light, on a near-grey picture).
RAMP = {
    "dark": ("#0f1113", "#1a1c1e", "#f0f0f4"),
    "light": ("#f9f9fc", "#f0f0f4", "#1a1c1e"),
}
ACCENTS = ["#99ccfa", "#808080", "#ff0000", "#2c638b", "#00ff00"]


def test_nominal_hues_agree_with_the_accent_metrics() -> None:
    for _, key, primary in ANSI_ACCENTS:
        assert NOMINAL_HUES[key] == pytest.approx(hex_to_oklch(primary)[2])
    assert list(NOMINAL_HUES) == list(BASE16_KEYS[8:])


@pytest.mark.parametrize("variant", ["dark", "light"])
@pytest.mark.parametrize("accent", ACCENTS)
def test_named_hues_stay_on_their_hue(variant: str, accent: str) -> None:
    colours = named_hues(variant, accent)
    assert list(colours) == list(BASE16_KEYS[8:])
    assert score(colours).hues == 6
    for key, colour in colours.items():
        lightness, _, hue = hex_to_oklch(colour)
        assert hue_distance(hue, NOMINAL_HUES[key]) < 3
        assert lightness == pytest.approx(LIGHTNESS[variant][key], abs=0.01)


@pytest.mark.parametrize("variant", ["dark", "light"])
@pytest.mark.parametrize("accent", ACCENTS)
def test_named_hues_are_distinct_and_legible(variant: str, accent: str) -> None:
    colours = named_hues(variant, accent)
    accents = [colours[key] for _, key, _ in ANSI_ACCENTS]
    assert distinctness(accents) >= 8.0
    base00, base01, base05 = RAMP[variant]
    for key in BASE16_KEYS[8:15]:
        assert contrast_ratio(colours[key], base00) >= 4.5, key
        assert contrast_ratio(colours[key], base01) >= 4.5, key
    # Text on blue as a background (less's prompt, paired brackets).
    assert contrast_ratio(base05, colours["base0D"]) >= 3.0


def test_chroma_follows_the_accent_within_bounds() -> None:
    assert accent_chroma("#808080") == CHROMA_MIN
    assert accent_chroma("#ff0000") == CHROMA_MAX
    middle = oklch_to_hex(0.7, 0.12, 200)
    assert accent_chroma(middle) == pytest.approx(0.12, abs=0.005)
    muted, vivid = named_hues("dark", "#808080"), named_hues("dark", "#ff0000")
    assert hex_to_oklch(vivid["base08"])[1] > hex_to_oklch(muted["base08"])[1]
    # Brown is orange's hue, duller and darker.
    brown, orange = hex_to_oklch(muted["base0F"]), hex_to_oklch(muted["base09"])
    assert brown[1] < orange[1] and brown[0] < orange[0]


def test_hue_fidelity_needs_all_six() -> None:
    colours = named_hues("dark", "#99ccfa")
    assert hue_fidelity([colours[key] for _, key, _ in ANSI_ACCENTS]) == 6
