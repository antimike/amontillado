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


# git-annex roots (amo-qnn.4).

needs_annex = pytest.mark.skipif(shutil.which("git-annex") is None, reason="needs git-annex")
LAYOUT = (
    "* annex.largefiles=nothing\n*.png annex.largefiles=anything\n"
    "**/.amo/** annex.largefiles=nothing\n"
)


@pytest.fixture
def annex(repo: Path) -> Path:
    """`repo` as a git-annex repository, images annexed and thumbnails in git."""
    _git(repo, "annex", "init", "-q", "test")
    (repo / ".gitattributes").write_text(LAYOUT)
    _git(repo, "add", ".gitattributes")
    _git(repo, "commit", "-q", "-m", "layout")
    return repo


def _modes(root: Path) -> dict[str, str]:
    """{path: mode} of the files the last commit added."""
    added = _git(root, "show", "--format=", "--name-only", "--diff-filter=A", "HEAD").split()
    return {path: _git(root, "ls-tree", "HEAD", path).split()[0] for path in added}


@needs_annex
def test_new_images_are_annexed_locked(annex: Path, tmp_path: Path) -> None:
    main(["add", "--name", "green", str(_image(tmp_path / "in" / "green.png", (0, 255, 0)))])
    assert _modes(annex) == {
        "green/.amo/thumbnail.jpg": "100644",  # in git: annex.largefiles=nothing
        "green/green.png": "120000",  # a locked annexed file: a symlink
        "green/info.yaml": "100644",
    }
    assert (annex / "green" / "green.png").is_symlink()
    assert _git(annex, "status", "--porcelain") == ""


@needs_annex
def test_annex_addunlocked_is_honoured(annex: Path, tmp_path: Path) -> None:
    _git(annex, "config", "annex.addunlocked", "true")
    main(["add", "--name", "green", str(_image(tmp_path / "in" / "green.png", (0, 255, 0)))])
    assert _modes(annex)["green/green.png"] == "100644"  # an unlocked file's pointer
    pointer = _git(annex, "cat-file", "blob", "HEAD:green/green.png")
    assert pointer.startswith("/annex/objects/SHA256E-")
    assert not (annex / "green" / "green.png").is_symlink()


@needs_annex
def test_without_git_annex_new_files_stay_uncommitted(
    annex: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    # A clone where git annex init never ran (no annex.uuid, filter or hooks), on a machine
    # without git-annex: the hook runs in a subprocess, its PATH holding git and sh alone.
    _git(annex, "config", "--unset", "annex.uuid")
    _git(annex, "config", "--remove-section", "filter.annex")
    (annex / ".git" / "hooks" / "pre-commit").unlink()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "git").symlink_to(shutil.which("git"))
    (bin_dir / "sh").symlink_to(shutil.which("sh"))
    monkeypatch.setenv("PATH", str(bin_dir))
    main(["add", "--name", "green", str(_image(tmp_path / "in" / "green.png", (0, 255, 0)))])
    assert "git-annex is not installed; new files left uncommitted" in capfd.readouterr().err
    assert _git(annex, "show", "--format=", "--name-only", "HEAD") == "green/info.yaml\n"


def test_annex_repository_from_the_files(tmp_path: Path) -> None:
    from amontillado.gitcommit import annex_repository

    (tmp_path / "plain" / ".git").mkdir(parents=True)
    (tmp_path / "annexed" / ".git" / "annex").mkdir(parents=True)
    (tmp_path / "annexed" / "sub").mkdir()
    assert not annex_repository(tmp_path / "plain")
    assert annex_repository(tmp_path / "annexed" / "sub")
    assert not annex_repository(tmp_path)
