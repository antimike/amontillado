"""Every config key in one table: its meaning, trade-offs and default.

The table generates the commented config template that `amo config init` writes
(`config.template.yaml`, shipped in the package and kept equal to `template()` by a test) and
the `--help` text of each flag that overrides a key (`flag_help`). docs/design.md links to the
template rather than repeating it; `amontillado.config` checks the values.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass

from amontillado import yamlio
from amontillado.config import (
    CONTRAST_CHOICES,
    FORMATS,
    GENERATORS,
    HUES_CHOICES,
    PREVIEWS,
    RENDERERS,
    SOURCES,
    VARIANT_CHOICES,
)

WIDTH = 100
# The placeholder under theme.apps for an app's own keys.
APP = "<app>"
# The placeholder under edit.tools for a tool's own keys.
TOOL = "<tool>"


@dataclass(frozen=True)
class Key:
    # Dotted, e.g. "theme.variant"; an app's keys are "theme.apps.<app>.source".
    path: str
    meaning: str
    # The value the template shows commented out: the default, or an example of a key that has
    # none. None for a section (a mapping of keys) and for an app's keys, which the template
    # lists rather than sets.
    value: str | None = None
    # Said in the comment and in flag help; None when `meaning` says what an unset key does.
    default: str | None = None
    choices: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.path.rsplit(".", 1)[-1]


def _or(choices: tuple[str, ...]) -> str:
    return ", ".join(choices[:-1]) + f" or {choices[-1]}"


KEYS: tuple[Key, ...] = (
    Key(
        "library_roots",
        "Library roots searched in addition to the default, $XDG_DATA_HOME/amontillado/library "
        "(where amo fetch and amo add put pictures). Absolute paths; ~ is expanded.",
        "[~/Pictures/wallpapers]",
    ),
    Key(
        "nsfw_root",
        "Where sketchy and nsfw pictures live, instead of $XDG_DATA_HOME/amontillado/"
        "library-nsfw. It may not be, contain or lie inside a library root (symlinks "
        "resolved), since a recursive search would then reach NSFW images.",
        "~/.local/share/amontillado/library-nsfw",
    ),
    Key(
        "api_key_command",
        "A command printing the Wallhaven API key on its first line, run by sh -c; "
        "WALLHAVEN_API_KEY wins over it. Needed for nsfw results. The "
        "key is never logged or written anywhere.",
        "pass show wallhaven/api-key",
    ),
    Key("crop", "amo crop --interactive: how it shows the picture and the box being placed."),
    Key(
        "crop.preview",
        "auto (kitty in a terminal that speaks the kitty graphics protocol, found from "
        "KITTY_WINDOW_ID, TERM or TERM_PROGRAM: kitty, ghostty, WezTerm; else viewer), kitty "
        "(drawn in the terminal) or viewer (a preview file, rewritten after each key, shown "
        "by crop.viewer). kitty is immediate; a viewer works anywhere but must reload a file "
        "that changes.",
        "auto",
        default="auto",
        choices=PREVIEWS,
    ),
    Key(
        "crop.viewer",
        "The image viewer for preview: viewer, started once by sh -c with AMO_FILE (the "
        'preview file) in its environment; quote it ("$AMO_FILE"). It must reload the file '
        "when it changes "
        "(eog, gThumb and Gwenview do; feh needs --reload; xdg-open opens whatever the "
        "desktop's default is).",
        "'xdg-open \"$AMO_FILE\"'",
    ),
    Key(
        "edit",
        "amo edit: the editors it runs on a copy of a picture's file, by name (docs/design.md, "
        '"Editing").',
    ),
    Key(
        "edit.default_tool",
        "The tool amo edit runs without --tool or --extcmd: a name under edit.tools. Unset: "
        "amo edit needs one of those flags.",
        "gimp",
    ),
    Key(
        "edit.tools",
        "Editors by name. A tool's cmd runs with sh -c in a fresh working directory inside the "
        "record (.amo/edit-*), with AMO_INPUT (a copy of the file being edited), AMO_OUTPUT "
        "(where a result may be written; it does not exist yet) and AMO_WORKDIR (that "
        "directory) added to your environment, so a cmd can also read variables you set "
        '(STYLE=x amo edit ...). Quote them ("$AMO_INPUT"). It must block until you are done: '
        "an editor that hands the file to a running instance and returns finds nothing. The "
        "result is AMO_OUTPUT if it "
        "exists, else the one image in the working directory (or below it) that is new or "
        "changed; files in the editor's own format (.xcf, .kra) are ignored, so export into "
        "the folder the editor opens in.",
    ),
    Key(
        f"edit.tools.{TOOL}.cmd",
        "The command line, run by sh -c.",
    ),
    Key(
        f"edit.tools.{TOOL}.description",
        "One line on what the tool is for, shown by amo edit --list-tools.",
    ),
    Key(
        "theme",
        'The theme engine: amo palette and amo theme (docs/design.md, "Theme engine (v0.2)").',
    ),
    Key(
        "theme.cache",
        "Where profiles are rendered: <cache>/<profile>/ and the current link, which app "
        "configs include from. Default $XDG_CACHE_HOME/theme.",
        "~/.cache/theme",
    ),
    Key(
        "theme.profile",
        "The profile amo theme apply writes: a name in the cache, not current and not "
        "starting with '.'. A second profile keeps its own files (another monitor, a test "
        "theme) and is activated by pointing current at it.",
        "default",
        default="default",
    ),
    Key(
        "theme.generator",
        f"The program that makes a picture's palette (the neutral ramp and the accent): "
        f"{_or(GENERATORS)}. Unset: the first installed, in that order. matugen gives both "
        "variants in one run and Material's accents; wallust is the fallback without it.",
        "matugen",
        choices=GENERATORS,
    ),
    Key(
        "theme.hues",
        "Who assigns base08-base0F (ANSI colours 1-6 and 9-14) of a picture's palette: "
        "amontillado (fixed named hues, so red stays red, with chroma and lightness from the "
        "picture) or generator (its own colours: matugen 4.2's are clustering, often off "
        "their hue or as dark as the background, so contrast fixes cannot save them).",
        "amontillado",
        default="amontillado",
        choices=HUES_CHOICES,
    ),
    Key(
        "theme.variant",
        "Which of the palette's variants is applied: auto (light when the picture's lightness "
        "is above 0.65, else dark), dark or light. An app's own variant wins. A variant the "
        "palette lacks warns and the app gets the one it has; nothing is inverted.",
        "auto",
        default="auto",
        choices=VARIANT_CHOICES,
    ),
    Key(
        "theme.contrast",
        "What happens to a colour pair below its WCAG contrast minimum: adjust (move the "
        "foreground, then the accent as a last resort, in lightness; each change logged and "
        "listed under adjusted), report (log the pair, change nothing) or off. adjust keeps "
        "text readable at the cost of colours a little off the source's.",
        "adjust",
        default="adjust",
        choices=CONTRAST_CHOICES,
    ),
    Key("theme.wallpaper", "The wallpaper hook."),
    Key(
        "theme.wallpaper.reload",
        "A command run last after each apply, by sh -c with AMO_WALLPAPER (the picture; "
        "unset, and the command skipped if it names it, when the theme has none), "
        "AMO_PROFILE, AMO_DIR (the profile's directory) and AMO_VARIANT (dark or light: the "
        "variant of an app without its own) in its environment. Quote them "
        '("$AMO_WALLPAPER"). Setting the wallpaper stays your command: amontillado only '
        "knows which picture belongs to the theme.",
        "'hyprctl hyprpaper reload ,\"$AMO_WALLPAPER\"'",
    ),
    Key(
        "theme.apps",
        "The apps to theme, one entry per app by name; each renders one file into the "
        "profile, which the app's own config includes. Every key of an app is optional: {} "
        "renders the built-in template of that name. amo theme templates lists the templates.",
    ),
    Key(
        f"theme.apps.{APP}.source",
        f"Where the template comes from: {_or(SOURCES)}. builtin is shipped and "
        "variables-only; tinted (tinted-theming), matugen-themes and pywal (pywal16) are "
        "fetched by amo theme sync, pinned; url is one file you pin; path is your own file. "
        "Default: the first with a template for the app, in the order builtin, tinted, "
        "matugen-themes, pywal.",
        choices=SOURCES,
    ),
    Key(
        f"theme.apps.{APP}.template",
        "The registry entry within the source, when it has several for the app (rofi-colors). "
        "Default: the app's name.",
    ),
    Key(
        f"theme.apps.{APP}.format",
        f"The template's language: {_or(FORMATS)}. Default: the source's; required for url "
        "and path.",
        choices=FORMATS,
    ),
    Key(
        f"theme.apps.{APP}.url",
        "For source url: the template at a commit URL (https://). Pinned, since some outputs "
        "are code that runs at every theme switch (a Lua file, a sourced shell file).",
    ),
    Key(
        f"theme.apps.{APP}.sha256",
        "For source url: the file's SHA-256, as hex. amo theme sync keeps no file that differs.",
    ),
    Key(
        f"theme.apps.{APP}.path",
        "For source path: your template file. Not resolved, so a symlink you swap is followed.",
    ),
    Key(
        f"theme.apps.{APP}.output",
        "The file name in the profile directory. Default: the registry's; required for url "
        "and path.",
    ),
    Key(
        f"theme.apps.{APP}.reload",
        "A command run after the swap, as theme.wallpaper.reload, but AMO_VARIANT is this "
        "app's. A failure warns: the app may not be running.",
    ),
    Key(
        f"theme.apps.{APP}.variant",
        "This app's variant, over theme.variant and --variant.",
        choices=VARIANT_CHOICES,
    ),
    Key(
        f"theme.apps.{APP}.render_with",
        f"Who renders a matugen-format template: {_or(RENDERERS)}. matugen renders from "
        "the picture with its own colours, not the palette's: the app misses the contrast "
        "adjustments and the named hues, and with a preset palette gets colours of the "
        "same accent hue only. Needs matugen >= 4 at every apply.",
        default="amontillado",
        choices=RENDERERS,
    ),
)

# Commented examples under theme.apps.
APP_EXAMPLES = (
    'kitty: {reload: "pkill -USR1 kitty"}',
    "rofi: {source: tinted}",
    'waybar: {template: gtk, output: waybar-colors.css, reload: "pkill -USR2 waybar"}',
    "zed: {source: matugen-themes, render_with: matugen}",
    "mytool: {source: path, path: ~/mytool.mustache, format: mustache, output: mytool.conf}",
    "",
    "libadwaita >= 1.6 takes its accent, success, warning and error text from the desktop's",
    "colour scheme, not the file: a reload that sets the scheme to the variant keeps it",
    "readable (docs/colour-scheme-hooks.md). One of, or no reload to leave the scheme alone:",
    "libadwaita:",
    """  reload: 'gsettings set org.gnome.desktop.interface color-scheme "prefer-$AMO_VARIANT"'""",
    """  # reload: 'darkman set "$AMO_VARIANT"'""",
    "",
    "GTK4 only: libadwaita-vars also sets that text and GNOME's palette (--blue-3 ...), for",
    "gtk-4.0/gtk.css; libadwaita then serves gtk-3.0 (adw-gtk3) alone:",
    "gtk4: {template: libadwaita-vars}",
)


@dataclass(frozen=True)
class ToolExample:
    """A commented example under edit.tools."""

    name: str
    cmd: str
    description: str
    note: str = ""


# Commented examples under edit.tools; tests/test_config_keys.py loads them uncommented.
TOOL_EXAMPLES = (
    ToolExample(
        "gimp",
        'gimp -n "$AMO_INPUT"',
        "GIMP; File > Overwrite the copy, or Export As into its folder",
        "-n starts a new GIMP: without it the file goes to a running one and gimp returns at once.",
    ),
    ToolExample(
        "krita",
        'krita "$AMO_INPUT"',
        "Krita; File > Export into its folder",
        "With Krita's 'Allow only one instance' setting on and Krita running, krita returns "
        "at once.",
    ),
    ToolExample("pinta", 'pinta "$AMO_INPUT"', "Pinta; save over the copy"),
    ToolExample(
        "darktable",
        'darktable --library :memory: "$AMO_INPUT"',
        "darktable's darkroom; export (to darktable_exported/ by default)",
        ":memory: keeps the copy out of your darktable library and its lock.",
    ),
    ToolExample(
        "darktable-cli",
        'darktable-cli "$AMO_INPUT" "$AMO_OUTPUT" --style "${STYLE:?a darktable style}"',
        "a darktable style, no window; STYLE=<name> amo edit ...",
    ),
    ToolExample(
        "rawtherapee",
        'rawtherapee "$AMO_INPUT"',
        "RawTherapee; Save current image into its folder",
    ),
    ToolExample(
        "rawtherapee-cli",
        'rawtherapee-cli -Y -o "$AMO_WORKDIR" -p "${PROFILE:?a .pp3 file}" -c "$AMO_INPUT"',
        "a RawTherapee profile, no window; PROFILE=<file.pp3>; writes JPEG",
        "Writes <name>.jpg into the working directory (over the copy if it is a JPEG); -n "
        "before -c writes PNG.",
    ),
    ToolExample(
        "satty",
        'satty -f "$AMO_INPUT" -o "$AMO_WORKDIR/annotated.png" --early-exit',
        "annotate, blur or redact; saving writes a PNG and closes it",
    ),
    ToolExample(
        "magick-modulate",
        'magick "$AMO_INPUT" -modulate 100,"${SATURATION:-80}" "$AMO_OUTPUT"',
        "ImageMagick, no window; saturation to SATURATION% (default 80)",
    ),
    ToolExample(
        "inkscape",
        'inkscape "$AMO_INPUT"',
        "Inkscape; Export as PNG into its folder (a vector editor, clumsy for bitmaps)",
    ),
)

_BY_PATH = {key.path: key for key in KEYS}


def key(path: str) -> Key:
    """The table's entry for `path`. Raises KeyError."""
    return _BY_PATH[path]


def names(section: str | None) -> frozenset[str]:
    """The names of the keys directly under `section` (None: the top level)."""
    prefix = "" if section is None else f"{section}."
    return frozenset(
        k.name for k in KEYS if k.path.startswith(prefix) and "." not in k.path[len(prefix) :]
    )


def flag_help(path: str, lead: str | None = None) -> str:
    """The --help of a flag overriding config key `path`: `lead` (default the key's meaning),
    then which key it overrides, with the key's default."""
    entry = key(path)
    text = lead or entry.meaning
    default = f": {entry.default}" if entry.default is not None else ""
    return f"{text} (overrides {path}{default})."


def _comment(text: str, indent: str, lead: str = "", hang: str = "") -> list[str]:
    return textwrap.wrap(
        text,
        WIDTH,
        initial_indent=f"{indent}# {lead}",
        subsequent_indent=f"{indent}# {hang}",
        break_on_hyphens=False,
    )


def _described(entry: Key) -> str:
    if entry.default is not None and f"Default: {entry.default}" not in entry.meaning:
        return f"{entry.meaning} Default: {entry.default}."
    return entry.meaning


def template() -> str:
    """The commented config template: every key at its default (or an example), commented
    out, under its meaning. Sections stay live so that a key uncommented under one parses."""
    lines = [
        "# amontillado's config file, $XDG_CONFIG_HOME/amontillado/config.yaml. Written by",
        "# `amo config init`; `amo config check` validates it. Every key is optional and",
        "# commented out at its default or with an example: uncomment and change what you need.",
    ]
    for entry in KEYS:
        if any(entry.path.startswith(f"{section}.{name}.") for section, name in _ENTRIES.items()):
            continue
        depth = entry.path.count(".")
        indent = "  " * depth
        lines.append("")
        lines.extend(_comment(_described(entry), indent))
        if entry.value is None:
            lines.append(f"{indent}{entry.name}:")
        else:
            lines.append(f"{indent}# {entry.name}: {entry.value}")
        if entry.path in _ENTRIES:
            lines.extend(_entry_keys(entry.path, indent + "  "))
        if entry.path == "theme.apps":
            lines.append(f"{indent}  #")
            lines.extend(
                f"{indent}  # {example}" if example else f"{indent}  #" for example in APP_EXAMPLES
            )
        if entry.path == "edit.tools":
            lines.extend(tool_example_lines(indent + "  "))
    return "\n".join(lines) + "\n"


# Sections holding named entries, and the placeholder for an entry's name in KEYS.
_ENTRIES = {"theme.apps": APP, "edit.tools": TOOL}
_ENTRY_KINDS = {"theme.apps": "An app's", "edit.tools": "A tool's"}


def _entry_keys(section: str, indent: str) -> list[str]:
    lines = [f"{indent}# {_ENTRY_KINDS[section]} keys:"]
    prefix = f"{section}.{_ENTRIES[section]}."
    for entry in KEYS:
        if entry.path.startswith(prefix):
            lines.extend(_comment(f"{entry.name}: {_described(entry)}", indent, "  ", "      "))
    return lines


def tool_example_lines(indent: str = "    ") -> list[str]:
    """The commented examples under edit.tools, as the template has them."""
    lines = []
    for example in TOOL_EXAMPLES:
        lines.append(f"{indent}#")
        if example.note:
            lines.extend(_comment(example.note, indent))
        lines.append(f"{indent}# {example.name}:")
        lines.append(f"{indent}#   cmd: {_scalar(example.cmd)}")
        lines.append(f"{indent}#   description: {_scalar(example.description)}")
    return lines


def _scalar(value: str) -> str:
    """`value` as a YAML scalar: plain when it can be, quoted when YAML would misread it."""
    return yamlio.dump_scalar(value)
