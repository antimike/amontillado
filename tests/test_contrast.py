from __future__ import annotations

import dataclasses
import logging

import pytest

from amontillado.colour import contrast_ratio, hex_to_oklch, hue_distance
from amontillado.contrast import FIXED, PAIRS, adjust, apply_contrast, check
from amontillado.palette import Palette, Variant, complete_variant

GOOD = {
    "base00": "#101010",
    "base01": "#181818",
    "base02": "#303030",
    "base03": "#707070",
    "base04": "#a0a0a0",
    "base05": "#e0e0e0",
    "base06": "#f0f0f0",
    "base07": "#ffffff",
    "base08": "#ff8080",
    "base09": "#ffa060",
    "base0A": "#ffe080",
    "base0B": "#80ff80",
    "base0C": "#80ffff",
    "base0D": "#80b0ff",
    "base0E": "#e0a0ff",
    "base0F": "#c08060",
}


def _variant(roles: dict[str, str] | None = None, **colours: str) -> Variant:
    return complete_variant("dark", {**GOOD, **colours}, roles)


def _ratio(variant: Variant, foreground: str, background: str) -> float:
    def colour(name: str) -> str:
        return variant.roles.get(name) or variant.base24[name]

    return contrast_ratio(colour(foreground), colour(background))


def test_every_pair_names_known_colours() -> None:
    variant = _variant()
    for foreground, background, _ in PAIRS:
        for name in (foreground, background):
            assert name in variant.roles or name in variant.base24


def test_a_good_palette_passes() -> None:
    assert check(_variant()) == []


def test_check_lists_failing_pairs() -> None:
    failures = check(_variant(base03="#202020"))
    assert [(f.foreground, f.background, f.minimum) for f in failures] == [
        ("base03", "base00", 3.0)
    ]
    assert str(failures[0]).startswith("base03 on base00: 1.")


def test_foreground_moves_by_the_smallest_step() -> None:
    before = _variant(base03="#303040")
    after, left = adjust(before, "dark")
    assert left == []
    assert after.adjusted == ("base03",)
    assert 3.0 <= _ratio(after, "base03", "base00") < 3.1
    assert hex_to_oklch(after.base24["base03"])[0] > hex_to_oklch(before.base24["base03"])[0]
    assert hue_distance(hex_to_oklch(after.base24["base03"])[2], hex_to_oklch("#303040")[2]) < 5
    assert {key: after.base24[key] for key in FIXED} == {key: before.base24[key] for key in FIXED}


def test_one_foreground_on_two_backgrounds() -> None:
    # base12, derived from the dark base08, is too dark as well.
    after, left = adjust(_variant(base08="#802020"), "dark")
    assert left == []
    assert after.adjusted == ("base08", "base12")
    assert _ratio(after, "base08", "base01") >= 4.5


def test_border_that_is_the_accent_moves_the_accent() -> None:
    before = _variant({"accent": "#303050"})
    after, left = adjust(before, "dark")
    assert left == []
    assert after.roles["accent"] == after.roles["border"] != "#303050"
    assert {"accent", "border"} <= set(after.adjusted)
    assert _ratio(after, "border", "base00") >= 3.0


def test_border_set_apart_moves_alone() -> None:
    after, left = adjust(_variant({"border": "#303050"}), "dark")
    assert left == []
    assert after.roles["accent"] == GOOD["base0D"]
    assert after.adjusted == ("border",)


def test_accent_moves_when_its_label_cannot() -> None:
    # The label is dark and darker cannot reach 4.5 on this accent: the accent moves lighter.
    before = _variant({"accent": "#4a6a8a", "on_accent": "#303030"})
    after, left = adjust(before, "dark")
    assert left == []
    assert after.roles["on_accent"] == "#303030"
    assert hex_to_oklch(after.roles["accent"])[0] > hex_to_oklch("#4a6a8a")[0]
    assert _ratio(after, "on_accent", "accent") >= 4.5


def test_what_no_allowed_move_fixes_is_left_failing() -> None:
    # Selection is a background no rule moves; its label cannot go darker enough.
    before = _variant({"selection": "#5a5a5a", "on_selection": "#303030"})
    after, left = adjust(before, "dark")
    assert [(f.foreground, f.background) for f in left] == [("on_selection", "selection")]
    assert after.roles["selection"] == "#5a5a5a"


def test_adjust_logs_each_change(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    adjust(_variant(base03="#202020"), "dark")
    assert "dark: base03 #202020 -> #" in caplog.text
    assert "(base03 on base00: 1." in caplog.text


def _palette(variant: Variant) -> Palette:
    return Palette("p", {"dark": variant})


def test_modes(caplog: pytest.LogCaptureFixture) -> None:
    palette = _palette(_variant(base03="#202020"))
    assert apply_contrast(palette, "off") == palette
    assert apply_contrast(palette, "report") == palette
    assert "dark: base03 on base00" in caplog.text
    adjusted = apply_contrast(palette, "adjust")
    assert adjusted.variants["dark"].adjusted == ("base03",)
    assert check(adjusted.variants["dark"]) == []


def test_unfixable_pairs_warn_after_adjusting(caplog: pytest.LogCaptureFixture) -> None:
    variant = _variant({"selection": "#5a5a5a", "on_selection": "#303030"})
    apply_contrast(_palette(variant), "adjust")
    assert "on_selection on selection" in caplog.text


def test_earlier_adjustments_are_kept() -> None:
    variant = dataclasses.replace(_variant(base03="#202020"), adjusted=("base05",))
    after, _ = adjust(variant, "dark")
    assert after.adjusted == ("base05", "base03")
