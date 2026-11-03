"""Accent metrics on a palette: hue fidelity and distinctness of ANSI colours 1-6.

docs/design.md, "Theme engine (v0.2)", "Accent metrics". The contrast check sees neither an
accent off the hue its ANSI name promises nor two accents too close to tell apart; these two
numbers do. Report only: they do not fail `amo palette --check`. Definitions match chezmoi's
`tools/palette-compare` (its `score`), so either can import or mirror the other.

Public: `ANSI_ACCENTS`, `HUE_TOLERANCE`, `MIN_CHROMA`, `DISTINCT_MINIMUM`, `AccentScore`,
`accent_colours`, `nominal_hues`, `on_hue`, `hue_fidelity`, `distinctness`, `score`.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from amontillado.colour import hex_to_oklch, hue_distance, srgb_to_oklab

# ANSI colours 1-6 and the base24 keys behind them (base16-shell's mapping), with the sRGB
# primary whose OKLCH hue each name promises.
ANSI_ACCENTS: tuple[tuple[str, str, str], ...] = (
    ("red", "base08", "#ff0000"),
    ("green", "base0B", "#00ff00"),
    ("yellow", "base0A", "#ffff00"),
    ("blue", "base0D", "#0000ff"),
    ("magenta", "base0E", "#ff00ff"),
    ("cyan", "base0C", "#00ffff"),
)
# *initial* thresholds: an accent is on its hue within this many degrees (OKLCH), with at least
# this chroma; two accents under this OKLab distance (x100) are hard to tell apart.
HUE_TOLERANCE = 45.0
MIN_CHROMA = 0.03
DISTINCT_MINIMUM = 8.0


@dataclass(frozen=True)
class AccentScore:
    """`hues`: how many of colours 1-6 are on their hue; `distinct`: the smallest OKLab distance
    (x100) between two of them, to one decimal."""

    hues: int
    distinct: float

    def __str__(self) -> str:
        return f"hues {self.hues}/{len(ANSI_ACCENTS)}, distinct {self.distinct:.1f}"


def accent_colours(base24: Mapping[str, str]) -> list[str]:
    """ANSI colours 1-6 (red, green, yellow, blue, magenta, cyan) from a base16/base24 mapping."""
    return [base24[key] for _, key, _ in ANSI_ACCENTS]


def nominal_hues() -> list[float]:
    """The OKLCH hue, in degrees, each of colours 1-6 promises."""
    return [hex_to_oklch(primary)[2] for _, _, primary in ANSI_ACCENTS]


def on_hue(colour: str, nominal: float) -> bool:
    """Whether `colour` has some chroma and its hue is within `HUE_TOLERANCE` of `nominal`."""
    _, chroma, hue = hex_to_oklch(colour)
    return chroma >= MIN_CHROMA and hue_distance(hue, nominal) <= HUE_TOLERANCE


def hue_fidelity(accents: Sequence[str]) -> int:
    """How many of `accents` (colours 1-6, in ANSI order) are on the hue their name promises."""
    return sum(
        on_hue(colour, nominal) for colour, nominal in zip(accents, nominal_hues(), strict=True)
    )


def _oklab(colour: str) -> np.ndarray:
    rgb = np.array([int(colour[i : i + 2], 16) for i in (1, 3, 5)], dtype=np.uint8)
    return srgb_to_oklab(rgb)


def distinctness(accents: Sequence[str]) -> float:
    """The smallest OKLab distance (x100) between two of `accents`, to one decimal."""
    points = [_oklab(colour) for colour in accents]
    nearest = min(math.dist(a, b) for a, b in itertools.combinations(points, 2))
    return round(100 * nearest, 1)


def score(base24: Mapping[str, str]) -> AccentScore:
    """Both metrics for the colours 1-6 of a base16/base24 mapping."""
    accents = accent_colours(base24)
    return AccentScore(hue_fidelity(accents), distinctness(accents))
