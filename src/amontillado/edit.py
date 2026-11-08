"""amo edit: run an editor on a copy of a record's file, then add what it saved as a hand-made
derived file (`add_derived`; docs/design.md, "Editing").

The copy lives in a working directory inside the record, `.amo/edit-*`: `amo index` never looks
there (a record's files are directly inside it), an NSFW picture stays under its root, and the
result moves into the record without crossing a file system. The tool's command line runs under
`sh -c` in that directory, with INPUT (the copy), OUTPUT (a path for the result, not yet there)
and WORKDIR added to the environment, and its standard output sent to standard error (amo's own
is the new file's path). The result is OUTPUT if the tool wrote it, else the one image in the
working directory, or below it, that is new or changed; hidden files and directories, and files
in an editor's own format (.xcf, .kra), are not images to it.

The working directory is removed once the result is added, or when the tool saved nothing;
otherwise it is kept and named in the error, so that `amo add-derived` can take a result by
hand.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from amontillado.config import Config
from amontillado.library import (
    AddError,
    Entry,
    add_derived,
    check_new_name,
    derived_source,
    needs_healing,
    present_files,
)
from amontillado.record import IMAGE_SUFFIXES, info_path, read_record, sha256_file

# Seconds (*initial*): a tool that returns sooner having saved nothing probably handed the file
# to a running instance instead of blocking.
QUICK_EXIT = 2.0
WORK_PREFIX = "edit-"
# What the shell reports for a command it cannot find.
_NOT_FOUND = 127
_SAME_FORMAT = {".jpeg": ".jpg"}
_STDERR = 2


class EditError(Exception):
    """amo edit failed. `workdir`, when set, is kept: it holds what the tool saved."""

    def __init__(self, message: str, workdir: Path | None = None) -> None:
        super().__init__(message)
        self.workdir = workdir


@dataclass(frozen=True)
class Plan:
    """An edit that passed the checks that can be made before the tool runs."""

    directory: Path
    # The record's file the copy is made of.
    source: str
    # The new file's name in the record; None: <source stem>-edit<result suffix>.
    name: str | None


def plan_edit(directory: Path, *, source: str | None = None, name: str | None = None) -> Plan:
    """Check that an edit of the record in `directory` could be added, as far as that is known
    before the tool runs: a record that needs `amo index` first, a `source` it does not list or
    lacks, a `name` it lists or that exists. Raises AddError."""
    path = info_path(directory)
    if path is None:
        raise AddError(f"{directory}: not a record")
    record = read_record(path)
    present = present_files(directory, record)
    if needs_healing(directory, record, present):
        raise AddError(f"{directory}: needs healing; run `amo index` first")
    source = derived_source(directory, record, present, source)
    if name is not None:
        check_new_name(directory, record, name)
    return Plan(directory, source, name)


def run_edit(config: Config, plan: Plan, root: Path, command: str) -> tuple[Entry, str]:
    """Copy the plan's source into a working directory, run `command` there under `sh -c`
    (module docstring), and add its result to the record under `root`. Returns the record as
    it now is and the new file's name. Raises EditError, with the working directory kept when
    it holds anything the tool saved."""
    directory = plan.directory
    work_root = directory / ".amo"
    work_root.mkdir(exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix=WORK_PREFIX, dir=work_root))
    copy = workdir / plan.source
    try:
        shutil.copy2(directory / plan.source, copy)
    except OSError as exc:
        _discard(workdir)
        raise EditError(f"cannot copy {directory / plan.source}: {exc}") from exc
    before = sha256_file(copy)
    source = Path(plan.source)
    output = workdir / f"{source.stem}-edit{source.suffix}"
    env = {**os.environ, "INPUT": str(copy), "OUTPUT": str(output), "WORKDIR": str(workdir)}
    started = time.monotonic()
    try:
        status = subprocess.run(
            # File descriptor 2, not sys.stderr: a replaced sys.stderr may have no descriptor.
            ["sh", "-c", command],
            cwd=workdir,
            env=env,
            stdout=_STDERR,
            check=False,
        ).returncode
    except KeyboardInterrupt:
        raise EditError("interrupted", workdir) from None
    except OSError as exc:
        _discard(workdir)
        raise EditError(f"cannot run sh: {exc}") from exc
    elapsed = time.monotonic() - started
    results = _results(workdir, copy, before, output)
    if status != 0:
        reason = " (command not found)" if status == _NOT_FOUND else ""
        raise EditError(
            f"the tool exited with status {status}{reason}", _kept(workdir, copy, before)
        )
    if not results:
        message = "the tool saved no image"
        if elapsed < QUICK_EXIT:
            message += (
                f"; it returned after {elapsed:.1f} s: if it hands the file to a running "
                "instance, make it start its own (gimp -n)"
            )
        raise EditError(message, _kept(workdir, copy, before))
    if len(results) > 1:
        names = ", ".join(str(result.relative_to(workdir)) for result in results)
        raise EditError(
            f"the tool saved several images ({names}); add one with amo add-derived", workdir
        )
    result = results[0]
    try:
        name = plan.name or _default_name(directory, source.stem, result.suffix)
        if _format(Path(name).suffix) != _format(result.suffix):
            raise AddError(f"name {name}: the result is a {result.suffix} file")
        entry, name = add_derived(config, directory, root, result, name=name, source=plan.source)
    except (AddError, OSError) as exc:
        raise EditError(str(exc), workdir) from exc
    _discard(workdir)
    return entry, name


def _results(workdir: Path, copy: Path, before: str, output: Path) -> list[Path]:
    """What the tool saved: OUTPUT if it is there, else every image in `workdir` (or below it,
    hidden paths left out) other than the copy unchanged."""
    if output.is_file():
        return [output]
    results = []
    for path in sorted(workdir.rglob("*")):
        parts = path.relative_to(workdir).parts
        if (
            path.is_file()
            and path.suffix.lower() in IMAGE_SUFFIXES
            and not any(part.startswith(".") for part in parts)
            and not (path == copy and sha256_file(path) == before)
        ):
            results.append(path)
    return results


def _kept(workdir: Path, copy: Path, before: str) -> Path | None:
    """`workdir` if the tool left anything in it (an .xcf, a half-written image); else it is
    removed and None returned."""
    others = [path for path in workdir.rglob("*") if path != copy]
    if others or not copy.is_file() or sha256_file(copy) != before:
        return workdir
    _discard(workdir)
    return None


def _discard(workdir: Path) -> None:
    shutil.rmtree(workdir)
    # .amo may hold nothing else (a record without a thumbnail).
    try:
        workdir.parent.rmdir()
    except OSError:
        pass


def _default_name(directory: Path, stem: str, suffix: str) -> str:
    """<stem>-edit<suffix>, or -edit-2, -edit-3 ... when the record lists or has that name."""
    record = read_record(info_path(directory))  # type: ignore[arg-type]
    number = 1
    while True:
        name = f"{stem}-edit{'' if number == 1 else f'-{number}'}{suffix.lower()}"
        if name not in record.files and not (directory / name).exists():
            return name
        number += 1


def _format(suffix: str) -> str:
    suffix = suffix.lower()
    return _SAME_FORMAT.get(suffix, suffix)
