"""Views of a palette and the renderers that fill templates from them.

docs/design.md, "Theme engine (v0.2)", "Formats and views". A view is the set of variables a
template format expects, made from one variant of a palette. Mustache is tinted-theming's
builder spec: per colour (every base24 key and every role) its hex, per-channel hex, BGR hex,
RGB 0-255, RGB 0-65535 and 0-1 decimals, plus the scheme variables, and amontillado's own
`gnome-<colour>-hex` (GNOME's palette remapped, amontillado.gnome). pywal is pywal16's
marker syntax (`{color0}`, `{color0.rgba}`, `{color0.lighten(10).strip}`) over its sixteen
positional colours. A variable a template names that the view does not have is a render error,
never an empty string.
"""

from __future__ import annotations

import colorsys
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import pystache
from pystache.common import PystacheError
from pystache.parser import ParsingError

from amontillado.gnome import gnome_palette
from amontillado.palette import Palette, Variant


class RenderError(Exception):
    """A template cannot be rendered; the message says why."""


def mustache_view(palette: Palette, variant: str) -> dict[str, object]:
    """The tinted builder variables of `palette`'s `variant`."""
    colours: Variant = palette.variants[variant]
    view: dict[str, object] = {}
    for name, colour in (*colours.base24.items(), *colours.roles.items()):
        hex_ = colour.removeprefix("#")
        channels = dict(zip("rgb", (hex_[0:2], hex_[2:4], hex_[4:6]), strict=True))
        view[f"{name}-hex"] = hex_
        view[f"{name}-hex-bgr"] = channels["b"] + channels["g"] + channels["r"]
        for channel, pair in channels.items():
            value = int(pair, 16)
            view[f"{name}-hex-{channel}"] = pair
            view[f"{name}-rgb-{channel}"] = value
            view[f"{name}-rgb16-{channel}"] = value * 257
            view[f"{name}-dec-{channel}"] = f"{value / 255:.8f}"
    # GNOME's palette remapped (libadwaita-vars); hex only, outside the builder spec.
    for name, colour in gnome_palette(colours).items():
        view[f"gnome-{name}-hex"] = colour.removeprefix("#")
    slug = _slug(palette.name)
    view.update(
        {
            "scheme-name": palette.name,
            # Template headers name them; amontillado's palettes have no description.
            "scheme-author": _author(palette, variant),
            "scheme-description": "",
            "scheme-slug": slug,
            "scheme-slug-underscored": slug.replace("-", "_"),
            "scheme-system": "base24",
            "scheme-variant": variant,
            "scheme-is-dark-variant": variant == "dark",
            "scheme-is-light-variant": variant == "light",
        }
    )
    return view


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "palette"


def _author(palette: Palette, variant: str) -> str:
    schemes = palette.source.get("schemes")
    scheme = schemes.get(variant) if isinstance(schemes, dict) else None
    author = scheme.get("author") if isinstance(scheme, dict) else None
    return author if isinstance(author, str) else ""


def render_mustache(template: str, view: dict[str, object]) -> str:
    """`template` filled from `view`. Raises RenderError for an unknown variable, a template
    that does not parse, or a partial (templates are single files)."""
    # No HTML escaping: the output is a config file. An empty partials mapping keeps `{{> x}}`
    # from reading x.mustache out of the working directory.
    renderer = pystache.Renderer(missing_tags="strict", escape=lambda text: text, partials={})
    try:
        return renderer.render(template, view)
    # ParsingError is not a PystacheError.
    except (PystacheError, ParsingError) as exc:
        raise RenderError(str(exc)) from exc


# pywal16's colour numbers by the base24 ANSI table (docs/design.md, "Formats and views").
PYWAL_COLOURS = (
    "base00", "base08", "base0B", "base0A", "base0D", "base0E", "base0C", "base05",
    "base03", "base12", "base14", "base13", "base16", "base17", "base15", "base07",
)  # fmt: skip
PYWAL_ALPHA = "100"


@dataclass(frozen=True)
class PywalColour:
    """pywal16's `Color`: a hex colour and the alpha its alpha properties report. The
    properties and functions below mirror pywal16's (`pywal/util.py`, MIT), including its
    arithmetic: channel values are truncated, not rounded, and every function but
    `adjust_alpha` returns a new colour at the default alpha (so an adjusted alpha is lost by
    a later `lighten`). tests/test_pywal_parity.py checks them against pywal16 itself."""

    hex: str
    alpha: str = PYWAL_ALPHA

    @property
    def rgb_values(self) -> tuple[int, int, int]:
        value = self.hex.removeprefix("#")
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)

    def property(self, name: str) -> str:
        """The value of property `name`, as pywal16 prints it."""
        prop = _PYWAL_PROPERTIES.get(name)
        if prop is None:
            raise RenderError(f"pywal has no colour property {name!r}")
        return str(prop(self))

    def call(self, name: str, args: list[float]) -> PywalColour:
        """The colour function `name` applied, as pywal16 applies it."""
        function = _PYWAL_FUNCTIONS.get(name)
        if function is None:
            raise RenderError(f"pywal has no colour function {name!r}")
        try:
            return function(self, *args)
        except TypeError as exc:
            raise RenderError(f"pywal function {name}: {exc}") from exc


def _alpha_int(value: object) -> int:
    # pywal16's alpha_integrify: a fraction below 1 is a share, the rest a percentage.
    alpha = abs(float(str(value)))
    if alpha < 1:
        alpha *= 100
    return int(min(alpha, 100))


def _percent(value: float) -> float:
    # pywal16 strips every non-digit, the decimal point and a minus sign included, so
    # lighten(2.5) is 25 % and darken(-10) is 10 %.
    return float(re.sub(r"[\D.]", "", str(value))) / 100


def _hex(channels: tuple[float, float, float] | list[float]) -> str:
    values = [int(channel) for channel in channels]
    if any(not 0 <= value <= 255 for value in values):
        # pywal16 would print an invalid colour (three hex digits): fail instead.
        raise RenderError(f"pywal arithmetic left the colour range: {values}")
    return "#{:02x}{:02x}{:02x}".format(*values)


def _lighten(colour: PywalColour, percent: float) -> PywalColour:
    amount = _percent(percent)
    return PywalColour(_hex([c + (255 - c) * amount for c in colour.rgb_values]))


def _darken(colour: PywalColour, percent: float) -> PywalColour:
    amount = _percent(percent)
    return PywalColour(_hex([c * (1 - amount) for c in colour.rgb_values]))


def _saturate(colour: PywalColour, percent: float) -> PywalColour:
    # pywal16 sets the HLS saturation to the amount; it does not add to it.
    hue, lightness, _ = colorsys.rgb_to_hls(*(c / 255 for c in colour.rgb_values))
    rgb = colorsys.hls_to_rgb(hue, lightness, _percent(percent))
    return PywalColour(_hex([c * 255 for c in rgb]))


def _foxify(colour: PywalColour, amount: float) -> PywalColour:
    # pywalfox's lightening, as pywal16 has it.
    factor = float(amount)
    channels = [max(c, 10) for c in colour.rgb_values]
    return PywalColour(_hex([min(max(0, int(c + c * factor)), 255) for c in channels]))


def _adjust_alpha(colour: PywalColour, alpha: float = 100) -> PywalColour:
    return replace(colour, alpha=str(alpha))


def _w3_luminance(colour: PywalColour) -> float:
    linear = []
    for channel in (float(f"{c / 255.0:.3f}") for c in colour.rgb_values):
        linear.append(channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4)
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


_PYWAL_FUNCTIONS: dict[str, Callable[..., PywalColour]] = {
    "lighten": _lighten,
    "darken": _darken,
    "saturate": _saturate,
    "foxify": _foxify,
    "adjust_alpha": _adjust_alpha,
}
_PYWAL_PROPERTIES: dict[str, Callable[[PywalColour], object]] = {
    "rgb": lambda c: "{},{},{}".format(*c.rgb_values),
    "rgbspace": lambda c: "{} {} {}".format(*c.rgb_values),
    "xrgba": lambda c: "{}{}/{}{}/{}{}/ff".format(*c.hex.lower().removeprefix("#")),
    "rgba": lambda c: "rgba({},{},{},{})".format(*c.rgb_values, _alpha_int(c.alpha) / 100),
    "hex_argb": lambda c: f"#{int(_alpha_int(c.alpha) * 255 / 100):02X}{c.hex[1:]}",
    "alpha": lambda c: f"[{_alpha_int(c.alpha)}]{c.hex}",
    "alpha_dec": lambda c: _alpha_int(c.alpha) / 100,
    "alpha_hex": lambda c: f"{int(_alpha_int(c.alpha) * 255 / 100):02X}",
    "decimal": lambda c: f"#{int(c.hex[1:], 16)}",
    "decimal_strip": lambda c: int(c.hex[1:], 16),
    "octal": lambda c: f"#{int(c.hex[1:], 16):o}",
    "octal_strip": lambda c: f"{int(c.hex[1:], 16):o}",
    "strip": lambda c: c.hex[1:],
    "red": lambda c: f"{c.rgb_values[0] / 255.0:.3f}",
    "green": lambda c: f"{c.rgb_values[1] / 255.0:.3f}",
    "blue": lambda c: f"{c.rgb_values[2] / 255.0:.3f}",
    "red_hex": lambda c: c.hex[1:3],
    "green_hex": lambda c: c.hex[3:5],
    "blue_hex": lambda c: c.hex[5:],
    "red_dec": lambda c: c.rgb_values[0],
    "green_dec": lambda c: c.rgb_values[1],
    "blue_dec": lambda c: c.rgb_values[2],
    "w3_luminance": _w3_luminance,
}


def pywal_view(palette: Palette, variant: str, wallpaper: Path | None) -> dict[str, object]:
    """pywal16's variables for `palette`'s `variant`: `color0`-`color15` by the ANSI table,
    `background`, `foreground`, `cursor` (colours); `wallpaper`, `alpha`, `checksum` (text)."""
    base24 = palette.variants[variant].base24
    view: dict[str, object] = {
        f"color{number}": PywalColour(base24[key]) for number, key in enumerate(PYWAL_COLOURS)
    }
    view.update(
        {
            "background": PywalColour(base24["base00"]),
            "foreground": PywalColour(base24["base05"]),
            "cursor": PywalColour(base24["base05"]),
            "wallpaper": "" if wallpaper is None else str(wallpaper),
            "alpha": PYWAL_ALPHA,
            # pywal16's is an MD5 of the picture, for caching; nothing reads it back here.
            "checksum": _slug(palette.name),
        }
    )
    return view


# Escapes ({{, }}) and markers ({...}), one line at a time as pywal16 reads a template.
_PYWAL_TOKEN = re.compile(r"\{\{|\}\}|\{([^{}\n]+)\}")
_PYWAL_MARKER = re.compile(
    r"(?P<name>[a-zA-Z][a-zA-Z0-9_]*)(?P<rest>(?:\.[a-zA-Z][a-zA-Z0-9_]*\([^)]*\))*)"
    r"(?:\.(?P<prop>[a-zA-Z][a-zA-Z0-9_]*))?"
)
_PYWAL_CALL = re.compile(r"\.([a-zA-Z][a-zA-Z0-9_]*)\(([^)]*)\)")
_PYWAL_NUMBER = re.compile(r"-?\d+(\.\d+)?")


def render_pywal(template: str, view: dict[str, object]) -> str:
    """`template` filled from `view` (pywal16 syntax: `{color0}`, `{color0.rgba}`,
    `{color0.lighten(10).strip}`, `{{` and `}}` for literal braces). Raises RenderError for a
    marker that does not parse (pywal16 skips the whole file then), an unknown colour,
    function or property."""

    def substitute(match: re.Match[str]) -> str:
        token = match.group(0)
        if token in ("{{", "}}"):
            return token[0]
        return _pywal_marker(match.group(1), view)

    # Positionally, unlike pywal16, which replaces a marker's first occurrence in its line
    # (and so can rewrite an escaped copy of it earlier in the line).
    return _PYWAL_TOKEN.sub(substitute, template)


def _pywal_marker(marker: str, view: dict[str, object]) -> str:
    match = _PYWAL_MARKER.fullmatch(marker)
    if match is None:
        raise RenderError(f"pywal marker {{{marker}}} does not parse")
    name = match["name"]
    if name not in view:
        raise RenderError(f"pywal has no variable {name!r} (in {{{marker}}})")
    value = view[name]
    calls = _PYWAL_CALL.findall(match["rest"])
    if not isinstance(value, PywalColour):
        if calls or match["prop"]:
            raise RenderError(f"pywal variable {name} is not a colour (in {{{marker}}})")
        return str(value)
    for function, args in calls:
        numbers = []
        for arg in filter(None, (a.strip() for a in args.split(","))):
            if not _PYWAL_NUMBER.fullmatch(arg):
                raise RenderError(f"pywal marker {{{marker}}}: {arg!r} is not a number")
            numbers.append(float(arg) if "." in arg else int(arg))
        value = value.call(function, numbers)
    return value.property(match["prop"]) if match["prop"] else value.hex
