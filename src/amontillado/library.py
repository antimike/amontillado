"""The library: the records under the roots, and healing their info files.

docs/design.md, "Records". A record is a directory under a root holding `info.yaml` (or
`info.yml`) and the picture's files. Healing recomputes derived fields (`id` when absent, and
per file `sha256`, `width`, `height`, `metrics`) and never rewrites authored ones: a record
whose info file does not parse, or whose authored fields are invalid, is reported and left
alone. Within a record, an unlisted image with the hash of a listed file that is missing is
that file renamed; other unlisted images are added; listed files that are missing keep their
entries and are reported. Images outside any record are reported, never moved.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import shutil
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from logging import getLogger
from pathlib import Path

from PIL import Image

from amontillado.config import Config
from amontillado.metrics import image_size, measure_file
from amontillado.record import (
    IMAGE_SUFFIXES,
    INFO_NAMES,
    NAME_PATTERN,
    FileEntry,
    Record,
    RecordError,
    load_raw,
    read_record,
    sha256_file,
    write_record,
)

logger = getLogger(__name__)

PURITIES = ("sfw", "sketchy", "nsfw")


@dataclass(frozen=True)
class Entry:
    """A record that can be indexed, with the files of it that are present."""

    directory: Path
    root: Path
    nsfw_root: bool
    record: Record
    present: tuple[str, ...]
    default: str
    # The name the record answers to: None when another record has the same one.
    name: str | None

    @property
    def id(self) -> str:
        assert self.record.id is not None
        return self.record.id

    @property
    def purity(self) -> str:
        """The source's purity; without one, what the record's root implies."""
        source = self.record.source or {}
        purity = source.get("purity")
        if purity in PURITIES:
            return purity
        return "nsfw" if self.nsfw_root else "sfw"


@dataclass
class Report:
    """What a pass over the library found, and (unless checking) did."""

    entries: list[Entry] = field(default_factory=list)
    records: int = 0
    healed: list[tuple[Path, str]] = field(default_factory=list)
    # Files measured (or, checking, to be measured), and files re-paired by hash.
    measured: int = 0
    renamed: int = 0
    loose: list[Path] = field(default_factory=list)
    missing: list[Path] = field(default_factory=list)
    conflicts: list[list[Path]] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.healed or self.loose or self.missing or self.conflicts or self.failed)


@dataclass(frozen=True)
class _Found:
    """A record directory as the scan found it."""

    directory: Path
    root: Path
    info: Path
    images: tuple[str, ...]


def heal_library(
    config: Config,
    *,
    check: bool = False,
    track: Callable[[list[_Found]], Iterable[_Found]] | None = None,
) -> Report:
    """Heal every record under the library roots and the NSFW root.

    With `check`, nothing is measured or written: `healed` lists what would be healed, and
    `entries` stays empty. `track` wraps the records found, for a progress display.
    """
    report = Report()
    found = _scan(config, report)
    report.records = len(found)
    hashes: dict[str, list[Path]] = defaultdict(list)
    ids: dict[str, list[Path]] = defaultdict(list)
    names: dict[str, list[Path]] = defaultdict(list)
    entries: list[Entry] = []
    for record_dir in track(found) if track else found:
        path = record_dir.info
        try:
            healed = _heal_record(record_dir, report, check=check)
        except RecordError as exc:
            report.failed.append((path, str(exc)))
            logger.error("%s: %s; fix it by hand", path, exc)
            continue
        if healed is None:
            continue
        record, file_hashes = healed
        for name, digest in file_hashes.items():
            hashes[digest].append(record_dir.directory / name)
        if record.id is not None:
            ids[record.id].append(path)
        if record.name is not None:
            names[record.name].append(path)
        if check:
            continue
        present = tuple(sorted(file_hashes))
        default = record.default(set(present))
        if default is None:
            continue
        nsfw = record_dir.directory.resolve().is_relative_to(config.nsfw_root)
        entry = Entry(
            record_dir.directory, record_dir.root, nsfw, record, present, default, record.name
        )
        if not entry.nsfw_root and entry.purity != "sfw":
            logger.warning(
                "%s: %s record outside the NSFW root", record_dir.directory, entry.purity
            )
        entries.append(entry)

    for paths in hashes.values():
        if len(paths) > 1:
            logger.warning("same content: %s", ", ".join(str(path) for path in sorted(paths)))
    duplicate_ids = {key for key, paths in ids.items() if len(paths) > 1}
    for key in sorted(duplicate_ids):
        report.conflicts.append(sorted(ids[key]))
        logger.error(
            "id %s is in %s; delete the id line from all but one for a new id at the next "
            "`amo index`",
            key,
            ", ".join(str(path) for path in sorted(ids[key])),
        )
    duplicate_names = {key for key, paths in names.items() if len(paths) > 1}
    for key in sorted(duplicate_names):
        report.conflicts.append(sorted(names[key]))
        logger.error(
            "name %r is in %s; neither answers to it until one is renamed",
            key,
            ", ".join(str(path) for path in sorted(names[key])),
        )
    report.entries = [
        dataclasses.replace(entry, name=None) if entry.name in duplicate_names else entry
        for entry in entries
        if entry.id not in duplicate_ids
    ]
    return report


def _scan(config: Config, report: Report) -> list[_Found]:
    """The record directories under every root; loose images and info files directly in a
    root go to `report`. Overlapping roots would find a directory twice; it is kept under the
    first root."""
    found: list[_Found] = []
    seen: set[Path] = set()
    for root in (*config.library_roots, config.nsfw_root):
        if not root.is_dir():
            logger.debug("%s: no such directory", root)
            continue
        # os.walk does not follow directory symlinks, so a symlink cannot pull in another tree.
        for dirpath, dirnames, filenames in os.walk(root):
            directory = Path(dirpath)
            dirnames.sort()
            if directory.resolve() in seen:
                dirnames.clear()
                continue
            seen.add(directory.resolve())
            info = [name for name in INFO_NAMES if name in filenames]
            images = tuple(
                sorted(name for name in filenames if Path(name).suffix.lower() in IMAGE_SUFFIXES)
            )
            if info and directory != root:
                # A record's files are directly inside it: records do not nest.
                dirnames.clear()
                if len(info) > 1:
                    paths = [directory / name for name in info]
                    report.conflicts.append(paths)
                    logger.error("%s: both %s; remove one", directory, " and ".join(info))
                else:
                    found.append(_Found(directory, root, directory / info[0], images))
                continue
            for name in info:
                logger.warning("%s: an info file directly in a root is ignored", directory / name)
            for name in images:
                if (directory / name).is_file():
                    report.loose.append(directory / name)
                    logger.warning("%s: not in a record; `amo add` it", directory / name)
    return found


def _heal_record(
    found: _Found, report: Report, *, check: bool
) -> tuple[Record, dict[str, str]] | None:
    """Heal one record. Returns it (with derived fields filled in unless checking) and the
    hashes of its files that are present, or None if it failed; RecordError if its info file
    cannot be used."""
    directory, path = found.directory, found.info
    try:
        record = read_record(path)
        # A broken symlink (an annexed file whose content is not here) is not present.
        hashes = {
            name: sha256_file(directory / name)
            for name in found.images
            if (directory / name).is_file()
        }
    except OSError as exc:
        report.failed.append((directory, str(exc)))
        logger.error("%s: %s", directory, exc)
        return None

    reasons: list[str] = []
    # Routine heals (a new record, measuring) log at DEBUG; a first index would log one line
    # per record. Content changes and renames are worth seeing.
    notable = False
    if record.id is None:
        record = dataclasses.replace(record, id=uuid.uuid4().hex)
        reasons.append("new id")
    files = dict(record.files)
    unlisted = [name for name in hashes if name not in files]
    missing = [name for name in files if name not in hashes]

    renames: dict[str, str] = {}
    for old in missing:
        match = next((name for name in unlisted if hashes[name] == files[old].sha256), None)
        if match is not None:
            unlisted.remove(match)
            renames[old] = match
            reasons.append(f"{match}: renamed from {old}")
    if renames:
        notable = True
        report.renamed += len(renames)
        files = {
            renames.get(name, name): dataclasses.replace(
                entry, derived_from=renames.get(entry.derived_from, entry.derived_from)
            )
            for name, entry in files.items()
        }
        default_file = renames.get(record.default_file, record.default_file)
        record = dataclasses.replace(record, default_file=default_file)

    to_measure: list[str] = []
    for name, entry in files.items():
        if name not in hashes:
            continue
        if entry.sha256 is not None and entry.sha256 != hashes[name]:
            reasons.append(f"{name}: content changed")
            notable = True
            to_measure.append(name)
        elif not entry.complete:
            reasons.append(f"{name}: measured")
            to_measure.append(name)
    for name in unlisted:
        reasons.append(f"{name}: added")
        files[name] = FileEntry()
        to_measure.append(name)

    for name in files:
        if name not in hashes:
            report.missing.append(directory / name)
            logger.warning("%s: listed in %s but missing", directory / name, path.name)
    if not files:
        report.missing.append(directory)
        logger.warning("%s: record without files", directory)
    if record.default_file is not None and record.default_file not in hashes:
        logger.warning(
            "%s: default_file %s is missing; using another file", directory, record.default_file
        )

    if reasons:
        report.healed.append((path, "; ".join(reasons)))
        logger.log(
            logging.INFO if notable else logging.DEBUG,
            "%s: %s%s",
            path,
            "would heal: " if check else "healed: ",
            "; ".join(reasons),
        )
    if check:
        report.measured += len(to_measure)
        return dataclasses.replace(record, files=files), hashes

    for name in to_measure:
        file = directory / name
        try:
            width, height = image_size(file)
            metrics = measure_file(file)
        except (OSError, Image.DecompressionBombError) as exc:
            report.failed.append((file, str(exc)))
            logger.error("%s: %s", file, exc)
            return None
        files[name] = dataclasses.replace(
            files[name], sha256=hashes[name], width=width, height=height, metrics=metrics
        )
    report.measured += len(to_measure)
    record = dataclasses.replace(record, files=files)
    if reasons:
        write_record(path, record)
    return record, hashes


def source_ids_on_disk(config: Config, site: str) -> set[str]:
    """The ids, at `site`, named in the `source` of every info file under the roots.

    Read from the files, not the index, which can be stale: a record synced in from another
    machine is not indexed until the next `amo index`. Every info file is parsed on each call;
    docs/design.md, "Flow", says when to revisit that. An info file that cannot be read is
    skipped here: `amo index` reports it.
    """
    ids: set[str] = set()
    for root in (*config.library_roots, config.nsfw_root):
        # os.walk does not follow directory symlinks, as in _scan.
        for dirpath, dirnames, filenames in os.walk(root):
            directory = Path(dirpath)
            info = [name for name in INFO_NAMES if name in filenames]
            if not info or directory == root:
                continue
            dirnames.clear()
            for name in info:
                try:
                    source = load_raw(directory / name).get("source")
                except (RecordError, OSError) as exc:
                    logger.debug("%s: %s", directory / name, exc)
                    continue
                if isinstance(source, dict) and source.get("site") == site:
                    source_id = source.get("id")
                    # A hand-edited id of digits only loads as an int.
                    if isinstance(source_id, (str, int)) and not isinstance(source_id, bool):
                        ids.add(str(source_id))
    return ids


class AddError(Exception):
    """A file cannot be made a record; the message says why."""


@dataclass(frozen=True)
class Placement:
    """Where `amo add` puts a file: the new record's directory, under `root`."""

    file: Path
    root: Path
    directory: Path


def place(config: Config, file: Path, *, name: str | None, nsfw: bool) -> Placement:
    """Where `file` would become a record: beside it if it is under a root, else in the first
    library root (or the NSFW root with `nsfw`), in a directory named `name` or its stem.
    Raises AddError."""
    if not file.is_file() or file.suffix.lower() not in IMAGE_SUFFIXES:
        raise AddError(f"{file}: not an image file")
    if name is not None and not NAME_PATTERN.fullmatch(name):
        raise AddError(f"name {name!r} does not match {NAME_PATTERN.pattern}")
    resolved = file.resolve()
    roots = (*config.library_roots, config.nsfw_root)
    root = next((root for root in roots if resolved.is_relative_to(root.resolve())), None)
    if root is not None:
        if nsfw:
            raise AddError(f"{file}: already under the root {root}; --nsfw is for other files")
        directory = resolved.parent
        while directory != root.resolve():
            if any((directory / info).is_file() for info in INFO_NAMES):
                raise AddError(f"{file}: already in the record {directory}")
            directory = directory.parent
        parent = file.parent
    else:
        root = config.nsfw_root if nsfw else config.library_roots[0]
        parent = root
    directory = parent / (name or file.stem)
    if directory.exists():
        raise AddError(f"{directory} already exists")
    return Placement(file, root, directory)


def add_picture(config: Config, placement: Placement, *, name: str | None) -> Entry:
    """Make a record of one file: measure it, move it into the new directory, write the info
    file. Raises OSError or Image.DecompressionBombError (before anything moves, if measuring
    fails)."""
    file = placement.file
    entry = FileEntry(sha256_file(file), *image_size(file), measure_file(file))
    record = Record(uuid.uuid4().hex, name=name, files={file.name: entry})
    placement.directory.mkdir(parents=True)
    shutil.move(file, placement.directory / file.name)
    write_record(placement.directory / INFO_NAMES[0], record)
    nsfw = placement.directory.resolve().is_relative_to(config.nsfw_root)
    return Entry(placement.directory, placement.root, nsfw, record, (file.name,), file.name, name)
