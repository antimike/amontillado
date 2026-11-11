from __future__ import annotations

import pytest

from amontillado import yamlio
from amontillado.infomerge import Change, InfoError, diff, format_path, load, merge

ID = "3f2a9c1e0b7d4e8f9a6b5c4d3e2f1a0b"
SHA_A, SHA_B, SHA_C = "a" * 64, "b" * 64, "c" * 64

BASE = f"""\
schema: 2
id: {ID}
name: harbour
source: null
files:
  a.png:
    sha256: {SHA_A}
    width: 100
    height: 50
"""


def _with(text: str, **changes: object) -> str:
    """`text` with top-level keys set (None removes one), through a round trip."""
    data = yamlio.load(text)
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    return yamlio.update_text(text, data)


def _entry(sha: str, **extra: object) -> dict[str, object]:
    return {"sha256": sha, "width": 100, "height": 50, **extra}


def test_diff_lists_key_paths() -> None:
    old = load(BASE)
    new = load(_with(BASE, name="pier", rating=5, source=None))
    new["files"]["a.png"]["width"] = 200
    assert [change.describe() for change in diff(old, new)] == [
        '~ name: "harbour" -> "pier"',
        "- source: null",
        '~ files["a.png"].width: 100 -> 200',
        "+ rating: 5",
    ]
    assert Change(("files", "a.png"), "added", new={}).to_dict() == {
        "path": ["files", "a.png"],
        "change": "added",
        "new": {},
    }


def test_diff_of_equal_values_of_another_type() -> None:
    assert [c.kind for c in diff({"w": 1}, {"w": 1.0})] == ["changed"]
    assert diff(load(BASE), load(BASE)) == []


def test_format_path() -> None:
    assert format_path(("files", "a.png", "metrics", "hue")) == 'files["a.png"].metrics.hue'
    assert format_path(("name",)) == "name"


def test_theirs_change_is_applied_and_ours_comments_survive() -> None:
    ours = BASE.replace("name: harbour", "name: harbour  # kept by hand")
    theirs = _with(BASE, source={"site": "local"})
    result = merge(BASE, ours, theirs)
    assert result.conflicts == [] and result.changed
    assert "name: harbour  # kept by hand\nsource:\n  site: local\n" in result.text


def test_both_sides_changing_different_units_merge() -> None:
    ours = _with(BASE, name="pier")
    data = load(BASE)
    data["files"]["b.png"] = _entry(SHA_B, derived_from="a.png", crop=[0, 0, 50, 50])
    theirs = yamlio.update_text(BASE, data)
    result = merge(BASE, ours, theirs)
    assert result.conflicts == []
    merged = load(result.text)
    assert merged["name"] == "pier"
    assert list(merged["files"]) == ["a.png", "b.png"]
    assert merged["files"]["b.png"]["derived_from"] == "a.png"


def test_same_change_on_both_sides_is_no_conflict() -> None:
    ours = theirs = _with(BASE, name="pier")
    result = merge(BASE, ours, theirs)
    assert result.conflicts == [] and not result.changed and result.text == ours


def test_nothing_from_theirs_leaves_ours_as_it_is() -> None:
    ours = "# mine\n" + _with(BASE, name="pier")
    assert merge(BASE, ours, BASE).text == ours


def test_one_key_changed_on_both_sides_conflicts() -> None:
    result = merge(BASE, _with(BASE, name="pier"), _with(BASE, name="quay"))
    assert result.text is None
    assert result.conflicts == ["name: changed on both sides"]


def test_one_file_entry_is_one_unit() -> None:
    def metrics(hue: float) -> str:
        data = load(BASE)
        data["files"]["a.png"]["metrics"] = {"version": 2, "hue": hue}
        return yamlio.update_text(BASE, data)

    result = merge(BASE, metrics(10.0), metrics(20.0))
    assert result.conflicts == ['files["a.png"]: changed on both sides']


def test_default_file_couples_with_the_file_names() -> None:
    data = load(BASE)
    data["files"]["b.png"] = _entry(SHA_B)
    ours = yamlio.update_text(BASE, data)
    data = load(BASE)
    data["files"]["c.png"] = _entry(SHA_C)
    theirs_adds = yamlio.update_text(BASE, data)
    assert merge(BASE, ours, theirs_adds).conflicts == [
        "the file names under files and default_file: changed on both sides"
    ]
    theirs_default = _with(BASE, default_file="a.png")
    assert merge(BASE, ours, theirs_default).conflicts == [
        "the file names under files and default_file: changed on both sides"
    ]
    # Without a change to the names on our side, the default is THEIRS'.
    result = merge(BASE, _with(BASE, name="pier"), theirs_default)
    assert load(result.text)["default_file"] == "a.png"


def test_a_merge_that_breaks_the_record_conflicts() -> None:
    # OURS derives b.png from a.png; THEIRS renamed a.png to z.png.
    data = load(BASE)
    data["files"]["b.png"] = _entry(SHA_B, derived_from="a.png")
    base = yamlio.update_text(BASE, data)
    data = load(base)
    data["files"]["b.png"]["crop"] = [0, 0, 10, 10]
    ours = yamlio.update_text(base, data)
    data = load(base)
    data["files"] = {"z.png": data["files"]["a.png"], "b.png": data["files"]["b.png"]}
    theirs = yamlio.update_text(base, data)
    result = merge(base, ours, theirs)
    assert result.text is None
    assert result.conflicts == [
        "the merged record is invalid: b.png: derived_from names no other file of the record"
    ]


def test_schema_mismatch_conflicts() -> None:
    result = merge(BASE, BASE, BASE.replace("schema: 2", "schema: 3"))
    assert result.conflicts == ["schema: 2 / 2 / 3 (base / ours / theirs)"]


def test_empty_base_is_an_add_add_merge() -> None:
    # git passes an empty BASE when both sides added the file.
    result = merge("", BASE, _with(BASE, rating=5))
    assert result.conflicts == []
    assert load(result.text)["rating"] == 5


def test_a_new_key_goes_after_its_predecessor_in_theirs() -> None:
    theirs = _with(BASE, rating=5)
    data = load(theirs)
    data = {"schema": 2, "id": ID, "name": "harbour", "note": "x", **data}
    theirs = yamlio.dump(data)
    result = merge(BASE, BASE, theirs)
    assert list(load(result.text)) == ["schema", "id", "name", "note", "source", "files", "rating"]


@pytest.mark.parametrize("bad", ["- a\n", "a: [\n", "a: 1\na: 2\n", "files: [a]\n"])
def test_unusable_input_raises(bad: str) -> None:
    with pytest.raises(InfoError):
        merge(BASE, BASE, bad)


def test_theirs_removals_apply() -> None:
    data = load(BASE)
    data["files"]["b.png"] = _entry(SHA_B)
    data["rating"] = 5
    base = yamlio.update_text(BASE, data)
    ours = base.replace("name: harbour", "name: pier")
    data = load(base)
    del data["files"]["b.png"], data["rating"]
    theirs = yamlio.update_text(base, data)
    merged = load(merge(base, ours, theirs).text)
    assert "rating" not in merged and list(merged["files"]) == ["a.png"]
    assert merged["name"] == "pier"
