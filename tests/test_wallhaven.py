from __future__ import annotations

from datetime import datetime

import pytest
from conftest import FakeClock, FakeWeb, fixture_json

from amontillado.wallhaven import (
    API,
    API_INTERVAL,
    SWATCHES,
    Client,
    Response,
    Search,
    WallhavenError,
    Wallpaper,
    nearest_swatch,
)

PAGE_1 = f"{API}/search?sorting=random&purity=100&page=1"
PAGE_2 = f"{API}/search?sorting=random&purity=100&page=2&seed=XyZ987"


@pytest.fixture
def web() -> FakeWeb:
    return FakeWeb()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def _client(web: FakeWeb, clock: FakeClock, api_key: str | None = None) -> Client:
    return Client(api_key, get=web.get, sleep=clock.sleep, clock=clock)


def test_search_params() -> None:
    search = Search(
        query="+landscape -anime",
        purity=frozenset({"sfw", "nsfw"}),
        categories=frozenset({"general", "people"}),
        atleast="2560x1440",
        ratios=("16x9", "21x9"),
        color="424153",
    )
    assert search.params() == {
        "sorting": "random",
        "purity": "101",
        "q": "+landscape -anime",
        "categories": "101",
        "atleast": "2560x1440",
        "ratios": "16x9,21x9",
        "colors": "424153",
    }
    assert Search().params() == {"sorting": "random", "purity": "100"}


def test_search_pages_through_with_the_seed(web: FakeWeb, clock: FakeClock) -> None:
    web.add(PAGE_1, fixture_json("wallhaven-search-1.json"))
    web.add(PAGE_2, fixture_json("wallhaven-search-2.json"))
    results = list(_client(web, clock).search(Search()))
    assert [w.id for w in results] == ["aaa111", "bbb222", "ccc333"]
    assert len(web.requests) == 2
    first = results[0]
    assert first.file_name == "wallhaven-aaa111.jpg"
    assert results[1].file_name == "wallhaven-bbb222.png"
    assert first.uploaded == datetime(2024, 6, 2, 21, 53, 31)
    assert first.thumbnail == "https://th.wallhaven.cc/lg/aa/aaa111.jpg"
    assert first.colors == ("#000000", "#424153")
    assert results[2].purity == "sketchy"


def test_search_skips_unusable_results(
    web: FakeWeb, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    page = fixture_json("wallhaven-search-2.json")
    assert isinstance(page, dict)
    good = page["data"][0]
    page["data"] = [{"id": "broken"}, {**good, "file_type": "image/gif"}, good]
    page["meta"] = {"last_page": 1}
    web.add(PAGE_1, page)
    assert [w.id for w in _client(web, clock).search(Search())] == ["ccc333"]
    assert "unusable search result" in caplog.text
    assert "unknown file type 'image/gif'" in caplog.text


def test_search_stops_at_an_empty_page(web: FakeWeb, clock: FakeClock) -> None:
    web.add(PAGE_1, {"data": [], "meta": {"last_page": 5}})
    assert list(_client(web, clock).search(Search())) == []
    assert len(web.requests) == 1


def test_api_calls_are_paced(web: FakeWeb, clock: FakeClock) -> None:
    web.add(PAGE_1, fixture_json("wallhaven-search-1.json"))
    web.add(PAGE_2, fixture_json("wallhaven-search-2.json"))
    web.add(f"{API}/w/aaa111", fixture_json("wallhaven-w.json"))
    client = _client(web, clock)
    list(client.search(Search()))
    client.tags("aaa111")
    assert clock.sleeps == [API_INTERVAL, API_INTERVAL]


def test_downloads_are_not_paced(web: FakeWeb, clock: FakeClock) -> None:
    web.add("https://th.wallhaven.cc/lg/aa/aaa111.jpg", b"thumb")
    client = _client(web, clock)
    assert client.download("https://th.wallhaven.cc/lg/aa/aaa111.jpg") == b"thumb"
    assert client.download("https://th.wallhaven.cc/lg/aa/aaa111.jpg") == b"thumb"
    assert clock.sleeps == []


def test_tags(web: FakeWeb, clock: FakeClock) -> None:
    web.add(f"{API}/w/aaa111", fixture_json("wallhaven-w.json"))
    assert _client(web, clock).tags("aaa111") == ["landscape", "night"]


def test_backs_off_on_429(web: FakeWeb, clock: FakeClock) -> None:
    limited = Response(429, {}, b"")
    web.add(PAGE_1, Response(429, {"Retry-After": "7"}, b""), limited, limited, {"data": []})
    assert list(_client(web, clock).search(Search())) == []
    assert clock.sleeps == [7.0, 20.0, 40.0]


def test_gives_up_after_retries(web: FakeWeb, clock: FakeClock) -> None:
    web.add(PAGE_1, Response(429, {}, b""))
    with pytest.raises(WallhavenError, match="HTTP 429"):
        list(_client(web, clock).search(Search()))
    assert len(clock.sleeps) == 5


def test_http_errors(web: FakeWeb, clock: FakeClock) -> None:
    web.add(PAGE_1, Response(401, {}, b""))
    with pytest.raises(WallhavenError, match="check the API key"):
        list(_client(web, clock).search(Search()))
    with pytest.raises(WallhavenError, match="HTTP 404"):
        _client(web, clock).download("https://w.wallhaven.cc/full/xx/nothing.jpg")
    web.add(PAGE_1, b"<html>")
    with pytest.raises(WallhavenError, match="not JSON"):
        list(_client(web, clock).search(Search()))


def test_api_key_goes_in_a_header(web: FakeWeb, clock: FakeClock) -> None:
    web.add(PAGE_1, {"data": []})
    list(_client(web, clock, api_key="secret-key").search(Search()))
    url, headers = web.requests[0]
    assert headers["X-API-Key"] == "secret-key"
    assert "secret-key" not in url
    assert headers["User-Agent"].startswith("amontillado/")
    list(_client(web, clock).search(Search()))
    assert "X-API-Key" not in web.requests[1][1]


def test_wallpaper_from_api_rejects_unknown_purity() -> None:
    page = fixture_json("wallhaven-search-1.json")
    assert isinstance(page, dict)
    with pytest.raises(WallhavenError, match="unknown purity"):
        Wallpaper.from_api({**page["data"][0], "purity": "nsfl"})


@pytest.mark.parametrize(
    ("color", "swatch"),
    [
        ("424153", "424153"),
        ("010101", "000000"),
        ("fefefe", "ffffff"),
        ("cd0203", "cc0000"),
        ("0068ce", "0066cc"),
        ("3a3a4a", "424153"),
    ],
)
def test_nearest_swatch(color: str, swatch: str) -> None:
    assert nearest_swatch(color) == swatch
    assert swatch in SWATCHES
