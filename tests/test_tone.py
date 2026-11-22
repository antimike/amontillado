from __future__ import annotations

import pytest

from amontillado.colour import contrast_ratio, hex_to_oklch, hue_distance, oklch_to_hex
from amontillado.contrast import BLUE_BACKGROUND, check
from amontillado.generators import tone_lightness
from amontillado.hues import named_hues
from amontillado.palette import BASE16_KEYS, Variant, complete_variant
from amontillado.tone import (
    ACCENT_FLOOR,
    SPECS,
    ToneError,
    check_tone,
    checked_pairs,
    fit,
    toned,
)

ACCENT = "#5b8fd0"
# The full ramps' Material tones, as matugen's neutral palette gives them.
FULL_RAMP = {"dark": (5, 10, 20, 50, 70, 95, 98, 100), "light": (98, 95, 90, 50, 40, 10, 5, 0)}


def _full(variant: str) -> Variant:
    """A full variant shaped like a picture's: a bluish neutral ramp and named hues."""
    ramp = {
        key: oklch_to_hex(tone_lightness(material), 0.01, 230.0)
        for key, material in zip(BASE16_KEYS[:8], FULL_RAMP[variant], strict=True)
    }
    return complete_variant(variant, {**ramp, **named_hues(variant, ACCENT)})


@pytest.fixture(params=["light", "dark"])
def variant(request: pytest.FixtureRequest) -> str:
    return request.param


def test_full_is_the_variant_unchanged(variant: str) -> None:
    full = _full(variant)
    assert toned(variant, full, "full") is full


@pytest.mark.parametrize(("variant", "tone"), [("light", "dim"), ("dark", "soft"), ("dark", "x")])
def test_a_tone_the_variant_does_not_take_is_refused(variant: str, tone: str) -> None:
    with pytest.raises(ToneError, match=f"{variant} takes tone full or"):
        check_tone(variant, tone)
    with pytest.raises(ToneError):
        toned(variant, _full(variant), tone)


@pytest.mark.parametrize(("variant", "tone"), [("light", "soft"), ("dark", "dim")])
def test_the_ramp_sits_at_the_tones_material_tones(variant: str, tone: str) -> None:
    result = toned(variant, _full(variant), tone)
    for key, material in zip(BASE16_KEYS[:8], SPECS[tone].ramp, strict=True):
        assert hex_to_oklch(result.base24[key])[0] == pytest.approx(
            tone_lightness(material), abs=0.01
        )


def test_soft_paper_is_cream_and_dim_keeps_the_neutral() -> None:
    soft = toned("light", _full("light"), "soft")
    _, chroma, hue = hex_to_oklch(soft.base24["base00"])
    assert hue_distance(hue, 80.0) < 3 and chroma == pytest.approx(0.024, abs=0.003)
    dim = toned("dark", _full("dark"), "dim")
    _, chroma, hue = hex_to_oklch(dim.base24["base00"])
    assert hue_distance(hue, 230.0) < 10 and chroma == pytest.approx(0.01, abs=0.004)


@pytest.mark.parametrize(("variant", "tone"), [("light", "soft"), ("dark", "dim")])
def test_accents_keep_their_hue_and_soften_toward_the_floor(variant: str, tone: str) -> None:
    full = _full(variant)
    result = toned(variant, full, tone)
    keys = ["base08", "base09", "base0A", "base0B", "base0C", "base0E"]
    if tone == "soft":
        keys.append("base0D")
    for key in keys:
        assert (
            hue_distance(hex_to_oklch(result.base24[key])[2], hex_to_oklch(full.base24[key])[2]) < 4
        )
        was = contrast_ratio(full.base24[key], full.base24["base01"])
        now = contrast_ratio(result.base24[key], result.base24["base01"])
        assert now >= ACCENT_FLOOR
        assert now <= max(ACCENT_FLOOR, was) + 0.1


def test_soft_raises_accent_chroma() -> None:
    full = _full("light")
    soft = toned("light", full, "soft")
    # Green has room in gamut at soft's lightness.
    assert hex_to_oklch(soft.base24["base0B"])[1] > hex_to_oklch(full.base24["base0B"])[1] * 1.2


def test_soft_passes_every_pair_without_adjusting() -> None:
    assert check(toned("light", _full("light"), "soft")) == []


def test_dim_blue_is_a_background_and_only_its_text_pairs_fail() -> None:
    dim = toned("dark", _full("dark"), "dim")
    assert contrast_ratio(dim.base24["base05"], dim.base24["base0D"]) >= BLUE_BACKGROUND
    assert [(f.foreground, f.background) for f in check(dim)] == [
        ("base0D", "base00"),
        ("base0D", "base01"),
    ]
    # Bright blue stays text.
    assert contrast_ratio(dim.base24["base16"], dim.base24["base01"]) >= 4.5


def test_dim_passes_with_its_own_pairs() -> None:
    assert check(toned("dark", _full("dark"), "dim"), checked_pairs("dim")) == []


@pytest.mark.parametrize("tone", ["full", "soft"])
def test_other_tones_check_the_usual_pairs(tone: str) -> None:
    assert checked_pairs(tone) == checked_pairs("full")
    assert ("base0D", "base00", 4.5) in checked_pairs(tone)


def test_roles_are_toned_and_derived(variant: str) -> None:
    tone = {"light": "soft", "dark": "dim"}[variant]
    result = toned(variant, _full(variant), tone)
    assert result.roles["selection"] == result.base24["base02"]
    assert contrast_ratio(result.roles["accent"], result.base24["base01"]) >= ACCENT_FLOOR


@pytest.mark.parametrize("lighter", [True, False])
def test_fit_reaches_the_target_after_rounding(lighter: bool) -> None:
    other = "#777777"
    colour = fit(0.1, 140.0, other, 3.0, lighter=lighter)
    ratio = contrast_ratio(colour, other)
    assert 3.0 <= ratio < 3.1
    assert (hex_to_oklch(colour)[0] > hex_to_oklch(other)[0]) == lighter


def test_fit_returns_the_extreme_when_no_colour_reaches_the_target() -> None:
    assert fit(0.0, 0.0, "#777777", 21.0, lighter=True) == "#ffffff"
