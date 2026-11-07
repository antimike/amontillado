from __future__ import annotations

import pytest

from amontillado.colour import hex_to_oklch, hue_distance, oklch_to_hex
from amontillado.gnome import FAMILIES, LADDERS, RAMP_KEYS, gnome_palette
from amontillado.palette import Palette, Variant, complete_variant
from amontillado.render import mustache_view

# libadwaita 1.9's GNOME palette, in its stylesheet's order.
GNOME_NAMES = [
    f"{family}-{step}"
    for family in ("blue", "green", "yellow", "orange", "red", "purple", "brown", "light", "dark")
    for step in range(1, 6)
]
# gruvbox dark and light, hard (tinted-theming/schemes, MIT).
GRUVBOX = {
    "dark": "1d2021 3c3836 504945 665c54 bdae93 d5c4a1 ebdbb2 fbf1c7"
    " fb4934 fe8019 fabd2f b8bb26 8ec07c 83a598 d3869b d65d0e",
    "light": "f9f5d7 ebdbb2 d5c4a1 bdae93 665c54 504945 3c3836 282828"
    " 9d0006 af3a03 b57614 79740e 427b58 076678 8f3f71 d65d0e",
}


def _variant(variant: str, **colours: str) -> Variant:
    base = {f"base{i:02X}": f"#{c}" for i, c in enumerate(GRUVBOX[variant].split())}
    return complete_variant(variant, {**base, **colours})


@pytest.mark.parametrize("variant", ["dark", "light"])
def test_every_gnome_colour(variant: str) -> None:
    assert list(gnome_palette(_variant(variant))) == GNOME_NAMES


@pytest.mark.parametrize("variant", ["dark", "light"])
def test_hue_families_keep_the_ladder_and_the_palette_hue(variant: str) -> None:
    colours = _variant(variant)
    gnome = gnome_palette(colours)
    for family, keys in FAMILIES.items():
        _, _, hue = hex_to_oklch(colours.base24[keys[0]])
        for step, target in enumerate(LADDERS[family], start=1):
            lightness, _, step_hue = hex_to_oklch(gnome[f"{family}-{step}"])
            assert lightness == pytest.approx(target, abs=0.01), (family, step)
            # The bright colour is the base one lighter, so one hue throughout.
            assert hue_distance(step_hue, hue) < 3, (family, step)


def test_ladders_get_darker() -> None:
    for family, ladder in LADDERS.items():
        assert list(ladder) == sorted(ladder, reverse=True), family


def test_hue_between_the_two_colours_by_lightness() -> None:
    # A red at L 0.50 and a bright one at L 0.70 turned 40 degrees: red-3 (L 0.58) is 40 %
    # of the way, red-5 (L 0.47) below the darker colour, red-1 (L 0.68) nearly the bright one.
    red = oklch_to_hex(0.50, 0.15, 20.0)
    bright = oklch_to_hex(0.70, 0.15, 60.0)
    gnome = gnome_palette(_variant("light", base08=red, base12=bright))
    hues = {step: hex_to_oklch(gnome[f"red-{step}"])[2] for step in (1, 3, 5)}
    assert hues[5] == pytest.approx(hex_to_oklch(red)[2], abs=2)
    assert hues[3] == pytest.approx(hex_to_oklch(red)[2] + 0.4 * 40, abs=3)
    assert hues[1] == pytest.approx(hex_to_oklch(red)[2] + 0.9 * 40, abs=3)


def test_hue_turns_the_short_way_round() -> None:
    purple = oklch_to_hex(0.50, 0.15, 340.0)
    bright = oklch_to_hex(0.60, 0.15, 20.0)
    gnome = gnome_palette(_variant("dark", base0E=purple, base17=bright))
    # purple-3 (L 0.53) is 30 % of the way from 340 deg to 380 deg.
    assert hue_distance(hex_to_oklch(gnome["purple-3"])[2], 352.0) < 3


@pytest.mark.parametrize("variant", ["dark", "light"])
def test_greys_are_the_ramp_lightest_first(variant: str) -> None:
    colours = _variant(variant)
    gnome = gnome_palette(colours)
    greys = [gnome[f"light-{step}"] for step in range(1, 6)]
    greys += [gnome[f"dark-{step}"] for step in range(1, 6)]
    assert sorted(greys) == sorted(colours.base24[key] for key in RAMP_KEYS)
    lightness = [hex_to_oklch(grey)[0] for grey in greys]
    assert lightness == sorted(lightness, reverse=True)


def test_mustache_view_has_the_gnome_colours() -> None:
    colours = _variant("dark")
    view = mustache_view(Palette("gruvbox", {"dark": colours}, {}), "dark")
    gnome = gnome_palette(colours)
    assert {key for key in view if key.startswith("gnome-")} == {
        f"gnome-{name}-hex" for name in GNOME_NAMES
    }
    assert view["gnome-blue-3-hex"] == gnome["blue-3"].removeprefix("#")
