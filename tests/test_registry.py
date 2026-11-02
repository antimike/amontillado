from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from amontillado.palette import BASE24_KEYS, ROLES, Palette, complete_variant
from amontillado.registry import FETCHED, RegistryError, find, parse, registry, text, variables
from amontillado.render import mustache_view, render_mustache

BUILTINS = registry()["builtin"]
DARK = {f"base{i:02X}": f"#{i * 16:02x}{i * 8:02x}{255 - i * 16:02x}" for i in range(16)}


def _palette() -> Palette:
    variants = {"dark": complete_variant("dark", DARK), "light": complete_variant("light", DARK)}
    return Palette("Some 'quoted' \"name\"", variants, {})


def _render(name: str, variant: str = "dark") -> str:
    palette = _palette()
    return render_mustache(text(find("builtin", name)), mustache_view(palette, variant))


@pytest.mark.parametrize("name", list(BUILTINS))
@pytest.mark.parametrize("variant", ["dark", "light"])
def test_every_template_renders(name: str, variant: str) -> None:
    output = _render(name, variant)
    assert "{{" not in output
    assert variant in output


@pytest.mark.parametrize("name", [n for n, t in BUILTINS.items() if n not in ("kitty", "dunst")])
def test_variables_only_templates_hold_every_key_and_role(name: str) -> None:
    used = set(variables(text(BUILTINS[name])))
    assert BUILTINS[name].complete is False
    for colour in (*BASE24_KEYS, *ROLES):
        assert f"{colour}-hex" in used


def test_variables_in_order_of_first_use() -> None:
    used = variables(text(BUILTINS["json"]))
    assert used[:3] == ["scheme-slug", "scheme-variant", "base00-hex"]
    assert len(used) == len(set(used))


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


def test_builtin_files_match_the_registry() -> None:
    shipped = Path(__file__).parent.parent / "src" / "amontillado" / "templates"
    assert {path.stem for path in shipped.glob("*.mustache")} == set(BUILTINS)


def test_every_fetched_entry_is_pinned() -> None:
    for source in FETCHED:
        for entry in registry()[source].values():
            assert entry.commit and len(entry.commit) == 40, entry
            assert entry.sha256 and len(entry.sha256) == 64, entry
            assert entry.url == (
                f"https://raw.githubusercontent.com/{entry.repository}/{entry.commit}/{entry.path}"
            )


def test_find_defaults_to_the_first_source_with_the_template() -> None:
    assert find(None, "kitty").source == "builtin"
    assert find(None, "foot").source == "tinted"
    assert find(None, "zed").source == "matugen-themes"
    assert find("pywal", "kitty").format == "pywal"
    with pytest.raises(RegistryError, match="no source has a template 'nope'"):
        find(None, "nope")
    with pytest.raises(RegistryError, match="tinted has no template 'hyprlock'"):
        find("tinted", "hyprlock")


def test_parse_rejects_an_unlisted_repository() -> None:
    data = {
        "version": 1,
        "repositories": {},
        "sources": {
            "tinted": {"x": {"repository": "a/b", "path": "t", "output": "o", "complete": True}}
        },
    }
    with pytest.raises(RegistryError, match=r"sources\.tinted\.x: needs a listed repository"):
        parse(data)
