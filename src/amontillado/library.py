"""The library: the images under the roots, and healing their sidecars.

docs/design.md, "Healing": an image without a sidecar gets one; a sidecar that does not parse,
lacks fields, or has older metrics is rewritten, keeping its `source` block where that still
parses; a changed content hash means new content, so the image is measured again. A sidecar that
is not valid YAML is kept as `<name>.yaml.bad` before it is replaced. Sidecars without an image,
and images that would share one sidecar, are reported and left alone.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from logging import getLogger
from pathlib import Path

from PIL import Image

from amontillado.config import Config
from amontillado.metrics import image_size, measure_file
from amontillado.sidecar import (
    Sidecar,
    SidecarError,
    content_id,
    load_raw,
    parse,
    sidecar_path,
    write_sidecar,
)

logger = getLogger(__name__)

IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})
PURITIES = ("sfw", "sketchy", "nsfw")


@dataclass(frozen=True)
class Entry:
    """An image with a valid sidecar."""

    path: Path
    root: Path
    nsfw_root: bool
    sidecar: Sidecar

    @property
    def purity(self) -> str:
        """The source's purity; without one, what the image's root implies."""
        source = self.sidecar.source or {}
        purity = source.get("purity")
        if purity in PURITIES:
            return purity
        return "nsfw" if self.nsfw_root else "sfw"


@dataclass
class Report:
    """What a pass over the library found, and (unless checking) did."""

    entries: list[Entry] = field(default_factory=list)
    healed: list[tuple[Path, str]] = field(default_factory=list)
    orphans: list[Path] = field(default_factory=list)
    conflicts: list[list[Path]] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.healed or self.orphans or self.conflicts or self.failed)


def heal_library(config: Config, *, check: bool = False) -> Report:
    """Heal every sidecar under the library roots and the NSFW root.

    With `check`, nothing is measured or written: `healed` lists what would be healed.
    """
    report = Report()
    images, sidecars = _scan(config)

    by_sidecar: dict[Path, list[tuple[Path, Path]]] = defaultdict(list)
    for image, root in images:
        by_sidecar[sidecar_path(image)].append((image, root))
    report.orphans = sorted(set(sidecars) - set(by_sidecar))
    for path in report.orphans:
        logger.warning("%s: sidecar without an image", path)

    for sidecar, group in sorted(by_sidecar.items()):
        if len(group) > 1:
            paths = [image for image, _ in group]
            report.conflicts.append(paths)
            logger.error(
                "%s would be the sidecar of %d images; rename all but one", sidecar, len(paths)
            )
            continue
        image, root = group[0]
        try:
            current, reason = _heal_image(image, check=check)
        except (OSError, Image.DecompressionBombError) as exc:
            report.failed.append((image, str(exc)))
            logger.error("%s: %s", image, exc)
            continue
        if reason is not None:
            report.healed.append((sidecar, reason))
            logger.info("%s: %s%s", sidecar, "would heal: " if check else "healed: ", reason)
        if current is not None:
            entry = Entry(image, root, image.resolve().is_relative_to(config.nsfw_root), current)
            if not entry.nsfw_root and entry.purity != "sfw":
                logger.warning("%s: %s image outside the NSFW root", image, entry.purity)
            report.entries.append(entry)
    return report


def _scan(config: Config) -> tuple[list[tuple[Path, Path]], list[Path]]:
    """Images (with the root they were found under) and YAML files under every root.

    Overlapping roots would find a file twice; it is kept under the first root.
    """
    images: list[tuple[Path, Path]] = []
    sidecars: list[Path] = []
    seen: set[Path] = set()
    for root in (*config.library_roots, config.nsfw_root):
        if not root.is_dir():
            logger.debug("%s: no such directory", root)
            continue
        # rglob does not follow directory symlinks, so a symlink cannot pull in another tree.
        for path in sorted(root.rglob("*")):
            suffix = path.suffix.lower()
            if suffix not in IMAGE_SUFFIXES and suffix != ".yaml":
                continue
            if not path.is_file() or path.resolve() in seen:
                continue
            seen.add(path.resolve())
            if suffix == ".yaml":
                sidecars.append(path)
            else:
                images.append((path, root))
    return images, sidecars


def _heal_image(image: Path, *, check: bool) -> tuple[Sidecar | None, str | None]:
    """The image's valid sidecar (None when checking one that needs measuring) and why it
    was or would be healed (None if it was fine)."""
    path = sidecar_path(image)
    image_id = content_id(image)
    source = fetched = None
    unparseable = False
    try:
        raw = load_raw(path)
    except FileNotFoundError:
        reason = "no sidecar"
    except SidecarError as exc:
        reason, unparseable = str(exc), True
    else:
        if isinstance(raw.get("source"), dict):
            source = raw["source"]
        if isinstance(raw.get("fetched"), datetime):
            fetched = raw["fetched"]
        try:
            current = parse(raw)
        except SidecarError as exc:
            reason = str(exc)
        else:
            if current.id != image_id:
                reason = "content changed"
            elif current.file != image.name:
                # A rename: the measurements still hold.
                renamed = dataclasses.replace(current, file=image.name)
                if not check:
                    write_sidecar(path, renamed)
                return renamed, f"file was {current.file!r}"
            else:
                return current, None
    if check:
        return None, reason

    width, height = image_size(image)
    healed = Sidecar(image_id, image.name, width, height, source, fetched, measure_file(image))
    if unparseable:
        path.replace(path.with_suffix(".yaml.bad"))
    write_sidecar(path, healed)
    return healed, reason
