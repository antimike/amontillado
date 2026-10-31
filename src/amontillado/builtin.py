"""The built-in templates: mustache files shipped in `amontillado/templates/`.

docs/design.md, "Theme engine (v0.2)", "Template sources". Each is variables-only (every base24
key and every role, in the app's own syntax, for the user's config to map) except where the app
has no variables: kitty's file sets its colour options, dunst's is a small complete drop-in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib.resources import files

# A mustache tag's name; sections ({{#x}}, {{^x}}) and their ends ({{/x}}) name a variable too.
_TAG = re.compile(r"\{\{\s*[#^/&]?\s*([\w.-]+)\s*\}\}")


@dataclass(frozen=True)
class Builtin:
    """One built-in template: its name (the app's), default output file and what it is for."""

    name: str
    output: str
    complete: bool
    description: str

    def text(self) -> str:
        return (files("amontillado") / "templates" / f"{self.name}.mustache").read_text()

    def variables(self) -> list[str]:
        """The mustache variables the template uses, in order of first use."""
        return list(dict.fromkeys(_TAG.findall(self.text())))


BUILTINS = {
    template.name: template
    for template in (
        Builtin("kitty", "kitty.conf", False, "colour options; include from kitty.conf"),
        Builtin(
            "gtk",
            "colors.css",
            False,
            "@define-color per colour; @import from waybar, swaync, wlogout, gtk.css",
        ),
        Builtin("rofi", "colors.rasi", False, "a * { } block (roles hyphenated: on-accent)"),
        Builtin("hyprland", "hyprland.lua", False, 'a Lua table of "rrggbb", for dofile()'),
        Builtin("hyprlock", "hyprlock.conf", False, "hyprlang $variables of rrggbb"),
        Builtin("sway", "sway", False, "set $variable per colour; include from the config"),
        Builtin("dunst", "dunst.conf", True, "a dunstrc.d drop-in: the urgency colours"),
        Builtin("nvim", "palette.lua", False, "a Lua table, for a lush spec"),
        Builtin("shell", "colors.sh", False, "export AMO_BASE00=... ; source from a shell"),
        Builtin("json", "palette.json", False, "the palette as JSON"),
    )
}
