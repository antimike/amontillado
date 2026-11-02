-- `:colorscheme amontillado`: the lush spec over the palette amontillado last applied.
-- Each run reads the palette afresh, so the watcher only has to run this again.

package.loaded["amontillado.lush_spec"] = nil
vim.cmd.highlight("clear")
vim.o.background = require("amontillado.palette").load().variant
vim.g.colors_name = "amontillado"
require("lush")(require("amontillado.lush_spec"))
