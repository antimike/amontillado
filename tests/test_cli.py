from __future__ import annotations

import io
import sqlite3
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import numpy as np
import pytest
import yaml
from conftest import FakeClock, FakeWeb, mark_record
from PIL import Image

from amontillado import __version__
from amontillado.cli import get_cli_arguments, main
from amontillado.wallhaven import Client


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"amontillado {__version__}"


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    main([])
    assert "usage: amontillado" in capsys.readouterr().out.lower()


def _save(array: np.ndarray, path: Path) -> Path:
    Image.fromarray(array).save(path)
    return path


def test_measure_prints_yaml(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    black = _save(np.zeros((36, 64, 3), dtype=np.uint8), tmp_path / "black.png")
    red = _save(np.full((36, 64, 3), (255, 0, 0), dtype=np.uint8), tmp_path / "red.png")
    main(["measure", str(black), str(red)])
    out = yaml.safe_load(capsys.readouterr().out)
    assert [entry["file"] for entry in out] == [str(black), str(red)]
    assert out[0]["metrics"]["hue"] is None
    assert out[0]["classes"] == ["dark", "muted", "sparse"]
    assert out[1]["metrics"]["hue_name"] == "red"
    assert {"saturated", "monochrome", "warm", "red"} <= set(out[1]["classes"])


def test_measure_reports_bad_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = _save(np.zeros((36, 64, 3), dtype=np.uint8), tmp_path / "good.png")
    bad = tmp_path / "bad.png"
    bad.write_text("not an image")
    with pytest.raises(SystemExit) as exc:
        main(["measure", str(bad), str(good), str(tmp_path / "missing.png")])
    assert exc.value.code == "amontillado: 2 of 3 files could not be measured"
    out = yaml.safe_load(capsys.readouterr().out)
    assert [entry["file"] for entry in out] == [str(good)]


def test_loglevel_before_or_after_command() -> None:
    assert get_cli_arguments(["-l", "debug", "measure", "x"]).loglevel == "DEBUG"
    assert get_cli_arguments(["measure", "-l", "warning", "x"]).loglevel == "WARNING"
    assert get_cli_arguments(["measure", "x"]).loglevel == "INFO"


@pytest.fixture
def library(home: Path) -> Path:
    """The default library root under a temporary HOME."""
    root = home / ".local/share/amontillado/library"
    root.mkdir(parents=True)
    return root


def _index_rows(home: Path) -> list[str]:
    with sqlite3.connect(home / ".local/state/amontillado/index.sqlite") as conn:
        return [Path(row[0]).name for row in conn.execute("SELECT path FROM files ORDER BY 1")]


def _record(directory: Path, rgb: tuple[int, int, int] = (0, 0, 0), name: str = "a.png") -> Path:
    """A record holding one solid-colour image; returns the image."""
    mark_record(directory)
    return _save(np.full((36, 64, 3), rgb, dtype=np.uint8), directory / name)


def test_index_heals_and_indexes(library: Path, home: Path) -> None:
    _record(library / "r")
    main(["index"])
    assert "a.png" in yaml.safe_load((library / "r" / "info.yaml").read_text())["files"]
    assert _index_rows(home) == ["a.png"]


def test_index_check_writes_nothing_and_fails(library: Path, home: Path) -> None:
    _record(library / "r")
    with pytest.raises(SystemExit) as exc:
        main(["index", "--check"])
    assert exc.value.code == "amontillado: 1 record to heal"
    assert (library / "r" / "info.yaml").read_text() == ""
    assert not (home / ".local/state/amontillado/index.sqlite").exists()


def test_index_check_passes_on_a_healed_library(library: Path) -> None:
    _record(library / "r")
    main(["index"])
    main(["index", "--check"])


def test_index_loose_and_missing_fail_only_a_check(library: Path) -> None:
    _save(np.zeros((36, 64, 3), dtype=np.uint8), library / "loose.png")
    _record(library / "r", name="a.png")
    _record(library / "r", name="b.png")
    main(["index"])
    (library / "r" / "a.png").unlink()
    main(["index"])
    with pytest.raises(SystemExit) as exc:
        main(["index", "--check"])
    assert exc.value.code == "amontillado: 1 image outside a record, 1 file missing"


def test_index_indexes_the_rest_when_a_record_fails(library: Path, home: Path) -> None:
    _record(library / "good")
    mark_record(library / "bad")
    (library / "bad" / "x.png").write_text("not an image")
    with pytest.raises(SystemExit) as exc:
        main(["index"])
    assert exc.value.code == "amontillado: 1 file could not be read or used"
    assert _index_rows(home) == ["a.png"]


def test_config_error_exits(home: Path) -> None:
    (home / ".config/amontillado").mkdir(parents=True)
    (home / ".config/amontillado/config.yaml").write_text("library_roots: /x\n")
    with pytest.raises(SystemExit) as exc:
        main(["index"])
    assert exc.value.code == "amontillado: library_roots must be a list of paths"


@pytest.fixture
def indexed(library: Path, home: Path) -> dict[str, Path]:
    """An indexed library of one-image records: black, white, red, grey noise, and a black
    one in the NSFW root. Images are named after their record."""
    noise = np.random.default_rng(0).integers(0, 256, size=(36, 64), dtype=np.uint8)
    nsfw = home / ".local/share/amontillado/library-nsfw"
    paths = {
        "black": _record(library / "black", (0, 0, 0), "black.png"),
        "white": _record(library / "white", (255, 255, 255), "white.png"),
        "red": _record(library / "red", (255, 0, 0), "red.png"),
        "private": _record(nsfw / "private", (0, 0, 0), "private.png"),
    }
    mark_record(library / "noise")
    paths["noise"] = _save(np.repeat(noise[..., None], 3, axis=2), library / "noise/noise.png")
    main(["index"])
    return paths


def _list(capsys: pytest.CaptureFixture[str], *args: str) -> set[str]:
    capsys.readouterr()
    main(["list", *args])
    return {Path(line).stem for line in capsys.readouterr().out.splitlines()}


def test_list_all_excludes_nsfw(
    indexed: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert _list(capsys) == {"black", "white", "red", "noise"}


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        (["--dark"], {"black"}),
        (["--light"], {"white"}),
        (["--saturated"], {"red"}),
        (["--muted", "--busy"], {"noise"}),
        (["--hue", "red"], {"red"}),
        (["--warm", "--monochrome"], {"red"}),
        (["--purity", "nsfw"], {"private"}),
        (["--purity", "sfw,nsfw", "--dark"], {"black", "private"}),
    ],
)
def test_list_filters(
    indexed: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
    flags: list[str],
    expected: set[str],
) -> None:
    assert _list(capsys, *flags) == expected


def test_list_prints_the_default_file(
    indexed: dict[str, Path], library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _save(np.zeros((18, 32, 3), dtype=np.uint8), library / "black" / "small.png")
    main(["index"])
    assert _list(capsys, "--dark") == {"black"}
    info = library / "black" / "info.yaml"
    data = yaml.safe_load(info.read_text())
    data["default_file"] = "small.png"
    info.write_text(yaml.safe_dump(data))
    main(["index"])
    assert _list(capsys, "--dark") == {"small"}


def test_list_aspect(
    indexed: dict[str, Path],
    library: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    # black: a 64x36 default (16:9), a white 64x27 crop (21:9) and a smaller 21:9 copy.
    black = library / "black"
    _save(np.full((27, 64, 3), 255, dtype=np.uint8), black / "wide.png")
    _save(np.full((18, 42, 3), 255, dtype=np.uint8), black / "wide-small.png")
    main(["index"])
    assert _list(capsys, "--aspect", "16:9", "--dark") == {"black"}
    caplog.clear()
    assert _list(capsys, "--aspect", "21:9", "--light") == {"wide", "white"}
    assert "no file of that aspect ratio for 1 picture" in caplog.text
    # Filtered on the crop's metrics: black's 21:9 file is white.
    with pytest.raises(SystemExit):
        _list(capsys, "--aspect", "21:9", "--dark")


def test_list_random(indexed: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    picked = _list(capsys, "--random", "2")
    assert len(picked) == 2
    assert picked <= {"black", "white", "red", "noise"}
    assert len(_list(capsys, "--random", "99")) == 4


def test_list_no_match_fails(indexed: dict[str, Path]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["list", "--hue", "green"])
    assert exc.value.code == "amontillado: no matching pictures"


def test_list_skips_missing_files(
    indexed: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    indexed["white"].unlink()
    assert _list(capsys) == {"black", "red", "noise"}
    assert "missing from disk: 1 file" in caplog.text


def test_list_excludes_the_current_nsfw_root(
    library: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Indexed while ~/walls was a library root; then the config makes it the NSFW root.
    config = home / ".config/amontillado/config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(f"library_roots: [{home}/walls]\n")
    _record(library / "plain", name="plain.png")
    _record(home / "walls" / "private", name="private.png")
    main(["index"])
    assert _list(capsys) == {"plain", "private"}
    config.write_text(f"nsfw_root: {home}/walls\n")
    assert _list(capsys) == {"plain"}


@pytest.mark.parametrize(
    ("flags", "message"),
    [
        (["--dark", "--light"], "not allowed with argument"),
        (["--purity", "sfw,lewd"], "unknown purity: lewd"),
        (["--random", "0"], "must be at least 1"),
        (["--hue", "teal"], "invalid choice"),
        (["--aspect", "21"], "must be W:H"),
        (["--aspect", "21:0"], "must be W:H"),
    ],
)
def test_list_bad_arguments(
    indexed: dict[str, Path], capsys: pytest.CaptureFixture[str], flags: list[str], message: str
) -> None:
    with pytest.raises(SystemExit):
        main(["list", *flags])
    assert message in capsys.readouterr().err


def test_list_without_an_index(library: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["list"])
    assert "run `amo index` first" in exc.value.code


def _usage(home: Path) -> list[tuple[str, int]]:
    with sqlite3.connect(home / ".local/state/amontillado/index.sqlite") as conn:
        return conn.execute("SELECT id, shown_count FROM usage ORDER BY id").fetchall()


def _id(image: Path) -> str:
    return yaml.safe_load((image.parent / "info.yaml").read_text())["id"]


def test_shown_records_by_record_id(indexed: dict[str, Path], home: Path) -> None:
    black, red = indexed["black"], indexed["red"]
    black_id = _id(black)
    main(["shown", str(black), str(red)])
    main(["shown", black_id[:12], str(black.parent)])
    red_id = _id(red)
    moved = red.rename(home / "elsewhere.png")
    main(["shown", str(moved)])
    assert dict(_usage(home)) == {black_id: 3, red_id: 2}


def test_shown_by_name(indexed: dict[str, Path], home: Path) -> None:
    info = indexed["red"].parent / "info.yaml"
    data = yaml.safe_load(info.read_text())
    data["name"] = "sunset"
    info.write_text(yaml.safe_dump(data))
    main(["index"])
    main(["shown", "sunset"])
    assert _usage(home) == [(data["id"], 1)]


def test_shown_dry_run_records_nothing(indexed: dict[str, Path], home: Path) -> None:
    main(["shown", "--dry-run", str(indexed["black"])])
    assert _usage(home) == []


def test_shown_unknown_picture_records_nothing(indexed: dict[str, Path], home: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["shown", str(indexed["black"]), "nothing"])
    assert exc.value.code == "amontillado: nothing: no such file, and no record has that name or id"
    assert _usage(home) == []


def test_shown_without_an_index(library: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["shown", "x"])
    assert "run `amo index` first" in exc.value.code


def test_usage_survives_reindexing(indexed: dict[str, Path], home: Path) -> None:
    main(["shown", str(indexed["red"])])
    main(["index"])
    assert len(_usage(home)) == 1


def test_add_indexes_and_refuses_duplicates(
    library: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["index"])
    loose = _save(np.zeros((36, 64, 3), dtype=np.uint8), library / "a.png")
    copy = home / "copy.png"
    copy.write_bytes(loose.read_bytes())
    main(["add", "--name", "night", str(loose)])
    assert _index_rows(home) == ["a.png"]
    assert _list(capsys) == {"a"}
    main(["shown", "night"])
    with pytest.raises(SystemExit) as exc:
        main(["add", str(copy)])
    assert exc.value.code == "amontillado: 1 of 1 files could not be added"
    assert copy.exists()
    main(["add", "--force", str(copy)])
    assert sorted(_index_rows(home)) == ["a.png", "copy.png"]
    main(["index", "--check"])


def test_add_refuses_a_taken_name(library: Path, home: Path) -> None:
    main(["add", "--name", "night", str(_save(np.zeros((36, 64, 3), np.uint8), home / "a.png"))])
    other = _save(np.full((36, 64, 3), 9, np.uint8), home / "b.png")
    with pytest.raises(SystemExit):
        main(["add", "--name", "night", str(other)])
    assert other.exists()


def test_add_dry_run_changes_nothing(library: Path, home: Path) -> None:
    loose = _save(np.zeros((36, 64, 3), dtype=np.uint8), library / "a.png")
    main(["add", "--dry-run", str(loose)])
    assert loose.exists()
    assert not (library / "a").exists()
    assert _index_rows(home) == []


def test_add_name_takes_one_file(library: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["add", "--name", "x", "a.png", "b.png"])
    assert exc.value.code == "amontillado: --name takes one FILE"


@pytest.fixture
def web(wallhaven: FakeWeb, monkeypatch: pytest.MonkeyPatch) -> FakeWeb:
    """`amo fetch` talks to the fake Wallhaven, and never sleeps."""
    clock = FakeClock()

    def client(api_key: str | None) -> Client:
        return Client(api_key, get=wallhaven.get, sleep=clock.sleep, clock=clock)

    monkeypatch.setattr("amontillado.cli.Client", client)
    monkeypatch.delenv("WALLHAVEN_API_KEY", raising=False)
    return wallhaven


def test_fetch_prints_and_indexes_what_it_keeps(
    library: Path, web: FakeWeb, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["fetch", "--dark"])
    kept = library / "wallhaven-aaa111" / "wallhaven-aaa111.jpg"
    assert capsys.readouterr().out.splitlines() == [str(kept)]
    assert _list(capsys, "--dark") == {"wallhaven-aaa111"}
    main(["index", "--check"])


def test_fetch_fails_when_short_of_count(library: Path, web: FakeWeb) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["fetch", "--dark", "--count", "3"])
    assert exc.value.code == "amontillado: 1 of 3 wanted"


def test_fetch_dry_run_prints_pages(
    library: Path, web: FakeWeb, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["fetch", "--light", "--dry-run"])
    assert capsys.readouterr().out.splitlines() == ["https://wallhaven.cc/w/bbb222"]
    assert list(library.iterdir()) == []


def test_fetch_passes_wallhaven_filters(library: Path, web: FakeWeb) -> None:
    args = ["--tags", "+night", "--category", "general,people", "--atleast", "2560x1440"]
    args += ["--ratio", "16:9,21x9", "--color", "#42415A", "--dry-run"]
    with pytest.raises(SystemExit):
        main(["fetch", *args])
    query = dict(parse_qsl(urlsplit(web.urls()[0]).query))
    assert query == {
        "sorting": "random",
        "purity": "100",
        "q": "+night",
        "categories": "101",
        "atleast": "2560x1440",
        "ratios": "16x9,21x9",
        # Not a swatch: replaced by the nearest one.
        "colors": "424153",
        "page": "1",
    }


@pytest.mark.parametrize(
    "args",
    [
        ["--ratio", "21/9"],
        ["--atleast", "2560"],
        ["--color", "red"],
        ["--category", "cats"],
        ["--purity", "sfw,lewd"],
        ["--busy-from", "both"],
        ["--dark", "--light"],
    ],
)
def test_fetch_rejects_bad_arguments(args: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        get_cli_arguments(["fetch", *args])
    assert exc.value.code == 2


def test_fetch_nsfw_needs_an_api_key(library: Path, web: FakeWeb) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["fetch", "--purity", "sfw,nsfw"])
    assert "nsfw needs a Wallhaven API key" in str(exc.value.code)
    assert web.requests == []


def test_fetch_nsfw_sends_the_api_key(
    library: Path, web: FakeWeb, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WALLHAVEN_API_KEY", "secret-key")
    main(["fetch", "--purity", "sfw,nsfw"])
    assert all(headers.get("X-API-Key") == "secret-key" for _, headers in web.requests)


def test_fetch_sfw_never_looks_up_the_key(
    library: Path, web: FakeWeb, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WALLHAVEN_API_KEY", "secret-key")
    main(["fetch"])
    assert all("X-API-Key" not in headers for _, headers in web.requests)


def test_fetch_exits_when_the_search_fails(library: Path, web: FakeWeb) -> None:
    web.routes.clear()
    with pytest.raises(SystemExit) as exc:
        main(["fetch"])
    assert str(exc.value.code).startswith("amontillado: https://wallhaven.cc/api/v1/search?")
    assert str(exc.value.code).endswith("HTTP 404")


def test_fetch_keeps_mismatches_without_printing_them(
    library: Path, web: FakeWeb, capsys: pytest.CaptureFixture[str]
) -> None:
    noise = np.random.default_rng(0).integers(0, 256, size=(243, 432, 3), dtype=np.uint8)
    web.add("https://th.wallhaven.cc/lg/aa/aaa111.jpg", _encode(noise))
    with pytest.raises(SystemExit):
        main(["fetch", "--busy", "--max-candidates", "1", "--discard-mismatches"])
    assert list(library.iterdir()) == []
    with pytest.raises(SystemExit) as exc:
        main(["fetch", "--busy", "--max-candidates", "1"])
    assert exc.value.code == "amontillado: 0 of 1 wanted"
    assert capsys.readouterr().out == ""
    assert (library / "wallhaven-aaa111" / "wallhaven-aaa111.jpg").is_file()


def _encode(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, "PNG")
    return buffer.getvalue()


def test_fetch_test_set_prints_buckets_and_fails_when_one_is_empty(
    library: Path, web: FakeWeb, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["fetch", "--test-set"])
    assert exc.value.code == (
        "amontillado: empty buckets: muted, saturated, busy, sparse, monochrome, multi-hue"
    )
    assert capsys.readouterr().out.splitlines() == [
        f"dark\t{library / 'wallhaven-aaa111' / 'wallhaven-aaa111.jpg'}",
        f"light\t{library / 'wallhaven-bbb222' / 'wallhaven-bbb222.png'}",
    ]


def test_fetch_test_set_dry_run_prints_pages(
    library: Path, web: FakeWeb, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        main(["fetch", "--test-set", "--dry-run"])
    assert capsys.readouterr().out.splitlines() == [
        "dark\thttps://wallhaven.cc/w/aaa111",
        "light\thttps://wallhaven.cc/w/bbb222",
    ]


@pytest.mark.parametrize("args", [["--dark"], ["--hue", "red"], ["--count", "2"]])
def test_fetch_test_set_takes_no_look_filters_or_count(
    library: Path, web: FakeWeb, args: list[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["fetch", "--test-set", *args])
    assert exc.value.code == "amontillado: --test-set takes no look filters or --count"
    assert web.requests == []
