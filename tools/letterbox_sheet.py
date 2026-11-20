#!/usr/bin/env python3
"""Contact sheets for calibrating letterbox detection (amontillado.letterbox; amo-5o8).

Two steps:

  sample  search Wallhaven (sfw) for each --query and keep the results' thumbnails, in the
          calibration sample's layout (sample.jsonl, thumbs/), so a sheet can take this sample
          beside the random one (tools/calibrate.py). Resumable: ids already kept are skipped.
  sheet   run the shipped detector on every thumbnail of the samples given and draw two
          sheets: the pictures it calls letterboxed (the content box framed green), and the
          near misses (bars on both ends rejected for a dark middle, or bars on one end, or
          both ends too thin), each labelled with its measurements. Prints a table of both.

Labels: the axis (rows: a letterbox; columns: a pillarbox), the bars at each end as a share of
the side, and the share of the content's middle third as dark as a bar (dm).

The samples hold Wallhaven images: keep them, and the sheets, outside the repository.

  uv run tools/letterbox_sheet.py sample ~/.local/state/amontillado/letterbox \\
      --query "film stills" --query "movie scenes" --count 60
  uv run tools/letterbox_sheet.py sheet ~/.local/state/amontillado/calibration \\
      ~/.local/state/amontillado/letterbox --out /tmp/letterbox
"""

from __future__ import annotations

import argparse
import io
import json
from logging import getLogger
from pathlib import Path

from PIL import Image, ImageDraw
from rich.console import Console
from rich.logging import RichHandler

from amontillado import letterbox
from amontillado.cli import HelpFormatter
from amontillado.colour import srgb_to_oklab
from amontillado.metrics import load_rgb
from amontillado.wallhaven import Client, Search, WallhavenError

logger = getLogger("letterbox_sheet")

TILE_WIDTH = 288
TILE_HEIGHT = 162
GAP = 6
COLUMNS = 5
LABEL = 16


def get_cli_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=HelpFormatter)
    parser.add_argument(
        "--loglevel",
        "-l",
        default="INFO",
        type=lambda v: v.strip().upper(),
        help="Logging verbosity (DEBUG, INFO, WARNING, ERROR).",
    )
    sub = parser.add_subparsers(dest="step", required=True)
    sample = sub.add_parser("sample", help="keep search results' thumbnails")
    sample.add_argument("directory", type=Path, help="where the sample is kept")
    sample.add_argument("--query", action="append", required=True, help="a Wallhaven query")
    sample.add_argument("--count", type=int, default=60, help="results per query")
    sheet = sub.add_parser("sheet", help="draw the detector's verdicts")
    sheet.add_argument("samples", type=Path, nargs="+", help="sample directories")
    sheet.add_argument("--out", type=Path, required=True, help="prefix of the PNG sheets")
    sheet.add_argument("--limit", type=int, default=40, help="tiles per sheet at most")
    return parser.parse_args()


def setup_logger(args: argparse.Namespace) -> None:
    logger.addHandler(RichHandler(level=args.loglevel, console=Console(stderr=True)))
    logger.setLevel(args.loglevel)


def sample(args: argparse.Namespace) -> None:
    thumbs = args.directory / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    listing = args.directory / "sample.jsonl"
    seen = set()
    if listing.exists():
        seen = {json.loads(line)["id"] for line in listing.read_text().splitlines()}
    client = Client(None)
    with listing.open("a") as out:
        for query in args.query:
            kept = 0
            try:
                for wallpaper in client.search(Search(query=query)):
                    if kept >= args.count:
                        break
                    kept += 1
                    if wallpaper.id in seen:
                        continue
                    data = client.download(wallpaper.thumbnail)
                    rgb = load_rgb(io.BytesIO(data))
                    Image.fromarray(rgb).save(thumbs / f"{wallpaper.id}.jpg", quality=92)
                    record = {"id": wallpaper.id, "query": query, "url": wallpaper.url}
                    out.write(json.dumps(record) + "\n")
                    out.flush()
                    seen.add(wallpaper.id)
            except WallhavenError as exc:
                logger.warning("%s: %s", query, exc)
            logger.info("%s: %d results", query, kept)


Verdict = tuple[str, Path, letterbox.Features, letterbox.Features, letterbox.Bars | None]


def _verdicts(samples: list[Path]) -> list[Verdict]:
    verdicts = []
    for directory in samples:
        for line in (directory / "sample.jsonl").read_text().splitlines():
            picture = json.loads(line)["id"]
            thumb = directory / "thumbs" / f"{picture}.jpg"
            if not thumb.exists():
                continue
            lightness = srgb_to_oklab(load_rgb(thumb))[..., 0]
            rows, columns = letterbox.features(lightness)
            verdicts.append((picture, thumb, rows, columns, letterbox.find_bars(lightness)))
    return verdicts


def _near(features: letterbox.Features) -> bool:
    """Bars on one end at least, or on both but rejected or too thin."""
    least = max(1, round(letterbox.MIN_BAR * features.length))
    return not features.bars and max(features.start, features.end) >= least


def _label(features: letterbox.Features) -> str:
    dark = "-" if features.dark_middle is None else f"{features.dark_middle:.2f}"
    return (
        f"{features.axis[0]} {features.start / features.length:.0%}/"
        f"{features.end / features.length:.0%} dm {dark}"
    )


def _tile(verdict: Verdict) -> Image.Image:
    picture, thumb, rows, columns, bars = verdict
    image = Image.open(thumb).convert("RGB")
    width, height = image.size
    scale_x, scale_y = TILE_WIDTH / width, TILE_HEIGHT / height
    tile = image.resize((TILE_WIDTH, TILE_HEIGHT))
    draw = ImageDraw.Draw(tile)
    if bars is not None:
        shown = rows if bars.top else columns
    elif (_thick(rows) and rows.dark_middle is not None) or (_near(rows) and not _thick(columns)):
        shown = rows
    else:
        shown = columns
    if bars is not None:
        x, y, w, h = bars.content(width, height)
        box = (x * scale_x, y * scale_y, (x + w) * scale_x - 1, (y + h) * scale_y - 1)
        draw.rectangle(box, outline="#1a9641", width=3)
    else:
        # The bars found, in red: where the edge runs end.
        if shown.axis == "rows":
            for y in (shown.start, height - shown.end):
                draw.line((0, y * scale_y, TILE_WIDTH, y * scale_y), fill="#d7191c", width=2)
        else:
            for x in (shown.start, width - shown.end):
                draw.line((x * scale_x, 0, x * scale_x, TILE_HEIGHT), fill="#d7191c", width=2)
    framed = Image.new("RGB", (TILE_WIDTH, TILE_HEIGHT + LABEL), "white")
    framed.paste(tile, (0, LABEL))
    ImageDraw.Draw(framed).text((4, 2), f"{picture}  {_label(shown)}", fill="black")
    return framed


def _sheet(path: Path, verdicts: list[Verdict]) -> None:
    rows = max(1, -(-len(verdicts) // COLUMNS))
    sheet = Image.new(
        "RGB", (COLUMNS * (TILE_WIDTH + GAP), rows * (TILE_HEIGHT + LABEL + GAP)), "white"
    )
    for n, verdict in enumerate(verdicts):
        row, column = divmod(n, COLUMNS)
        sheet.paste(
            _tile(verdict), (column * (TILE_WIDTH + GAP), row * (TILE_HEIGHT + LABEL + GAP))
        )
    sheet.save(path)
    logger.info("sheet: %s (%d pictures)", path, len(verdicts))


def sheet(args: argparse.Namespace) -> None:
    verdicts = _verdicts(args.samples)
    found = [v for v in verdicts if v[4] is not None]
    near = [v for v in verdicts if v[4] is None and (_near(v[2]) or _near(v[3]))]
    # Bars thick enough on both ends of an axis, rejected only for a dark middle.
    dark = [v for v in near if any(f.dark_middle is not None and _thick(f) for f in v[2:4])]
    thin = [v for v in near if v not in dark]
    print(
        f"{len(verdicts)} pictures: {len(found)} letterboxed; near misses: {len(dark)} with a "
        f"dark middle, {len(thin)} with thin or one-sided bars"
    )
    for title, group in (("letterboxed", found), ("dark", dark), ("thin", thin)):
        for picture, _, rows, columns, _ in group:
            print(f"{title:12} {picture:8} {_label(rows):24} {_label(columns)}")

    def darkness(verdict: Verdict) -> float:
        values = [f.dark_middle for f in verdict[2:4] if f.dark_middle is not None]
        return min(values, default=2.0)

    for name, group in (("found", found), ("dark", dark), ("thin", thin)):
        path = args.out.with_name(f"{args.out.name}-{name}.png")
        _sheet(path, sorted(group, key=darkness)[: args.limit])


def _thick(features: letterbox.Features) -> bool:
    least = max(1, round(letterbox.MIN_BAR * features.length))
    return min(features.start, features.end) >= least


def main() -> None:
    args = get_cli_arguments()
    setup_logger(args)
    if args.step == "sample":
        sample(args)
    else:
        sheet(args)


if __name__ == "__main__":
    main()
