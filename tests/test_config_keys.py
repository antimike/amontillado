from __future__ import annotations

import logging
import re
from importlib.resources import files
from pathlib import Path

import pytest

from amontillado import config as config_module
from amontillado.cli import main
from amontillado.config import load_config
from amontillado.config_keys import APP, KEYS, WIDTH, flag_help, names, template

CONFIG = Path(".config/amontillado/config.yaml")
# A key's value line, commented out; an app's key documentation is indented further.
VALUE_LINE = re.compile(r"^(\s*)# ((\w+): .*)$")
EXAMPLE_APPS = {"kitty", "rofi", "waybar", "zed", "mytool"}


def _uncomment(line: str) -> str:
    match = VALUE_LINE.match(line)
    if match is None or match[3] not in {key.name for key in KEYS} | EXAMPLE_APPS:
        return line
    return match[1] + match[2]


def test_the_shipped_template_is_generated_from_the_table() -> None:
    shipped = (files("amontillado") / "config.template.yaml").read_text()
    assert shipped == template(), "regenerate it: just config-template"


def test_the_table_covers_every_key_the_config_reads() -> None:
    assert names(None) == config_module._KNOWN_KEYS
    assert names("theme") == config_module._THEME_KEYS
    assert names("theme.wallpaper") == {"reload"}
    assert names("crop") == config_module._CROP_KEYS
    assert names(f"theme.apps.{APP}") == config_module._APP_KEYS
    for key in KEYS:
        assert key.meaning.endswith("."), key.path


def test_the_template_fits_and_loads_as_the_defaults(home: Path) -> None:
    text = template()
    assert all(len(line) <= WIDTH for line in text.splitlines())
    (home / CONFIG).parent.mkdir(parents=True)
    (home / CONFIG).write_text(text)
    assert load_config() == load_config(home / "none.yaml")


def test_every_commented_value_is_valid(home: Path, caplog: pytest.LogCaptureFixture) -> None:
    uncommented = "\n".join(_uncomment(line) for line in template().splitlines())
    (home / CONFIG).parent.mkdir(parents=True)
    (home / CONFIG).write_text(uncommented)
    with caplog.at_level(logging.WARNING):
        config = load_config()
    assert not caplog.records
    assert config.theme.generator == "matugen"
    assert config.theme.wallpaper_reload == ("hyprctl", "hyprpaper", "reload", ",{wallpaper}")
    assert set(config.theme.apps) == EXAMPLE_APPS
    assert config.theme.apps["zed"].render_with == "matugen"


def test_flag_help_names_the_key_and_its_default() -> None:
    assert (
        flag_help("theme.variant", "The variant") == "The variant (overrides theme.variant: auto)."
    )
    assert flag_help("theme.generator", "G") == "G (overrides theme.generator)."
    assert flag_help("theme.hues").startswith("Who assigns base08-base0F")


def test_config_init(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["config", "init"])
    assert (home / CONFIG).read_text() == template()
    (home / CONFIG).write_text("theme: {}\n")
    with pytest.raises(SystemExit, match="exists: --force replaces it"):
        main(["config", "init"])
    assert (home / CONFIG).read_text() == "theme: {}\n"
    main(["config", "init", "--force"])
    assert (home / CONFIG).read_text() == template()
    capsys.readouterr()
    main(["config", "init", "--stdout"])
    assert capsys.readouterr().out == template()


def _check(home: Path, text: str) -> None:
    path = home / "check.yaml"
    path.write_text(text)
    main(["config", "check", str(path)])


def test_config_check_passes_a_good_config(home: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        _check(home, "theme:\n  apps:\n    kitty: {}\n    nvim: {}\n")
    assert "ok (2 apps)" in caplog.text


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("theme: {variant: dusk}\n", "theme.variant: 'dusk' is not one of"),
        ("theme: {varient: dark}\n", "1 problem"),
        ("theme: {apps: {kitty: {template: nope}}}\n", "1 problem"),
        # A fetched template amo theme sync has not kept.
        ("theme: {apps: {rofi: {source: tinted}}}\n", "1 problem"),
        (
            "theme: {apps: {a: {template: kitty}, b: {template: kitty}}}\n",
            "1 problem",
        ),
    ],
)
def test_config_check_fails(home: Path, text: str, error: str) -> None:
    with pytest.raises(SystemExit, match=re.escape(error)):
        _check(home, text)


def test_config_check_names_each_problem(home: Path, caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(SystemExit), caplog.at_level(logging.WARNING):
        _check(home, "theme: {apps: {a: {template: kitty}, b: {template: kitty}}}\n")
    assert "theme.apps.b: output kitty.conf is also a's" in caplog.text


def test_config_check_without_a_file(home: Path) -> None:
    with pytest.raises(SystemExit, match="no config file"):
        main(["config", "check"])
