"""Palettes: per variant (dark, light), the base24 colours plus roles, as YAML.

docs/design.md, "Theme engine (v0.2)", "Palette". A palette's variants each hold all 24 base24
keys (`base00`-`base17`) and every role; whatever a source leaves out is derived here: the
base24 keys from base16 in OKLCH, the roles from the base colours (base16 has no accent). A
tinted-theming scheme (base16 or base24 YAML, the current format or the legacy one) converts
into a palette; two schemes of one family, a dark and a light, make one palette with both.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from logging import getLogger
from pathlib import Path

from amontillado import yamlio
from amontillado.colour import (
    HEX_PATTERN,
    contrast_ratio,
    hex_to_oklch,
    hue_distance,
    oklch_to_hex,
)

logger = getLogger(__name__)

VERSION = 1
VARIANTS = ("dark", "light")
BASE16_KEYS = tuple(f"base{i:02X}" for i in range(16))
BASE24_KEYS = BASE16_KEYS + tuple(f"base{i:02X}" for i in range(16, 24))
ROLES = (
    "accent",
    "on_accent",
    "secondary",
    "on_secondary",
    "border",
    "border_inactive",
    "selection",
    "on_selection",
    "error",
    "warning",
    "success",
    "info",
)
# The named accents, red to magenta (base0F, brown, is not one an accent is taken from).
ACCENT_KEYS = ("base08", "base09", "base0A", "base0B", "base0C", "base0D", "base0E")
# base24's darker backgrounds: steps from base00 in OKLCH lightness (*initial*), darker for a
# dark variant and lighter for a light one.
BACKGROUND_STEPS = {"base10": 0.03, "base11": 0.06}
# base24's bright colours, each its base16 colour lighter by BRIGHT_STEP (*initial*).
BRIGHT_KEYS = {
    "base12": "base08",
    "base13": "base0A",
    "base14": "base0B",
    "base15": "base0C",
    "base16": "base0D",
    "base17": "base0E",
}
BRIGHT_STEP = 0.08
# Roles taken straight from a base colour when not given.
_ROLE_KEYS = {
    "border_inactive": "base03",
    "selection": "base02",
    "on_selection": "base05",
    "error": "base08",
    "warning": "base0A",
    "success": "base0B",
    "info": "base0C",
}


class PaletteError(Exception):
    """A palette or scheme cannot be used; the message says why."""


@dataclass(frozen=True)
class Variant:
    """One variant of a palette: every base24 key and every role, as `#rrggbb`."""

    base24: dict[str, str]
    roles: dict[str, str]
    # Colours the contrast check changed.
    adjusted: tuple[str, ...] = ()


@dataclass(frozen=True)
class Palette:
    name: str
    variants: dict[str, Variant]
    # Informational: where the palette came from.
    source: dict[str, object] = field(default_factory=dict)


def complete_variant(
    variant: str,
    colours: Mapping[str, str],
    roles: Mapping[str, str] | None = None,
    *,
    hue: float | None = None,
) -> Variant:
    """A Variant from base16 (or base24) `colours` and any `roles` given, deriving the rest.

    `hue` is the picture's hue metric: the accent is then the named accent nearest to it,
    instead of `base0D`.
    """
    base24 = {key: colours[key] for key in BASE16_KEYS}
    lightness, chroma, hue_00 = hex_to_oklch(base24["base00"])
    sign = -1 if variant == "dark" else 1
    for key, step in BACKGROUND_STEPS.items():
        base24[key] = colours.get(key) or oklch_to_hex(lightness + sign * step, chroma, hue_00)
    for key, source in BRIGHT_KEYS.items():
        if key not in colours:
            bright_l, bright_c, bright_h = hex_to_oklch(base24[source])
            base24[key] = oklch_to_hex(bright_l + BRIGHT_STEP, bright_c, bright_h)
        else:
            base24[key] = colours[key]
    base24 = {key: base24[key] for key in BASE24_KEYS}
    return Variant(base24, _derive_roles(base24, dict(roles or {}), hue))


def _derive_roles(
    base24: dict[str, str], given: dict[str, str], hue: float | None
) -> dict[str, str]:
    roles = dict(given)
    if "accent" not in roles:
        roles["accent"] = (
            base24["base0D"] if hue is None else base24[_nearest_accent(base24, hue, ())]
        )
    if "secondary" not in roles:
        accent = roles["accent"]
        others = tuple(key for key in ACCENT_KEYS if base24[key] == accent)
        roles["secondary"] = base24[_nearest_accent(base24, hex_to_oklch(accent)[2], others)]
    for role in ("accent", "secondary"):
        roles.setdefault(f"on_{role}", _label(roles[role], base24))
    roles.setdefault("border", roles["accent"])
    for role, key in _ROLE_KEYS.items():
        roles.setdefault(role, base24[key])
    return {role: roles[role] for role in ROLES}


def _nearest_accent(base24: dict[str, str], hue: float, exclude: Sequence[str]) -> str:
    """The named accent key nearest in hue to `hue`, leaving out `exclude`."""
    return min(
        (key for key in ACCENT_KEYS if key not in exclude),
        key=lambda key: hue_distance(hex_to_oklch(base24[key])[2], hue),
    )


def _label(colour: str, base24: dict[str, str]) -> str:
    """Whichever of base00 and base07 contrasts more with `colour`."""
    return max((base24["base00"], base24["base07"]), key=lambda text: contrast_ratio(text, colour))


def load_palette(path: Path) -> Palette:
    """Read and complete a palette file. Raises PaletteError."""
    return palette_from_data(_read_yaml(path), str(path))


def palette_from_data(data: object, where: str) -> Palette:
    """A Palette from a parsed palette file; `where` names it in errors. Raises PaletteError."""
    data = _mapping(data, where)
    if data.get("version") != VERSION:
        raise PaletteError(f"{where}: version must be {VERSION}, not {data.get('version')!r}")
    name = data.get("name")
    if not isinstance(name, str) or not name:
        raise PaletteError(f"{where}: name must be a non-empty string")
    source = _mapping(data.get("source", {}), f"{where}: source")
    for key in data.keys() - {"version", "name", "source", "variants"}:
        logger.warning("%s: unknown key %r ignored", where, key)
    variants = _mapping(data.get("variants"), f"{where}: variants")
    if not variants:
        raise PaletteError(f"{where}: variants must hold dark, light or both")
    unknown = variants.keys() - set(VARIANTS)
    if unknown:
        raise PaletteError(f"{where}: unknown variant {sorted(map(str, unknown))[0]!r}")
    return Palette(
        name,
        {
            key: _variant(variants[key], f"{where}: {key}", key)
            for key in VARIANTS
            if key in variants
        },
        dict(source),
    )


def _variant(data: object, where: str, variant: str) -> Variant:
    data = _mapping(data, where)
    unknown = data.keys() - {"base24", "roles", "adjusted"}
    if unknown:
        raise PaletteError(f"{where}: unknown key {sorted(map(str, unknown))[0]!r}")
    base24 = _colours(data.get("base24"), f"{where}: base24", BASE24_KEYS, strict=True)
    missing = [key for key in BASE16_KEYS if key not in base24]
    if missing:
        raise PaletteError(f"{where}: base24 lacks {', '.join(missing)}")
    roles = _colours(data.get("roles", {}), f"{where}: roles", ROLES, strict=True)
    adjusted = data.get("adjusted", [])
    if not isinstance(adjusted, list) or not all(isinstance(key, str) for key in adjusted):
        raise PaletteError(f"{where}: adjusted must be a list of colour names")
    completed = complete_variant(variant, base24, roles)
    return Variant(completed.base24, completed.roles, tuple(adjusted))


def palette_to_data(palette: Palette) -> dict[str, object]:
    """The palette file's contents, in file order."""
    data: dict[str, object] = {"version": VERSION, "name": palette.name}
    if palette.source:
        data["source"] = palette.source
    variants: dict[str, object] = {}
    for key, variant in palette.variants.items():
        variants[key] = {"base24": dict(variant.base24), "roles": dict(variant.roles)}
        if variant.adjusted:
            variants[key]["adjusted"] = list(variant.adjusted)
    data["variants"] = variants
    return data


def dump_palette(palette: Palette) -> str:
    """The palette as a palette file."""
    return yamlio.dump(palette_to_data(palette))


@dataclass(frozen=True)
class _Scheme:
    name: str
    author: str | None
    variant: str
    colours: dict[str, str]
    file: str


def palette_from_schemes(paths: Sequence[Path]) -> Palette:
    """A palette from one tinted-theming scheme, or from a dark and a light one (placed by
    their `variant` keys). Raises PaletteError."""
    if not 1 <= len(paths) <= 2:
        raise PaletteError("give one scheme, or a dark and a light one")
    schemes = [_scheme(_read_yaml(path), path) for path in paths]
    if len(schemes) == 2 and schemes[0].variant == schemes[1].variant:
        raise PaletteError(
            f"{paths[0]} and {paths[1]} are both {schemes[0].variant}; give a dark and a light"
        )
    by_variant = {scheme.variant: scheme for scheme in schemes}
    ordered = [by_variant[key] for key in VARIANTS if key in by_variant]
    source: dict[str, object] = {
        "schemes": {
            scheme.variant: {
                key: value
                for key, value in (
                    ("name", scheme.name),
                    ("author", scheme.author),
                    ("file", scheme.file),
                )
                if value is not None
            }
            for scheme in ordered
        }
    }
    return Palette(
        _family_name([scheme.name for scheme in ordered]),
        {scheme.variant: complete_variant(scheme.variant, scheme.colours) for scheme in ordered},
        source,
    )


def _scheme(data: object, path: Path) -> _Scheme:
    """A scheme in the current format (`system`, `palette`) or the legacy one (`scheme`, keys
    at the top level, values without `#`)."""
    where = str(path)
    data = _mapping(data, where)
    if "palette" in data:
        system = data.get("system")
        if system not in ("base16", "base24"):
            raise PaletteError(f"{where}: system must be base16 or base24, not {system!r}")
        name = data.get("name")
        colours = _colours(data["palette"], f"{where}: palette", BASE24_KEYS, strict=False)
    else:
        name = data.get("scheme")
        colours = _colours(data, where, BASE24_KEYS, strict=False)
    if not isinstance(name, str) or not name:
        raise PaletteError(f"{where}: not a tinted-theming scheme (no name)")
    missing = [key for key in BASE16_KEYS if key not in colours]
    if missing:
        raise PaletteError(f"{where}: lacks {', '.join(missing)}")
    variant = data.get("variant")
    if variant not in VARIANTS:
        # Legacy schemes have no variant: their background says.
        variant = "dark" if hex_to_oklch(colours["base00"])[0] < 0.5 else "light"
        logger.info("%s: no variant given; %s by its background", where, variant)
    author = data.get("author")
    return _Scheme(name, author if isinstance(author, str) else None, variant, colours, path.name)


def _family_name(names: list[str]) -> str:
    """One scheme's name, or the words two schemes' names begin with ("Gruvbox dark, hard" and
    "Gruvbox light, hard" are "Gruvbox")."""
    if len(names) == 1:
        return names[0]
    common: list[str] = []
    for words in zip(*(name.split() for name in names), strict=False):
        if len(set(words)) > 1:
            break
        common.append(words[0])
    return " ".join(common).rstrip(" ,-") or names[0]


def _read_yaml(path: Path) -> object:
    try:
        return yamlio.load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PaletteError(f"{path}: {exc.strerror or exc}") from exc
    except yamlio.YAMLError as exc:
        raise PaletteError(f"{path}: not valid YAML: {exc}") from exc


def _mapping(data: object, where: str) -> dict:
    if not isinstance(data, dict):
        raise PaletteError(f"{where}: must be a mapping")
    return data


def _colours(data: object, where: str, keys: Sequence[str], *, strict: bool) -> dict[str, str]:
    """The colours under `keys` in `data`, as `#rrggbb`. `strict` (a palette file) wants
    `#rrggbb` and no other keys; otherwise (a scheme) the `#` is optional, any case, and other
    keys are left alone."""
    data = _mapping(data, where)
    colours = {}
    for key, value in data.items():
        if key not in keys:
            if strict:
                raise PaletteError(f"{where}: unknown key {key!r}")
            continue
        text = value.lower() if isinstance(value, str) else None
        if text is not None and not strict and not text.startswith("#"):
            text = "#" + text
        if text is None or not HEX_PATTERN.fullmatch(text):
            raise PaletteError(f'{where}: {key} must be a quoted "#rrggbb" colour, not {value!r}')
        colours[key] = text
    return colours
