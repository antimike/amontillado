from __future__ import annotations

import numpy as np
import pytest

from amontillado.colour import (
    contrast_ratio,
    hex_to_oklch,
    hue_distance,
    oklch_to_hex,
    srgb_to_oklab,
    srgb_to_oklch,
)


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


@pytest.mark.parametrize(
    "colour", ["#000000", "#ffffff", "#7aa2f7", "#1b1d2b", "#ff0000", "#00ff00"]
)
def test_oklch_round_trip(colour: str) -> None:
    assert oklch_to_hex(*hex_to_oklch(colour)) == colour


def test_out_of_gamut_keeps_lightness_and_hue_and_lowers_chroma() -> None:
    lightness, chroma, hue = hex_to_oklch("#fabd2f")
    clipped = oklch_to_hex(lightness + 0.08, chroma, hue)
    new_l, new_c, new_h = hex_to_oklch(clipped)
    assert new_l == pytest.approx(lightness + 0.08, abs=0.005)
    assert new_c < chroma
    assert hue_distance(new_h, hue) < 2


def test_lightness_is_clamped() -> None:
    assert oklch_to_hex(1.4, 0.0, 0.0) == "#ffffff"
    assert oklch_to_hex(-0.2, 0.1, 30.0) == "#000000"


def test_contrast_ratio() -> None:
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0)
    assert contrast_ratio("#777777", "#777777") == pytest.approx(1.0)
    # WebAIM's checker gives 4.48 for #777777 on white.
    assert contrast_ratio("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)


def test_hue_distance_wraps() -> None:
    assert hue_distance(350.0, 10.0) == pytest.approx(20.0)
    assert hue_distance(10.0, 190.0) == pytest.approx(180.0)
