-- Call a function whenever amontillado applies a theme (docs/design.md, "Cache").
--
-- `amo theme apply` swaps symlinks in the cache directory: the profile's (`default`) and
-- `current`, each by renaming a new link over the old. So this watches the cache directory
-- itself, which is never replaced, and reacts to either name. A watch on
-- `current/palette.lua` would follow the generation directory the link pointed to when the
-- watch began, and go deaf at the first swap.
--
-- Usage (see the README beside this file):
--
--   require("amontillado.watch").start(function(dir)
--     vim.cmd.colorscheme("amontillado")
--   end)
--
-- `dir` is `<cache>/current`. The callback runs on the main loop, once per apply (events
-- within `debounce` ms are one change).

local M = {}

local function default_cache()
  local base = vim.env.XDG_CACHE_HOME
  if base == nil or base == "" then
    base = vim.fs.joinpath(vim.env.HOME, ".cache")
  end
  -- amontillado's default `theme.cache`; set `cache` if the config moves it.
  return vim.fs.joinpath(base, "theme")
end

--- Start watching. Returns the libuv handle (`:stop()` it to end the watch).
--- @param on_change fun(dir: string)
--- @param opts? { cache?: string, debounce?: integer }
function M.start(on_change, opts)
  opts = opts or {}
  local cache = opts.cache or default_cache()
  local debounce = opts.debounce or 100
  local handle = assert(vim.uv.new_fs_event())
  local timer = assert(vim.uv.new_timer())

  local function relevant(name)
    if name == "current" then
      return true
    end
    -- An apply with --no-activate to the profile `current` points at moves only that link.
    local profile = vim.uv.fs_readlink(vim.fs.joinpath(cache, "current"))
    return profile ~= nil and name == profile
  end

  handle:start(cache, {}, function(err, name)
    if err or not name or not relevant(name) then
      return
    end
    -- One apply renames several links; wait for the last.
    timer:stop()
    timer:start(debounce, 0, function()
      vim.schedule(function()
        on_change(vim.fs.joinpath(cache, "current"))
      end)
    end)
  end)
  return handle
end

return M
