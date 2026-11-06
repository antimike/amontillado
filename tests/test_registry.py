from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from amontillado.colour import contrast_ratio
from amontillado.contrast import adjust
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


# Templates that fill a fixed set of names rather than one variable per key and role.
FIXED_NAME_BUILTINS = ("kitty", "dunst", "libadwaita", "libadwaita-vars")


@pytest.mark.parametrize("name", [n for n in BUILTINS if n not in FIXED_NAME_BUILTINS])
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


# libadwaita 1.9's @define-color names (gtk.css in the library's resources), less the GNOME
# palette (blue_1 ... dark_5) and what libadwaita derives from these (theme_*, insensitive_*).
LIBADWAITA_NAMES = {
    *(
        f"{name}_{part}"
        for name in ("accent", "destructive", "success", "warning", "error")
        for part in ("bg_color", "fg_color", "color")
    ),
    *(f"{name}_{part}" for name in ("window", "view") for part in ("bg_color", "fg_color")),
    *(
        f"{name}_{part}"
        for name in ("headerbar", "sidebar", "secondary_sidebar")
        for part in ("bg_color", "fg_color", "border_color", "backdrop_color", "shade_color")
    ),
    "headerbar_darker_shade_color",
    *(
        f"{name}_{part}"
        for name in ("card", "dialog", "popover", "thumbnail")
        for part in ("bg_color", "fg_color")
    ),
    "card_shade_color",
    "popover_shade_color",
    "shade_color",
    "scrollbar_outline_color",
    "borders",
}
# gruvbox dark and light, hard (tinted-theming/schemes, MIT).
GRUVBOX = {
    "dark": "1d2021 3c3836 504945 665c54 bdae93 d5c4a1 ebdbb2 fbf1c7"
    " fb4934 fe8019 fabd2f b8bb26 8ec07c 83a598 d3869b d65d0e",
    "light": "f9f5d7 ebdbb2 d5c4a1 bdae93 665c54 504945 3c3836 282828"
    " 9d0006 af3a03 b57614 79740e 427b58 076678 8f3f71 d65d0e",
}


def _define_colours(output: str) -> dict[str, str]:
    return dict(re.findall(r"^@define-color (\w+) (.+);$", output, re.MULTILINE))


@pytest.mark.parametrize("variant", ["dark", "light"])
def test_libadwaita_defines_every_named_colour(variant: str) -> None:
    assert set(_define_colours(_render("libadwaita", variant))) == LIBADWAITA_NAMES


@pytest.mark.parametrize("variant", ["dark", "light"])
def test_libadwaita_foregrounds_contrast_with_their_backgrounds(variant: str) -> None:
    colours = {f"base{i:02X}": f"#{c}" for i, c in enumerate(GRUVBOX[variant].split())}
    adjusted, _ = adjust(complete_variant(variant, colours), variant)
    palette = Palette("gruvbox", {variant: adjusted}, {})
    names = _define_colours(
        render_mustache(text(find("builtin", "libadwaita")), mustache_view(palette, variant))
    )
    pairs = [(name, name.replace("_fg_", "_bg_")) for name in names if "_fg_" in name]
    assert len(pairs) == 14
    for foreground, background in pairs:
        ratio = contrast_ratio(names[foreground], names[background])
        assert ratio >= 4.5, (foreground, background, ratio)


# libadwaita 1.9's colour variables (the :root blocks of gtk.css in the library's resources),
# less the accent presets (--accent-blue ... --accent-slate: the system accent's choices, which
# the stylesheet never reads and the named accent colours override).
LIBADWAITA_VARIABLES = {
    *(f"--{name.replace('_', '-')}" for name in LIBADWAITA_NAMES if name != "borders"),
    "--active-toggle-bg-color",
    "--active-toggle-fg-color",
    "--overview-bg-color",
    "--overview-fg-color",
    *(
        f"--{family}-{step}"
        for family in ("blue", "green", "yellow", "orange", "red", "purple", "brown")
        for step in range(1, 6)
    ),
    *(f"--{grey}-{step}" for grey in ("light", "dark") for step in range(1, 6)),
}


def _gruvbox_render(name: str, variant: str) -> str:
    colours = {f"base{i:02X}": f"#{c}" for i, c in enumerate(GRUVBOX[variant].split())}
    adjusted, _ = adjust(complete_variant(variant, colours), variant)
    palette = Palette("gruvbox", {variant: adjusted}, {})
    return render_mustache(text(find("builtin", name)), mustache_view(palette, variant))


def _root_variables(output: str) -> dict[str, str]:
    (block,) = re.findall(r"^:root \{$(.*?)^\}$", output, re.MULTILINE | re.DOTALL)
    return dict(re.findall(r"^\s+(--[\w-]+): (#[0-9a-f]{6});$", block, re.MULTILINE))


@pytest.mark.parametrize("variant", ["dark", "light"])
def test_libadwaita_vars_holds_the_libadwaita_colours(variant: str) -> None:
    # The same @define-color block, so gtk-3.0 and gtk-4.0 agree.
    assert _define_colours(_render("libadwaita-vars", variant)) == _define_colours(
        _render("libadwaita", variant)
    )


@pytest.mark.parametrize("variant", ["dark", "light"])
def test_libadwaita_vars_defines_every_variable(variant: str) -> None:
    output = _render("libadwaita-vars", variant)
    from_names = {f"--{name.replace('_', '-')}" for name in _define_colours(output)}
    root = _root_variables(output)
    assert len(root) == 54
    assert LIBADWAITA_VARIABLES <= from_names | set(root)
    # Every pinned standalone colour is its *_color name's value.
    names = _define_colours(output)
    for name in ("accent", "destructive", "success", "warning", "error"):
        assert root[f"--{name}-color"] == names[f"{name}_color"]


@pytest.mark.parametrize("variant", ["dark", "light"])
def test_libadwaita_vars_contrast(variant: str) -> None:
    output = _gruvbox_render("libadwaita-vars", variant)
    names, root = _define_colours(output), _root_variables(output)
    # The standalone colours are text on libadwaita's surfaces.
    for name in ("accent", "destructive", "success", "warning", "error"):
        for surface in ("window", "view", "card", "dialog", "popover", "sidebar", "headerbar"):
            ratio = contrast_ratio(root[f"--{name}-color"], names[f"{surface}_bg_color"])
            assert ratio >= 4.5, (name, surface, ratio)
    for name in ("active-toggle", "overview"):
        ratio = contrast_ratio(root[f"--{name}-fg-color"], root[f"--{name}-bg-color"])
        assert ratio >= 4.5, (name, ratio)
    # GNOME's extremes, as apps pair them (text on --dark-5, on --light-1).
    assert contrast_ratio(root["--light-1"], root["--dark-5"]) >= 7.0


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
