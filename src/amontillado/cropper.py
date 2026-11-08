"""Placing a crop by hand: `amo crop --interactive`.

docs/design.md, "Crops". The picture is shown with the crop box drawn on it; keys move the box
along both axes and zoom it (a smaller box of the same ratio, never past the picture); Enter
takes the box, Esc takes none. The keys drive a pure state machine (`press`), so everything but
the terminal itself is tested without one. The preview is drawn in the terminal with the kitty
graphics protocol, or written to a file an image viewer shows (`crop.preview`).
"""

from __future__ import annotations

import base64
import contextlib
import fcntl
import io
import os
import select
import struct
import subprocess
import sys
import termios
import tty
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from logging import getLogger
from pathlib import Path
from typing import BinaryIO, Protocol, TextIO

from PIL import Image, ImageDraw, ImageEnhance, ImageOps

from amontillado.config import CropConfig, xdg_dir
from amontillado.library import Box, Choose, crop_box

logger = getLogger(__name__)

# An arrow moves the box by this share of its own size; shifted (or HJKL), by the larger one.
MOVE_STEP = 0.05
BIG_STEP = 0.25
# + and - multiply the box's scale by this, or divide it.
ZOOM_STEP = 0.9
# The smallest box, as a share of the largest (*initial*).
MIN_SCALE = 0.1
# The preview's longest side, in pixels: enough for a terminal or a viewer window.
PREVIEW_SIDE = 1600
# Outside the box the preview is darkened to this brightness.
DIM = 0.35
# A lone Esc is told from the start of an escape sequence by waiting this long (seconds) for
# more.
ESCAPE_WAIT = 0.05

ACCEPT = "accept"
CANCEL = "cancel"
_MOVES = {
    "left": (-MOVE_STEP, 0.0),
    "right": (MOVE_STEP, 0.0),
    "up": (0.0, -MOVE_STEP),
    "down": (0.0, MOVE_STEP),
    "Left": (-BIG_STEP, 0.0),
    "Right": (BIG_STEP, 0.0),
    "Up": (0.0, -BIG_STEP),
    "Down": (0.0, BIG_STEP),
}
HELP = "arrows/hjkl move (shift: more)  +/- zoom  0 reset  Enter crop  Esc cancel"


@dataclass(frozen=True)
class State:
    """Where the box is: its scale (of the largest box of the ratio) and its centre, in
    picture pixels, unrounded so that zooming in and out again comes back to the same box."""

    width: int
    height: int
    ratio: float
    scale: float = 1.0
    # None: the picture's centre.
    centre: tuple[float, float] | None = None

    @property
    def size(self) -> tuple[int, int]:
        _, _, box_width, box_height = crop_box(self.width, self.height, self.ratio, 0.5, self.scale)
        return box_width, box_height

    @property
    def box(self) -> Box:
        box_width, box_height = self.size
        centre_x, centre_y = self.centre or (self.width / 2, self.height / 2)
        x = min(max(centre_x - box_width / 2, 0), self.width - box_width)
        y = min(max(centre_y - box_height / 2, 0), self.height - box_height)
        return round(x), round(y), box_width, box_height

    def clamped(self) -> State:
        """The same box with its centre where the box is: no hidden offset past an edge."""
        box_width, box_height = self.size
        centre_x, centre_y = self.centre or (self.width / 2, self.height / 2)
        exact_x = min(max(centre_x, box_width / 2), self.width - box_width / 2)
        exact_y = min(max(centre_y, box_height / 2), self.height - box_height / 2)
        return replace(self, centre=(exact_x, exact_y))


def start(width: int, height: int, ratio: float, box: Box) -> State:
    """The state showing `box`, a largest box of `ratio` (as `amo crop --at` places it)."""
    x, y, box_width, box_height = box
    return State(width, height, ratio, centre=(x + box_width / 2, y + box_height / 2))


def press(state: State, key: str) -> State | str:
    """The state after `key`, or ACCEPT or CANCEL. Keys: left, right, up, down (and Left ...
    for a larger step), in, out, reset, enter, cancel; any other leaves the state as it is."""
    if key == "enter":
        return ACCEPT
    if key == "cancel":
        return CANCEL
    if key == "reset":
        return State(state.width, state.height, state.ratio)
    box_width, box_height = state.size
    centre_x, centre_y = state.clamped().centre  # type: ignore[misc]
    if key in _MOVES:
        step_x, step_y = _MOVES[key]
        moved = (centre_x + step_x * box_width, centre_y + step_y * box_height)
        return replace(state, centre=moved).clamped()
    if key in ("in", "out"):
        # About the box's centre; zooming out at an edge pushes the box back inside.
        factor = ZOOM_STEP if key == "in" else 1 / ZOOM_STEP
        scale = min(max(state.scale * factor, MIN_SCALE), 1.0)
        return replace(state, scale=scale, centre=(centre_x, centre_y)).clamped()
    return state


def status(state: State, label: str) -> str:
    x, y, box_width, box_height = state.box
    return (
        f"{label.replace('x', ':')} {box_width}x{box_height} at {x},{y} ({state.scale:.0%})  {HELP}"
    )


# Escape sequences and keys, as a terminal in cbreak mode sends them.
SEQUENCES = {
    b"\x1b[A": "up",
    b"\x1b[B": "down",
    b"\x1b[C": "right",
    b"\x1b[D": "left",
    b"\x1bOA": "up",
    b"\x1bOB": "down",
    b"\x1bOC": "right",
    b"\x1bOD": "left",
    b"\x1b[1;2A": "Up",
    b"\x1b[1;2B": "Down",
    b"\x1b[1;2C": "Right",
    b"\x1b[1;2D": "Left",
}
CHARACTERS = {
    b"h": "left",
    b"j": "down",
    b"k": "up",
    b"l": "right",
    b"H": "Left",
    b"J": "Down",
    b"K": "Up",
    b"L": "Right",
    b"+": "in",
    b"=": "in",
    b"-": "out",
    b"_": "out",
    b"0": "reset",
    b"\r": "enter",
    b"\n": "enter",
    b"q": "cancel",
    b"\x1b": "cancel",
    # Ctrl-C: cbreak mode keeps signals, but a raw terminal would send this.
    b"\x03": "cancel",
}


def decode(data: bytes) -> tuple[str | None, bytes]:
    """The first key in `data` (not empty), by its name as `press` takes it (None for one it
    does not know), and the bytes after it. A lone Esc is `cancel`; an escape sequence it does
    not know (a CSI sequence, an SS3 key, Alt with a key) is consumed whole."""
    if data[:1] != b"\x1b" or len(data) == 1:
        return CHARACTERS.get(data[:1]), data[1:]
    for sequence in sorted(SEQUENCES, key=len, reverse=True):
        if data.startswith(sequence):
            return SEQUENCES[sequence], data[len(sequence) :]
    if data[1:2] == b"[":
        # Parameters, then one final byte in @ to ~.
        for index in range(2, len(data)):
            if 0x40 <= data[index] <= 0x7E:
                return None, data[index + 1 :]
        return None, b""
    return None, data[3:] if data[1:2] == b"O" else data[2:]


def keys(fd: int, wait: float = ESCAPE_WAIT) -> Iterator[str]:
    """Every key read from `fd` that `press` knows, until the end of input (which cancels).
    Keys typed quickly may arrive in one read; an Esc alone waits `wait` for the rest of a
    sequence before it counts as Esc."""
    buffer = b""
    while True:
        if not buffer:
            buffer = os.read(fd, 64)
            if not buffer:
                yield "cancel"
                return
        if buffer == b"\x1b" and select.select([fd], [], [], wait)[0]:
            buffer += os.read(fd, 64)
        key, buffer = decode(buffer)
        if key is not None:
            yield key


class Preview:
    """The picture scaled down once, and each frame drawn from it: the box at full brightness
    and outlined, the rest darkened."""

    def __init__(self, path: Path, width: int, height: int, side: int = PREVIEW_SIDE) -> None:
        with Image.open(path) as image:
            picture = ImageOps.exif_transpose(image).convert("RGB")
        picture.thumbnail((side, side))
        self.picture = picture
        self.dimmed = ImageEnhance.Brightness(picture).enhance(DIM)
        self.factor = picture.width / width

    def frame(self, box: Box) -> Image.Image:
        x, y, box_width, box_height = (round(value * self.factor) for value in box)
        right, bottom = x + max(box_width, 1), y + max(box_height, 1)
        frame = self.dimmed.copy()
        frame.paste(self.picture.crop((x, y, right, bottom)), (x, y))
        ImageDraw.Draw(frame).rectangle((x, y, right - 1, bottom - 1), outline="white", width=2)
        return frame


class Renderer(Protocol):
    def show(self, frame: Image.Image, text: str) -> None: ...

    def close(self) -> None: ...


def kitty_terminal(environ: Mapping[str, str]) -> bool:
    """Whether the environment names a terminal that speaks the kitty graphics protocol."""
    return (
        bool(environ.get("KITTY_WINDOW_ID"))
        or environ.get("TERM") in ("xterm-kitty", "xterm-ghostty")
        or environ.get("TERM_PROGRAM") in ("WezTerm", "ghostty")
    )


def preview_mode(config: CropConfig, environ: Mapping[str, str] = os.environ) -> str:
    """kitty or viewer, from `crop.preview`."""
    if config.preview != "auto":
        return config.preview
    return "kitty" if kitty_terminal(environ) else "viewer"


# The kitty graphics protocol's payload is sent in chunks of at most 4096 base64 bytes.
_CHUNK = 4096
_IMAGE_ID = 1


def kitty_image(png: bytes, placement: str) -> bytes:
    """The escape sequences that transmit and show `png` as image 1 (`placement` sizes it in
    cells: `c=COLUMNS` or `r=ROWS`), the cursor kept where it is, no reply wanted."""
    data = base64.standard_b64encode(png)
    chunks = [data[i : i + _CHUNK] for i in range(0, len(data), _CHUNK)] or [b""]
    out = []
    for index, chunk in enumerate(chunks):
        more = int(index < len(chunks) - 1)
        if index == 0:
            control = f"a=T,f=100,i={_IMAGE_ID},q=2,C=1,{placement},m={more}"
        else:
            control = f"m={more}"
        out.append(b"\x1b_G" + control.encode() + b";" + chunk + b"\x1b\\")
    return b"".join(out)


KITTY_DELETE = f"\x1b_Ga=d,d=I,i={_IMAGE_ID},q=2\x1b\\".encode()


def _cells(fd: int) -> tuple[int, int, float]:
    """The terminal's columns, rows and cell aspect (width / height; 0.5 if not reported)."""
    try:
        rows, columns, x_pixels, y_pixels = struct.unpack(
            "HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8)
        )
    except OSError:
        size = os.get_terminal_size(fd)
        return size.columns, size.lines, 0.5
    aspect = (x_pixels / columns) / (y_pixels / rows) if x_pixels and y_pixels else 0.5
    return columns, rows, aspect


def placement(columns: int, rows: int, cell_aspect: float, image_aspect: float) -> str:
    """The cell size that fits an image of `image_aspect` (width / height) in `columns` x
    `rows`: its full width if that fits, else its full height. kitty computes the other."""
    needed_rows = columns * cell_aspect / image_aspect
    return f"c={columns}" if needed_rows <= rows else f"r={rows}"


class KittyRenderer:
    """The preview drawn in the terminal on `out` (the terminal's fd `fd`), in its alternate
    screen, the status on the last line."""

    def __init__(self, out: BinaryIO, fd: int) -> None:
        self.out, self.fd = out, fd
        self.out.write(b"\x1b[?1049h\x1b[?25l")

    def show(self, frame: Image.Image, text: str) -> None:
        columns, rows, cell_aspect = _cells(self.fd)
        png = io.BytesIO()
        frame.save(png, "PNG", compress_level=1)
        where = placement(columns, rows - 1, cell_aspect, frame.width / frame.height)
        self.out.write(KITTY_DELETE + b"\x1b[H" + kitty_image(png.getvalue(), where))
        self.out.write(f"\x1b[{rows};1H\x1b[2K{text[: columns - 1]}".encode())
        self.out.flush()

    def close(self) -> None:
        self.out.write(KITTY_DELETE + b"\x1b[?25h\x1b[?1049l")
        self.out.flush()


def preview_path() -> Path:
    return xdg_dir("XDG_CACHE_HOME", ".cache") / "amontillado" / "crop-preview.png"


class ViewerRenderer:
    """The preview written to `path` after each key (atomically), shown by `command` (a command
    line for `sh -c`, with AMO_FILE the preview file), started at the first frame; the status
    on `status`."""

    def __init__(
        self,
        command: str,
        path: Path,
        status: TextIO,
        start: Callable[[list[str], dict[str, str]], object] | None = None,
    ) -> None:
        self.command, self.path, self.status = command, path, status
        self.start = start or _start_viewer
        self.started = False

    def show(self, frame: Image.Image, text: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        partial = self.path.with_name(f".{self.path.name}.part")
        frame.save(partial, "PNG", compress_level=1)
        partial.replace(self.path)
        if not self.started:
            self.start(["sh", "-c", self.command], {**os.environ, "AMO_FILE": str(self.path)})
            self.started = True
        self.status.write(f"\r\x1b[2K{text}")
        self.status.flush()

    def close(self) -> None:
        self.status.write("\r\x1b[2K")
        self.status.flush()
        self.path.unlink(missing_ok=True)


def _start_viewer(command: list[str], env: dict[str, str]) -> object:
    try:
        return subprocess.Popen(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise OSError(f"crop.viewer: {exc}") from exc


def place(
    preview: Preview, state: State, label: str, renderer: Renderer, presses: Iterator[str]
) -> Box | None:
    """Show `state` and apply each key of `presses` until Enter (the box) or Esc (None)."""
    try:
        while True:
            renderer.show(preview.frame(state.box), status(state, label))
            outcome = press(state, next(presses, "cancel"))
            if outcome == ACCEPT:
                return state.box
            if outcome == CANCEL:
                return None
            state = outcome  # type: ignore[assignment]
    finally:
        renderer.close()


@contextlib.contextmanager
def _cbreak(fd: int) -> Iterator[None]:
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def chooser(config: CropConfig, ratio: float, label: str) -> Choose:
    """The `choose` for crop_picture: the terminal on stdin (keys) and stderr (the preview,
    or the status beside a viewer), so stdout still carries only the crop's path."""

    def choose(path: Path, width: int, height: int, box: Box) -> Box | None:
        preview = Preview(path, width, height)
        state = start(width, height, ratio, box)
        fd = sys.stdin.fileno()
        with _cbreak(fd):
            if preview_mode(config) == "kitty":
                renderer: Renderer = KittyRenderer(sys.stderr.buffer, sys.stderr.fileno())
            else:
                renderer = ViewerRenderer(config.viewer, preview_path(), sys.stderr)
            return place(preview, state, label, renderer, keys(fd))

    return choose
