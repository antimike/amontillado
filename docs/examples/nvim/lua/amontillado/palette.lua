-- The palette amontillado last applied: `<cache>/current/palette.lua`, rendered by the built-in
-- `nvim` template (every base24 key and role as "#rrggbb", and `variant`).

local M = {}

--- @param cache? string amontillado's theme cache (default `$XDG_CACHE_HOME/theme`)
--- @return table<string, string>
function M.load(cache)
  if cache == nil then
    local base = vim.env.XDG_CACHE_HOME
    if base == nil or base == "" then
      base = vim.fs.joinpath(vim.env.HOME, ".cache")
    end
    cache = vim.fs.joinpath(base, "theme")
  end
  local path = vim.fs.joinpath(cache, "current", "palette.lua")
  local ok, palette = pcall(dofile, path)
  if not ok then
    error(("amontillado: cannot read %s (run amo theme apply with an nvim app): %s"):format(path, palette))
  end
  return palette
end

return M
