#!/usr/bin/env python3
"""Contact sheets for palette-aware grouping: which pictures does each signature call close?

The evidence behind docs/design.md, "Grouping: decisions", 1 (spike amo-50c.1), and the tool for
calibrating the compatibility bound (amo-6f0.4). Over the calibration sample's thumbnails
(tools/calibrate.py), two colour signatures:

  metrics  the stored metrics as a mean colour in OKLab (lightness, chroma, hue) plus
           hue_spread, compared by Euclidean distance
  palette  a k-means palette in OKLab (k colours with their pixel shares), compared by the
           share-weighted distance from each colour to the other palette's nearest, both ways

For --anchors random pictures, the sheet shows one row per signature: the anchor, then its
--neighbours nearest pictures, each labelled with its distance. Also printed: how many
neighbours the two signatures share, and percentiles of the palette distance (between any two
pictures, and to each picture's nearest), which show whether the sample has cluster structure.

The sheet holds Wallhaven thumbnails: write it outside the repository.

  uv run tools/grouping_sheet.py ~/.local/state/amontillado/calibration /tmp/sheet.png
"""

from __future__ import annotations

import argparse
import json
import math
import time
from logging import getLogger
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from rich.console import Console
from rich.logging import RichHandler

from amontillado.cli import HelpFormatter
from amontillado.colour import srgb_to_oklab
from amontillado.metrics import Metrics, load_rgb, measure

logger = getLogger("grouping_sheet")

TILE_WIDTH = 200
TILE_HEIGHT = TILE_WIDTH * 9 // 16
GAP = 4
LABEL_WIDTH = 30
ANCHOR_GAP = 12
# Pairs for the distance percentiles: the first this many pictures, every pair.
PERCENTILE_PICTURES = 120

Palette = tuple[np.ndarray, np.ndarray]


def get_cli_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=HelpFormatter)
    parser.add_argument(
        "--loglevel",
        "-l",
        default="INFO",
        type=lambda v: v.strip().upper(),
        help="Logging verbosity (DEBUG, INFO, WARNING, ERROR).",
    )
    parser.add_argument("sample", type=Path, help="the calibration sample directory")
    parser.add_argument("sheet", type=Path, help="the PNG contact sheet to write")
    parser.add_argument("--anchors", type=int, default=8, help="random pictures to show")
    parser.add_argument("--neighbours", type=int, default=5, help="nearest pictures per row")
    parser.add_argument("--colours", type=int, default=6, help="k, the palette's colours")
    parser.add_argument("--seed", type=int, default=7, help="for the anchors and k-means")
    return parser.parse_args()


def setup_logger(args: argparse.Namespace) -> None:
    logger.addHandler(RichHandler(level=args.loglevel, console=Console(stderr=True)))
    logger.setLevel(args.loglevel)


def kmeans_palette(lab: np.ndarray, k: int, rng: np.random.Generator) -> Palette:
    """k OKLab centres and their pixel shares: k-means++ start, then 12 Lloyd steps."""
    centres = [lab[rng.integers(len(lab))]]
    for _ in range(1, k):
        nearest = np.min([((lab - c) ** 2).sum(1) for c in centres], axis=0)
        centres.append(lab[rng.choice(len(lab), p=nearest / nearest.sum())])
    centre_array = np.array(centres)
    for _ in range(12):
        labels = ((lab[:, None, :] - centre_array[None]) ** 2).sum(2).argmin(1)
        for j in range(k):
            members = lab[labels == j]
            if len(members):
                centre_array[j] = members.mean(0)
    return centre_array, np.bincount(labels, minlength=k) / len(lab)


def palette_distance(first: Palette, second: Palette) -> float:
    """Each colour's distance to the other palette's nearest, share-weighted, both ways."""
    (colours_a, shares_a), (colours_b, shares_b) = first, second
    d = np.sqrt(((colours_a[:, None, :] - colours_b[None]) ** 2).sum(2))
    return float((d.min(1) * shares_a).sum() + (d.min(0) * shares_b).sum()) / 2


def metric_vector(metrics: Metrics) -> np.ndarray:
    hue = math.radians(metrics.hue) if metrics.hue is not None else 0.0
    # Chroma scaled up so that a change of hue weighs about as much as one of lightness.
    chroma = metrics.chroma * 4
    return np.array(
        [metrics.lightness, chroma * math.cos(hue), chroma * math.sin(hue), metrics.hue_spread / 2]
    )


def write_sheet(
    path: Path, thumbs: dict[str, Path], rows: list[tuple[str, str, list[str], list[float]]]
) -> None:
    columns = len(rows[0][2]) + 1
    anchors = len(rows) // 2
    size = (
        LABEL_WIDTH + columns * (TILE_WIDTH + GAP),
        len(rows) * (TILE_HEIGHT + GAP) + anchors * ANCHOR_GAP,
    )
    sheet = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(sheet)
    y = 0
    for n, (label, anchor, near, distances) in enumerate(rows):
        if n and n % 2 == 0:
            y += ANCHOR_GAP
        draw.text((6, y + TILE_HEIGHT // 2), label, fill="black")
        for column, picture in enumerate([anchor, *near]):
            tile = Image.open(thumbs[picture]).convert("RGB").resize((TILE_WIDTH, TILE_HEIGHT))
            x = LABEL_WIDTH + column * (TILE_WIDTH + GAP)
            sheet.paste(tile, (x, y))
            if column:
                text = f"{distances[column - 1]:.3f}"
                draw.text((x + 3, y + 3), text, fill="white", stroke_width=2, stroke_fill="black")
        y += TILE_HEIGHT + GAP
    sheet.save(path)


def main() -> None:
    args = get_cli_arguments()
    setup_logger(args)
    rng = np.random.default_rng(args.seed)
    with (args.sample / "sample.jsonl").open() as sample:
        ids = [json.loads(line)["id"] for line in sample]
    thumbs = {i: args.sample / "thumbs" / f"{i}.jpg" for i in ids}
    ids = [i for i in ids if thumbs[i].exists()]
    if len(ids) <= args.neighbours:
        raise SystemExit(f"grouping_sheet: {len(ids)} thumbnails in {args.sample}")

    vectors: dict[str, np.ndarray] = {}
    palettes: dict[str, Palette] = {}
    measuring = clustering = 0.0
    for picture in ids:
        rgb = load_rgb(thumbs[picture])
        start = time.perf_counter()
        vectors[picture] = metric_vector(measure(rgb))
        middle = time.perf_counter()
        palettes[picture] = kmeans_palette(
            srgb_to_oklab(rgb.reshape(-1, 3))[::4], args.colours, rng
        )
        clustering += time.perf_counter() - middle
        measuring += middle - start
    logger.info(
        "%d thumbnails; metrics %.1f ms, k-means %.1f ms per picture",
        len(ids),
        1000 * measuring / len(ids),
        1000 * clustering / len(ids),
    )

    rows = []
    shared = []
    for anchor in rng.choice(ids, args.anchors, replace=False):
        others = [i for i in ids if i != anchor]
        by_metrics = sorted(
            (float(np.linalg.norm(vectors[anchor] - vectors[i])), i) for i in others
        )[: args.neighbours]
        by_palette = sorted((palette_distance(palettes[anchor], palettes[i]), i) for i in others)[
            : args.neighbours
        ]
        near_metrics = [i for _, i in by_metrics]
        near_palette = [i for _, i in by_palette]
        shared.append(len(set(near_metrics) & set(near_palette)))
        rows.append(("M", anchor, near_metrics, [d for d, _ in by_metrics]))
        rows.append(("P", anchor, near_palette, [d for d, _ in by_palette]))
        print(f"{anchor}: {shared[-1]}/{args.neighbours} shared")
    print(f"shared on average: {np.mean(shared):.2f}/{args.neighbours}")

    first = ids[:PERCENTILE_PICTURES]
    pairs = [palette_distance(palettes[a], palettes[b]) for a in first for b in first if a < b]
    nearest = [
        min(palette_distance(palettes[a], palettes[b]) for b in ids if b != a) for a in first
    ]
    print(
        "palette distance, any two (p5/25/50/75/95):",
        np.percentile(pairs, [5, 25, 50, 75, 95]).round(3),
    )
    print(
        "palette distance, to the nearest (p5/50/95):", np.percentile(nearest, [5, 50, 95]).round(3)
    )

    write_sheet(args.sheet, thumbs, rows)
    logger.info("sheet: %s (row M: metrics, row P: palette)", args.sheet)


if __name__ == "__main__":
    main()
