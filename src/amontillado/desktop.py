"""The desktop's colour scheme as a variant, for `variant: system`.

docs/design.md, "Theme engine (v0.2)", "Variant". Read once per `amo theme apply`: the xdg
settings portal's `org.freedesktop.appearance color-scheme` first (1 dark, 2 light, 0 no
preference), through `gdbus`; then GNOME's `org.gnome.desktop.interface color-scheme`
(`prefer-dark`, `prefer-light`, `default`), through `gsettings`. Both need a session bus;
`gdbus` and `gsettings` ship with GLib. Without a preference from either, the variant is `auto`
(the picture decides) and a warning says why.
"""

from __future__ import annotations

import re
import subprocess
from logging import getLogger

logger = getLogger(__name__)

PORTAL_COMMAND = (
    "gdbus",
    "call",
    "--session",
    "--dest",
    "org.freedesktop.portal.Desktop",
    "--object-path",
    "/org/freedesktop/portal/desktop",
    "--method",
    # Read, not ReadOne: every portal version has it (ReadOne needs version 2).
    "org.freedesktop.portal.Settings.Read",
    "org.freedesktop.appearance",
    "color-scheme",
)
GSETTINGS_COMMAND = ("gsettings", "get", "org.gnome.desktop.interface", "color-scheme")
PORTAL_VARIANTS = {1: "dark", 2: "light"}
GSETTINGS_VARIANTS = {"prefer-dark": "dark", "prefer-light": "light"}
TIMEOUT = 5


def desktop_variant() -> str:
    """dark or light from the desktop's colour scheme, else auto (with a warning)."""
    reasons = []
    for name, read in (("portal", _portal), ("gsettings", _gsettings)):
        variant, reason = read()
        if variant is not None:
            logger.debug("variant system: %s from the %s", variant, name)
            return variant
        reasons.append(f"{name}: {reason}")
    logger.warning("variant system: no colour scheme (%s); using auto", "; ".join(reasons))
    return "auto"


def _portal() -> tuple[str | None, str]:
    output, error = _run(PORTAL_COMMAND)
    if output is None:
        return None, error
    # (<<uint32 1>>,) from Read; (<uint32 1>,) from ReadOne.
    found = re.search(r"\buint32 (\d+)", output)
    if found is None:
        return None, f"unexpected reply {output.strip()!r}"
    value = int(found.group(1))
    if value not in PORTAL_VARIANTS:
        return None, "no preference" if value == 0 else f"unknown value {value}"
    return PORTAL_VARIANTS[value], ""


def _gsettings() -> tuple[str | None, str]:
    output, error = _run(GSETTINGS_COMMAND)
    if output is None:
        return None, error
    value = output.strip().strip("'")
    if value not in GSETTINGS_VARIANTS:
        return None, "no preference" if value == "default" else f"unknown value {value!r}"
    return GSETTINGS_VARIANTS[value], ""


def _run(command: tuple[str, ...]) -> tuple[str | None, str]:
    """`command`'s stdout, or None and why it failed."""
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=TIMEOUT
        )
    except FileNotFoundError:
        return None, f"{command[0]} not found"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    if result.returncode != 0:
        lines = result.stderr.strip().splitlines()
        return None, lines[-1] if lines else f"exit status {result.returncode}"
    return result.stdout, ""
