#!/usr/bin/env python3
"""A swatch sheet of one palette in every tone: light full and soft, dark full and dim.

Each panel is the variant as `amo theme apply` renders it (amontillado.tone, then the contrast
check with the tone's pairs, as under theme.contrast: adjust): the ramp base00-base07, the
accents base08-base0F, text, a comment and the six ANSI accents on base01, each labelled with
its measured contrast, and under dim blue as a background under base05. Swatches only: the
picture is never drawn, so the sheet can go in docs/images/ (CONTRIBUTING.md, "Tests").

The palette needs both variants (`amo palette PICTURE > FILE`); the default is the current
profile's. Writes a 64-colour PNG.

  uv run tools/tone_sheet.py palette.yaml --title 3qz176 --out docs/images/tone-swatches.png
"""

from __future__ import annotations

import argparse
import sys
from logging import getLogger
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from rich.console import Console
from rich.logging import RichHandler

from amontillado.cli import HelpFormatter
from amontillado.colour import contrast_ratio
from amontillado.config import ConfigError, load_config
from amontillado.contrast import adjust
from amontillado.palette import BASE16_KEYS, PaletteError, Variant, load_palette
from amontillado.theme import PALETTE_FILE, current_profile, profile_dir
from amontillado.tone import FULL, TONES, checked_pairs, toned

logger = getLogger("tone_sheet")

PANEL_WIDTH = 520
PANEL_HEIGHT = 300
GAP = 8
PAD = 18
SWATCH = 52
# The six ANSI accents, as terminals name them.
ANSI = (
    ("red", "base08"),
    ("yellow", "base0A"),
    ("green", "base0B"),
    ("cyan", "base0C"),
    ("blue", "base0D"),
    ("magenta", "base0E"),
)


def get_cli_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=HelpFormatter)
    parser.add_argument(
        "--loglevel",
        "-l",
        default="INFO",
        type=lambda v: v.strip().upper(),
        help="Logging verbosity (DEBUG, INFO, WARNING, ERROR).",
    )
    parser.add_argument(
        "palette",
        nargs="?",
        type=Path,
        help="A palette file with both variants (default: the current profile's).",
    )
    parser.add_argument("--title", help="The sheet's title (default: the palette's name).")
    parser.add_argument("--out", type=Path, required=True, help="The PNG to write.")
    return parser.parse_args()


def setup_logger(args: argparse.Namespace) -> None:
    handler = RichHandler(level=args.loglevel, console=Console(stderr=True))
    logger.addHandler(handler)
    logger.setLevel(args.loglevel)


def _hex(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def made(variant: str, full: Variant, tone: str) -> Variant:
    """`full` in `tone`, as apply makes it (theme.contrast: adjust)."""
    if tone == FULL:
        return full
    result, failures = adjust(
        toned(variant, full, tone), f"{variant} ({tone})", checked_pairs(tone)
    )
    for failure in failures:
        logger.warning("%s (%s): %s", variant, tone, failure)
    return result


def panel(
    variant: str, tone: str, colours: Variant, fonts: dict[str, ImageFont.FreeTypeFont]
) -> Image.Image:
    b = colours.base24
    image = Image.new("RGB", (PANEL_WIDTH, PANEL_HEIGHT), _hex(b["base00"]))
    draw = ImageDraw.Draw(image)
    ratio = lambda fg, bg: contrast_ratio(b[fg], b[bg])  # noqa: E731
    y = PAD
    draw.text((PAD, y), f"{variant} {tone}", fill=_hex(b["base05"]), font=fonts["title"])
    draw.text(
        (PAD + 150, y + 4),
        f"text {ratio('base05', 'base00'):.1f}:1   comment {ratio('base03', 'base00'):.1f}:1",
        fill=_hex(b["base03"]),
        font=fonts["small"],
    )
    y += 40
    for row in (BASE16_KEYS[:8], BASE16_KEYS[8:]):
        for index, key in enumerate(row):
            x = PAD + index * (SWATCH + 9)
            draw.rectangle(
                (x, y, x + SWATCH, y + SWATCH), fill=_hex(b[key]), outline=_hex(b["base03"])
            )
            draw.text((x, y + SWATCH + 2), key[4:], fill=_hex(b["base04"]), font=fonts["small"])
        y += SWATCH + 22
    band = (PAD - 6, y - 4, PANEL_WIDTH - PAD + 6, y + 58)
    draw.rectangle(band, fill=_hex(b["base01"]))
    x = PAD
    for word, key in ANSI:
        label = f"{word} {ratio(key, 'base01'):.1f}"
        draw.text((x, y), label, fill=_hex(b[key]), font=fonts["body"])
        x += int(draw.textlength(label, font=fonts["body"])) + 12
    y += 30
    label = f"base04 on base01 {ratio('base04', 'base01'):.1f}:1"
    draw.text((PAD, y), label, fill=_hex(b["base04"]), font=fonts["body"])
    chip = f" base05 on blue {ratio('base05', 'base0D'):.1f}:1 "
    x = PAD + int(draw.textlength(label, font=fonts["body"])) + 24
    width = int(draw.textlength(chip, font=fonts["body"]))
    draw.rectangle((x, y - 2, x + width, y + 22), fill=_hex(b["base0D"]))
    draw.text((x, y), chip, fill=_hex(b["base05"]), font=fonts["body"])
    return image


def main() -> None:
    args = get_cli_arguments()
    setup_logger(args)
    path = args.palette
    if path is None:
        try:
            theme = load_config().theme
            path = profile_dir(theme, current_profile(theme)) / PALETTE_FILE
        except ConfigError as exc:
            sys.exit(f"tone_sheet: {exc}")
    try:
        palette = load_palette(path)
    except PaletteError as exc:
        sys.exit(f"tone_sheet: {exc}")
    missing = [variant for variant in TONES if variant not in palette.variants]
    if missing:
        sys.exit(f"tone_sheet: {path} has no {' or '.join(missing)} variant")
    fonts = {
        "title": ImageFont.load_default(size=24),
        "body": ImageFont.load_default(size=17),
        "small": ImageFont.load_default(size=13),
    }
    sheet = Image.new(
        "RGB", (2 * PANEL_WIDTH + 3 * GAP, 2 * PANEL_HEIGHT + 3 * GAP + 30), "#808080"
    )
    draw = ImageDraw.Draw(sheet)
    draw.text((GAP, GAP), args.title or palette.name, fill="#ffffff", font=fonts["body"])
    swatches = []
    for row, variant in enumerate(("light", "dark")):
        full = palette.variants[variant]
        for column, tone in enumerate(TONES[variant]):
            image = panel(variant, tone, made(variant, full, tone), fonts)
            left = GAP + column * (PANEL_WIDTH + GAP)
            top = 30 + GAP + row * (PANEL_HEIGHT + GAP)
            swatches += [
                (
                    left + PAD + index * (SWATCH + 9) + SWATCH // 2,
                    top + PAD + 40 + line * (SWATCH + 22) + SWATCH // 2,
                )
                for line in range(2)
                for index in range(8)
            ]
            sheet.paste(
                image, (GAP + column * (PANEL_WIDTH + GAP), 30 + GAP + row * (PANEL_HEIGHT + GAP))
            )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Swatches must keep their exact colours: a palette PNG only when it loses none of them.
    quantized = sheet.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
    exact = all(
        quantized.convert("RGB").getpixel(point) == sheet.getpixel(point) for point in swatches
    )
    (quantized if exact else sheet).save(args.out, optimize=True)
    if not exact:
        logger.info("a 256-colour palette would shift a swatch: writing full colour")
    logger.info("wrote %s", args.out)


if __name__ == "__main__":
    main()
