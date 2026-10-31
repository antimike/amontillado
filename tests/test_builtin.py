from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from amontillado.builtin import BUILTINS
from amontillado.palette import BASE24_KEYS, ROLES, Palette, complete_variant
from amontillado.render import mustache_view, render_mustache

DARK = {f"base{i:02X}": f"#{i * 16:02x}{i * 8:02x}{255 - i * 16:02x}" for i in range(16)}


def _palette() -> Palette:
    variants = {"dark": complete_variant("dark", DARK), "light": complete_variant("light", DARK)}
    return Palette("Some 'quoted' \"name\"", variants, {})


def _render(name: str, variant: str = "dark") -> str:
    palette = _palette()
    return render_mustache(BUILTINS[name].text(), mustache_view(palette, variant))


@pytest.mark.parametrize("name", list(BUILTINS))
@pytest.mark.parametrize("variant", ["dark", "light"])
def test_every_template_renders(name: str, variant: str) -> None:
    output = _render(name, variant)
    assert "{{" not in output
    assert variant in output


@pytest.mark.parametrize("name", [n for n, t in BUILTINS.items() if n not in ("kitty", "dunst")])
def test_variables_only_templates_hold_every_key_and_role(name: str) -> None:
    variables = set(BUILTINS[name].variables())
    assert BUILTINS[name].complete is False
    for colour in (*BASE24_KEYS, *ROLES):
        assert f"{colour}-hex" in variables


def test_variables_in_order_of_first_use() -> None:
    variables = BUILTINS["json"].variables()
    assert variables[:3] == ["scheme-slug", "scheme-variant", "base00-hex"]
    assert len(variables) == len(set(variables))


def test_kitty_colours() -> None:
    output = _render("kitty")
    view = mustache_view(_palette(), "dark")
    assert f"color4 #{view['base0D-hex']}\n" in output
    assert f"active_tab_background #{view['accent-hex']}\n" in output
    assert re.findall(r"^color(\d+) ", output, re.MULTILINE) == [str(i) for i in range(22)]


def test_rofi_names_have_no_underscore() -> None:
    # rofi 2.0 fails to parse a theme whose variable names hold "_".
    names = re.findall(r"^\s+([^:\s]+):", _render("rofi"), re.MULTILINE)
    assert "on-accent" in names
    assert not [name for name in names if "_" in name]


def test_json_is_the_palette() -> None:
    data = json.loads(_render("json"))
    colours = _palette().variants["dark"]
    assert data["variant"] == "dark"
    assert data["base24"] == colours.base24
    assert data["roles"] == colours.roles


def test_shell_exports(tmp_path: Path) -> None:
    script = tmp_path / "colors.sh"
    script.write_text(_render("shell"))
    result = subprocess.run(
        ["sh", "-c", '. "$1" && printf "%s %s" "$AMO_VARIANT" "$AMO_ON_ACCENT"', "sh", script],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == f"dark {_palette().variants['dark'].roles['on_accent']}"
