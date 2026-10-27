from __future__ import annotations

import logging
from pathlib import Path

import pytest

from amontillado.config import ConfigError, load_config


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    for variable in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(variable, raising=False)
    return tmp_path


def write_config(home: Path, text: str) -> None:
    path = home / ".config" / "amontillado" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_defaults_without_a_config_file(home: Path) -> None:
    config = load_config()
    assert config.library_roots == (home / ".local/share/amontillado/library",)
    assert config.nsfw_root == home / ".local/share/amontillado/library-nsfw"
    assert config.index_path == home / ".local/state/amontillado/index.sqlite"


def test_xdg_variables(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(home / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "conf"))
    (home / "conf" / "amontillado").mkdir(parents=True)
    (home / "conf" / "amontillado" / "config.yaml").write_text("library_roots: [/srv/walls]\n")
    config = load_config()
    assert config.library_roots == (home / "data/amontillado/library", Path("/srv/walls"))
    assert config.index_path == home / "state/amontillado/index.sqlite"


def test_relative_xdg_variable_is_ignored(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", "relative/data")
    assert load_config().library_roots == (home / ".local/share/amontillado/library",)


def test_config_adds_roots_and_moves_nsfw_root(home: Path) -> None:
    write_config(home, "library_roots: [~/walls, ~/walls, /srv/walls]\nnsfw_root: ~/private\n")
    config = load_config()
    assert config.library_roots == (
        home / ".local/share/amontillado/library",
        home / "walls",
        Path("/srv/walls"),
    )
    assert config.nsfw_root == home / "private"


def test_empty_config_file(home: Path) -> None:
    defaults = load_config()
    write_config(home, "")
    assert load_config() == defaults


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("library_roots: [", "not valid YAML"),
        ("- a\n- b\n", "must be a mapping"),
        ("library_roots: /srv/walls\n", "must be a list of paths"),
        ("library_roots: [3]\n", "is not a path"),
        ("library_roots: [walls]\n", "is not an absolute path"),
        ("nsfw_root: [/a, /b]\n", "is not a path"),
        ("nsfw_root: ~/.local/share/amontillado/library/nsfw\n", "overlaps library root"),
        ("library_roots: [~/walls]\nnsfw_root: ~/walls\n", "overlaps library root"),
        ("library_roots: [~/walls/sfw]\nnsfw_root: ~/walls\n", "overlaps library root"),
    ],
)
def test_bad_config(home: Path, text: str, message: str) -> None:
    write_config(home, text)
    with pytest.raises(ConfigError, match=message):
        load_config()


def test_symlinked_nsfw_root_inside_a_library_root(home: Path) -> None:
    (home / "walls" / "nsfw").mkdir(parents=True)
    (home / "link").symlink_to(home / "walls" / "nsfw")
    write_config(home, "library_roots: [~/walls]\nnsfw_root: ~/link\n")
    with pytest.raises(ConfigError, match="overlaps library root"):
        load_config()


def test_unknown_setting_warns(home: Path, caplog: pytest.LogCaptureFixture) -> None:
    write_config(home, "libary_roots: [/srv/walls]\n")
    with caplog.at_level(logging.WARNING):
        config = load_config()
    assert "unknown setting 'libary_roots'" in caplog.text
    assert len(config.library_roots) == 1
