-- The third way: matugen-themes' `neovim/matugen.lua`, rendered by amontillado (registry source
-- `matugen-themes`, template `nvim-lua`) into `<cache>/current/matugen.lua`. That file is a whole
-- colourscheme, `nvim_set_hl` calls over the Material roles (and the custom colours `red`,
-- `blue`, ... it names, from the palette's named hues), so running it again re-themes nvim.
--
-- Usage (see the README beside this file):
--
--   require("amontillado.matugen").start()

local M = {}

local function default_cache()
  local base = vim.env.XDG_CACHE_HOME
  if base == nil or base == "" then
    base = vim.fs.joinpath(vim.env.HOME, ".cache")
  end
  return vim.fs.joinpath(base, "theme")
end

--- Run the rendered colourscheme in `dir` (default `<cache>/current`).
--- @param dir? string
function M.load(dir)
  local path = vim.fs.joinpath(dir or vim.fs.joinpath(default_cache(), "current"), "matugen.lua")
  local ok, err = pcall(dofile, path)
  if not ok then
    local hint = "run amo theme apply with an nvim-lua app from matugen-themes"
    error(("amontillado: cannot run %s (%s): %s"):format(path, hint, err))
  end
end

--- Load the colourscheme now and again after each apply. Returns watch.lua's handle.
--- @param opts? { cache?: string, debounce?: integer }
function M.start(opts)
  opts = opts or {}
  M.load(vim.fs.joinpath(opts.cache or default_cache(), "current"))
  return require("amontillado.watch").start(function(dir)
    M.load(dir)
  end, opts)
end

return M
