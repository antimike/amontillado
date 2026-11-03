# nvim examples

Documentation, not a plugin: copy what you need into your nvim config. The directory is laid
out as an nvim runtime directory, so `lua/` and `colors/` go to the same places under
`~/.config/nvim/` (or add this directory to `runtimepath` to try it).

| File | What it is |
|---|---|
| [lua/amontillado/watch.lua](lua/amontillado/watch.lua) | Calls a function after each `amo theme apply`. Shared by every option below. |
| [lua/amontillado/palette.lua](lua/amontillado/palette.lua) | Reads `<cache>/current/palette.lua` (the built-in `nvim` template). |
| [lua/amontillado/lush_spec.lua](lua/amontillado/lush_spec.lua) | A [lush.nvim](https://github.com/rktjmp/lush.nvim) spec: the palette's roles for the interface, base24's named hues for syntax. |
| [colors/amontillado.lua](colors/amontillado.lua) | `:colorscheme amontillado`, built from the spec. |
| [lua/amontillado/tinted.lua](lua/amontillado/tinted.lua) | The other way: [tinted-nvim](https://github.com/tinted-theming/tinted-nvim) v1 with the palette as a custom base24 scheme. |

amontillado's config needs an nvim app with the built-in template (its default):

```yaml
theme:
  apps:
    nvim: {}          # renders palette.lua into the profile
```

Then, in `init.lua` (with lush.nvim installed; lazy.nvim loads a lazy plugin on `require`):

```lua
vim.cmd.colorscheme("amontillado")
require("amontillado.watch").start(function()
  vim.cmd.colorscheme("amontillado")
end)
```

nvim needs no reload command: every running nvim re-reads the palette when a theme is applied.

## Or: tinted-nvim

Instead of the lush spec, tinted-nvim (v1; `version = "1.*"` in lazy.nvim) gives its own
highlight coverage (core, treesitter, LSP, telescope, cmp, blink, lualine, notify, dapui)
with nothing to write:

```lua
require("amontillado.tinted").start({
  setup = {},   -- any tinted-nvim options; `schemes` gains "base24-amontillado"
})
```

It runs tinted-nvim's `setup()` and `load()` again after each apply. To keep that working it
turns off tinted-nvim's `compile` (compiled highlights are kept by scheme name, so a later apply
would load the first palette), `apply_scheme_on_startup` and `selector` (tinty's file), and sets
`background` from the palette, which tinted-nvim leaves alone. tinted-nvim follows base16's
conventions (its interface uses `base0D`); the module's `highlights.overrides` puts the accent
role on a few groups (`CursorLineNr`, `FloatBorder`, `PmenuSel`, ...), and yours, if any, win.

## Notes

- **Why the watcher watches the directory.** `amo theme apply` swaps symlinks: `<cache>/<profile>`
  points to a new generation directory, and `current` is renamed over. A watch on
  `current/palette.lua` follows the file it first resolved to: on a test (2026-11-02, three
  applies) it saw nothing on the first, three events on the second (when the generation it was
  bound to was deleted, one swap late) and nothing after. `watch.lua` watches `<cache>/` for
  `current` or the profile `current` points to (an apply with `--no-activate` moves only that).
- **Exact colours.** The spec uses the palette's `#rrggbb` strings. `lush.hsl()` round-trips
  through rounded HSL and can move a channel by one; wrap a colour only to operate on it
  (`lush.hsl(c.accent).darken(20)`).
- **The cache.** Both modules default to `$XDG_CACHE_HOME/theme`, amontillado's default
  `theme.cache`; pass `cache` if the config moves it.
- **Light and dark.** `background` follows the palette's `variant`, which `theme.variant` (or the
  nvim app's `variant`) chooses.
- **The third way** (docs/design.md, "nvim and lush"): matugen-themes' `neovim/matugen.lua`,
  rendered by amontillado (`template: nvim-lua`), uses `watch.lua` the same way.
- **Tested** by `tests/test_nvim.py` (`just test-nvim`; nvim 0.11.7, lush.nvim and tinted-nvim
  v1.0.0 on 2026-11-02): one callback per apply, including `--no-activate` and `--app`, none for
  another profile, quick applies debounced to one; `Normal`, the accent and `@string` matching
  the palette exactly after each apply; tinted-nvim's background, accent overrides (yours
  winning) and telescope's border.
