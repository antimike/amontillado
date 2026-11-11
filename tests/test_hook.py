"""The on_change hook: what amo records of its writes, and how it runs the hook."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from conftest import mark_record
from PIL import Image

from amontillado import changes, yamlio
from amontillado.cli import main

# Saves each payload as payload.<command>.<root's name>, and says it ran on stdout.
CAPTURE = 'cat > "$HOME/payload.$AMO_COMMAND.$(basename "$AMO_ROOT")"; echo "hook ran"'


def _config(home: Path, **settings: object) -> None:
    path = home / ".config" / "amontillado" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yamlio.dump(settings))


def _image(path: Path, rgb: tuple[int, int, int] = (0, 0, 0)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.full((36, 64, 3), rgb, dtype=np.uint8)).save(path)
    return path


def _payload(home: Path, command: str, root: str = "library") -> dict:
    return json.loads((home / f"payload.{command}.{root}").read_text())


@pytest.fixture
def library(home: Path) -> Path:
    root = home / ".local/share/amontillado/library"
    root.mkdir(parents=True)
    _config(home, on_change=CAPTURE)
    return root


def _kinds(payload: dict) -> list[tuple[str, str]]:
    return [(c["type"], c.get("path") or f"{c['from']} -> {c['to']}") for c in payload["changes"]]


def test_index_reports_info_files_and_thumbnails(
    library: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    info = mark_record(library / "red")
    _image(library / "red" / "red.png", (255, 0, 0))
    main(["index"])
    payload = _payload(home, "index")
    assert payload["version"] == 1 and payload["command"] == "index"
    assert payload["root"] == str(library.resolve())
    assert _kinds(payload) == [("info", "red/info.yaml"), ("file", "red/.amo/thumbnail.jpg")]
    assert payload["changes"][0]["before"] == ""
    assert payload["changes"][0]["after"] == info.read_text()
    # The hook's stdout is not amo's: it goes to stderr.
    captured = capsys.readouterr()
    assert "hook ran" in captured.err and "hook ran" not in captured.out

    (home / "payload.index.library").unlink()
    main(["index"])  # nothing to heal: no hook
    assert not (home / "payload.index.library").exists()


def test_name_reports_the_rename_and_the_text_as_read(library: Path, home: Path) -> None:
    mark_record(library / "red")
    _image(library / "red" / "red.png", (255, 0, 0))
    main(["index"])
    before = (library / "red" / "info.yaml").read_text()
    main(["name", str(library / "red"), "harbour"])
    payload = _payload(home, "name")
    assert _kinds(payload) == [("rename", "red -> harbour"), ("info", "harbour/info.yaml")]
    assert payload["changes"][1]["before"] == before
    assert "name: harbour" in payload["changes"][1]["after"]


def test_crop_and_add(library: Path, home: Path, tmp_path: Path) -> None:
    main(["add", "--name", "wide", str(_image(tmp_path / "outside" / "wide.png"))])
    assert _kinds(_payload(home, "add")) == [
        ("info", "wide/info.yaml"),
        ("file", "wide/wide.png"),
        ("file", "wide/.amo/thumbnail.jpg"),
    ]
    main(["crop", "wide", "1:1"])
    assert _kinds(_payload(home, "crop")) == [
        ("info", "wide/info.yaml"),
        ("file", "wide/wide-1x1.png"),
    ]
    # A loose image already in the root moves into its record: a rename.
    main(["add", str(_image(library / "loose.png", (0, 0, 255)))])
    assert _kinds(_payload(home, "add")) == [
        ("rename", "loose.png -> loose/loose.png"),
        ("info", "loose/info.yaml"),
        ("file", "loose/loose.png"),
        ("file", "loose/.amo/thumbnail.jpg"),
    ]


def test_one_run_per_root(library: Path, home: Path) -> None:
    nsfw = home / ".local/share/amontillado/library-nsfw"
    for root in (library, nsfw):
        mark_record(root / "r")
        _image(root / "r" / "r.png")
    main(["index"])
    assert _payload(home, "index", "library")["root"] == str(library.resolve())
    assert _payload(home, "index", "library-nsfw")["root"] == str(nsfw.resolve())


def test_a_failing_hook_is_a_warning(
    library: Path, home: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _config(home, on_change="exit 3")
    mark_record(library / "r")
    _image(library / "r" / "r.png")
    main(["index"])  # no SystemExit: amo's own run succeeded
    assert "on_change failed (exit status 3); amo's changes stand" in caplog.text
    assert "sha256" in (library / "r" / "info.yaml").read_text()


def test_the_hook_runs_after_a_failed_command(
    library: Path, home: Path, caplog: pytest.LogCaptureFixture
) -> None:
    mark_record(library / "good")
    _image(library / "good" / "good.png")
    (library / "bad").mkdir()
    (library / "bad" / "info.yaml").write_text("- not a mapping\n")
    with pytest.raises(SystemExit):
        main(["index"])
    assert _kinds(_payload(home, "index"))[0] == ("info", "good/info.yaml")


def test_unset_runs_nothing(library: Path, home: Path) -> None:
    _config(home)
    mark_record(library / "r")
    _image(library / "r" / "r.png")
    main(["index"])
    assert not list(home.glob("payload.*"))


def test_a_file_written_back_as_read_is_no_change(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    with changes.recording() as recorder:
        changes.info_written(root / "r" / "info.yaml", "a: 1\n", "a: 2\n")
        changes.info_written(root / "r" / "info.yaml", "a: 2\n", "a: 1\n")
        changes.file_written(tmp_path / "elsewhere.png")
    assert recorder.payloads("x", [root / "r"]) == []
    changes.file_written(root / "late.png")  # not recording: ignored
    assert recorder.files == {root / "elsewhere.png": None}
