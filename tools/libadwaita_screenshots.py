#!/usr/bin/env python3
"""Capture screenshots of a running libadwaita test app for the libadwaita live test.

Called by `tools/libadwaita-live-test.sh --screenshot DIR` once per scenario, after the shell
script has launched the app on the rendered gtk.css; it can also be run by hand against an app
that is already open. For adwaita-1-demo it opens each requested page and captures the window;
for gnome-text-editor it captures the window once. Paths of the files written go to stdout.

SPECIFIC TO ONE KIND OF SETUP (MH's). It needs:
  - Hyprland: window geometry and focus come from `hyprctl activewindow -j` (no other
    compositor is supported). No `hyprctl dispatch` is sent: Hyprland 0.56 moved it to a Lua
    syntax, so focus is never moved for you.
  - grim (capture), wtype (keys), an AT-SPI accessibility bus, and the system python3 with
    PyGObject's Atspi 2.0 (python3-gobject, at-spi2-core). Not the project's uv venv: PyGObject
    is not in it, which is also why this script uses only the standard library otherwise.
    ImageMagick (`magick`) is optional, for a contact sheet per run.
  - No mouse: ydotool needs root (/dev/uinput). Pages are reached by keyboard.
  - KEYBOARD FOCUS ON THE APP'S WINDOW for the whole run. wtype types into whatever window has
    focus, so before every key press the active window is checked and the run stops if it is not
    the app's. Do not switch windows or workspaces while it runs.
  - adwaita-1-demo's sidebar page names and button labels as of libadwaita 1.9.1; a newer
    libadwaita may rename them, which shows as "no page" or "no button" errors.

How pages are opened: a sidebar row is found by its label over AT-SPI. Rows switch the page when
*activated*, not when selected, and AT-SPI cannot focus them, so the script presses Down or Up
one key at a time and reads the focused row back after each press (keys sent quickly were
dropped or doubled), then Return. A button is pressed through its own click action; a label's
first action is clipboard.copy, so labels are never actioned. After the capture, a button that
opened a dialog (Style Classes) is undone with Escape; one that opened a window of its own (Tab
View's demo, which Escape does not close) is undone with that window's header bar Close button,
over AT-SPI, and the run waits for the main window to have focus again.

Not covered by the test suite: it needs a live graphical session.

  python3 -I tools/libadwaita_screenshots.py --app adwaita-1-demo --prefix dark OUTDIR
  python3 -I tools/libadwaita_screenshots.py --app adwaita-1-demo --prefix dark OUTDIR \\
      "Buttons" "Alert Dialog+Alert Dialog"
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import warnings
from logging import getLogger
from pathlib import Path

logger = getLogger(__name__)

PROG = "libadwaita_screenshots"
# AT-SPI application name -> Hyprland window class.
APPS = {
    "adwaita-1-demo": "org.gnome.Adwaita1.Demo",
    "gnome-text-editor": "org.gnome.TextEditor",
}
# PAGE or PAGE+BUTTON: open the sidebar page, then press the button (a dialog, a toast, a
# window) before capturing.
DEMO_PAGES = [
    "Buttons",
    "Boxed Lists",
    "Banner",
    "Toasts+Show",
    "Alert Dialog+Alert Dialog",
    "Tab View+Run the Demo",
    "Style Classes+Run the Demo",
]
SETTLE = 0.8
KEY_PAUSE = 0.15
APPEAR_TIMEOUT = 15.0
FOCUS_TIMEOUT = 5.0


class HelpFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    """Preserve the docstring's layout and show defaults (stdlib only: see the docstring)."""


def get_cli_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=HelpFormatter)
    parser.add_argument(
        "--loglevel",
        "-l",
        default="INFO",
        type=lambda v: v.strip().upper(),
        help="Logging verbosity (DEBUG, INFO, WARNING, ERROR).",
    )
    parser.add_argument("--app", choices=sorted(APPS), default="adwaita-1-demo")
    parser.add_argument("--prefix", required=True, help="File name prefix, e.g. the scenario.")
    parser.add_argument("outdir", type=Path, help="Directory for the PNG files.")
    parser.add_argument(
        "pages",
        nargs="*",
        help="adwaita-1-demo pages, PAGE or PAGE+BUTTON (default: a fixed set covering "
        "buttons, lists, banner, toast, dialog, the tab view window and the style classes dialog).",
    )
    return parser.parse_args()


def setup_logger(args: argparse.Namespace) -> None:
    logging.basicConfig(level=args.loglevel, format=f"{PROG}: %(levelname)s: %(message)s")


def fail(message: str) -> None:
    sys.exit(f"{PROG}: {message}")


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, text=True, capture_output=True).stdout


def preflight() -> None:
    """Every prerequisite, checked up front, naming what is missing."""
    missing = []
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        missing.append("a Hyprland session (HYPRLAND_INSTANCE_SIGNATURE is unset)")
    missing += [
        f"{tool} on PATH" for tool in ("hyprctl", "grim", "wtype") if not shutil.which(tool)
    ]
    try:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi  # noqa: F401
    except (ImportError, ValueError) as exc:
        missing.append(f"PyGObject with Atspi 2.0 for {sys.executable} ({exc})")
    if missing:
        fail("missing: " + "; ".join(missing))


def active_window() -> dict:
    return json.loads(run(["hyprctl", "activewindow", "-j"]))


class Driver:
    """One running app, reached over AT-SPI and captured through Hyprland."""

    def __init__(self, app_name: str) -> None:
        from gi.repository import Atspi

        self.atspi = Atspi
        self.app_name = app_name
        self.window_class = APPS[app_name]
        self.app = self._wait_for_app()
        # The main window, told apart from windows the app opens later (same class).
        self.main_window = active_window()["address"]

    def _wait_for_app(self):
        deadline = time.monotonic() + APPEAR_TIMEOUT
        while time.monotonic() < deadline:
            desktop = self.atspi.get_desktop(0)
            for i in range(desktop.get_child_count()):
                app = desktop.get_child_at_index(i)
                if app.get_name() == self.app_name and active_window().get("class") == (
                    self.window_class
                ):
                    time.sleep(SETTLE)
                    return app
            time.sleep(0.5)
        fail(
            f"{self.app_name} did not appear as the focused window within {APPEAR_TIMEOUT:g}s "
            "(not running, on another workspace, or not on the accessibility bus)"
        )

    def find(self, node, role: str, name: str):
        try:
            if node.get_role_name() == role and node.get_name() == name:
                return node
            count = node.get_child_count()
        except Exception as exc:  # a node can vanish while the tree is walked
            logger.debug("skipping a node: %s", exc)
            return None
        for i in range(count):
            hit = self.find(node.get_child_at_index(i), role, name)
            if hit:
                return hit
        return None

    def focused(self, node=None):
        node = self.app if node is None else node
        try:
            if node.get_state_set().contains(self.atspi.StateType.FOCUSED):
                return node
            count = node.get_child_count()
        except Exception as exc:
            logger.debug("skipping a node: %s", exc)
            return None
        for i in range(count):
            hit = self.focused(node.get_child_at_index(i))
            if hit:
                return hit
        return None

    def key(self, name: str) -> None:
        """Press `name`, only while the app has focus: wtype types into whatever window does."""
        window = active_window().get("class")
        if window != self.window_class:
            fail(f"the focused window is {window!r}, not {self.window_class}: not sending {name}")
        run(["wtype", "-k", name])

    def sidebar_focus(self, rows) -> int:
        """The index of the focused row in `rows`, waiting for it: at launch, and after a
        key, focus arrives a moment after the window does."""
        deadline = time.monotonic() + FOCUS_TIMEOUT
        while time.monotonic() < deadline:
            current = self.focused()
            if current is not None and current.get_parent() == rows:
                return current.get_index_in_parent()
            time.sleep(0.2)
        fail("keyboard focus is not in the sidebar: not sending keys")

    def open_page(self, label: str) -> None:
        node = self.find(self.app, "label", label)
        while node is not None and node.get_role_name() != "list item":
            node = node.get_parent()
        if node is None:
            fail(f"no sidebar page {label!r} in {self.app_name}")
        rows = node.get_parent()
        target = node.get_index_in_parent()
        for _ in range(3 * rows.get_child_count()):
            at = self.sidebar_focus(rows)
            if at == target:
                self.key("Return")
                time.sleep(SETTLE)
                return
            self.key("Down" if at < target else "Up")
            time.sleep(KEY_PAUSE)
        fail(f"could not reach the {label!r} row")

    def press(self, name: str) -> None:
        node = self.find(self.app, "button", name)
        if node is None:
            fail(f"no button {name!r} in {self.app_name}")
        self.click(node, name)

    def click(self, node, name: str) -> None:
        action = node.get_action_iface()
        if action is None:
            fail(f"button {name!r} has no actions")
        for i in range(action.get_n_actions()):
            # get_action_name is deprecated for atspi_action_get_name, which PyGObject hides
            # behind Accessible.get_name on the same object: the old name is the only one.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                name = action.get_action_name(i)
            if name in ("click", "activate", "press"):
                action.do_action(i)
                time.sleep(SETTLE)
                return
        fail(f"button {name!r} has no click action")

    def undo(self) -> None:
        """Close what the last button opened: a window of its own by its Close button, else
        (a dialog) with Escape."""
        if active_window().get("address") == self.main_window:
            self.key("Escape")
            time.sleep(SETTLE)
            return
        frame = self.active_frame()
        close = self.find(frame, "button", "Close") if frame is not None else None
        if close is None:
            fail("a window the demo opened has no Close button: close it by hand")
        self.click(close, "Close")
        deadline = time.monotonic() + FOCUS_TIMEOUT
        while active_window().get("address") != self.main_window:
            if time.monotonic() > deadline:
                fail("the main window did not get focus back after closing the demo window")
            time.sleep(0.2)
        time.sleep(SETTLE)

    def active_frame(self):
        """The app's top-level window that is active (has focus), if AT-SPI says so."""
        for i in range(self.app.get_child_count()):
            frame = self.app.get_child_at_index(i)
            if frame.get_state_set().contains(self.atspi.StateType.ACTIVE):
                return frame
        return None

    def capture(self, path: Path) -> None:
        # The active window: the app's, or a window it opened (Style Classes).
        window = active_window()
        if window.get("class") != self.window_class:
            fail(f"the focused window is {window.get('class')!r}: not capturing")
        (x, y), (width, height) = window["at"], window["size"]
        run(["grim", "-g", f"{x},{y} {width}x{height}", str(path)])
        print(path)


def contact_sheet(paths: list[Path], sheet: Path) -> None:
    if len(paths) < 2:
        return
    if not shutil.which("magick"):
        logger.info("no ImageMagick (magick): no contact sheet")
        return
    columns = min(3, len(paths))
    run(
        [
            "magick",
            "montage",
            *map(str, paths),
            "-tile",
            f"{columns}x",
            "-geometry",
            "900x+6+6",
            "-background",
            "#888",
            str(sheet),
        ]
    )
    print(sheet)


def main() -> None:
    args = get_cli_arguments()
    setup_logger(args)
    preflight()
    args.outdir.mkdir(parents=True, exist_ok=True)
    driver = Driver(args.app)
    paths = []
    if args.app != "adwaita-1-demo":
        if args.pages:
            fail(f"pages are for adwaita-1-demo only, not {args.app}")
        path = args.outdir / f"{args.prefix}-window.png"
        driver.capture(path)
        return
    for page in args.pages or DEMO_PAGES:
        label, _, button = page.partition("+")
        logger.info("%s: %s", args.prefix, page)
        driver.open_page(label)
        if button:
            driver.press(button)
        path = args.outdir / f"{args.prefix}-{label.lower().replace(' ', '-')}.png"
        driver.capture(path)
        paths.append(path)
        if button:
            driver.undo()
    contact_sheet(paths, args.outdir / f"{args.prefix}-sheet.png")


if __name__ == "__main__":
    main()
