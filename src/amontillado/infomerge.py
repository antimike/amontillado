"""Schema-aware diff and three-way merge of info files (`amo info diff`, `amo info merge`).

docs/design.md, "git-annex libraries: decisions" 5. The merge works on units, not lines:

- every top-level key is a unit, except `files` and `default_file`;
- the names under `files`, with `default_file`, are one unit (adding, removing or renaming a
  file, or choosing another default);
- each entry under `files` is a unit (its sha256, size, crop, derived_from and metrics agree
  with each other and with the file).

A unit changed on one side only takes that side; changed the same way on both, it is that
value; changed differently on both, it is a conflict. The merge is applied to OURS through a
round trip, so OURS' comments and layout survive, and must still be a valid record
(`record.parse`), else it is a conflict too. Three files of different `schema` conflict: no
implicit upgrade.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from amontillado import yamlio
from amontillado.record import SCHEMA, RecordError, parse

_FILES = "files"
_DEFAULT = "default_file"
# A unit's value when the unit is absent from a file (None is a value YAML can hold).
_ABSENT = object()


class InfoError(Exception):
    """An info file is not a YAML mapping; the message says why."""


@dataclass(frozen=True)
class Change:
    """One difference between two info files: a key path added, removed or changed."""

    path: tuple[str, ...]
    kind: str  # "added", "removed" or "changed"
    old: object = None
    new: object = None

    def to_dict(self) -> dict[str, object]:
        values: dict[str, object] = {"path": list(self.path), "change": self.kind}
        if self.kind != "added":
            values["old"] = self.old
        if self.kind != "removed":
            values["new"] = self.new
        return values

    def describe(self) -> str:
        where = format_path(self.path)
        if self.kind == "added":
            return f"+ {where}: {_brief(self.new)}"
        if self.kind == "removed":
            return f"- {where}: {_brief(self.old)}"
        return f"~ {where}: {_brief(self.old)} -> {_brief(self.new)}"


@dataclass
class Merge:
    """A three-way merge: the merged text of OURS (None on conflict), whether THEIRS changed
    anything OURS lacks, and the conflicting units."""

    text: str | None = None
    changed: bool = False
    conflicts: list[str] = field(default_factory=list)


def load(text: str) -> dict[str, object]:
    """An info file's mapping (empty for an empty file). Raises InfoError."""
    try:
        data = yamlio.load(text)
    except yamlio.YAMLError as exc:
        raise InfoError(f"not valid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise InfoError("not a YAML mapping")
    return data


def diff(old: Mapping[str, object], new: Mapping[str, object]) -> list[Change]:
    """The key paths that differ from `old` to `new`, in `old`'s order then `new`'s; mappings
    are compared key by key, anything else (lists included) as a whole."""
    changes: list[Change] = []
    _diff((), old, new, changes)
    return changes


def _diff(
    path: tuple[str, ...], old: Mapping[str, object], new: Mapping[str, object], out: list[Change]
) -> None:
    for key, value in old.items():
        here = (*path, str(key))
        if key not in new:
            out.append(Change(here, "removed", old=value))
        elif isinstance(value, Mapping) and isinstance(new[key], Mapping):
            _diff(here, value, new[key], out)
        elif not yamlio.same(value, new[key]):
            out.append(Change(here, "changed", old=value, new=new[key]))
    for key, value in new.items():
        if key not in old:
            out.append(Change((*path, str(key)), "added", new=value))


def format_path(path: tuple[str, ...]) -> str:
    """A key path for people: dotted, with a key that has a dot in it (a file name) bracketed:
    `files["a.png"].metrics.hue`."""
    text = ""
    for key in path:
        if "." in key or "[" in key or not key:
            text += f"[{json.dumps(key)}]"
        else:
            text += f".{key}" if text else key
    return text


def _brief(value: object, limit: int = 60) -> str:
    text = json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def merge(base: str, ours: str, theirs: str) -> Merge:
    """Merge THEIRS' changes since BASE into OURS (three info files' texts). Raises InfoError
    if one is not a YAML mapping."""
    base_data, ours_data, theirs_data = load(base), load(ours), load(theirs)
    schemas = [data.get("schema", SCHEMA) for data in (base_data, ours_data, theirs_data)]
    if len({json.dumps(schema, default=str) for schema in schemas}) > 1:
        return Merge(conflicts=[f"schema: {' / '.join(map(str, schemas))} (base / ours / theirs)"])
    for data in (base_data, ours_data, theirs_data):
        if data.get(_FILES) is not None and not isinstance(data[_FILES], dict):
            raise InfoError(f"{_FILES} is not a mapping")

    keys: dict[str, object] = {}  # top-level keys THEIRS changed, to its values
    names: tuple[list[str], object] | None = None  # the file names and default_file
    files: dict[str, object] = {}  # files entries THEIRS changed
    conflicts: list[str] = []
    for unit in _units(base_data, ours_data, theirs_data):
        value_base, value_ours, value_theirs = (
            unit.value(data) for data in (base_data, ours_data, theirs_data)
        )
        if _same(value_ours, value_theirs) or _same(value_base, value_theirs):
            continue  # OURS has it already, or THEIRS did not change it
        if not _same(value_base, value_ours):
            conflicts.append(f"{unit.describe()}: changed on both sides")
        elif unit.kind == "key":
            keys[unit.key] = value_theirs
        elif unit.kind == "names":
            names = value_theirs  # type: ignore[assignment]
        else:
            files[unit.key] = value_theirs
    if conflicts:
        return Merge(conflicts=conflicts)
    if not (keys or names or files):
        return Merge(text=ours)

    merged = _ordered(ours_data, theirs_data, keys)
    if names is not None:
        merged.pop(_DEFAULT, None)
        if names[1] is not _ABSENT:
            merged = _ordered(merged, theirs_data, {_DEFAULT: names[1]})
    if files:
        merged_files = _ordered(_files(ours_data), _files(theirs_data), files)
        merged = _ordered(merged, theirs_data, {_FILES: merged_files})
    try:
        parse(merged)
    except RecordError as exc:
        return Merge(conflicts=[f"the merged record is invalid: {exc}"])
    return Merge(text=yamlio.update_text(ours, merged), changed=True)


def _same(a: object, b: object) -> bool:
    if a is _ABSENT or b is _ABSENT:
        return a is b
    if isinstance(a, tuple) and isinstance(b, tuple):  # the names unit
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    return yamlio.same(a, b)


def _files(data: Mapping[str, object]) -> dict[str, object]:
    files = data.get(_FILES)
    return files if isinstance(files, dict) else {}


@dataclass(frozen=True)
class _Unit:
    kind: str  # "key" (a top-level key), "names" (files' names, default_file) or "file"
    key: str = ""

    def value(self, data: Mapping[str, object]) -> object:
        if self.kind == "key":
            return data.get(self.key, _ABSENT)
        if self.kind == "names":
            return (sorted(map(str, _files(data))), data.get(_DEFAULT, _ABSENT))
        return _files(data).get(self.key, _ABSENT)

    def describe(self) -> str:
        if self.kind == "key":
            return format_path((self.key,))
        if self.kind == "names":
            return f"the file names under {_FILES} and {_DEFAULT}"
        return format_path((_FILES, self.key))


def _units(*datas: Mapping[str, object]) -> list[_Unit]:
    """Every unit of the files `datas`, top-level keys in their order of first appearance."""
    keys: dict[object, None] = {}
    names: dict[object, None] = {}
    for data in datas:
        keys.update(dict.fromkeys(key for key in data if key not in (_FILES, _DEFAULT)))
        names.update(dict.fromkeys(_files(data)))
    return [
        *(_Unit("key", key) for key in keys),  # type: ignore[arg-type]
        _Unit("names"),
        *(_Unit("file", name) for name in names),  # type: ignore[arg-type]
    ]


def _ordered(
    ours: Mapping[str, object], theirs: Mapping[str, object], updates: Mapping[str, object]
) -> dict[str, object]:
    """`ours` with `updates` applied (an _ABSENT value removes the key); a key not in `ours`
    goes after the nearest key before it in `theirs` that the result has, else last."""
    merged = {key: updates.get(key, value) for key, value in ours.items()}
    order = list(theirs)
    for key, value in updates.items():
        if key in merged:
            continue
        position = len(merged)
        if key in order:
            keys = list(merged)
            for before in reversed(order[: order.index(key)]):
                if before in merged:
                    position = keys.index(before) + 1
                    break
        items = list(merged.items())
        items.insert(position, (key, value))
        merged = dict(items)
    return {key: value for key, value in merged.items() if value is not _ABSENT}
