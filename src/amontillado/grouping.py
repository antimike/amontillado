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

`companions` picks the pictures that go with a primary one, one per monitor, for `amo group`,
from a `Pool` per monitor ratio; `fills` tells whether a primary gets compatible companions
for every monitor.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
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


class Pool:
    """The files a monitor's picture can come from (with a palette, and accepted by the
    caller's filters), in the order they are taken in (least shown first), with their palettes
    stacked so that their distances to one picture are one array operation: `amo group` ranks
    the whole pool against each primary it tries."""

    def __init__(
        self, files: Sequence[IndexedFile], categories: Mapping[str, str | None] | None = None
    ) -> None:
        self.files = list(files)
        self.ids = np.array([file.record_id for file in self.files], dtype=object)
        categories = categories or {}
        self.categories = np.array(
            [categories.get(file.record_id) for file in self.files], dtype=object
        )
        prepared = [_prepared(file.metrics.palette) for file in self.files]
        width = max((len(weights) for _, weights, _ in prepared), default=1)
        # Padding: colours too far away to be anyone's nearest, weighing nothing.
        self.lab = np.full((len(prepared), width, 3), _FAR)
        self.weights = np.zeros((len(prepared), width))
        for row, (lab, weights, _) in enumerate(prepared):
            self.lab[row, : len(weights)] = lab
            self.weights[row, : len(weights)] = weights
        self.contrast = np.array([contrast for _, _, contrast in prepared])
        self.warmth = np.array([file.metrics.warmth for file in self.files])

    def distances(self, metrics: Metrics) -> np.ndarray:
        """`distance` from `metrics` to each file of the pool, in pool order."""
        lab, weights, contrast = _prepared(metrics.palette)
        d = np.sqrt(((lab[None, :, None, :] - self.lab[:, None, :, :]) ** 2).sum(3))
        nearest = ((d.min(2) * weights).sum(1) + (d.min(1) * self.weights).sum(1)) / 2
        apart = nearest + CONTRAST_WEIGHT * np.abs(contrast - self.contrast)
        gated = (metrics.warmth * self.warmth < 0) & (
            np.minimum(abs(metrics.warmth), np.abs(self.warmth)) > GATE_WARMTH
        )
        return np.where(gated, np.inf, apart)


_FAR = 1e3


# Asked about each candidate in turn (amo group --predicate): the monitor, the candidate's file
# and its distance to the primary; True accepts it.
Accept = Callable[[Monitor, IndexedFile, float], bool]


def companions(
    primary: IndexedFile,
    monitors: Sequence[Monitor],
    pools: Mapping[float, Pool],
    *,
    max_distance: float,
    nearest: bool,
    category: str | None = None,
    accept: Accept | None = None,
    beyond: bool = True,
) -> list[Choice]:
    """A picture for each of `monitors` (the primary's monitor not among them) from the pool of
    its ratio, other than the primary's record and each other's, not gated off by warmth, and
    of `category` if given. Compatible ones (within `max_distance` of the primary) are taken in
    pool order (least shown first), or nearest first with `nearest` (ties in pool order); with
    none left, the nearest beyond the bound (unless not `beyond`). `accept`, if given, is asked
    about the candidates in that order and the first it accepts is taken: it is called lazily,
    never for a candidate after the one taken. Raises GroupError when a monitor has no candidate
    left (or none accepted)."""
    used = [primary.record_id]
    chosen: list[Choice] = []
    # Monitors of one ratio share a pool: its distances to the primary are computed once.
    measured: dict[float, np.ndarray] = {}
    for monitor in monitors:
        pool = pools[monitor.ratio]
        if monitor.ratio not in measured:
            measured[monitor.ratio] = pool.distances(primary.metrics)
        apart = measured[monitor.ratio]
        allowed = np.isfinite(apart) & ~np.isin(pool.ids, used)
        if category is not None:
            allowed &= pool.categories == category
        candidates = np.flatnonzero(allowed)
        if not candidates.size:
            raise GroupError(
                f"not enough matching pictures: none left for monitor {monitor.name} "
                f"({len(monitors) + 1} monitors)"
            )
        within = apart[candidates] <= max_distance
        compatible, outside = candidates[within], candidates[~within]
        if nearest:
            compatible = compatible[np.argsort(apart[compatible], kind="stable")]
        order = [(int(i), False) for i in compatible]
        # The nearest beyond the bound, after every compatible one: reached only when none of
        # those is left (or accepted).
        if beyond:
            order += [(int(i), True) for i in outside[np.argsort(apart[outside], kind="stable")]]
        pick = next(
            (
                (i, is_beyond)
                for i, is_beyond in order
                if accept is None or accept(monitor, pool.files[i], float(apart[i]))
            ),
            None,
        )
        if pick is None:
            reason = "accepted by the predicates" if accept is not None else "within the bound"
            raise GroupError(f"no picture {reason} for monitor {monitor.name}")
        i, is_beyond = pick
        chosen.append(Choice(monitor, pool.files[i], float(apart[i]), beyond=is_beyond))
        used.append(pool.files[i].record_id)
    return chosen


def fills(
    primary: IndexedFile,
    monitors: Sequence[Monitor],
    pools: Mapping[float, Pool],
    *,
    max_distance: float,
    category: str | None = None,
    accept: Accept | None = None,
    nearest: bool = True,
) -> bool:
    """Whether `primary` gets a compatible companion (accepted by `accept`, asked in the order
    `nearest` gives, as `companions`) for every one of `monitors`, none from beyond the
    bound."""
    try:
        companions(
            primary,
            monitors,
            pools,
            max_distance=max_distance,
            nearest=nearest,
            category=category,
            accept=accept,
            beyond=False,
        )
    except GroupError:
        return False
    return True
