from __future__ import annotations

import logging
import os
import re
from dataclasses import replace
from pathlib import Path

import pytest

from amontillado import yamlio
from amontillado.cli import main
from amontillado.config import AppConfig, Config, ThemeConfig
from amontillado.palette import Palette, complete_variant, dump_palette
from amontillado.theme import (
    Reload,
    ThemeError,
    apply,
    choose_variant,
    describe,
    find_palette,
    plan,
    reload_commands,
    repoint_wallpapers,
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
    assert yamlio.load((directory / "palette.yaml").read_text())["name"] == "p"
    theme = yamlio.load((directory / "theme.yaml").read_text())
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
    with pytest.raises(
        ThemeError, match=re.escape("theme.apps.bad: no source has a template 'nope'")
    ):
        _apply(broken, _palette("two"))
    assert (tmp_path / "cache" / "default").resolve() == before
    assert len(list((tmp_path / "cache" / ".profiles" / "default").iterdir())) == 1


def test_unsupported_sources_are_errors(tmp_path: Path) -> None:
    with pytest.raises(ThemeError, match="tinted has no template 'x'"):
        _apply(_config(tmp_path, x=AppConfig(source="tinted")), _palette())


def _by_matugen(tmp_path: Path, name: str, **extra: object) -> AppConfig:
    template = tmp_path / f"{name}.in"
    template.write_text(f"{name} {{{{colors.primary.default.hex}}}}\n")
    return AppConfig(
        source="path",
        path=template,
        format="matugen",
        output=f"{name}.out",
        render_with="matugen",
        **extra,
    )


def test_render_with_matugen_runs_matugen_once_per_variant(
    matugen_renderer: Path, tmp_path: Path
) -> None:
    apps = {
        "a": _by_matugen(tmp_path, "a"),
        "kitty": AppConfig(),
        "b": _by_matugen(tmp_path, "b"),
        "c": _by_matugen(tmp_path, "c", variant="light"),
    }
    picture = tmp_path / "picture.jpg"
    config = _config(tmp_path, **apps)
    built = plan(
        config,
        _palette(variants=("dark", "light")),
        profile="default",
        variant="dark",
        contrast="off",
        wallpaper=picture,
    )
    assert [item.app for item in built.rendered] == ["a", "kitty", "b", "c"]
    directory = apply(config, built, activate=True)
    # matugen's own output, the template untouched by amontillado.
    marker = "{{colors.primary.default.hex}}"
    assert (directory / "a.out").read_text() == f"dark {picture}: a {marker}\n"
    assert (directory / "c.out").read_text().startswith(f"light {picture}: c ")
    assert (directory / "kitty.conf").read_text().startswith("# amontillado p (dark)")
    runs = [line for line in matugen_renderer.read_text().splitlines() if line != "--version"]
    assert len(runs) == 2
    assert runs[0].startswith(f"image {picture} --source-color-index 0 -c ")
    assert runs[0].endswith("-m dark -q") and runs[1].endswith("-m light -q")
    theme = yamlio.load((directory / "theme.yaml").read_text())
    assert theme["apps"]["b"]["renderer"] == "matugen 4.2.0"
    assert theme["apps"]["c"]["variant"] == "light"
    assert "renderer" not in theme["apps"]["kitty"]


def test_render_with_matugen_without_a_picture_uses_the_accent(
    matugen_renderer: Path, tmp_path: Path
) -> None:
    directory = _apply(_config(tmp_path, a=_by_matugen(tmp_path, "a")), _palette())
    assert (directory / "a.out").read_text().startswith("dark hex #80b0ff: a ")


def test_render_with_matugen_failing_changes_nothing(
    matugen_renderer: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, a=_by_matugen(tmp_path, "a"), kitty=AppConfig())
    monkeypatch.setenv("FAKE_MATUGEN_FAIL", "1")
    with pytest.raises(
        ThemeError, match=r"theme\.apps\.a: render_with: matugen failed \(exit 3\): no colours"
    ):
        _apply(config, _palette())
    assert not (tmp_path / "cache" / "default").exists()


def test_render_with_matugen_needs_matugen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(ThemeError, match=r"theme\.apps\.a: render_with: matugen is not installed"):
        _apply(_config(tmp_path, a=_by_matugen(tmp_path, "a")), _palette())


def test_path_source(tmp_path: Path) -> None:
    template = tmp_path / "mine.mustache"
    template.write_text("bg={{base00-hex}} {{scheme-variant}}\n")
    app = AppConfig(source="path", path=template, format="mustache", output="mine.conf")
    directory = _apply(_config(tmp_path, mine=app), _palette())
    assert (directory / "mine.conf").read_text() == "bg=101010 dark\n"


def test_matugen_format(tmp_path: Path) -> None:
    template = tmp_path / "mine.css"
    template.write_text(
        "@define-color primary {{colors.primary.default.hex}};\n"
        "@define-color bg {{colors.surface.dark.rgba | set_alpha: 0.5}}; /* {{mode}} */\n"
    )
    app = AppConfig(source="path", path=template, format="matugen", output="mine.css")
    directory = _apply(_config(tmp_path, mine=app), _palette())
    assert (directory / "mine.css").read_text() == (
        "@define-color primary #80b0ff;\n@define-color bg rgba(16, 16, 16, 0.5); /* dark */\n"
    )
    template.write_text("<* for name, p in palettes *>{{name}}<* endfor *>")
    with pytest.raises(ThemeError, match=r"theme\.apps\.mine: .*unknown variable 'palettes'"):
        _apply(_config(tmp_path, mine=app), _palette())


def test_wallpaper_links_follow_a_moved_record(tmp_path: Path) -> None:
    config = _config(tmp_path)
    directory = _apply(config, _palette())
    old, new = tmp_path / "lib" / "wallhaven-abc123", tmp_path / "lib" / "cats-abc123"
    (directory / "wallpaper").symlink_to(old / "wallhaven-abc123.jpg")
    other = tmp_path / "cache" / ".profiles" / "other-1"
    other.mkdir(parents=True)
    (tmp_path / "cache" / "other").symlink_to(other)
    (other / "wallpaper").symlink_to(tmp_path / "elsewhere.jpg")
    assert repoint_wallpapers(config.theme, old, new) == ["default"]
    assert os.readlink(directory / "wallpaper") == str(new / "wallhaven-abc123.jpg")
    assert os.readlink(other / "wallpaper") == str(tmp_path / "elsewhere.jpg")
    assert repoint_wallpapers(replace(config.theme, cache=tmp_path / "none"), old, new) == []


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
    assert yamlio.load((directory / "theme.yaml").read_text())["palette"] == "kept"
    assert os.readlink(directory / "wallpaper") == str(picture)


def test_app_subset_keeps_the_others(tmp_path: Path) -> None:
    config = _config(tmp_path)
    directory = _apply(config, _palette("old"))
    _apply(config, _palette("new"), only=("nvim",))
    assert (directory / "kitty.conf").read_text().startswith("# amontillado old")
    assert (directory / "palette.lua").read_text().startswith("-- amontillado new")
    apps = yamlio.load((directory / "theme.yaml").read_text())["apps"]
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
        "kitty": AppConfig(reload="pkill -USR1 kitty"),
        "nvim": AppConfig(reload='notify "$AMO_PROFILE" "$AMO_DIR/palette.lua"'),
    }
    config = _config(tmp_path, **apps)
    config = replace(config, theme=replace(config.theme, wallpaper_reload='set "$AMO_WALLPAPER"'))
    built = plan(config, _palette(), profile="default", variant="auto", contrast="off")
    directory = tmp_path / "cache" / "default"
    env = {"AMO_PROFILE": "default", "AMO_DIR": str(directory), "AMO_VARIANT": "dark"}
    # No wallpaper: AMO_WALLPAPER is unset and the hook naming it is left out.
    assert reload_commands(config, built, directory) == [
        Reload("pkill -USR1 kitty", env),
        Reload('notify "$AMO_PROFILE" "$AMO_DIR/palette.lua"', env),
    ]
    directory.mkdir(parents=True)
    (directory / "wallpaper").symlink_to("/pictures/a b.jpg")
    hook = reload_commands(config, built, directory)[-1]
    assert hook == Reload('set "$AMO_WALLPAPER"', {**env, "AMO_WALLPAPER": "/pictures/a b.jpg"})
    assert str(hook) == (
        f"AMO_DIR={directory} AMO_PROFILE=default AMO_VARIANT=dark "
        "AMO_WALLPAPER='/pictures/a b.jpg' sh -c 'set \"$AMO_WALLPAPER\"'"
    )


def test_reload_commands_fill_each_apps_variant(tmp_path: Path) -> None:
    hook = 'gsettings set x color-scheme "prefer-$AMO_VARIANT"'
    apps = {"libadwaita": AppConfig(variant="light", reload=hook), "kitty": AppConfig(reload=hook)}
    config = _config(tmp_path, **apps)
    config = replace(config, theme=replace(config.theme, wallpaper_reload="set"))
    both = _palette(variants=("dark", "light"))
    built = plan(config, both, profile="default", variant="auto", contrast="off")
    variants = [r.env["AMO_VARIANT"] for r in reload_commands(config, built, tmp_path / "x")]
    assert variants == ["light", "dark", "dark"]
    # A variant the palette lacks resolves as the render does.
    built = plan(config, _palette(), profile="default", variant="light", contrast="off")
    variants = [r.env["AMO_VARIANT"] for r in reload_commands(config, built, tmp_path)]
    assert variants == ["dark", "dark", "dark"]


def test_run_reloads_under_sh_with_amo_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    # A stale AMO_* from amo's own environment does not reach the command.
    monkeypatch.setenv("AMO_WALLPAPER", "stale")
    command = f'echo "$AMO_PROFILE|$AMO_VARIANT|${{AMO_WALLPAPER-unset}}" | tr a-z A-Z > {out}'
    run_reloads([Reload(command, {"AMO_PROFILE": "p", "AMO_VARIANT": "dark"})])
    assert out.read_text() == "P|DARK|UNSET\n"


def test_failing_reloads_warn(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        run_reloads([Reload("false", {}), Reload("amo-no-such-command", {}), Reload("true", {})])
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


def _cli_setup(home: Path) -> Path:
    config = home / ".config" / "amontillado" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(
        yamlio.dump(
            {
                "theme": {
                    "apps": {"kitty": {"reload": 'true "$AMO_PROFILE" "$AMO_VARIANT"'}, "json": {}}
                }
            }
        )
    )
    palette = home / "p.yaml"
    palette.write_text(dump_palette(_palette("cli")))
    return palette


def test_cli_apply_and_current(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    palette = _cli_setup(home)
    main(["theme", "apply", "--palette", str(palette)])
    cache = home / ".cache" / "theme"
    assert (cache / "current" / "palette.json").is_file()
    main(["theme", "current"])
    out = capsys.readouterr().out.splitlines()
    assert out[:3] == ["profile: default", "palette: cli", "picture: "]
    assert out[3].startswith("applied: ")
    with pytest.raises(SystemExit) as exc:
        main(["theme", "apply", "--profile", ".hidden"])
    assert exc.value.code == "amontillado: --profile: '.hidden' is not a profile name"


def test_cli_dry_run_changes_nothing(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    palette = _cli_setup(home)
    main(["theme", "apply", "--palette", str(palette), "--dry-run"])
    out = capsys.readouterr().out.splitlines()
    assert (Path(out[0]) / "kitty.conf").is_file()
    directory = home / ".cache" / "theme" / "default"
    assert out[1] == (
        f"would run: AMO_DIR={directory} AMO_PROFILE=default AMO_VARIANT=dark "
        'sh -c \'true "$AMO_PROFILE" "$AMO_VARIANT"\''
    )
    assert not (home / ".cache" / "theme").exists()
