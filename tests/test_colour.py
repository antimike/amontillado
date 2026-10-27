from __future__ import annotations

import numpy as np
import pytest

from amontillado.colour import srgb_to_oklab, srgb_to_oklch


def _pixel(r: int, g: int, b: int) -> np.ndarray:
    return np.array([[r, g, b]], dtype=np.uint8)


@pytest.mark.parametrize(
    ("rgb", "expected_hue"),
    [
        ((255, 0, 0), 29.2),
        ((255, 255, 0), 109.8),
        ((0, 255, 0), 142.5),
        ((0, 255, 255), 194.8),
        ((0, 0, 255), 264.1),
        ((255, 0, 255), 328.4),
    ],
)
def test_primary_hues(rgb: tuple[int, int, int], expected_hue: float) -> None:
    _, chroma, hue = srgb_to_oklch(_pixel(*rgb))
    assert chroma[0] > 0.1
    assert hue[0] == pytest.approx(expected_hue, abs=0.5)


def test_white_and_black() -> None:
    white = srgb_to_oklab(_pixel(255, 255, 255))[0]
    black = srgb_to_oklab(_pixel(0, 0, 0))[0]
    np.testing.assert_allclose(white, [1.0, 0.0, 0.0], atol=1e-4)
    np.testing.assert_allclose(black, [0.0, 0.0, 0.0], atol=1e-6)


def test_greys_have_no_chroma() -> None:
    greys = np.repeat(np.arange(256, dtype=np.uint8)[:, None], 3, axis=1)
    lightness, chroma, _ = srgb_to_oklch(greys)
    assert chroma.max() < 1e-4
    assert np.all(np.diff(lightness) > 0)


def test_known_value() -> None:
    # Reference value for sRGB red from Ottosson's published implementation.
    lab = srgb_to_oklab(_pixel(255, 0, 0))[0]
    np.testing.assert_allclose(lab, [0.62796, 0.22486, 0.12585], atol=1e-4)


def test_rejects_float_input() -> None:
    with pytest.raises(TypeError):
        srgb_to_oklab(np.zeros((1, 3)))
