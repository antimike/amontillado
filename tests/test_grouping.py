from __future__ import annotations

from pathlib import Path

import pytest

from amontillado.grouping import GroupError, Monitor, companions, palette_distance
from amontillado.index import IndexedFile
from amontillado.metrics import Metrics


def test_identical_palettes_are_zero_apart() -> None:
    palette = (("#1b2330", 0.6), ("#c9a46b", 0.4))
    assert palette_distance(palette, palette) == 0.0


def test_distance_is_symmetric_and_weighted_by_share() -> None:
    black, white = ("#000000", 1.0), ("#ffffff", 1.0)
    # Black to white is 1 in OKLab (lightness 0 to 1).
    assert palette_distance((black,), (white,)) == pytest.approx(1.0, abs=1e-6)
    mostly_black = (("#000000", 0.75), ("#ffffff", 0.25))
    # From black's side 0; from the other's, white (a quarter) is 1 from black: (0 + 0.25) / 2.
    assert palette_distance((black,), mostly_black) == pytest.approx(0.125, abs=1e-6)
    assert palette_distance(mostly_black, (black,)) == palette_distance((black,), mostly_black)


def _file(record_id: str, colour: str, ratio: float = 16 / 9) -> IndexedFile:
    metrics = Metrics(0.5, 0.1, 0.5, None, None, 0.0, 0.0, 0.0, 0.0, ((colour, 1.0),))
    return IndexedFile(
        Path(f"/l/{record_id}.png"),
        record_id,
        "sfw",
        False,
        True,
        round(900 * ratio),
        900,
        None,
        metrics,
    )


GREYS = {"g10": "#1a1a1a", "g20": "#333333", "g30": "#4d4d4d", "g90": "#e6e6e6"}
PRIMARY = _file("g00", "#000000")
MONITORS = [Monitor("DP-2", 16 / 9, "16:9"), Monitor("HDMI-1", 16 / 9, "16:9")]


def _companions(order: list[str], **kwargs: object) -> list[tuple[str, bool]]:
    options = {"max_distance": 0.25, "nearest": False, "accept": lambda f: True, **kwargs}
    accept = options.pop("accept")
    chosen = companions(
        PRIMARY, MONITORS, order, lambda r, _: _file(r, GREYS[r]), accept, **options
    )
    return [(choice.file.record_id, choice.beyond) for choice in chosen]


def test_companions_in_the_order_given_or_nearest() -> None:
    # From black: g10 0.22, g20 0.32, g30 0.42, g90 0.92 (OKLab lightness).
    order = ["g20", "g10", "g90", "g30"]
    assert _companions(order, max_distance=0.35) == [("g20", False), ("g10", False)]
    assert _companions(order, max_distance=0.35, nearest=True) == [("g10", False), ("g20", False)]


def test_too_few_compatible_fill_with_the_nearest_beyond() -> None:
    assert _companions(["g90", "g30", "g10"], max_distance=0.25) == [("g10", False), ("g30", True)]


def test_companions_skip_the_primary_and_rejected_records() -> None:
    order = ["g00", "g10", "g20", "g30"]
    GREYS["g00"] = "#000000"
    try:
        chosen = _companions(order, accept=lambda f: f.record_id != "g10")
    finally:
        del GREYS["g00"]
    assert chosen == [("g20", True), ("g30", True)]


def test_too_few_pictures() -> None:
    with pytest.raises(GroupError, match="none left for monitor HDMI-1"):
        _companions(["g10"])
