# Spike: tinted-theming before designing templates

Bead `amo-aqp.1`, 2026-10-28. Question: can amontillado's palette be exported as base16/base24 so
that tinted-theming's app templates do the rendering, and what would amontillado add over
`tinty`? Sources: the tinted-theming `home` repository (`styling.md`, `builder.md`, template
list), tinty's README and USAGE, matugen's and wallust's READMEs, and matugen 3.1.0 run locally on
the test-set images. Facts are marked as such; the recommendation at the end is a proposal for MH.

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
- **Templates** are mustache files plus a `templates/config.yaml`. Variables per colour: hex
  (`base08-hex`, and per channel), RGB 0-255, 16-bit RGB, and 0-1 decimals; no HSL. Scheme
  variables: `scheme-name`, `scheme-slug`, `scheme-variant`, `scheme-is-dark-variant`, ...
- **Templates exist** (official) for kitty, dunst, rofi, waybar, fzf, tmux, the shell, GTK3
  (`base16-gtk-flatcolor`, a whole GTK theme), vim and nvim (`tinted-vim`, `tinted-nvim`);
  **unofficial** ones for Hyprland, Sway, swaylock, mako. **None** for hyprlock, swaync, wlogout or
  libadwaita (GTK4 `gtk.css` colour overrides).
- **tinty** (Rust, GPL-3.0) is the manager: `tinty sync` clones the template repositories named
  in `config.toml` (`[[items]]`: `path` (a Git URL or a **local directory**), `themes-dir`,
  `hook`, `supported-systems`), `tinty apply <scheme>` copies each item's rendered file and runs
  its hook (with `TINTY_THEME_FILE_PATH`, `TINTY_SCHEME_ID` in the environment), `tinty build`
  renders a template directory. Custom schemes live in
  `~/.local/share/tinted-theming/tinty/custom-schemes/`. `tinty generate-scheme IMAGE` makes a
  scheme from an image through `tinted-scheme-extractor`, which calls itself early-stage.
  tinty is not installed here.

## Generators against base16 (facts)

- **matugen 3.1.0** (Fedora's package, installed): Material You roles only (`primary`,
  `secondary`, `tertiary`, `error`, surfaces, `on_*`), from three accent hues. Its JSON has no
  base16 block. **matugen 4.0** added base16 output (`--base16-backend`, template keys like
  `base16.base00.dark.hex`) and changed the default JSON; 4.1.0 is current. Fedora 44 and the
  `sdegler/hyprland` COPR have only 3.x (checked with `dnf list`, 2026-10-28).
- **wallust** produces a 16-colour terminal palette plus background and foreground: close to
  base16's shape, but its colours are clustered from the image, not assigned to the hues base16
  names (its `color1` need not be red).

## Fit (analysis)

- **base16 is an editor-syntax palette.** Its accents are named hues, so a red accent must look
  red even when the wallpaper has no red: a generator has to synthesise hues the image lacks
  (matugen 4's base16 backend does; image clustering does not). What a wallpaper-driven theme
  wants most, "the accent colour" for borders, bars, focus and selection, has no base16 slot;
  templates pick `base0D` (blue) or `base0A` by convention, so a red wallpaper gets blue window
  borders unless the palette bends the hue names.
- **Material roles map onto the neutral ramp well** (surfaces → `base00`-`base02`, outline →
  `base03`, `on_surface_variant` / `on_surface` → `base04`-`base05`), and onto the accents
  poorly: three accent hues and error for eight slots.
- **What tinty does not do**, and amontillado would: choose wallpapers (filters, usage,
  per-output sets from one palette cluster), generate a palette with checked contrast, keep the
  per-profile cache of the chezmoi plan (`~/.cache/theme/<profile>/`, D39; tinty writes to its
  own data directory), and switch a theme as one step with the wallpaper.
- **What amontillado should not do**: maintain per-app templates for kitty, dunst, rofi, waybar,
  nvim and the rest. tinted-theming has them and keeps them working as the apps change.

## Recommendation (proposal, for MH)

1. **The palette is base24, plus an accent block.** amontillado's palette file is a base24 scheme
   (so every tinted-theming template works, terminals get distinct bright colours) with an extra
   `accent` role (primary, its `on` colour, a secondary) for UI templates. Whether tinty passes
   extra palette keys through to templates is not documented: to check; if not, the accent goes
   in a second file.
2. **Render with tinty, not our own renderer.** amontillado writes the scheme into tinty's
   custom-schemes directory and runs `tinty apply`; each item's hook copies the rendered file into
   `~/.cache/theme/<profile>/` and reloads the app, so the chezmoi include lines stay as planned.
   Templates for the apps tinted-theming lacks (hyprlock, swaync, wlogout, libadwaita colours)
   are written in tinted-theming's format, in a local template directory (`path` may be local),
   so there is one renderer. tinty runs as a separate program: its GPL does not touch
   amontillado's MIT licence.
3. **Generator: decide in the chezmoi plan's step 1, with base16 in mind.** matugen 4's base16
   backend is the only candidate that assigns the named hues and pairs contrast by design; try it
   before wallust. That needs matugen ≥ 4.0 (Fedora ships 3.1.0: COPR, cargo or the release
   binary).
4. **First steps of the v0.2 design:** install tinty, apply a hand-written base24 scheme to kitty
   and waybar through a hook into `~/.cache/theme/current/`; check the extra-keys question; run
   matugen 4 with `--base16-backend` on the eight test-set wallpapers and check contrast with
   `tools/term-contrast` (chezmoi).

Rejected: rendering tinted-theming's mustache templates inside amontillado (duplicates tinty);
writing our own per-app templates (maintenance tinted-theming already does); `tinty
generate-scheme` as the generator (early-stage extractor, no contrast handling).
