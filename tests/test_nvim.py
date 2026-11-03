"""The nvim examples (docs/examples/nvim) in a real nvim, driven through pynvim.

Each test embeds `nvim --headless --clean` with the examples and the plugins on 'runtimepath',
applies themes in-process (theme.plan and theme.apply, as `amo theme apply` does) into the
cache under the `home` fixture, and reads the resulting highlights back. Python never sleeps:
nvim's own loop is pumped with `vim.wait`, which also bounds every wait.

Plugins come from AMO_TEST_NVIM_PLUGINS (default: lazy.nvim's directory) and are never
fetched; a test whose nvim or plugin is missing is skipped, naming what is missing.
`just test-nvim` runs only these.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pynvim
import pytest

from amontillado.config import AppConfig, Config, ThemeConfig
from amontillado.palette import Palette, Variant, complete_variant
from amontillado.theme import apply, plan

pytestmark = pytest.mark.nvim

EXAMPLES = Path(__file__).parent.parent / "docs" / "examples" / "nvim"
PLUGINS = Path(
    os.environ.get("AMO_TEST_NVIM_PLUGINS") or Path.home() / ".local" / "share" / "nvim" / "lazy"
)
# Generous: a loaded machine can be slow to deliver file events.
WAIT_MS = 5000
# How long a callback that should not come is waited for.
QUIET_MS = 500

RAMP = ["#101418", "#1c2228", "#2c343c", "#5c6670", "#8c96a0", "#d0d8e0", "#e4eaf0", "#f4f8fc"]
ACCENTS = ["#e06c75", "#d19a66", "#e5c07b", "#98c379", "#56b6c2", "#61afef", "#c678dd", "#be5046"]
KEYS = [f"base{i:02X}" for i in range(16)]


def _palette(name: str, variant: str) -> Palette:
    ramp = RAMP if variant == "dark" else RAMP[::-1]
    return Palette(
        name, {variant: complete_variant(variant, dict(zip(KEYS, ramp + ACCENTS, strict=True)))}
    )


DARK = _palette("dark-one", "dark")
LIGHT = _palette("light-one", "light")


def _variant(palette: Palette) -> Variant:
    (variant,) = palette.variants.values()
    return variant


def _plugin(name: str) -> Path:
    path = PLUGINS / name
    if not path.is_dir():
        pytest.skip(f"{name} not found in {PLUGINS} (set AMO_TEST_NVIM_PLUGINS)")
    return path


@pytest.fixture
def cache(home: Path) -> Path:
    """amontillado's default theme cache, which the examples default to as well."""
    return home / ".cache" / "theme"


@pytest.fixture
def config(cache: Path, tmp_path: Path) -> Config:
    theme = ThemeConfig(cache=cache, apps={"nvim": AppConfig(), "shell": AppConfig()})
    return Config((tmp_path / "library",), tmp_path / "nsfw", tmp_path / "index", theme=theme)


@pytest.fixture
def nvim(home: Path) -> Iterator[pynvim.Nvim]:
    """An embedded nvim with the examples on 'runtimepath'; HOME is the `home` fixture's."""
    if shutil.which("nvim") is None:
        pytest.skip("nvim not on PATH")
    session = pynvim.attach("child", argv=["nvim", "--embed", "--headless", "--clean"])
    try:
        session.exec_lua("vim.opt.rtp:prepend(...)", str(EXAMPLES))
        yield session
    finally:
        session.close()


def _add_plugins(nvim: pynvim.Nvim, *names: str) -> None:
    for name in names:
        nvim.exec_lua("vim.opt.rtp:append(...)", str(_plugin(name)))


def _apply(
    config: Config, palette: Palette | None, *, activate: bool = True, only: tuple[str, ...] = ()
) -> None:
    built = plan(config, palette, profile="default", variant="auto", contrast="off", only=only)
    apply(config, built, activate=activate)


def _watch(nvim: pynvim.Nvim, action: str, opts: str = "{}") -> None:
    """Start watch.lua, counting callbacks in _G.calls; `action` (Lua) runs on each."""
    nvim.exec_lua(
        f"""
        _G.calls = 0
        require("amontillado.watch").start(function()
          {action}
          _G.calls = _G.calls + 1
        end, {opts})
        """
    )


def _wait_calls(nvim: pynvim.Nvim, count: int) -> None:
    """Wait for the callback count to reach `count`, then check no further one comes."""
    reached = nvim.exec_lua(
        "local ms, n = ...; return vim.wait(ms, function() return _G.calls >= n end, 10)",
        WAIT_MS,
        count,
    )
    assert reached, f"{nvim.exec_lua('return _G.calls')} callbacks, expected {count}"
    extra = nvim.exec_lua(
        "local ms, n = ...; return vim.wait(ms, function() return _G.calls > n end, 10)",
        QUIET_MS,
        count,
    )
    assert not extra, f"{nvim.exec_lua('return _G.calls')} callbacks, expected {count}"


def _hl(nvim: pynvim.Nvim, group: str) -> dict[str, str]:
    """The colours of `group`, links followed, as "#rrggbb"."""
    attrs = nvim.exec_lua("return vim.api.nvim_get_hl(0, { name = ..., link = false })", group)
    return {key: f"#{attrs[key]:06x}" for key in ("fg", "bg", "sp") if key in attrs}


def _assert_lush(nvim: pynvim.Nvim, palette: Palette) -> None:
    variant = _variant(palette)
    colours = {**variant.base24, **variant.roles}
    assert _hl(nvim, "Normal") == {"fg": colours["base05"], "bg": colours["base00"]}
    assert _hl(nvim, "CursorLineNr")["fg"] == colours["accent"]
    assert _hl(nvim, "@string")["fg"] == colours["base0B"]
    assert nvim.exec_lua("return vim.o.background") == next(iter(palette.variants))
    # Exactly what palette.lua holds, too.
    on_disk = nvim.exec_lua('return require("amontillado.palette").load()')
    assert {key: on_disk[key] for key in ("base00", "base05", "base0B", "accent")} == {
        key: colours[key] for key in ("base00", "base05", "base0B", "accent")
    }


def test_lush_colorscheme_follows_each_apply(nvim: pynvim.Nvim, config: Config) -> None:
    _add_plugins(nvim, "lush.nvim")
    _apply(config, DARK)
    nvim.command("colorscheme amontillado")
    _assert_lush(nvim, DARK)
    _watch(nvim, 'vim.cmd.colorscheme("amontillado")')
    for count, palette in enumerate((LIGHT, DARK), start=1):
        _apply(config, palette)
        _wait_calls(nvim, count)
        _assert_lush(nvim, palette)


def test_watcher_fires_once_per_apply(nvim: pynvim.Nvim, config: Config) -> None:
    _apply(config, DARK)
    _watch(nvim, "")
    _apply(config, LIGHT)
    _wait_calls(nvim, 1)
    # --no-activate to the profile `current` points at moves only the profile's link.
    _apply(config, DARK, activate=False)
    _wait_calls(nvim, 2)
    # --app re-renders one app from the profile's own palette.
    _apply(config, None, only=("nvim",))
    _wait_calls(nvim, 3)


def test_watcher_ignores_other_profiles(nvim: pynvim.Nvim, config: Config) -> None:
    _apply(config, DARK)
    _watch(nvim, "")
    built = plan(config, LIGHT, profile="other", variant="auto", contrast="off")
    apply(config, built, activate=False)
    _wait_calls(nvim, 0)


def test_watcher_debounces_quick_applies(nvim: pynvim.Nvim, config: Config) -> None:
    _apply(config, DARK)
    _watch(nvim, "", "{ debounce = 300 }")
    _apply(config, LIGHT)
    _apply(config, DARK)
    _wait_calls(nvim, 1)


def test_missing_palette_names_the_fix(nvim: pynvim.Nvim) -> None:
    _add_plugins(nvim, "lush.nvim")
    with pytest.raises(pynvim.NvimError, match=r"cannot read .*current/palette\.lua.*amo theme"):
        nvim.command("colorscheme amontillado")


def test_cache_can_be_moved(nvim: pynvim.Nvim, config: Config, tmp_path: Path) -> None:
    moved = tmp_path / "elsewhere"
    config = replace(config, theme=replace(config.theme, cache=moved))
    _apply(config, DARK)
    loaded = nvim.exec_lua('return require("amontillado.palette").load(...)', str(moved))
    assert loaded["base00"] == _variant(DARK).base24["base00"]
    _watch(nvim, "", f"{{ cache = {json.dumps(str(moved))} }}")
    _apply(config, LIGHT)
    _wait_calls(nvim, 1)


def _start_tinted(nvim: pynvim.Nvim, setup: str = "{}") -> None:
    nvim.exec_lua(
        f"""
        _G.calls = 0
        local tinted = require("amontillado.tinted")
        local apply = tinted.apply
        -- Count re-applies: start() calls M.apply through the module table.
        tinted.apply = function(...)
          apply(...)
          _G.calls = _G.calls + 1
        end
        tinted.start({{ setup = {setup} }})
        _G.calls = 0
        """
    )


def _assert_tinted(nvim: pynvim.Nvim, palette: Palette) -> None:
    variant = _variant(palette)
    assert nvim.exec_lua("return vim.o.background") == next(iter(palette.variants))
    assert _hl(nvim, "Normal")["bg"] == variant.base24["base00"]
    # The accent overrides, and the telescope integration through them.
    roles = variant.roles
    assert _hl(nvim, "PmenuSel") == {"fg": roles["on_accent"], "bg": roles["accent"]}
    assert _hl(nvim, "TelescopeBorder")["fg"] == variant.roles["border"]


def test_tinted_follows_each_apply(nvim: pynvim.Nvim, config: Config) -> None:
    _add_plugins(nvim, "tinted-nvim")
    _apply(config, DARK)
    _start_tinted(nvim)
    _assert_tinted(nvim, DARK)
    for count, palette in enumerate((LIGHT, DARK), start=1):
        _apply(config, palette)
        _wait_calls(nvim, count)
        _assert_tinted(nvim, palette)


def test_tinted_user_overrides_win(nvim: pynvim.Nvim, config: Config) -> None:
    _add_plugins(nvim, "tinted-nvim")
    _apply(config, DARK)
    _start_tinted(
        nvim,
        """{ highlights = { overrides = function(p)
          return { CursorLineNr = { fg = p.base08 } }
        end } }""",
    )
    assert _hl(nvim, "CursorLineNr")["fg"] == _variant(DARK).base24["base08"]
    # The module's other overrides stay.
    assert _hl(nvim, "PmenuSel")["bg"] == _variant(DARK).roles["accent"]


# matugen-themes' neovim/matugen.lua at the registry's pin: never fetched by the tests. Found in
# AMO_TEST_MATUGEN_LUA, else in amontillado's sources cache (`amo theme sync` keeps it there).
MATUGEN_LUA_SHA = "63a1c8577a40eacbc78615af60e09efdf06e78cb2a583688732468066f1640d3"
MATUGEN_LUA = Path(
    os.environ.get("AMO_TEST_MATUGEN_LUA")
    or Path.home() / ".cache" / "amontillado" / "sources" / MATUGEN_LUA_SHA
)
# A stand-in in matugen's format, so the module's load and watch run without the real file.
STAND_IN = """vim.cmd("highlight clear")
vim.o.background = "{{ mode }}"
vim.api.nvim_set_hl(0, "Normal", { fg = "{{ colors.on_background.default.hex }}" })
vim.api.nvim_set_hl(0, "CursorLineNr", { fg = "{{ colors.primary.default.hex }}" })
vim.g.terminal_color_1 = "{{ colors.red.default.hex }}"
"""


def _matugen_config(config: Config, template: Path) -> Config:
    app = AppConfig(source="path", path=template, format="matugen", output="matugen.lua")
    return replace(config, theme=replace(config.theme, apps={"nvim-lua": app}))


def _assert_matugen(nvim: pynvim.Nvim, palette: Palette) -> None:
    variant = _variant(palette)
    colours = {**variant.base24, **variant.roles}
    assert nvim.exec_lua("return vim.o.background") == next(iter(palette.variants))
    assert _hl(nvim, "Normal")["fg"] == colours["base05"]  # on_background
    assert _hl(nvim, "CursorLineNr")["fg"] == colours["accent"]  # primary
    assert nvim.exec_lua("return vim.g.terminal_color_1") == colours["base08"]  # red


def _follow_with_matugen(nvim: pynvim.Nvim, config: Config) -> None:
    _apply(config, DARK)
    nvim.exec_lua(
        """
        _G.calls = 0
        local matugen = require("amontillado.matugen")
        local load = matugen.load
        matugen.load = function(...)
          load(...)
          _G.calls = _G.calls + 1
        end
        matugen.start()
        _G.calls = 0
        """
    )
    _assert_matugen(nvim, DARK)
    for count, palette in enumerate((LIGHT, DARK), start=1):
        _apply(config, palette)
        _wait_calls(nvim, count)
        _assert_matugen(nvim, palette)


def test_matugen_module_follows_each_apply(
    nvim: pynvim.Nvim, config: Config, tmp_path: Path
) -> None:
    template = tmp_path / "stand-in.lua"
    template.write_text(STAND_IN)
    _follow_with_matugen(nvim, _matugen_config(config, template))


def test_matugen_themes_colourscheme_follows_each_apply(
    nvim: pynvim.Nvim, config: Config, tmp_path: Path
) -> None:
    if not MATUGEN_LUA.is_file():
        pytest.skip(f"neovim/matugen.lua not found at {MATUGEN_LUA} (set AMO_TEST_MATUGEN_LUA)")
    text = MATUGEN_LUA.read_text()
    # At the pin (81dbb648, also upstream's head on 2026-11-03) the file ends with a stray line
    # `v`, which nvim refuses ("'=' expected near '<eof>'"); the test drops it.
    if text.endswith("\nv\n"):
        text = text.removesuffix("v\n")
    template = tmp_path / "matugen.lua"
    template.write_text(text)
    _follow_with_matugen(nvim, _matugen_config(config, template))


def test_missing_matugen_lua_names_the_fix(nvim: pynvim.Nvim) -> None:
    with pytest.raises(pynvim.NvimError, match=r"cannot run .*current/matugen\.lua.*nvim-lua"):
        nvim.exec_lua('require("amontillado.matugen").load()')
