"""amontillado: a local wallpaper library that knows what its images look like.

Fetches wallpapers from Wallhaven, measures each image's lightness, colourfulness,
dominant hue and detail, keeps that next to the image, and answers queries such as
"a dark, muted, sparse wallpaper" from a local index.

Commands are added as they are built; see docs/design.md for the plan.
"""

from __future__ import annotations

import argparse
import math
import random
import re
import sqlite3
import sys
from contextlib import closing
from logging import getLogger
from pathlib import Path
from typing import NoReturn

import yaml
from PIL import Image
from rich.console import Console
from rich.logging import RichHandler
from rich_argparse import RawDescriptionRichHelpFormatter

from amontillado import __version__
from amontillado.classes import CLASSES, Look, classify, has_aspect
from amontillado.config import API_KEY_VARIABLE, Config, ConfigError, api_key, load_config
from amontillado.fetch import Options as FetchOptions
from amontillado.fetch import fetch
from amontillado.index import (
    IndexDatabaseError,
    IndexedFile,
    LookupFailed,
    connect,
    files,
    files_with_hash,
    find_record,
    names,
    rebuild,
    record_shown,
)
from amontillado.index import (
    add as add_to_index,
)
from amontillado.library import PURITIES, AddError, Report, add_picture, heal_library, place
from amontillado.metrics import HUE_NAMES, measure_file
from amontillado.record import sha256_file
from amontillado.wallhaven import CATEGORY_FLAGS, Client, Search, WallhavenError

logger = getLogger("amontillado")


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


def _add_loglevel(parser: argparse.ArgumentParser, default: str) -> None:
    parser.add_argument(
        "--loglevel",
        "-l",
        default=default,
        type=lambda v: v.strip().upper(),
        help="Logging verbosity (DEBUG, INFO, WARNING, ERROR; default INFO).",
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
        "metrics; records without one fall back to their default file, with a warning.",
    )
    list_.add_argument(
        "--random", type=_positive, metavar="N", help="Print N matches chosen at random."
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
        "the library, and a name another record has.",
        formatter_class=HelpFormatter,
    )
    _add_loglevel(add, argparse.SUPPRESS)
    add.add_argument("files", nargs="+", type=Path, metavar="FILE", help="Image files.")
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
    add.set_defaults(func=cmd_add)

    fetch = commands.add_parser(
        "fetch",
        help="Fetch wallpapers from Wallhaven.",
        description="Search Wallhaven in random order, measure each result's thumbnail, and "
        "keep the ones that match every filter: download each, make it a record (sfw ones in "
        "the first library root, others in the NSFW root), and index it. The full image is "
        "judged again; see --discard-mismatches. Prints the path of each file kept that "
        "matches. Results already in the library are passed over. Fails if fewer than "
        "--count are kept.",
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
        help="One of Wallhaven's colour swatches, e.g. 424153.",
    )
    fetch.add_argument(
        "--count", type=_positive, default=1, metavar="N", help="Stop after keeping N images."
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


def _aspect(value: str) -> float:
    width, _, height = value.partition(":")
    try:
        ratio = float(width) / float(height)
    except (ValueError, ZeroDivisionError):
        raise argparse.ArgumentTypeError("must be W:H, for example 21:9") from None
    if not (math.isfinite(ratio) and ratio > 0):
        raise argparse.ArgumentTypeError("must be W:H, for example 21:9")
    return ratio


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def get_cli_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def setup_logger(args: argparse.Namespace) -> None:
    # Rich's default console is stdout, which carries data (`amo list` output is piped).
    logger.addHandler(RichHandler(level=args.loglevel, console=Console(stderr=True)))
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
        print(yaml.safe_dump(results, sort_keys=False, allow_unicode=True), end="")
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
    report = heal_library(config, check=args.check)
    if not args.check:
        try:
            with closing(connect(config.index_path)) as conn:
                count = rebuild(conn, report.entries)
        except (sqlite3.Error, IndexDatabaseError, OSError) as exc:
            _index_error(config, exc)
        logger.info("indexed %s", _count(count, "record"))
    problems = _problems(report, check=args.check)
    if problems:
        sys.exit(f"amontillado: {', '.join(problems)}")


def cmd_list(args: argparse.Namespace) -> None:
    config = _load_config()
    if not config.index_path.exists():
        sys.exit(f"amontillado: no index at {config.index_path}; run `amo index` first")
    try:
        with closing(connect(config.index_path)) as conn:
            by_record: dict[str, list[IndexedFile]] = {}
            for row in files(conn):
                by_record.setdefault(row.record_id, []).append(row)
    except (sqlite3.Error, IndexDatabaseError, OSError) as exc:
        _index_error(config, exc)
    rows = [_pick(group, args.aspect) for group in by_record.values()]
    look = _look(args)
    matches = [row for row in rows if _matches(row, args, look, config)]
    if args.aspect is not None:
        fallbacks = sum(not has_aspect(row.width, row.height, args.aspect) for row in matches)
        if fallbacks:
            logger.warning(
                "no file of that aspect ratio for %s; using the default file",
                _count(fallbacks, "picture"),
            )
    present = [row for row in matches if row.path.is_file()]
    if len(present) < len(matches):
        gone = len(matches) - len(present)
        logger.warning("missing from disk: %s; run `amo index`", _count(gone, "file"))
    matches = present
    if args.random is not None:
        matches = random.sample(matches, min(args.random, len(matches)))
    if not matches:
        sys.exit("amontillado: no matching pictures")
    for row in matches:
        print(row.path)


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


def cmd_add(args: argparse.Namespace) -> None:
    if args.name is not None and len(args.files) > 1:
        sys.exit("amontillado: --name takes one FILE")
    config = _load_config()
    failed = 0
    try:
        with closing(connect(config.index_path)) as conn:
            taken = names(conn)
            for file in args.files:
                try:
                    _add_one(conn, config, file, args, taken)
                except AddError as exc:
                    logger.error("%s", exc)
                    failed += 1
                except (OSError, Image.DecompressionBombError) as exc:
                    logger.error("%s: %s", file, exc)
                    failed += 1
    except (sqlite3.Error, IndexDatabaseError) as exc:
        _index_error(config, exc)
    if failed:
        sys.exit(f"amontillado: {failed} of {len(args.files)} files could not be added")


def _add_one(
    conn: sqlite3.Connection,
    config: Config,
    file: Path,
    args: argparse.Namespace,
    taken: set[str],
) -> None:
    placement = place(config, file, name=args.name, nsfw=args.nsfw)
    if args.name in taken:
        raise AddError(f"name {args.name!r} is taken")
    duplicates = files_with_hash(conn, sha256_file(file))
    if duplicates and not args.force:
        raise AddError(f"{file}: same content as {duplicates[0]}; --force adds it anyway")
    if duplicates:
        logger.warning("%s: same content as %s", file, duplicates[0])
    if args.dry_run:
        logger.info("would add %s as %s", file, placement.directory)
        return
    entry = add_picture(config, placement, name=args.name)
    add_to_index(conn, entry)
    logger.info("added %s as %s", file, entry.directory)


def cmd_fetch(args: argparse.Namespace) -> None:
    config = _load_config()
    search = Search(
        query=args.tags,
        purity=args.purity,
        categories=args.category,
        atleast=args.atleast,
        ratios=args.ratio,
        color=args.color,
    )
    options = FetchOptions(
        args.count, args.max_candidates, args.busy_from, args.discard_mismatches, args.dry_run
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
            report = fetch(config, conn, Client(key), search, _look(args), options)
    except WallhavenError as exc:
        sys.exit(f"amontillado: {exc}")
    except (sqlite3.Error, IndexDatabaseError) as exc:
        _index_error(config, exc)
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
    if report.count < args.count:
        sys.exit(f"amontillado: {report.count} of {args.count} wanted")


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
    args.func(args)
