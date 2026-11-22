"""amo hook gtk3-theme: the GTK3 live-theme reload, against a fake gsettings (no session bus)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from amontillado import yamlio
from amontillado.cli import main

# gsettings get/set of one key, its value in $GSETTINGS_STATE, each call logged to $GSETTINGS_LOG.
FAKE_GSETTINGS = """#!/bin/sh
echo "$*" >> "$GSETTINGS_LOG"
case "$1" in
  get) printf "'%s'\\n" "$(cat "$GSETTINGS_STATE")" ;;
  set) printf '%s' "$4" > "$GSETTINGS_STATE" ;;
  *) exit 1 ;;
esac
"""
SCHEMA_KEY = "org.gnome.desktop.interface gtk-theme"


@pytest.fixture
def gsettings(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake gsettings first on PATH, gtk-theme 'Adwaita'; returns its call log."""
    bin_dir = home / "bin"
    bin_dir.mkdir()
    script = bin_dir / "gsettings"
    script.write_text(FAKE_GSETTINGS)
    script.chmod(0o755)
    state, log = home / "gsettings.state", home / "gsettings.log"
    state.write_text("Adwaita")
    log.write_text("")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("GSETTINGS_STATE", str(state))
    monkeypatch.setenv("GSETTINGS_LOG", str(log))
    return log


@pytest.fixture
def adw_gtk3(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """adw-gtk3 and adw-gtk3-dark under a system data dir; returns that dir."""
    system = home / "system-share"
    for name in ("adw-gtk3", "adw-gtk3-dark"):
        css = system / "themes" / name / "gtk-3.0" / "gtk.css"
        css.parent.mkdir(parents=True)
        css.write_text("/* adw-gtk3 */\n")
    monkeypatch.setenv("XDG_DATA_DIRS", str(system))
    monkeypatch.setenv("AMO_VARIANT", "dark")
    return system


def _config(home: Path, apps: dict[str, object]) -> None:
    path = home / ".config" / "amontillado" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yamlio.dump({"theme": {"apps": apps}}))


def _theme_css(home: Path, variant: str = "dark") -> Path:
    return home / ".local" / "share" / "themes" / f"amontillado-{variant}" / "gtk-3.0" / "gtk.css"


def _state(home: Path) -> str:
    return (home / "gsettings.state").read_text()


def test_writes_the_theme_and_selects_it(home: Path, gsettings: Path, adw_gtk3: Path) -> None:
    _config(home, {"libadwaita": {"reload": "amo hook gtk3-theme"}})
    main(["hook", "gtk3-theme"])
    adw = adw_gtk3 / "themes" / "adw-gtk3-dark" / "gtk-3.0" / "gtk.css"
    colours = home / ".cache" / "theme" / "current" / "libadwaita.css"
    imports = [line for line in _theme_css(home).read_text().splitlines() if "@import" in line]
    assert imports == [f'@import url("{adw.as_uri()}");', f'@import url("{colours.as_uri()}");']
    assert _state(home) == "amontillado-dark"
    assert gsettings.read_text().splitlines() == [
        f"get {SCHEMA_KEY}",
        f"set {SCHEMA_KEY} amontillado-dark",
    ]


def test_flips_through_adwaita_when_unchanged(home: Path, gsettings: Path, adw_gtk3: Path) -> None:
    _config(home, {"libadwaita": {}})
    (home / "gsettings.state").write_text("amontillado-dark")
    main(["hook", "gtk3-theme"])
    assert gsettings.read_text().splitlines() == [
        f"get {SCHEMA_KEY}",
        f"set {SCHEMA_KEY} Adwaita",
        f"set {SCHEMA_KEY} amontillado-dark",
    ]
    assert _state(home) == "amontillado-dark"


def test_light_variant_imports_adw_gtk3(
    home: Path, gsettings: Path, adw_gtk3: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _config(home, {"libadwaita": {"output": "adw.css"}})
    monkeypatch.setenv("AMO_VARIANT", "light")
    main(["hook", "gtk3-theme"])
    text = _theme_css(home, "light").read_text()
    assert "/themes/adw-gtk3/gtk-3.0/gtk.css" in text
    assert "/current/adw.css" in text
    assert _state(home) == "amontillado-light"


def test_leaves_an_existing_theme_alone(home: Path, gsettings: Path, adw_gtk3: Path) -> None:
    _config(home, {"libadwaita": {}})
    css = _theme_css(home)
    css.parent.mkdir(parents=True)
    css.write_text("/* mine */\n")
    main(["hook", "gtk3-theme"])
    assert css.read_text() == "/* mine */\n"
    assert _state(home) == "amontillado-dark"


def test_refuses_without_adw_gtk3(
    home: Path, gsettings: Path, adw_gtk3: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _config(home, {"libadwaita": {}})
    monkeypatch.setenv("XDG_DATA_DIRS", str(home / "empty"))
    with pytest.raises(SystemExit, match="missing: adw-gtk3-dark"):
        main(["hook", "gtk3-theme"])
    assert not _theme_css(home).exists()
    assert gsettings.read_text() == ""
    assert _state(home) == "Adwaita"


def test_refuses_without_gsettings(
    home: Path, adw_gtk3: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _config(home, {"libadwaita": {}})
    monkeypatch.setenv("PATH", str(home / "no-bin"))
    with pytest.raises(SystemExit, match=r"missing: gsettings"):
        main(["hook", "gtk3-theme"])
    assert not _theme_css(home).exists()


def test_needs_amo_variant(
    home: Path, gsettings: Path, adw_gtk3: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _config(home, {"libadwaita": {}})
    monkeypatch.delenv("AMO_VARIANT")
    with pytest.raises(SystemExit, match="AMO_VARIANT is not set"):
        main(["hook", "gtk3-theme"])
    assert gsettings.read_text() == ""


def test_needs_the_app_configured(home: Path, gsettings: Path, adw_gtk3: Path) -> None:
    _config(home, {"kitty": {}})
    with pytest.raises(SystemExit, match=r"theme.apps.libadwaita is not configured"):
        main(["hook", "gtk3-theme"])


def test_dry_run_changes_nothing(
    home: Path, gsettings: Path, adw_gtk3: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _config(home, {"libadwaita": {}})
    main(["hook", "gtk3-theme", "--dry-run"])
    out = capsys.readouterr().out
    assert f"would write {_theme_css(home)}" in out
    assert f"would set {SCHEMA_KEY} amontillado-dark" in out
    assert not _theme_css(home).exists()
    assert gsettings.read_text() == ""
