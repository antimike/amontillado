"""Fetching: Wallhaven search results, judged by their thumbnails, kept as records.

docs/design.md, "Fetcher (Wallhaven)". For each search result not already in the index, the
`large` thumbnail is measured and judged against the look filters; a result that passes is
downloaded (to a temporary file in its root, then renamed into a new record directory), given
its tags, and recorded with metrics measured on the full image, never the thumbnail. Sfw
images go to the first library root, sketchy and nsfw ones to the NSFW root.

The full image is judged again. One that no longer matches (a borderline thumbnail) is still
kept by default, since it has been downloaded, but does not count towards `count`;
`discard_mismatches` deletes it instead.

A test set (`Options.test_set`) keeps one image per bucket in TEST_SET instead of `count`
images of one look: an image fills the first bucket still open that it belongs to, judged on
the full image, so it fills one bucket only.
"""

from __future__ import annotations

import io
import os
import sqlite3
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging import getLogger
from pathlib import Path

from PIL import Image

from amontillado.classes import Look, classify
from amontillado.config import Config
from amontillado.index import add as add_to_index
from amontillado.index import files_with_hash, source_ids
from amontillado.library import Entry, source_ids_on_disk
from amontillado.metrics import Metrics, image_size, measure_file
from amontillado.record import INFO_NAMES, FileEntry, Record, sha256_file, write_record
from amontillado.wallhaven import Client, Search, WallhavenError, Wallpaper

logger = getLogger(__name__)

SITE = "wallhaven"
# Not judged on the thumbnail with --busy-from full: thumbnail JPEG artefacts add edges.
BUSY_CLASSES = ("busy", "sparse")
# The visual extremes a palette generator is compared on (docs/design.md, "Test set").
TEST_SET = ("dark", "light", "muted", "saturated", "busy", "sparse", "monochrome", "multi-hue")


class FetchError(Exception):
    """A search result cannot be kept; the message says why."""


@dataclass(frozen=True)
class Options:
    count: int = 1
    max_candidates: int = 100
    busy_from: str = "thumb"
    discard_mismatches: bool = False
    dry_run: bool = False
    test_set: bool = False


@dataclass
class FetchReport:
    """What a fetch kept (or, in a dry run, would have kept) and passed over."""

    kept: list[Path] = field(default_factory=list)
    # Kept, but the full image does not match: not counted towards Options.count.
    mismatched: list[Path] = field(default_factory=list)
    would_keep: list[Wallpaper] = field(default_factory=list)
    examined: int = 0
    known: int = 0
    rejected: int = 0
    discarded: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    # With Options.test_set: what fills each bucket, a path or, in a dry run, a wallpaper.
    buckets: dict[str, Path | Wallpaper] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.kept) + len(self.would_keep)


def fetch(
    config: Config,
    conn: sqlite3.Connection,
    client: Client,
    search: Search,
    look: Look,
    options: Options,
) -> FetchReport:
    """Keep up to `options.count` search results that look as asked (with `options.test_set`,
    one per TEST_SET bucket, and `look` must be empty), examining at most
    `options.max_candidates` thumbnails. WallhavenError if the search itself fails."""
    report = FetchReport()
    late = BUSY_CLASSES if options.busy_from == "full" else ()
    if options.test_set:
        if look != Look():
            raise ValueError("a test set takes no look filters")
        # A dry run never sees the full image: buckets judged only there cannot be filled.
        names = [n for n in TEST_SET if not (options.dry_run and n in late)]
        slots: list[tuple[str | None, Look]] = [(name, Look((name,))) for name in names]
    else:
        slots = [(None, look)] * options.count
    known = source_ids(conn, SITE)
    unindexed = source_ids_on_disk(config, SITE) - known
    if unindexed:
        logger.warning(
            "Wallhaven records not in the index (passed over anyway; run `amo index`): %d",
            len(unindexed),
        )
    known |= unindexed
    if late and options.dry_run and (options.test_set or any(n in look.classes for n in late)):
        logger.warning("dry run with --busy-from full: busy and sparse are not judged")
    for wallpaper in client.search(search):
        if not slots or report.examined >= options.max_candidates:
            break
        if wallpaper.id in known:
            report.known += 1
            logger.debug("%s: already in the library", wallpaper.id)
            continue
        if wallpaper.purity not in search.purity:
            # Wallhaven filters by purity; an answer it should not have given is never kept.
            logger.warning("%s: purity %s was not asked for", wallpaper.id, wallpaper.purity)
            continue
        report.examined += 1
        try:
            thumbnail = measure_file(io.BytesIO(client.download(wallpaper.thumbnail)))
        except (WallhavenError, OSError, Image.DecompressionBombError) as exc:
            _failed(report, wallpaper, f"thumbnail: {exc}")
            continue
        slot = _slot(slots, thumbnail, late)
        if slot is None:
            report.rejected += 1
            logger.debug("%s: rejected (%s)", wallpaper.id, _classes(thumbnail))
            continue
        if options.dry_run:
            _fill(report, slots, slot, wallpaper)
            report.would_keep.append(wallpaper)
            logger.info("would keep %s (%s)", wallpaper.url, _classes(thumbnail))
            continue
        try:
            kept = _keep(
                config,
                conn,
                client,
                wallpaper,
                lambda m: _slot(slots, m) is not None,
                options.discard_mismatches,
            )
        except (FetchError, WallhavenError, OSError, Image.DecompressionBombError) as exc:
            _failed(report, wallpaper, str(exc))
            continue
        if kept is None:
            report.discarded += 1
            continue
        path, metrics = kept
        known.add(wallpaper.id)
        slot = _slot(slots, metrics)
        if slot is None:
            report.mismatched.append(path)
            continue
        _fill(report, slots, slot, path)
        report.kept.append(path)
    return report


def _slot(
    slots: list[tuple[str | None, Look]], metrics: Metrics, late: tuple[str, ...] = ()
) -> int | None:
    """The index of the first open slot whose look `metrics` matches, or None."""
    return next(
        (i for i, (_, look) in enumerate(slots) if look.matches(metrics, ignore=late)), None
    )


def _fill(
    report: FetchReport,
    slots: list[tuple[str | None, Look]],
    slot: int,
    kept: Path | Wallpaper,
) -> None:
    """Close `slot`, filled by `kept`."""
    name, _ = slots.pop(slot)
    if name is not None:
        report.buckets[name] = kept


def _failed(report: FetchReport, wallpaper: Wallpaper, message: str) -> None:
    report.failed.append((wallpaper.id, message))
    logger.error("%s: %s", wallpaper.id, message)


def _classes(metrics: Metrics) -> str:
    return ", ".join(classify(metrics)) or "no class"


def _keep(
    config: Config,
    conn: sqlite3.Connection,
    client: Client,
    wallpaper: Wallpaper,
    accept: Callable[[Metrics], bool],
    discard_mismatches: bool,
) -> tuple[Path, Metrics] | None:
    """Download a wallpaper and make it a record; returns its file and the full image's
    metrics, or None if `accept` refuses them and `discard_mismatches` deleted it. Nothing is
    left behind on failure."""
    root = config.library_roots[0] if wallpaper.purity == "sfw" else config.nsfw_root
    directory = root / f"wallhaven-{wallpaper.id}"
    if directory.exists():
        raise FetchError(f"{directory} already exists; run `amo index`")
    data = client.download(wallpaper.image_url)
    root.mkdir(parents=True, exist_ok=True)
    # Not an image suffix, so a scan of the root never takes it for a loose image.
    fd, name = tempfile.mkstemp(dir=root, prefix=f".{wallpaper.file_name}.", suffix=".part")
    temporary = Path(name)
    file = directory / wallpaper.file_name
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        width, height = image_size(temporary)
        metrics = measure_file(temporary)
        matches = accept(metrics)
        if not matches and discard_mismatches:
            logger.info(
                "%s: discarded: the full image does not match (%s)", wallpaper.id, _classes(metrics)
            )
            return None
        sha256 = sha256_file(temporary)
        duplicates = files_with_hash(conn, sha256)
        if duplicates:
            raise FetchError(f"same content as {duplicates[0]}")
        tags = client.tags(wallpaper.id)
        directory.mkdir(parents=True)
        os.replace(temporary, file)
        record = Record(
            uuid.uuid4().hex,
            source=_source(wallpaper, tags),
            fetched=datetime.now(timezone.utc).replace(microsecond=0),
            files={file.name: FileEntry(sha256, width, height, metrics)},
        )
        write_record(directory / INFO_NAMES[0], record)
    except BaseException:
        file.unlink(missing_ok=True)
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
        raise
    finally:
        temporary.unlink(missing_ok=True)
    nsfw = directory.resolve().is_relative_to(config.nsfw_root)
    add_to_index(conn, Entry(directory, root, nsfw, record, (file.name,), file.name, None))
    if matches:
        logger.info("kept %s (%s)", file, _classes(metrics))
    else:
        logger.info("kept %s, but the full image does not match (%s)", file, _classes(metrics))
    return file, metrics


def _source(wallpaper: Wallpaper, tags: list[str]) -> dict[str, object]:
    return {
        "site": SITE,
        "id": wallpaper.id,
        "url": wallpaper.url,
        "image_url": wallpaper.image_url,
        "purity": wallpaper.purity,
        "category": wallpaper.category,
        "tags": tags,
        "colors": list(wallpaper.colors),
        "source": wallpaper.source,
        "uploaded": wallpaper.uploaded,
    }
