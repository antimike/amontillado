"""The preview card of a theme (experimental): each monitor's picture side by side, the primary
first, at its aspect and a common height, over a swatch strip of the palette as the screen would
show it (docs/design.md, "Saved looks: design", "The preview"). `amo theme preview` shows it and
`amo theme list --format rofi` gives one per row; both draw it here.

A card showing a non-sfw picture is cached in `$XDG_RUNTIME_DIR` (tmpfs: never backed up, gone
at logout), never in `$XDG_CACHE_HOME`: it copies the picture's pixels out of the NSFW root.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from amontillado.config import xdg_dir
from amontillado.contrast import apply_contrast
from amontillado.desktop import desktop_variant
from amontillado.palette import BASE16_KEYS, Palette
from amontillado.theme import choose_variant, toned_palette
from amontillado.tone import FULL, takes_tone

# The thumbnails' common height, in pixels (*initial*).
HEIGHT = 160
# Each strip row's height under the thumbnails.
ROW_HEIGHT = 24
# A card without pictures is as wide as one 16:9 picture, the strip filling it.
PRESET_WIDTH = round(HEIGHT * 16 / 9)
# Bump to drop every cached card when the drawing changes.
_DRAWING = 1


class PreviewError(Exception):
    """A preview cannot be drawn or kept; the message says why."""


@dataclass(frozen=True)
class Shown:
    """One monitor's picture: the file shown and the monitor's ratio (width / height)."""

    path: Path
    ratio: float


def strip(
    palette: Palette, variant: str, tones: Mapping[str, str], contrast: str
) -> list[list[str]]:
    """The strip's rows: base00-base0F of each variant the theme would apply (dark over light
    under system or auto, when the palette has both; else the one chosen), after the contrast
    check and in its tone, as `amo theme apply` renders them."""
    palette = apply_contrast(palette, contrast)
    if variant in ("system", "auto") and len(palette.variants) == 2:
        variants = ["dark", "light"]
    else:
        wanted = desktop_variant() if variant == "system" else variant
        variants = [choose_variant(palette, wanted)]
    rows = []
    for name in variants:
        tone = tones.get(name, FULL) if takes_tone(palette) else FULL
        toned = toned_palette(palette, name, tone, contrast)
        rows.append([toned.variants[name].base24[key] for key in BASE16_KEYS])
    return rows


def card(pictures: Sequence[Shown], rows: Sequence[Sequence[str]]) -> Image.Image:
    """The card: the thumbnails over the strip, or the strip alone filling a preset's card."""
    widths = [max(1, round(HEIGHT * shown.ratio)) for shown in pictures]
    if pictures:
        width, top = sum(widths), HEIGHT
        row_height = ROW_HEIGHT
    else:
        width, top = PRESET_WIDTH, 0
        row_height = (HEIGHT + ROW_HEIGHT * len(rows)) // max(len(rows), 1)
    image = Image.new("RGB", (width, top + row_height * len(rows)), "black")
    x = 0
    for shown, thumb_width in zip(pictures, widths, strict=True):
        try:
            with Image.open(shown.path) as picture:
                picture.draft("RGB", (thumb_width * 2, HEIGHT * 2))
                thumb = ImageOps.fit(picture.convert("RGB"), (thumb_width, HEIGHT))
        except OSError as exc:
            raise PreviewError(f"{shown.path}: {exc}") from exc
        image.paste(thumb, (x, 0))
        x += thumb_width
    draw = ImageDraw.Draw(image)
    for index, colours in enumerate(rows):
        y = top + index * row_height
        for column, colour in enumerate(colours):
            left = column * width // len(colours)
            right = (column + 1) * width // len(colours)
            draw.rectangle((left, y, right - 1, y + row_height - 1), fill=colour)
    return image


def key(pictures: Sequence[Shown], rows: Sequence[Sequence[str]]) -> str:
    """What the card shows, hashed: each file (path, size, modification time) and ratio, and
    the strip's colours."""
    shown = []
    for item in pictures:
        stat = item.path.stat()
        shown.append([str(item.path), stat.st_size, stat.st_mtime_ns, round(item.ratio, 6)])
    data = json.dumps([_DRAWING, HEIGHT, ROW_HEIGHT, shown, [list(row) for row in rows]])
    return hashlib.sha256(data.encode()).hexdigest()


def cache_dir(*, private: bool) -> Path:
    """Where cards are kept: the runtime dir for one showing a non-sfw picture."""
    if not private:
        return xdg_dir("XDG_CACHE_HOME", ".cache") / "amontillado" / "previews"
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        raise PreviewError(
            "XDG_RUNTIME_DIR is not set: a preview of a non-sfw picture is kept only there "
            "(-o FILE writes one where you say)"
        )
    return Path(runtime) / "amontillado" / "previews"


def cached(pictures: Sequence[Shown], rows: Sequence[Sequence[str]], *, private: bool) -> Path:
    """The card's PNG, drawn once and kept by `key`. Raises PreviewError."""
    directory = cache_dir(private=private)
    try:
        path = directory / f"{key(pictures, rows)}.png"
    except OSError as exc:
        raise PreviewError(str(exc)) from exc
    if path.is_file():
        return path
    image = card(pictures, rows)
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        partial = path.with_name(f".{path.name}.part")
        image.save(partial, "PNG")
        partial.replace(path)
    except OSError as exc:
        raise PreviewError(f"{path}: {exc}") from exc
    return path
