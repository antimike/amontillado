# Changelog

All notable changes to amontillado are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Palettes (v0.2 theme engine): per variant (dark, light), all 24 base24 colours plus roles
  (accent, selection, error, ...); base24 keys and roles a source leaves out are derived in
  OKLCH. `amo palette --from-scheme FILE [FILE]` converts one tinted-theming scheme (base16 or
  base24, current or legacy format), or a family's dark and light pair, into a palette.
- Contrast checks: WCAG 2 ratios over fixed pairs (body text 7, syntax and labels 4.5, comments
  and borders 3), per variant. `amo palette --from-scheme` adjusts failing colours in OKLCH
  lightness (foregrounds first, the accent last, never the backgrounds), logging each change and
  listing it under `adjusted`; `theme.contrast: adjust | report | off` and `--no-adjust` say
  whether. `amo palette --check FILE` reports a palette file's failing pairs.
- The config file's `theme:` block (cache, profile, generator, variant, contrast, wallpaper
  reload, and per app source, template, format, output, reload, variant, render_with), checked
  on every load with errors naming the key; nothing uses it yet.
- Built-in templates (mustache, variables-only: every base24 colour and role in the app's own
  syntax): kitty, gtk (`@define-color`, for waybar, swaync, wlogout and GTK), rofi, hyprland (a
  Lua table), hyprlock, sway, dunst (a small complete `dunstrc.d` drop-in), nvim
  (`palette.lua`), shell and json. `amo theme templates [APP]` lists them, or one's variables.
- `amo theme apply [--palette NAME|FILE]`: render every app under `theme.apps` (built-in
  templates, or `source: path` mustache files) into a new generation of the profile and swap
  it in atomically (`<cache>/<profile>` and `current` are symlinks), then run each app's reload
  command and the wallpaper hook; a render error changes nothing, a failing reload warns.
  `--palette` takes a file or a preset in `$XDG_CONFIG_HOME/amontillado/palettes/`; without it
  the profile's palette is re-rendered. `--profile`, `--variant`, `--app NAME` (re-render a
  subset), `--no-adjust`, `--no-activate`, `--no-reload`, `--dry-run`.
- The template registry: per source (builtin; tinted-theming, matugen-themes and pywal16
  templates, pinned to a commit with each file's sha256), the templates for each app, their
  output files and whether each is a complete theme or variables only. `amo theme sync
  [--check]` downloads the templates the config uses (one HTTPS request per file, hash-checked,
  nothing kept on a mismatch); `amo theme apply` renders tinted, `url` and `path` mustache
  templates and never uses the network. `amo theme templates [APP]` lists every source.
- pywal-format templates (pywal16's `{color0.rgba}` markers, with its colour properties and
  `lighten`, `darken`, `saturate`, `foxify`, `adjust_alpha`), rendered by amontillado over
  `color0`-`color15` by the base24 ANSI table, so `source: pywal` apps apply.
- `docs/examples/nvim/`: a lush.nvim spec over the applied `palette.lua` (roles for the interface,
  base24 hues for syntax) and a watcher that re-runs `:colorscheme` after each `amo theme apply`.
  Or tinted-nvim v1 fed the palette as a custom scheme, re-applied by the same watcher.
- `amo theme current [--profile P]`: the applied palette, picture and time; warns when apps
  were rendered from different palettes.
- `amo index --rehash`: hash every file again (see the hash cache below).
- `amo crop PICTURE W:H [--at F]`: write the largest W:H crop of a record's original beside it,
  centred unless `--at` moves it, recorded (`derived_from`, `crop`) and indexed. On a terminal,
  `amo list --aspect W:H` offers to crop the pictures it found no such file for;
  `--non-interactive` never asks.
- Thumbnails: each record can name a small preview (`thumbnail`, at `.amo/thumbnail.jpg`, never
  one of its files). `amo fetch` keeps Wallhaven's thumbnail; `amo add` and `amo index` make one
  of the default file. `amo list --format rofi` prints each path with its thumbnail as the icon,
  for `rofi -dmenu -show-icons`. The index is upgraded to schema 4 in place.

### Changed

- Python 3.11 or later (was 3.10, end of life since 2026-10).
- New runtime dependency: `pystache` (MIT), for rendering mustache templates.
- `amo index` hashes only files whose size or mtime changed since the last index; the index
  keeps both per file (schema 3; a schema 2 index is upgraded in place).
- `amo fetch` names each record from up to three of its Wallhaven tags and its id
  (`food-dessert-ice-cream-4l36wr`; the category when no tag is usable), in a directory of that
  name; records fetched earlier keep theirs.

- `hue_share` is the weight of the heaviest 60° arc of hues, and `hue_name` names the sector
  holding that arc's mean, so a hue on a sector boundary is no longer split (metrics version
  2: `amo index` remeasures every file). One hue now holds 80% of the calibration sample (was
  68%).

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
