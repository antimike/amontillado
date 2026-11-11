"""What a command wrote under the library roots, for the `on_change` hook.

docs/design.md, "git-annex libraries: decisions" 5. The library's writers report here as they
write: `info_written` (an info file: its text as amo read it, and as written), `file_written`
(an image or thumbnail made or replaced) and `moved` (a file or record directory moved or
renamed). Nothing is recorded unless the CLI started a `recording()`; `payloads` then gives
one payload per root that was written to.

A payload is a JSON object: `version` (1), `command` (`fetch`, `add-derived`, ...), `root`
(absolute), and `changes`, a list in which each item has a `type` and paths relative to the
root:

- `{"type": "rename", "from": ..., "to": ...}`: a file or directory amo moved within the root
  (`amo name`, or `amo add` of a file already in the root; not out of a record's `.amo/`, as
  `amo edit` does); listed first;
- `{"type": "info", "path": ..., "before": TEXT|null, "after": TEXT}`: an info file amo wrote,
  `before` null for a new one; a path inside a renamed directory is its new path;
- `{"type": "file", "path": ...}`: an image or thumbnail amo made or replaced (moved in from
  outside the root, too).

No command deletes files under a root, so there is no delete change.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

PAYLOAD_VERSION = 1


@dataclass
class _Info:
    before: str | None
    after: str


@dataclass
class Recorder:
    """The changes of one run, by absolute path (the file itself never resolved: an annexed
    file is a symlink)."""

    infos: dict[Path, _Info] = field(default_factory=dict)
    files: dict[Path, None] = field(default_factory=dict)
    renames: list[tuple[Path, Path]] = field(default_factory=list)

    def payloads(self, command: str, roots: Sequence[Path]) -> list[tuple[Path, dict]]:
        """One payload per root (in `roots` order) with a change; paths outside every root are
        left out, and an info file written back as it was read is no change."""
        found = []
        for root in roots:
            changes: list[dict[str, object]] = []
            for source, target in self.renames:
                # A move out of amo's own .amo/ (an edit's working directory) is a new file.
                if _under(target, root) and _under(source, root) and not _internal(source, root):
                    rename = {
                        "type": "rename",
                        "from": _rel(source, root),
                        "to": _rel(target, root),
                    }
                    changes.append(rename)
            for path, info in self.infos.items():
                if _under(path, root) and info.before != info.after:
                    changes.append(
                        {
                            "type": "info",
                            "path": _rel(path, root),
                            "before": info.before,
                            "after": info.after,
                        }
                    )
            changes += [
                {"type": "file", "path": _rel(p, root)} for p in self.files if _under(p, root)
            ]
            if changes:
                payload = {
                    "version": PAYLOAD_VERSION,
                    "command": command,
                    "root": str(root),
                    "changes": changes,
                }
                found.append((root, payload))
        return found


_recorder: ContextVar[Recorder | None] = ContextVar("amontillado_changes", default=None)


@contextmanager
def recording() -> Iterator[Recorder]:
    """Record the writes made inside the block."""
    recorder = Recorder()
    token = _recorder.set(recorder)
    try:
        yield recorder
    finally:
        _recorder.reset(token)


def info_written(path: Path, before: str | None, after: str) -> None:
    """An info file was written: `before` as amo read it (None: a new file), `after` as
    written. Several writes of one file in a run keep the first `before` and the last
    `after`."""
    recorder = _recorder.get()
    if recorder is None:
        return
    key = _absolute(path)
    earlier = recorder.infos.get(key)
    recorder.infos[key] = _Info(earlier.before if earlier else before, after)


def file_written(path: Path) -> None:
    """An image or thumbnail was made or replaced."""
    recorder = _recorder.get()
    if recorder is not None:
        recorder.files[_absolute(path)] = None


def moved(source: Path, target: Path) -> None:
    """A file or directory was moved: what was recorded under `source` is now under `target`.
    A source outside the root makes it a new file there (`payloads`)."""
    recorder = _recorder.get()
    if recorder is None:
        return
    source, target = _absolute(source), _absolute(target)
    recorder.infos = {_move(p, source, target): info for p, info in recorder.infos.items()}
    recorder.files = {_move(p, source, target): None for p in recorder.files}
    recorder.renames.append((source, target))
    if not target.is_dir():
        recorder.files[target] = None  # its content, wherever it came from


def _move(path: Path, source: Path, target: Path) -> Path:
    if path == source or path.is_relative_to(source):
        return target / path.relative_to(source)
    return path


def _absolute(path: Path) -> Path:
    """`path` absolute, its directory resolved but not the file itself."""
    path = path.absolute()
    return path.parent.resolve() / path.name


def _under(path: Path, root: Path) -> bool:
    return path.is_relative_to(root)


def _internal(path: Path, root: Path) -> bool:
    return ".amo" in path.relative_to(root).parts


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()
