"""Contrast checks on a palette: WCAG 2 ratios over fixed pairs, and adjusting what fails.

docs/design.md, "Theme engine (v0.2)", "Contrast checks". Each variant is checked on its own.
Adjusting moves one colour of a failing pair in OKLCH lightness, away from the other, by the
smallest step that passes (hue kept, chroma lowered only to stay in gamut), or across the
other when going away cannot pass (a foreground darker than a dark background goes light).
What may move, in order: the pair's foreground; then `accent` (or `secondary`), only when no
foreground fixes the pair; never the ramp backgrounds `base00`, `base01`, `base10`, `base11`.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from logging import getLogger

from amontillado.colour import contrast_ratio, hex_to_oklch, oklch_to_hex
from amontillado.palette import Palette, Variant

logger = getLogger(__name__)

# Foreground, background, minimum ratio (*initial*).
_TEXT = 7.0
_UI = 4.5
_FAINT = 3.0
PAIRS: tuple[tuple[str, str, float], ...] = (
    ("base05", "base00", _TEXT),
    ("base05", "base01", _TEXT),
    ("base04", "base01", _UI),
    ("base03", "base00", _FAINT),
    *(
        (foreground, background, _UI)
        for foreground in (
            "base08",
            "base09",
            "base0A",
            "base0B",
            "base0C",
            "base0D",
            "base0E",
            "base12",
            "base13",
            "base14",
            "base15",
            "base16",
            "base17",
        )
        for background in ("base00", "base01")
    ),
    ("on_accent", "accent", _UI),
    ("on_secondary", "secondary", _UI),
    ("on_selection", "selection", _UI),
    ("border", "base00", _FAINT),
)
# Never moved: a background sits under every foreground, so moving it changes every pair.
FIXED = frozenset({"base00", "base01", "base10", "base11"})
# The palette's link to the picture: moved only when no foreground fixes a pair.
LAST_RESORT = ("accent", "secondary")


@dataclass(frozen=True)
class Failure:
    """A pair below its minimum."""

    foreground: str
    background: str
    ratio: float
    minimum: float

    def __str__(self) -> str:
        return f"{self.foreground} on {self.background}: {self.ratio:.2f}, needs {self.minimum:g}"


def _colour(variant: Variant, name: str) -> str:
    return variant.roles[name] if name in variant.roles else variant.base24[name]


def check(variant: Variant) -> list[Failure]:
    """The pairs of `variant` below their minimums, in table order."""
    failures = []
    for foreground, background, minimum in PAIRS:
        ratio = contrast_ratio(_colour(variant, foreground), _colour(variant, background))
        if ratio < minimum:
            failures.append(Failure(foreground, background, ratio, minimum))
    return failures


def adjust(variant: Variant, label: str) -> tuple[Variant, list[Failure]]:
    """`variant` with failing pairs fixed where the rules allow, and the pairs still failing.
    Each change is logged (under `label`, the variant's name) and listed in `adjusted`."""
    # Each pass makes one move; the bound only guards against moves that undo each other.
    for _ in range(2 * len(PAIRS)):
        changed = False
        for failure in check(variant):
            moved = _fix(variant, failure)
            if moved is None:
                continue
            name, colour = moved
            logger.info(
                "%s: %s %s -> %s (%s)", label, name, _colour(variant, name), colour, failure
            )
            variant = _set(variant, name, colour)
            changed = True
            # Every later pair is checked again against the changed colour.
            break
        if not changed:
            break
    return variant, check(variant)


def _fix(variant: Variant, failure: Failure) -> tuple[str, str] | None:
    """The colour to move, and where to, to fix `failure`; None if no allowed move does."""
    foreground, background = failure.foreground, failure.background
    # A border that is the accent moves as the accent does (rule 2); one set apart is a
    # foreground like any other.
    is_accent = foreground == "border" and variant.roles["border"] == variant.roles["accent"]
    if foreground not in FIXED and foreground not in LAST_RESORT and not is_accent:
        colour = _move(_colour(variant, foreground), _colour(variant, background), failure.minimum)
        if colour is not None:
            return foreground, colour
    for name in LAST_RESORT:
        if is_accent and name == "accent":
            other = background
        elif background == name:
            other = foreground
        else:
            continue
        colour = _move(_colour(variant, name), _colour(variant, other), failure.minimum)
        if colour is not None:
            return name, colour
    return None


def _move(colour: str, other: str, minimum: float) -> str | None:
    """`colour` moved in OKLCH lightness by the smallest step that gives `minimum` against
    `other`: away from it, or, if even the end of that side does not, across it to the other
    side (from `other`'s lightness on). None if neither end passes."""
    lightness, chroma, hue = hex_to_oklch(colour)
    other_lightness = hex_to_oklch(other)[0]
    away = 1.0 if lightness >= other_lightness else 0.0
    for start, end in ((lightness, away), (other_lightness, 1.0 - away)):
        if contrast_ratio(oklch_to_hex(end, chroma, hue), other) >= minimum:
            return _nearest_passing(start, end, chroma, hue, other, minimum)
    return None


def _nearest_passing(
    failing: float, passing: float, chroma: float, hue: float, other: str, minimum: float
) -> str:
    """Bisect on lightness between `failing` and `passing` (which passes)."""
    for _ in range(30):
        middle = (failing + passing) / 2
        if contrast_ratio(oklch_to_hex(middle, chroma, hue), other) >= minimum:
            passing = middle
        else:
            failing = middle
    return oklch_to_hex(passing, chroma, hue)


def _set(variant: Variant, name: str, colour: str) -> Variant:
    base24, roles = dict(variant.base24), dict(variant.roles)
    moved = [name]
    if name in roles:
        if name == "accent" and roles["border"] == roles["accent"]:
            roles["border"] = colour
            moved.append("border")
        roles[name] = colour
    else:
        base24[name] = colour
    adjusted = (*variant.adjusted, *(key for key in moved if key not in variant.adjusted))
    return dataclasses.replace(variant, base24=base24, roles=roles, adjusted=adjusted)


def apply_contrast(palette: Palette, mode: str) -> Palette:
    """`palette` under `theme.contrast` `mode`: `adjust` fixes what it can, `report` logs the
    failing pairs and changes nothing, `off` does neither. Pairs left failing are warnings."""
    if mode == "off":
        return palette
    variants = {}
    for name, variant in palette.variants.items():
        if mode == "adjust":
            variant, failures = adjust(variant, name)
        else:
            failures = check(variant)
        for failure in failures:
            logger.warning("%s: %s", name, failure)
        variants[name] = variant
    return dataclasses.replace(palette, variants=variants)
