from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from amontillado.metrics import MEASURE_WIDTH, METRICS_VERSION, load_rgb, measure, measure_file


def solid(rgb: tuple[int, int, int], size: tuple[int, int] = (64, 36)) -> np.ndarray:
    return np.full((size[1], size[0], 3), rgb, dtype=np.uint8)


def grey_noise(seed: int = 0) -> np.ndarray:
    values = np.random.default_rng(seed).integers(0, 256, size=(243, 432), dtype=np.uint8)
    return np.repeat(values[..., None], 3, axis=2)


def grey_gradient() -> np.ndarray:
    row = np.linspace(0, 255, 432).astype(np.uint8)
    return np.repeat(np.tile(row, (243, 1))[..., None], 3, axis=2)


def hue_wheel() -> np.ndarray:
    hsv = np.zeros((243, 432, 3), dtype=np.uint8)
    hsv[..., 0] = np.linspace(0, 255, 432, endpoint=False).astype(np.uint8)
    hsv[..., 1:] = 255
    return np.asarray(Image.fromarray(hsv, mode="HSV").convert("RGB"))


def test_black_is_dark_and_colourless() -> None:
    m = measure(solid((0, 0, 0)))
    assert m.lightness == pytest.approx(0.0, abs=1e-6)
    assert m.chroma == pytest.approx(0.0, abs=1e-6)
    assert m.colourful_share == 0.0
    assert m.busy == 0.0


def test_greyscale_has_no_hue() -> None:
    m = measure(solid((128, 128, 128)))
    assert (m.hue, m.hue_name, m.hue_share, m.hue_spread, m.warmth) == (None, None, 0.0, 0.0, 0.0)


def test_solid_red_is_one_saturated_warm_hue() -> None:
    m = measure(solid((255, 0, 0)))
    assert m.chroma > 0.2
    assert m.colourful_share == 1.0
    assert m.hue == pytest.approx(29.2, abs=0.5)
    assert m.hue_name == "red"
    assert m.hue_share == pytest.approx(1.0)
    assert m.hue_spread == pytest.approx(0.0, abs=1e-9)
    assert m.warmth == pytest.approx(1.0)


def test_solid_blue_is_cool() -> None:
    m = measure(solid((0, 0, 255)))
    assert m.hue_name == "blue"
    assert m.warmth == pytest.approx(-1.0)


@pytest.mark.parametrize(
    ("rgb", "name"),
    [
        ((255, 0, 0), "red"),
        ((255, 128, 0), "orange"),
        ((255, 255, 0), "yellow"),
        ((0, 200, 0), "green"),
        ((0, 255, 255), "cyan"),
        ((0, 0, 255), "blue"),
        ((128, 0, 255), "purple"),
        ((255, 0, 255), "pink"),
    ],
)
def test_hue_sectors(rgb: tuple[int, int, int], name: str) -> None:
    assert measure(solid(rgb)).hue_name == name


def test_red_hue_wraps_around_zero() -> None:
    # One pixel either side of 0°: the circular mean is near 0°, not near 180°.
    image = np.array([[[255, 0, 90], [255, 60, 0]]], dtype=np.uint8)
    m = measure(image)
    assert m.hue_name == "red"
    assert min(m.hue, 360 - m.hue) < 30


def test_half_red_half_blue() -> None:
    image = solid((255, 0, 0))
    image[:, 32:] = (0, 0, 255)
    m = measure(image)
    assert 0.3 < m.hue_spread < 0.7
    assert m.hue_share < 0.6


def test_hue_wheel_is_multi_hued() -> None:
    m = measure(hue_wheel())
    assert m.hue_spread > 0.9
    assert m.hue_share < 0.3


def test_vivid_patch_on_grey() -> None:
    image = solid((128, 128, 128))
    image[:9, :16] = (255, 0, 0)
    m = measure(image)
    assert m.colourful_share == pytest.approx(9 * 16 / (36 * 64))
    assert m.hue_name == "red"
    assert m.hue_share == pytest.approx(1.0)


def test_grey_noise_is_busy_and_muted() -> None:
    m = measure(grey_noise())
    assert m.busy > 0.5
    assert m.chroma < 0.01


def test_smooth_gradient_is_sparse() -> None:
    m = measure(grey_gradient())
    assert m.busy == 0.0
    assert 0.4 < m.lightness < 0.7


def test_hard_edge_scores_half() -> None:
    image = solid((0, 0, 0), size=(10, 10))
    image[:, 5:] = 255
    m = measure(image)
    assert m.busy == pytest.approx(2 / 8)


def test_to_dict_rounds_and_versions() -> None:
    d = measure(hue_wheel()).to_dict()
    assert next(iter(d)) == "version"
    assert d["version"] == METRICS_VERSION
    assert d["lightness"] == round(d["lightness"], 3)
    assert d["hue"] == round(d["hue"], 1)


def test_tiny_image() -> None:
    assert measure(solid((10, 200, 30), size=(2, 1))).busy == 0.0


def _save(array: np.ndarray, path: Path, **kwargs: object) -> Path:
    Image.fromarray(array).save(path, **kwargs)
    return path


def test_load_resizes_to_thumbnail_width(tmp_path: Path) -> None:
    rgb = load_rgb(_save(solid((10, 20, 30), size=(1920, 1080)), tmp_path / "a.png"))
    assert rgb.shape == (243, MEASURE_WIDTH, 3)
    assert rgb.dtype == np.uint8


def test_large_jpeg_matches_png(tmp_path: Path) -> None:
    # The JPEG takes the reduced-scale decode path; the result should barely differ.
    big = np.repeat(np.repeat(hue_wheel(), 8, axis=0), 8, axis=1)
    from_png = measure_file(_save(big, tmp_path / "big.png"))
    from_jpeg = measure_file(_save(big, tmp_path / "big.jpg", quality=95))
    assert from_jpeg.lightness == pytest.approx(from_png.lightness, abs=0.01)
    assert from_jpeg.chroma == pytest.approx(from_png.chroma, abs=0.01)
    assert from_jpeg.hue_spread == pytest.approx(from_png.hue_spread, abs=0.01)


def test_exif_orientation_is_applied(tmp_path: Path) -> None:
    stored = solid((0, 0, 0), size=(800, 400))
    stored[:, :400] = 255
    image = Image.fromarray(stored)
    exif = image.getexif()
    exif[0x0112] = 6  # rotate 90° clockwise for display
    path = tmp_path / "rotated.jpg"
    image.save(path, exif=exif)
    rgb = load_rgb(path)
    assert rgb.shape == (864, MEASURE_WIDTH, 3)
    assert rgb[:400].mean() > 200  # the white half is on top once rotated
    assert rgb[-400:].mean() < 50


def test_alpha_is_composited_on_black(tmp_path: Path) -> None:
    rgba = np.zeros((36, 64, 4), dtype=np.uint8)
    rgba[..., :3] = 255
    path = tmp_path / "clear.png"
    Image.fromarray(rgba, mode="RGBA").save(path)
    assert measure_file(path).lightness == pytest.approx(0.0, abs=1e-6)


def test_palette_and_cmyk(tmp_path: Path) -> None:
    red = Image.fromarray(solid((255, 0, 0)))
    red.convert("P").save(tmp_path / "p.png")
    red.convert("CMYK").save(tmp_path / "c.jpg")
    assert measure_file(tmp_path / "p.png").hue_name == "red"
    assert measure_file(tmp_path / "c.jpg").hue_name == "red"
