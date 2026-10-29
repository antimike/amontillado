# Spike: tinted-theming before designing templates

Bead `amo-aqp.1`, 2026-10-28, revised 2026-10-29 after MH's questions. Question: can amontillado's
palette be exported as base16/base24 so that existing app templates do the rendering, and what
would amontillado add over `tinty`? Sources: the tinted-theming `home` repository (`styling.md`,
`builder.md`, the Tinted8 spec, the template list), tinty's README and USAGE, tinted-builder's
source, the matugen, matugen-themes, wallust, pywal16 and wpgtk repositories (licences and
activity through the GitHub API), and matugen 3.1.0 run locally on the test-set images. Facts and
analysis are kept apart; the last section is the direction MH agreed in principle (2026-10-29),
the input for the v0.2 design.

## What tinted-theming is (facts)

- **Schemes** are YAML: `system` (base16, base24, or tinted8), `name`, `author`, optional `slug`,
  `description`, `variant` (`dark` / `light`), and `palette` with `base00`-`base0F` (base24 adds
  `base10`-`base17`), as hex.
- **Roles (base16).** `base00`-`base07` are a neutral ramp (background, lighter background,
  selection, comments, dark foreground, foreground, light foreground, lightest foreground);
  `base08`-`base0F` are accents tied to hues and syntax roles: red (variables), orange
  (constants), yellow (classes), green (strings), cyan (regex), blue (functions), magenta
  (keywords), brown (deprecated). Terminals map them onto ANSI 0-15; base16 leaves the bright
  colours equal to the normal ones, base24 adds distinct bright colours. The spec sets **no
  contrast requirement**.
- **Tinted8** (spec 0.2.0, beta): eight ANSI hues with bright and dim variants, a `syntax`
  namespace (TextMate scopes) and a `ui` namespace with **`ui.accent.normal`** ("focus rings and
  active borders"), `ui.border.normal`, `ui.selection.*`, `ui.status.*`. How many templates
  support it yet is not documented.
- **Templates** are mustache files plus a `templates/config.yaml`. Variables per colour: hex
  (`base08-hex`, and per channel), RGB 0-255, 16-bit RGB, and 0-1 decimals; no HSL. Scheme
  variables: `scheme-name`, `scheme-slug`, `scheme-variant`, `scheme-is-dark-variant`, ...
  tinted-builder builds the variables by iterating over **every** palette key
  (`for (name, color) in scheme.palette`, `src/template/base16.rs`, 0.14.0), so an extra key
  `accent` would give `accent-hex`; whether the scheme parser accepts extra keys was not checked.
- **The template library is independent of tinty.** Each app's templates are their own
  repository under the tinted-theming organisation, all **MIT**, all pushed within the last month
  (2026-10): `tinted-terminal` (kitty, foot and other terminals), `base16-rofi`, `base16-waybar`,
  `base16-dunst`, `tinted-shell`, `tinted-nvim`, `base16-gtk-flatcolor` (a whole GTK3 theme), and
  the scheme catalogue `schemes`. Unofficial ones exist for Hyprland, Sway, swaylock and mako.
  **None** for hyprlock, swaync, wlogout or libadwaita. Most are complete themes: they assign
  palette slots to the app's elements (rofi's selected row, waybar's selectors).
- **tinty** (Rust, **GPL-3.0**, the only GPL piece) is a manager: `tinty sync` clones the template
  repositories named in `config.toml` (`[[items]]`: `path` (a Git URL or a local directory),
  `revision`, `themes-dir`, `hook`, `supported-systems`), `tinty apply <scheme>` copies each
  item's rendered file and runs its hook (with `TINTY_THEME_FILE_PATH`, `TINTY_SCHEME_ID` in the
  environment), `tinty current` / `tinty init` keep and restore the current scheme. It reloads
  nothing itself: each hook does. Its shell integration recolours a terminal with escape
  sequences, but only the shell that runs it. `tinty generate-scheme IMAGE` uses
  `tinted-scheme-extractor`, which calls itself early-stage. tinty is not installed here.

## Other template libraries (facts)

- **matugen-themes** (`InioX/matugen-themes`, **MIT**, separate from matugen, which is
  GPL-2.0): about 60 templates in matugen's own template syntax, over Material roles (which have
  a real accent: `primary`, `on_primary`, ...). For the theming plan's apps: `hyprland-colors.lua`
  (the Lua config of D62), `gtk-colors.css` (libadwaita colour overrides), `kitty-colors.conf`,
  `rofi-colors.rasi`, `dunstrc-colors`, `sway-colors.conf`, `swaybar-colors.conf`, `mako`,
  `foot-colors.ini`, `neovim`, `tmux-colors.conf`, a generic `colors.css`, and
  `terminal-sequences` (recolours open terminals, as pywal does). None for waybar, swaync,
  wlogout or hyprlock.
- **pywal16 templates** (inside `eylles/pywal16`, **MIT**): about 55, Python `str.format` over
  positional colours (`{color0}`-`{color15}`, `{background}`, `{foreground}`, `{cursor}`).
  Mostly variable definitions (`colors-waybar.css` is `@define-color color0 ...`), some complete
  themes (rofi). Positional: `color1` is whatever the generator put there, not "red". wallust
  reads the same format.
- **wpgtk** (GPL-2.0): a GUI over pywal (its generator), with hand-editing of generated schemes,
  schemes saved per wallpaper, colour sorting for readability, and keyword templates over pywal's
  16 colours. Its README does not mention Wayland. It overlaps amontillado's own job (managing
  wallpapers) and inherits pywal's generator: not adopted.
- Everything else found is a fixed palette with per-app ports (Catppuccin, rendered by
  `catppuccin/whiskers`) or terminal-only (Gogh, iTerm2-Color-Schemes). tinted-theming and
  matugen-themes are the only broad libraries that map colours to roles.

## Generators against base16 (facts)

- **matugen 3.1.0** (Fedora's package, installed): Material You roles only (`primary`,
  `secondary`, `tertiary`, `error`, surfaces, `on_*`), from three accent hues. Its JSON has no
  base16 block. **matugen 4.0** added base16 output (`--base16-backend`, template keys like
  `base16.base00.dark.hex`) and changed the default JSON; 4.1.0 is current. Fedora 44 and the
  `sdegler/hyprland` COPR have only 3.x (checked with `dnf list`, 2026-10-28). matugen renders
  templates itself (`[templates.<name>]` in its config) and takes extra render data with
  `--import-json` (its `--help`).
- **wallust** produces a 16-colour terminal palette plus background and foreground: close to
  base16's shape, but its colours are clustered from the image, not assigned to the hues base16
  names (its `color1` need not be red).

## Fit (analysis)

- **base16 has no accent.** Its accents are named hues for code syntax, so a red accent must look
  red even when the wallpaper has no red: a generator has to synthesise hues the image lacks
  (matugen 4's base16 backend does; image clustering does not). What a wallpaper-driven theme
  wants most, "the accent colour" for borders, bars, focus and selection, has no base16 slot;
  templates borrow `base0D` (blue) by convention, so a red wallpaper gets blue highlights unless
  the generator puts the wallpaper's colour into `base0D` (and the terminal's "blue" is then red).
  This affects every template for interface elements, not one app.
- **Extra palette keys help only templates that use them**: ours, and any upstream template we
  enrich. Upstream templates reference `base00`-`base17` only.
- **Material roles map onto the neutral ramp well** (surfaces → `base00`-`base02`, outline →
  `base03`, `on_surface_variant` / `on_surface` → `base04`-`base05`), and onto the accents
  poorly: three accent hues and error for eight slots.
- **waybar, swaync and wlogout all style with GTK CSS**, so one colour-variables file serves all
  three (each one's `style.css` imports it). Only hyprlock lacks any template; matugen-themes
  covers libadwaita.
- **Two template styles, two maintenance costs.** Complete themes name an app's elements and
  break when the app renames them (rofi changed between 1.7 and 2.0); a fork of every one would
  have to follow each app. Variables-only templates export the palette in the app's syntax (GTK
  `@define-color`, rofi `* { accent: #...; }`, kitty `color0`-`color15`, a Hyprland Lua table),
  which almost never changes, and leave the mapping onto elements to the user's own config
  (chezmoi's, for MH).
- **tinty adds** template-repository pinning, apply-plus-hook, the current-scheme state and a
  catalogue of preset schemes. Rendering mustache from Python and running hooks is a small part
  of amontillado; pinning comes from chezmoi externals or amontillado's own registry. **tinty
  does not do**, and amontillado would: choose wallpapers (filters, usage, per-output sets from
  one palette cluster), generate a palette with checked contrast, write the per-profile cache of
  the chezmoi plan (`~/.cache/theme/<profile>/`, D39; tinty writes to its own data directory),
  and switch wallpaper and theme as one step.
- **Licensing.** Copying or adapting an MIT template (tinted-theming, matugen-themes, pywal16)
  into amontillado (MIT) needs only its copyright and permission notice kept, in the file or a
  `THIRD-PARTY.md`. Nothing is copied from GPL sources (tinty, matugen, wpgtk). Templates fetched
  at run time are not redistributed by amontillado.

## Direction (agreed in principle by MH, 2026-10-29)

1. **amontillado renders; it runs neither tinty nor pywal.** Template libraries are optional
   *sources*, so amontillado stays an independent tool that reads their formats.
2. **The palette** holds base24 (`base00`-`base17`) plus roles: accent (with its `on` colour),
   secondary accent, border, selection, status colours, and the variant. Each template format
   gets a *view* of it:

   | Format | View | Rendered by |
   |---|---|---|
   | `mustache` | `base00`-`base17` plus the roles as extra keys | amontillado (a Python mustache library) |
   | `pywal` | `color0`-`color15` (base24's ANSI mapping), background, foreground, cursor | amontillado (a small renderer) |
   | `matugen` | Material roles | matugen, with the palette passed by `--import-json` |

3. **Built-in templates are variables-only** and carry every role, accent included, so no overlay
   pass is needed and maintenance stays near zero. Complete looks come from the other sources.
4. **Per-app configuration** in amontillado's YAML config (no other formats until one is needed):

   ```yaml
   apps:
     kitty:    {source: builtin, reload: "pkill -USR1 kitty"}
     rofi:     {source: tinted}                     # complete theme from base16-rofi
     waybar:   {source: builtin, output: gtk-colors.css, reload: "pkill -USR2 waybar"}
     hyprland: {source: matugen-themes, template: hyprland-colors.lua, reload: "hyprctl reload"}
     nvim:     {source: builtin}                    # palette.lua, for a lush spec
   ```

   - `source`: `builtin`, `tinted`, `matugen-themes`, `pywal`, a URL or a path. The default per
     app is the first that has a template, in that order (most role-aware first), from a registry
     amontillado ships (app → repository, template path, pinned revision).
   - `format`: defaults from the source; set it for a URL or a path.
   - `output` (the file name in the cache), `reload` (a command), and whether the result is a
     complete theme or variables only (the user's config must then map the variables).
   - **A URL must be pinned** (a commit URL plus `sha256`) and is cached: some outputs are code
     (`hyprland.lua`, sourced shell scripts), so an unpinned template would run someone else's
     code at every theme switch.
5. **nvim and lush.** The built-in `nvim` template renders `palette.lua` (the base24 colours, the
   roles and the variant) into the cache. A lush spec in the user's nvim config loads it and maps
   roles onto highlight groups, as the chezmoi theming plan intends; a file watcher there re-runs
   `colorscheme` when `palette.lua` changes, so nvim needs no reload command. Users without lush
   pick `tinted` (tinted-nvim) or `matugen-themes` (`neovim`) for the same app. amontillado's docs
   carry an example lush spec, not a plugin.
6. **Generator**: decided in the chezmoi plan's step 1, with base16 in mind. matugen 4's base16
   backend is the only candidate that assigns the named hues and pairs contrast by design; try it
   before wallust. It needs matugen ≥ 4.0 (Fedora ships 3.1.0: COPR, cargo or the release binary).

**Open:**

- The `matugen` format for palettes matugen did not make (presets, wallust): amontillado would
  synthesise Material roles for `--import-json`, or the format works only with matugen-generated
  palettes.
- Whether tinted-builder's scheme parser accepts extra palette keys (it matters only for
  rendering tinted schemes with tinted's own tools, not for amontillado's renderer).
- Tinted8's `ui.accent.normal` may close the accent gap upstream; watch its template support.

Rejected: tinty as the renderer (an extra data directory and copy step, a Rust binary on every
machine, for glue amontillado needs anyway); forking tinted-theming's complete themes for every
app (they follow app changes, our forks would not); wpgtk (a pywal GUI that overlaps
amontillado's own job); `tinty generate-scheme` as the generator (early-stage extractor, no
contrast handling).
