from __future__ import annotations

from dataclasses import replace

import pytest

from amontillado.classes import CLASSES, Look, classify, has_aspect, has_hue
from amontillado.metrics import Metrics

# A mid-grey-ish, mildly coloured, moderately detailed image: in no class at all.
NEUTRAL = Metrics(
    lightness=0.5,
    chroma=0.05,
    colourful_share=0.5,
    hue=262.0,
    hue_name="blue",
    hue_share=0.3,
    hue_spread=0.45,
    warmth=0.0,
    busy=0.08,
)


def test_neutral_is_unclassified() -> None:
    assert classify(NEUTRAL) == []


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"lightness": 0.2}, ["dark"]),
        ({"lightness": 0.8}, ["light"]),
        ({"chroma": 0.01}, ["muted"]),
        ({"chroma": 0.1}, ["saturated"]),
        ({"busy": 0.01}, ["sparse"]),
        ({"busy": 0.2}, ["busy"]),
        ({"hue_spread": 0.1}, ["monochrome"]),
        ({"hue_spread": 0.8}, ["multi-hue"]),
        ({"warmth": 0.5}, ["warm"]),
        ({"warmth": -0.5}, ["cool"]),
        ({"hue_share": 0.7}, ["blue"]),
    ],
)
def test_each_class(changes: dict[str, float], expected: list[str]) -> None:
    assert classify(replace(NEUTRAL, **changes)) == expected


def test_greyscale_is_muted_never_monochrome() -> None:
    grey = replace(NEUTRAL, chroma=0.0, hue=None, hue_name=None, hue_share=0.0, hue_spread=0.0)
    assert "muted" in classify(grey)
    assert not CLASSES["monochrome"](grey)


def test_muted_image_has_no_hue() -> None:
    tinted = replace(NEUTRAL, chroma=0.02, hue_share=0.9)
    assert not has_hue(tinted, "blue")
    assert classify(tinted) == ["muted"]


def test_hue_is_only_the_dominant_one() -> None:
    m = replace(NEUTRAL, hue_share=0.9)
    assert has_hue(m, "blue")
    assert not has_hue(m, "red")


@pytest.mark.parametrize(
    ("size", "ratio", "expected"),
    [
        ((3440, 1440), 21 / 9, True),
        ((2560, 1080), 21 / 9, True),
        ((1920, 1080), 16 / 9, True),
        ((1920, 1200), 16 / 9, False),
        ((1920, 1080), 21 / 9, False),
    ],
)
def test_has_aspect(size: tuple[int, int], ratio: float, expected: bool) -> None:
    assert has_aspect(*size, ratio) is expected


def test_look_matches_every_class_and_the_hue() -> None:
    red = replace(NEUTRAL, chroma=0.2, hue_name="red", hue_share=0.9, busy=0.2)
    assert Look().matches(red)
    assert Look(("saturated", "busy"), "red").matches(red)
    assert not Look(("saturated", "sparse")).matches(red)
    assert Look(("saturated", "sparse")).matches(red, ignore={"sparse"})
    assert not Look(hue="blue").matches(red)
