from __future__ import annotations

import logging
import re
import shutil
from importlib.resources import files
from pathlib import Path

import pytest

from amontillado import config as config_module
from amontillado.cli import main
from amontillado.config import load_config
from amontillado.config_keys import (
    APP,
    KEYS,
    TOOL,
    TOOL_EXAMPLES,
    WIDTH,
    flag_help,
    names,
    template,
    tool_example_lines,
)

CONFIG = Path(".config/amontillado/config.yaml")
# A key's value line, commented out; an app's key documentation is indented further.
VALUE_LINE = re.compile(r"^(\s*)# ((\w+): .*)$")
# A tool example's name or key line, commented out.
TOOL_LINE = re.compile(r"^(\s*)# ((?:[\w-]+|  (?:cmd|description)):.*)$")
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
    assert names("edit") == config_module._EDIT_KEYS
    assert names(f"edit.tools.{TOOL}") == config_module._TOOL_KEYS
    for key in KEYS:
        assert key.meaning.endswith("."), key.path


def test_the_template_fits_and_loads_as_the_defaults(home: Path) -> None:
    text = template()
    assert all(len(line) <= WIDTH for line in text.splitlines())
    (home / CONFIG).parent.mkdir(parents=True)
    (home / CONFIG).write_text(text)
    assert load_config() == load_config(home / "none.yaml")


def _uncomment_tools(text: str) -> str:
    """The tool examples' YAML lines uncommented; their notes stay comments."""
    examples = set(tool_example_lines())
    return "\n".join(
        TOOL_LINE.sub(r"\1\2", line) if line in examples else line for line in text.splitlines()
    )


def test_every_commented_value_is_valid(home: Path, caplog: pytest.LogCaptureFixture) -> None:
    text = _uncomment_tools(template())
    uncommented = "\n".join(_uncomment(line) for line in text.splitlines())
    (home / CONFIG).parent.mkdir(parents=True)
    (home / CONFIG).write_text(uncommented)
    with caplog.at_level(logging.WARNING):
        config = load_config()
    assert not caplog.records
    assert config.theme.generator == "matugen"
    assert config.theme.wallpaper_reload == 'hyprctl hyprpaper reload ,"$AMO_WALLPAPER"'
    assert set(config.theme.apps) == EXAMPLE_APPS
    assert config.theme.apps["zed"].render_with == "matugen"
    assert config.edit.default_tool == "gimp"
    assert {name: tool.cmd for name, tool in config.edit.tools.items()} == {
        example.name: example.cmd for example in TOOL_EXAMPLES
    }


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


def test_config_check_parses_every_command(home: Path, caplog: pytest.LogCaptureFixture) -> None:
    text = (
        'api_key_command: "printf \'unclosed"\n'
        "crop: {viewer: 'eog \"$AMO_FILE\" |'}\n"
        "edit: {tools: {ok: {cmd: 'gimp \"$AMO_INPUT\" || true'}}}\n"
        "theme: {wallpaper: {reload: 'if true; then'}}\n"
    )
    with pytest.raises(SystemExit, match="3 problems"), caplog.at_level(logging.ERROR):
        _check(home, text)
    named = {line.split(":")[0] for line in caplog.messages}
    assert named == {"api_key_command", "crop.viewer", "theme.wallpaper.reload"}


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="needs shellcheck")
def test_config_check_shellcheck(home: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = home / "check.yaml"
    path.write_text("theme: {wallpaper: {reload: 'swww img $AMO_WALLPAPER'}}\n")
    main(["config", "check", str(path)])  # sh -n alone has nothing to say
    with pytest.raises(SystemExit, match="1 problem"), caplog.at_level(logging.ERROR):
        main(["config", "check", "--shellcheck", str(path)])
    assert "theme.wallpaper.reload: 1:10: note: Double quote" in caplog.text
    assert "[SC2086]" in caplog.text


def test_config_check_without_a_file(home: Path) -> None:
    with pytest.raises(SystemExit, match="no config file"):
        main(["config", "check"])
