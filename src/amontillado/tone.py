"""Tone: a gentler version of a palette's variant, made from its full variant at apply time.

docs/design.md, "Tone (designed in v0.10)", decisions 1 and 4. `soft` is the light variant on
cream paper with dark-grey text; `dim` is the dark variant on charcoal. The ramp `base00`-`base07`
is re-derived at the tone's Material tones (CIELAB L*), each accent keeps its hue and chroma and
takes the lightness whose contrast on the new `base01` sits part of the way from its full
contrast down to the floor, and the rest (brights, backgrounds, roles) is derived as for any
palette. The contrast check then runs on the result as on any variant.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from amontillado.colour import contrast_ratio, hex_to_oklch, oklch_to_hex
from amontillado.contrast import nearest_passing
from amontillado.generators import tone_lightness
from amontillado.palette import BASE16_KEYS, Variant, complete_variant

FULL = "full"
# The tones each variant takes; `full` is the variant as the palette holds it.
TONES = {"light": (FULL, "soft"), "dark": (FULL, "dim")}
# Lowest contrast an accent is moved to on base01: the check's 4.5 plus a margin.
ACCENT_FLOOR = 4.7
# Under dim, blue is a background under base05 (decision 4) instead of text.
BLUE_BACKGROUND = 3.0


@dataclass(frozen=True)
class Tone:
    """How a tone is made from the full variant (*initial* values, docs/design.md)."""

    # Material tones of base00-base07 (base04 retuned in the build, amo-k79.1, so it passes
    # 4.5:1 on base01 without the contrast check moving it).
    ramp: tuple[float, ...]
    # A fixed hue and per-step chroma for the ramp, or None for the palette's own neutral.
    tint: tuple[float, tuple[float, ...]] | None
    # Accent chroma multiplier, so accents on darker paper stay apart.
    chroma: float
    # How far each accent's contrast on base01 falls from its full value toward ACCENT_FLOOR.
    soften: float
    # Fit base0D as a background under base05 at BLUE_BACKGROUND (decision 4).
    blue_background: bool = False


SPECS = {
    "soft": Tone(
        ramp=(92, 89, 84, 55, 41, 24, 18, 12),
        tint=(80.0, (0.024, 0.024, 0.022, 0.012, 0.012, 0.010, 0.008, 0.006)),
        chroma=1.4,
        soften=0.4,
    ),
    "dim": Tone(
        ramp=(18, 22, 30, 52, 65, 83, 88, 92),
        tint=None,
        chroma=1.0,
        soften=0.8,
        blue_background=True,
    ),
}


class ToneError(ValueError):
    """A tone the variant does not take."""


def check_tone(variant: str, tone: str) -> None:
    """Raise ToneError unless `variant` (dark or light) takes `tone`."""
    if tone not in TONES[variant]:
        raise ToneError(f"{variant} takes tone {' or '.join(TONES[variant])}, not {tone}")


def toned(variant: str, full: Variant, tone: str) -> Variant:
    """`full`, the palette's `variant` (dark or light), in `tone`; `full` returns it unchanged.

    Raises ToneError for a tone the variant does not take. The result is not contrast-checked.
    """
    check_tone(variant, tone)
    if tone == FULL:
        return full
    spec = SPECS[tone]
    dark = variant == "dark"
    colours = _ramp(full.base24, spec)
    old_base01, new_base01 = full.base24["base01"], colours["base01"]

    def soften(colour: str) -> str:
        was = contrast_ratio(colour, old_base01)
        target = max(ACCENT_FLOOR, was - (was - ACCENT_FLOOR) * spec.soften)
        _, chroma, hue = hex_to_oklch(colour)
        return fit(chroma * spec.chroma, hue, new_base01, target, lighter=dark)

    for key in BASE16_KEYS[8:]:
        colours[key] = soften(full.base24[key])
    if spec.blue_background:
        # Bright blue stays text (4.5:1, decision 4): derived from blue before the refit.
        colours["base16"] = complete_variant(variant, colours).base24["base16"]
        _, chroma, hue = hex_to_oklch(colours["base0D"])
        colours["base0D"] = fit(chroma, hue, colours["base05"], BLUE_BACKGROUND, lighter=not dark)
    roles = {role: soften(full.roles[role]) for role in ("accent", "secondary")}
    return complete_variant(variant, colours, roles)


def _ramp(base24: Mapping[str, str], spec: Tone) -> dict[str, str]:
    """base00-base07 at the tone's Material tones, tinted as the spec says."""
    if spec.tint is None:
        _, chroma, hue = hex_to_oklch(base24["base02"])
        tint = (hue, (chroma,) * len(spec.ramp))
    else:
        tint = spec.tint
    hue, chromas = tint
    return {
        key: oklch_to_hex(tone_lightness(material), chroma, hue)
        for key, material, chroma in zip(BASE16_KEYS[:8], spec.ramp, chromas, strict=True)
    }


def fit(chroma: float, hue: float, other: str, target: float, *, lighter: bool) -> str:
    """The colour at `hue` and `chroma` (lowered to stay in gamut) nearest in lightness to
    `other` whose contrast with `other` is at least `target`, lighter or darker than it; the
    extreme (white or black side) when none reaches `target`."""
    start = hex_to_oklch(other)[0]
    end = 1.0 if lighter else 0.0
    if contrast_ratio(oklch_to_hex(end, chroma, hue), other) < target:
        return oklch_to_hex(end, chroma, hue)
    return nearest_passing(start, end, chroma, hue, other, target)
