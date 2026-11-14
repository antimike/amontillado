"""amontillado: a local wallpaper library that knows what its images look like.

Fetches wallpapers from Wallhaven, measures each image's lightness, colourfulness,
dominant hue and detail, keeps that next to the image, and answers queries such as
"a dark, muted, sparse wallpaper" from a local index.

Each picture is a directory (a record) holding its files and an info.yaml; the index is
rebuilt from those by `amo index`. `amo COMMAND --help` documents each command;
docs/design.md has the record format, the metric and class definitions, and the fetcher.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import random
import re
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Callable, Iterable
from contextlib import closing
from dataclasses import dataclass
from importlib.resources import files as package_files
from logging import getLogger
from pathlib import Path
from typing import NoReturn, TypeVar

from PIL import Image
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import track
from rich_argparse import RawDescriptionRichHelpFormatter

from amontillado import __version__, changes, infomerge, yamlio
from amontillado.accents import score as accent_score
from amontillado.classes import CLASSES, Look, classify, has_aspect
from amontillado.config import (
    API_KEY_VARIABLE,
    GENERATORS,
    HUES_CHOICES,
    VARIANT_CHOICES,
    Config,
    ConfigError,
    api_key,
    check_profile,
    commands,
    config_path,
    load_config,
    shellcheck,
    syntax_error,
)
from amontillado.config_keys import flag_help
from amontillado.contrast import apply_contrast, check
from amontillado.cropper import chooser
from amontillado.edit import EditError, plan_edit, run_edit
from amontillado.fetch import SITE, TEST_SET, fetch, name_from_tags
from amontillado.fetch import Options as FetchOptions
from amontillado.generators import GeneratorError, choose_generator, generate, picture_palette
from amontillado.gitcommit import HookError, annex_repository, git_commit
from amontillado.hook import run_on_change
from amontillado.index import (
    IndexDatabaseError,
    IndexedFile,
    LookupFailed,
    QueryError,
    RecordFilter,
    connect,
    files,
    files_with_hash,
    find_record,
    known_hashes,
    matching_records,
    names,
    rebuild,
    record_location,
    record_name,
    record_shown,
    unnamed,
    usage,
)
from amontillado.index import (
    add as add_to_index,
)
from amontillado.index import (
    replace as replace_in_index,
)
from amontillado.library import (
    PROVENANCE_KEYS,
    PURITIES,
    AddError,
    Addition,
    CropError,
    NamingError,
    Report,
    add_derived,
    add_picture,
    additions_from_json,
    annex_absent,
    crop_picture,
    hand_source,
    heal_library,
    name_record,
    place,
)
from amontillado.metrics import HUE_NAMES, Metrics, measure_file
from amontillado.palette import (
    Palette,
    PaletteError,
    dump_palette,
    load_palette,
    palette_from_schemes,
)
from amontillado.record import RecordError, sha256_file, write_text_atomic
from amontillado.registry import RegistryError, registry
from amontillado.registry import text as registry_text
from amontillado.registry import variables as template_variables
from amontillado.sources import check as sources_check
from amontillado.sources import check_apps
from amontillado.sources import needed as sources_needed
from amontillado.sources import sync as sources_sync
from amontillado.theme import (
    ThemeError,
    current_profile,
    find_palette,
    reload_commands,
    repoint_wallpapers,
    run_reloads,
)
from amontillado.theme import apply as apply_theme
from amontillado.theme import describe as describe_theme
from amontillado.theme import plan as theme_plan
from amontillado.theme import write as write_theme
from amontillado.wallhaven import (
    CATEGORY_FLAGS,
    USER_AGENT,
    Client,
    Search,
    WallhavenError,
    Wallpaper,
    http_get,
    nearest_swatch,
)

logger = getLogger("amontillado")
# Shared by logging and progress bars, so log lines print above a bar. Rich's default console is
# stdout, which carries data (`amo list` output is piped).
STDERR = Console(stderr=True)

T = TypeVar("T")


# Opposite classes: asking for both could only ever match nothing.
_CLASS_PAIRS = (
    ("dark", "light"),
    ("muted", "saturated"),
    ("sparse", "busy"),
    ("monochrome", "multi-hue"),
    ("warm", "cool"),
)


class HelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter,
    RawDescriptionRichHelpFormatter,
):
    """Preserve description/epilog whitespace, show defaults, and style with Rich."""

    def _get_help_string(self, action: argparse.Action) -> str | None:
        # None, False and [] mean "not given": the help says what that does.
        if action.default is None or action.default is False or action.default == []:
            return action.help
        return super()._get_help_string(action)


def _add_loglevel(parser: argparse.ArgumentParser, default: str) -> None:
    parser.add_argument(
        "--loglevel",
        "-l",
        default=default,
        type=lambda v: v.strip().upper(),
        help="Logging verbosity (DEBUG, INFO, WARNING, ERROR; default INFO).",
    )


def _add_hues(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--hues",
        choices=HUES_CHOICES,
        help=flag_help(
            "theme.hues",
            "Who assigns base08-base0F of a picture's palette: amontillado (fixed named hues) "
            "or the generator's own colours",
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="amontillado",
        description=__doc__,
        formatter_class=HelpFormatter,
    )
    _add_loglevel(parser, "INFO")
    parser.set_defaults(func=None)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(title="commands", metavar="COMMAND")

    measure = commands.add_parser(
        "measure",
        help="Print metrics and classes for images, as YAML.",
        description="Measure images (no library needed) and print their metrics and classes "
        "as a YAML list, one entry per file.",
        formatter_class=HelpFormatter,
    )
    # SUPPRESS: a command's parser must not overwrite a --loglevel given before the command.
    _add_loglevel(measure, argparse.SUPPRESS)
    measure.add_argument("files", nargs="+", type=Path, metavar="FILE", help="Image files.")
    measure.set_defaults(func=cmd_measure)

    index = commands.add_parser(
        "index",
        help="Heal records and rebuild the index.",
        description="Fill in and update the derived fields of every record's info.yaml "
        "(ids, hashes, sizes, metrics), and rebuild the index from them (the usage history is "
        "kept). Reports images outside a record, missing files, and info files that need a "
        "fix by hand. Searches the library roots and the NSFW root.",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(index, argparse.SUPPRESS)
    index.add_argument(
        "--check",
        action="store_true",
        help="Report what would be healed, and fail if anything would; write nothing (the "
        "dry run of this command).",
    )
    index.add_argument(
        "--rehash",
        action="store_true",
        help="Hash every file, not only those whose size or mtime changed since the last index "
        "(an edit that keeps both goes unnoticed otherwise).",
    )
    index.set_defaults(func=cmd_index)

    list_ = commands.add_parser(
        "list",
        help="Print the paths of matching pictures.",
        description="Print the default file of every indexed record that matches every "
        "filter, one per line. Records from the NSFW root, and any not marked sfw, are left "
        'out unless --purity asks for them. Class thresholds are in docs/design.md, "Classes".',
        formatter_class=HelpFormatter,
    )
    _add_loglevel(list_, argparse.SUPPRESS)
    _add_look(list_)
    list_.add_argument(
        "--purity",
        type=_purities,
        metavar="LIST",
        help="Comma-separated purities to include (sfw, sketchy, nsfw); also searches the "
        "NSFW root. Default: sfw only, NSFW root excluded.",
    )
    list_.add_argument(
        "--aspect",
        type=_aspect,
        metavar="W:H",
        help="Print each record's file of this aspect ratio (within 3%%), filtering on its "
        "metrics; records without one fall back to their default file, with a warning (on a "
        "terminal, after an offer to crop them: see amo crop).",
    )
    list_.add_argument(
        "--non-interactive",
        action="store_true",
        help="Never ask (as when stdin or stderr is not a terminal): take the fallback.",
    )
    search = list_.add_argument_group(
        "provenance filters",
        "Exact matches on what a record's source says (amo fetch, amo add's provenance "
        "options); a record without the field does not match.",
    )
    search.add_argument(
        "--tag",
        action="append",
        default=[],
        dest="tags",
        metavar="TAG",
        help="One of its tags (repeatable: all must be).",
    )
    search.add_argument("--site", help="Where it is from, e.g. wallhaven, wikimedia-commons.")
    search.add_argument("--category", help="e.g. general, anime, people.")
    search.add_argument("--license", help="Its licence (SPDX), in any case.")
    search.add_argument("--author", help="Its creator.")
    search.add_argument(
        "--where",
        metavar="SQL",
        help="A SQL boolean expression over the index's pictures view (id, name, directory, "
        "purity, site, source_id, category, tags, license, author, title, shown_count, "
        "last_shown, and info, the whole record as JSON), ANDed with the other filters: e.g. "
        "\"shown_count = 0\", \"info ->> '$.source.uploaded' >= '2024'\". Read-only; --purity "
        "still decides what may be printed.",
    )
    list_.add_argument(
        "--order",
        choices=("path", "least-shown"),
        default="path",
        help="path: by file path. least-shown: fewest showings first (amo shown counts them), "
        "then the longest since last shown, never-shown pictures first, ties in random order.",
    )
    list_.add_argument(
        "--random",
        type=_positive,
        metavar="N",
        help="Print N matches chosen at random; with --order least-shown, the first N in that "
        "order.",
    )
    list_.add_argument(
        "--format",
        choices=("path", "rofi"),
        default="path",
        help="path: one path per line. rofi: for rofi -dmenu -show-icons, each path followed "
        "by its record's thumbnail as the icon (\\0icon\\x1f<thumbnail>), if it has one.",
    )
    list_.set_defaults(func=cmd_list)

    shown = commands.add_parser(
        "shown",
        help="Record that pictures were shown.",
        description="Count one showing of each picture in the usage history, now. Usage is "
        "kept by record id, so it follows a picture through renames and moves.",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(shown, argparse.SUPPRESS)
    shown.add_argument(
        "pictures",
        nargs="+",
        metavar="PICTURE",
        help="A file or record directory, a record name, an id, or a unique prefix of an id.",
    )
    shown.add_argument(
        "--dry-run", action="store_true", help="Log what would be recorded; record nothing."
    )
    shown.set_defaults(func=cmd_shown)

    add = commands.add_parser(
        "add",
        help="Make records of image files.",
        description="Make each file a record of its own: create a directory beside it (or, "
        "for a file outside the roots, in the first library root), move the file in, write "
        "its info.yaml, and add it to the index. Refuses a file whose content is already in "
        "the library, and a name another record has. The provenance options record where a "
        "picture came from in its source; --from-json gives them per picture.",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(add, argparse.SUPPRESS)
    add.add_argument("files", nargs="*", type=Path, metavar="FILE", help="Image files.")
    add.add_argument(
        "--name",
        type=str,
        help="The record's name (one FILE only), also used for its directory; default: no "
        "name, and the file's stem for the directory.",
    )
    add.add_argument(
        "--nsfw",
        action="store_true",
        help="Put files from outside the roots in the NSFW root.",
    )
    add.add_argument(
        "--force", action="store_true", help="Add files whose content is already in the library."
    )
    add.add_argument(
        "--dry-run", action="store_true", help="Log what would be added; change nothing."
    )
    add.add_argument(
        "--from-json",
        type=Path,
        metavar="FILE",
        help="Add the pictures a JSON file lists instead of FILEs: a list of objects with "
        "file (relative to the JSON file), and optionally name, nsfw and the provenance "
        "keys (url, image_url, site, title, author, license, purity, category, tags as a "
        "list, uploaded).",
    )
    provenance = add.add_argument_group(
        "provenance",
        "Where the picture came from (recorded in source; one FILE for the options marked so).",
    )
    provenance.add_argument(
        "--source-url", dest="url", metavar="URL", help="The picture's page (one FILE)."
    )
    provenance.add_argument(
        "--image-url", metavar="URL", help="The file that was downloaded (one FILE)."
    )
    provenance.add_argument(
        "--site", help="Where it is from, e.g. wikimedia-commons; without it, the URL's host."
    )
    provenance.add_argument("--title", help="The work's title (one FILE).")
    provenance.add_argument("--author", help="Its creator (not the uploader).")
    provenance.add_argument(
        "--license",
        help="Its licence, as an SPDX identifier (CC0-1.0, CC-BY-4.0, ...) or public-domain.",
    )
    provenance.add_argument(
        "--purity",
        choices=PURITIES,
        help="sfw, sketchy or nsfw; sketchy and nsfw go to the NSFW root. Without it, what "
        "the root implies.",
    )
    provenance.add_argument("--category", help="e.g. general, anime, people.")
    provenance.add_argument("--tags", type=_words, metavar="A,B,...", help="Comma-separated tags.")
    provenance.add_argument(
        "--uploaded", metavar="DATE", help="When it was published (ISO 8601 date or time)."
    )
    add.set_defaults(func=cmd_add)

    crop = commands.add_parser(
        "crop",
        help="Crop a picture to an aspect ratio.",
        description="Write the largest W:H crop of a record's original (its default file, if "
        "that is not a crop itself) beside it, as <stem>-<W>x<H>.<ext> in the same format, "
        "and record it in info.yaml (derived_from, crop) and the index. amo list --aspect W:H "
        "then prints it. Prints the new file's path.",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(crop, argparse.SUPPRESS)
    crop.add_argument(
        "picture", metavar="PICTURE", help="A file, record directory, name or id (or prefix)."
    )
    crop.add_argument("aspect", type=_aspect, metavar="W:H", help="The aspect ratio, e.g. 21:9.")
    crop.add_argument(
        "--at",
        type=_fraction,
        default=0.5,
        metavar="F",
        help="Where the crop sits along the side it cuts: 0 left or top, 0.5 centred, 1 right "
        "or bottom.",
    )
    crop.add_argument(
        "--force",
        action="store_true",
        help="Crop even if the record has a file of that ratio; replaces an earlier crop of the "
        "same name.",
    )
    crop.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Place the box by hand: the picture is shown with the box drawn (in the terminal, "
        "or in an image viewer: crop.preview), arrows or hjkl move it (shifted: further), + "
        "and - zoom it, 0 resets it, Enter crops, Esc writes nothing (and fails). Starts from "
        "--at. Needs a terminal.",
    )
    crop.add_argument(
        "--dry-run", action="store_true", help="Log what would be cropped; change nothing."
    )
    crop.set_defaults(func=cmd_crop)

    add_derived = commands.add_parser(
        "add-derived",
        help="Add a file made by hand from a record's picture.",
        description="Register FILE, made from one of a record's files in any tool (an edit, a "
        "retouch, a recolour), as a derived file of the record: measure it, move it into the "
        "record's directory (a file already there stays), and list it in info.yaml with "
        "derived_from and no crop, which marks it hand-made: unlike a crop it cannot be made "
        "again. The original stays the default file. Indexed at once. Prints the file's path "
        "in the record.",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(add_derived, argparse.SUPPRESS)
    add_derived.add_argument(
        "picture", metavar="PICTURE", help="A file, record directory, name or id (or prefix)."
    )
    add_derived.add_argument("file", type=Path, metavar="FILE", help="The image made by hand.")
    add_derived.add_argument(
        "--name", metavar="N", help="Its file name in the record (default: FILE's own)."
    )
    add_derived.add_argument(
        "--from",
        dest="source",
        metavar="FILE",
        help="The record's file it was made from (default: the record's original: its default "
        "file if that is an original, else its largest).",
    )
    add_derived.add_argument(
        "--dry-run", action="store_true", help="Log what would be added; change nothing."
    )
    add_derived.set_defaults(func=cmd_add_derived)

    edit = commands.add_parser(
        "edit",
        help="Edit a copy of a picture in an editor and add the result.",
        description="Copy one of a record's files into a working directory inside it "
        "(.amo/edit-*), run an editor on the copy (a tool under edit.tools, or --extcmd) and "
        "add what it saved as a hand-made derived file, as amo add-derived does. The tool "
        "runs under sh -c with AMO_INPUT (the copy), AMO_OUTPUT (where a result may go) and "
        "AMO_WORKDIR in its environment, and must block until you are done. The result is "
        "AMO_OUTPUT if the "
        "tool wrote it, else the one image in the working directory (or below it) that is new "
        "or changed: export into the folder the editor opens in. Saved as <stem>-edit.<ext> "
        "by default. The working directory is removed once the result is added, or if "
        "nothing was saved, and otherwise kept and named. Prints the new file's path.",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(edit, argparse.SUPPRESS)
    edit.add_argument(
        "picture",
        nargs="?",
        metavar="PICTURE",
        help="A file, record directory, name or id (or prefix).",
    )
    which = edit.add_mutually_exclusive_group()
    which.add_argument(
        "--tool",
        "-t",
        metavar="NAME",
        help=flag_help("edit.default_tool", "The editor: a tool's name under edit.tools"),
    )
    which.add_argument(
        "--extcmd",
        "-x",
        metavar="CMD",
        help="A command line to run instead of a named tool, as a tool's cmd is "
        "(sh -c, with AMO_INPUT, AMO_OUTPUT and AMO_WORKDIR).",
    )
    which.add_argument(
        "--list-tools",
        action="store_true",
        help="List the tools under edit.tools with their descriptions; the default is marked.",
    )
    edit.add_argument(
        "--name",
        metavar="N",
        help="The new file's name in the record (default: <stem>-edit.<ext>).",
    )
    edit.add_argument(
        "--from",
        dest="source",
        metavar="FILE",
        help="The record's file to edit (default: the record's original: its default file if "
        "that is an original, else its largest).",
    )
    edit.add_argument(
        "--dry-run",
        action="store_true",
        help="Check the record and the tool and log what would run; run nothing.",
    )
    edit.set_defaults(func=cmd_edit)

    name = commands.add_parser(
        "name",
        help="Name or rename a record.",
        usage="%(prog)s [-h] [--no-rename-directory] [--dry-run] PICTURE NAME\n"
        "       %(prog)s [-h] --from-tags [--no-rename-directory] [--dry-run] [PICTURE ...]",
        description="Give a record a name, or a new one, and rename its directory to the name "
        "where it is (foo/bar/old becomes foo/bar/NAME; --no-rename-directory keeps it). A name "
        "already taken is refused, as amo add does. --from-tags names records fetched from "
        "Wallhaven without a name (before amo 0.2, or when the name was taken) as amo fetch "
        "would, from the tags their info.yaml keeps (wallhaven-x8ye3z becomes "
        "cyberpunk-interior-technology-x8ye3z): the PICTUREs given, or every such record. The "
        "kept tags lack Wallhaven's tag categories, so a tag amo fetch would pass over as an "
        "artist's or a company's may be used. Updates the index, and any theme profile's "
        "wallpaper link into a renamed directory. Prints each record's directory.",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(name, argparse.SUPPRESS)
    name.add_argument(
        "arguments",
        nargs="*",
        metavar="PICTURE NAME | PICTURE...",
        help="A record (a file, record directory, name or id, or an id prefix) and its new "
        "name; with --from-tags, records (default: every indexed Wallhaven record without a "
        "name).",
    )
    name.add_argument(
        "--from-tags",
        action="store_true",
        help="Name from the stored Wallhaven tags; refuses records that have a name.",
    )
    name.add_argument(
        "--no-rename-directory",
        dest="rename_directory",
        action="store_false",
        help="Keep each record's directory as it is.",
    )
    name.add_argument(
        "--dry-run", action="store_true", help="Log the name each record would get; change nothing."
    )
    name.set_defaults(func=cmd_name)

    fetch = commands.add_parser(
        "fetch",
        help="Fetch wallpapers from Wallhaven.",
        description="Search Wallhaven in random order, measure each result's thumbnail, and "
        "keep the ones that match every filter: download each, make it a record (sfw ones in "
        "the first library root, others in the NSFW root), and index it. The full image is "
        "judged again; see --discard-mismatches. Prints the path of each file kept that "
        "matches. Results already in the library are passed over. Fails if fewer than "
        "--count are kept. With --test-set, keeps one image per bucket instead.",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(fetch, argparse.SUPPRESS)
    _add_look(fetch)
    wallhaven = fetch.add_argument_group("Wallhaven filters")
    wallhaven.add_argument(
        "--tags", metavar="QUERY", help="Wallhaven search query: tags, +tag, -tag."
    )
    wallhaven.add_argument(
        "--purity",
        type=_purities,
        default="sfw",
        metavar="LIST",
        help="Comma-separated purities (sfw, sketchy, nsfw); nsfw needs an API key "
        "(WALLHAVEN_API_KEY or api_key_command).",
    )
    wallhaven.add_argument(
        "--category",
        type=_categories,
        metavar="LIST",
        help="Comma-separated categories (general, anime, people). Default: all.",
    )
    wallhaven.add_argument(
        "--atleast", type=_resolution, metavar="WxH", help="Minimum resolution, e.g. 2560x1440."
    )
    wallhaven.add_argument(
        "--ratio",
        type=_ratios,
        metavar="LIST",
        help="Comma-separated aspect ratios, e.g. 16:9,21:9.",
    )
    wallhaven.add_argument(
        "--color",
        type=_color,
        metavar="HEX",
        help="A colour, as hex; Wallhaven searches by one of 29 fixed swatches, so any other "
        "colour is replaced by the nearest swatch (in OKLab), e.g. 424153.",
    )
    fetch.add_argument(
        "--count",
        type=_positive,
        metavar="N",
        help="Stop after keeping N images. Default: 1.",
    )
    fetch.add_argument(
        "--test-set",
        action="store_true",
        help=f"Keep one image per bucket ({', '.join(TEST_SET)}); an image fills the first "
        "bucket still open that its full image belongs to, and no other. Takes no look "
        "filters or --count. Prints BUCKET<TAB>PATH lines, in that order; fails if a bucket "
        "stays empty.",
    )
    fetch.add_argument(
        "--max-candidates",
        type=_positive,
        default=100,
        metavar="N",
        help="Stop after examining N thumbnails.",
    )
    fetch.add_argument(
        "--busy-from",
        choices=("thumb", "full"),
        default="thumb",
        help="Judge --busy and --sparse on the thumbnail, or only on the full image "
        "(thumbnail JPEG artefacts add edges).",
    )
    fetch.add_argument(
        "--discard-mismatches",
        action="store_true",
        help="Delete a download whose full image does not match the look filters. By default "
        "it is kept as a record, but not printed or counted towards --count.",
    )
    fetch.add_argument(
        "--dry-run",
        action="store_true",
        help="Measure thumbnails and print the pages of the wallpapers that would be kept; "
        "download and write nothing.",
    )
    fetch.set_defaults(func=cmd_fetch)

    palette = commands.add_parser(
        "palette",
        help="Make a palette.",
        description="Print a palette (per variant, the base24 colours and the roles: accent, "
        "selection, ...) as YAML, or check a palette file's contrast. A picture's palette has "
        "both variants, from a generator (matugen or wallust). Base24 keys and roles the source "
        "leaves out are derived; pairs below their WCAG contrast minimum are fixed as "
        "theme.contrast says (default: adjusted, each change logged).",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(palette, argparse.SUPPRESS)
    palette_input = palette.add_mutually_exclusive_group(required=True)
    palette_input.add_argument(
        "picture",
        nargs="?",
        metavar="PICTURE",
        help="A record's file, directory, name or id (or prefix): its default file, or the "
        "file given.",
    )
    palette_input.add_argument(
        "--from-scheme",
        nargs="+",
        type=Path,
        metavar="FILE",
        help="One tinted-theming scheme (base16 or base24 YAML), or a dark and a light one of "
        "a family, which make one palette with both variants.",
    )
    palette_input.add_argument(
        "--check",
        type=Path,
        metavar="FILE",
        help="Print each variant's accent metrics (hues on their ANSI name, distinctness) and "
        "the pairs of a palette file below their contrast minimum, and fail if any pair is; "
        "change nothing.",
    )
    palette.add_argument(
        "--no-adjust",
        action="store_true",
        help=flag_help("theme.contrast", "Report failing pairs instead of adjusting them"),
    )
    palette.add_argument(
        "--generator",
        choices=GENERATORS,
        help=flag_help("theme.generator", "The generator for PICTURE"),
    )
    _add_hues(palette)
    palette.set_defaults(func=cmd_palette)

    theme = commands.add_parser(
        "theme",
        help="Theme apps from a palette.",
        description="Render a palette into each configured app's file (docs/design.md, "
        '"Theme engine (v0.2)").',
        formatter_class=HelpFormatter,
    )
    _add_loglevel(theme, argparse.SUPPRESS)
    theme.set_defaults(func=lambda _args: theme.print_help())
    theme_commands = theme.add_subparsers(title="commands", metavar="COMMAND")

    templates = theme_commands.add_parser(
        "templates",
        help="List the templates and their variables.",
        description="Print each template of the registry: its name (the app it is for), "
        "source, whether it is variables-only or a complete theme, its default output file "
        "and what it holds or where it comes from. With APP, only that app's, each mustache "
        "one followed by the variables it uses.",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(templates, argparse.SUPPRESS)
    templates.add_argument("app", nargs="?", metavar="APP", help="A template's name.")
    templates.set_defaults(func=cmd_theme_templates)

    sync = theme_commands.add_parser(
        "sync",
        help="Fetch every template the config needs.",
        description="Download each template the apps under theme.apps use from a fetched "
        "source (tinted, matugen-themes, pywal: at the registry's pinned commit; url: the "
        "configured URL) into $XDG_CACHE_HOME/amontillado/sources/, one HTTPS request per "
        "file not already there. A file whose sha256 differs from the registry's (or the "
        "config's) is not kept. amo theme apply never uses the network.",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(sync, argparse.SUPPRESS)
    sync.add_argument(
        "--check",
        action="store_true",
        help="Fetch nothing: fail if a template is missing or does not match its hash.",
    )
    sync.set_defaults(func=cmd_theme_sync)

    apply = theme_commands.add_parser(
        "apply",
        help="Render every app from a palette, swap the profile in, reload.",
        description="Render each app under theme.apps from a palette into a new generation of "
        "the profile, swap it in for <cache>/<profile> and point <cache>/current at it, then "
        "run each app's reload command and the wallpaper hook (a failing reload warns). A "
        "render error changes nothing. Given PICTURE, the palette is generated from it, the "
        "profile's wallpaper link points to it and it is recorded as shown. Without PICTURE or "
        "--palette, re-render the profile's own palette (after a config change). No network.",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(apply, argparse.SUPPRESS)
    apply_input = apply.add_mutually_exclusive_group()
    apply_input.add_argument(
        "picture",
        nargs="?",
        metavar="PICTURE",
        help="A record's file, directory, name or id (or prefix).",
    )
    apply_input.add_argument(
        "--palette",
        metavar="NAME|FILE",
        help="A palette file, or a preset in $XDG_CONFIG_HOME/amontillado/palettes/.",
    )
    _add_hues(apply)
    apply.add_argument(
        "--profile", metavar="P", help=flag_help("theme.profile", "The profile to write")
    )
    apply.add_argument(
        "--variant",
        choices=VARIANT_CHOICES,
        help=flag_help("theme.variant", "The variant for every app without its own"),
    )
    apply.add_argument(
        "--app",
        action="append",
        default=[],
        metavar="NAME",
        help="Re-render only this app (repeatable); the others keep their files.",
    )
    apply.add_argument(
        "--no-adjust",
        action="store_true",
        help=flag_help("theme.contrast", "Report failing contrast pairs instead of adjusting them"),
    )
    apply.add_argument(
        "--no-activate", action="store_true", help="Leave current where it is; reload nothing."
    )
    apply.add_argument("--no-reload", action="store_true", help="Run no reload commands.")
    apply.add_argument(
        "--dry-run",
        action="store_true",
        help="Render into a temporary directory, print its path and the reload commands; "
        "change nothing.",
    )
    apply.set_defaults(func=cmd_theme_apply)

    current = theme_commands.add_parser(
        "current",
        help="Show the applied palette, picture and time.",
        description="Print the profile's palette name, picture and the time it was applied, "
        "and warn when its apps were rendered from different palettes (an --app apply).",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(current, argparse.SUPPRESS)
    current.add_argument(
        "--profile", metavar="P", help="The profile (default: the one current points to)."
    )
    current.set_defaults(func=cmd_theme_current)

    info = commands.add_parser(
        "info",
        help="Compare or merge info files.",
        description='Schema-aware tools for info files (docs/design.md, "git-annex libraries: '
        'decisions" 5), for version control and on_change hooks. Exit status: 0 the same or '
        "merged, 1 different or a conflict, 2 an unreadable file.",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(info, argparse.SUPPRESS)
    info.set_defaults(func=lambda _args: info.print_help())
    info_commands = info.add_subparsers(title="commands", metavar="COMMAND")

    info_diff = info_commands.add_parser(
        "diff",
        help="Print the key paths that differ between two info files.",
        description="Print each key path that differs from OLD to NEW, one per line: `+ path: "
        "value` added, `- path: value` removed, `~ path: old -> new` changed. Mappings are "
        "compared key by key, lists as a whole; comments and layout are ignored. Exits 0 if "
        "there is no difference, 1 if there is, 2 if a file cannot be read.",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(info_diff, argparse.SUPPRESS)
    info_diff.add_argument("old", type=Path, metavar="OLD", help="The first info file.")
    info_diff.add_argument("new", type=Path, metavar="NEW", help="The second info file.")
    info_diff.add_argument(
        "--json",
        action="store_true",
        help="Print a JSON list of {path, change, old, new} instead (path: a list of keys).",
    )
    info_diff.set_defaults(func=cmd_info_diff)

    info_merge = info_commands.add_parser(
        "merge",
        help="Three-way merge of info files (a git merge driver).",
        description="Merge into OURS what THEIRS changed since BASE, by unit: a top-level key; "
        "the file names under files with default_file; one files entry. A unit changed on "
        "both sides, differently, is a conflict; so is a merge that is no valid record, or "
        "three files of different schema. OURS keeps its comments and layout. Exits 0 merged "
        "(OURS rewritten, if THEIRS changed anything), 1 on a conflict (OURS untouched, the "
        "conflicting units on stderr; no conflict markers, which would make the YAML "
        "unparseable), 2 if a file cannot be read. As git's merge driver: in .gitattributes "
        "`info.yaml merge=amo-info`, and `git config merge.amo-info.driver 'amo info merge "
        "%%O %%A %%B --name %%P'`.",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(info_merge, argparse.SUPPRESS)
    info_merge.add_argument("base", type=Path, metavar="BASE", help="The common ancestor.")
    info_merge.add_argument("ours", type=Path, metavar="OURS", help="Our version; the result.")
    info_merge.add_argument("theirs", type=Path, metavar="THEIRS", help="Their version.")
    info_merge.add_argument(
        "--name", metavar="PATH", help="The path to name in messages (git's %%P)."
    )
    info_merge.add_argument(
        "--stdout",
        action="store_true",
        help="Print the merged file instead of rewriting OURS (writes nothing).",
    )
    info_merge.set_defaults(func=cmd_info_merge)

    hook = commands.add_parser(
        "hook",
        help="Hooks to set as on_change.",
        description="Commands to run as the on_change hook (a config key): each reads the "
        "changes amo made under one root, as JSON on stdin.",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(hook, argparse.SUPPRESS)
    hook.set_defaults(func=lambda _args: hook.print_help())
    hook_commands = hook.add_subparsers(title="commands", metavar="COMMAND")
    git_commit = hook_commands.add_parser(
        "git-commit",
        help="Commit amo's changes to the root's git repository.",
        description="Set `on_change: amo hook git-commit` to commit what each amo command "
        "writes, one commit per root that is in a git work tree (others are skipped with a "
        "warning). Only amo's changes are committed: info files are merged with amo info "
        "merge against the committed version, so an uncommitted edit of yours stays "
        "uncommitted (a conflict leaves that record uncommitted, with a warning); new images "
        "and thumbnails are added unless git ignores them; what you have staged is neither "
        "committed nor lost. Your git hooks and signing apply. Needs git.",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(git_commit, argparse.SUPPRESS)
    git_commit.set_defaults(func=cmd_hook_git_commit)

    config = commands.add_parser(
        "config",
        help="Write or check the config file.",
        description=f"The config file, {config_path()} (every key optional).",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(config, argparse.SUPPRESS)
    config.set_defaults(func=lambda _args: config.print_help())
    config_commands = config.add_subparsers(title="commands", metavar="COMMAND")

    init = config_commands.add_parser(
        "init",
        help="Write the commented config template.",
        description="Write the config template, every key commented out at its default or "
        "with an example, under its meaning and trade-offs, to the config file (or stdout). "
        "Refuses to replace a config file that exists.",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(init, argparse.SUPPRESS)
    init.add_argument("--stdout", action="store_true", help="Print the template instead.")
    init.add_argument("--force", action="store_true", help="Replace an existing config file.")
    init.set_defaults(func=cmd_config_init)

    check_ = config_commands.add_parser(
        "check",
        help="Validate a config file.",
        description="Load a config file as every command does, and fail if it has an error, an "
        "unknown key, an app whose template cannot be found or read (a fetched one: run amo "
        "theme sync), two apps writing one output file, or a command (a reload hook, "
        "crop.viewer, an edit tool, api_key_command, on_change) that sh -n cannot parse, or "
        "on_change: amo hook git-commit without git (or git-annex, for a root in a git-annex "
        "repository) on PATH. Changes nothing.",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(check_, argparse.SUPPRESS)
    check_.add_argument(
        "file", nargs="?", type=Path, metavar="FILE", help="The file (default: the config file)."
    )
    check_.add_argument(
        "--shellcheck",
        action="store_true",
        help="Also run shellcheck on every command, as a POSIX sh script; its findings are "
        "problems too (needs shellcheck).",
    )
    check_.set_defaults(func=cmd_config_check)

    return parser


def _add_look(parser: argparse.ArgumentParser) -> None:
    """The class flags and --hue (docs/design.md, "Classes")."""
    group = parser.add_argument_group("look filters")
    for pair in _CLASS_PAIRS:
        exclusive = group.add_mutually_exclusive_group()
        for name in pair:
            exclusive.add_argument(f"--{name}", action="store_true", help=f"Only {name} images.")
    group.add_argument(
        "--hue", choices=HUE_NAMES, metavar="NAME", help=f"Dominant hue: {', '.join(HUE_NAMES)}."
    )


def _purities(value: str) -> frozenset[str]:
    names = frozenset(name.strip() for name in value.split(","))
    unknown = names - set(PURITIES)
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown purity: {', '.join(sorted(unknown))}")
    return names


def _categories(value: str) -> frozenset[str]:
    names = frozenset(name.strip() for name in value.split(","))
    unknown = names - set(CATEGORY_FLAGS)
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown category: {', '.join(sorted(unknown))}")
    return names


def _resolution(value: str) -> str:
    if not re.fullmatch(r"[1-9]\d*x[1-9]\d*", value):
        raise argparse.ArgumentTypeError("must be WxH, for example 2560x1440")
    return value


def _ratios(value: str) -> tuple[str, ...]:
    ratios = []
    for ratio in value.split(","):
        match = re.fullmatch(r"([1-9]\d*)[:x]([1-9]\d*)", ratio.strip())
        if not match:
            raise argparse.ArgumentTypeError("must be W:H, for example 21:9")
        ratios.append(f"{match[1]}x{match[2]}")
    return tuple(ratios)


def _color(value: str) -> str:
    if not re.fullmatch(r"#?[0-9a-fA-F]{6}", value):
        raise argparse.ArgumentTypeError("must be a hex colour, for example 424153")
    return value.removeprefix("#").lower()


@dataclass(frozen=True)
class Aspect:
    """An aspect ratio as given: `label` names crop files (21:9 is `21x9`)."""

    ratio: float
    label: str


def _aspect(value: str) -> Aspect:
    width, _, height = value.partition(":")
    try:
        ratio = float(width) / float(height)
    except (ValueError, ZeroDivisionError):
        raise argparse.ArgumentTypeError("must be W:H, for example 21:9") from None
    if not (math.isfinite(ratio) and ratio > 0):
        raise argparse.ArgumentTypeError("must be W:H, for example 21:9")
    return Aspect(ratio, f"{width.strip()}x{height.strip()}")


def _words(value: str) -> list[str]:
    return [word.strip() for word in value.split(",") if word.strip()]


def _fraction(value: str) -> float:
    number = float(value)
    if not 0 <= number <= 1:
        raise argparse.ArgumentTypeError("must be from 0 to 1")
    return number


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def get_cli_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def setup_logger(args: argparse.Namespace) -> None:
    logger.addHandler(RichHandler(level=args.loglevel, console=STDERR))
    logger.setLevel(args.loglevel)


def cmd_measure(args: argparse.Namespace) -> None:
    results = []
    failed = 0
    for path in args.files:
        try:
            metrics = measure_file(path)
        except (OSError, Image.DecompressionBombError) as exc:
            logger.error("%s: %s", path, exc)
            failed += 1
            continue
        results.append(
            {"file": str(path), "metrics": metrics.to_dict(), "classes": classify(metrics)}
        )
    if results:
        print(yamlio.dump(results), end="")
    if failed:
        sys.exit(f"amontillado: {failed} of {len(args.files)} files could not be measured")


def _load_config() -> Config:
    try:
        return load_config()
    except ConfigError as exc:
        sys.exit(f"amontillado: {exc}")


def _index_error(config: Config, exc: Exception) -> NoReturn:
    sys.exit(f"amontillado: index {config.index_path}: {exc}")


def cmd_index(args: argparse.Namespace) -> None:
    config = _load_config()
    try:
        known = {} if args.rehash else known_hashes(config.index_path)
    except (sqlite3.Error, IndexDatabaseError, OSError) as exc:
        _index_error(config, exc)
    report = heal_library(
        config,
        check=args.check,
        known=known,
        track=_progress("checking" if args.check else "indexing"),
    )
    if args.check:
        logger.info("%s", _summary(f"checked {_count(report.records, 'record')}", report, True))
    else:
        try:
            with closing(connect(config.index_path)) as conn:
                count = rebuild(conn, report.entries)
        except (sqlite3.Error, IndexDatabaseError, OSError) as exc:
            _index_error(config, exc)
        logger.info("%s", _summary(f"indexed {_count(count, 'record')}", report, False))
    problems = _problems(report, check=args.check)
    if problems:
        sys.exit(f"amontillado: {', '.join(problems)}")


def cmd_list(args: argparse.Namespace) -> None:
    config = _load_config()
    if not config.index_path.exists():
        sys.exit(f"amontillado: no index at {config.index_path}; run `amo index` first")
    search = RecordFilter(
        tuple(args.tags), args.site, args.category, args.license, args.author, args.where
    )
    try:
        with closing(connect(config.index_path)) as conn:
            wanted = matching_records(conn, search) if search else None
            shown = usage(conn) if args.order == "least-shown" else {}
            by_record: dict[str, list[IndexedFile]] = {}
            for row in files(conn):
                # Annexed content not on this machine cannot be shown.
                if row.absent:
                    continue
                if wanted is None or row.record_id in wanted:
                    by_record.setdefault(row.record_id, []).append(row)
    except QueryError as exc:
        sys.exit(f"amontillado: {exc}")
    except (sqlite3.Error, IndexDatabaseError, OSError) as exc:
        _index_error(config, exc)
    ratio = args.aspect.ratio if args.aspect is not None else None
    rows = [_pick(group, ratio) for group in by_record.values()]
    look = _look(args)
    matches = [row for row in rows if _matches(row, args, look, config)]
    present = [row for row in matches if row.path.is_file() and not annex_absent(row.path)]
    if len(present) < len(matches):
        gone = len(matches) - len(present)
        logger.warning(
            "missing from disk or its annex content dropped: %s; run `amo index`",
            _count(gone, "file"),
        )
    matches = present
    if args.order == "least-shown":
        matches = _least_shown(matches, shown)
        if args.random is not None:
            matches = matches[: args.random]
    elif args.random is not None:
        matches = random.sample(matches, min(args.random, len(matches)))
    if not matches:
        sys.exit("amontillado: no matching pictures")
    paths = {row.path: row.path for row in matches}
    if args.aspect is not None:
        fallbacks = [row for row in matches if not has_aspect(row.width, row.height, ratio)]
        answer = "no"
        if fallbacks and _may_ask(args):
            answer = _ask_crop(
                f"no {args.aspect.label.replace('x', ':')} file for "
                f"{_count(len(fallbacks), 'picture')}; crop"
            )
        if answer != "no":
            paths.update(_crop_all(config, fallbacks, args.aspect, answer == "interactive"))
            fallbacks = [row for row in fallbacks if paths[row.path] == row.path]
        if fallbacks:
            logger.warning(
                "no file of that aspect ratio for %s; using the default file",
                _count(len(fallbacks), "picture"),
            )
    for row in matches:
        path = paths[row.path]
        if args.format == "rofi" and row.thumbnail is not None and row.thumbnail.is_file():
            print(f"{path}\0icon\x1f{row.thumbnail}")
        else:
            print(path)


def _least_shown(rows: list[IndexedFile], shown: dict[str, tuple[int, str]]) -> list[IndexedFile]:
    """Fewest showings first, then the longest since last shown; ties in random order."""
    rows = random.sample(rows, len(rows))
    # Never shown sorts first: count 0, and "" before any timestamp. The sort is stable, so the
    # shuffle above breaks ties.
    return sorted(rows, key=lambda row: shown.get(row.record_id, (0, "")))


def _may_ask(args: argparse.Namespace) -> bool:
    """Whether a prompt is allowed: stdin and stderr are terminals (stdout may be a pipe: it
    carries data) and --non-interactive was not given."""
    return not args.non_interactive and sys.stdin.isatty() and sys.stderr.isatty()


def _ask_crop(question: str) -> str:
    """Ask how to crop, on stderr: centred, interactive, or (anything else, or end of input)
    no."""
    STDERR.print(
        f"{question}: [c]entred, [i]nteractively, [N]o? ", end="", markup=False, highlight=False
    )
    try:
        answer = input().strip().lower()
    except EOFError:
        return "no"
    if answer in ("c", "centred", "centered"):
        return "centred"
    if answer in ("i", "interactive", "interactively"):
        return "interactive"
    return "no"


def _crop_all(
    config: Config, rows: list[IndexedFile], aspect: Aspect, interactive: bool = False
) -> dict[Path, Path]:
    """Crop the records of `rows` to `aspect`, centred or placed by hand; maps each default
    file printed to its crop. A record that cannot be cropped (or whose crop is cancelled) is
    logged and left out."""
    crops: dict[Path, Path] = {}
    choose = chooser(config.crop, aspect.ratio, aspect.label) if interactive else None
    try:
        with closing(connect(config.index_path)) as conn:
            for row in rows:
                try:
                    directory, root = record_location(conn, row.record_id)
                    entry, name = crop_picture(
                        config, directory, root, aspect.ratio, aspect.label, choose=choose
                    )
                except (CropError, LookupFailed, RecordError) as exc:
                    logger.error("%s", exc)
                    continue
                except (OSError, Image.DecompressionBombError) as exc:
                    logger.error("%s: %s", row.path, exc)
                    continue
                replace_in_index(conn, entry)
                logger.info("cropped %s", directory / name)
                crops[row.path] = directory / name
    except (sqlite3.Error, IndexDatabaseError) as exc:
        _index_error(config, exc)
    return crops


def _pick(group: list[IndexedFile], aspect: float | None) -> IndexedFile:
    """The file of a record that `amo list` prints: the default file, or with an aspect ratio
    the default file if it matches, else the largest matching file (ties broken by path), else
    the default file anyway."""
    default = next(row for row in group if row.is_default)
    if aspect is None or has_aspect(default.width, default.height, aspect):
        return default
    matching = [row for row in group if has_aspect(row.width, row.height, aspect)]
    # max keeps the first of equals, and the group is in path order.
    return max(matching, key=lambda row: row.width * row.height, default=default)


def _look(args: argparse.Namespace) -> Look:
    classes = tuple(name for name in CLASSES if getattr(args, name.replace("-", "_")))
    return Look(classes, args.hue)


def _matches(row: IndexedFile, args: argparse.Namespace, look: Look, config: Config) -> bool:
    if row.purity not in (args.purity or {"sfw"}):
        return False
    # Checked against the current config too, and through symlinks: the index may predate a
    # config change, and a picker bug must not put an NSFW image on screen.
    if args.purity is None and (
        row.nsfw_root or row.path.resolve().is_relative_to(config.nsfw_root)
    ):
        return False
    return look.matches(row.metrics)


def cmd_shown(args: argparse.Namespace) -> None:
    config = _load_config()
    if not config.index_path.exists():
        sys.exit(f"amontillado: no index at {config.index_path}; run `amo index` first")
    try:
        with closing(connect(config.index_path)) as conn:
            ids = []
            for picture in args.pictures:
                try:
                    ids.append(find_record(conn, picture))
                except LookupFailed as exc:
                    sys.exit(f"amontillado: {exc}")
            for picture, record_id in zip(args.pictures, ids, strict=True):
                if args.dry_run:
                    logger.info("would record %s as shown (%s)", picture, record_id)
                else:
                    record_shown(conn, record_id)
    except (sqlite3.Error, IndexDatabaseError, OSError) as exc:
        _index_error(config, exc)


def cmd_palette(args: argparse.Namespace) -> None:
    if args.check is not None:
        _check_palette(args.check)
        return
    config = _load_config()
    mode = config.theme.contrast
    if args.no_adjust and mode == "adjust":
        mode = "report"
    try:
        if args.picture is not None:
            palette, _ = _picture_palette(
                config, args.picture, generator=args.generator, hues=args.hues
            )
        else:
            palette = palette_from_schemes(args.from_scheme)
    except (PaletteError, GeneratorError) as exc:
        sys.exit(f"amontillado: {exc}")
    print(dump_palette(apply_contrast(palette, mode)), end="")


@dataclass(frozen=True)
class _Picture:
    """A record's file, for a palette."""

    record_id: str
    name: str
    path: Path
    metrics: Metrics


def _find_picture(config: Config, query: str) -> _Picture:
    """The record `query` names and its file: the one given, else the default."""
    if not config.index_path.exists():
        sys.exit(f"amontillado: no index at {config.index_path}; run `amo index` first")
    try:
        with closing(connect(config.index_path)) as conn:
            try:
                record_id = find_record(conn, query)
            except LookupFailed as exc:
                sys.exit(f"amontillado: {exc}")
            indexed = files(conn, record_id)
            name = record_name(conn, record_id) or record_id
    except (sqlite3.Error, IndexDatabaseError, OSError) as exc:
        _index_error(config, exc)
    given = Path(query).absolute()
    chosen = next((item for item in indexed if item.path == given), None)
    if chosen is None:
        chosen = next((item for item in indexed if item.is_default), None)
    if chosen is None:
        sys.exit(f"amontillado: {query}: the record has no default file")
    if chosen.absent or annex_absent(chosen.path):
        sys.exit(f"amontillado: {chosen.path}: its content is not here; `git annex get` it")
    return _Picture(record_id, name, chosen.path, chosen.metrics)


def _picture_palette(
    config: Config, query: str, *, generator: str | None, hues: str | None
) -> tuple[Palette, _Picture]:
    """The palette generated from the picture `query` names, before the contrast check.
    Raises GeneratorError or PaletteError."""
    picture = _find_picture(config, query)
    name = choose_generator(generator or config.theme.generator)
    generated = generate(picture.path, name)
    palette = picture_palette(
        generated,
        name=picture.name,
        hues=hues or config.theme.hues,
        hue=picture.metrics.hue,
        source={
            "picture": picture.record_id,
            "file": picture.path.name,
            "lightness": round(picture.metrics.lightness, 3),
        },
    )
    return palette, picture


def _check_palette(path: Path) -> None:
    try:
        palette = load_palette(path)
    except PaletteError as exc:
        sys.exit(f"amontillado: {exc}")
    failed = 0
    for name, variant in palette.variants.items():
        print(f"{name}: {accent_score(variant.base24)}")
        failures = check(variant)
        for failure in failures:
            print(f"{name}: {failure}")
        if not failures:
            logger.info("%s: every pair passes", name)
        failed += len(failures)
    if failed:
        sys.exit(f"amontillado: {_count(failed, 'pair')} below the contrast minimum")


def cmd_theme_templates(args: argparse.Namespace) -> None:
    entries = [entry for source in registry().values() for entry in source.values()]
    if args.app is not None:
        entries = [entry for entry in entries if entry.name == args.app]
        if not entries:
            sys.exit(f"amontillado: no template {args.app!r} (amo theme templates lists them)")
    widths = [
        max(len(entry.name) for entry in entries),
        max(len(entry.source) for entry in entries),
        max(len(entry.output) for entry in entries),
    ]
    for entry in entries:
        kind = "complete" if entry.complete else "variables"
        print(
            f"{entry.name:<{widths[0]}}  {entry.source:<{widths[1]}}  {kind:<9}  "
            f"{entry.output:<{widths[2]}}  {entry.summary}"
        )
        if args.app is None or entry.format != "mustache":
            continue
        try:
            names = template_variables(registry_text(entry))
        except RegistryError:
            print("    (not synced: amo theme sync)")
            continue
        for name in names:
            print(f"    {name}")


def cmd_theme_sync(args: argparse.Namespace) -> None:
    config = _load_config()
    try:
        templates = sources_needed(config)
    except RegistryError as exc:
        sys.exit(f"amontillado: {exc}")
    if args.check:
        problems = sources_check(templates)
    else:
        try:
            problems = sources_sync(templates, http_get, {"User-Agent": USER_AGENT})
        except (WallhavenError, OSError) as exc:
            sys.exit(f"amontillado: {exc}")
    for problem in problems:
        logger.error("%s", problem)
    if problems:
        sys.exit(f"amontillado: {_count(len(problems), 'template')} not synced")
    logger.info("%s synced", _count(len(templates), "template"))


def cmd_theme_apply(args: argparse.Namespace) -> None:
    config = _load_config()
    profile = args.profile if args.profile is not None else config.theme.profile
    mode = config.theme.contrast
    if args.no_adjust and mode == "adjust":
        mode = "report"
    if args.picture is not None and args.app:
        sys.exit("amontillado: PICTURE with --app: a new picture re-renders every app")
    picture = None
    try:
        check_profile(profile, "--profile")
        if args.picture is not None:
            palette, picture = _picture_palette(
                config, args.picture, generator=None, hues=args.hues
            )
        elif args.palette is not None:
            palette = load_palette(find_palette(args.palette))
        else:
            palette = None
        plan = theme_plan(
            config,
            palette,
            profile=profile,
            variant=args.variant or config.theme.variant,
            contrast=mode,
            only=args.app,
            wallpaper=None if picture is None else picture.path,
        )
        if args.dry_run:
            directory = Path(tempfile.mkdtemp(prefix="amo-theme-"))
            if plan.copy_from is not None:
                shutil.copytree(plan.copy_from, directory, symlinks=True, dirs_exist_ok=True)
            write_theme(plan, directory)
            print(directory)
            for reload in reload_commands(config, plan, directory):
                print(f"would run: {reload}")
            return
        directory = apply_theme(config, plan, activate=not args.no_activate)
    except (ConfigError, ThemeError, PaletteError, GeneratorError, OSError) as exc:
        sys.exit(f"amontillado: {exc}")
    logger.info("applied %s to profile %s", plan.palette.name, profile)
    # A picture behind an inactive profile has not been shown.
    if picture is not None and not args.no_activate:
        try:
            with closing(connect(config.index_path)) as conn:
                record_shown(conn, picture.record_id)
        except (sqlite3.Error, IndexDatabaseError, OSError) as exc:
            logger.warning("%s: not recorded as shown: %s", picture.name, exc)
    if not args.no_reload and not args.no_activate:
        run_reloads(reload_commands(config, plan, directory))


def cmd_theme_current(args: argparse.Namespace) -> None:
    config = _load_config()
    profile = args.profile if args.profile is not None else current_profile(config.theme)
    try:
        info, palettes = describe_theme(config.theme, profile)
    except ThemeError as exc:
        sys.exit(f"amontillado: {exc}")
    for key, value in info.items():
        print(f"{key}: {value}")
    if palettes:
        logger.warning("apps rendered from different palettes: %s", ", ".join(palettes))


def cmd_config_init(args: argparse.Namespace) -> None:
    template = (package_files("amontillado") / "config.template.yaml").read_text()
    if args.stdout:
        print(template, end="")
        return
    path = config_path()
    if path.exists() and not args.force:
        sys.exit(f"amontillado: {path} exists: --force replaces it, --stdout prints the template")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template)
    logger.info("wrote %s", path)


class _Collect(logging.Handler):
    """Keeps the messages of the records it handles."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _read_info_text(path: Path) -> str:
    """An info file's text for amo info; exit status 2 if it cannot be read (1 means a
    difference or a conflict there)."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("%s: %s", path, exc.strerror or exc)
        sys.exit(2)


def cmd_info_diff(args: argparse.Namespace) -> None:
    old, new = (_load_info(path) for path in (args.old, args.new))
    found = infomerge.diff(old, new)
    if args.json:
        print(json.dumps([change.to_dict() for change in found], default=str, indent=2))
    else:
        for change in found:
            print(change.describe())
    sys.exit(1 if found else 0)


def _load_info(path: Path) -> dict[str, object]:
    try:
        return infomerge.load(_read_info_text(path))
    except infomerge.InfoError as exc:
        logger.error("%s: %s", path, exc)
        sys.exit(2)


def cmd_info_merge(args: argparse.Namespace) -> None:
    name = args.name or str(args.ours)
    base, ours, theirs = (_read_info_text(path) for path in (args.base, args.ours, args.theirs))
    try:
        result = infomerge.merge(base, ours, theirs)
    except infomerge.InfoError as exc:
        logger.error("%s: cannot merge: %s", name, exc)
        sys.exit(2)
    if result.text is None:
        for conflict in result.conflicts:
            logger.error("%s: conflict: %s", name, conflict)
        sys.exit(1)
    if args.stdout:
        print(result.text, end="")
    elif result.changed:
        write_text_atomic(args.ours, result.text)
        logger.debug("%s: merged", name)


def cmd_hook_git_commit(args: argparse.Namespace) -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except ValueError as exc:
        sys.exit(f"amontillado: hook git-commit: stdin is not an on_change payload: {exc}")
    if not isinstance(payload, dict):
        sys.exit("amontillado: hook git-commit: stdin is not an on_change payload")
    try:
        git_commit(payload)
    except HookError as exc:
        sys.exit(f"amontillado: hook git-commit: {exc}")


def cmd_config_check(args: argparse.Namespace) -> None:
    path = config_path() if args.file is None else args.file
    if not path.is_file():
        sys.exit(f"amontillado: no config file {path}")
    # Unknown keys only warn when a command loads the config; here they are problems.
    collect = _Collect()
    config_logger = logging.getLogger("amontillado.config")
    config_logger.addHandler(collect)
    try:
        config = load_config(path)
    except ConfigError as exc:
        sys.exit(f"amontillado: {exc}")
    finally:
        config_logger.removeHandler(collect)
    problems = check_apps(config) + _check_commands(config, shellcheck_too=args.shellcheck)
    problems += _check_on_change(config)
    for problem in problems:
        logger.error("%s", problem)
    count = len(problems) + len(collect.messages)
    if count:
        sys.exit(f"amontillado: {path}: {_count(count, 'problem')}")
    logger.info("%s: ok (%s)", path, _count(len(config.theme.apps), "app"))


def _check_on_change(config: Config) -> list[str]:
    """The hook's own needs: amo hook git-commit needs git, and git-annex for a root in a
    git-annex repository."""
    if not (config.on_change and "amo hook git-commit" in config.on_change):
        return []
    if not shutil.which("git"):
        return ["on_change: amo hook git-commit needs git, which is not on PATH"]
    if not shutil.which("git-annex"):
        roots = (*config.library_roots, config.nsfw_root)
        return [
            f"on_change: {root} is in a git-annex repository; amo hook git-commit needs "
            "git-annex, which is not on PATH"
            for root in roots
            if annex_repository(root)
        ]
    return []


def _check_commands(config: Config, *, shellcheck_too: bool) -> list[str]:
    """What sh -n (and with `shellcheck_too`, shellcheck) finds in the config's commands."""
    problems = []
    for key, command in commands(config):
        error = syntax_error(command)
        if error is not None:
            problems.append(f"{key}: {error}")
        elif shellcheck_too:
            try:
                problems += [f"{key}: {finding}" for finding in shellcheck(command)]
            except OSError as exc:
                sys.exit(f"amontillado: --shellcheck: cannot run shellcheck: {exc}")
    return problems


# The provenance options that name one picture, so take one FILE (as --name does).
_ONE_FILE_OPTIONS = {"name": "--name", "url": "--source-url", "image_url": "--image-url",
                     "title": "--title"}  # fmt: skip


def cmd_add(args: argparse.Namespace) -> None:
    given = {key: getattr(args, key) for key in PROVENANCE_KEYS if getattr(args, key) is not None}
    if args.from_json is not None:
        if args.files or args.name is not None or given or args.nsfw:
            sys.exit("amontillado: --from-json takes no FILEs, --name, --nsfw or provenance")
        try:
            additions = additions_from_json(args.from_json)
        except (AddError, OSError) as exc:
            sys.exit(f"amontillado: {exc}")
    else:
        if not args.files:
            sys.exit("amontillado: no FILE (or --from-json) given")
        for key, option in _ONE_FILE_OPTIONS.items():
            if getattr(args, key) is not None and len(args.files) > 1:
                sys.exit(f"amontillado: {option} takes one FILE")
        try:
            hand_source(given)
        except AddError as exc:
            sys.exit(f"amontillado: {exc}")
        additions = [Addition(file, args.name, args.nsfw, given) for file in args.files]
    config = _load_config()
    failed = 0
    try:
        with closing(connect(config.index_path)) as conn:
            taken = names(conn)
            for addition in additions:
                try:
                    _add_one(conn, config, addition, args, taken)
                except AddError as exc:
                    logger.error("%s", exc)
                    failed += 1
                except (OSError, Image.DecompressionBombError) as exc:
                    logger.error("%s: %s", addition.file, exc)
                    failed += 1
    except (sqlite3.Error, IndexDatabaseError) as exc:
        _index_error(config, exc)
    if failed:
        sys.exit(f"amontillado: {failed} of {len(additions)} files could not be added")


def _add_one(
    conn: sqlite3.Connection,
    config: Config,
    addition: Addition,
    args: argparse.Namespace,
    taken: set[str],
) -> None:
    file, name = addition.file, addition.name
    source = hand_source(addition.fields)
    purity = source.get("purity") if source else None
    placement = place(
        config,
        file,
        name=name,
        nsfw=addition.nsfw,
        purity=purity if isinstance(purity, str) else None,
    )
    if name in taken:
        raise AddError(f"name {name!r} is taken")
    duplicates = files_with_hash(conn, sha256_file(file))
    if duplicates and not args.force:
        raise AddError(f"{file}: same content as {duplicates[0]}; --force adds it anyway")
    if duplicates:
        logger.warning("%s: same content as %s", file, duplicates[0])
    if args.dry_run:
        logger.info("would add %s as %s", file, placement.directory)
        return
    entry = add_picture(config, placement, name=name, source=source)
    add_to_index(conn, entry)
    if name is not None:
        taken.add(name)
    logger.info("added %s as %s", file, entry.directory)


def cmd_crop(args: argparse.Namespace) -> None:
    config = _load_config()
    if args.interactive and not (sys.stdin.isatty() and sys.stderr.isatty()):
        sys.exit("amontillado: --interactive needs a terminal (stdin and stderr)")
    if not config.index_path.exists():
        sys.exit(f"amontillado: no index at {config.index_path}; run `amo index` first")
    try:
        with closing(connect(config.index_path)) as conn:
            try:
                directory, root = record_location(conn, find_record(conn, args.picture))
                entry, name = crop_picture(
                    config,
                    directory,
                    root,
                    args.aspect.ratio,
                    args.aspect.label,
                    at=args.at,
                    force=args.force,
                    dry_run=args.dry_run,
                    choose=chooser(config.crop, args.aspect.ratio, args.aspect.label)
                    if args.interactive
                    else None,
                )
            except (CropError, LookupFailed, RecordError) as exc:
                sys.exit(f"amontillado: {exc}")
            except (OSError, Image.DecompressionBombError) as exc:
                sys.exit(f"amontillado: {args.picture}: {exc}")
            if args.dry_run:
                logger.info("would crop %s", directory / name)
                return
            replace_in_index(conn, entry)
    except (sqlite3.Error, IndexDatabaseError) as exc:
        _index_error(config, exc)
    print(directory / name)


def cmd_add_derived(args: argparse.Namespace) -> None:
    config = _load_config()
    if not config.index_path.exists():
        sys.exit(f"amontillado: no index at {config.index_path}; run `amo index` first")
    try:
        with closing(connect(config.index_path)) as conn:
            try:
                directory, root = record_location(conn, find_record(conn, args.picture))
                entry, name = add_derived(
                    config,
                    directory,
                    root,
                    args.file,
                    name=args.name,
                    source=args.source,
                    dry_run=args.dry_run,
                )
            except (AddError, LookupFailed, RecordError) as exc:
                sys.exit(f"amontillado: {exc}")
            except (OSError, Image.DecompressionBombError) as exc:
                sys.exit(f"amontillado: {args.file}: {exc}")
            if args.dry_run:
                logger.info("would add %s as %s", args.file, directory / name)
                return
            replace_in_index(conn, entry)
    except (sqlite3.Error, IndexDatabaseError) as exc:
        _index_error(config, exc)
    print(directory / name)


def cmd_edit(args: argparse.Namespace) -> None:
    config = _load_config()
    if args.list_tools:
        if args.picture is not None:
            sys.exit("amontillado: --list-tools takes no PICTURE")
        _list_tools(config)
        return
    if args.picture is None:
        sys.exit("amontillado: edit needs a PICTURE")
    command = _edit_command(config, args)
    if not config.index_path.exists():
        sys.exit(f"amontillado: no index at {config.index_path}; run `amo index` first")
    try:
        with closing(connect(config.index_path)) as conn:
            try:
                directory, root = record_location(conn, find_record(conn, args.picture))
                plan = plan_edit(directory, source=args.source, name=args.name)
            except (AddError, LookupFailed, RecordError) as exc:
                sys.exit(f"amontillado: {exc}")
            if args.dry_run:
                logger.info("would run %s on a copy of %s", command, directory / plan.source)
                return
            try:
                entry, name = run_edit(config, plan, root, command)
            except EditError as exc:
                kept = f"; what it saved is in {exc.workdir}" if exc.workdir is not None else ""
                sys.exit(f"amontillado: {exc}{kept}")
            except (RecordError, OSError, Image.DecompressionBombError) as exc:
                sys.exit(f"amontillado: {directory}: {exc}")
            replace_in_index(conn, entry)
    except (sqlite3.Error, IndexDatabaseError) as exc:
        _index_error(config, exc)
    print(directory / name)


def _edit_command(config: Config, args: argparse.Namespace) -> str:
    """The command line amo edit runs: --extcmd, else the tool --tool or edit.default_tool
    names."""
    if args.extcmd is not None:
        if not args.extcmd.strip():
            sys.exit("amontillado: --extcmd is empty")
        return args.extcmd
    name = args.tool or config.edit.default_tool
    if name is None:
        sys.exit("amontillado: no editor: pass --tool or --extcmd, or set edit.default_tool")
    tool = config.edit.tools.get(name)
    if tool is None:
        known = ", ".join(config.edit.tools) or "none"
        sys.exit(f"amontillado: no tool {name!r} under edit.tools (tools: {known})")
    return tool.cmd


def _list_tools(config: Config) -> None:
    tools = config.edit.tools
    if not tools:
        logger.info("no tools under edit.tools (amo config init writes examples)")
        return
    width = max(len(name) for name in tools)
    for name, tool in tools.items():
        default = " (default)" if name == config.edit.default_tool else ""
        print(f"{name:<{width}}  {tool.description or ''}{default}".rstrip())


def cmd_name(args: argparse.Namespace) -> None:
    if not args.from_tags and len(args.arguments) != 2:
        sys.exit("amontillado: name takes PICTURE NAME, or --from-tags [PICTURE...]")
    config = _load_config()
    if not config.index_path.exists():
        sys.exit(f"amontillado: no index at {config.index_path}; run `amo index` first")
    pictures = args.arguments if args.from_tags else args.arguments[:1]
    failed = 0
    try:
        with closing(connect(config.index_path)) as conn:
            try:
                ids = [find_record(conn, picture) for picture in pictures]
            except LookupFailed as exc:
                sys.exit(f"amontillado: {exc}")
            if args.from_tags and not ids:
                ids = unnamed(conn, SITE)
                if not ids:
                    logger.info("no unnamed record fetched from Wallhaven")
                    return
            taken = names(conn)
            for record_id in ids:
                directory, root = record_location(conn, record_id)
                old = record_name(conn, record_id)
                try:
                    if args.from_tags:
                        entry, given = name_from_tags(
                            config,
                            directory,
                            root,
                            taken,
                            rename_directory=args.rename_directory,
                            dry_run=args.dry_run,
                        )
                    else:
                        given = args.arguments[1]
                        entry = name_record(
                            config,
                            directory,
                            root,
                            given,
                            taken,
                            rename_directory=args.rename_directory,
                            dry_run=args.dry_run,
                        )
                except (NamingError, RecordError) as exc:
                    logger.error("%s", exc)
                    failed += 1
                    continue
                except OSError as exc:
                    logger.error("%s: %s", directory, exc)
                    failed += 1
                    continue
                taken.discard(old)
                taken.add(given)
                if args.dry_run:
                    logger.info("would name %s %s", directory, given)
                    continue
                replace_in_index(conn, entry)
                if entry.directory != directory:
                    for profile in repoint_wallpapers(config.theme, directory, entry.directory):
                        logger.info("profile %s: wallpaper link follows to %s", profile, given)
                print(entry.directory)
    except (sqlite3.Error, IndexDatabaseError) as exc:
        _index_error(config, exc)
    if failed:
        sys.exit(f"amontillado: {failed} of {_count(len(ids), 'record')} could not be named")


def cmd_fetch(args: argparse.Namespace) -> None:
    look = _look(args)
    if args.test_set and (look != Look() or args.count is not None):
        sys.exit("amontillado: --test-set takes no look filters or --count")
    wanted = len(TEST_SET) if args.test_set else args.count or 1
    config = _load_config()
    color = args.color and nearest_swatch(args.color)
    if color != args.color:
        logger.info(
            "--color %s is not a Wallhaven swatch; using the nearest, %s", args.color, color
        )
    search = Search(
        query=args.tags,
        purity=args.purity,
        categories=args.category,
        atleast=args.atleast,
        ratios=args.ratio,
        color=color,
    )
    options = FetchOptions(
        args.count or 1,
        args.max_candidates,
        args.busy_from,
        args.discard_mismatches,
        args.dry_run,
        args.test_set,
    )
    # Only NSFW needs the key, and its command may ask for a passphrase: no lookup otherwise.
    key = None
    if "nsfw" in args.purity:
        try:
            key = api_key(config)
        except ConfigError as exc:
            sys.exit(f"amontillado: {exc}")
        if key is None:
            sys.exit(
                f"amontillado: nsfw needs a Wallhaven API key: set {API_KEY_VARIABLE} or "
                "api_key_command"
            )
    try:
        with closing(connect(config.index_path)) as conn:
            report = fetch(config, conn, Client(key), search, look, options)
    except WallhavenError as exc:
        sys.exit(f"amontillado: {exc}")
    except (sqlite3.Error, IndexDatabaseError) as exc:
        _index_error(config, exc)
    if args.test_set:
        for name in TEST_SET:
            kept = report.buckets.get(name)
            if kept is not None:
                print(f"{name}\t{kept.url if isinstance(kept, Wallpaper) else kept}")
    else:
        for path in report.kept:
            print(path)
        for wallpaper in report.would_keep:
            print(wallpaper.url)
    logger.info(
        "%s %d, examined %s: %d rejected, %d failed; %d already in the library",
        "would keep" if args.dry_run else "kept",
        report.count,
        _count(report.examined, "thumbnail"),
        report.rejected,
        len(report.failed),
        report.known,
    )
    if report.mismatched or report.discarded:
        logger.info(
            "full images that did not match: %d kept anyway, %d discarded",
            len(report.mismatched),
            report.discarded,
        )
    if args.test_set and report.count < wanted:
        empty = [name for name in TEST_SET if name not in report.buckets]
        sys.exit(f"amontillado: empty buckets: {', '.join(empty)}")
    if report.count < wanted:
        sys.exit(f"amontillado: {report.count} of {wanted} wanted")


def _progress(description: str) -> Callable[[list[T]], Iterable[T]] | None:
    """A progress bar on stderr, cleared when done; None when stderr is not a terminal (a
    timer's run logs to the journal)."""
    if not STDERR.is_terminal:
        return None
    return lambda items: track(items, description=description, console=STDERR, transient=True)


def _summary(head: str, report: Report, check: bool) -> str:
    """`head`, then the counts in `report` that are not zero."""
    parts = [
        f"{len(report.healed)} {'to heal' if check else 'healed'}" if report.healed else "",
        _count(report.measured, "file") + (" to measure" if check else " measured")
        if report.measured
        else "",
        f"{report.renamed} renamed" if report.renamed else "",
        f"{_count(len(report.loose), 'image')} outside a record" if report.loose else "",
        f"{_count(len(report.missing), 'file')} missing" if report.missing else "",
        f"{_count(len(report.absent), 'file')} not here (git-annex)" if report.absent else "",
        _count(len(report.conflicts), "conflict") if report.conflicts else "",
        f"{len(report.failed)} failed" if report.failed else "",
    ]
    details = ", ".join(part for part in parts if part)
    return f"{head}: {details}" if details else head


def _problems(report: Report, *, check: bool) -> list[str]:
    """What makes `amo index` fail. Loose images and missing files only fail a check: they
    are reported, and a pass that leaves them alone has still done its job."""
    problems = []
    if check and report.healed:
        problems.append(f"{_count(len(report.healed), 'record')} to heal")
    if check and report.loose:
        problems.append(f"{_count(len(report.loose), 'image')} outside a record")
    if check and report.missing:
        problems.append(f"{_count(len(report.missing), 'file')} missing")
    if report.conflicts:
        problems.append(_count(len(report.conflicts), "conflict"))
    if report.failed:
        problems.append(f"{_count(len(report.failed), 'file')} could not be read or used")
    return problems


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}{'' if number == 1 else 's'}"


def main(argv: list[str] | None = None) -> None:
    args = get_cli_arguments(argv)
    setup_logger(args)
    if args.func is None:
        build_parser().print_help()
        return
    with changes.recording() as recorder:
        try:
            args.func(args)
        finally:
            # Also after a failure: what was written stands, and the hook sees it.
            _on_change(recorder, args.func.__name__.removeprefix("cmd_").replace("_", "-"))


def _on_change(recorder: changes.Recorder, command: str) -> None:
    """Run the on_change hook for what the command wrote, if it wrote anything."""
    if not (recorder.infos or recorder.files or recorder.renames):
        return
    try:
        config = load_config()
    except ConfigError as exc:
        logger.warning("on_change not run: %s", exc)
        return
    run_on_change(config, recorder, command)
