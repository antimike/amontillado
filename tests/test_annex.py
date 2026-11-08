"""A library root that is a real git-annex repository: content dropped and got back.

Skipped when git-annex is not installed. A clone, `backup`, holds a copy of every image, so
content can be dropped and got back.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import subprocess
from pathlib import Path

import numpy as np
import pytest
from conftest import mark_record
from PIL import Image

from amontillado.cli import main

pytestmark = pytest.mark.skipif(shutil.which("git-annex") is None, reason="needs git-annex")

ATTRIBUTES = "* annex.largefiles=nothing\n*.png annex.largefiles=anything\n"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


@pytest.fixture
def annexed(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The default library root as a git-annex repository holding one record, red, with
    red.png annexed (locked) and blue.png beside it; indexed."""
    for variable, value in (
        ("GIT_AUTHOR_NAME", "test"),
        ("GIT_AUTHOR_EMAIL", "test@example.invalid"),
        ("GIT_COMMITTER_NAME", "test"),
        ("GIT_COMMITTER_EMAIL", "test@example.invalid"),
        ("GIT_CONFIG_NOSYSTEM", "1"),
    ):
        monkeypatch.setenv(variable, value)
    root = home / ".local/share/amontillado/library"
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "annex", "init", "-q", "test")
    (root / ".gitattributes").write_text(ATTRIBUTES)
    record = mark_record(root / "red").parent
    for name, rgb in (("red.png", (255, 0, 0)), ("blue.png", (0, 0, 255))):
        Image.fromarray(np.full((36, 64, 3), rgb, dtype=np.uint8)).save(record / name)
    main(["index"])
    (record / "info.yaml").write_text(
        (record / "info.yaml").read_text().replace("schema:", "default_file: red.png\nschema:")
    )
    main(["index"])
    _git(root, "annex", "add", "-q", ".")
    _git(root, "commit", "-q", "-m", "red")
    assert (record / "red.png").is_symlink()
    backup = home / "backup"
    subprocess.run(["git", "clone", "-q", str(root), str(backup)], check=True)
    _git(backup, "annex", "init", "-q", "backup")
    _git(root, "remote", "add", "backup", str(backup))
    _git(root, "annex", "copy", "-q", "--to", "backup", ".")
    main(["index"])
    return record


def _absent_rows(home: Path) -> dict[str, int]:
    with sqlite3.connect(home / ".local/state/amontillado/index.sqlite") as conn:
        return {
            Path(path).name: absent
            for path, absent in conn.execute("SELECT path, absent FROM files")
        }


def test_dropped_content_is_absent_and_not_listed(
    annexed: Path,
    home: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    root = annexed.parent
    _git(root, "annex", "drop", "-q", "red/red.png")
    assert (annexed / "red.png").is_symlink() and not (annexed / "red.png").exists()
    caplog.set_level(logging.INFO)
    capsys.readouterr()
    main(["index", "--check"])  # absent content is not a problem: no SystemExit
    main(["index"])
    assert "1 file not here (git-annex)" in caplog.text
    assert "missing" not in caplog.text
    # The dropped default keeps its row, flagged; amo list prints the file that is here.
    assert _absent_rows(home) == {"red.png": 1, "blue.png": 0}
    main(["list"])
    assert capsys.readouterr().out == f"{annexed / 'blue.png'}\n"
    # .git/annex/objects holds images; none of them is reported loose.
    assert "not in a record" not in caplog.text

    _git(root, "annex", "drop", "-q", "red/blue.png")
    main(["index"])
    assert _absent_rows(home) == {"red.png": 1, "blue.png": 1}
    with pytest.raises(SystemExit, match="no matching pictures"):
        main(["list"])
    with pytest.raises(SystemExit, match=r"red\.png: its content is not here; `git annex get`"):
        main(["palette", str(annexed)])

    _git(root, "annex", "get", "-q", "--from", "backup", ".")
    main(["index"])
    assert _absent_rows(home) == {"red.png": 0, "blue.png": 0}
    capsys.readouterr()
    main(["list"])
    assert capsys.readouterr().out == f"{annexed / 'red.png'}\n"


def test_an_unlocked_file_dropped_is_absent(
    annexed: Path, home: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = annexed.parent
    _git(root, "annex", "unlock", "red/red.png")
    _git(root, "commit", "-q", "-m", "unlock")
    _git(root, "annex", "copy", "-q", "--to", "backup", ".")
    assert not (annexed / "red.png").is_symlink()
    _git(root, "annex", "drop", "-q", "red/red.png")
    assert (annexed / "red.png").read_bytes().startswith(b"/annex/objects/")
    caplog.set_level(logging.INFO)
    main(["index", "--check"])
    main(["index"])
    # Not hashed as content, not measured, not failed.
    assert "failed" not in caplog.text and "content changed" not in caplog.text
    assert _absent_rows(home) == {"red.png": 1, "blue.png": 0}
