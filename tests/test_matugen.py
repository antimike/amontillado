from __future__ import annotations

import pytest
from conftest import FIXTURES, fixture_json

from amontillado.colour import contrast_ratio
from amontillado.matugen import (
    CUSTOM_COLOURS,
    ROLES,
    MatugenError,
    material_view,
    parse_hex,
    render_matugen,
)
from amontillado.palette import Palette, complete_variant

PROBE = (FIXTURES / "matugen-probe.txt").read_text()


def _matugen_view(mode: str) -> dict[str, object]:
    """The view matugen itself had for the recorded probe run (its image is Null without one)."""
    data = fixture_json(f"matugen-probe-{mode}.json")
    return {
        name: {
            key: {m: parse_hex(c) for m, c in modes.items()} for key, modes in data[name].items()
        }
        for name in ("colors", "base16")
    } | {"image": "Null", "mode": data["mode"]}


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_probe_renders_as_matugen_does(mode: str) -> None:
    # matugen 4.2.0 rendered tests/fixtures/matugen-probe.txt (`matugen color hex "#c0703a"
    # -m MODE`): every field, filter, loop and escape there must come out byte for byte.
    expected = (FIXTURES / f"matugen-probe-{mode}.txt").read_text()
    assert render_matugen(PROBE, _matugen_view(mode)) == expected


def test_channels_are_held_as_matugen_holds_them() -> None:
    # 231 is 231.0000014 in matugen, so `rgb` after set_lightness truncates to 50, not 51.
    view = {"c": {"x": parse_hex("#e7d7cf")}}
    assert render_matugen("{{c.x.rgb | set_lightness: 15.0}}", view) == "rgb(50, 34, 25)"
    assert render_matugen("{{c.x.rgba | set_lightness: 15.0}}", view) == "rgba(51, 34, 26, 1)"
    assert parse_hex("#e7d7cf").red == pytest.approx(231.0)


def test_whitespace_after_if_and_else_is_dropped() -> None:
    view = {
        "colors": {"a": {"default": parse_hex("#000000")}, "b": {"default": parse_hex("#ffffff")}}
    }
    template = (
        "<* for k, v in colors *>{{k}}<* if {{ loop.last }} *>\n  .<* else *>\n  ,<* endif *>\n"
        "<* endfor *>"
    )
    assert render_matugen(template, view) == "a,\nb.\n"


@pytest.mark.parametrize(
    ("template", "message"),
    [
        ("<* for name, p in palettes *>x<* endfor *>", "unknown variable 'palettes'"),
        ("{{colors.nope.default.hex}}", "unknown variable 'colors.nope.default.hex'"),
        ("{{colors.primary.default.hue}}", "unknown colour field 'hue'"),
        ("{{colors.primary.default.hex | blend: 1}}", "unknown filter 'blend'"),
        ("{{colors.primary.default}}", "a colour needs a field"),
        ("{{colors.primary.default.hex | saturate: 10, hsv}}", "expected N, hsl"),
        ("<* include other *>", "unsupported block"),
        ("<* for i in 0..3 *>x<* endfor *>", "unsupported loop over"),
        ("{{colors.primary.default.hex", "unclosed {{"),
        ("<* if {{ loop.last }} *>x", "missing <* endif *>"),
    ],
)
def test_unsupported_is_an_error(template: str, message: str) -> None:
    view = _matugen_view("dark")
    with pytest.raises(MatugenError, match=message.replace("*", r"\*").replace("(", r"\(")):
        render_matugen(template, view)


RAMP = ["#101010", "#181818", "#303030", "#707070", "#a0a0a0", "#e0e0e0", "#f0f0f0", "#ffffff"]
LIGHT = list(reversed(RAMP))
ACCENTS = ["#ff8080", "#ffa060", "#ffe080", "#80ff80", "#80ffff", "#80b0ff", "#e0a0ff", "#c08060"]


def _palette(*variants: str) -> Palette:
    keys = [f"base{i:02X}" for i in range(16)]
    ramps = {"dark": RAMP, "light": LIGHT}
    return Palette(
        "p",
        {
            v: complete_variant(v, dict(zip(keys, ramps[v] + ACCENTS, strict=True)))
            for v in variants
        },
    )


def test_material_view_covers_every_matugen_role() -> None:
    view = material_view(_palette("dark", "light"), "dark")
    colors = view["colors"]
    assert set(ROLES) == set(fixture_json("matugen-probe-dark.json")["colors"])
    assert set(colors) == set(ROLES) | set(CUSTOM_COLOURS)
    assert all(set(modes) == {"dark", "light", "default"} for modes in colors.values())
    assert set(view["base16"]) == {f"base{i:02x}" for i in range(16)}
    assert (view["mode"], view["is_dark_mode"], view["image"]) == ("dark", True, "")


def _hex(view: dict[str, object], role: str, mode: str = "default") -> str:
    return render_matugen(f"{{{{colors.{role}.{mode}.hex}}}}", view)


def test_material_roles_from_the_palette() -> None:
    palette = _palette("dark", "light")
    dark = palette.variants["dark"]
    view = material_view(palette, "light")
    assert _hex(view, "primary", "dark") == dark.roles["accent"]
    assert _hex(view, "surface", "dark") == dark.base24["base00"]
    assert _hex(view, "on_surface", "dark") == dark.base24["base05"]
    assert _hex(view, "surface_container_lowest", "dark") == dark.base24["base11"]
    assert _hex(view, "surface") == palette.variants["light"].base24["base00"]
    assert _hex(view, "red") == palette.variants["light"].base24["base08"]
    # The other variant's accent.
    assert _hex(view, "inverse_primary") == dark.roles["accent"]
    for mode in ("dark", "light"):
        # Text on a container reads; a container sits near the background.
        container = _hex(view, "primary_container", mode)
        assert contrast_ratio(_hex(view, "on_primary_container", mode), container) > 3.0
        surface = _hex(view, "surface", mode)
        assert contrast_ratio(container, surface) < contrast_ratio(
            _hex(view, "primary", mode), surface
        )
    # Containers rise away from the background, for either variant.
    for mode in ("dark", "light"):
        steps = ["surface_container_low", "surface_container", "surface_container_high"]
        ratios = [contrast_ratio(_hex(view, s, mode), _hex(view, "surface", mode)) for s in steps]
        assert ratios == sorted(ratios)


def test_one_variant_gives_it_for_every_mode() -> None:
    view = material_view(_palette("dark"), "dark")
    assert _hex(view, "primary", "light") == _hex(view, "primary", "dark") == _hex(view, "primary")
    assert view["mode"] == "dark"
