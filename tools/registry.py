#!/usr/bin/env python3
"""Move the template registry's pins and record each file's hash.

For every repository in src/amontillado/registry.yaml: find its default branch's head commit
(GitHub API), fetch each registered file at that commit (raw.githubusercontent.com), and
record the commit and the file's sha256. A tinted-theming template must be one its
templates/config.yaml builds for base16 or base24 (not tinted8, whose variables differ).
Without --update, print what would change; with it, rewrite registry.yaml. Needs the network;
the release checklist runs it.

  uv run tools/registry.py            # report
  uv run tools/registry.py --update   # rewrite the pins and hashes
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from logging import getLogger
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from amontillado import yamlio
from amontillado.cli import HelpFormatter
from amontillado.registry import RegistryError, parse
from amontillado.wallhaven import USER_AGENT, WallhavenError, http_get

logger = getLogger("registry")

REGISTRY = Path(__file__).resolve().parent.parent / "src" / "amontillado" / "registry.yaml"
GITHUB_API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
SYSTEMS = {"base16", "base24"}


def get_cli_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=HelpFormatter)
    parser.add_argument(
        "--loglevel",
        "-l",
        default="INFO",
        type=lambda v: v.strip().upper(),
        help="Logging verbosity (DEBUG, INFO, WARNING, ERROR).",
    )
    parser.add_argument(
        "--update", action="store_true", help="Rewrite registry.yaml with the new pins."
    )
    return parser.parse_args()


def setup_logger(args: argparse.Namespace) -> None:
    handler = RichHandler(level=args.loglevel, console=Console(stderr=True))
    logger.addHandler(handler)
    logger.setLevel(args.loglevel)


def get(url: str) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    if url.startswith(GITHUB_API):
        headers["Accept"] = "application/vnd.github+json"
    response = http_get(url, headers)
    if response.status != 200:
        sys.exit(f"registry: {url}: HTTP {response.status}")
    return response.body


def head_commit(repository: str) -> str:
    return json.loads(get(f"{GITHUB_API}/repos/{repository}/commits/HEAD"))["sha"]


def check_systems(repository: str, commit: str, path: str) -> None:
    """Exit unless tinted's templates/config.yaml builds `path` for base16 or base24."""
    config = yamlio.load(get(f"{RAW}/{repository}/{commit}/templates/config.yaml").decode())
    name = Path(path).name.removesuffix(".mustache")
    entry = config.get(name) if isinstance(config, dict) else None
    if not isinstance(entry, dict):
        sys.exit(f"registry: {repository}: templates/config.yaml has no {name}")
    # A template without the key is base16's (the tinted builder's default).
    systems = set(entry.get("supported-systems", ["base16"]))
    if not systems & SYSTEMS:
        sys.exit(f"registry: {repository} {name}: built for {sorted(systems)}, not base16/24")


def main() -> None:
    args = get_cli_arguments()
    setup_logger(args)
    text = REGISTRY.read_text()
    data = yamlio.load(text)
    changes = 0
    try:
        for repository, pin in data["repositories"].items():
            commit = head_commit(repository)
            if pin.get("commit") != commit:
                logger.info("%s: %s -> %s", repository, pin.get("commit"), commit)
                pin["commit"] = commit
                changes += 1
            for source, templates in data["sources"].items():
                for name, entry in templates.items():
                    if entry.get("repository") != repository:
                        continue
                    if source == "tinted":
                        check_systems(repository, commit, entry["path"])
                    sha256 = hashlib.sha256(get(f"{RAW}/{repository}/{commit}/{entry['path']}"))
                    if entry.get("sha256") != sha256.hexdigest():
                        logger.info("%s %s: %s", source, name, sha256.hexdigest())
                        entry["sha256"] = sha256.hexdigest()
                        changes += 1
        parse(data)
    except (WallhavenError, RegistryError) as exc:
        sys.exit(f"registry: {exc}")
    logger.info("%d change%s", changes, "" if changes == 1 else "s")
    if args.update and changes:
        # Only the changed pins and hashes: comments and the one-line entries stay.
        REGISTRY.write_text(yamlio.update_text(text, data))


if __name__ == "__main__":
    main()
