"""amontillado: a local wallpaper library that knows what its images look like.

Fetches wallpapers from Wallhaven, measures each image's lightness, colourfulness,
dominant hue and detail, keeps that next to the image, and answers queries such as
"a dark, muted, sparse wallpaper" from a local index.

Commands are added as they are built; see docs/design.md for the plan.
"""

from __future__ import annotations

import argparse
import random
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
from amontillado.classes import CLASSES, classify, has_hue
from amontillado.config import Config, ConfigError, load_config
from amontillado.index import IndexDatabaseError, IndexedImage, connect, images, rebuild
from amontillado.library import PURITIES, Report, heal_library
from amontillado.metrics import HUE_NAMES, measure_file

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
        help="Heal sidecars and rebuild the index.",
        description="Give every image a sidecar, rewrite broken or outdated ones, and rebuild "
        "the index from them (the usage history is kept). Searches the library roots and the "
        "NSFW root.",
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
        help="Print the paths of matching images.",
        description="Print the paths of indexed images that match every filter, one per line. "
        "Images from the NSFW root, and any not marked sfw, are left out unless --purity asks "
        'for them. Class thresholds are in docs/design.md, "Classes".',
        formatter_class=HelpFormatter,
    )
    _add_loglevel(list_, argparse.SUPPRESS)
    for pair in _CLASS_PAIRS:
        group = list_.add_mutually_exclusive_group()
        for name in pair:
            group.add_argument(f"--{name}", action="store_true", help=f"Only {name} images.")
    list_.add_argument(
        "--hue", choices=HUE_NAMES, metavar="NAME", help=f"Dominant hue: {', '.join(HUE_NAMES)}."
    )
    list_.add_argument(
        "--purity",
        type=_purities,
        metavar="LIST",
        help="Comma-separated purities to include (sfw, sketchy, nsfw); also searches the "
        "NSFW root. Default: sfw only, NSFW root excluded.",
    )
    list_.add_argument(
        "--random", type=_positive, metavar="N", help="Print N matches chosen at random."
    )
    list_.set_defaults(func=cmd_list)

    return parser


def _purities(value: str) -> frozenset[str]:
    names = frozenset(name.strip() for name in value.split(","))
    unknown = names - set(PURITIES)
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown purity: {', '.join(sorted(unknown))}")
    return names


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
        logger.info("indexed %d images", count)
    problems = _problems(report, check=args.check)
    if problems:
        sys.exit(f"amontillado: {', '.join(problems)}")


def cmd_list(args: argparse.Namespace) -> None:
    config = _load_config()
    if not config.index_path.exists():
        sys.exit(f"amontillado: no index at {config.index_path}; run `amo index` first")
    try:
        with closing(connect(config.index_path)) as conn:
            rows = images(conn)
    except (sqlite3.Error, IndexDatabaseError, OSError) as exc:
        _index_error(config, exc)
    wanted = [name for name in CLASSES if getattr(args, name.replace("-", "_"))]
    matches = [row for row in rows if _matches(row, args, wanted, config)]
    present = [row for row in matches if row.path.is_file()]
    if len(present) < len(matches):
        gone = len(matches) - len(present)
        logger.warning("missing from disk: %s; run `amo index`", _count(gone, "image"))
    matches = present
    if args.random is not None:
        matches = random.sample(matches, min(args.random, len(matches)))
    if not matches:
        sys.exit("amontillado: no matching images")
    for row in matches:
        print(row.path)


def _matches(
    row: IndexedImage, args: argparse.Namespace, wanted: list[str], config: Config
) -> bool:
    if row.purity not in (args.purity or {"sfw"}):
        return False
    # Checked against the current config too, and through symlinks: the index may predate a
    # config change, and a picker bug must not put an NSFW image on screen.
    if args.purity is None and (
        row.nsfw_root or row.path.resolve().is_relative_to(config.nsfw_root)
    ):
        return False
    if not all(CLASSES[name](row.metrics) for name in wanted):
        return False
    return args.hue is None or has_hue(row.metrics, args.hue)


def _problems(report: Report, *, check: bool) -> list[str]:
    """What makes `amo index` fail. Orphaned sidecars only fail a check: they are reported,
    and a pass that leaves them alone has still done its job."""
    problems = []
    if check and report.healed:
        problems.append(f"{_count(len(report.healed), 'sidecar')} to heal")
    if check and report.orphans:
        problems.append(f"{_count(len(report.orphans), 'sidecar')} without an image")
    if report.conflicts:
        problems.append(f"{_count(len(report.conflicts), 'sidecar name conflict')}")
    if report.failed:
        problems.append(f"{_count(len(report.failed), 'image')} could not be read")
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
