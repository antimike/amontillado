from __future__ import annotations

from pathlib import Path

import pytest
from conftest import SaveImage, mark_record

from amontillado.config import Config
from amontillado.edit import EditError, plan_edit, run_edit
from amontillado.library import AddError, heal_library
from amontillado.record import read_record


@pytest.fixture
def record(config: Config, save_image: SaveImage) -> Path:
    """A healed record holding pic.png (red)."""
    info = mark_record(config.library_roots[0] / "r")
    save_image(info.parent / "pic.png", (200, 0, 0), (80, 40))
    heal_library(config)
    return info.parent


@pytest.fixture
def edited(tmp_path: Path, save_image: SaveImage, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An edit of pic.png (green), as EDITED in the environment the tool sees."""
    path = save_image(tmp_path / "edited.png", (0, 200, 0), (80, 40))
    save_image(tmp_path / "edited.jpg", (0, 200, 0), (80, 40))
    monkeypatch.setenv("EDITED", str(path))
    return path


def _workdirs(record: Path) -> list[Path]:
    return list((record / ".amo").glob("edit-*"))


def _edit(config: Config, record: Path, command: str, **plan: str) -> str:
    entry, name = run_edit(config, plan_edit(record, **plan), config.library_roots[0], command)
    assert name in entry.present
    return name


def test_an_edit_over_the_copy_is_added(config: Config, record: Path, edited: Path) -> None:
    name = _edit(config, record, 'cp "$EDITED" "$INPUT"')
    assert name == "pic-edit.png"
    entry = read_record(record / "info.yaml").files[name]
    assert (entry.derived_from, entry.crop) == ("pic.png", None)
    assert (record / name).read_bytes() == edited.read_bytes()
    assert not _workdirs(record)
    assert heal_library(config).clean


def test_output_wins_over_a_changed_copy(config: Config, record: Path, edited: Path) -> None:
    name = _edit(config, record, 'cp "$EDITED" "$OUTPUT" && echo changed >> "$INPUT"')
    assert name == "pic-edit.png"
    assert (record / name).read_bytes() == edited.read_bytes()


def test_an_export_below_the_working_directory_is_found(
    config: Config, record: Path, edited: Path
) -> None:
    command = (
        "touch pic.xcf .hidden.png && mkdir darktable_exported && "
        'cp "${EDITED%.png}.jpg" darktable_exported/pic.jpg'
    )
    assert _edit(config, record, command) == "pic-edit.jpg"


def test_the_default_name_steps_past_a_taken_one(
    config: Config, record: Path, edited: Path, save_image: SaveImage
) -> None:
    assert _edit(config, record, 'cp "$EDITED" "$INPUT"') == "pic-edit.png"
    save_image(edited, (0, 0, 200), (80, 40))
    assert _edit(config, record, 'cp "$EDITED" "$INPUT"') == "pic-edit-2.png"


def test_name_and_source(config: Config, record: Path, edited: Path, save_image: SaveImage) -> None:
    _edit(config, record, 'cp "$EDITED" "$INPUT"')
    save_image(edited, (0, 0, 200), (80, 40))
    command = 'test "$(basename "$INPUT")" = pic-edit.png && cp "$EDITED" "$INPUT"'
    name = _edit(config, record, command, source="pic-edit.png", name="blue.png")
    assert name == "blue.png"
    assert read_record(record / "info.yaml").files[name].derived_from == "pic-edit.png"


@pytest.mark.parametrize(
    ("command", "message", "kept"),
    [
        ("true", r"saved no image; it returned after \d", False),
        ("touch pic.xcf", "saved no image", True),
        ('cp "$EDITED" a.png && cp "$EDITED" b.png', r"several images \(a.png, b.png\)", True),
        ('cp "$EDITED" "$INPUT"; exit 3', "exited with status 3$", True),
        ("exit 3", "exited with status 3$", False),
        ("no-such-editor-here", r"status 127 \(command not found\)", False),
        ('cp "$WORKDIR/pic.png" "$OUTPUT"', "same content as", True),
    ],
)
def test_failures(
    config: Config, record: Path, edited: Path, command: str, message: str, kept: bool
) -> None:
    before = (record / "info.yaml").read_text()
    with pytest.raises(EditError, match=message) as caught:
        _edit(config, record, command)
    workdir = caught.value.workdir
    assert (workdir is not None) == kept
    if workdir is not None:
        assert workdir.is_dir() and workdir.parent == record / ".amo"
    else:
        assert not _workdirs(record)
    assert (record / "info.yaml").read_text() == before
    # Whatever is kept is invisible to amo index.
    assert heal_library(config).clean


def test_a_name_of_another_format_is_refused(config: Config, record: Path, edited: Path) -> None:
    with pytest.raises(EditError, match=r"the result is a \.png file") as caught:
        _edit(config, record, 'cp "$EDITED" "$INPUT"', name="pic-edit.jpg")
    assert caught.value.workdir is not None


def test_a_jpeg_name_takes_a_jpg_result(config: Config, record: Path, edited: Path) -> None:
    command = 'cp "${EDITED%.png}.jpg" out.jpg'
    assert _edit(config, record, command, name="pic-edit.jpeg") == "pic-edit.jpeg"


def test_the_tool_output_goes_to_stderr(
    config: Config, record: Path, edited: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    _edit(config, record, 'echo from-the-tool; cp "$EDITED" "$INPUT"')
    out, err = capfd.readouterr()
    assert "from-the-tool" not in out and "from-the-tool" in err


def test_plan_refusals(config: Config, record: Path, save_image: SaveImage) -> None:
    for options, message in (
        ({"source": "none.png"}, "no file none.png"),
        ({"name": "pic.png"}, "lists pic.png already"),
        ({"name": "x.txt"}, "not an image file name"),
    ):
        with pytest.raises(AddError, match=message):
            plan_edit(record, **options)
    save_image(record / "unlisted.png")
    with pytest.raises(AddError, match="run `amo index` first"):
        plan_edit(record)
    with pytest.raises(AddError, match="not a record"):
        plan_edit(record.parent)
