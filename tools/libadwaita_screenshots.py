#!/usr/bin/env python3
"""Launch a libadwaita test app, open its pages and capture them, for the libadwaita live test.

Called by `tools/libadwaita-live-test.sh --screenshot DIR` once per scenario, with the
environment that points the app at the rendered gtk.css (`--env`). It launches the app itself,
drives it, captures each page, and closes it again. For adwaita-1-demo it opens each requested
page and captures the window (or the window a page's button opened); for gnome-text-editor it
captures the window once. Paths of the files written go to stdout.

Keyboard focus is never needed and never taken: keys go to the app's window by Hyprland's
`send_key_state` dispatcher, buttons are pressed over AT-SPI, and captures are of the window
itself (`grim -T`), not of a region of the screen. Windows the app opens are routed to its
workspace without focus by a window rule held for the run. Two placements:

  visible (default)  The app opens on the workspace you are on when the run starts, without
                     taking focus. Work in another window if you like, but keep that workspace
                     on screen: GTK does not update a window it is not drawing, and pages then
                     cannot be found.
  --hidden           The app opens on a headless output created for the run (a virtual monitor
                     placed far from the real ones, so the cursor never reaches it) and removed
                     after; nothing appears on screen. Creating and removing an output fires
                     Hyprland's monitor.added / monitor.removed events, which your config may
                     act on (MH's: waybar reconcile, and the lid-closed panel logic, which
                     counts any output besides eDP-1 as a docking monitor: do not close the lid
                     during a hidden run).

SPECIFIC TO ONE KIND OF SETUP (MH's). It needs:
  - Hyprland 0.56 or later (its Lua `hyprctl eval`); no other compositor is supported.
  - grim 1.5 or later (`-T`, capture of one window), an AT-SPI accessibility bus, and the
    system python3 with PyGObject's Atspi 2.0 (python3-gobject, at-spi2-core). Not the
    project's uv venv: PyGObject is not in it, which is also why this script uses only the
    standard library otherwise. ImageMagick (`magick`) is optional, for a contact sheet per run.
  - adwaita-1-demo's sidebar page names and button labels as of libadwaita 1.9.1; a newer
    libadwaita may rename them, which shows as "no page" or "no button" errors.

How pages are opened: a sidebar row is found by its label over AT-SPI. Rows switch the page when
*activated*, not when selected, and AT-SPI cannot activate them, so the script sends Down or Up
one key at a time and reads the selected row back after each (an unfocused window reports no
focused widget, but its selected row), then Return. Each key is a separate press and release:
Hyprland's `send_shortcut` sends both at once, and GTK dropped some of those. A button is
pressed through its own click action; a label's first action is clipboard.copy, so labels are
never actioned. After the capture, a button that opened a window of its own (Tab View's demo) is
undone with that window's Close button over AT-SPI; one that opened a dialog (Style Classes)
with Escape.

Not covered by the test suite: it needs a live graphical session.

  python3 -I tools/libadwaita_screenshots.py --app adwaita-1-demo --prefix dark \\
      --env XDG_CONFIG_HOME=/tmp/x/dark --env ADW_DEBUG_COLOR_SCHEME=prefer-dark OUTDIR
  python3 -I tools/libadwaita_screenshots.py --hidden --app adwaita-1-demo --prefix dark \\
      OUTDIR "Buttons" "Alert Dialog+Alert Dialog"
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import warnings
from logging import getLogger
from pathlib import Path

logger = getLogger(__name__)

PROG = "libadwaita_screenshots"
# AT-SPI application name (also the command) -> the Hyprland window classes of its windows.
APPS = {
    "adwaita-1-demo": ("org.gnome.Adwaita1.Demo", "adwaita-1-demo"),
    "gnome-text-editor": ("org.gnome.TextEditor",),
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
# Names of what the run creates in Hyprland, removed (or disabled) when it ends.
OUTPUT = "AMO-LIVE-TEST"
RULE = "amo-live-test"
# Lua global holding the rule between `hyprctl eval` calls, to disable it at the end.
RULE_GLOBAL = "amo_live_test_rule"
# The headless output sits this far right of the rightmost real one.
OUTPUT_GAP = 10000
SETTLE = 0.8
KEY_PAUSE = 0.4
KEY_HOLD = 0.08
APPEAR_TIMEOUT = 15.0
STATE_TIMEOUT = 5.0


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
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="An environment variable for the app (repeatable).",
    )
    parser.add_argument(
        "--hidden",
        action="store_true",
        help="Run the app on a headless output for the run, off screen (see above).",
    )
    parser.add_argument("outdir", type=Path, help="Directory for the PNG files.")
    parser.add_argument(
        "pages",
        nargs="*",
        help="adwaita-1-demo pages, PAGE or PAGE+BUTTON (default: a fixed set covering "
        "buttons, lists, banner, toast, dialog, the tab view window and the style classes "
        "dialog).",
    )
    return parser.parse_args()


def setup_logger(args: argparse.Namespace) -> None:
    logging.basicConfig(level=args.loglevel, format=f"{PROG}: %(levelname)s: %(message)s")


class Failure(Exception):
    """An expected failure: reported as `PROG: message` after cleaning up."""


def fail(message: str) -> None:
    raise Failure(message)


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, text=True, capture_output=True).stdout


def lua(code: str) -> None:
    """Run `code` in Hyprland's Lua (`hyprctl eval`); it answers "ok" or an error."""
    answer = run(["hyprctl", "eval", code]).strip()
    if answer != "ok":
        fail(f"hyprctl eval failed: {answer} (code: {code})")


def lua_string(text: str) -> str:
    return json.dumps(text)  # a JSON string literal is a valid Lua one for these characters


def clients() -> list[dict]:
    return json.loads(run(["hyprctl", "clients", "-j"]))


def monitors() -> list[dict]:
    return json.loads(run(["hyprctl", "monitors", "-j"]))


def preflight() -> None:
    """Every prerequisite, checked up front, naming what is missing."""
    missing = []
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        missing.append("a Hyprland session (HYPRLAND_INSTANCE_SIGNATURE is unset)")
    missing += [f"{tool} on PATH" for tool in ("hyprctl", "grim") if not shutil.which(tool)]
    if shutil.which("grim"):
        usage = subprocess.run(["grim", "-h"], check=False, text=True, capture_output=True)
        if " -T " not in usage.stdout + usage.stderr:
            missing.append("grim 1.5 or later (-T, capture of one window)")
    try:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi  # noqa: F401
    except (ImportError, ValueError) as exc:
        missing.append(f"PyGObject with Atspi 2.0 for {sys.executable} ({exc})")
    if missing:
        fail("missing: " + "; ".join(missing))


def wait_for(what: str, probe, timeout: float = STATE_TIMEOUT):
    """`probe()`'s first true result, polled until `timeout`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = probe()
        if result:
            return result
        time.sleep(0.2)
    fail(f"timed out waiting for {what}")


class Session:
    """What the run sets up in Hyprland, and takes down again: the headless output (--hidden)
    and the window rule that routes the app's windows to its workspace without focus."""

    def __init__(self, app_name: str, hidden: bool) -> None:
        self.classes = APPS[app_name]
        self.hidden = hidden
        self.output_created = False
        self.rule_created = False

    def __enter__(self) -> Session:
        if self.hidden:
            right = max(m["x"] + m["width"] for m in monitors())
            lua(
                f"hl.monitor({{ output = {lua_string(OUTPUT)}, mode = '1920x1080@60', "
                f"position = '{right + OUTPUT_GAP}x0', scale = 1 }})"
            )
            run(["hyprctl", "output", "create", "headless", OUTPUT])
            self.output_created = True
            output = wait_for(
                f"the headless output {OUTPUT}",
                lambda: next((m for m in monitors() if m["name"] == OUTPUT), None),
            )
            workspace = output["activeWorkspace"]
        else:
            workspace = next(m for m in monitors() if m["focused"])["activeWorkspace"]
        # A named workspace is addressed as name:NAME; a numbered one by its number.
        name = workspace["name"]
        target = name if re.fullmatch(r"-?\d+", name) else f"name:{name}"
        pattern = "^(" + "|".join(re.escape(c) for c in self.classes) + ")$"
        lua(
            f"{RULE_GLOBAL} = hl.window_rule({{ name = {lua_string(RULE)}, "
            f"match = {{ class = {lua_string(pattern)} }}, "
            f"workspace = {lua_string(target + ' silent')} }})"
        )
        self.rule_created = True
        where = f" on the headless output {OUTPUT}" if self.hidden else ""
        logger.info("app windows go to workspace %s%s", name, where)
        return self

    def __exit__(self, *exc: object) -> None:
        if self.rule_created:
            try:
                lua(f"if {RULE_GLOBAL} then {RULE_GLOBAL}:set_enabled(false) end")
            except (Failure, subprocess.CalledProcessError) as error:
                logger.warning("could not disable the window rule %s: %s", RULE, error)
        if self.output_created:
            result = subprocess.run(
                ["hyprctl", "output", "remove", OUTPUT], check=False, text=True, capture_output=True
            )
            if result.returncode != 0 or result.stdout.strip() != "ok":
                logger.warning(
                    "could not remove the headless output %s (hyprctl output remove %s): %s",
                    OUTPUT,
                    OUTPUT,
                    (result.stdout + result.stderr).strip(),
                )


class Driver:
    """One app launched for the run, reached over AT-SPI and through Hyprland."""

    def __init__(self, app_name: str, env: dict[str, str]) -> None:
        from gi.repository import Atspi

        self.atspi = Atspi
        self.app_name = app_name
        self.process = subprocess.Popen(
            [app_name],
            env={**os.environ, **env},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            main = wait_for(
                f"a window of {app_name}", lambda: next(iter(self.windows()), None), APPEAR_TIMEOUT
            )
            self.main_window = main["address"]
            self.app = wait_for(
                f"{app_name} on the accessibility bus", self._accessible, APPEAR_TIMEOUT
            )
        except BaseException:
            self.close()
            raise
        time.sleep(SETTLE)

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()

    def windows(self) -> list[dict]:
        """The app's mapped windows, in the order Hyprland lists them."""
        return [c for c in clients() if c["pid"] == self.process.pid and c["mapped"]]

    def _accessible(self):
        desktop = self.atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            try:
                if app.get_process_id() == self.process.pid:
                    return app
            except Exception as exc:  # an app can leave the bus while it is walked
                logger.debug("skipping an application: %s", exc)
        return None

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

    def key(self, name: str) -> None:
        """Press and release `name` in the main window, which needs no focus."""
        select = (
            f"local target; for _, w in ipairs(hl.get_windows()) do "
            f"if w.address == {lua_string(self.main_window)} then target = w end end; "
            "if not target then error('the app window is gone') end; "
        )
        for state in ("down", "up"):
            lua(
                select + "hl.dispatch(hl.dsp.send_key_state({ mods = '', "
                f"key = {lua_string(name)}, state = '{state}', window = target }}))"
            )
            time.sleep(KEY_HOLD)
        time.sleep(KEY_PAUSE)

    def selected_row(self, rows) -> int | None:
        for i in range(rows.get_child_count()):
            try:
                if (
                    rows.get_child_at_index(i)
                    .get_state_set()
                    .contains(self.atspi.StateType.SELECTED)
                ):
                    return i
            except Exception as exc:
                logger.debug("skipping a row: %s", exc)
        return None

    def _selected(self, rows) -> tuple[int] | None:
        at = self.selected_row(rows)
        return None if at is None else (at,)

    def open_page(self, label: str) -> None:
        node = self.find(self.app, "label", label)
        while node is not None and node.get_role_name() != "list item":
            node = node.get_parent()
        if node is None:
            fail(f"no sidebar page {label!r} in {self.app_name}")
        rows = node.get_parent()
        target = node.get_index_in_parent()
        for _ in range(3 * rows.get_child_count()):
            # A tuple, since row 0 is a valid (and falsy) answer.
            (at,) = wait_for("a selected sidebar row", lambda: self._selected(rows))
            if at == target:
                self.key("Return")
                time.sleep(SETTLE)
                return
            self.key("Down" if at < target else "Up")
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
                action_name = action.get_action_name(i)
            if action_name in ("click", "activate", "press"):
                action.do_action(i)
                time.sleep(SETTLE)
                return
        fail(f"button {name!r} has no click action")

    def other_window(self) -> dict | None:
        """A window the app opened besides its main one, if any."""
        return next((w for w in self.windows() if w["address"] != self.main_window), None)

    def undo(self) -> None:
        """Close what the last button opened: a window of its own by its Close button, else
        (a dialog) with Escape."""
        window = self.other_window()
        if window is None:
            self.key("Escape")
            time.sleep(SETTLE)
            return
        frame = next(
            (
                self.app.get_child_at_index(i)
                for i in range(self.app.get_child_count())
                if self.app.get_child_at_index(i).get_name() == window["title"]
            ),
            None,
        )
        close = self.find(frame, "button", "Close") if frame is not None else None
        if close is None:
            fail(f"the window {window['title']!r} has no Close button: close it by hand")
        self.click(close, "Close")
        wait_for(
            f"the window {window['title']!r} to close",
            lambda: all(w["address"] != window["address"] for w in self.windows()),
        )

    def capture(self, path: Path) -> None:
        """The window the last button opened, or else the main one."""
        window = self.other_window() or next(
            (w for w in self.windows() if w["address"] == self.main_window), None
        )
        if window is None:
            fail(f"{self.app_name} has no window to capture")
        run(["grim", "-T", window["stableId"], str(path)])
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


def capture_pages(driver: Driver, args: argparse.Namespace) -> None:
    if args.app != "adwaita-1-demo":
        driver.capture(args.outdir / f"{args.prefix}-window.png")
        return
    paths = []
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


def main() -> None:
    args = get_cli_arguments()
    setup_logger(args)
    env = {}
    for item in args.env:
        name, sep, value = item.partition("=")
        if not sep or not name:
            sys.exit(f"{PROG}: --env takes NAME=VALUE, not {item!r}")
        env[name] = value
    if args.pages and args.app != "adwaita-1-demo":
        sys.exit(f"{PROG}: pages are for adwaita-1-demo only, not {args.app}")
    try:
        preflight()
        args.outdir.mkdir(parents=True, exist_ok=True)
        with Session(args.app, args.hidden):
            driver = Driver(args.app, env)
            try:
                capture_pages(driver, args)
            finally:
                driver.close()
    except Failure as error:
        sys.exit(f"{PROG}: {error}")


if __name__ == "__main__":
    main()
