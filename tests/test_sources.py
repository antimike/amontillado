from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml

from amontillado.cli import main
from amontillado.config import AppConfig, Config, ThemeConfig
from amontillado.palette import Palette, complete_variant, dump_palette
from amontillado.registry import RegistryError, cached_path, find
from amontillado.sources import check, needed, resolve, sync, text
from amontillado.theme import ThemeError, render_app
from amontillado.wallhaven import Response

TEMPLATE = b"bg #{{base00-hex}} accent #{{accent-hex}}\n"
SHA = hashlib.sha256(TEMPLATE).hexdigest()
URL = "https://example.org/t.mustache"
BASE16 = {f"base{i:02X}": f"#{i * 16:02x}{i * 16:02x}{i * 16:02x}" for i in range(16)}


def _config(**apps: AppConfig) -> Config:
    return Config((Path("l"),), Path("n"), Path("i"), theme=ThemeConfig(apps=apps))


class Server:
    """A stub `get`: serves `files` by URL and records each request."""

    def __init__(self, files: Mapping[str, bytes]) -> None:
        self.files = dict(files)
        self.requests: list[str] = []

    def __call__(self, url: str, headers: Mapping[str, str]) -> Response:
        self.requests.append(url)
        if url not in self.files:
            return Response(404, {}, b"")
        return Response(200, {}, self.files[url])


def test_resolve_defaults() -> None:
    kitty = resolve("kitty", AppConfig())
    assert (kitty.source, kitty.name, kitty.output, kitty.fetched) == (
        "builtin",
        "kitty",
        "kitty.conf",
        False,
    )
    waybar = resolve("waybar", AppConfig(source="builtin", template="gtk", output="w.css"))
    assert (waybar.name, waybar.output) == ("gtk", "w.css")
    rofi = resolve("rofi", AppConfig(source="tinted"))
    entry = find("tinted", "rofi")
    assert (rofi.format, rofi.url, rofi.sha256, rofi.commit) == (
        "mustache",
        entry.url,
        entry.sha256,
        entry.commit,
    )
    assert resolve("zed", AppConfig()).source == "matugen-themes"


def test_resolve_errors() -> None:
    with pytest.raises(RegistryError, match=r"theme\.apps\.mytool: no source has a template"):
        resolve("mytool", AppConfig())
    with pytest.raises(RegistryError, match=r"theme\.apps\.rofi\.format: tinted templates are"):
        resolve("rofi", AppConfig(source="tinted", format="pywal"))


def test_url_template(home: Path) -> None:
    app = AppConfig(source="url", url=URL, sha256=SHA, format="mustache", output="t.conf")
    template = resolve("mine", app)
    assert (template.source, template.url, template.output) == ("url", URL, "t.conf")
    with pytest.raises(RegistryError, match=r"not synced \(run amo theme sync\)"):
        text(template)
    assert sync([template], Server({URL: TEMPLATE}), {}) == []
    assert text(template) == TEMPLATE.decode()


def test_sync_keeps_only_matching_files(home: Path) -> None:
    good = resolve("a", AppConfig(source="url", url=URL, sha256=SHA, format="mustache", output="a"))
    other = "https://example.org/other"
    bad = resolve(
        "b", AppConfig(source="url", url=other, sha256="0" * 64, format="mustache", output="b")
    )
    gone = resolve(
        "c",
        AppConfig(source="url", url=URL + "x", sha256="1" * 64, format="mustache", output="c"),
    )
    server = Server({URL: TEMPLATE, other: b"tampered"})
    problems = sync([good, bad, gone], server, {})
    assert problems == [
        f"{other}: sha256 is {hashlib.sha256(b'tampered').hexdigest()}, expected {'0' * 64}",
        f"{URL}x: HTTP 404",
    ]
    assert cached_path(SHA).read_bytes() == TEMPLATE
    assert not cached_path("0" * 64).exists()
    assert not list(cached_path(SHA).parent.glob(".sync-*"))
    # A kept file is not fetched again; one changed on disk is.
    sync([good], server, {})
    assert server.requests.count(URL) == 1
    cached_path(SHA).write_bytes(b"changed")
    assert check([good]) == [
        f"{URL}: {cached_path(SHA)} does not match its hash (run amo theme sync)"
    ]
    sync([good], server, {})
    assert server.requests.count(URL) == 2
    assert check([good]) == []


def test_needed_lists_each_fetched_file_once() -> None:
    config = _config(
        kitty=AppConfig(),
        rofi=AppConfig(source="tinted"),
        rofi2=AppConfig(source="tinted", template="rofi", output="r2.rasi"),
        zed=AppConfig(source="matugen-themes"),
    )
    assert [(t.app, t.source) for t in needed(config)] == [
        ("rofi", "tinted"),
        ("zed", "matugen-themes"),
    ]


def test_apply_renders_a_synced_tinted_template(home: Path) -> None:
    palette = Palette("p", {"dark": complete_variant("dark", BASE16)}, {})
    app = AppConfig(source="tinted")
    with pytest.raises(ThemeError, match=r"tinted rofi\): not synced \(run amo theme sync\)"):
        render_app("rofi", app, palette, "dark")
    entry = find("tinted", "rofi")
    # The real file is not fetched in tests: a stand-in kept under the pinned hash.
    cached_path(entry.sha256).parent.mkdir(parents=True)
    cached_path(entry.sha256).write_bytes(TEMPLATE)
    with pytest.raises(ThemeError, match="does not match its hash"):
        render_app("rofi", app, palette, "dark")
    # matugen-themes templates render too, once synced.
    with pytest.raises(ThemeError, match=r"matugen-themes kitty\): not synced"):
        render_app("kitty", AppConfig(source="matugen-themes"), palette, "dark")


def test_apply_records_the_pin(home: Path) -> None:
    palette = Palette("p", {"dark": complete_variant("dark", BASE16)}, {})
    app = AppConfig(source="url", url=URL, sha256=SHA, format="mustache", output="t.conf")
    sync([resolve("mine", app)], Server({URL: TEMPLATE}), {})
    rendered = render_app("mine", app, palette, "dark")
    assert rendered.text.startswith("bg #000000 accent #")
    assert rendered.record["sha256"] == SHA
    tinted = resolve("rofi", AppConfig(source="tinted"))
    assert tinted.commit == find("tinted", "rofi").commit


def _write_config(home: Path, apps: dict) -> None:
    path = home / ".config" / "amontillado" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"theme": {"apps": apps}}))


def test_cli_sync(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    app = {"source": "url", "url": URL, "sha256": SHA, "format": "mustache", "output": "t"}
    _write_config(home, {"mine": app, "kitty": {}})
    with pytest.raises(SystemExit) as exc:
        main(["theme", "sync", "--check"])
    assert exc.value.code == "amontillado: 1 template not synced"
    server = Server({URL: TEMPLATE})
    monkeypatch.setattr("amontillado.cli.http_get", server)
    main(["theme", "sync"])
    main(["theme", "sync", "--check"])
    assert server.requests == [URL]
    palette = home / "p.yaml"
    palette.write_text(dump_palette(Palette("p", {"dark": complete_variant("dark", BASE16)}, {})))
    main(["theme", "apply", "--palette", str(palette), "--no-reload"])
    assert (home / ".cache" / "theme" / "current" / "t").read_text().startswith("bg #000000")


def test_cli_templates(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["theme", "templates"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split()[:4] == ["kitty", "builtin", "variables", "kitty.conf"]
    assert any(line.split()[:3] == ["zed", "matugen-themes", "complete"] for line in lines)
    main(["theme", "templates", "rofi"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split()[:2] == ["rofi", "builtin"]
    assert "    base00-hex" in lines
    assert "    (not synced: amo theme sync)" in lines
    with pytest.raises(SystemExit) as exc:
        main(["theme", "templates", "nope"])
    assert exc.value.code == "amontillado: no template 'nope' (amo theme templates lists them)"
