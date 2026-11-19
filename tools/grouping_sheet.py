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

--mode compare (the default) is that spike. The other modes calibrate the shipped code
(amontillado.metrics.palette, amontillado.grouping.palette_distance; amo-6f0.4) and print, for
each k in --k, the distance percentiles and how many pictures have enough companions within
each bound of --bounds (for 2 and 3 monitors without falling back beyond the bound):

  threshold  each anchor and its --neighbours nearest (k = the first of --k), each tile framed
             green within --max-distance, red beyond
  k          each anchor's nearest under every k of --k, one row per k
  sets       amo group's choice for 3 monitors at --max-distance: the anchor as the primary,
             companions nearest first (row N) and in random order, standing in for least-shown
             (row R); a red frame is a companion from beyond the bound
  letterbox  the pictures with bars (uniform dark rows or columns on both sides) as anchors,
             and their nearest
  variants   each anchor's nearest under each distance variant, one row per variant
             (VARIANTS: V0 the shipped distance; V1 colour axes weighted; V2 also near-black
             and near-white colours down-weighted; V3 also a contrast term and a warmth gate)

The sheet holds Wallhaven thumbnails: write it outside the repository.

  uv run tools/grouping_sheet.py ~/.local/state/amontillado/calibration /tmp/sheet.png
  uv run tools/grouping_sheet.py --mode sets --max-distance 0.05 SAMPLE /tmp/sets.png
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
from amontillado.grouping import palette_distance as shipped_distance
from amontillado.metrics import Metrics, load_rgb, measure
from amontillado.metrics import palette as shipped_palette

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
    parser.add_argument(
        "--mode",
        choices=("compare", "threshold", "k", "sets", "letterbox", "variants"),
        default="compare",
        help="what the sheet shows (see above)",
    )
    parser.add_argument(
        "--k",
        type=lambda v: [int(k) for k in v.split(",")],
        default=[6],
        help="comma-separated palette sizes to calibrate (not compare mode)",
    )
    parser.add_argument(
        "--max-distance", type=float, default=0.05, help="the compatibility bound under test"
    )
    parser.add_argument(
        "--variants",
        type=lambda v: v.split(","),
        default=["V0", "V1", "V2", "V3"],
        help="comma-separated distance variants to show (variants mode; see VARIANTS)",
    )
    parser.add_argument(
        "--variant",
        choices=sorted(VARIANTS),
        help="the distance variant the threshold, k and sets modes use (default: the shipped "
        "distance)",
    )
    parser.add_argument(
        "--bounds",
        type=lambda v: [float(b) for b in v.split(",")],
        default=[0.03, 0.04, 0.05, 0.06, 0.08],
        help="comma-separated bounds to report coverage for",
    )
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


Row = tuple[str, str, list[str], list[float]]
FRAME = 4


def write_sheet(
    path: Path,
    thumbs: dict[str, Path],
    rows: list[Row],
    per_anchor: int = 2,
    bound: float | None = None,
) -> None:
    """Rows of (label, anchor, neighbours, distances), a gap after every `per_anchor` rows.
    With `bound`, each neighbour is framed green within it, red beyond."""
    columns = max(len(row[2]) for row in rows) + 1
    anchors = len(rows) // per_anchor
    size = (
        LABEL_WIDTH + columns * (TILE_WIDTH + GAP),
        len(rows) * (TILE_HEIGHT + GAP) + anchors * ANCHOR_GAP,
    )
    sheet = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(sheet)
    y = 0
    for n, (label, anchor, near, distances) in enumerate(rows):
        if n and n % per_anchor == 0:
            y += ANCHOR_GAP
        draw.text((6, y + TILE_HEIGHT // 2), label, fill="black")
        for column, picture in enumerate([anchor, *near]):
            tile = Image.open(thumbs[picture]).convert("RGB").resize((TILE_WIDTH, TILE_HEIGHT))
            x = LABEL_WIDTH + column * (TILE_WIDTH + GAP)
            sheet.paste(tile, (x, y))
            if column:
                distance = distances[column - 1]
                if bound is not None:
                    colour = "#1a9641" if distance <= bound else "#d7191c"
                    box = (x, y, x + TILE_WIDTH - 1, y + TILE_HEIGHT - 1)
                    draw.rectangle(box, outline=colour, width=FRAME)
                text = f"{distance:.3f}"
                draw.text((x + 6, y + 6), text, fill="white", stroke_width=2, stroke_fill="black")
        y += TILE_HEIGHT + GAP
    sheet.save(path)


def letterboxed(rgb: np.ndarray, share: float = 0.04) -> bool:
    """Whether uniform dark bars (rows, or columns) take at least `share` of both ends with a
    lit picture between them."""
    lightness = srgb_to_oklab(rgb)[..., 0]
    for axis in (1, 0):  # rows, then columns
        flat = (lightness.std(axis=axis) < 0.01) & (lightness.mean(axis=axis) < 0.12)
        need = max(1, round(share * len(flat)))
        content = lightness.mean(axis=axis)[~flat]
        # A logo on a dark background has dark "bars" too: a letterbox frames a lit picture.
        if flat[:need].all() and flat[-need:].all() and content.size and content.mean() > 0.25:
            return True
    return False


# name: (colour-axis weight, weight of near-black/near-white colours, contrast weight, gate)
VARIANTS = {
    "V0": (1.0, 1.0, 0.0, False),
    "V1": (2.5, 1.0, 0.0, False),
    "V2": (2.5, 0.25, 0.0, False),
    "V3": (2.5, 0.25, 0.5, True),
    # Round 2 (MH 2026-11-17: V2 best, keep some contrast): contrast weight and gate apart.
    "C.25": (2.5, 0.25, 0.25, False),
    "C.5": (2.5, 0.25, 0.5, False),
    "C.25+G": (2.5, 0.25, 0.25, True),
}
EXTREME = (0.2, 0.95)  # lightness below / above which a colour is near-black / near-white


def oklab_palette(palette: tuple[tuple[str, float], ...]) -> tuple[np.ndarray, np.ndarray]:
    rgb = np.array([[int(c[i : i + 2], 16) for i in (1, 3, 5)] for c, _ in palette], np.uint8)
    return srgb_to_oklab(rgb), np.array([share for _, share in palette])


def variant_distance(
    first: tuple[np.ndarray, np.ndarray, float],
    second: tuple[np.ndarray, np.ndarray, float],
    variant: tuple[float, float, float, bool],
) -> float:
    """The share-weighted nearest-colour distance with the colour axes scaled, extreme
    colours down-weighted (unless that leaves nothing), plus a contrast term; inf when the
    warmth gate separates a clearly warm picture from a clearly cool one."""
    weight, extreme, contrast, gate = variant
    (lab_a, share_a, warm_a), (lab_b, share_b, warm_b) = first, second
    if gate and warm_a * warm_b < 0 and min(abs(warm_a), abs(warm_b)) > 0.5:
        return float("inf")
    scale = np.array([1.0, weight, weight])

    def weights(lab: np.ndarray, share: np.ndarray) -> np.ndarray:
        light = lab[:, 0]
        w = share * np.where((light < EXTREME[0]) | (light > EXTREME[1]), extreme, 1.0)
        return w / w.sum() if w.sum() > 0.05 else share

    wa, wb = weights(lab_a, share_a), weights(lab_b, share_b)
    d = np.sqrt((((lab_a[:, None] - lab_b[None]) * scale) ** 2).sum(2))
    distance = float((d.min(1) * wa).sum() + (d.min(0) * wb).sum()) / 2

    def spread(lab: np.ndarray, share: np.ndarray) -> float:
        mean = (lab[:, 0] * share).sum()
        return float(np.sqrt(((lab[:, 0] - mean) ** 2 * share).sum()))

    return distance + contrast * abs(spread(lab_a, share_a) - spread(lab_b, share_b))


def variants_sheet(args: argparse.Namespace, ids: list[str], thumbs: dict[str, Path]) -> None:
    """Each anchor's nearest under each of VARIANTS, at k = the first of --k."""
    rng = np.random.default_rng(args.seed)
    anchors = list(rng.choice(ids, args.anchors, replace=False))
    data = {}
    for picture in ids:
        rgb = load_rgb(thumbs[picture])
        lab, share = oklab_palette(shipped_palette(rgb, args.k[0]))
        data[picture] = (lab, share, measure(rgb).warmth)
    rows: list[Row] = []
    for anchor in anchors:
        for name in args.variants:
            variant = VARIANTS[name]
            ranked = sorted(
                (variant_distance(data[anchor], data[p], variant), p) for p in ids if p != anchor
            )[: args.neighbours]
            rows.append((name, anchor, [p for _, p in ranked], [d for d, _ in ranked]))
    write_sheet(args.sheet, thumbs, rows, len(args.variants))
    logger.info("sheet: %s (variants, k=%d)", args.sheet, args.k[0])


def calibrate(args: argparse.Namespace, ids: list[str], thumbs: dict[str, Path]) -> None:
    """The shipped palette and distance: statistics for each k, then the --mode sheet."""
    rng = np.random.default_rng(args.seed)
    rgbs = {picture: load_rgb(thumbs[picture]) for picture in ids}
    palettes = {
        k: {picture: shipped_palette(rgb, k) for picture, rgb in rgbs.items()} for k in args.k
    }
    warmth = {picture: measure(rgb).warmth for picture, rgb in rgbs.items()}
    distances = {}
    for k, by_picture in palettes.items():
        if args.variant is None:
            d = np.array(
                [[shipped_distance(by_picture[a], by_picture[b]) for b in ids] for a in ids]
            )
        else:
            data = {p: (*oklab_palette(by_picture[p]), warmth[p]) for p in ids}
            variant = VARIANTS[args.variant]
            d = np.array([[variant_distance(data[a], data[b], variant) for b in ids] for a in ids])
        np.fill_diagonal(d, np.inf)
        distances[k] = d
        # The warmth gate makes some pairs incompatible (inf): left out of the percentiles.
        pairs = d[np.triu_indices(len(ids), 1)]
        pairs = pairs[np.isfinite(pairs)]
        nearest = d.min(1)
        print(
            f"k={k}: any two (p5/25/50/75/95)", np.percentile(pairs, [5, 25, 50, 75, 95]).round(3)
        )
        print(f"k={k}: to the nearest (p5/50/95)", np.percentile(nearest, [5, 50, 95]).round(3))
        for bound in args.bounds:
            within = (d <= bound).sum(1)
            print(
                f"k={k}: within {bound}: >=1 companion {np.mean(within >= 1):.0%}, "
                f">=2 {np.mean(within >= 2):.0%}, median {np.median(within):.0f}"
            )

    k = args.k[0]
    d = distances[k]
    index = {picture: n for n, picture in enumerate(ids)}

    def near(anchor: str, k: int, count: int) -> tuple[list[str], list[float]]:
        row = distances[k][index[anchor]]
        order = np.argsort(row, kind="stable")[:count]
        return [ids[i] for i in order], [float(row[i]) for i in order]

    rows: list[Row] = []
    per_anchor = 1
    bound = None
    if args.mode == "letterbox":
        anchors = [picture for picture in ids if letterboxed(rgbs[picture])]
        print(f"letterboxed: {len(anchors)} of {len(ids)}: {' '.join(anchors)}")
        anchors = anchors[: args.anchors]
    else:
        anchors = list(rng.choice(ids, args.anchors, replace=False))
    for anchor in anchors:
        if args.mode in ("threshold", "letterbox"):
            rows.append((f"{len(rows) + 1}", anchor, *near(anchor, k, args.neighbours)))
            bound = args.max_distance
        elif args.mode == "k":
            per_anchor = len(args.k)
            rows += [(f"k{kk}", anchor, *near(anchor, kk, args.neighbours)) for kk in args.k]
        else:  # sets
            per_anchor, bound = 2, args.max_distance
            ranked, dist = near(anchor, k, len(ids) - 1)
            compatible = [(p, x) for p, x in zip(ranked, dist, strict=True) if x <= bound]
            beyond = [(p, x) for p, x in zip(ranked, dist, strict=True) if x > bound]
            shuffled = [compatible[i] for i in rng.permutation(len(compatible))]
            for label, pool in (("N", compatible), ("R", shuffled)):
                picked = (pool + beyond)[:2]
                rows.append((label, anchor, [p for p, _ in picked], [x for _, x in picked]))
    write_sheet(args.sheet, thumbs, rows, per_anchor, bound)
    logger.info("sheet: %s (%s, k=%d, bound %s)", args.sheet, args.mode, k, bound)


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
    if args.mode == "variants":
        variants_sheet(args, ids, thumbs)
        return
    if args.mode != "compare":
        calibrate(args, ids, thumbs)
        return

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
