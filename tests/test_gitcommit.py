"""`amo hook git-commit` end to end: amo commands in a library root that is a git repository,
with the hook set as on_change. Skipped without git."""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from conftest import mark_record
from PIL import Image

from amontillado import yamlio
from amontillado.cli import main
from amontillado.gitcommit import HookError, git_commit

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

HOOK = f"{shlex.quote(sys.executable)} -m amontillado hook git-commit"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout


def _image(path: Path, rgb: tuple[int, int, int] = (0, 0, 0)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.full((36, 64, 3), rgb, dtype=np.uint8)).save(path)
    return path


@pytest.fixture
def repo(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The default library root as a git repository with on_change: amo hook git-commit, and
    two records, red and blue, indexed and committed."""
    # Neither the user's git config (signing, hooks) nor the system's.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("COLUMNS", "300")  # the hook's log lines unwrapped, for the asserts
    for variable, value in (("NAME", "t"), ("EMAIL", "t@example.org")):
        monkeypatch.setenv(f"GIT_AUTHOR_{variable}", value)
        monkeypatch.setenv(f"GIT_COMMITTER_{variable}", value)
    config = home / ".config/amontillado/config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(yamlio.dump({"on_change": HOOK}))
    root = home / ".local/share/amontillado/library"
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    for name, rgb in (("red", (255, 0, 0)), ("blue", (0, 0, 255))):
        mark_record(root / name)
        _image(root / name / f"{name}.png", rgb)
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "pictures")
    main(["index"])  # the hook commits the healed info files and the thumbnails
    return root


def _last(root: Path) -> list[str]:
    """The last commit's subject, then its name-status lines."""
    return _git(root, "show", "--format=%s", "--name-status", "HEAD").split("\n\n")[0].splitlines()


def test_index_commits_info_files_and_thumbnails(repo: Path) -> None:
    subject, *changed = _git(repo, "show", "--format=%s", "--name-status", "HEAD").splitlines()
    assert subject == "amo index: blue, red"
    assert sorted(line for line in changed if line) == [
        "A\tblue/.amo/thumbnail.jpg",
        "A\tred/.amo/thumbnail.jpg",
        "M\tblue/info.yaml",
        "M\tred/info.yaml",
    ]
    assert _git(repo, "status", "--porcelain") == ""


def test_an_uncommitted_edit_stays_uncommitted(repo: Path) -> None:
    info = repo / "red" / "info.yaml"
    info.write_text("# my note\n" + info.read_text())
    main(["name", str(repo / "red"), "sunset"])
    assert _git(repo, "log", "-1", "--format=%s") == "amo name: sunset\n"
    committed = _git(repo, "show", "HEAD:sunset/info.yaml")
    assert "name: sunset" in committed and "# my note" not in committed
    assert (repo / "sunset" / "info.yaml").read_text().startswith("# my note\n")
    # The rename is a rename, and only the note is left to commit.
    assert "R100\tred/red.png\tsunset/red.png" in _git(repo, "show", "-M", "--name-status", "HEAD")
    assert _git(repo, "status", "--porcelain") == " M sunset/info.yaml\n"
    assert "+# my note" in _git(repo, "diff")


def test_a_conflict_leaves_the_record_out(repo: Path, capfd: pytest.CaptureFixture[str]) -> None:
    # A hand edit of red's name, not committed, then amo names it: one unit, two changes.
    info = repo / "red" / "info.yaml"
    info.write_text(info.read_text().replace("schema: 2", "schema: 2\nname: mine", 1))
    main(["name", str(repo / "red"), "sunset", "--no-rename-directory"])
    assert "red: not committed: amo's change conflicts" in capfd.readouterr().err
    assert "\nname:" not in _git(repo, "show", "HEAD:red/info.yaml")
    assert _git(repo, "log", "-1", "--format=%s") == "amo index: blue, red\n"


def test_what_you_staged_is_not_committed(repo: Path) -> None:
    (repo / "notes.txt").write_text("mine\n")
    _git(repo, "add", "notes.txt")
    main(["crop", str(repo / "red"), "1:1"])
    assert _last(repo)[0] == "amo crop: red"
    assert "notes.txt" not in _git(repo, "show", "--name-only", "HEAD")
    assert _git(repo, "status", "--porcelain") == "A  notes.txt\n"


def test_ignored_files_are_not_added(repo: Path) -> None:
    (repo / ".gitignore").write_text("*-1x1.png\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-q", "-m", "ignore crops")
    main(["crop", str(repo / "red"), "1:1"])
    assert _git(repo, "show", "--name-only", "--format=", "HEAD") == "red/info.yaml\n"


def test_a_root_outside_git_is_a_warning(
    home: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    git_commit({"version": 1, "command": "index", "root": str(tmp_path), "changes": []})
    assert "not in a git repository; nothing committed" in caplog.text


def test_missing_git_is_a_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("amontillado.gitcommit.shutil.which", lambda _name: None)
    with pytest.raises(HookError, match="git is not installed"):
        git_commit({"version": 1, "command": "index", "root": str(tmp_path), "changes": []})


def test_bad_payload_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("not json"))
    with pytest.raises(SystemExit, match="stdin is not an on_change payload"):
        main(["hook", "git-commit"])
