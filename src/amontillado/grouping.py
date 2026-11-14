"""Palette-aware grouping: how far apart two pictures' colours are.

docs/design.md, "Grouping (v0.7)". Each file's metrics carry a palette (`metrics.palette`); two
palettes are compared by the distance from each colour to the nearest colour of the other, in
OKLab, weighted by its share, averaged over both directions: 0 for identical palettes. A cheap
stand-in for earth mover's distance, which would need a linear-programming solver.

`companions` picks the pictures that go with a primary one, one per monitor, for `amo group`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from amontillado.colour import srgb_to_oklab
from amontillado.index import IndexedFile
from amontillado.metrics import Palette


def palette_distance(first: Palette, second: Palette) -> float:
    """The distance between two palettes (non-empty), 0 for identical ones."""
    (colours_a, shares_a), (colours_b, shares_b) = _oklab(first), _oklab(second)
    d = np.sqrt(((colours_a[:, None, :] - colours_b[None]) ** 2).sum(2))
    return float((d.min(1) * shares_a).sum() + (d.min(0) * shares_b).sum()) / 2


# A library ranked against one picture converts each palette once; palettes are tuples.
@lru_cache(maxsize=65536)
def _oklab(palette: Palette) -> tuple[np.ndarray, np.ndarray]:
    if not palette:
        raise ValueError("an empty palette")
    rgb = np.array(
        [[int(colour[i : i + 2], 16) for i in (1, 3, 5)] for colour, _ in palette], dtype=np.uint8
    )
    return srgb_to_oklab(rgb), np.array([share for _, share in palette])


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
    through its file for the monitor's ratio (`file_for`), which must have a palette and be
    accepted (`accept`: filters, purity, on disk). Compatible ones (within `max_distance` of
    the primary) are taken in `records` order, or nearest first with `nearest`; with none left,
    the nearest beyond the bound. Raises GroupError when a monitor has no candidate left."""
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
            distance = palette_distance(primary.metrics.palette, file.metrics.palette)
            candidates.append((distance, position, file))
        if not candidates:
            raise GroupError(
                f"not enough matching pictures: none left for monitor {monitor.name} "
                f"({len(monitors) + 1} monitors)"
            )
        compatible = [c for c in candidates if c[0] <= max_distance]
        if compatible:
            pool = sorted(compatible) if nearest else compatible
            distance, _, file = pool[0]
            chosen.append(Choice(monitor, file, distance))
        else:
            distance, _, file = min(candidates)
            chosen.append(Choice(monitor, file, distance, beyond=True))
        used.add(file.record_id)
    return chosen
