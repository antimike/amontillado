# Terminal theming

How to make a terminal and the tools in it follow the palette amontillado applies, including
under a light variant: which colours follow on their own and which do not, `LS_COLORS` from the
palette, reaching shells that are already running, and prompt and highlighter reloads. The
snippets are for zsh (bash where it differs) and use the default cache,
`${XDG_CACHE_HOME:-$HOME/.cache}/theme`; adjust if `theme.cache` says otherwise.

## The rule: what follows the palette

A terminal theme sets 16 ANSI colours (0-15), the background and the foreground. amontillado's
built-in `kitty` template also sets 16-21 (base16-shell's extras: `base09`, `base0F`, `base01`,
`base02`, `base04`, `base06`). What a tool draws depends on how it names a colour:

| A tool names | Example | Follows the palette? |
|---|---|---|
| an ANSI colour 0-15 | `\e[34m`, `fg=blue`, `di=01;34` | yes, live, as soon as the terminal reloads |
| a 256-colour cube slot 16-231 | `38;5;184` | no: xterm's fixed table, made for dark backgrounds |
| a grey-ramp slot 232-255 | `38;5;252` | no: same table |
| a truecolour value | `38;2;248;248;242` | never: the tool chose the colour itself |

Most fixed-colour defaults assume a dark background. Under a light variant, grey 252 (`#d0d0d0`)
is about 1.5:1 on a near-white background, unreadable. `amo palette --check FILE` reports, per
variant, how many of xterm's fixed colours fall below 4.5:1 on `base00`.

What reaches the fixed colours:

- **kitty 0.47 and later:** the built-in `kitty` template sets `palette_generate semantic`, so
  kitty derives 22-255 from the palette: the grey ramp runs from near the background (232) to
  near the foreground (255), and the cube is mapped the same way. Grey 252 goes from 1.5:1 to
  10.9:1 on a light background. A template of your own (`source: path`) gets this by adding
  the line `palette_generate semantic`. For older kitty, or to keep xterm's colours, use
  `apps.kitty.template: kitty-fixed`. The reasoning and measurements are in
  [design.md](design.md), "Light variants and fixed colours".
- **Other terminals:** foot takes `0`-`255` keys but does not generate them; a tinted or
  matugen terminal template sets 0-15 (sometimes 16-21) only.
- **Truecolour tools:** only the tool's own setting helps (an ANSI-only or light theme of its
  own).
- **A tool's config that names cube slots** is best replaced by one made from the palette, as
  below for `LS_COLORS`.

### Worked example: LS_COLORS from a dark-only set

Under a light variant, `ls` and `lsd` showed yellow and green file names that were hard to read
in every tone. The cause was not the palette: `LS_COLORS` came from trapd00r/LS_COLORS, which
names cube slots (`*.md=38;5;184`, `*.toml=38;5;178`, `di=38;5;30`); `lsd` reads `LS_COLORS`
too. 184 is `#d7d700`, about 1.5:1 on a near-white background. With `LS_COLORS` from amo's
`vivid` template (next section) the same files took the palette's colours, which the contrast
check holds at 4.5:1 on `base00`.

## LS_COLORS with vivid

The built-in `vivid` template renders a [vivid](https://github.com/sharkdp/vivid) theme,
`vivid.yml`, from the palette; amontillado never runs vivid itself. Add the app:

```yaml
theme:
  apps:
    vivid: {}                  # builtin: vivid.yml in the profile directory
```

Then build `LS_COLORS` from it in the shell (zsh or bash):

```sh
amo_ls_colors() {
  local theme="${XDG_CACHE_HOME:-$HOME/.cache}/theme/current/vivid.yml"
  [ -r "$theme" ] && command -v vivid >/dev/null || return
  export LS_COLORS="$(vivid generate "$theme")"
}
amo_ls_colors
```

`vivid generate` writes truecolour codes; `vivid -m 8-bit generate` writes 256-colour ones, which
a terminal with `palette_generate semantic` remaps again. Completion menus in zsh take the same
colours with:

```zsh
zstyle ':completion:*' list-colors ${(s.:.)LS_COLORS}
```

(Set it after `LS_COLORS`, and again whenever `LS_COLORS` changes: the style holds a copy.)

## Reaching running shells

A reload command (`theme.apps.<app>.reload`) reaches the terminal, but environment variables
such as `LS_COLORS` live in each shell. A prompt hook can check, once per prompt, whether the
applied theme changed and re-source what it needs. `<cache>/current` links to the profile
(`current -> default`) and each `amo theme apply` points the profile at a new generation
directory, so the hook resolves the whole chain (`readlink -f`) and compares it with the last
one it saw; that costs about nothing per prompt.

zsh:

```zsh
autoload -Uz add-zsh-hook
typeset -g _amo_theme_seen=
_amo_theme_precmd() {
  local now
  now=$(readlink -f "${XDG_CACHE_HOME:-$HOME/.cache}/theme/current") || return
  [[ $now == $_amo_theme_seen ]] && return
  _amo_theme_seen=$now
  amo_ls_colors
  zstyle ':completion:*' list-colors ${(s.:.)LS_COLORS}
  # Re-source anything else the theme rendered here, e.g. the shell template's colors.sh.
}
add-zsh-hook precmd _amo_theme_precmd
```

bash:

```bash
_amo_theme_seen=
_amo_theme_prompt() {
  local now
  now=$(readlink -f "${XDG_CACHE_HOME:-$HOME/.cache}/theme/current") || return
  [[ $now == "$_amo_theme_seen" ]] && return
  _amo_theme_seen=$now
  amo_ls_colors
}
PROMPT_COMMAND="_amo_theme_prompt${PROMPT_COMMAND:+;$PROMPT_COMMAND}"
```

The first prompt of a new shell runs the hook too, so the hook can replace the startup call.

## Prompt and highlighter

### powerlevel10k

Segment colours given as ANSI numbers 0-15 (`POWERLEVEL9K_DIR_FOREGROUND=4`) follow the palette
with no reload at all. Numbers 16-255 follow it only through the terminal's palette generation
(above). Hex colours do not follow it. To give p10k palette colours as hex, add the built-in
`shell` template (`colors.sh`: `export AMO_BASE0D='#rrggbb'`, every base24 key and role), set
the parameters from it, and reload p10k from the prompt hook:

```zsh
# in the hook above, after the profile changed:
source "${XDG_CACHE_HOME:-$HOME/.cache}/theme/current/colors.sh"
typeset -g POWERLEVEL9K_DIR_FOREGROUND=$AMO_BASE0D
typeset -g POWERLEVEL9K_VCS_CLEAN_FOREGROUND=$AMO_BASE0B
(( $+functions[p10k] )) && p10k reload
```

`p10k reload` re-reads the `POWERLEVEL9K_*` parameters; without it the old colours stay until
the shell restarts.

### fast-syntax-highlighting

Its default theme names ANSI colours (`green`, `yellow`, `red,bold`) and slots 12 and 18,
which amo's `kitty` template sets (18 is `base01`), so it follows the palette with no reload.
A style that names a cube slot or hex colour does not. Override single styles from the hook
(keys are the theme file's names, prefixed by the current theme name):

```zsh
FAST_HIGHLIGHT_STYLES[${FAST_THEME_NAME}path]="fg=${AMO_BASE0C}"
```

or render a whole theme file with a template of your own (`source: path`, `format: mustache`,
an `.ini` in fast-syntax-highlighting's theme format) and load it once with `fast-theme PATH`,
which stores it; run it again when the file changes.

## The fallback: a dark terminal under a light desktop

If the tools you use cannot be fixed, keep the terminal dark while the rest of the desktop
follows the scheme:

```yaml
theme:
  variant: system
  apps:
    kitty: {variant: dark}
```

`apps.<app>.variant` wins over `theme.variant` for that app only.
