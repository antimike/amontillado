"""matugen's template language, the subset matugen-themes uses, over a Material view of a palette.

docs/design.md, "Theme engine (v0.2)", "Formats and views" (matugen). amontillado renders these
templates itself rather than running matugen, so any palette can drive them. The view gives
every Material role matugen 4.2 exports (`colors.<role>.<dark|light|default>`), computed from
the palette, the palette's base16 keys (`base16.base0a.dark`), `image`, `mode` and
`is_dark_mode`, and the custom colours neovim/matugen.lua names (`colors.red`, from the
palette's named hues: `CUSTOM_COLOURS`).

Supported, as matugen 4.2 does it (checked against its output, tests/test_matugen.py):

- `{{ path }}`: a colour field (`hex`, `hex_stripped`, `hex_alpha`, `hex_alpha_stripped`,
  `rgb`, `rgba`, `hsl`, `hsla`, `red`, `green`, `blue`), a loop variable or `image`;
- filters `| name: arg, ...`: `set_alpha`, `set_lightness` (sets HSL lightness: matugen-themes'
  negative values give black, as in matugen), `auto_lightness` (HSL lightness moved toward
  the middle), `lighten`, `saturate: N, hsl`, `replace: "a", "b"`; the colour is formatted by
  the path's last field after them;
- `<* for name, value in colors *>` (and `base16`), in key order, with `loop.index`,
  `loop.first`, `loop.last`; `<* if {{ cond }} *>`, `<* if not ... *>`, `<* else *>`,
  `<* endif *>`; backslash escapes of `{{`, `}}`, `<*`, `*>` and `\\`.

Colour arithmetic follows matugen's (the `colorsys` crate's): channels are floats, HSL steps
clamp, `hex` rounds while `rgb` and the channels truncate. Anything else (a `palettes` loop, a
range, an unknown filter, role or field) is a render error naming it.
"""

from __future__ import annotations

import math
import re
import struct
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from amontillado.colour import contrast_ratio, hex_to_oklch, hue_distance, oklch_to_hex
from amontillado.palette import ACCENT_KEYS, BASE16_KEYS, Palette, Variant


class MatugenError(Exception):
    """A matugen template cannot be rendered; the message says why."""


# --- colour arithmetic (colorsys 0.6.7, as matugen 4.2 uses it) ----------------------------------


@dataclass(frozen=True)
class Rgb:
    red: float
    green: float
    blue: float
    alpha: float = 1.0


@dataclass(frozen=True)
class Hsl:
    hue: float
    saturation: float
    lightness: float
    alpha: float = 1.0


Colour = Rgb | Hsl


def _clamp(value: float, highest: float) -> float:
    return 0.0 if value < 0.0 else highest if value > highest else value


def _bound(value: float, entire: float) -> float:
    while value < 0.0 or value > entire:
        value = value + entire if value < 0.0 else value - entire
    return value


def _f32(value: float) -> float:
    return struct.unpack("f", struct.pack("f", value))[0]


def parse_hex(colour: str) -> Rgb:
    """A `#rrggbb` colour as matugen holds it: each channel parsed to an f32 ratio, then times
    255 (csscolorparser), so 231 is 231.0000014. Truncating formats (`rgb`, `red`) and the
    filters depend on it."""
    hex_ = colour.removeprefix("#")
    red, green, blue = (_f32(int(hex_[i : i + 2], 16) / 255.0) * 255.0 for i in (0, 2, 4))
    return Rgb(red, green, blue)


def to_hsl(colour: Colour) -> Hsl:
    if isinstance(colour, Hsl):
        return colour
    channels = [colour.red / 255.0, colour.green / 255.0, colour.blue / 255.0]
    # The first channel reaching the maximum (minimum) wins, as colorsys's min_max.
    high, high_index = channels[0], 0
    low = channels[0]
    for index in (1, 2):
        if channels[index] > high:
            high, high_index = channels[index], index
        if channels[index] < low:
            low = channels[index]
    both = high + low
    lightness = both / 2.0
    if high == low:
        return Hsl(0.0, 0.0, lightness * 100.0, colour.alpha)
    delta = high - low
    saturation = delta / (2.0 - both) if lightness > 0.5 else delta / both
    red, green, blue = channels
    if high_index == 0:
        hue = (green - blue) / delta + (6.0 if green < blue else 0.0)
    elif high_index == 1:
        hue = (blue - red) / delta + 2.0
    else:
        hue = (red - green) / delta + 4.0
    return Hsl(hue * 60.0, saturation * 100.0, lightness * 100.0, colour.alpha)


def _rgb_unit(unit: float, temp1: float, temp2: float) -> float:
    result = temp2
    if 6.0 * unit < 1.0:
        result = temp2 + (temp1 - temp2) * 6.0 * unit
    elif 2.0 * unit < 1.0:
        result = temp1
    elif 3.0 * unit < 2.0:
        result = temp2 + (temp1 - temp2) * (2.0 / 3.0 - unit) * 6.0
    return result * 255.0


def to_rgb(colour: Colour) -> Rgb:
    if isinstance(colour, Rgb):
        return colour
    hue, saturation, lightness = (
        colour.hue / 360.0,
        colour.saturation / 100.0,
        colour.lightness / 100.0,
    )
    if saturation == 0.0:
        unit = 255.0 * lightness
        return Rgb(unit, unit, unit, colour.alpha)
    if lightness < 0.5:
        temp1 = lightness * (1.0 + saturation)
    else:
        temp1 = lightness + saturation - lightness * saturation
    temp2 = 2.0 * lightness - temp1
    return Rgb(
        _rgb_unit(_bound(hue + 1.0 / 3.0, 1.0), temp1, temp2),
        _rgb_unit(_bound(hue, 1.0), temp1, temp2),
        _rgb_unit(_bound(hue - 1.0 / 3.0, 1.0), temp1, temp2),
        colour.alpha,
    )


def _rgb_from_hsl(hsl: Hsl) -> Rgb:
    """An Rgb's channels set from `hsl` (colorsys `_apply_tuple`: each clamped to 0-255)."""
    rgb = to_rgb(hsl)
    return Rgb(_clamp(rgb.red, 255.0), _clamp(rgb.green, 255.0), _clamp(rgb.blue, 255.0), hsl.alpha)


def _lighten(colour: Colour, amount: float) -> Colour:
    hsl = to_hsl(colour)
    hsl = replace(hsl, lightness=_clamp(hsl.lightness + amount, 100.0))
    return _rgb_from_hsl(hsl) if isinstance(colour, Rgb) else hsl


def _saturate(colour: Colour, amount: float) -> Colour:
    hsl = to_hsl(colour)
    hsl = replace(hsl, saturation=_clamp(hsl.saturation + amount, 100.0))
    return _rgb_from_hsl(hsl) if isinstance(colour, Rgb) else hsl


def _set_alpha(colour: Colour, alpha: float) -> Colour:
    return replace(colour, alpha=_clamp(alpha, 1.0))


def _round(value: float) -> int:
    """f64::round: halves away from zero."""
    return math.floor(value + 0.5) if value >= 0 else -math.floor(-value + 0.5)


def _u8(value: float) -> int:
    """Rust's `as u8`: truncated toward zero, saturating."""
    if math.isnan(value):
        return 0
    return max(0, min(255, int(value)))


def _alpha_u8(alpha: float) -> int:
    return _round(_clamp(alpha, 1.0) * 255.0) if alpha <= 1.0 else _round(min(alpha, 255.0))


def _display(value: float) -> str:
    """Rust's `{}` for an f64: the shortest form, without a trailing `.0`."""
    text = repr(value)
    return text[:-2] if text.endswith(".0") else text


def _hex(colour: Rgb) -> str:
    return "#" + "".join(
        f"{_round(channel):02x}" for channel in (colour.red, colour.green, colour.blue)
    )


def _hex_alpha(colour: Rgb) -> str:
    channels = (_u8(colour.red), _u8(colour.green), _u8(colour.blue), _alpha_u8(colour.alpha))
    return "".join(f"{channel:02X}" for channel in channels)


def _alpha_text(alpha: float) -> str:
    return _display(_round(alpha * 100.0) / 100.0)


def _f0(value: float) -> str:
    """Rust's `{:.0}`: round half to even, as Python's format."""
    return f"{value:.0f}"


FORMATS: dict[str, Callable[[Rgb], str]] = {
    "hex": _hex,
    "hex_stripped": lambda c: _hex(c)[1:],
    "hex_alpha": lambda c: "#" + _hex_alpha(c),
    "hex_alpha_stripped": _hex_alpha,
    "rgb": lambda c: f"rgb({_u8(c.red)}, {_u8(c.green)}, {_u8(c.blue)})",
    "rgba": lambda c: f"rgba({_f0(c.red)}, {_f0(c.green)}, {_f0(c.blue)}, {_alpha_text(c.alpha)})",
    "hsl": lambda c: (lambda h: f"hsl({_f0(h.hue)}, {_f0(h.saturation)}%, {_f0(h.lightness)}%)")(
        to_hsl(c)
    ),
    "hsla": lambda c: (
        lambda h: (
            f"hsla({_f0(h.hue)}, {_f0(h.saturation)}%, {_f0(h.lightness)}%, {_alpha_text(h.alpha)})"
        )
    )(to_hsl(c)),
    "red": lambda c: str(int(c.red)),
    "green": lambda c: str(int(c.green)),
    "blue": lambda c: str(int(c.blue)),
}


def format_colour(colour: Colour, name: str) -> str:
    if name not in FORMATS:
        raise MatugenError(f"unknown colour field {name!r}")
    return FORMATS[name](to_rgb(colour))


# --- filters ------------------------------------------------------------------------------------

Value = str | float | int | bool | Colour


def _number(name: str, args: list[object], count: int = 1) -> list[float]:
    numbers = [arg for arg in args if isinstance(arg, (int, float)) and not isinstance(arg, bool)]
    if len(args) != count or len(numbers) < 1:
        raise MatugenError(f"filter {name}: expected {count} argument(s), got {args!r}")
    return [float(number) for number in numbers]


def _colour_filter(name: str, value: Value) -> Colour:
    if not isinstance(value, (Rgb, Hsl)):
        raise MatugenError(f"filter {name} needs a colour, got {value!r}")
    return value


def _filter(name: str, args: list[object], value: Value, field_name: str | None) -> Value:
    if name == "replace":
        if len(args) != 2 or not all(isinstance(arg, str) for arg in args):
            raise MatugenError(f"filter replace: expected two strings, got {args!r}")
        if isinstance(value, (Rgb, Hsl)):
            if field_name is None:
                raise MatugenError("filter replace on a colour needs a field (hex, rgb, ...)")
            value = format_colour(value, field_name)
        return str(value).replace(str(args[0]), str(args[1]))
    colour = _colour_filter(name, value)
    if name == "set_alpha":
        return _set_alpha(colour, _number(name, args)[0])
    if name == "set_lightness":
        hsl = to_hsl(colour)
        return replace(hsl, lightness=_clamp(_number(name, args)[0], 100.0))
    if name == "lighten":
        return _lighten(colour, _number(name, args)[0])
    if name == "auto_lightness":
        amount = _number(name, args)[0]
        return _lighten(colour, amount if to_hsl(colour).lightness < 50.0 else -amount)
    if name == "saturate":
        if len(args) != 2 or str(args[1]).lower() != "hsl":
            raise MatugenError(f"filter saturate: expected N, hsl; got {args!r}")
        return _saturate(colour, _number(name, args[:1])[0])
    raise MatugenError(f"unknown filter {name!r}")


# --- the template language ----------------------------------------------------------------------

_ESCAPES = ("{{", "}}", "<*", "*>", "\\")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PATH = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*|_\d+)(?:\s*\.\s*([A-Za-z_][A-Za-z0-9_]*|_\d+))*\s*")
_NUMBER = re.compile(r"[+-]?\d+(\.\d+)?")


@dataclass
class _Node:
    kind: str  # raw, value, for, if
    text: str = ""
    path: list[str] = field(default_factory=list)
    filters: list[tuple[str, list[object]]] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    body: list[_Node] = field(default_factory=list)
    other: list[_Node] = field(default_factory=list)
    negated: bool = False


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.at = 0

    def error(self, message: str) -> MatugenError:
        line = self.text.count("\n", 0, self.at) + 1
        return MatugenError(f"line {line}: {message}")

    def parse(self, until: tuple[str, ...] = ()) -> tuple[list[_Node], str | None]:
        """Nodes up to a block tag in `until` (returned, consumed), or to the end."""
        nodes: list[_Node] = []
        raw: list[str] = []
        text = self.text
        while self.at < len(text):
            if text.startswith("\\", self.at):
                escaped = next((e for e in _ESCAPES if text.startswith(e, self.at + 1)), None)
                if escaped is not None:
                    raw.append(escaped)
                    self.at += 1 + len(escaped)
                    continue
            if text.startswith("{{", self.at):
                self._flush(nodes, raw)
                nodes.append(self._keyword())
                continue
            if text.startswith("<*", self.at):
                self._flush(nodes, raw)
                tag = self._block_tag()
                word = tag.split(None, 1)[0] if tag.strip() else ""
                if word in until:
                    return nodes, tag
                if word == "for":
                    nodes.append(self._for(tag))
                elif word == "if":
                    nodes.append(self._if(tag))
                else:
                    raise self.error(f"unsupported block <* {tag.strip()} *>")
                continue
            raw.append(text[self.at])
            self.at += 1
        self._flush(nodes, raw)
        if until:
            raise self.error(f"missing <* {until[-1]} *>")
        return nodes, None

    @staticmethod
    def _flush(nodes: list[_Node], raw: list[str]) -> None:
        if raw:
            nodes.append(_Node("raw", "".join(raw)))
            raw.clear()

    def _keyword(self) -> _Node:
        end = self.text.find("}}", self.at + 2)
        if end < 0:
            raise self.error("unclosed {{")
        inside = self.text[self.at + 2 : end]
        self.at = end + 2
        return self._expression(inside)

    def _expression(self, inside: str) -> _Node:
        head, *filters = _split(inside, "|")
        match = _PATH.fullmatch(head)
        if match is None:
            raise self.error(f"unsupported expression {{{{{inside}}}}}")
        path = [part.strip() for part in head.split(".")]
        node = _Node("value", path=path)
        for item in filters:
            name, _, arguments = item.partition(":")
            name = name.strip()
            if not _IDENT.fullmatch(name):
                raise self.error(f"unsupported filter {item.strip()!r}")
            args = [_literal(arg, self) for arg in _split(arguments, ",")] if arguments else []
            node.filters.append((name, args))
        return node

    def _block_tag(self) -> str:
        end = self.text.find("*>", self.at + 2)
        if end < 0:
            raise self.error("unclosed <*")
        tag = self.text[self.at + 2 : end]
        self.at = end + 2
        return tag

    def _for(self, tag: str) -> _Node:
        match = re.fullmatch(r"\s*for\s+(.+?)\s+in\s+(.+?)\s*", tag)
        if match is None:
            raise self.error(f"unsupported loop <* {tag.strip()} *>")
        names = [name.strip() for name in match.group(1).split(",")]
        if not all(_IDENT.fullmatch(name) for name in names):
            raise self.error(f"unsupported loop variables in <* {tag.strip()} *>")
        if _PATH.fullmatch(match.group(2)) is None:
            raise self.error(f"unsupported loop over {match.group(2).strip()!r}")
        path = [part.strip() for part in match.group(2).split(".")]
        body, _ = self.parse(("endfor",))
        return _Node("for", names=names, path=path, body=body)

    def _if(self, tag: str) -> _Node:
        match = re.fullmatch(r"\s*if\s+(not\s+)?\{\{(.*)\}\}\s*", tag, re.DOTALL)
        if match is None:
            raise self.error(f"unsupported condition <* {tag.strip()} *>")
        condition = self._expression(match.group(2))
        # matugen drops the whitespace after `<* if ... *>` and after `<* else *>`.
        self._skip_space()
        body, ended = self.parse(("else", "endif"))
        other: list[_Node] = []
        if ended is not None and ended.split()[0] == "else":
            self._skip_space()
            other, _ = self.parse(("endif",))
        return _Node(
            "if",
            path=condition.path,
            filters=condition.filters,
            body=body,
            other=other,
            negated=bool(match.group(1)),
        )

    def _skip_space(self) -> None:
        while self.at < len(self.text) and self.text[self.at].isspace():
            self.at += 1


def _split(text: str, separator: str) -> list[str]:
    """`text` split on `separator` outside double quotes."""
    parts, current, quoted, escape = [], [], False, False
    for char in text:
        if escape:
            current.append(char)
            escape = False
        elif char == "\\" and quoted:
            current.append(char)
            escape = True
        elif char == '"':
            current.append(char)
            quoted = not quoted
        elif char == separator and not quoted:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def _literal(text: str, parser: _Parser) -> object:
    text = text.strip()
    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        return re.sub(r'\\(["\\])', r"\1", text[1:-1])
    if _NUMBER.fullmatch(text):
        return float(text) if "." in text else int(text)
    if text in ("true", "false"):
        return text == "true"
    if _IDENT.fullmatch(text):
        return text
    raise parser.error(f"unsupported filter argument {text!r}")


def render_matugen(template: str, view: Mapping[str, object]) -> str:
    """`template` (matugen's syntax) filled from `view`. Raises MatugenError."""
    nodes, _ = _Parser(template).parse()
    out: list[str] = []
    _render(nodes, [dict(view)], out)
    return "".join(out)


def _lookup(path: list[str], scopes: list[dict[str, object]]) -> object:
    for scope in reversed(scopes):
        if path[0] in scope:
            value = scope[path[0]]
            break
    else:
        raise MatugenError(f"unknown variable {'.'.join(path)!r}")
    for index, part in enumerate(path[1:], 1):
        if isinstance(value, Mapping) and part in value:
            value = value[part]
        elif isinstance(value, (Rgb, Hsl)) and index == len(path) - 1:
            return value, part
        else:
            raise MatugenError(f"unknown variable {'.'.join(path)!r}")
    return value, None


def _evaluate(node: _Node, scopes: list[dict[str, object]]) -> Value:
    value, field_name = _lookup(node.path, scopes)
    if isinstance(value, Mapping):
        raise MatugenError(f"{'.'.join(node.path)} is not a value")
    for name, args in node.filters:
        value = _filter(name, args, value, field_name)
    if isinstance(value, (Rgb, Hsl)):
        if field_name is None:
            raise MatugenError(f"{'.'.join(node.path)}: a colour needs a field (hex, rgb, ...)")
        return format_colour(value, field_name)
    return value


def _text(value: Value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return _display(value)
    return str(value)


def _render(nodes: list[_Node], scopes: list[dict[str, object]], out: list[str]) -> None:
    for node in nodes:
        if node.kind == "raw":
            out.append(node.text)
        elif node.kind == "value":
            out.append(_text(_evaluate(node, scopes)))
        elif node.kind == "if":
            condition = _evaluate(node, scopes)
            if not isinstance(condition, bool):
                raise MatugenError(f"condition {'.'.join(node.path)} is not true or false")
            _render(node.body if condition != node.negated else node.other, scopes, out)
        else:
            _loop(node, scopes, out)


def _loop(node: _Node, scopes: list[dict[str, object]], out: list[str]) -> None:
    items, _ = _lookup(node.path, scopes)
    if not isinstance(items, Mapping) or node.path[0] not in ("colors", "base16"):
        raise MatugenError(f"loop over {'.'.join(node.path)} is not supported")
    if len(node.names) != 2:
        raise MatugenError(f"loop over {'.'.join(node.path)}: give two names (key, value)")
    keys = sorted(items)
    for index, key in enumerate(keys):
        loop = {"index": index, "first": index == 0, "last": index == len(keys) - 1}
        scope = {node.names[0]: key, node.names[1]: items[key], "loop": loop}
        _render(node.body, [*scopes, scope], out)


# --- the Material view --------------------------------------------------------------------------

# Material's mode-independent "fixed" tones, as OKLCH lightness (*initial*): fixed 90, fixed_dim
# 80, on_fixed 10, on_fixed_variant 30.
FIXED_LIGHTNESS = {"fixed": 0.92, "fixed_dim": 0.84, "on_fixed": 0.22, "on_fixed_variant": 0.40}
# A container's chroma, as a share of its colour's (*initial*).
CONTAINER_CHROMA = 0.6
# surface_container_highest: base02 moved this much further from base00 in OKLCH lightness.
HIGHEST_STEP = 0.03
# Every role matugen 4.2 exports (`colors.*`), in its order.
ROLES = (
    "background",
    "error",
    "error_container",
    "inverse_on_surface",
    "inverse_primary",
    "inverse_surface",
    "on_background",
    "on_error",
    "on_error_container",
    "on_primary",
    "on_primary_container",
    "on_primary_fixed",
    "on_primary_fixed_variant",
    "on_secondary",
    "on_secondary_container",
    "on_secondary_fixed",
    "on_secondary_fixed_variant",
    "on_surface",
    "on_surface_variant",
    "on_tertiary",
    "on_tertiary_container",
    "on_tertiary_fixed",
    "on_tertiary_fixed_variant",
    "outline",
    "outline_variant",
    "primary",
    "primary_container",
    "primary_fixed",
    "primary_fixed_dim",
    "scrim",
    "secondary",
    "secondary_container",
    "secondary_fixed",
    "secondary_fixed_dim",
    "shadow",
    "source_color",
    "surface",
    "surface_bright",
    "surface_container",
    "surface_container_high",
    "surface_container_highest",
    "surface_container_low",
    "surface_container_lowest",
    "surface_dim",
    "surface_tint",
    "surface_variant",
    "tertiary",
    "tertiary_container",
    "tertiary_fixed",
    "tertiary_fixed_dim",
)


# Custom colours (matugen's `custom_colors`, which a user names in its config) that
# matugen-themes' neovim/matugen.lua expects, from the palette's named hues and bright colours.
CUSTOM_COLOURS = {
    "red": "base08",
    "orange": "base09",
    "yellow": "base0A",
    "green": "base0B",
    "teal": "base0C",
    "blue": "base0D",
    "purple": "base0E",
    "maroon": "base12",
    "mint": "base14",
    "sky": "base15",
    "lavender": "base16",
    "pink": "base17",
}


def _at_lightness(colour: str, lightness: float, chroma_share: float = 1.0) -> str:
    _, chroma, hue = hex_to_oklch(colour)
    return oklch_to_hex(lightness, chroma * chroma_share, hue)


def _label(colour: str, base24: Mapping[str, str]) -> str:
    return max((base24["base00"], base24["base07"]), key=lambda text: contrast_ratio(text, colour))


def material_roles(variant: str, colours: Variant, other: Variant | None) -> dict[str, str]:
    """Every Material role of one variant, from its base24 colours and roles. `other` is the
    palette's other variant, if it has one (for `inverse_primary`)."""
    base, roles = colours.base24, colours.roles
    accent = roles["accent"]
    tertiary = base[
        max(
            ACCENT_KEYS,
            key=lambda key: hue_distance(hex_to_oklch(base[key])[2], hex_to_oklch(accent)[2]),
        )
    ]
    container_l = hex_to_oklch(base["base02"])[0]
    on_container_l = hex_to_oklch(base["base06"])[0]
    base00_l = hex_to_oklch(base["base00"])[0]
    base02_l, chroma02, hue02 = hex_to_oklch(base["base02"])
    step = HIGHEST_STEP if base02_l >= base00_l else -HIGHEST_STEP
    highest = oklch_to_hex(base02_l + step, chroma02, hue02)
    result = {
        "background": base["base00"],
        "on_background": base["base05"],
        "surface": base["base00"],
        "surface_container_lowest": base["base11"],
        "surface_container_low": base["base10"],
        "surface_container": base["base01"],
        "surface_container_high": base["base02"],
        "surface_container_highest": highest,
        "surface_dim": base["base00"] if variant == "dark" else highest,
        "surface_bright": highest if variant == "dark" else base["base00"],
        "surface_variant": base["base02"],
        "on_surface": base["base05"],
        "on_surface_variant": base["base04"],
        "outline": base["base03"],
        "outline_variant": base["base02"],
        "inverse_surface": base["base05"],
        "inverse_on_surface": base["base01"],
        "inverse_primary": other.roles["accent"] if other is not None else accent,
        "shadow": "#000000",
        "scrim": "#000000",
        "source_color": accent,
        "surface_tint": accent,
    }
    for name, colour, label in (
        ("primary", accent, roles["on_accent"]),
        ("secondary", roles["secondary"], roles["on_secondary"]),
        ("tertiary", tertiary, _label(tertiary, base)),
        ("error", roles["error"], _label(roles["error"], base)),
    ):
        result[name] = colour
        result[f"on_{name}"] = label
        result[f"{name}_container"] = _at_lightness(colour, container_l, CONTAINER_CHROMA)
        result[f"on_{name}_container"] = _at_lightness(colour, on_container_l)
        if name != "error":
            result[f"{name}_fixed"] = _at_lightness(colour, FIXED_LIGHTNESS["fixed"])
            result[f"{name}_fixed_dim"] = _at_lightness(colour, FIXED_LIGHTNESS["fixed_dim"])
            result[f"on_{name}_fixed"] = _at_lightness(colour, FIXED_LIGHTNESS["on_fixed"])
            result[f"on_{name}_fixed_variant"] = _at_lightness(
                colour, FIXED_LIGHTNESS["on_fixed_variant"]
            )
    return {role: result[role] for role in ROLES}


def material_view(
    palette: Palette, variant: str, wallpaper: Path | None = None
) -> dict[str, object]:
    """The matugen view of `palette`: `.default` is `variant`, `.dark` and `.light` the
    palette's variants (with one variant, all three give it)."""
    names = {mode: mode if mode in palette.variants else variant for mode in ("dark", "light")}
    names["default"] = variant
    computed = {
        name: material_roles(
            name,
            palette.variants[name],
            next((v for key, v in palette.variants.items() if key != name), None),
        )
        for name in set(names.values())
    }
    colors = {
        role: {mode: parse_hex(computed[name][role]) for mode, name in names.items()}
        for role in ROLES
    }
    for colour, key in CUSTOM_COLOURS.items():
        colors[colour] = {
            mode: parse_hex(palette.variants[name].base24[key]) for mode, name in names.items()
        }
    base16 = {
        key.lower(): {
            mode: parse_hex(palette.variants[name].base24[key]) for mode, name in names.items()
        }
        for key in BASE16_KEYS
    }
    return {
        "colors": colors,
        "base16": base16,
        "image": "" if wallpaper is None else str(wallpaper),
        "mode": variant,
        "is_dark_mode": variant == "dark",
    }
