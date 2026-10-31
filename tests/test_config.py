from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from amontillado.config import AppConfig, ConfigError, ThemeConfig, api_key, load_config


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
        ("api_key_command: [pass, show]\n", "must be a command line"),
        ("api_key_command: ' '\n", "must be a command line"),
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


@pytest.fixture
def no_key_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WALLHAVEN_API_KEY", raising=False)


def test_api_key_none_without_a_source(home: Path, no_key_variable: None) -> None:
    assert api_key(load_config()) is None


def test_api_key_from_the_environment_first(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WALLHAVEN_API_KEY", " env-key\n")
    write_config(home, "api_key_command: printf command-key\n")
    assert api_key(load_config()) == "env-key"


def test_api_key_from_the_command(home: Path, no_key_variable: None) -> None:
    write_config(home, "api_key_command: printf '%s\\n%s\\n' 'command key' second-line\n")
    assert api_key(load_config()) == "command key"


@pytest.mark.parametrize(
    ("command", "message"),
    [
        ("false", "failed with exit status 1"),
        ("true", "printed nothing"),
        ("/nonexistent/key-command", "cannot run"),
        ("printf 'unclosed", "cannot run"),
    ],
)
def test_api_key_command_errors(
    home: Path, no_key_variable: None, command: str, message: str
) -> None:
    write_config(home, f"api_key_command: {command!r}\n")
    with pytest.raises(ConfigError, match=message):
        api_key(load_config())


def test_api_key_command_output_never_in_errors(home: Path, no_key_variable: None) -> None:
    write_config(home, "api_key_command: sh -c 'echo secret-key; echo secret-err >&2; exit 2'\n")
    with pytest.raises(ConfigError) as exc:
        api_key(load_config())
    assert "secret" not in str(exc.value)


SHA = "ab" * 32

# The design's example block, with an https URL app added.
THEME = f"""
theme:
  cache: ~/.cache/theme
  profile: laptop
  generator: matugen
  variant: auto
  contrast: report
  wallpaper: {{reload: "hyprctl hyprpaper reload ,{{wallpaper}}"}}
  apps:
    kitty:    {{reload: "pkill -USR1 kitty"}}
    waybar:   {{source: builtin, template: gtk, output: waybar-colors.css}}
    zed:      {{source: matugen-themes, template: zed-colors.json, render_with: matugen}}
    rofi-alt: {{source: tinted, template: rofi, variant: light, output: rofi-light.rasi}}
    nvim:     {{}}
    bare:
    mytool:   {{source: path, path: ~/.config/mytool/theme.mustache, format: mustache}}
    pinned:   {{source: url, url: "https://x.org/t.mustache", sha256: {SHA}, format: mustache}}
"""


def test_theme_defaults(home: Path) -> None:
    theme = load_config().theme
    assert theme == ThemeConfig(cache=home / ".cache/theme")
    assert (theme.profile, theme.variant, theme.contrast, theme.generator) == (
        "default",
        "auto",
        "adjust",
        None,
    )


def test_theme_cache_follows_xdg(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / "cache"))
    assert load_config().theme.cache == home / "cache/theme"


def test_theme_block(home: Path) -> None:
    write_config(home, THEME)
    theme = load_config().theme
    assert (theme.cache, theme.profile, theme.generator, theme.contrast) == (
        home / ".cache/theme",
        "laptop",
        "matugen",
        "report",
    )
    assert theme.wallpaper_reload == ("hyprctl", "hyprpaper", "reload", ",{wallpaper}")
    apps = theme.apps
    assert list(apps) == ["kitty", "waybar", "zed", "rofi-alt", "nvim", "bare", "mytool", "pinned"]
    assert apps["kitty"] == AppConfig(reload=("pkill", "-USR1", "kitty"))
    assert apps["nvim"] == apps["bare"] == AppConfig()
    assert apps["zed"].render_with == "matugen"
    assert (apps["rofi-alt"].variant, apps["rofi-alt"].output) == ("light", "rofi-light.rasi")
    assert apps["mytool"].path == home / ".config/mytool/theme.mustache"
    assert (apps["pinned"].url, apps["pinned"].sha256) == ("https://x.org/t.mustache", SHA)


def _app(line: str) -> str:
    return f"theme:\n  apps:\n    a: {line}\n"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("theme: [kitty]\n", "theme must be a mapping"),
        ("theme: {cache: cache}\n", "theme.cache: cache is not an absolute path"),
        ("theme: {profile: current}\n", "theme.profile"),
        ("theme: {profile: .hidden}\n", "theme.profile"),
        ("theme: {profile: a/b}\n", "theme.profile"),
        ("theme: {generator: pywal}\n", "theme.generator: 'pywal' is not one of matugen, wallust"),
        ("theme: {variant: dusk}\n", "theme.variant"),
        ("theme: {contrast: strict}\n", "theme.contrast"),
        ("theme: {wallpaper: swaybg}\n", "theme.wallpaper must be a mapping"),
        ("theme: {wallpaper: {reload: [a, b]}}\n", "theme.wallpaper.reload must be a command"),
        ('theme: {wallpaper: {reload: "x \'"}}\n', "theme.wallpaper.reload: No closing"),
        ("theme: {wallpaper: {reload: 'x {image}'}}\n", "unknown placeholder {image}"),
        ("theme: {apps: [kitty]}\n", "theme.apps must be a mapping"),
        (_app("[x]"), "theme.apps.a must be a mapping"),
        (_app("{source: github}"), "theme.apps.a.source"),
        (_app("{format: jinja}"), "theme.apps.a.format"),
        (_app("{template: ''}"), "theme.apps.a.template"),
        (_app("{variant: dusk}"), "theme.apps.a.variant"),
        (_app("{reload: ''}"), "theme.apps.a.reload must be a command line"),
        (_app("{source: url, url: 'http://x/t', sha256: " + SHA + ", format: mustache}"), "https"),
        (_app("{source: url, url: 'https://x/t', sha256: abc, format: mustache}"), "SHA-256"),
        (_app("{source: url, url: 'https://x/t', sha256: " + SHA + "}"), "a.format: source url"),
        (_app("{source: tinted, url: 'https://x/t'}"), "for source url only"),
        (_app("{source: path, format: mustache}"), "a.path: source path needs"),
        (_app("{source: path, path: rel, format: mustache}"), "not an absolute path"),
        (_app("{source: tinted, path: /x}"), "for source path only"),
        (_app("{source: tinted, render_with: matugen}"), "matugen renders format matugen"),
        (_app("{source: path, path: /t, format: mustache, render_with: matugen}"), "render_with"),
        (_app("{render_with: tinty}"), "theme.apps.a.render_with"),
        (_app("{output: sub/file.css}"), "is not a file name"),
        (_app("{output: .hidden}"), "is not a file name"),
        (_app("{output: theme.yaml}"), "amontillado's own"),
        ("theme:\n  apps:\n    a: {output: x.css}\n    b: {output: x.css}\n", "also a's"),
    ],
)
def test_bad_theme(home: Path, text: str, message: str) -> None:
    write_config(home, text)
    with pytest.raises(ConfigError, match=re.escape(message)):
        load_config()


def test_render_with_matugen_for_a_matugen_path_template(home: Path) -> None:
    write_config(home, _app("{source: path, path: /t.css, format: matugen, render_with: matugen}"))
    assert load_config().theme.apps["a"].render_with == "matugen"


def test_unknown_theme_keys_warn(home: Path, caplog: pytest.LogCaptureFixture) -> None:
    write_config(home, "theme:\n  varient: dark\n  apps:\n    kitty: {relaod: x}\n")
    with caplog.at_level(logging.WARNING):
        load_config()
    assert "unknown setting 'theme.varient'" in caplog.text
    assert "unknown setting 'theme.apps.kitty.relaod'" in caplog.text


@pytest.mark.parametrize("value", ["off", "'off'"])
def test_contrast_off_unquoted(home: Path, value: str) -> None:
    write_config(home, f"theme: {{contrast: {value}}}\n")
    assert load_config().theme.contrast == "off"
