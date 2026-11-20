"""Letterbox detection: dark bars framing a picture.

docs/design.md, "Letterboxes" (amo-5o8). A letterboxed picture's bars dominate its palette, so
it groups with mostly black pictures. Bars are told by where the dark pixels lie, not by how
uniform they are: a bar is a run of uniform dark rows (columns, for a pillarbox) at an edge, on
both sides, and between the bars the dark does not go on through the frame. A logo on a black
background has uniform dark rows at both edges too, but its middle is dark as well; off-the-shelf
trimmers (ImageMagick -trim, ffmpeg cropdetect, Pillow's getbbox) cannot tell the two apart.

Calibrated with MH 2026-11-19 on 542 Wallhaven thumbnails (400 random, 150 from film-still
queries; tools/letterbox_sheet.py): every detection was a true letterbox or pillarbox; the
dark-middle bound misses dark film scenes, which look like logos on black by every measure
tried, rather than crop a logo's background.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# A bar row (or column): its mean OKLab lightness below BAR_LIGHTNESS and its standard
# deviation below BAR_FLATNESS.
BAR_LIGHTNESS = 0.15
BAR_FLATNESS = 0.03
# Each bar at least this share of the height (or width).
MIN_BAR = 0.03
# A pixel as dark as a bar: OKLab lightness below this.
DARK = 0.15
# At most this share of the content's middle third may be as dark as a bar (calibrated: at
# 0.25 one dark film scene more is found, with a logo on black at 0.27).
MAX_DARK_MIDDLE = 0.15


@dataclass(frozen=True)
class Bars:
    """Bars on an image's edges, in pixels of the image measured: a letterbox has `top` and
    `bottom`, a pillarbox `left` and `right` (the others 0)."""

    top: int
    bottom: int
    left: int
    right: int

    def content(self, width: int, height: int) -> tuple[int, int, int, int]:
        """The picture between the bars, as (x, y, width, height)."""
        return (
            self.left,
            self.top,
            width - self.left - self.right,
            height - self.top - self.bottom,
        )


@dataclass(frozen=True)
class Features:
    """What the detector measured along one axis: the bars' lengths (pixels) at each end, and
    the share of the content's middle third as dark as a bar (None without bars on both
    ends)."""

    axis: str  # "rows" (a letterbox) or "columns" (a pillarbox)
    start: int
    end: int
    length: int
    dark_middle: float | None

    @property
    def bars(self) -> bool:
        """Bars on both ends, each at least MIN_BAR, and a lit middle."""
        least = max(1, round(MIN_BAR * self.length))
        return (
            self.start >= least
            and self.end >= least
            and self.dark_middle is not None
            and self.dark_middle <= MAX_DARK_MIDDLE
        )


def features(lightness: np.ndarray) -> tuple[Features, Features]:
    """The detector's measurements along rows and along columns of an OKLab lightness array
    (h, w)."""
    return _axis(lightness, "rows"), _axis(lightness.T, "columns")


def find_bars(lightness: np.ndarray) -> Bars | None:
    """The bars framing an OKLab lightness array (h, w), or None. A letterbox wins over a
    pillarbox (a picture with both is windowboxed: its rows are taken)."""
    rows, columns = features(lightness)
    if rows.bars:
        return Bars(rows.start, rows.end, 0, 0)
    if columns.bars:
        return Bars(0, 0, columns.start, columns.end)
    return None


def _axis(lightness: np.ndarray, axis: str) -> Features:
    """Bars at the top and bottom of `lightness` (rows): uniform dark rows from each edge."""
    flat = (lightness.mean(axis=1) < BAR_LIGHTNESS) & (lightness.std(axis=1) < BAR_FLATNESS)
    length = len(flat)
    start = _run(flat)
    end = _run(flat[::-1])
    if start == length or not start or not end:
        return Features(axis, start, end if start < length else 0, length, None)
    content = lightness[start : length - end]
    third = len(content) // 3
    middle = content[third : len(content) - third] if third else content
    return Features(axis, start, end, length, float((middle < DARK).mean()))


def _run(flags: np.ndarray) -> int:
    """How many of `flags` are true from the start."""
    false = np.flatnonzero(~flags)
    return int(false[0]) if false.size else len(flags)
