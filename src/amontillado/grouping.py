"""Palette-aware grouping: how far apart two pictures' colours are.

docs/design.md, "Grouping (v0.7)" and its decision 6 (calibrated with MH, amo-6f0.4). Each
file's metrics carry a palette (`metrics.palette`); two pictures are compared by the distance
from each palette colour to the nearest colour of the other palette, weighted by its share and
averaged over both directions, with three corrections for what makes pictures go together on a
desk rather than what OKLab calls a colour difference:

- the colour axes (a, b) count COLOUR_WEIGHT times as much as lightness, which otherwise makes
  up most of the distance (a median 61% on the calibration sample);
- near-black and near-white colours count EXTREME_WEIGHT of their share (the weights then
  renormalised), so two mostly dark pictures are compared mostly on their accents;
- the difference in contrast (the spread of the palette's lightness) is added, CONTRAST_WEIGHT
  times;

and a gate: a clearly warm picture and a clearly cool one (`warmth` beyond GATE_WARMTH either
way) never go together (infinite distance). 0 is identical colours. A cheap stand-in for earth
mover's distance, which would need a linear-programming solver.

`companions` picks the pictures that go with a primary one, one per monitor, for `amo group`.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from amontillado.colour import srgb_to_oklab
from amontillado.index import IndexedFile
from amontillado.metrics import Metrics, Palette

# Calibrated with MH, 2026-11-17 (design decision 6, variant "C.25+G").
COLOUR_WEIGHT = 2.5
EXTREME_LIGHTNESS = (0.2, 0.95)
EXTREME_WEIGHT = 0.25
CONTRAST_WEIGHT = 0.25
GATE_WARMTH = 0.5
_SCALE = np.array([1.0, COLOUR_WEIGHT, COLOUR_WEIGHT])


def distance(first: Metrics, second: Metrics) -> float:
    """How far apart two pictures' colours are (their palettes must not be empty): 0 for
    identical palettes, infinite when the warmth gate separates them."""
    if (
        first.warmth * second.warmth < 0
        and min(abs(first.warmth), abs(second.warmth)) > GATE_WARMTH
    ):
        return math.inf
    lab_a, weight_a, contrast_a = _prepared(first.palette)
    lab_b, weight_b, contrast_b = _prepared(second.palette)
    d = np.sqrt(((lab_a[:, None, :] - lab_b[None]) ** 2).sum(2))
    nearest = float((d.min(1) * weight_a).sum() + (d.min(0) * weight_b).sum()) / 2
    return nearest + CONTRAST_WEIGHT * abs(contrast_a - contrast_b)


# A library ranked against one picture prepares each palette once; palettes are tuples.
@lru_cache(maxsize=65536)
def _prepared(palette: Palette) -> tuple[np.ndarray, np.ndarray, float]:
    """The palette in OKLab with its colour axes scaled, its colours' weights, and its
    contrast (the share-weighted standard deviation of lightness)."""
    if not palette:
        raise ValueError("an empty palette")
    rgb = np.array(
        [[int(colour[i : i + 2], 16) for i in (1, 3, 5)] for colour, _ in palette], dtype=np.uint8
    )
    lab = srgb_to_oklab(rgb)
    shares = np.array([share for _, share in palette])
    lightness = lab[:, 0]
    extreme = (lightness < EXTREME_LIGHTNESS[0]) | (lightness > EXTREME_LIGHTNESS[1])
    weights = shares * np.where(extreme, EXTREME_WEIGHT, 1.0)
    weights = weights / weights.sum()
    mean = float((lightness * shares).sum() / shares.sum())
    contrast = math.sqrt(float(((lightness - mean) ** 2 * shares).sum() / shares.sum()))
    return lab * _SCALE, weights, contrast


@dataclass(frozen=True)
class Monitor:
    """A monitor as `amo group --monitor NAME=W:H` gives it."""

    name: str
    # Width over height, and the ratio as given (`21:9`).
    ratio: float
    aspect: str


@dataclass(frozen=True)
class Choice:
    """The picture chosen for one monitor: its file, and its palette distance to the
    primary's (0 for the primary itself)."""

    monitor: Monitor
    file: IndexedFile
    distance: float
    # Chosen from beyond the compatibility bound, for want of compatible pictures.
    beyond: bool = False


class GroupError(Exception):
    """No group can be made; the message says why."""


def companions(
    primary: IndexedFile,
    monitors: Sequence[Monitor],
    records: Sequence[str],
    file_for: Callable[[str, float], IndexedFile],
    accept: Callable[[IndexedFile], bool],
    *,
    max_distance: float,
    nearest: bool,
) -> list[Choice]:
    """A picture for each of `monitors` (the primary's monitor not among them) from `records`
    (record ids, in least-shown order), other than the primary's and each other: each record
    through its file for the monitor's ratio (`file_for`), which must have a palette, be
    accepted (`accept`: filters, purity, on disk) and not be gated off by warmth. Compatible
    ones (within `max_distance` of the primary) are taken in `records` order, or nearest first
    with `nearest`; with none left, the nearest beyond the bound. Raises GroupError when a
    monitor has no candidate left."""
    used = {primary.record_id}
    chosen: list[Choice] = []
    for monitor in monitors:
        candidates = []
        for position, record_id in enumerate(records):
            if record_id in used:
                continue
            file = file_for(record_id, monitor.ratio)
            if not file.metrics.palette or not accept(file):
                continue
            apart = distance(primary.metrics, file.metrics)
            # The warmth gate: never a companion, not even beyond the bound.
            if math.isfinite(apart):
                candidates.append((apart, position, file))
        if not candidates:
            raise GroupError(
                f"not enough matching pictures: none left for monitor {monitor.name} "
                f"({len(monitors) + 1} monitors)"
            )
        compatible = [c for c in candidates if c[0] <= max_distance]
        if compatible:
            pool = sorted(compatible) if nearest else compatible
            apart, _, file = pool[0]
            chosen.append(Choice(monitor, file, apart))
        else:
            apart, _, file = min(candidates)
            chosen.append(Choice(monitor, file, apart, beyond=True))
        used.add(file.record_id)
    return chosen
