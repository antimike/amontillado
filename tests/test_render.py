from __future__ import annotations

from pathlib import Path

import pytest

from amontillado.palette import BASE24_KEYS, ROLES, Palette, complete_variant
from amontillado.render import RenderError, mustache_view, render_mustache

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
