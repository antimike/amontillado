-- tinted-nvim (v1, https://github.com/tinted-theming/tinted-nvim) over amontillado's palette:
-- the plugin's highlight coverage (core, treesitter, LSP, telescope, cmp, blink, lualine, ...)
-- with the palette loaded as a custom base24 scheme, re-applied after each `amo theme apply`.
--
--   require("amontillado.tinted").start({
--     setup = { highlights = { integrations = { dapui = false } } },  -- tinted-nvim options
--   })
--
-- tinted-nvim follows base16's conventions, so its interface uses base0D (blue) where
-- amontillado has an accent role. Its `highlights.overrides` receives the whole palette,
-- roles included, which is how the accent reaches the interface below; extend it as you like.

local M = {}

-- tinted-nvim's custom schemes must be named base16-* or base24-*.
local NAME = "base24-amontillado"

local function accent_overrides(palette)
  return {
    CursorLineNr = { fg = palette.accent, bold = true },
    FloatBorder = { fg = palette.border, bg = palette.base01 },
    WinSeparator = { fg = palette.border_inactive },
    Visual = { fg = palette.on_selection, bg = palette.selection },
    PmenuSel = { fg = palette.on_accent, bg = palette.accent },
    IncSearch = { fg = palette.on_accent, bg = palette.accent },
  }
end

--- Load the applied palette into tinted-nvim and apply it.
--- @param opts? { setup?: table, cache?: string }
function M.apply(opts)
  opts = opts or {}
  local setup = vim.tbl_deep_extend("force", {}, opts.setup or {})
  local palette = require("amontillado.palette").load(opts.cache)
  setup.schemes = vim.tbl_extend("force", setup.schemes or {}, { [NAME] = palette })
  -- Compiled artifacts are kept by scheme name: with compile on, every later apply would load
  -- the first palette. setup() runs again on each apply, so it must not start the selector's
  -- watcher (tinty's file, unused here) or load the default scheme first.
  setup.compile = false
  setup.apply_scheme_on_startup = false
  setup.selector = { enabled = false }
  local user_overrides = setup.highlights and setup.highlights.overrides
  setup.highlights = vim.tbl_extend("force", setup.highlights or {}, {
    overrides = function(resolved)
      local groups = accent_overrides(resolved)
      return vim.tbl_extend("force", groups, user_overrides and user_overrides(resolved) or {})
    end,
  })
  local tinted = require("tinted-nvim")
  tinted.setup(setup)
  -- tinted-nvim leaves 'background' alone. Setting it while colors_name is set would re-run
  -- `:colorscheme base24-amontillado`, which has no colors/ file: clear the name first.
  vim.g.colors_name = nil
  vim.o.background = palette.variant
  tinted.load(NAME)
end

--- Apply now and after every theme switch. Returns the watcher's handle.
--- @param opts? { setup?: table, cache?: string }
function M.start(opts)
  M.apply(opts)
  return require("amontillado.watch").start(function()
    M.apply(opts)
  end, { cache = opts and opts.cache })
end

return M
