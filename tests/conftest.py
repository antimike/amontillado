from __future__ import annotations

import io
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import numpy as np
import pytest
from PIL import Image

from amontillado.config import Config
from amontillado.wallhaven import Response

SaveImage = Callable[..., Path]


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """HOME at tmp_path, XDG variables unset: load_config() sees only this tree."""
    monkeypatch.setenv("HOME", str(tmp_path))
    for variable in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(variable, raising=False)
    return tmp_path


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """A library root, an NSFW root and an index, all under tmp_path."""
    (tmp_path / "library").mkdir()
    (tmp_path / "nsfw").mkdir()
    return Config(
        library_roots=(tmp_path / "library",),
        nsfw_root=tmp_path / "nsfw",
        index_path=tmp_path / "state" / "index.sqlite",
    )


def mark_record(directory: Path) -> Path:
    """Make `directory` a record with an empty info.yaml, as by hand; returns that file."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "info.yaml"
    path.write_text("")
    return path


@pytest.fixture
def save_image() -> SaveImage:
    """Write a solid-colour image: save_image(path, rgb=(0, 0, 0), size=(64, 36))."""

    def save(
        path: Path, rgb: tuple[int, int, int] = (0, 0, 0), size: tuple[int, int] = (64, 36)
    ) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(np.full((size[1], size[0], 3), rgb, dtype=np.uint8)).save(path)
        return path

    return save


FIXTURES = Path(__file__).parent / "fixtures"


def fixture_json(name: str) -> object:
    """A recorded (trimmed) response from tests/fixtures."""
    return json.loads((FIXTURES / name).read_text())


def _canonical(url: str) -> str:
    """`url` with its query parameters sorted, so that routes match in any order."""
    parts = urlsplit(url)
    query = urlencode(sorted(parse_qsl(parts.query)))
    return urlunsplit(parts._replace(query=query))


class FakeWeb:
    """A stub for wallhaven.http_get: serves added routes, records each request, and answers
    404 to anything else. A route given several responses serves them in turn, then repeats
    the last."""

    def __init__(self) -> None:
        self.routes: dict[str, list[Response]] = {}
        self.requests: list[tuple[str, dict[str, str]]] = []

    def add(self, url: str, *responses: object) -> None:
        """Serve `responses` at `url`: bytes as they are, a Response as it is, anything else
        as JSON."""
        self.routes[_canonical(url)] = [
            r if isinstance(r, Response) else Response(200, {}, _body(r)) for r in responses
        ]

    def get(self, url: str, headers: Mapping[str, str]) -> Response:
        self.requests.append((url, dict(headers)))
        responses = self.routes.get(_canonical(url))
        if not responses:
            return Response(404, {}, b"")
        return responses.pop(0) if len(responses) > 1 else responses[0]

    def urls(self) -> list[str]:
        return [url for url, _ in self.requests]


def _body(value: object) -> bytes:
    return value if isinstance(value, bytes) else json.dumps(value).encode()


def image_bytes(
    rgb: tuple[int, int, int] = (0, 0, 0), size: tuple[int, int] = (64, 36), fmt: str = "PNG"
) -> bytes:
    """A solid-colour image, encoded."""
    buffer = io.BytesIO()
    Image.fromarray(np.full((size[1], size[0], 3), rgb, dtype=np.uint8)).save(buffer, fmt)
    return buffer.getvalue()


class FakeClock:
    """A clock that only moves when slept on; `sleeps` records each sleep."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
