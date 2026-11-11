"""YAML in and out, through ruamel.yaml (YAML 1.2).

Two kinds of use. Reading data amo only consumes (the config, palettes, theme.yaml, the
registry, and every info file `amo index` reads) goes through `load`, ruamel's safe loader
(its C parser, from ruamel.yaml.clib, when installed):
plain dicts, lists and scalars. Writing an info file amo read before goes through
`update_text`: the old text is loaded round-trip, only the keys whose values changed are set,
and the document is dumped again, so hand-written comments, key order and formatting survive.
New files and generated output go through `dump`.

Documents are YAML 1.2, where `yes`, `on` and `no` are strings. Output stays readable by YAML
1.1 parsers (PyYAML, which earlier versions used) too: a string either version would take for
something else (`yes`, `1e5`, `012`) is quoted.

Every loader rejects a duplicate mapping key (ruamel's default), rather than keeping the last
one as PyYAML does. Output keeps PyYAML's shape, which earlier versions wrote: two-space
mappings, sequences not indented under their key, `null` spelt out. Lines never fold: ruamel
puts a long scalar that cannot fold (a URL) on a line of its own, and a round trip writes
every scalar again, so folding would reshape lines nobody changed.
"""

from __future__ import annotations

import io
import re
from collections.abc import Mapping

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.constructor import DuplicateKeyError
from ruamel.yaml.error import YAMLError
from ruamel.yaml.nodes import ScalarNode
from ruamel.yaml.representer import RoundTripRepresenter
from ruamel.yaml.resolver import VersionedResolver

__all__ = ["YAMLError", "dump", "dump_scalar", "load", "same", "update_text"]

_WIDTH = 1_000_000  # no folding


_STR_TAG = "tag:yaml.org,2002:str"
_YAML_1_1 = VersionedResolver(version=(1, 1))


class _Representer(RoundTripRepresenter):
    """The round-trip representer, writing None as `null` (it writes nothing by default) and
    quoting a string YAML 1.1 would resolve to another type (1.2's are quoted already)."""

    def represent_str(self, data: str) -> ScalarNode:
        if type(data) is str and _YAML_1_1.resolve(ScalarNode, data, (True, False)) != _STR_TAG:
            return self.represent_scalar(_STR_TAG, data, style="'")
        return super().represent_str(data)


_Representer.add_representer(str, _Representer.represent_str)
_Representer.add_representer(
    type(None),
    lambda representer, _: representer.represent_scalar("tag:yaml.org,2002:null", "null"),
)


def _round_trip() -> YAML:
    # A YAML instance is not reentrant; a new one per call is cheap next to the parse.
    yaml = YAML()
    yaml.Representer = _Representer
    yaml.indent(mapping=2, sequence=2, offset=0)
    yaml.width = _WIDTH
    yaml.preserve_quotes = True
    return yaml


def load(text: str) -> object:
    """The data of a YAML document as plain dicts, lists and scalars; None if it is empty.
    Raises YAMLError (a duplicate key is one)."""
    try:
        # ruamel.yaml.clib's C parser when installed: several times faster for `amo index`.
        return YAML(typ="safe").load(text)
    except DuplicateKeyError as exc:
        raise _duplicate(exc) from None


def _duplicate(exc: DuplicateKeyError) -> YAMLError:
    """A short message for a duplicate key (ruamel's quotes both values and adds a URL)."""
    match = re.search(r'found duplicate key "(.*?)" with value', exc.problem or "")
    key = match.group(1) if match else "?"
    line = f" on line {exc.problem_mark.line + 1}" if exc.problem_mark else ""
    return YAMLError(f"duplicate key {key!r}{line}")


def dump(data: object) -> str:
    """`data` (plain dicts, lists and scalars) as a block-style YAML document, keys in the
    order given."""
    stream = io.StringIO()
    _round_trip().dump(data, stream)
    return stream.getvalue()


def dump_scalar(value: str) -> str:
    """`value` as a YAML scalar on one line: plain when it can be, quoted when YAML would read
    it as something else."""
    stream = io.StringIO()
    _round_trip().dump(value, stream)
    return stream.getvalue().removesuffix("\n").removesuffix("\n...").strip()


def update_text(text: str, data: Mapping[str, object]) -> str:
    """`text`, a YAML mapping, changed to hold `data`: keys whose values are unchanged keep
    their text and comments, changed values are replaced, missing keys removed, new keys added
    after the key that precedes them in `data`. If `text` is not a mapping, `data` is dumped
    fresh. Raises YAMLError if `text` does not parse."""
    yaml = _round_trip()
    try:
        document = yaml.load(text)
    except DuplicateKeyError as exc:
        raise _duplicate(exc) from None
    if not isinstance(document, CommentedMap):
        return dump(dict(data))
    _merge(document, data)
    stream = io.StringIO()
    yaml.dump(document, stream)
    return stream.getvalue()


def _merge(document: CommentedMap, data: Mapping[str, object]) -> None:
    for key in [key for key in document if key not in data]:
        del document[key]
    previous: object = None
    for key, value in data.items():
        if key in document:
            old = document[key]
            if isinstance(old, CommentedMap) and isinstance(value, Mapping):
                _merge(old, value)
            elif not same(old, value):
                document[key] = value
        else:
            keys = list(document)
            position = keys.index(previous) + 1 if previous in keys else len(keys)
            document.insert(position, key, value)
        previous = key


def same(old: object, new: object) -> bool:
    """Whether two loaded values are equal, by type as well as by value: `1` is not `1.0` and
    `true` is not `1`, though Python's `==` says they are."""
    if isinstance(old, Mapping) and isinstance(new, Mapping):
        return old.keys() == new.keys() and all(same(old[key], new[key]) for key in old)
    if isinstance(old, list) and isinstance(new, list):
        return len(old) == len(new) and all(same(a, b) for a, b in zip(old, new, strict=True))
    for kind in (bool, int, float, str):
        if isinstance(old, kind) or isinstance(new, kind):
            return isinstance(old, kind) and isinstance(new, kind) and old == new
    return old == new
