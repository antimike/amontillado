"""amo group --predicate: the user's commands that accept or reject a companion.

docs/design.md, "Grouping (v0.7)", "Predicates" (amo-6x6, agreed with MH 2026-11-18). A predicate
is a command line run under `sh -c` with AMO_PRIMARY and AMO_CANDIDATE, paths to JSON files amo
writes into a temporary directory (`describe`: the record as `amo list --where` sees it, the
file chosen for the monitor with its metrics and palette, the monitor, the distance to the
primary), and AMO_MONITOR, the candidate's monitor; never the info files themselves. Exit 0
accepts, 1 rejects; anything else (126 and 127 from the shell, a signal) is an error that stops
`amo group`. Its standard output goes to standard error: amo group's own is data.

`Judge` runs them, all of them for a candidate (stopping at the first rejection), and keeps
each verdict, since `amo group` may ask about the same pair again (once to see whether a
primary can fill the set, once to fill it).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path

from amontillado.config import shell_status
from amontillado.grouping import Choice

logger = getLogger(__name__)


class PredicateError(Exception):
    """A predicate failed (not a verdict): it could not run, or exited other than 0 or 1."""


@dataclass(frozen=True)
class Predicate:
    """A command line for `sh -c`, and how messages name it (its name under
    group.predicates, or --predicate-cmd)."""

    label: str
    cmd: str


def describe(choice: Choice, record: Mapping[str, object]) -> dict[str, object]:
    """What a predicate reads about a picture: `record` (the record as `amo list --where` sees
    it: a row of the `pictures` view), the file chosen for the monitor, the monitor, and the
    distance to the primary's palette (0 for the primary)."""
    file = choice.file
    return {
        "record": dict(record),
        "file": {
            "path": str(file.path),
            "width": file.width,
            "height": file.height,
            "default": file.is_default,
            "metrics": file.metrics.to_dict(),
        },
        "monitor": {"name": choice.monitor.name, "aspect": choice.monitor.aspect},
        "distance": round(choice.distance, 3),
    }


class Judge:
    """Runs `predicates` on candidates, writing their JSON into `directory` (which must exist
    and be the caller's to remove). `records` gives a record's row by id."""

    def __init__(
        self,
        predicates: Sequence[Predicate],
        directory: Path,
        records: Callable[[str], Mapping[str, object]],
    ) -> None:
        self.predicates = list(predicates)
        self.directory = directory
        self.records = records
        self._verdicts: dict[tuple[Path, Path, str], bool] = {}
        self._written: dict[tuple[Path, str, Path | None], Path] = {}
        # AMO_* from amo's own environment would be stale: only this run's are set.
        self._base = {k: v for k, v in os.environ.items() if not k.startswith("AMO_")}

    def accepts(self, primary: Choice, candidate: Choice) -> bool:
        """Whether every predicate accepts `candidate` beside `primary`. Raises
        PredicateError."""
        key = (primary.file.path, candidate.file.path, candidate.monitor.name)
        if key not in self._verdicts:
            self._verdicts[key] = self._judge(primary, candidate)
        return self._verdicts[key]

    def _judge(self, primary: Choice, candidate: Choice) -> bool:
        variables = {
            "AMO_PRIMARY": str(self._write(primary, None)),
            "AMO_CANDIDATE": str(self._write(candidate, primary.file.path)),
            "AMO_MONITOR": candidate.monitor.name,
        }
        for predicate in self.predicates:
            try:
                result = subprocess.run(
                    ["sh", "-c", predicate.cmd],
                    env=self._base | variables,
                    stdout=subprocess.PIPE,
                    check=False,
                    text=True,
                )
            except OSError as exc:
                raise PredicateError(f"predicate {predicate.label}: {exc}") from exc
            # Its output is not data: stdout carries amo group's.
            sys.stderr.write(result.stdout)
            if result.returncode not in (0, 1):
                status = (
                    f"killed by signal {-result.returncode}"
                    if result.returncode < 0
                    else shell_status(result.returncode)
                )
                raise PredicateError(f"predicate {predicate.label} failed: {status}")
            logger.debug(
                "predicate %s %s %s for %s",
                predicate.label,
                "accepts" if result.returncode == 0 else "rejects",
                candidate.file.path,
                candidate.monitor.name,
            )
            if result.returncode == 1:
                return False
        return True

    def _write(self, choice: Choice, primary: Path | None) -> Path:
        """The JSON file describing `choice` (as a candidate beside `primary`, or as the
        primary when None), written once."""
        key = (choice.file.path, choice.monitor.name, primary)
        path = self._written.get(key)
        if path is None:
            kind = "primary" if primary is None else "candidate"
            path = self.directory / f"{kind}-{len(self._written)}.json"
            data = describe(choice, self.records(choice.file.record_id))
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            self._written[key] = path
        return path
