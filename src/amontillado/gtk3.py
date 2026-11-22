"""GTK3 live theming: `amo hook gtk3-theme`, the libadwaita app's reload command.

docs/gtk-theming.md. GTK3 applications read a theme's `gtk.css` when the theme is loaded, and
reload it when the desktop's `gtk-theme` setting changes. The reload points that setting at the
theme `amontillado-<variant>` (AMO_VARIANT, set by `amo theme apply`), whose `gtk.css` imports
adw-gtk3 and then the applied `libadwaita.css` through the cache's `current` link, so its
`@define-color`s override adw-gtk3's. Setting an unchanged value notifies no one, so when
`gtk-theme` already names that theme it is first set to Adwaita (one brief flash).

The theme's `gtk.css` is written when missing ($XDG_DATA_HOME/themes/amontillado-<variant>/
gtk-3.0/), never overwritten. Setup-specific: needs `gsettings` on PATH, a session whose GTK3
apps follow the `org.gnome.desktop.interface gtk-theme` setting (GNOME, or a Wayland compositor
with xdg-desktop-portal-gtk or gsd-xsettings; an X11 session without them needs xsettingsd's
Net/ThemeName instead), and adw-gtk3 (Fedora `adw-gtk3-theme`) installed under a themes
directory of $XDG_DATA_HOME or $XDG_DATA_DIRS. libadwaita (GTK4) apps ignore `gtk-theme`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path

from amontillado.config import xdg_dir
from amontillado.record import write_text_atomic

logger = getLogger(__name__)

THEME_PREFIX = "amontillado-"
ADW_GTK3 = {"light": "adw-gtk3", "dark": "adw-gtk3-dark"}
# What gtk-theme is set to first when it already names the theme.
FLIP_THEME = "Adwaita"
SCHEMA = "org.gnome.desktop.interface"
KEY = "gtk-theme"
DEFAULT_DATA_DIRS = "/usr/local/share:/usr/share"


class Gtk3Error(Exception):
    pass


@dataclass(frozen=True)
class Plan:
    """What the reload does: the theme to select, and its gtk.css with the text it needs."""

    theme: str
    css: Path
    text: str
    write: bool


def theme_name(variant: str) -> str:
    return THEME_PREFIX + variant


def data_dirs() -> list[Path]:
    """$XDG_DATA_HOME, then $XDG_DATA_DIRS (absolute entries only), as GTK searches them."""
    value = os.environ.get("XDG_DATA_DIRS") or DEFAULT_DATA_DIRS
    system = [Path(entry) for entry in value.split(":") if entry and Path(entry).is_absolute()]
    return [xdg_dir("XDG_DATA_HOME", ".local/share"), *system]


def find_adw_gtk3(variant: str) -> Path | None:
    """adw-gtk3's gtk.css for `variant` (adw-gtk3-dark for dark), or None if not installed."""
    for directory in data_dirs():
        css = directory / "themes" / ADW_GTK3[variant] / "gtk-3.0" / "gtk.css"
        if css.is_file():
            return css
    return None


def theme_css(variant: str) -> Path:
    """The gtk.css of the theme amontillado-<variant>, under $XDG_DATA_HOME/themes."""
    themes = xdg_dir("XDG_DATA_HOME", ".local/share") / "themes"
    return themes / theme_name(variant) / "gtk-3.0" / "gtk.css"


def theme_text(variant: str, adw_gtk3: Path, colours: Path) -> str:
    """The theme's gtk.css: adw-gtk3, then the applied colours. Absolute file:// URLs, since a
    relative @import resolves against the path GTK loaded."""
    return (
        f"/* amontillado-{variant}: adw-gtk3 in the applied palette's colours (amo hook "
        "gtk3-theme). */\n"
        f'@import url("{adw_gtk3.absolute().as_uri()}");\n'
        f'@import url("{colours.absolute().as_uri()}");\n'
    )


def plan(variant: str, colours: Path) -> Plan:
    """The reload for `variant`, `colours` being the applied libadwaita.css through `current`.
    Raises Gtk3Error when gsettings or adw-gtk3 is missing."""
    if variant not in ADW_GTK3:
        raise Gtk3Error(f"AMO_VARIANT is {variant!r}, not dark or light")
    missing = []
    if shutil.which("gsettings") is None:
        missing.append("gsettings (not on PATH)")
    adw_gtk3 = find_adw_gtk3(variant)
    if adw_gtk3 is None:
        dirs = ", ".join(str(d / "themes") for d in data_dirs())
        missing.append(f"{ADW_GTK3[variant]} (no gtk-3.0/gtk.css under {dirs})")
    if missing:
        raise Gtk3Error("missing: " + "; ".join(missing))
    assert adw_gtk3 is not None
    css = theme_css(variant)
    text = theme_text(variant, adw_gtk3, colours)
    if css.is_file() and css.read_text() != text:
        logger.warning("%s differs from what amo would write; left as it is", css)
    return Plan(theme_name(variant), css, text, write=not css.exists())


def _gsettings(*args: str) -> str:
    result = subprocess.run(["gsettings", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise Gtk3Error(f"gsettings {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def current_theme() -> str:
    """gtk-theme's value (gsettings prints it quoted: 'Adwaita')."""
    return _gsettings("get", SCHEMA, KEY).strip("'")


def run(reload: Plan) -> None:
    """Write the theme's gtk.css if missing, then select the theme."""
    if reload.write:
        reload.css.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(reload.css, reload.text)
        logger.info("wrote %s", reload.css)
    if current_theme() == reload.theme:
        _gsettings("set", SCHEMA, KEY, FLIP_THEME)
    _gsettings("set", SCHEMA, KEY, reload.theme)
    logger.debug("gtk-theme: %s", reload.theme)
