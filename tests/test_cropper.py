from __future__ import annotations

import base64
import fcntl
import io
import os
import re
import struct
import termios
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from amontillado.config import CropConfig
from amontillado.cropper import (
    ACCEPT,
    CANCEL,
    KITTY_DELETE,
    MIN_SCALE,
    KittyRenderer,
    Preview,
    State,
    ViewerRenderer,
    decode,
    keys,
    kitty_image,
    place,
    placement,
    press,
    preview_mode,
    start,
    status,
)
from amontillado.library import crop_box


def _state(box: tuple[int, int, int, int] | None = None) -> State:
    # A 2000x1000 picture, a 1:1 box: 1000 pixels of room across, none down at scale 1.
    return start(2000, 1000, 1.0, box or crop_box(2000, 1000, 1.0, 0.5))


def _pressed(state: State, *names: str) -> State:
    for name in names:
        outcome = press(state, name)
        assert isinstance(outcome, State)
        state = outcome
    return state


def test_start_shows_the_box_it_was_given() -> None:
    for at in (0.0, 0.3, 1.0):
        box = crop_box(2000, 1000, 1.0, at)
        assert _state(box).box == box


def test_moves_are_a_share_of_the_box_and_stay_inside() -> None:
    state = _state()
    assert state.box == (500, 0, 1000, 1000)
    assert _pressed(state, "right").box == (550, 0, 1000, 1000)
    assert _pressed(state, "Left").box == (250, 0, 1000, 1000)
    # No room down at full size; the place across is kept.
    assert _pressed(state, "down", "Down").box == (500, 0, 1000, 1000)
    assert _pressed(state, *["Right"] * 5).box == (1000, 0, 1000, 1000)
    assert _pressed(state, *["left"] * 50).box == (0, 0, 1000, 1000)


def test_zoom_keeps_the_centre_and_its_limits() -> None:
    state = _pressed(_state(), "in")
    assert state.box == (550, 50, 900, 900)
    # Now it can move down too.
    assert _pressed(state, "down").box == (550, 95, 900, 900)
    smallest = _pressed(state, *["in"] * 60)
    assert smallest.scale == MIN_SCALE
    assert smallest.box == (950, 450, 100, 100)
    assert _pressed(smallest, *["out"] * 60).box == (500, 0, 1000, 1000)
    # Zooming out at an edge pushes the box back inside.
    corner = _pressed(state, *["Up"] * 4, *["Left"] * 4, "out")
    assert corner.box == (0, 0, 1000, 1000)


def test_reset_enter_cancel_and_other_keys() -> None:
    state = _pressed(_state(), "in", "in", "Right")
    assert _pressed(state, "reset").box == (500, 0, 1000, 1000)
    assert press(state, "enter") == ACCEPT
    assert press(state, "cancel") == CANCEL
    assert press(state, "mystery") == state
    assert status(state, "1x1").startswith("1:1 810x810 at ")


@pytest.mark.parametrize(
    ("sent", "key", "rest"),
    [
        (b"\x1b[A", "up", b""),
        (b"\x1bOD", "left", b""),
        (b"\x1b[1;2Cq", "Right", b"q"),
        (b"\x1b[Bq", "down", b"q"),
        (b"L", "Right", b""),
        (b"\r", "enter", b""),
        (b"+-", "in", b"-"),
        (b"_", "out", b""),
        (b"0", "reset", b""),
        (b"\x1b", "cancel", b""),
        (b"x", None, b""),
        (b"\x1b[5~j", None, b"j"),
        (b"\x1bOPj", None, b"j"),
        (b"\x1bxj", None, b"j"),
    ],
)
def test_decode(sent: bytes, key: str | None, rest: bytes) -> None:
    assert decode(sent) == (key, rest)


def test_keys_from_a_pipe() -> None:
    read, write = os.pipe()
    # Keys typed quickly arrive together; unknown ones are skipped.
    os.write(write, b"xl\x1b[B\x1b[5~K")
    os.close(write)
    try:
        assert list(keys(read)) == ["right", "down", "Up", "cancel"]
    finally:
        os.close(read)


def test_a_lone_escape_waits_for_the_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    read, write = os.pipe()
    os.write(write, b"\x1b")
    try:
        presses = keys(read, wait=0.01)
        assert next(presses) == "cancel"
        os.write(write, b"\x1b")
        os.write(write, b"[A")
        assert next(presses) == "up"
    finally:
        os.close(read)
        os.close(write)


def _picture(path: Path) -> Path:
    pixels = np.full((100, 200, 3), 200, dtype=np.uint8)
    Image.fromarray(pixels).save(path)
    return path


def test_preview_dims_all_but_the_box(tmp_path: Path) -> None:
    preview = Preview(_picture(tmp_path / "p.png"), 2000, 1000, side=200)
    assert preview.factor == 0.1
    frame = preview.frame((500, 0, 1000, 1000))
    assert frame.size == (200, 100)
    assert frame.getpixel((100, 50)) == (200, 200, 200)
    assert frame.getpixel((20, 50))[0] < 100
    assert frame.getpixel((50, 50)) == (255, 255, 255)  # the outline


def test_kitty_image_chunks_its_payload() -> None:
    png = os.urandom(10_000)
    sent = kitty_image(png, "c=80")
    commands = re.findall(rb"\x1b_G([^;]*);([^\x1b]*)\x1b\\", sent)
    assert commands[0][0] == b"a=T,f=100,i=1,q=2,C=1,c=80,m=1"
    assert [control for control, _ in commands[1:]] == [b"m=1"] * (len(commands) - 2) + [b"m=0"]
    assert all(len(data) <= 4096 for _, data in commands)
    assert base64.standard_b64decode(b"".join(data for _, data in commands)) == png


def test_placement_fits_width_or_height() -> None:
    # 80x24 cells of 1:2: a 2:1 image 80 columns wide takes 20 rows.
    assert placement(80, 24, 0.5, 2.0) == "c=80"
    assert placement(80, 24, 0.5, 1.0) == "r=24"


def test_preview_mode() -> None:
    assert preview_mode(CropConfig(), {"KITTY_WINDOW_ID": "3"}) == "kitty"
    assert preview_mode(CropConfig(), {"TERM": "xterm-ghostty"}) == "kitty"
    assert preview_mode(CropConfig(), {"TERM": "xterm-256color"}) == "viewer"
    assert preview_mode(CropConfig(preview="viewer"), {"KITTY_WINDOW_ID": "3"}) == "viewer"
    assert preview_mode(CropConfig(preview="kitty"), {}) == "kitty"


def test_kitty_renderer(tmp_path: Path) -> None:
    leader, follower = os.openpty()
    try:
        # 100 columns, 30 rows of 10x20 pixels.
        fcntl.ioctl(follower, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 1000, 600))
        out = io.BytesIO()
        renderer = KittyRenderer(out, follower)
        renderer.show(Image.new("RGB", (200, 100)), "status line")
        renderer.close()
    finally:
        os.close(leader)
        os.close(follower)
    sent = out.getvalue()
    assert sent.startswith(b"\x1b[?1049h\x1b[?25l" + KITTY_DELETE + b"\x1b[H\x1b_Ga=T")
    # 100 columns of 10 pixels for a 2:1 image need 25 rows of 20: they fit in 29.
    assert b",c=100," in sent
    assert b"\x1b[30;1H\x1b[2Kstatus line" in sent
    assert sent.endswith(KITTY_DELETE + b"\x1b[?25h\x1b[?1049l")


def test_viewer_renderer(tmp_path: Path) -> None:
    started = []
    status_out = io.StringIO()
    path = tmp_path / "cache" / "crop-preview.png"
    renderer = ViewerRenderer(("eog", "--single", "{file}"), path, status_out, started.append)
    renderer.show(Image.new("RGB", (20, 10), "red"), "one")
    renderer.show(Image.new("RGB", (20, 10), "blue"), "two")
    assert started == [["eog", "--single", str(path)]]
    with Image.open(path) as image:
        assert image.getpixel((0, 0)) == (0, 0, 255)
    assert status_out.getvalue().endswith("\r\x1b[2Ktwo")
    renderer.close()
    assert not path.exists()


class _Recorder:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.closed = False

    def show(self, frame: Image.Image, text: str) -> None:
        self.texts.append(text)

    def close(self) -> None:
        self.closed = True


def test_place(tmp_path: Path) -> None:
    preview = Preview(_picture(tmp_path / "p.png"), 2000, 1000)
    recorder = _Recorder()
    box = place(preview, _state(), "1x1", recorder, iter(["in", "Left", "enter"]))
    assert box == _pressed(_state(), "in", "Left").box
    assert len(recorder.texts) == 3 and recorder.closed
    recorder = _Recorder()
    assert place(preview, _state(), "1x1", recorder, iter(["right", "cancel"])) is None
    assert recorder.closed
    # Input that ends cancels.
    assert place(preview, _state(), "1x1", _Recorder(), iter(["right"])) is None
