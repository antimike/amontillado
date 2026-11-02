"""amontillado's pywal renderer against pywal16's own (a dev dependency, pinned to the release
whose `export.py` and `util.py` match the registry's pywal16 commit).

Each marker is executed by pywal16's `Parser` over its `Color` and by `render_pywal`; the
results must be equal, except where amontillado fails on purpose (docs/design.md, "Formats and
views"): there pywal16's result must be the invalid colour amontillado refuses to print.
"""

from __future__ import annotations

import random
import re
from pathlib import Path

import pytest

pywal_export = pytest.importorskip("pywal.export")
pywal_util = pytest.importorskip("pywal.util")

from amontillado.render import (  # noqa: E402  # after the importorskip guards
    _PYWAL_PROPERTIES,
    PywalColour,
    RenderError,
    render_pywal,
)

PROPERTIES = sorted(_PYWAL_PROPERTIES)
FUNCTIONS = [
    *(f"lighten({a})" for a in (0, 5, 10, 2.5, -10, 50, 99, 100, 150)),
    *(f"darken({a})" for a in (0, 5, 25, 2.5, -10, 50, 100, 150)),
    *(f"saturate({a})" for a in (0, 25, 50, 75, 100)),
    *(f"foxify({a})" for a in (0, 0.2, 0.5, 1.5, -0.3, -2)),
    *(f"adjust_alpha({a})" for a in (0, 0.5, 50, 80, 100, 150, -0.2, 0.05)),
    "adjust_alpha()",
]
EDGES = ["#000000", "#ffffff", "#808080", "#ff0000", "#00ff00", "#0000ff", "#0a0a0a", "#fefefe"]
RNG = random.Random(20261102)
COLOURS = EDGES + [f"#{RNG.randrange(1 << 24):06x}" for _ in range(300)]
_VALID = re.compile(r"#[0-9a-f]{6}")


def _pywal16(marker: str, hex_: str) -> str:
    parsed = pywal_export.Parser.parse_marker(marker)
    assert parsed is not None, marker
    colours = {"color4": pywal_util.Color(hex_)}
    return pywal_export.Parser.execute_marker(colours, parsed[0])


def _ours(marker: str, hex_: str) -> str:
    return render_pywal("{" + marker + "}", {"color4": PywalColour(hex_)})


def _compare(marker: str, hex_: str) -> None:
    try:
        expected = _pywal16(marker, hex_)
    except (ValueError, TypeError):
        # pywal16 fails the marker (a ValueError it logs, leaving the marker; a TypeError that
        # stops it): so must amontillado.
        with pytest.raises(RenderError):
            _ours(marker, hex_)
        return
    try:
        actual = _ours(marker, hex_)
    except RenderError as exc:
        assert "left the colour range" in str(exc), (marker, hex_, exc)
        # pywal16 printed a channel outside 0-255: not a #rrggbb colour. Compare its colour,
        # before any trailing property.
        colour = marker if marker.endswith(")") else marker.rsplit(".", 1)[0]
        assert not _VALID.fullmatch(_pywal16(colour, hex_)), (marker, hex_)
        return
    assert actual == expected, (marker, hex_)


@pytest.mark.parametrize("prop", PROPERTIES)
def test_every_property(prop: str) -> None:
    for hex_ in COLOURS:
        _compare(f"color4.{prop}", hex_)


@pytest.mark.parametrize("function", FUNCTIONS)
def test_every_function(function: str) -> None:
    for hex_ in COLOURS:
        _compare(f"color4.{function}", hex_)
        _compare(f"color4.{function}.strip", hex_)
        _compare(f"color4.{function}.rgba", hex_)


def test_chains() -> None:
    chains = [
        "lighten(10).darken(10)",
        "darken(30).saturate(80).rgb",
        "adjust_alpha(0.5).lighten(20).rgba",
        "foxify(0.2).adjust_alpha(70).hex_argb",
        "saturate(0).lighten(2.5).alpha",
    ]
    for hex_ in COLOURS:
        for chain in chains:
            _compare(f"color4.{chain}", hex_)


def test_whole_template(tmp_path: Path) -> None:
    # A template with escapes, every special name and markers in several places per line.
    template = (
        "{{\n"
        '  "wallpaper": "{wallpaper}", "alpha": "{alpha}", "checksum": "{checksum}",\n'
        '  "bg": "{background}", "fg": "{foreground.rgba}", "c": "{cursor.strip}",\n'
        "  {color0} {color1.rgb} x{color2}y {color15.lighten(10).strip}\n"
        "}}\n"
        "${{LS_COLORS}} {{literal}}\n"
    )
    hexes = [f"#{RNG.randrange(1 << 24):06x}" for _ in range(16)]
    special = {"background": hexes[0], "foreground": hexes[7], "cursor": hexes[7]}
    names = {f"color{i}": h for i, h in enumerate(hexes)}
    source = tmp_path / "t"
    source.write_text(template)
    data = {"wallpaper": "/p/a.jpg", "checksum": "slug", "alpha": "100"}
    data |= {"special": special, "colors": names}
    pywal_export.template(pywal_export.flatten_colors(data), str(source), str(tmp_path / "out"))
    view: dict[str, object] = {k: PywalColour(v) for k, v in {**names, **special}.items()}
    view |= {"wallpaper": "/p/a.jpg", "alpha": "100", "checksum": "slug"}
    assert render_pywal(template, view) == (tmp_path / "out").read_text()
