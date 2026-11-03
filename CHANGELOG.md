# Changelog

All notable changes to amontillado are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-11-03

The theme engine: a palette from a picture, a preset or a tinted-theming scheme, checked for
contrast, rendered into each configured app's file and swapped in at once.

### Added

- Palettes: per variant (dark, light), all 24 base24 colours plus roles (accent, selection,
  error, ...); base24 keys and roles a source leaves out are derived in OKLCH. `amo palette
  PICTURE` makes one with both variants from a generator: matugen (>= 4.0) or wallust (>= 3.0),
  detected at run time (`theme.generator`, `--generator`). `amo palette --from-scheme FILE
  [FILE]` converts one tinted-theming scheme (base16 or base24, current or legacy format), or a
  family's dark and light pair.
- Named hues (`theme.hues`, `--hues`): by default amontillado assigns `base08`-`base0F` itself,
  each at a fixed nominal hue with the picture's chroma and a calibrated lightness, so red stays
  red; `generator` keeps the generator's own colours. Calibrated on the 13 library pictures: the
  dark variant matches or beats the hand-made baseline on every one.
- Contrast checks: WCAG 2 ratios over fixed pairs (body text 7, syntax and labels 4.5, comments
  and borders 3), per variant. Failing colours are adjusted in OKLCH lightness (foregrounds
  first, the accent last, never the backgrounds; away from the background, or across it when
  that cannot pass), each change logged and listed under `adjusted`; `theme.contrast: adjust |
  report | off` and `--no-adjust` say whether. `amo palette --check FILE` reports a palette
  file's accent metrics (hues on their ANSI name, distinctness) and failing pairs.
- `amo theme apply [PICTURE | --palette NAME|FILE]`: render every app under `theme.apps` into a
  new generation of the profile and swap it in atomically (`<cache>/<profile>` and `current`
  are symlinks), then run each app's reload command and the wallpaper hook; a render error
  changes nothing, a failing reload warns. A PICTURE's palette is generated, its wallpaper
  linked and recorded as shown; `--palette` takes a file or a preset in
  `$XDG_CONFIG_HOME/amontillado/palettes/`; without either the profile's palette is
  re-rendered. `--profile`, `--variant`, `--hues`, `--app NAME` (re-render a subset),
  `--no-adjust`, `--no-activate`, `--no-reload`, `--dry-run`. No network.
- `amo theme current [--profile P]`: the applied palette, picture and time; warns when apps
  were rendered from different palettes.
- Templates in three formats, all rendered by amontillado: mustache (tinted-theming's builder
  spec, with every role as well), pywal (pywal16's markers, properties and functions, checked
  against pywal16 itself) and matugen (the subset matugen-themes uses, over a Material view of
  the palette, checked byte for byte against matugen 4.2.0 on all of matugen-themes). An app
  can have matugen render its template instead (`render_with: matugen`), with matugen's colours.
- Built-in templates (variables-only, every colour and role in the app's own syntax): kitty,
  gtk (`@define-color`, for waybar, swaync, wlogout and GTK), rofi, hyprland (a Lua table),
  hyprlock, sway, dunst (a small complete `dunstrc.d` drop-in), nvim (`palette.lua`), shell and
  json.
- The template registry: per source (builtin; tinted-theming, matugen-themes and pywal16,
  pinned to a commit with each file's sha256) the templates for each app, their output files
  and whether each is a complete theme or variables only. `amo theme sync [--check]` downloads
  the templates the config uses (one HTTPS request per file, hash-checked); `amo theme
  templates [APP]` lists them, or one's variables.
- `docs/examples/nvim/`: three ways to theme nvim from the applied palette (a lush.nvim spec,
  tinted-nvim fed the palette as a custom scheme, matugen-themes' colourscheme), sharing a
  watcher that re-runs `:colorscheme` after each `amo theme apply`.
- The config file's `theme:` block (cache, profile, generator, hues, variant, contrast,
  wallpaper reload, and per app source, template, format, output, reload, variant,
  render_with) and `crop:` block, checked on every load with errors naming the key.
  `amo config init` writes a commented template of every key (its meaning, trade-offs and
  default); `amo config check [FILE]` validates a config, its templates and output files.
- `amo crop PICTURE W:H [--at F]`: write the largest W:H crop of a record's original beside it,
  centred unless `--at` moves it, recorded (`derived_from`, `crop`) and indexed. `--interactive`
  places the box by hand (move, zoom; Enter crops, Esc writes nothing), previewed in the
  terminal with the kitty graphics protocol or in an image viewer (`crop.preview`,
  `crop.viewer`). On a terminal, `amo list --aspect W:H` offers to crop the pictures it found no
  such file for, centred or interactively; `--non-interactive` never asks.
- `amo list` search: `--tag` (repeatable), `--site`, `--category`, `--license`, `--author`,
  and `--where SQL`, an expression over a read-only view of the index that includes each
  record's whole info file as JSON. Purity and the NSFW root still decide what is printed.
- `amo add` records where a picture came from: `--source-url`, `--image-url`, `--site`,
  `--title`, `--author`, `--license` (SPDX), `--purity`, `--category`, `--tags`, `--uploaded`,
  or per picture from `amo add --from-json FILE`.
- Thumbnails: each record can name a small preview (`thumbnail`, at `.amo/thumbnail.jpg`, never
  one of its files). `amo fetch` keeps Wallhaven's thumbnail; `amo add` and `amo index` make one
  of the default file. `amo list --format rofi` prints each path with its thumbnail as the icon,
  for `rofi -dmenu -show-icons`.
- `amo index --rehash`: hash every file again (see the hash cache below).

### Changed

- Python 3.11 or later (was 3.10, end of life since 2026-10).
- New runtime dependency: `pystache` (MIT), for rendering mustache templates. matugen and
  wallust are optional external programs.
- The index is at schema 6 (thumbnails, the hash cache, provenance columns, each record's info
  file as JSON), upgraded in place from any earlier one; the next `amo index` fills the new
  columns. amontillado 0.1.0 refuses an index this version has opened.
- `amo index` hashes only files whose size or mtime changed since the last index.
- `amo fetch` names each record from up to three of its Wallhaven tags and its id
  (`food-dessert-ice-cream-4l36wr`; the category when no tag is usable), in a directory of that
  name; records fetched earlier keep theirs.
- `hue_share` is the weight of the heaviest 60° arc of hues, and `hue_name` names the sector
  holding that arc's mean, so a hue on a sector boundary is no longer split (metrics version
  2: `amo index` remeasures every file). One hue now holds 80% of the calibration sample (was
  68%).
- `--help` no longer ends options with `(default: None)` or `(default: False)`; a flag that
  overrides a config key names it and its default.

## [0.1.0] - 2026-10-28

### Added

- Package skeleton: `amontillado` and `amo` commands (`--version`, `--loglevel`), uv build,
  ruff, pytest, CI, gitleaks pre-commit hook.
- `amo measure FILE...`: an image's lightness, chroma, hue, hue spread, warmth and detail in
  OKLCH, with its classes (dark, muted, busy, ...), as YAML.
- Records: a directory per picture holding its files and an `info.yaml` (id, optional unique
  name, source, and per file its SHA-256, size and metrics).
- `amo index [--check]`: fills in and updates the derived fields of every record (never the
  authored ones), follows a file renamed inside its record by content hash, reports images
  outside a record, missing files and conflicting records, and rebuilds the SQLite index,
  keeping the usage history. Logs one summary line (routine heals only at
  `--loglevel debug`), with a progress bar on a terminal.
- `amo list`: the default file of each indexed record by class (`--dark`, `--muted`,
  `--sparse`, `--hue blue`, `--monochrome`, `--warm`, ...), `--random N`; NSFW records only
  with `--purity`. `--aspect 21:9` prints each record's file of that aspect ratio instead.
- `amo shown PICTURE...`: records that pictures were shown, by record id, in the usage history;
  a picture is a file, a record directory, a name, an id or a unique id prefix.
- `amo add FILE... [--name N] [--nsfw] [--force]`: makes each image file a record of its own
  and indexes it; refuses content already in the library unless `--force`.
- `amo fetch`: searches Wallhaven in random order (`--tags`, `--purity`, `--category`,
  `--atleast`, `--ratio`, `--color`), measures each thumbnail, and keeps the ones that match the
  look filters (`--dark`, `--hue blue`, ...) as indexed records, up to `--count`, examining at
  most `--max-candidates`. Each full image is judged again: one that no longer matches is kept
  but not counted, or deleted with `--discard-mismatches`. `--busy-from full` judges busy and
  sparse only on the full image; `--dry-run` downloads nothing.
  `--color` takes any hex colour and searches by the nearest of Wallhaven's 29 swatches. Paced under Wallhaven's rate limit, with back-off on HTTP 429.
- `amo fetch --test-set`: keeps one wallpaper per bucket (dark, light, muted, saturated, busy,
  sparse, monochrome, multi-hue), each filling one bucket only, and prints `BUCKET<TAB>PATH`
  lines; fails if a bucket stays empty.
- `tools/calibrate.py` (`just calibrate`): samples random Wallhaven thumbnails and reports
  metric distributions and class shares. The class thresholds are calibrated with it on 400
  images, so each class holds roughly a fifth of them; `--warm` and `--cool` leave out muted
  images.
- `api_key_command` in `config.yaml`, or `WALLHAVEN_API_KEY`: the Wallhaven API key, needed for
  nsfw results, never logged or stored.

### Fixed

- Log messages go to stderr, not stdout.
