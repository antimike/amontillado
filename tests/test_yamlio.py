from __future__ import annotations

from datetime import UTC, datetime

import pytest

from amontillado import yamlio


def test_dump_keeps_pyyaml_shape() -> None:
    data = {"b": None, "a": {"list": [1, 2]}, "when": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)}
    assert yamlio.dump(data) == (
        "b: null\na:\n  list:\n  - 1\n  - 2\nwhen: 2026-01-02 03:04:05+00:00\n"
    )


@pytest.mark.parametrize("value", ["yes", "on", "No", "y", "1:30", "1e5", "012", "~", "null", ""])
def test_strings_another_yaml_version_would_misread_are_quoted(value: str) -> None:
    # YAML 1.1 (PyYAML) reads yes/on/y as booleans, 1:30 as 90, 012 as octal; 1.2 reads 1e5
    # as a float. Quoted, every reader gets the string back.
    text = yamlio.dump({"key": value})
    assert text == f"key: '{value}'\n"
    assert yamlio.load(text) == {"key": value}


def test_long_lines_do_not_fold() -> None:
    url = "https://example.org/" + "a" * 120
    words = " ".join(["word"] * 40)
    assert yamlio.dump({"source": url, "text": words}) == f"source: {url}\ntext: {words}\n"


def test_duplicate_key_message_is_short() -> None:
    with pytest.raises(yamlio.YAMLError) as caught:
        yamlio.load("a: 1\nb: 2\na: 3\n")
    assert str(caught.value) == "duplicate key 'a' on line 3"
    with pytest.raises(yamlio.YAMLError, match="duplicate key 'a'"):
        yamlio.update_text("a: 1\na: 3\n", {"a": 1})


def test_yaml_1_2_scalars() -> None:
    assert yamlio.load("a: yes\nb: on\nc: 1e3\n") == {"a": "yes", "b": "on", "c": 1000.0}


def test_update_text_keeps_untouched_text() -> None:
    text = "# top\nkeep: [1, 2]  # flow\nnested:\n  x: 'quoted'\n  w: 1\ngone: 3\n"
    data = {"keep": [1, 2], "nested": {"x": "quoted", "w": 2, "z": "new"}, "added": True}
    assert yamlio.update_text(text, data) == (
        "# top\nkeep: [1, 2]  # flow\nnested:\n  x: 'quoted'\n  w: 2\n  z: new\nadded: true\n"
    )


def test_update_text_of_a_non_mapping_dumps_fresh() -> None:
    assert yamlio.update_text("", {"a": 1}) == "a: 1\n"
    assert yamlio.update_text("- x\n", {"a": 1}) == "a: 1\n"
