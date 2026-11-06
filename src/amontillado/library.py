"""The library: the records under the roots, and healing their info files.

docs/design.md, "Records". A record is a directory under a root holding `info.yaml` (or
`info.yml`) and the picture's files. Healing recomputes derived fields (`id` when absent, a
missing `thumbnail`, and per file `sha256`, `width`, `height`, `metrics`) and never rewrites
authored ones: a record
whose info file does not parse, or whose authored fields are invalid, is reported and left
alone. Within a record, an unlisted image with the hash of a listed file that is missing is
that file renamed; other unlisted images are added; listed files that are missing keep their
entries and are reported. Images outside any record are reported, never moved. A file whose
size and mtime are what the index last saw is not hashed again.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import shutil
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from logging import getLogger
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image

from amontillado.classes import has_aspect
from amontillado.config import Config
from amontillado.metrics import image_size, measure_file, write_crop, write_thumbnail
from amontillado.record import (
    IMAGE_SUFFIXES,
    INFO_NAMES,
    NAME_PATTERN,
    THUMBNAIL_PATH,
    FileEntry,
    Record,
    RecordError,
    info_path,
    load_raw,
    read_record,
    sha256_file,
    write_record,
)

logger = getLogger(__name__)

PURITIES = ("sfw", "sketchy", "nsfw")
# The longer side of a thumbnail amontillado makes, in pixels (*initial*).
THUMBNAIL_SIZE = 400

# A file's size and mtime (ns): when both are unchanged, so is its content (the hash cache).
Stat = tuple[int, int]


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
    # The Stat of each present file when it was hashed, for the hash cache.
    stats: Mapping[str, Stat] = field(default_factory=dict)

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
    known: Mapping[str, tuple[int, int, str]] | None = None,
    track: Callable[[list[_Found]], Iterable[_Found]] | None = None,
) -> Report:
    """Heal every record under the library roots and the NSFW root.

    With `check`, nothing is measured or written: `healed` lists what would be healed, and
    `entries` stays empty. `known` maps a file's path to its size, mtime (ns) and hash as last
    indexed: a file whose size and mtime match is not hashed again. `track` wraps the records
    found, for a progress display.
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
            healed = _heal_record(record_dir, report, check=check, known=known or {})
        except RecordError as exc:
            report.failed.append((path, str(exc)))
            logger.error("%s: %s; fix it by hand", path, exc)
            continue
        if healed is None:
            continue
        record, file_hashes, stats = healed
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
            record_dir.directory,
            record_dir.root,
            nsfw,
            record,
            present,
            default,
            record.name,
            stats,
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
    found: _Found, report: Report, *, check: bool, known: Mapping[str, tuple[int, int, str]]
) -> tuple[Record, dict[str, str], dict[str, Stat]] | None:
    """Heal one record. Returns it (with derived fields filled in unless checking), and the
    hashes and Stats of its files that are present, or None if it failed; RecordError if its
    info file cannot be used."""
    directory, path = found.directory, found.info
    hashes: dict[str, str] = {}
    stats: dict[str, Stat] = {}
    try:
        record = read_record(path)
        for name in found.images:
            file = directory / name
            # A broken symlink (an annexed file whose content is not here) is not present.
            if not file.is_file():
                continue
            # Stat before hashing: a change while hashing then shows at the next index.
            stats[name] = file_stat(file)
            cached = known.get(str(file))
            if cached is not None and cached[:2] == stats[name]:
                hashes[name] = cached[2]
            else:
                hashes[name] = sha256_file(file)
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
    thumbnail = record.thumbnail
    needs_thumbnail = bool(hashes) and (thumbnail is None or not (directory / thumbnail).is_file())
    if needs_thumbnail:
        reasons.append("thumbnail")
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
        return dataclasses.replace(record, files=files), hashes, stats

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
    if needs_thumbnail:
        record = _with_thumbnail(directory, record, set(hashes))
    if reasons:
        write_record(path, record)
    return record, hashes, stats


def _with_thumbnail(directory: Path, record: Record, present: set[str]) -> Record:
    """`record` with a thumbnail of its default file made at THUMBNAIL_PATH; unchanged, with a
    warning, if that fails (a thumbnail is a convenience, not worth failing the record)."""
    default = record.default(present)
    if default is None:
        return record
    try:
        write_thumbnail(directory / default, directory / THUMBNAIL_PATH, THUMBNAIL_SIZE)
    except (OSError, Image.DecompressionBombError) as exc:
        logger.warning("%s: no thumbnail: %s", directory / default, exc)
        return record
    return dataclasses.replace(record, thumbnail=THUMBNAIL_PATH)


def file_stat(path: Path) -> Stat:
    """The file's size and mtime (ns), for the hash cache."""
    st = path.stat()
    return st.st_size, st.st_mtime_ns


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


def place(
    config: Config, file: Path, *, name: str | None, nsfw: bool, purity: str | None = None
) -> Placement:
    """Where `file` would become a record: beside it if it is under a root, else in the first
    library root (or the NSFW root with `nsfw`, or a `purity` other than sfw), in a directory
    named `name` or its stem. Raises AddError, also for a non-sfw `purity` under a library
    root (it would show in default queries)."""
    if not file.is_file() or file.suffix.lower() not in IMAGE_SUFFIXES:
        raise AddError(f"{file}: not an image file")
    if name is not None and not NAME_PATTERN.fullmatch(name):
        raise AddError(f"name {name!r} does not match {NAME_PATTERN.pattern}")
    if nsfw and purity == "sfw":
        raise AddError(f"{file}: --nsfw with purity sfw")
    nsfw = nsfw or purity in ("sketchy", "nsfw")
    resolved = file.resolve()
    roots = (*config.library_roots, config.nsfw_root)
    root = next((root for root in roots if resolved.is_relative_to(root.resolve())), None)
    if root is not None:
        if nsfw and root != config.nsfw_root:
            raise AddError(
                f"{file}: under the library root {root}; move it out (or into the NSFW root) "
                "to add it as non-sfw"
            )
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


def add_picture(
    config: Config,
    placement: Placement,
    *,
    name: str | None,
    source: dict[str, object] | None = None,
) -> Entry:
    """Make a record of one file: measure it, move it into the new directory, make its
    thumbnail, write the info file (with `source`, from `hand_source`). Raises OSError or
    Image.DecompressionBombError (before anything moves, if measuring fails)."""
    file = placement.file
    entry = FileEntry(sha256_file(file), *image_size(file), measure_file(file))
    record = Record(uuid.uuid4().hex, name=name, source=source, files={file.name: entry})
    placement.directory.mkdir(parents=True)
    shutil.move(file, placement.directory / file.name)
    record = _with_thumbnail(placement.directory, record, {file.name})
    write_record(placement.directory / INFO_NAMES[0], record)
    nsfw = placement.directory.resolve().is_relative_to(config.nsfw_root)
    stats = {file.name: file_stat(placement.directory / file.name)}
    return Entry(
        placement.directory, placement.root, nsfw, record, (file.name,), file.name, name, stats
    )


# Where a hand-added picture came from (docs/design.md, "Provenance"): `amo add` options and
# --from-json keys, in the order they are written to `source`.
PROVENANCE_KEYS = (
    "site",
    "url",
    "image_url",
    "title",
    "author",
    "license",
    "purity",
    "category",
    "tags",
    "uploaded",
)


def hand_source(fields: Mapping[str, object]) -> dict[str, object] | None:
    """The `source` of a hand-added picture from PROVENANCE_KEYS fields (None and empty values
    left out), or None if none is given. `site` defaults to the host of `url` (or of
    `image_url`). Raises AddError naming a field of the wrong type."""
    source: dict[str, object] = {}
    for key in PROVENANCE_KEYS:
        value = fields.get(key)
        if value is None or value == "" or value == []:
            continue
        if key == "tags":
            if not (isinstance(value, list) and all(isinstance(t, str) and t for t in value)):
                raise AddError("tags: not a list of words")
        elif key == "uploaded":
            value = _timestamp(value)
        elif not isinstance(value, str):
            raise AddError(f"{key}: not a string")
        elif key == "purity" and value not in PURITIES:
            raise AddError(f"purity: {value!r} is not one of {', '.join(PURITIES)}")
        elif key in ("url", "image_url") and urlsplit(value).scheme not in ("http", "https"):
            raise AddError(f"{key}: {value!r} is not an http(s) URL")
        source[key] = value
    if not source:
        return None
    if "site" not in source:
        url = source.get("url") or source.get("image_url")
        if isinstance(url, str):
            host = urlsplit(url).hostname or ""
            source["site"] = host.removeprefix("www.")
    return {key: source[key] for key in PROVENANCE_KEYS if key in source}


@dataclass(frozen=True)
class Addition:
    """One picture for `amo add`: the file, the record's name, and its provenance fields."""

    file: Path
    name: str | None = None
    nsfw: bool = False
    fields: Mapping[str, object] = field(default_factory=dict)


def additions_from_json(path: Path) -> list[Addition]:
    """The pictures listed in a JSON file for `amo add --from-json`: a list of objects, each
    with `file` (relative paths are relative to the JSON file), optional `name` and `nsfw`,
    and any PROVENANCE_KEYS. Raises AddError naming the entry and key at fault; OSError if the
    file cannot be read."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise AddError(f"{path}: not JSON: {exc}") from exc
    if not isinstance(data, list):
        raise AddError(f"{path}: not a list of pictures")
    additions = []
    allowed = {"file", "name", "nsfw", *PROVENANCE_KEYS}
    for number, item in enumerate(data, start=1):
        where = f"{path}: picture {number}"
        if not isinstance(item, dict):
            raise AddError(f"{where}: not an object")
        unknown = sorted(set(item) - allowed)
        if unknown:
            raise AddError(f"{where}: unknown keys {', '.join(unknown)}")
        file, name, nsfw = item.get("file"), item.get("name"), item.get("nsfw", False)
        if not isinstance(file, str) or not file:
            raise AddError(f"{where}: no file")
        if name is not None and not isinstance(name, str):
            raise AddError(f"{where}: name is not a string")
        if not isinstance(nsfw, bool):
            raise AddError(f"{where}: nsfw is not true or false")
        fields = {key: item[key] for key in PROVENANCE_KEYS if key in item}
        try:
            hand_source(fields)
        except AddError as exc:
            raise AddError(f"{where}: {exc}") from None
        additions.append(Addition(path.parent / Path(file).expanduser(), name, nsfw, fields))
    return additions


def _timestamp(value: object) -> date | datetime:
    if isinstance(value, (date, datetime)):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value)
        except ValueError:
            pass
    raise AddError(f"uploaded: {value!r} is not an ISO 8601 date or time")


class CropError(Exception):
    """A crop cannot be made; the message says why."""


class CropCancelled(CropError):
    """The crop was not chosen (Esc in `amo crop --interactive`); nothing was written."""


Box = tuple[int, int, int, int]
# Shows the image, lets the user place a box, and returns it, or None to write nothing: called
# with the original's path, its size (as displayed) and the box to start from.
Choose = Callable[[Path, int, int, Box], "Box | None"]


def crop_box(
    width: int,
    height: int,
    ratio: float,
    at: float | tuple[float, float] = 0.5,
    scale: float = 1.0,
) -> Box:
    """A box of `ratio` (width / height) in a `width` x `height` image, as (x, y, width,
    height): the largest such box times `scale` (0 < scale <= 1, never under one pixel), placed
    at `at` along each axis, from 0 (left or top) through 0.5 (centred) to 1 (right or bottom).
    One `at` places both axes; at scale 1 only the axis the box is cut on has room to move."""
    at_x, at_y = (at, at) if isinstance(at, (int, float)) else at
    if width / height > ratio:
        full_width, full_height = min(width, height * ratio), height
    else:
        full_width, full_height = width, min(height, width / ratio)
    crop_width = min(width, max(1, round(full_width * scale)))
    crop_height = min(height, max(1, round(full_height * scale)))
    return (
        round((width - crop_width) * at_x),
        round((height - crop_height) * at_y),
        crop_width,
        crop_height,
    )


def crop_picture(
    config: Config,
    directory: Path,
    root: Path,
    ratio: float,
    label: str,
    *,
    at: float = 0.5,
    force: bool = False,
    dry_run: bool = False,
    choose: Choose | None = None,
) -> tuple[Entry, str]:
    """Crop a record's original to `ratio`, as `<stem>-<label><suffix>` beside it, and record
    the crop (`derived_from`, `crop`, measured). Returns the record as it now is, and the new
    file's name. Refuses (CropError) a record that needs `amo index`, one whose original is of
    that ratio already, and, without `force`, one with a file of that ratio; `force` replaces
    an earlier crop of the same name, never a file that is not a crop. `choose`, if given,
    places the box after those checks (starting from the one `at` gives); it returning None
    raises CropCancelled."""
    path = info_path(directory)
    if path is None:
        raise CropError(f"{directory}: not a record")
    record = read_record(path)
    present = present_files(directory, record)
    if needs_healing(directory, record, present):
        raise CropError(f"{directory}: needs healing; run `amo index` first")
    source = original_file(record, present)
    if source is None:
        raise CropError(f"{directory}: no original file to crop")
    entry = record.files[source]
    assert entry.width is not None and entry.height is not None
    if has_aspect(entry.width, entry.height, ratio):
        raise CropError(f"{directory / source}: already {label.replace('x', ':')}")
    name = f"{Path(source).stem}-{label}{Path(source).suffix}"
    existing = record.files.get(name)
    if existing is not None and existing.derived_from is None:
        raise CropError(f"{directory / name}: exists and is not a crop")
    matching = sorted(
        other
        for other in present
        if other != name and has_aspect(*_size(record.files[other]), ratio)
    )
    if (matching or existing is not None) and not force:
        found = matching[0] if matching else name
        raise CropError(
            f"{directory / found} is {label.replace('x', ':')} already; --force crops anyway"
        )
    box = crop_box(entry.width, entry.height, ratio, at)
    if choose is not None:
        chosen = choose(directory / source, entry.width, entry.height, box)
        if chosen is None:
            raise CropCancelled(f"{directory / source}: cancelled; nothing written")
        box = chosen
    if dry_run:
        return record_entry(config, directory, root, record, present), name
    target = directory / name
    write_crop(directory / source, target, box)
    try:
        crop = FileEntry(
            sha256_file(target),
            *image_size(target),
            measure_file(target),
            derived_from=source,
            crop=box,
        )
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    record = dataclasses.replace(record, files={**record.files, name: crop})
    write_record(path, record)
    return record_entry(config, directory, root, record, present | {name}), name


def add_derived(
    config: Config,
    directory: Path,
    root: Path,
    file: Path,
    *,
    name: str | None = None,
    source: str | None = None,
    dry_run: bool = False,
) -> tuple[Entry, str]:
    """Register `file`, made by hand from one of a record's files (an edit in any tool), as a
    derived file of the record: measure it, move it into the record's directory as `name`
    (default: its own name; a file already in the directory stays there, renamed if `name`
    says so), and list it with `derived_from` (`source`, default the record's original as
    `original_file` picks it) and no `crop`, which marks it hand-made: it cannot be made
    again. Returns the record as it now is (under `dry_run`, as it is: nothing is written or
    moved) and the file's name in it. Raises AddError for a file that is not an image, a name
    the record lists or that exists, a `source` it does not list or lacks, content one of its
    files has, and a record that needs `amo index` first."""
    path = info_path(directory)
    if path is None:
        raise AddError(f"{directory}: not a record")
    record = read_record(path)
    if not file.is_file() or file.suffix.lower() not in IMAGE_SUFFIXES:
        raise AddError(f"{file}: not an image file")
    inside = file.resolve().parent == directory.resolve()
    name = name or file.name
    if Path(name).name != name or Path(name).suffix.lower() not in IMAGE_SUFFIXES:
        raise AddError(f"name {name!r}: not an image file name")
    if name in record.files:
        raise AddError(f"{directory}: lists {name} already")
    target = directory / name
    if target.exists() and not (inside and name == file.name):
        raise AddError(f"{target} exists")
    present = present_files(directory, record)
    if needs_healing(directory, record, present, ignore=file.name if inside else None):
        raise AddError(f"{directory}: needs healing; run `amo index` first")
    source = source or original_file(record, present)
    if source is None:
        raise AddError(f"{directory}: no original file to derive from")
    if source not in present:
        raise AddError(f"{directory}: no file {source} to derive from")
    sha256 = sha256_file(file)
    same = [other for other in sorted(present) if record.files[other].sha256 == sha256]
    if same:
        raise AddError(f"{file}: same content as {directory / same[0]}")
    entry = FileEntry(sha256, *image_size(file), measure_file(file), derived_from=source)
    if dry_run:
        return record_entry(config, directory, root, record, present), name
    moved = file.resolve() != target.resolve()
    if moved:
        shutil.move(file, target)
    try:
        record = dataclasses.replace(record, files={**record.files, name: entry})
        write_record(path, record)
    except BaseException:
        if moved:
            shutil.move(target, file)
        raise
    return record_entry(config, directory, root, record, present | {name}), name


def _size(entry: FileEntry) -> tuple[int, int]:
    assert entry.width is not None and entry.height is not None
    return entry.width, entry.height


class NamingError(Exception):
    """A record cannot be named; the message says why. Nothing was changed."""


def name_record(
    config: Config,
    directory: Path,
    root: Path,
    name: str,
    taken: set[str],
    *,
    rename_directory: bool = True,
    dry_run: bool = False,
) -> Entry:
    """Give the record in `directory` the name `name`, a first name or a new one, and unless
    `rename_directory` is false, rename its directory to the name where it is (foo/bar/old
    becomes foo/bar/<name>). Returns the record as it now is (under `dry_run`, as it is:
    nothing is written). Raises NamingError for an invalid name, the record's own name, one in
    `taken`, a record that needs `amo index` first, and an existing directory for the name. A
    failed rename puts info.yaml back as it was."""
    path = info_path(directory)
    if path is None:
        raise NamingError(f"{directory}: not a record")
    record = read_record(path)
    if not NAME_PATTERN.fullmatch(name):
        raise NamingError(f"name {name!r} does not match {NAME_PATTERN.pattern}")
    if name == record.name:
        raise NamingError(f"{directory}: named {name} already")
    if name in taken:
        raise NamingError(f"{directory}: name {name!r} is taken")
    present = present_files(directory, record)
    if not present or needs_healing(directory, record, present):
        raise NamingError(f"{directory}: needs healing; run `amo index` first")
    target = directory.parent / name if rename_directory else directory
    if target != directory and target.exists():
        raise NamingError(f"{directory}: {target} already exists")
    if dry_run:
        return record_entry(config, directory, root, record, present)
    named = dataclasses.replace(record, name=name)
    write_record(path, named)
    if target != directory:
        try:
            directory.rename(target)
        except BaseException:
            write_record(path, record)
            raise
    return record_entry(config, target, root, named, present)


def present_files(directory: Path, record: Record) -> set[str]:
    """The files `record` lists that are in `directory`."""
    return {name for name in record.files if (directory / name).is_file()}


def original_file(record: Record, present: set[str]) -> str | None:
    """The original a derived file comes from by default: the default file if it is an
    original, else the largest original; None if no present file is one."""
    originals = {name for name in present if record.files[name].derived_from is None}
    default = record.default(present)
    if default in originals:
        return default
    return record.default(originals) if originals else None


def needs_healing(
    directory: Path, record: Record, present: set[str], ignore: str | None = None
) -> bool:
    """Whether `amo index` has work to do on the record first: an image it does not list
    (other than `ignore`), or a present file not yet hashed and measured."""
    unlisted = [
        file
        for file in directory.iterdir()
        if file.suffix.lower() in IMAGE_SUFFIXES
        and file.name not in record.files
        and file.name != ignore
    ]
    return bool(unlisted) or any(not record.files[name].complete for name in present)


def record_entry(
    config: Config, directory: Path, root: Path, record: Record, present: set[str]
) -> Entry:
    """`record`, in `directory` under `root`, as the index takes it."""
    default = record.default(present)
    assert default is not None
    nsfw = directory.resolve().is_relative_to(config.nsfw_root)
    stats = {name: file_stat(directory / name) for name in present}
    return Entry(directory, root, nsfw, record, tuple(sorted(present)), default, record.name, stats)
