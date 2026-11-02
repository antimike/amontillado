from __future__ import annotations

import re
from pathlib import Path

import pytest

from amontillado.palette import BASE24_KEYS, ROLES, Palette, complete_variant
from amontillado.render import (
    PywalColour,
    RenderError,
    mustache_view,
    pywal_view,
    render_mustache,
    render_pywal,
)

DARK = {f"base{i:02X}": f"#{i * 16:02x}{i * 8:02x}{255 - i * 16:02x}" for i in range(16)}
DARK["base0D"] = "#7cafc2"


def _palette(**source: object) -> Palette:
    variants = {"dark": complete_variant("dark", DARK), "light": complete_variant("light", DARK)}
    return Palette("Gruvbox Dark, Hard!", variants, dict(source))


def test_colour_variables() -> None:
    view = mustache_view(_palette(), "dark")
    assert view["base0D-hex"] == "7cafc2"
    assert (view["base0D-hex-r"], view["base0D-hex-g"], view["base0D-hex-b"]) == ("7c", "af", "c2")
    assert view["base0D-hex-bgr"] == "c2af7c"
    assert (view["base0D-rgb-r"], view["base0D-rgb-g"], view["base0D-rgb-b"]) == (124, 175, 194)
    assert view["base0D-rgb16-r"] == 124 * 257
    assert view["base0D-dec-r"] == "0.48627451"
    # Roles get the same set: the accent is base0D in a scheme-made palette.
    assert view["accent-hex"] == "7cafc2"
    assert view["accent-dec-b"] == view["base0D-dec-b"]


def test_every_key_and_role_has_every_variable() -> None:
    view = mustache_view(_palette(), "dark")
    suffixes = ["hex", "hex-bgr"] + [
        f"{kind}-{channel}" for kind in ("hex", "rgb", "rgb16", "dec") for channel in "rgb"
    ]
    for name in (*BASE24_KEYS, *ROLES):
        for suffix in suffixes:
            assert f"{name}-{suffix}" in view


def test_scheme_variables() -> None:
    palette = _palette(schemes={"light": {"name": "x", "author": "someone"}})
    dark, light = mustache_view(palette, "dark"), mustache_view(palette, "light")
    assert dark["scheme-name"] == "Gruvbox Dark, Hard!"
    assert dark["scheme-slug"] == "gruvbox-dark-hard"
    assert dark["scheme-slug-underscored"] == "gruvbox_dark_hard"
    assert dark["scheme-system"] == "base24"
    assert (dark["scheme-variant"], light["scheme-variant"]) == ("dark", "light")
    assert dark["scheme-is-dark-variant"] and not dark["scheme-is-light-variant"]
    assert light["scheme-is-light-variant"] and not light["scheme-is-dark-variant"]
    assert (dark["scheme-author"], light["scheme-author"]) == ("", "someone")


def test_render() -> None:
    template = (
        "# {{scheme-name}} by {{scheme-author}}\n"
        "background #{{base00-hex}}\n"
        "accent {{accent-rgb-r}},{{accent-rgb-g}},{{accent-rgb-b}} & more\n"
        "{{#scheme-is-dark-variant}}dark{{/scheme-is-dark-variant}}"
        "{{^scheme-is-dark-variant}}light{{/scheme-is-dark-variant}}\n"
    )
    out = render_mustache(template, mustache_view(_palette(), "dark"))
    assert out == (
        f"# Gruvbox Dark, Hard! by \nbackground #{DARK['base00'][1:]}\n"
        "accent 124,175,194 & more\ndark\n"
    )


@pytest.mark.parametrize(
    ("template", "message"),
    [
        ("{{base18-hex}}", "base18-hex"),
        ("{{#nope}}x{{/nope}}", "nope"),
        ("{{#scheme-is-dark-variant}}x{{/base00-hex}}", "mismatch"),
        ("{{> header}}", "header"),
    ],
)
def test_render_errors(template: str, message: str) -> None:
    with pytest.raises(RenderError, match=message):
        render_mustache(template, mustache_view(_palette(), "dark"))


def test_partials_are_never_read_from_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "header.mustache").write_text("from disk")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RenderError, match="not found in partials"):
        render_mustache("{{> header}}", {})


def _pywal(template: str, wallpaper: Path | None = None) -> str:
    view = pywal_view(_palette(), "dark", wallpaper)
    view["color4"] = PywalColour("#7cafc2")
    return render_pywal(template, view)


def test_pywal_view() -> None:
    palette = _palette()
    view = pywal_view(palette, "dark", Path("/pics/a.jpg"))
    base24 = palette.variants["dark"].base24
    assert [view[f"color{i}"].hex for i in (0, 1, 4, 8, 9, 15)] == [
        base24[key] for key in ("base00", "base08", "base0D", "base03", "base12", "base07")
    ]
    assert view["background"].hex == base24["base00"]
    assert view["foreground"].hex == view["cursor"].hex == base24["base05"]
    assert (view["wallpaper"], view["alpha"], view["checksum"]) == (
        "/pics/a.jpg",
        "100",
        "gruvbox-dark-hard",
    )
    assert pywal_view(palette, "dark", None)["wallpaper"] == ""


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        # Hand-computed from pywal16's util.Color (af71171) for #7cafc2 = (124, 175, 194).
        ("{color4}", "#7cafc2"),
        ("{color4.strip}", "7cafc2"),
        ("{color4.rgb}", "124,175,194"),
        ("{color4.rgbspace}", "124 175 194"),
        ("{color4.xrgba}", "7c/af/c2/ff"),
        ("{color4.rgba}", "rgba(124,175,194,1.0)"),
        ("{color4.hex_argb}", "#FF7cafc2"),
        ("{color4.alpha}", "[100]#7cafc2"),
        ("{color4.alpha_dec}", "1.0"),
        ("{color4.alpha_hex}", "FF"),
        ("{color4.decimal}", "#8171458"),
        ("{color4.decimal_strip}", "8171458"),
        ("{color4.octal}", "#37127702"),
        ("{color4.octal_strip}", "37127702"),
        ("{color4.red}", "0.486"),
        ("{color4.green}", "0.686"),
        ("{color4.blue}", "0.761"),
        ("{color4.red_hex}", "7c"),
        ("{color4.blue_hex}", "c2"),
        ("{color4.green_dec}", "175"),
        ("{color4.w3_luminance}", "0.38810087752096467"),
        # Channel values are truncated.
        ("{color4.lighten(10)}", "#89b7c8"),
        ("{color4.darken(25)}", "#5d8391"),
        # pywal16 strips the decimal point and the sign: 25 % and 10 %.
        ("{color4.lighten(2.5)}", "#9cc3d1"),
        ("{color4.darken(-10)}", "#6f9dae"),
        # saturate sets the HLS saturation.
        ("{color4.saturate(0)}", "#9f9f9f"),
        ("{color4.saturate(50)}", "#6fb4cf"),
        ("{color4.foxify(0.2)}", "#94d2e8"),
        ("{color4.foxify(1.5)}", "#ffffff"),
        ("{color4.lighten(100)}", "#ffffff"),
        ("{color4.darken(100).strip}", "000000"),
        ("{color4.adjust_alpha(0.5).rgba}", "rgba(124,175,194,0.5)"),
        ("{color4.adjust_alpha(80).hex_argb}", "#CC7cafc2"),
        ("{color4.adjust_alpha().alpha}", "[100]#7cafc2"),
        ("{color4.lighten(10).darken(10).strip}", "7ba4b4"),
        # Every function but adjust_alpha returns a colour at the default alpha (pywal16 does).
        ("{color4.adjust_alpha(0.5).lighten(20).rgba}", "rgba(150,191,206,1.0)"),
        ("{color4.lighten(20).adjust_alpha(0.5).rgba}", "rgba(150,191,206,0.5)"),
        ("{alpha}", "100"),
        ("{{literal}} {{color4}} x{color4}x", "{literal} {color4} x#7cafc2x"),
        ('{{ "a": "{color4}" }}', '{ "a": "#7cafc2" }'),
    ],
)
def test_pywal_markers(marker: str, expected: str) -> None:
    assert _pywal(marker) == expected


def test_pywal_wallpaper() -> None:
    assert _pywal("wallpaper='{wallpaper}'", Path("/p/a b.jpg")) == "wallpaper='/p/a b.jpg'"


@pytest.mark.parametrize(
    ("template", "message"),
    [
        ("{color4.nope}", "no colour property 'nope'"),
        ("{color4.nope(1)}", "no colour function 'nope'"),
        ("{color4.strip()}", "no colour function 'strip'"),
        ("{color99}", "no variable 'color99'"),
        ("a { color: red; }", "does not parse"),
        ("{wallpaper.strip}", "is not a colour"),
        ("{color4.lighten()}", "pywal function lighten"),
        ("{color4.lighten(a)}", "'a' is not a number"),
        ("{color4.lighten(150)}", "left the colour range"),
    ],
)
def test_pywal_errors(template: str, message: str) -> None:
    with pytest.raises(RenderError, match=re.escape(message)):
        _pywal(template)
