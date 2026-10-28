#!/usr/bin/env python3
"""Calibrate the class thresholds on a random Wallhaven sample.

Two steps, so the analysis can be rerun offline (after a metric changes, say):

  sample   fetch random sfw search results: each `large` thumbnail, the result's fields and
           its tag objects (from /w/<id>), and for the first --full results the metrics of the
           full image (downloaded, measured, not kept). Resumable: ids already sampled are
           skipped.
  report   measure every saved thumbnail and print each metric's distribution, the share of
           the sample in each class under the thresholds in classes.py, how far thumbnail
           metrics stray from full-image ones, and how often fixed hue sectors split one hue.

The sample directory holds Wallhaven images and responses: keep it out of the repository.

  uv run tools/calibrate.py sample ~/.local/state/amontillado/calibration --count 400
  uv run tools/calibrate.py report ~/.local/state/amontillado/calibration
"""

from __future__ import annotations

import argparse
import io
import json
import math
import sys
from logging import getLogger
from pathlib import Path

import numpy as np
from rich.console import Console
from rich.logging import RichHandler

from amontillado import classes
from amontillado.cli import HelpFormatter
from amontillado.colour import srgb_to_oklch
from amontillado.metrics import CHROMATIC_MIN, Metrics, load_rgb, measure, measure_file
from amontillado.wallhaven import Client, Search, WallhavenError

logger = getLogger("calibrate")

SAMPLE_FILE = "sample.jsonl"
THUMBS = "thumbs"
METRIC_NAMES = (
    "lightness",
    "chroma",
    "colourful_share",
    "hue_share",
    "hue_spread",
    "warmth",
    "busy",
)
PERCENTILES = (5, 10, 25, 50, 75, 90, 95)


def get_cli_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=HelpFormatter)
    parser.add_argument(
        "--loglevel",
        "-l",
        default="INFO",
        type=lambda v: v.strip().upper(),
        help="Logging verbosity (DEBUG, INFO, WARNING, ERROR).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sample = sub.add_parser("sample", help="fetch a random sample", formatter_class=HelpFormatter)
    sample.add_argument("directory", type=Path, help="where the sample is kept")
    sample.add_argument("--count", type=int, default=400, help="sample size to reach")
    sample.add_argument("--full", type=int, default=40, help="results also measured in full")
    report = sub.add_parser("report", help="analyse a sample", formatter_class=HelpFormatter)
    report.add_argument("directory", type=Path, help="where the sample is kept")
    return parser.parse_args()


def setup_logger(args: argparse.Namespace) -> None:
    logger.addHandler(RichHandler(level=args.loglevel, console=Console(stderr=True)))
    logger.setLevel(args.loglevel)


def load_sample(directory: Path) -> list[dict]:
    path = directory / SAMPLE_FILE
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def cmd_sample(args: argparse.Namespace) -> None:
    thumbs = args.directory / THUMBS
    thumbs.mkdir(parents=True, exist_ok=True)
    sample = load_sample(args.directory)
    seen = {entry["id"] for entry in sample}
    full_done = sum("full_metrics" in entry for entry in sample)
    client = Client()
    with (args.directory / SAMPLE_FILE).open("a") as out:
        for wallpaper in client.search(Search()):
            if len(seen) >= args.count:
                break
            if wallpaper.id in seen:
                continue
            try:
                thumbnail = client.download(wallpaper.thumbnail)
                # Client.tags keeps names only; amo-0z2 wants alias and category too.
                data = client._api(f"/w/{wallpaper.id}", {}).get("data") or {}
                entry = {
                    "id": wallpaper.id,
                    "category": wallpaper.category,
                    "width": wallpaper.width,
                    "height": wallpaper.height,
                    "colors": list(wallpaper.colors),
                    "tags": [
                        {key: tag.get(key) for key in ("name", "alias", "category")}
                        for tag in data.get("tags") or ()
                    ],
                }
                if full_done < args.full:
                    image = client.download(wallpaper.image_url)
                    entry["full_metrics"] = measure_file(io.BytesIO(image)).to_dict()
                    full_done += 1
            except WallhavenError as exc:
                logger.warning("%s: %s", wallpaper.id, exc)
                continue
            (thumbs / f"{wallpaper.id}.jpg").write_bytes(thumbnail)
            out.write(json.dumps(entry) + "\n")
            out.flush()
            seen.add(wallpaper.id)
            logger.info("%d/%d %s", len(seen), args.count, wallpaper.id)
    if len(seen) < args.count:
        sys.exit(f"calibrate: the search ended at {len(seen)} results")


def window_share(rgb: np.ndarray, half_width: float) -> float:
    """Share of chromatic weight within ±half_width degrees of the mean hue."""
    _, chroma, hue = srgb_to_oklch(rgb)
    chromatic = chroma > CHROMATIC_MIN
    hue, weight = hue[chromatic], chroma[chromatic]
    if weight.sum() == 0:
        return 0.0
    radians = np.radians(hue)
    mean = math.degrees(
        math.atan2((weight * np.sin(radians)).sum(), (weight * np.cos(radians)).sum())
    )
    distance = np.abs((hue - mean + 180.0) % 360.0 - 180.0)
    return float(weight[distance <= half_width].sum() / weight.sum())


def cmd_report(args: argparse.Namespace) -> None:
    sample = load_sample(args.directory)
    if not sample:
        sys.exit(f"calibrate: no sample in {args.directory}")
    rows: list[tuple[dict, Metrics, np.ndarray]] = []
    for entry in sample:
        rgb = load_rgb(args.directory / THUMBS / f"{entry['id']}.jpg")
        rows.append((entry, measure(rgb), rgb))
    n = len(rows)
    print(f"sample: {n} thumbnails")
    categories = {}
    for entry, _, _ in rows:
        categories[entry["category"]] = categories.get(entry["category"], 0) + 1
    print("categories:", ", ".join(f"{k} {v}" for k, v in sorted(categories.items())))

    print("\npercentiles (thumbnails):")
    print(f"{'metric':<16}" + "".join(f"{f'p{p}':>8}" for p in PERCENTILES))
    for name in METRIC_NAMES:
        values = np.array([getattr(m, name) for _, m, _ in rows])
        print(f"{name:<16}" + "".join(f"{v:>8.3f}" for v in np.percentile(values, PERCENTILES)))

    print("\nclass shares (current thresholds):")
    for name, rule in classes.CLASSES.items():
        share = sum(rule(m) for _, m, _ in rows) / n
        print(f"  {name:<12}{share:6.1%}")
    hues = {}
    for _, m, _ in rows:
        for hue in classes.classify(m):
            if hue not in classes.CLASSES:
                hues[hue] = hues.get(hue, 0) + 1
    print("  hues:", ", ".join(f"{k} {v / n:.1%}" for k, v in sorted(hues.items())))

    print("\nhue sectors splitting one hue (hue_spread < 0.30):")
    narrow = [(m, rgb) for _, m, rgb in rows if m.hue_name is not None and m.hue_spread < 0.30]
    split = [m for m, _ in narrow if m.hue_share < classes.HUE_SHARE_MIN]
    print(f"  {len(narrow)} narrow-hued, {len(split)} with hue_share < {classes.HUE_SHARE_MIN}")
    for half_width in (20, 30, 40):
        shares = np.array([window_share(rgb, half_width) for _, _, rgb in rows])
        print(
            f"  window ±{half_width}°: p25/p50/p75 "
            + "/".join(f"{v:.2f}" for v in np.percentile(shares, (25, 50, 75)))
            + f", narrow-hued below {classes.HUE_SHARE_MIN}: "
            + str(sum(window_share(rgb, half_width) < classes.HUE_SHARE_MIN for _, rgb in narrow))
        )

    full = [(Metrics.from_dict(e["full_metrics"]), m) for e, m, _ in rows if "full_metrics" in e]
    if full:
        print(
            f"\nthumbnail minus full image ({len(full)} pairs): "
            "median difference, median and p90 of |difference|"
        )
        for name in METRIC_NAMES:
            diff = np.array([getattr(t, name) - getattr(f, name) for f, t in full])
            print(
                f"  {name:<16}{np.median(diff):+8.3f}{np.median(np.abs(diff)):8.3f}"
                f"{np.percentile(np.abs(diff), 90):8.3f}"
            )


def main() -> None:
    args = get_cli_arguments()
    setup_logger(args)
    {"sample": cmd_sample, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
