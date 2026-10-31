from __future__ import annotations

import logging
import os
import re
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from amontillado.config import AppConfig, Config, ThemeConfig
from amontillado.palette import Palette, complete_variant, dump_palette
from amontillado.theme import (
    ThemeError,
    apply,
    choose_variant,
    describe,
    find_palette,
    plan,
    reload_commands,
    run_reloads,
)

RAMP = ["#101010", "#181818", "#303030", "#707070", "#a0a0a0", "#e0e0e0", "#f0f0f0", "#ffffff"]
ACCENTS = ["#ff8080", "#ffa060", "#ffe080", "#80ff80", "#80ffff", "#80b0ff", "#e0a0ff", "#c08060"]
BASE16 = dict(zip([f"base{i:02X}" for i in range(16)], RAMP + ACCENTS, strict=True))


def _palette(name: str = "p", variants: tuple[str, ...] = ("dark",), **source: object) -> Palette:
    return Palette(name, {v: complete_variant(v, BASE16) for v in variants}, dict(source))


def _config(tmp_path: Path, **apps: AppConfig) -> Config:
    apps = apps or {"kitty": AppConfig(), "nvim": AppConfig()}
    theme = ThemeConfig(cache=tmp_path / "cache", apps=apps)
    return Config((tmp_path / "library",), tmp_path / "nsfw", tmp_path / "index", theme=theme)


def _apply(config: Config, palette: Palette | None, *, only: tuple[str, ...] = ()) -> Path:
    built = plan(config, palette, profile="default", variant="auto", contrast="off", only=only)
    return apply(config, built, activate=True)


def test_apply_writes_a_profile_and_points_current_at_it(tmp_path: Path) -> None:
    config = _config(tmp_path)
    directory = _apply(config, _palette())
    cache = tmp_path / "cache"
    assert directory == cache / "default"
    assert directory.is_symlink() and os.readlink(cache / "current") == "default"
    assert (cache / "current" / "kitty.conf").read_text().startswith("# amontillado p (dark)")
    assert 'base0D = "#80b0ff"' in (directory / "palette.lua").read_text()
    assert yaml.safe_load((directory / "palette.yaml").read_text())["name"] == "p"
    theme = yaml.safe_load((directory / "theme.yaml").read_text())
    assert theme["palette"] == "p"
    assert theme["apps"]["kitty"] == {
        "source": "builtin",
        "template": "kitty",
        "output": "kitty.conf",
        "variant": "dark",
        "palette": "p",
    }
    assert not (directory / "wallpaper").exists()


def test_swap_keeps_the_previous_generation_only(tmp_path: Path) -> None:
    config = _config(tmp_path)
    generations = tmp_path / "cache" / ".profiles" / "default"
    _apply(config, _palette("one"))
    first = (tmp_path / "cache" / "default").resolve()
    _apply(config, _palette("two"))
    second = (tmp_path / "cache" / "default").resolve()
    assert set(generations.iterdir()) == {first, second}
    _apply(config, _palette("three"))
    assert second in set(generations.iterdir()) and first not in set(generations.iterdir())
    assert len(list(generations.iterdir())) == 2
    assert not list((tmp_path / "cache").glob(".*.link"))


def test_render_error_changes_nothing(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _apply(config, _palette("one"))
    before = (tmp_path / "cache" / "default").resolve()
    broken = _config(tmp_path, kitty=AppConfig(), bad=AppConfig(template="nope"))
    with pytest.raises(ThemeError, match=re.escape("theme.apps.bad: no built-in template 'nope'")):
        _apply(broken, _palette("two"))
    assert (tmp_path / "cache" / "default").resolve() == before
    assert len(list((tmp_path / "cache" / ".profiles" / "default").iterdir())) == 1


def test_unsupported_sources_are_errors(tmp_path: Path) -> None:
    for app, message in [
        (AppConfig(source="tinted"), "source tinted is not supported yet"),
        (AppConfig(format="matugen", render_with="matugen"), "render_with: matugen"),
        (AppConfig(source="path", path=tmp_path / "t", format="mustache"), "needs an output"),
    ]:
        with pytest.raises(ThemeError, match=message):
            _apply(_config(tmp_path, x=app), _palette())


def test_path_source(tmp_path: Path) -> None:
    template = tmp_path / "mine.mustache"
    template.write_text("bg={{base00-hex}} {{scheme-variant}}\n")
    app = AppConfig(source="path", path=template, format="mustache", output="mine.conf")
    directory = _apply(_config(tmp_path, mine=app), _palette())
    assert (directory / "mine.conf").read_text() == "bg=101010 dark\n"


def test_not_amontillados_profile_is_refused(tmp_path: Path) -> None:
    (tmp_path / "cache" / "default").mkdir(parents=True)
    with pytest.raises(ThemeError, match="is not amontillado's"):
        _apply(_config(tmp_path), _palette())
    assert not list((tmp_path / "cache" / ".profiles" / "default").iterdir())


def test_rerender_uses_the_profiles_palette_and_wallpaper(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(ThemeError, match="profile default has no palette yet"):
        _apply(config, None)
    directory = _apply(config, _palette("kept"))
    picture = tmp_path / "picture.jpg"
    (directory / "wallpaper").symlink_to(picture)
    _apply(config, None)
    assert yaml.safe_load((directory / "theme.yaml").read_text())["palette"] == "kept"
    assert os.readlink(directory / "wallpaper") == str(picture)


def test_app_subset_keeps_the_others(tmp_path: Path) -> None:
    config = _config(tmp_path)
    directory = _apply(config, _palette("old"))
    _apply(config, _palette("new"), only=("nvim",))
    assert (directory / "kitty.conf").read_text().startswith("# amontillado old")
    assert (directory / "palette.lua").read_text().startswith("-- amontillado new")
    apps = yaml.safe_load((directory / "theme.yaml").read_text())["apps"]
    assert (apps["kitty"]["palette"], apps["nvim"]["palette"]) == ("old", "new")
    info, palettes = describe(config.theme, "default")
    assert info["palette"] == "new"
    assert palettes == ["new", "old"]


def test_app_subset_errors(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(ThemeError, match="run without --app first"):
        _apply(config, _palette(), only=("kitty",))
    with pytest.raises(ThemeError, match=re.escape("--app sway: not under theme.apps")):
        _apply(config, _palette(), only=("sway",))


def test_variant(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    both = _palette(variants=("dark", "light"), lightness=0.8)
    assert choose_variant(both, "auto") == "light"
    assert choose_variant(replace(both, source={"lightness": 0.3}), "auto") == "dark"
    assert choose_variant(replace(both, source={}), "auto") == "dark"
    assert choose_variant(_palette(variants=("light",)), "auto") == "light"
    with caplog.at_level(logging.WARNING):
        assert choose_variant(_palette(), "light") == "dark"
    assert "has no light variant: using dark" in caplog.text
    config = _config(tmp_path, kitty=AppConfig(variant="light"), nvim=AppConfig())
    built = plan(config, both, profile="default", variant="dark", contrast="off")
    assert [item.record["variant"] for item in built.rendered] == ["light", "dark"]


def test_reload_commands(tmp_path: Path) -> None:
    apps = {
        "kitty": AppConfig(reload=("pkill", "-USR1", "kitty")),
        "nvim": AppConfig(reload=("notify", "{profile}", "{dir}/palette.lua")),
    }
    config = _config(tmp_path, **apps)
    config = replace(config, theme=replace(config.theme, wallpaper_reload=("set", "{wallpaper}")))
    built = plan(config, _palette(), profile="default", variant="auto", contrast="off")
    directory = tmp_path / "cache" / "default"
    assert reload_commands(config, built, directory) == [
        ("pkill", "-USR1", "kitty"),
        ("notify", "default", f"{directory}/palette.lua"),
    ]
    directory.mkdir(parents=True)
    (directory / "wallpaper").symlink_to("/pictures/a.jpg")
    assert reload_commands(config, built, directory)[-1] == ("set", "/pictures/a.jpg")


def test_failing_reloads_warn(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        run_reloads([("false",), ("amo-no-such-command",), ("true",)])
    assert "reload false: exit status 1" in caplog.text
    assert "reload amo-no-such-command:" in caplog.text
    assert "reload true" not in caplog.text


def test_find_palette(home: Path) -> None:
    presets = home / ".config" / "amontillado" / "palettes"
    presets.mkdir(parents=True)
    (presets / "gruvbox.yaml").write_text(dump_palette(_palette()))
    assert find_palette("gruvbox") == presets / "gruvbox.yaml"
    assert find_palette(str(presets / "gruvbox.yaml")) == presets / "gruvbox.yaml"
    with pytest.raises(ThemeError, match="no palette file nord and no preset"):
        find_palette("nord")
