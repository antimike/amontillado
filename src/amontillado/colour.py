"""sRGB to OKLCH conversion.

OKLab is Björn Ottosson's perceptual colour space (https://bottosson.github.io/posts/oklab/);
OKLCH is its polar form: lightness L (0-1), chroma C (0 for greys), hue h in degrees.
"""

from __future__ import annotations

import numpy as np

_LINEAR_TO_LMS = np.array(
    [
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ]
)
_LMS_TO_OKLAB = np.array(
    [
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ]
)


def _srgb_decode_table() -> np.ndarray:
    c = np.arange(256) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


# 8-bit input has only 256 possible channel values: decode them once.
_SRGB_TO_LINEAR = _srgb_decode_table()


def srgb_to_oklab(rgb: np.ndarray) -> np.ndarray:
    """Convert 8-bit sRGB, shape (..., 3) and dtype uint8, to OKLab, shape (..., 3)."""
    if rgb.dtype != np.uint8:
        raise TypeError(f"expected uint8 sRGB, got {rgb.dtype}")
    linear = _SRGB_TO_LINEAR[rgb]
    lms = np.cbrt(linear @ _LINEAR_TO_LMS.T)
    return lms @ _LMS_TO_OKLAB.T


def srgb_to_oklch(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Convert 8-bit sRGB to OKLCH: arrays L (0-1), C (≥ 0) and h (degrees, 0-360).

    The hue of a pixel with no chroma is meaningless; callers mask those pixels out.
    """
    lab = srgb_to_oklab(rgb)
    lightness, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    chroma = np.hypot(a, b)
    hue = np.degrees(np.arctan2(b, a)) % 360.0
    return lightness, chroma, hue
