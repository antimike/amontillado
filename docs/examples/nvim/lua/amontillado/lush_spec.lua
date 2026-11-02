-- A lush spec over amontillado's palette: the roles (accent, selection, border, error, ...) for
-- the interface, base24's named hues for syntax. An example to edit, not a finished theme: it
-- covers the core groups, diagnostics and treesitter; plugins' groups mostly link to these.
--
-- base24 (tinted-theming's styling guide): base00-base07 the ramp from background to the
-- lightest foreground, base08-base0F red, orange, yellow, green, cyan, blue, magenta, brown,
-- base10/base11 darker backgrounds, base12-base17 the bright accents.

local lush = require("lush")
local p = require("amontillado.palette").load()
-- The palette's own "#rrggbb" strings: lush.hsl() round-trips through rounded HSL and can
-- move a channel by one. Wrap a colour only to operate on it: lush.hsl(c.accent).darken(20).
local c = setmetatable({}, {
  __index = function(_, key)
    return assert(p[key], "palette has no " .. key)
  end,
})

---@diagnostic disable: undefined-global
return lush(function(injected)
  local sym = injected.sym
  return {
    -- Editor
    Normal { fg = c.base05, bg = c.base00 },
    NormalFloat { fg = c.base05, bg = c.base01 },
    NormalNC { Normal },
    FloatBorder { fg = c.border, bg = c.base01 },
    FloatTitle { fg = c.accent, bg = c.base01, gui = "bold" },
    WinSeparator { fg = c.border_inactive },
    Cursor { fg = c.base00, bg = c.base05 },
    CursorLine { bg = c.base01 },
    CursorColumn { CursorLine },
    ColorColumn { bg = c.base01 },
    CursorLineNr { fg = c.accent, gui = "bold" },
    LineNr { fg = c.base03 },
    SignColumn { fg = c.base03 },
    Folded { fg = c.base04, bg = c.base01 },
    FoldColumn { fg = c.base03 },
    NonText { fg = c.base02 },
    Whitespace { NonText },
    EndOfBuffer { NonText },
    Visual { fg = c.on_selection, bg = c.selection },
    Search { fg = c.on_secondary, bg = c.secondary },
    IncSearch { fg = c.on_accent, bg = c.accent },
    CurSearch { IncSearch },
    Substitute { IncSearch },
    MatchParen { fg = c.accent, gui = "bold,underline" },
    StatusLine { fg = c.base04, bg = c.base01 },
    StatusLineNC { fg = c.base03, bg = c.base10 },
    TabLine { fg = c.base04, bg = c.base01 },
    TabLineFill { bg = c.base10 },
    TabLineSel { fg = c.on_accent, bg = c.accent },
    WinBar { fg = c.base05, gui = "bold" },
    WinBarNC { fg = c.base03 },
    Pmenu { fg = c.base05, bg = c.base01 },
    PmenuSel { fg = c.on_accent, bg = c.accent },
    PmenuSbar { bg = c.base02 },
    PmenuThumb { bg = c.base03 },
    Title { fg = c.accent, gui = "bold" },
    Directory { fg = c.accent },
    Question { fg = c.info },
    MoreMsg { fg = c.success },
    ModeMsg { fg = c.base04, gui = "bold" },
    ErrorMsg { fg = c.error },
    WarningMsg { fg = c.warning },
    SpellBad { sp = c.error, gui = "undercurl" },
    SpellCap { sp = c.warning, gui = "undercurl" },
    DiffAdd { fg = c.success },
    DiffChange { fg = c.warning },
    DiffDelete { fg = c.error },
    DiffText { fg = c.info, gui = "bold" },

    -- Diagnostics: the status roles
    DiagnosticError { fg = c.error },
    DiagnosticWarn { fg = c.warning },
    DiagnosticInfo { fg = c.info },
    DiagnosticHint { fg = c.secondary },
    DiagnosticOk { fg = c.success },
    DiagnosticUnderlineError { sp = c.error, gui = "undercurl" },
    DiagnosticUnderlineWarn { sp = c.warning, gui = "undercurl" },
    DiagnosticUnderlineInfo { sp = c.info, gui = "undercurl" },
    DiagnosticUnderlineHint { sp = c.secondary, gui = "undercurl" },

    -- Syntax: base24's named hues, as base16 templates assign them
    Comment { fg = c.base03, gui = "italic" },
    Constant { fg = c.base09 },
    String { fg = c.base0B },
    Character { String },
    Number { fg = c.base09 },
    Boolean { Number },
    Float { Number },
    Identifier { fg = c.base08 },
    Function { fg = c.base0D },
    Statement { fg = c.base0E },
    Keyword { Statement },
    Conditional { Statement },
    Repeat { Statement },
    Operator { fg = c.base05 },
    PreProc { fg = c.base0A },
    Include { fg = c.base0D },
    Type { fg = c.base0A },
    Special { fg = c.base0C },
    Delimiter { fg = c.base0F },
    Todo { fg = c.base00, bg = c.warning, gui = "bold" },
    Error { fg = c.error },
    Underlined { gui = "underline" },

    -- Treesitter: mostly links to the groups above
    sym("@variable") { fg = c.base05 },
    sym("@variable.builtin") { fg = c.base08 },
    sym("@variable.parameter") { fg = c.base05, gui = "italic" },
    sym("@property") { fg = c.base0C },
    sym("@constant") { Constant },
    sym("@constant.builtin") { Constant },
    sym("@string") { String },
    sym("@string.escape") { Special },
    sym("@number") { Number },
    sym("@boolean") { Boolean },
    sym("@function") { Function },
    sym("@function.builtin") { fg = c.base0C },
    sym("@function.method") { Function },
    sym("@constructor") { Type },
    sym("@keyword") { Keyword },
    sym("@keyword.return") { Keyword },
    sym("@type") { Type },
    sym("@type.builtin") { Type },
    sym("@operator") { Operator },
    sym("@punctuation") { Delimiter },
    sym("@comment") { Comment },
    sym("@tag") { fg = c.base08 },
    sym("@markup.heading") { Title },
    sym("@markup.link") { fg = c.accent, gui = "underline" },
  }
end)
