"""Image metrics: lightness, colourfulness, hue and detail, measured in OKLCH.

Definitions and the reasoning behind them are in docs/design.md, "Metrics". Every image is
resized to the width of Wallhaven's `large` thumbnail first, so a thumbnail and its full image
are measured at the same scale.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO

import numpy as np
from PIL import Image, ImageOps

from amontillado.colour import srgb_to_oklch

# Bump when a metric's definition changes: sidecars with an older version are recomputed.
METRICS_VERSION = 2

MEASURE_WIDTH = 432

# Initial values; calibrated thresholds replace them (docs/design.md).
CHROMATIC_MIN = 0.03
EDGE_MIN = 0.08

# Upper bounds of the hue sectors, in degrees; red wraps around 0°.
_SECTOR_BOUNDS = np.array([44.0, 80.0, 125.0, 170.0, 230.0, 280.0, 310.0, 358.0])
HUE_NAMES = ("red", "orange", "yellow", "green", "cyan", "blue", "purple", "pink")
# Width of the arc whose weight is hue_share, in degrees (one per histogram bin).
HUE_ARC = 60
WARM_HUES = frozenset({"red", "orange", "yellow", "pink"})

_ALPHA_MODES = frozenset({"RGBA", "RGBa", "LA", "La", "PA"})
# EXIF orientations that swap width and height for display.
_TRANSPOSED = frozenset({5, 6, 7, 8})


@dataclass(frozen=True)
class Metrics:
    """The measurements of one image; see docs/design.md for each definition."""

    lightness: float
    chroma: float
    colourful_share: float
    hue: float | None
    hue_name: str | None
    hue_share: float
    hue_spread: float
    warmth: float
    busy: float

    def to_dict(self) -> dict[str, object]:
        """The sidecar `metrics` block: version first, values rounded for readability."""
        values: dict[str, object] = {"version": METRICS_VERSION}
        for name, value in asdict(self).items():
            if isinstance(value, float):
                value = round(value, 1 if name == "hue" else 3)
            values[name] = value
        return values

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> Metrics:
        """Metrics from a sidecar `metrics` block; the version is the caller's to check.

        Raises ValueError naming the first field that is missing or of the wrong type.
        """
        fields: dict[str, object] = {}
        for name in cls.__dataclass_fields__:
            value = values.get(name)
            if name == "hue_name":
                ok = value is None or value in HUE_NAMES
            else:
                # bool is an int subclass, and never a measurement.
                number = isinstance(value, (int, float)) and not isinstance(value, bool)
                ok = number or (name == "hue" and value is None)
                if number:
                    value = float(value)
            if not ok:
                raise ValueError(f"metrics.{name} is missing or invalid")
            fields[name] = value
        return cls(**fields)


def image_size(path: Path) -> tuple[int, int]:
    """Width and height as displayed, after EXIF orientation; reads the header only."""
    with Image.open(path) as image:
        if _orientation(image) in _TRANSPOSED:
            return image.height, image.width
        return image.width, image.height


_ORIENTATION = 0x0112


def _orientation(image: Image.Image) -> int:
    return image.getexif().get(_ORIENTATION, 1)


def load_rgb(path: Path | IO[bytes]) -> np.ndarray:
    """Open an image (a path or a binary file object) and return it as 8-bit sRGB,
    MEASURE_WIDTH wide, shape (h, w, 3).

    EXIF orientation is applied, alpha is composited on black, and JPEGs are decoded at a
    reduced scale where that still leaves at least MEASURE_WIDTH pixels.
    """
    with Image.open(path) as image:
        _request_draft(image)
        image = ImageOps.exif_transpose(image)
        image = _to_rgb(image)
        height = max(1, round(image.height * MEASURE_WIDTH / image.width))
        image = image.resize((MEASURE_WIDTH, height), Image.Resampling.LANCZOS)
        return np.asarray(image, dtype=np.uint8)


def write_thumbnail(source: Path, target: Path, size: int) -> None:
    """Write a JPEG of `source` at most `size` pixels on its longer side to `target` (made
    atomically, its directory created), EXIF orientation applied, alpha on black."""
    with Image.open(source) as image:
        if max(image.size) > size:
            image.draft("RGB", (size, size))
        image = _to_rgb(ImageOps.exif_transpose(image))
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f".{target.name}.part")
        try:
            image.save(partial, "JPEG", quality=85)
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)


def write_crop(source: Path, target: Path, box: tuple[int, int, int, int]) -> None:
    """Write `box` (x, y, width, height, in the image as displayed: after EXIF orientation) of
    `source` to `target` in the same format, atomically. JPEG and WebP are encoded at quality
    95. The ICC profile and EXIF are kept, the orientation reset: the rotation is in the
    pixels, so a viewer that ignores EXIF shows the crop as the original is displayed."""
    x, y, width, height = box
    with Image.open(source) as image:
        format_ = image.format
        icc = image.info.get("icc_profile")
        exif = image.getexif()
        cropped = ImageOps.exif_transpose(image).crop((x, y, x + width, y + height))
    options: dict[str, object] = {"icc_profile": icc} if icc else {}
    if exif:
        exif[_ORIENTATION] = 1
        options["exif"] = exif
    if format_ in ("JPEG", "WEBP"):
        options["quality"] = 95
    # Not an image suffix, so a scan never takes it for one of the record's files.
    partial = target.with_name(f".{target.name}.part")
    try:
        cropped.save(partial, format_, **options)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def _request_draft(image: Image.Image) -> None:
    # The scale is the same along both axes, so this holds whatever the EXIF rotation is.
    displayed_width = image.height if _orientation(image) in _TRANSPOSED else image.width
    scale = MEASURE_WIDTH / displayed_width
    if scale < 1:
        image.draft("RGB", (math.ceil(image.width * scale), math.ceil(image.height * scale)))


def _to_rgb(image: Image.Image) -> Image.Image:
    if image.mode == "P" and "transparency" in image.info:
        image = image.convert("RGBA")
    if image.mode in _ALPHA_MODES:
        rgba = image.convert("RGBA")
        black = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
        return Image.alpha_composite(black, rgba).convert("RGB")
    return image.convert("RGB")


def measure(rgb: np.ndarray) -> Metrics:
    """Measure an 8-bit sRGB array of shape (h, w, 3)."""
    lightness, chroma, hue = srgb_to_oklch(rgb)
    chromatic = chroma > CHROMATIC_MIN
    hue_stats = _hue_statistics(hue[chromatic], chroma[chromatic])
    return Metrics(
        lightness=float(lightness.mean()),
        chroma=float(chroma.mean()),
        colourful_share=float(chromatic.mean()),
        busy=_edge_density(lightness),
        **hue_stats,
    )


def measure_file(path: Path | IO[bytes]) -> Metrics:
    """Measure the image at `path`, or in a binary file object."""
    return measure(load_rgb(path))


def _hue_statistics(hue: np.ndarray, weight: np.ndarray) -> dict[str, object]:
    total = float(weight.sum())
    if total == 0:
        return {"hue": None, "hue_name": None, "hue_share": 0.0, "hue_spread": 0.0, "warmth": 0.0}

    radians = np.radians(hue)
    sin_sum = float((weight * np.sin(radians)).sum())
    cos_sum = float((weight * np.cos(radians)).sum())
    resultant = math.hypot(sin_sum, cos_sum) / total

    sector = _sector(hue)
    sector_weight = np.bincount(sector, weights=weight, minlength=len(HUE_NAMES))
    warm = sum(sector_weight[i] for i, name in enumerate(HUE_NAMES) if name in WARM_HUES)
    arc_weight, arc_hue = _heaviest_arc(hue, weight)

    return {
        "hue": math.degrees(math.atan2(sin_sum, cos_sum)) % 360.0,
        "hue_name": HUE_NAMES[int(_sector(np.array(arc_hue)))],
        "hue_share": arc_weight / total,
        "hue_spread": max(0.0, 1.0 - resultant),
        "warmth": float((2 * warm - total) / total),
    }


def _sector(hue: np.ndarray) -> np.ndarray:
    return np.searchsorted(_SECTOR_BOUNDS, hue, side="right") % len(HUE_NAMES)


def _heaviest_arc(hue: np.ndarray, weight: np.ndarray) -> tuple[float, float]:
    """The weight of the heaviest HUE_ARC-degree arc of the hue circle, and the weighted
    circular mean of the hues in it.

    Arcs start on whole degrees. Measuring the arc rather than a fixed sector keeps one hue
    that straddles a sector boundary together; centring it on the peak rather than on the
    mean hue keeps a dominant hue that a second one pulls the mean away from.
    """
    degree = np.floor(hue).astype(np.intp) % 360
    histogram = np.bincount(degree, weights=weight, minlength=360)
    wrapped = np.concatenate([histogram, histogram[: HUE_ARC - 1]])
    arcs = np.convolve(wrapped, np.ones(HUE_ARC), mode="valid")
    start = int(arcs.argmax())
    inside = (degree - start) % 360 < HUE_ARC
    radians = np.radians(hue[inside])
    w = weight[inside]
    mean = math.degrees(math.atan2((w * np.sin(radians)).sum(), (w * np.cos(radians)).sum()))
    return float(arcs[start]), mean % 360.0


def _edge_density(lightness: np.ndarray) -> float:
    """Share of interior pixels whose Sobel gradient magnitude on L exceeds EDGE_MIN.

    The kernels are divided by 8, so the magnitude is the change in L per pixel: a hard edge
    from black to white scores 0.5 on the pixels either side of it.
    """
    if lightness.shape[0] < 3 or lightness.shape[1] < 3:
        return 0.0
    p = lightness
    gx = (
        (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    ) / 8
    gy = (
        (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    ) / 8
    return float((np.hypot(gx, gy) > EDGE_MIN).mean())
