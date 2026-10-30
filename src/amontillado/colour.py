"""sRGB to OKLCH conversion and back, and WCAG 2 contrast.

OKLab is Björn Ottosson's perceptual colour space (https://bottosson.github.io/posts/oklab/);
OKLCH is its polar form: lightness L (0-1), chroma C (0 for greys), hue h in degrees. Single
colours are `#rrggbb` strings; images are uint8 arrays.
"""

from __future__ import annotations

import math
import re

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


HEX_PATTERN = re.compile(r"#[0-9a-f]{6}")

_OKLAB_TO_LMS = np.linalg.inv(_LMS_TO_OKLAB)
_LMS_TO_LINEAR = np.linalg.inv(_LINEAR_TO_LMS)
# A colour this close outside the sRGB cube rounds into it.
_GAMUT_TOLERANCE = 1e-4


def _hex_rgb(colour: str) -> np.ndarray:
    return np.array([int(colour[i : i + 2], 16) for i in (1, 3, 5)], dtype=np.uint8)


def hex_to_oklch(colour: str) -> tuple[float, float, float]:
    """The OKLCH of a `#rrggbb` colour: L, C, and h in degrees (meaningless when C is ~0)."""
    lightness, chroma, hue = srgb_to_oklch(_hex_rgb(colour))
    return float(lightness), float(chroma), float(hue)


def _oklch_to_linear(lightness: float, chroma: float, hue: float) -> np.ndarray:
    angle = math.radians(hue)
    lab = np.array([lightness, chroma * math.cos(angle), chroma * math.sin(angle)])
    return (lab @ _OKLAB_TO_LMS.T) ** 3 @ _LMS_TO_LINEAR.T


def _in_gamut(linear: np.ndarray) -> bool:
    return bool(np.all(linear >= -_GAMUT_TOLERANCE) and np.all(linear <= 1 + _GAMUT_TOLERANCE))


def oklch_to_hex(lightness: float, chroma: float, hue: float) -> str:
    """The `#rrggbb` colour nearest to an OKLCH one: lightness clamped to 0-1, then chroma lowered
    (hue and lightness kept) until the colour is inside the sRGB gamut."""
    lightness = min(max(lightness, 0.0), 1.0)
    linear = _oklch_to_linear(lightness, chroma, hue)
    if not _in_gamut(linear):
        # Bisect on chroma: chroma 0 (a grey) is always in gamut.
        low, high = 0.0, chroma
        for _ in range(30):
            middle = (low + high) / 2
            if _in_gamut(_oklch_to_linear(lightness, middle, hue)):
                low = middle
            else:
                high = middle
        linear = _oklch_to_linear(lightness, low, hue)
    linear = np.clip(linear, 0.0, 1.0)
    encoded = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055)
    return "#" + "".join(f"{round(channel * 255):02x}" for channel in encoded)


def relative_luminance(colour: str) -> float:
    """WCAG 2 relative luminance of a `#rrggbb` colour."""
    red, green, blue = _SRGB_TO_LINEAR[_hex_rgb(colour)]
    return float(0.2126 * red + 0.7152 * green + 0.0722 * blue)


def contrast_ratio(first: str, second: str) -> float:
    """WCAG 2 contrast ratio of two `#rrggbb` colours, 1 to 21."""
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def hue_distance(first: float, second: float) -> float:
    """The angle between two hues in degrees, 0 to 180."""
    difference = abs(first - second) % 360.0
    return min(difference, 360.0 - difference)
