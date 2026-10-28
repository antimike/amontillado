"""The Wallhaven API: search, a wallpaper's tags, and downloads.

docs/design.md, "Fetcher (Wallhaven)". All HTTP goes through `http_get`, one small function that
tests replace with a stub. API calls are paced to stay under Wallhaven's limit of 45 a minute;
an HTTP 429 from any host is retried after a back-off. The API key travels in a header, never
in a URL, so URLs can be logged.
"""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from logging import getLogger
from urllib.parse import urlencode

from amontillado import __version__

logger = getLogger(__name__)

API = "https://wallhaven.cc/api/v1"
USER_AGENT = f"amontillado/{__version__} (+https://github.com/antimike/amontillado)"
PURITY_FLAGS = ("sfw", "sketchy", "nsfw")
CATEGORY_FLAGS = ("general", "anime", "people")
# 40 a minute: a margin under the limit of 45 for clocks that disagree.
API_INTERVAL = 1.5
# Back-off after an HTTP 429 without Retry-After: 10 s, doubling, at most RETRIES times.
BACKOFF = 10.0
RETRIES = 5
TIMEOUT = 60.0
_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png"}


class WallhavenError(Exception):
    """A request failed, or Wallhaven answered with something unusable; the message says why."""


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]
    body: bytes


def http_get(url: str, headers: Mapping[str, str]) -> Response:
    """GET `url`. Any HTTP status is a Response; a network failure raises WallhavenError."""
    request = urllib.request.Request(url, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return Response(response.status, dict(response.headers), response.read())
    except urllib.error.HTTPError as exc:
        with exc:
            return Response(exc.code, dict(exc.headers), exc.read())
    except (OSError, http.client.HTTPException) as exc:
        raise WallhavenError(f"{url}: {exc}") from exc


@dataclass(frozen=True)
class Search:
    """Wallhaven's server-side filters; None leaves a filter to Wallhaven's default."""

    query: str | None = None
    purity: frozenset[str] = frozenset({"sfw"})
    categories: frozenset[str] | None = None
    atleast: str | None = None
    ratios: tuple[str, ...] | None = None
    color: str | None = None

    def params(self) -> dict[str, str]:
        """The search parameters, random order."""
        params = {"sorting": "random", "purity": _flags(PURITY_FLAGS, self.purity)}
        if self.query:
            params["q"] = self.query
        if self.categories is not None:
            params["categories"] = _flags(CATEGORY_FLAGS, self.categories)
        if self.atleast:
            params["atleast"] = self.atleast
        if self.ratios:
            params["ratios"] = ",".join(self.ratios)
        if self.color:
            params["colors"] = self.color
        return params


def _flags(names: tuple[str, ...], chosen: frozenset[str]) -> str:
    return "".join("1" if name in chosen else "0" for name in names)


@dataclass(frozen=True)
class Wallpaper:
    """One search result."""

    id: str
    url: str
    image_url: str
    file_type: str
    width: int
    height: int
    purity: str
    category: str
    colors: tuple[str, ...]
    source: str
    uploaded: datetime | None
    thumbnail: str

    @classmethod
    def from_api(cls, data: object) -> Wallpaper:
        """A wallpaper from a search result; WallhavenError if a field is missing or wrong."""
        try:
            if not isinstance(data, dict):
                raise TypeError(f"{data!r} is not an object")
            wallpaper = cls(
                id=_str(data["id"]),
                url=_str(data["url"]),
                image_url=_str(data["path"]),
                file_type=_str(data["file_type"]),
                width=int(data["dimension_x"]),
                height=int(data["dimension_y"]),
                purity=_str(data["purity"]),
                category=_str(data["category"]),
                colors=tuple(_str(color) for color in data.get("colors") or ()),
                source=_str(data.get("source") or ""),
                uploaded=_timestamp(data.get("created_at")),
                thumbnail=_str(data["thumbs"]["large"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise WallhavenError(f"unusable search result: {exc!r}") from exc
        if wallpaper.purity not in PURITY_FLAGS:
            raise WallhavenError(f"{wallpaper.id}: unknown purity {wallpaper.purity!r}")
        if wallpaper.file_type not in _EXTENSIONS:
            raise WallhavenError(f"{wallpaper.id}: unknown file type {wallpaper.file_type!r}")
        return wallpaper

    @property
    def file_name(self) -> str:
        """`wallhaven-<id>.<ext>`, the name of the file as served."""
        return f"wallhaven-{self.id}{_EXTENSIONS[self.file_type]}"


def _str(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{value!r} is not a string")
    return value


def _timestamp(value: object) -> datetime | None:
    # "2015-10-06 22:09:58", in no stated time zone: kept naive.
    return datetime.fromisoformat(value) if isinstance(value, str) and value else None


class Client:
    """Wallhaven over HTTP. `get`, `sleep` and `clock` are replaceable for tests."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        get: Callable[[str, Mapping[str, str]], Response] = http_get,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api_key = api_key
        self._get = get
        self._sleep = sleep
        self._clock = clock
        self._next_api_call = 0.0

    def search(self, search: Search) -> Iterator[Wallpaper]:
        """Every result of a search, page by page. Results that cannot be used are logged
        and left out. The seed of the first page keeps the random order stable."""
        params = search.params()
        page = 1
        while True:
            data = self._api("/search", {**params, "page": str(page)})
            meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
            results = data.get("data")
            if not isinstance(results, list):
                raise WallhavenError("search: no data in the response")
            for result in results:
                try:
                    yield Wallpaper.from_api(result)
                except WallhavenError as exc:
                    logger.warning("%s", exc)
            last_page = meta.get("last_page")
            if not results or not isinstance(last_page, int) or page >= last_page:
                return
            if isinstance(meta.get("seed"), str):
                params["seed"] = meta["seed"]
            page += 1

    def tags(self, wallpaper_id: str) -> list[str]:
        """The tag names of a wallpaper (one more API call)."""
        data = self._api(f"/w/{wallpaper_id}", {}).get("data")
        tags = data.get("tags") if isinstance(data, dict) else None
        if not isinstance(tags, list):
            raise WallhavenError(f"{wallpaper_id}: no tags in the response")
        return [tag["name"] for tag in tags if isinstance(tag, dict) and "name" in tag]

    def download(self, url: str) -> bytes:
        """The bytes at `url` (a thumbnail or an image; not paced, not an API call)."""
        return self._request(url)

    def _api(self, path: str, params: Mapping[str, str]) -> dict[str, object]:
        url = f"{API}{path}" + (f"?{urlencode(params)}" if params else "")
        wait = self._next_api_call - self._clock()
        if wait > 0:
            self._sleep(wait)
        try:
            body = self._request(url)
        finally:
            self._next_api_call = self._clock() + API_INTERVAL
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise WallhavenError(f"{url}: not JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise WallhavenError(f"{url}: not a JSON object")
        return data

    def _request(self, url: str) -> bytes:
        headers = {"User-Agent": USER_AGENT}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        for attempt in range(RETRIES + 1):
            logger.debug("GET %s", url)
            response = self._get(url, headers)
            if response.status == 200:
                return response.body
            if response.status != 429 or attempt == RETRIES:
                break
            delay = _retry_after(response.headers) or BACKOFF * 2**attempt
            logger.warning("rate limited by Wallhaven; retrying in %.0f s", delay)
            self._sleep(delay)
        if response.status == 401:
            raise WallhavenError(f"{url}: HTTP 401; check the API key")
        raise WallhavenError(f"{url}: HTTP {response.status}")


def _retry_after(headers: Mapping[str, str]) -> float | None:
    value = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
    try:
        return max(0.0, float(value)) if value is not None else None
    except ValueError:
        return None
