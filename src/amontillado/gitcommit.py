"""`amo hook git-commit`: the reference on_change hook, committing amo's changes to git.

docs/design.md, "git-annex libraries: decisions" 5. Set `on_change: amo hook git-commit` to
use it. For each run it gets one root's payload (`amontillado.changes`) and, if the root is in
a git work tree, makes one commit holding amo's changes and nothing else:

- each info file is merged with `amo info merge` (BASE: as amo read it, OURS: the committed
  version, THEIRS: as amo wrote it) and the result staged as a blob, so an edit of yours that
  is not committed stays out of the commit (and stays in the working tree). A conflict leaves
  that record out of the commit, with a warning naming it; the rest is committed;
- a rename moves the committed entries under the old path to the new one;
- new files (images, thumbnails) are added as they are (`git add`), unless git ignores them.

The commit is built in a temporary index, so whatever you have staged is neither committed nor
lost, and it is made with `git commit`, so your hooks and signing apply. Afterwards the real
index takes the committed version of each path you had not staged anything for.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from logging import getLogger
from pathlib import Path, PurePosixPath

from amontillado import infomerge
from amontillado.changes import PAYLOAD_VERSION

logger = getLogger(__name__)

_SUMMARY_RECORDS = 3
_EMPTY = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # git's empty tree (SHA-1 repositories)


class HookError(Exception):
    """The hook cannot do its work; the message says why."""


@dataclass
class _Git:
    """git run at a repository's top level, optionally on another index file."""

    top: Path
    index: Path | None = None

    def run(
        self, *args: str, input: str | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        if self.index is not None:
            env["GIT_INDEX_FILE"] = str(self.index)
        result = subprocess.run(
            ["git", "-C", str(self.top), *args],
            input=input,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if check and result.returncode != 0:
            raise HookError(f"git {args[0]}: {result.stderr.strip() or result.returncode}")
        return result

    def entries(self, tree: str | None, paths: Sequence[str]) -> dict[str, tuple[str, str]]:
        """{path: (mode, object)} under `paths` in `tree` (a commit), or in the index if None."""
        if not paths:
            return {}
        if tree is None:
            out = self.run("ls-files", "-s", "-z", "--full-name", "--", *paths).stdout
            fields = [line.split("\t", 1) for line in out.split("\0") if line]
            return {path: (meta.split()[0], meta.split()[1]) for meta, path in fields}
        out = self.run("ls-tree", "-r", "-z", "--full-name", tree, "--", *paths).stdout
        fields = [line.split("\t", 1) for line in out.split("\0") if line]
        return {path: (meta.split()[0], meta.split()[2]) for meta, path in fields}


@dataclass
class _Plan:
    """What one payload asks of git, paths relative to the repository's top level."""

    command: str
    renames: list[tuple[str, str]] = field(default_factory=list)
    infos: list[tuple[str, str | None, str]] = field(default_factory=list)  # path, before, after
    files: list[str] = field(default_factory=list)


def git_commit(payload: Mapping[str, object]) -> None:
    """Commit one root's changes (a payload) to the git repository the root is in. Raises
    HookError when git is missing or fails; a root outside git is a warning."""
    if payload.get("version") != PAYLOAD_VERSION:
        raise HookError(f"payload version {payload.get('version')!r}; this amo knows 1")
    if shutil.which("git") is None:
        raise HookError("git is not installed; on_change: amo hook git-commit needs it")
    root = Path(str(payload["root"]))
    found = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel", "--show-prefix"],
        capture_output=True,
        text=True,
        check=False,
    )
    if found.returncode != 0:
        logger.warning("%s: not in a git repository; nothing committed", root)
        return
    top, prefix = [*found.stdout.splitlines(), ""][:2]
    git = _Git(Path(top))
    plan = _plan(payload, prefix)
    head = git.run("rev-parse", "--verify", "-q", "HEAD^{commit}", check=False).stdout.strip()

    with tempfile.TemporaryDirectory(prefix="amo-git-commit-") as temporary:
        staging = _Git(git.top, Path(temporary) / "index")
        staging.run("read-tree", *(["HEAD"] if head else ["--empty"]))
        merged, conflicted = _merge_infos(git, head, plan)
        skip = _skipper(conflicted)
        for source, target in plan.renames:
            if skip(target):
                continue
            for path, (mode, sha) in staging.entries(None, [source]).items():
                moved = target + path[len(source) :]
                staging.run("update-index", "--add", "--cacheinfo", f"{mode},{sha},{moved}")
            staging.run("rm", "--cached", "-r", "-q", "--ignore-unmatch", "--", source)
        for path, text in merged.items():
            sha = git.run("hash-object", "-w", "--stdin", input=text).stdout.strip()
            mode = staging.entries(None, [path]).get(path, ("100644", ""))[0]
            staging.run("update-index", "--add", "--cacheinfo", f"{mode},{sha},{path}")
        files = [path for path in plan.files if not skip(path)]
        ignored = _ignored(git, files)
        if files_to_add := [path for path in files if path not in ignored]:
            staging.run("add", "--", *files_to_add)
        tree = staging.run("write-tree").stdout.strip()
        unchanged = git.run("rev-parse", f"{head}^{{tree}}").stdout.strip() if head else _EMPTY
        if tree == unchanged:
            logger.info("%s: nothing to commit", root)
            return
        staging.run("commit", "-q", "-m", _message(plan, merged, files_to_add))
    touched = [p for pair in plan.renames for p in pair] + list(merged) + files_to_add
    _sync_index(git, head or None, touched)
    logger.info("%s: committed amo %s", root, plan.command)


def _plan(payload: Mapping[str, object], prefix: str) -> _Plan:
    def full(path: object) -> str:
        return (PurePosixPath(prefix) / str(path)).as_posix() if prefix else str(path)

    plan = _Plan(str(payload.get("command", "")))
    changes = payload.get("changes")
    if not isinstance(changes, list):
        raise HookError("payload: no list of changes")
    for change in changes:
        kind = change.get("type")
        if kind == "rename":
            plan.renames.append((full(change["from"]), full(change["to"])))
        elif kind == "info":
            plan.infos.append((full(change["path"]), change.get("before"), change["after"]))
        elif kind == "file":
            plan.files.append(full(change["path"]))
        else:
            raise HookError(f"payload: unknown change type {kind!r}")
    return plan


def _merge_infos(git: _Git, head: str, plan: _Plan) -> tuple[dict[str, str], set[str]]:
    """Each info file's text to commit, and the record directories left out on a conflict."""
    merged: dict[str, str] = {}
    conflicted: set[str] = set()
    for path, before, after in plan.infos:
        committed = _committed(git, head, _before_renames(path, plan.renames))
        if committed is None:
            merged[path] = after  # new to git: nothing to merge with
            continue
        try:
            result = infomerge.merge(before or "", committed, after)
        except infomerge.InfoError as exc:
            result = infomerge.Merge(conflicts=[str(exc)])
        if result.text is None:
            record = PurePosixPath(path).parent.as_posix()
            conflicted.add(record)
            logger.warning(
                "%s: not committed: amo's change conflicts with the committed version (%s); "
                "commit it by hand",
                record,
                "; ".join(result.conflicts),
            )
            continue
        merged[path] = result.text
    return merged, conflicted


def _before_renames(path: str, renames: Sequence[tuple[str, str]]) -> str:
    """Where `path` was before this run's renames (the committed version's path)."""
    for source, target in reversed(renames):
        if path == target or path.startswith(target + "/"):
            path = source + path[len(target) :]
    return path


def _committed(git: _Git, head: str, path: str) -> str | None:
    if not head:
        return None
    shown = git.run("cat-file", "blob", f"{head}:{path}", check=False)
    return shown.stdout if shown.returncode == 0 else None


def _skipper(conflicted: set[str]) -> Callable[[str], bool]:
    def skip(path: str) -> bool:
        return any(path == record or path.startswith(record + "/") for record in conflicted)

    return skip


def _ignored(git: _Git, paths: Sequence[str]) -> set[str]:
    if not paths:
        return set()
    # A tracked file is never reported ignored: git add takes it.
    out = git.run("check-ignore", "--stdin", input="\n".join(paths), check=False)
    return set(out.stdout.splitlines())


def _message(plan: _Plan, merged: Mapping[str, str], files: Sequence[str]) -> str:
    """`amo <command>: <records>` (their directories' names), then every path."""
    records: dict[str, None] = {}
    for path in [*merged, *files]:
        parts = PurePosixPath(path).parts
        record = parts[: parts.index(".amo")] if ".amo" in parts else parts[:-1]
        records[record[-1] if record else path] = None
    names = list(records)
    summary = ", ".join(names[:_SUMMARY_RECORDS])
    if len(names) > _SUMMARY_RECORDS:
        summary += f" and {len(names) - _SUMMARY_RECORDS} more"
    lines = [f"rename {source} -> {target}" for source, target in plan.renames]
    lines += [f"update {path}" for path in merged]
    lines += [f"add {path}" for path in files]
    return f"amo {plan.command}: {summary}\n\n" + "\n".join(lines) + "\n"


def _sync_index(git: _Git, old_head: str | None, paths: Sequence[str]) -> None:
    """Give the real index the new commit's version of each path under `paths` whose index
    entry was the old commit's (nothing of yours staged there); warn about the others."""
    if not paths:
        return
    index = git.entries(None, paths)
    before = git.entries(old_head, paths) if old_head else {}
    after = git.entries("HEAD", paths)
    candidates = sorted({*index, *before, *after})
    safe = [path for path in candidates if index.get(path) == before.get(path)]
    if safe:
        git.run("reset", "-q", "HEAD", "--", *safe)
    for path in candidates:
        if path not in safe and index.get(path) != after.get(path):
            logger.warning("%s: you had staged changes here; left as they are", path)
