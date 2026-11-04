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
    assert after.adjusted == ("base03", "border_inactive")
    assert 3.0 <= _ratio(after, "base03", "base00") < 3.1
    assert hex_to_oklch(after.base24["base03"])[0] > hex_to_oklch(before.base24["base03"])[0]
    assert hue_distance(hex_to_oklch(after.base24["base03"])[2], hex_to_oklch("#303040")[2]) < 5
    assert {key: after.base24[key] for key in FIXED} == {key: before.base24[key] for key in FIXED}


def test_one_foreground_on_two_backgrounds() -> None:
    # base12, derived from the dark base08, is too dark as well.
    after, left = adjust(_variant(base08="#802020"), "dark")
    assert left == []
    assert after.adjusted == ("base08", "error", "base12")
    assert _ratio(after, "base08", "base01") >= 4.5


def test_border_that_is_the_accent_moves_the_accent() -> None:
    before = _variant({"accent": "#303050"})
    after, left = adjust(before, "dark")
    assert left == []
    assert after.roles["accent"] == after.roles["border"] != "#303050"
    assert {"accent", "border"} <= set(after.adjusted)
    assert _ratio(after, "border", "base00") >= 3.0


def test_roles_derived_from_a_moved_colour_move_with_it() -> None:
    # success is derived from base0B: left behind, it would keep the failing colour.
    after, left = adjust(_variant(base0B="#205020"), "dark")
    assert left == []
    assert after.roles["success"] == after.base24["base0B"] != "#205020"
    assert after.adjusted[:2] == ("base0B", "success")
    assert _ratio(after, "success", "base00") >= 4.5


def test_a_role_set_apart_stays() -> None:
    after, _ = adjust(_variant({"success": "#40c040"}, base0B="#205020"), "dark")
    assert after.roles["success"] == "#40c040"
    assert "success" not in after.adjusted


def test_border_set_apart_moves_alone() -> None:
    after, left = adjust(_variant({"border": "#303050"}), "dark")
    assert left == []
    assert after.roles["accent"] == GOOD["base0D"]
    assert after.adjusted == ("border",)


def test_a_label_that_cannot_go_darker_crosses_its_accent() -> None:
    # Darker cannot reach 4.5 on this accent: the label goes light, the accent stays.
    before = _variant({"accent": "#4a6a8a", "on_accent": "#303030"})
    after, left = adjust(before, "dark")
    assert left == []
    assert after.roles["accent"] == "#4a6a8a"
    assert hex_to_oklch(after.roles["on_accent"])[0] > hex_to_oklch("#4a6a8a")[0]
    assert 4.5 <= _ratio(after, "on_accent", "accent") < 4.6


def test_a_foreground_darker_than_a_dark_background_goes_light() -> None:
    # amo-1xk: matugen's base16 on a cloudscape, every accent below base00 (tone 10).
    near_black = ["#03080c", "#04090d", "#050a0e", "#060b0f", "#070c10", "#080d11", "#090e12"]
    dark = dict(zip([f"base{n:02X}" for n in range(8, 16)], [*near_black, "#0a0f13"], strict=True))
    before = _variant(base00="#1a1c1e", base01="#1e2022", **dark)
    after, left = adjust(before, "dark")
    assert left == []
    for name in ("base08", "base0D", "base12", "base17"):
        assert hex_to_oklch(after.base24[name])[0] > hex_to_oklch("#1e2022")[0]
        assert 4.5 <= min(_ratio(after, name, "base00"), _ratio(after, name, "base01")) < 4.7


def test_what_no_allowed_move_fixes_is_left_failing() -> None:
    # A mid-grey background: neither black nor white reaches 7 on it, and it never moves.
    before = _variant(base00="#777777")
    after, left = adjust(before, "dark")
    assert ("base05", "base00") in [(f.foreground, f.background) for f in left]
    assert after.base24["base00"] == "#777777"


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
    assert adjusted.variants["dark"].adjusted == ("base03", "border_inactive")
    assert check(adjusted.variants["dark"]) == []


def test_unfixable_pairs_warn_after_adjusting(caplog: pytest.LogCaptureFixture) -> None:
    apply_contrast(_palette(_variant(base00="#777777")), "adjust")
    assert "base05 on base00" in caplog.text


def test_earlier_adjustments_are_kept() -> None:
    variant = dataclasses.replace(_variant(base03="#202020"), adjusted=("base05",))
    after, _ = adjust(variant, "dark")
    assert after.adjusted == ("base05", "base03", "border_inactive")
