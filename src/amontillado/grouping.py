"""Palette-aware grouping: how far apart two pictures' colours are.

docs/design.md, "Grouping (v0.7)". Each file's metrics carry a palette (`metrics.palette`); two
palettes are compared by the distance from each colour to the nearest colour of the other, in
OKLab, weighted by its share, averaged over both directions: 0 for identical palettes. A cheap
stand-in for earth mover's distance, which would need a linear-programming solver.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from amontillado.colour import srgb_to_oklab
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
