"""amontillado: a local wallpaper library that knows what its images look like.

Fetches wallpapers from Wallhaven, measures each image's lightness, colourfulness,
dominant hue and detail, keeps that next to the image, and answers queries such as
"a dark, muted, sparse wallpaper" from a local index.

Commands are added as they are built; see docs/design.md for the plan.
"""

from __future__ import annotations

import argparse
import sys
from logging import getLogger
from pathlib import Path

import yaml
from PIL import Image
from rich.console import Console
from rich.logging import RichHandler
from rich_argparse import RawDescriptionRichHelpFormatter

from amontillado import __version__
from amontillado.classes import classify
from amontillado.metrics import measure_file

logger = getLogger("amontillado")


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

    return parser


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


def main(argv: list[str] | None = None) -> None:
    args = get_cli_arguments(argv)
    setup_logger(args)
    if args.func is None:
        build_parser().print_help()
        return
    args.func(args)
