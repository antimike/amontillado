from __future__ import annotations

import io
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import numpy as np
import pytest
import yaml
from conftest import FakeClock, FakeWeb, image_bytes
from PIL import Image

from amontillado.classes import Look
from amontillado.config import Config
from amontillado.fetch import FetchReport, Options, fetch
from amontillado.index import add, connect, files
from amontillado.library import add_picture, place
from amontillado.wallhaven import API, Client, Response, Search

NOISE = np.random.default_rng(0).integers(0, 256, size=(72, 128), dtype=np.uint8)
NOISE_RGB = np.repeat(NOISE[..., None], 3, axis=2)


@pytest.fixture
def web(wallhaven: FakeWeb) -> FakeWeb:
    return wallhaven


@pytest.fixture
def conn(config: Config) -> Iterator[sqlite3.Connection]:
    with closing(connect(config.index_path)) as conn:
        yield conn


def _fetch(
    config: Config,
    conn: sqlite3.Connection,
    web: FakeWeb,
    look: Look | None = None,
    search: Search | None = None,
    **options: object,
) -> FetchReport:
    client = Client(get=web.get, sleep=FakeClock().sleep, clock=FakeClock())
    return fetch(config, conn, client, search or Search(), look or Look(), Options(**options))  # type: ignore[arg-type]


def _leftovers(root: Path) -> list[str]:
    return sorted(path.name for path in root.rglob(".*"))


def test_keeps_a_matching_wallpaper_as_a_record(
    config: Config, conn: sqlite3.Connection, web: FakeWeb
) -> None:
    report = _fetch(config, conn, web, Look(("dark",)))
    directory = config.library_roots[0] / "wallhaven-aaa111"
    assert report.kept == [directory / "wallhaven-aaa111.jpg"]
    assert (report.examined, report.rejected, report.failed) == (1, 0, [])
    info = yaml.safe_load((directory / "info.yaml").read_text())
    assert info["source"]["id"] == "aaa111"
    assert info["source"]["tags"] == ["tag-aaa111"]
    assert info["source"]["purity"] == "sfw"
    assert info["fetched"] is not None
    entry = info["files"]["wallhaven-aaa111.jpg"]
    assert (entry["width"], entry["height"]) == (128, 72)
    assert entry["metrics"]["lightness"] < 0.1
    assert [row.path for row in files(conn)] == report.kept
    # One search page, one thumbnail, the image, its tags: nothing for the others.
    assert len(web.requests) == 4


def test_look_filters_on_the_thumbnail(
    config: Config, conn: sqlite3.Connection, web: FakeWeb
) -> None:
    report = _fetch(config, conn, web, Look(("light",)))
    assert [path.name for path in report.kept] == ["wallhaven-bbb222.png"]
    assert report.rejected == 1
    assert "https://w.wallhaven.cc/full/aa/wallhaven-aaa111.jpg" not in web.urls()


def test_skips_wallpapers_in_the_index(
    config: Config, conn: sqlite3.Connection, web: FakeWeb
) -> None:
    _fetch(config, conn, web, Look(("dark",)))
    report = _fetch(config, conn, web, Look(("dark",)))
    assert report.kept == []
    assert report.known == 1
    # ccc333 is dark too, but sketchy: an sfw search never keeps it.
    assert report.examined == 1


def test_non_sfw_goes_to_the_nsfw_root(
    config: Config, conn: sqlite3.Connection, web: FakeWeb
) -> None:
    search = Search(purity=frozenset({"sfw", "sketchy"}))
    report = _fetch(config, conn, web, search=search, count=3)
    assert [path.parent.parent for path in report.kept] == [
        config.library_roots[0],
        config.library_roots[0],
        config.nsfw_root,
    ]
    rows = {row.path.name: row for row in files(conn)}
    assert rows["wallhaven-ccc333.jpg"].nsfw_root
    assert rows["wallhaven-ccc333.jpg"].purity == "sketchy"


def test_stops_at_max_candidates(config: Config, conn: sqlite3.Connection, web: FakeWeb) -> None:
    report = _fetch(config, conn, web, Look(("light",)), count=5, max_candidates=1)
    assert (report.examined, report.rejected, report.kept) == (1, 1, [])


def test_dry_run_downloads_thumbnails_only(
    config: Config, conn: sqlite3.Connection, web: FakeWeb
) -> None:
    report = _fetch(config, conn, web, count=2, dry_run=True)
    assert [w.id for w in report.would_keep] == ["aaa111", "bbb222"]
    assert report.kept == []
    assert not any("/full/" in url or "/w/" in url for url in web.urls())
    assert list(config.library_roots[0].iterdir()) == []
    assert files(conn) == []


@pytest.mark.parametrize(("busy_from", "kept"), [("thumb", 0), ("full", 1)])
def test_busy_from(
    config: Config, conn: sqlite3.Connection, web: FakeWeb, busy_from: str, kept: int
) -> None:
    # A smooth thumbnail of a busy full image: only --busy-from full looks past it.
    web.add("https://w.wallhaven.cc/full/aa/wallhaven-aaa111.jpg", _encode(NOISE_RGB, "JPEG"))
    report = _fetch(config, conn, web, Look(("busy",)), busy_from=busy_from, max_candidates=1)
    assert len(report.kept) == kept
    assert report.rejected == 1 - kept
    assert report.mismatched == []


@pytest.fixture
def borderline(web: FakeWeb) -> FakeWeb:
    """aaa111's thumbnail is busy; its full image is not."""
    web.add("https://th.wallhaven.cc/lg/aa/aaa111.jpg", _encode(NOISE_RGB))
    return web


def test_a_mismatch_on_the_full_image_is_kept_but_not_counted(
    config: Config, conn: sqlite3.Connection, borderline: FakeWeb
) -> None:
    report = _fetch(config, conn, borderline, Look(("busy",)), max_candidates=1)
    path = config.library_roots[0] / "wallhaven-aaa111" / "wallhaven-aaa111.jpg"
    assert report.kept == []
    assert report.mismatched == [path]
    assert report.count == 0
    assert [row.path for row in files(conn)] == [path]


def test_discard_mismatches(config: Config, conn: sqlite3.Connection, borderline: FakeWeb) -> None:
    report = _fetch(
        config, conn, borderline, Look(("busy",)), max_candidates=1, discard_mismatches=True
    )
    assert (report.kept, report.mismatched, report.discarded) == ([], [], 1)
    assert list(config.library_roots[0].iterdir()) == []
    assert files(conn) == []


def _encode(array: np.ndarray, fmt: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, fmt)
    return buffer.getvalue()


def test_a_failure_leaves_nothing_behind(
    config: Config, conn: sqlite3.Connection, web: FakeWeb
) -> None:
    web.add(f"{API}/w/aaa111", Response(500, {}, b""))
    report = _fetch(config, conn, web, Look(("dark",)), max_candidates=1)
    assert report.kept == []
    assert report.failed == [("aaa111", f"{API}/w/aaa111: HTTP 500")]
    assert list(config.library_roots[0].iterdir()) == []


def test_a_bad_thumbnail_is_passed_over(
    config: Config, conn: sqlite3.Connection, web: FakeWeb
) -> None:
    web.add("https://th.wallhaven.cc/lg/aa/aaa111.jpg", b"not an image")
    report = _fetch(config, conn, web)
    assert [w for w, _ in report.failed] == ["aaa111"]
    assert [path.name for path in report.kept] == ["wallhaven-bbb222.png"]


def test_refuses_content_already_in_the_library(
    config: Config, conn: sqlite3.Connection, web: FakeWeb, tmp_path: Path
) -> None:
    copy = tmp_path / "copy.jpg"
    copy.write_bytes(web.routes["https://w.wallhaven.cc/full/aa/wallhaven-aaa111.jpg"][0].body)
    add(conn, add_picture(config, place(config, copy, name=None, nsfw=False), name=None))
    report = _fetch(config, conn, web, Look(("dark",)), max_candidates=1)
    assert report.kept == []
    assert "same content as" in report.failed[0][1]
    assert not (config.library_roots[0] / "wallhaven-aaa111").exists()
    assert _leftovers(config.library_roots[0]) == []


def test_refuses_an_existing_directory(
    config: Config, conn: sqlite3.Connection, web: FakeWeb
) -> None:
    (config.library_roots[0] / "wallhaven-aaa111").mkdir()
    report = _fetch(config, conn, web, Look(("dark",)), max_candidates=1)
    assert "already exists" in report.failed[0][1]
    assert list((config.library_roots[0] / "wallhaven-aaa111").iterdir()) == []


def test_a_failure_after_the_move_leaves_nothing_behind(
    config: Config, conn: sqlite3.Connection, web: FakeWeb, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(path: Path, record: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("amontillado.fetch.write_record", fail)
    report = _fetch(config, conn, web, Look(("dark",)), max_candidates=1)
    assert report.failed == [("aaa111", "disk full")]
    assert list(config.library_roots[0].iterdir()) == []


def test_skips_wallhaven_ids_on_disk_but_not_indexed(
    config: Config, conn: sqlite3.Connection, web: FakeWeb, caplog: pytest.LogCaptureFixture
) -> None:
    # As a record synced in from another machine, before `amo index`.
    record = config.nsfw_root / "elsewhere" / "synced"
    record.mkdir(parents=True)
    (record / "info.yaml").write_text("source: {site: wallhaven, id: aaa111}\n")
    broken = config.library_roots[0] / "broken"
    broken.mkdir()
    (broken / "info.yaml").write_text("source: [\n")
    report = _fetch(config, conn, web, Look(("dark",)))
    assert report.known == 1
    assert report.kept == []
    assert "https://th.wallhaven.cc/lg/aa/aaa111.jpg" not in web.urls()
    assert "not in the index (passed over anyway; run `amo index`): 1" in caplog.text


def test_test_set_fills_one_bucket_per_image(
    config: Config, conn: sqlite3.Connection, web: FakeWeb
) -> None:
    # Black is dark, muted and sparse, but fills dark only; white then fills light.
    report = _fetch(config, conn, web, test_set=True)
    root = config.library_roots[0]
    assert report.buckets == {
        "dark": root / "wallhaven-aaa111" / "wallhaven-aaa111.jpg",
        "light": root / "wallhaven-bbb222" / "wallhaven-bbb222.png",
    }
    assert report.kept == list(report.buckets.values())


def test_test_set_buckets_by_the_full_image(
    config: Config, conn: sqlite3.Connection, web: FakeWeb
) -> None:
    # aaa111's thumbnail is black but its full image white: it fills light, not dark, and
    # bbb222 (white too) the next bucket open to it.
    web.add(
        "https://w.wallhaven.cc/full/aa/wallhaven-aaa111.jpg",
        image_bytes((255, 255, 255), (128, 72), "JPEG"),
    )
    report = _fetch(config, conn, web, test_set=True)
    assert {name: path.name for name, path in report.buckets.items()} == {
        "light": "wallhaven-aaa111.jpg",
        "muted": "wallhaven-bbb222.png",
    }


def test_test_set_dry_run_cannot_fill_buckets_judged_on_the_full_image(
    config: Config, conn: sqlite3.Connection, web: FakeWeb, caplog: pytest.LogCaptureFixture
) -> None:
    # Black and white, each muted and sparse: with --busy-from full, sparse is never filled.
    report = _fetch(config, conn, web, test_set=True, dry_run=True, busy_from="full")
    assert {name: w.id for name, w in report.buckets.items()} == {
        "dark": "aaa111",
        "light": "bbb222",
    }
    assert "busy and sparse are not judged" in caplog.text


def test_test_set_takes_no_look_filters(
    config: Config, conn: sqlite3.Connection, web: FakeWeb
) -> None:
    with pytest.raises(ValueError, match="no look filters"):
        _fetch(config, conn, web, Look(("dark",)), test_set=True)
