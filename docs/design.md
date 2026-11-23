# Design

Status: v0.1 (2026-10-28): the library, index, query commands and the fetcher, test sets
included, class thresholds calibrated. v0.2 (2026-11-03): the theme engine as agreed
(2026-10-30, "Theme engine (v0.2)"), built: palettes from pictures (matugen and wallust, named
hues calibrated), presets and tinted-theming schemes, contrast checks, the mustache, pywal and
matugen formats, the registry and `amo theme sync`, apply with profile swaps; also interactive
crops, `amo list` search over the index, and the commented config template. v0.3
(2026-11-05): the built-in libadwaita template and the `{variant}` reload placeholder for a
colour-scheme hook ([colour-scheme-hooks.md](colour-scheme-hooks.md)), `amo name` (also
`--from-tags`) and `amo add-derived`. v0.4 (2026-11-13): optional version control (the
`on_change` hook, git-annex libraries, info files merged by key, "git-annex libraries"), the
GTK4-only `libadwaita-vars` template ("Template sources") with GNOME's palette remapped
(`gnome-*-hex`, "Formats and views"), and a live test that takes any scheme or library picture
and captures without keyboard focus, optionally off screen; `amo edit` with named editor tools
("Editing", 2026-11-07); every config command under `sh -c` with `AMO_*` variables
instead of `{placeholder}`s ("Config", 2026-11-08). v0.5 (2026-11-13): the `system` variant,
which follows the desktop's colour scheme ("Variant"). v0.6 (2026-11-13): `amo list --order
least-shown`, the stale-index warning ("CLI"), the light variant's bright step calibrated
("Contrast checks"), and the grouping design for v0.7 ("Grouping (v0.7)"). v0.7 (2026-11-18):
grouping built ("Grouping (v0.7)"): a palette per file, `amo list --like`, `amo group` with a
setter hook, the distance and its bound calibrated with MH ("Grouping: decisions" 6). v0.8
(2026-11-19): `amo group --predicate` ("Grouping (v0.7)", Predicates) and letterbox detection
with `amo crop --letterbox` ("Letterboxes (v0.8)"). v0.9 (2026-11-20): Wallhaven tag
categories kept in `source.tag_categories` for naming, `amo fetch --refresh-tags` to backfill
them, and `amo name --from-tags --force` ("Names of fetched records", "CLI").
Values marked *initial* are starting points to calibrate on real images; change them here when
they change in code.

## Scope

**v0.1, the library:** measure images, keep records, build the index, query it, fetch from
Wallhaven with filters, and build test sets. No GUI, no wallpaper setter, no timer: those belong
to the user's desktop configuration and call `amo list`.

**v0.2, the theme engine:** palettes from pictures, presets or tinted-theming schemes,
contrast checks, and per-app templates rendered into a per-profile cache, with reload commands.

**v0.7, grouping:** pictures that go together across monitors ("Grouping (v0.7)").

## Storage

### Library

- **Library roots**: directories of records (below), searched recursively; the layout under a
  root is up to the user (as in papis: sub-directories are allowed and carry no meaning to the
  tool).
  Default root `$XDG_DATA_HOME/amontillado/library`; more roots from the config file.
- **One exception: purity.** Sketchy and NSFW images go to a separate root (default
  `$XDG_DATA_HOME/amontillado/library-nsfw`) that is searched only when a command asks for it
  (`--purity`). A default query can never return one, so a picker bug cannot put one on screen
  during a screen share, and backups or syncs can treat that tree separately.
- **File names**: `wallhaven-<id>.<ext>` for fetched images (the original file as served, never
  re-encoded: JPEG or PNG); any name for images added by hand.
- **Purity** is the record's `source.purity`; without one, a record under the NSFW root counts
  as `nsfw` and any other as `sfw`. A non-sfw record outside the NSFW root is warned about.
  Directory symlinks under a root are not followed.

### Records (source of truth)

A **record** is one picture: a directory holding `info.yaml` (or `info.yml`) and the picture's
files, all inside the directory: formats of the same image, crops per aspect ratio, and later
generated theme files. The directory name carries no meaning to the tool; `amo` names the ones
it creates after the record's `name`, the file's stem, or the Wallhaven id. Images are
`.jpg`, `.jpeg`, `.png` and `.webp` files. `info.yaml` holds only facts that do not change
about the picture; usage history lives in the index, so records stay stable under sync tools.
It is written atomically (temporary file, then rename).

```yaml
schema: 2
id: 3f2a9c1e0b7d4e8f9a6b5c4d3e2f1a0b   # generated once (uuid4), never changes; usage keys off it
name: night-city                    # optional; unique in the library; [a-z0-9][a-z0-9._-]*
default_file: night-city.png        # optional; see below
thumbnail: .amo/thumbnail.jpg       # derived; a small preview, never one of `files`
source:                             # Wallhaven's; for hand-added pictures see "Provenance"
  site: wallhaven
  id: abc123
  url: https://wallhaven.cc/w/abc123
  image_url: https://w.wallhaven.cc/full/ab/wallhaven-abc123.jpg
  purity: sfw                       # sfw | sketchy | nsfw
  category: general                 # general | anime | people
  tags: [landscape, night]
  tag_categories: {landscape: Landscapes, night: ""}  # Wallhaven's, per tag; "" for none
  colors: ["#000000", "#424153"]    # Wallhaven's own swatches
  source: ""                        # the uploader's credited source, if any
  uploaded: 2024-06-02T21:53:31
fetched: 2026-10-27T18:00:00+00:00  # null for pictures added by hand
files:
  night-city.png:
    sha256: <hex>                   # required: content lookups, duplicates, re-pairing
    width: 3840
    height: 2160
    metrics:                        # per file: a crop measures differently
      version: 4                    # bump when a metric's definition changes: forces recomputation
      lightness: 0.31
      chroma: 0.042
      colourful_share: 0.38
      hue: 262.0
      hue_name: blue
      hue_share: 0.71
      hue_spread: 0.18
      warmth: 0.12
      busy: 0.06
      palette: [['#1b2330', 0.412], ['#3d4a5e', 0.233], ['#c9a46b', 0.118], ...]
  night-city-21x9.png:
    sha256: <hex>
    width: 3840
    height: 1646
    derived_from: night-city.png    # crops say how to regenerate them
    crop: [0, 257, 3840, 1646]      # x, y, width, height in the original
    metrics: {...}
```

- **Lookup**: any command that takes a picture accepts its `name`, its `id`, a unique prefix
  of the id, or a file path. A duplicate `name` is reported by `amo index`, and neither record
  answers to it until fixed; `amo` commands that set a name refuse duplicates.
- **Content addressing** comes from the per-file `sha256`, indexed: adding a file whose hash
  is already in the library warns (with a `--force` escape hatch), with or without git-annex
  (whose default keys carry the same hash, but whose backend is configurable).
- **Default file** (what `amo list` prints without `--aspect`): `default_file` if set, else the
  largest non-derived file by pixel count, ties broken by name.
- Aspect ratio and format are derived at query time, not stored; `--aspect W:H` matches a
  file whose width / height is within 3% (*initial*) of W / H (so 3440×1440 and 2560×1080 are
  both 21:9), and uses the matching file's metrics for the class filters. Among several
  matches: the default file if it is one, else the largest by pixel count, ties broken by name.
- **Prompts**: commands may ask (e.g. "no 21:9 file; create a crop?") only when stdin and
  stderr are terminals (stdout may be a pipe: `amo list` output is data) and
  `--non-interactive` is not given; otherwise they take the documented fallback (for
  `--aspect`: the default file, with a warning) and never block.
- **Crops** (`amo crop`, amo-jak): the largest W:H box of the record's original (its default
  file if that is not a crop, else its largest original), centred by default; `--at F` places
  it along the side it cuts, from 0 (left or top) to 1 (right or bottom). Coordinates are in
  the image as displayed (after EXIF orientation). Written beside the original as
  `<stem>-<W>x<H>.<ext>` in its format (JPEG and WebP at quality 95; the ICC profile and EXIF
  kept, the orientation reset to 1, since the rotation is in the pixels),
  measured, recorded with `derived_from` and `crop`, and indexed at once. Refused: a record
  that needs `amo index`, an original of that ratio already, and without `--force` a record
  with a file of that ratio; `--force` replaces an earlier crop of the same name, never a file
  that is not a crop.
- **Hand-made derived files** (`amo add-derived`, amo-rqr): a file made from one of the record's
  files in any tool (an edit, a retouch) is listed with `derived_from` and **no `crop`**,
  which is what marks it hand-made: nothing can make it again, so unlike a crop it is never
  replaced or regenerated. `derived_from` defaults to the record's original, chosen as for
  crops (`--from FILE` picks another listed file). It is measured, moved into the record's
  directory (a file already there stays, renamed by `--name`), and indexed at once; the
  original stays the default file. Refused: a file that is not an image, a name the record
  lists or that exists, a `--from` it does not list or lacks, content one of its files has,
  and a record that needs `amo index`. Without `amo add-derived`, `amo index` adds an unlisted
  image as an original. `amo edit` opens an editor on a copy and adds the result ("Editing").
- **Editing** (`amo edit`, amo-2mf; agreed with MH 2026-11-07): the same refusals as
  `amo add-derived`, checked before any tool runs, then the source file (`--from`, default the
  original as above) is copied into a fresh working directory inside the record,
  `.amo/edit-*`: `amo index` never looks there (records do not nest), an NSFW picture stays
  under its root, and the result moves in without crossing a file system. The tool is named
  like git's difftool: `--tool NAME` picks an entry of `edit.tools` (default
  `edit.default_tool`), `--extcmd CMD` runs a one-off command line, `--list-tools` lists them
  with their descriptions. A tool's `cmd` runs under `sh -c` in the working directory with
  `AMO_INPUT` (the copy), `AMO_OUTPUT` (a path for the result, not created) and `AMO_WORKDIR`
  added to the environment, as every config command does ("Config": several named arguments,
  shell features, and the user's own variables as parameters, `STYLE=x amo edit --tool
  darktable-cli`); its standard
  output goes to standard error. It must block: GIMP needs `-n`, `xdg-open` never works.
  **The result** is `AMO_OUTPUT` if the tool wrote it, else the one image (`.jpg`, `.png`,
  `.webp`, hidden paths left out) in the working directory or below it that is new or changed,
  which covers editors that keep their own format and export separately (GIMP's `.xcf`,
  Krita's `.kra`, darktable's `darktable_exported/`): export into the folder the editor opens
  in. It is added as `<stem>-edit<ext>` (then `-edit-2` ...; `--name` must keep the result's
  format). A tool that exits non-zero, saves nothing or saves several images fails; the
  working directory is removed when it holds nothing the tool saved and otherwise kept and
  named, for `amo add-derived` by hand. Saving nothing within 2 s (*initial*) adds a hint that
  the tool probably did not block. Not built: tools with declared parameters (`--args`, an
  `env:` schema), since environment variables cover them; descriptions for shell completion
  are there when completion is.
- **Interactive crops** (`amo crop --interactive`, amo-cmj): after the same refusals, the
  original is shown with the box drawn (the rest darkened), starting from the box `--at` gives.
  Arrows or `hjkl` move it by 5% of its size (shifted, or `HJKL`: 25%), `+` and `-` zoom it
  (×0.9 per step, down to 0.1 of the largest box, *initial*; about its centre, never past the
  picture), `0` resets it, Enter writes the crop as above (the exact box recorded in `crop`),
  Esc (or `q`, or the end of input) writes nothing and exits non-zero. The box is the largest
  of the ratio times a scale (0 < s <= 1) at a 2-D place (`crop_box`); the keys drive a pure
  state machine (`amontillado.cropper.press`) over its unrounded centre, so zooming in and out
  again returns the same box. Keys come from stdin in cbreak mode, the preview and status go
  to stderr: stdout still carries only the new file's path. Needs stdin and stderr to be
  terminals. The preview (`crop.preview`, with `auto` the default):
  - `kitty`: drawn in the terminal's alternate screen with the kitty graphics protocol (PNG,
    direct transmission in 4096-byte base64 chunks, so it works over ssh; replaced on each key;
    sized to the terminal in cells from `TIOCGWINSZ`), the status on the last line. `auto`
    picks it when `KITTY_WINDOW_ID` is set, `TERM` is `xterm-kitty` or `xterm-ghostty`, or
    `TERM_PROGRAM` is `WezTerm` or `ghostty`: from the environment only, since a protocol query
    would need a reply read before cbreak input starts.
  - `viewer`: the preview (at most 1600 pixels a side) written atomically to
    `$XDG_CACHE_HOME/amontillado/crop-preview.png` after each key and shown by `crop.viewer`
    (default `xdg-open "$AMO_FILE"`, under `sh -c`), started once; the viewer must reload a changed file (eog,
    gThumb and Gwenview do; feh needs `--reload`). The file is removed afterwards; the viewer
    is left running.

  `amo list --aspect` offers the same: its prompt is `crop: [c]entred, [i]nteractively, [N]o?`,
  and `i` places each picture's box in turn. Machine-specific choices (which viewer) belong in
  the user's config, not here. External editors are out of scope (amo-rqr). **Decision**
  (amo-cmj, MH 2026-11-03: position and zoom): the kitty graphics protocol where the terminal
  speaks it, else a regenerated preview file in a viewer, chosen by `crop.preview`; sixel and
  a GUI of amontillado's own were not taken (sixel: no zoomed redraw without flicker in the
  terminals at hand, and kitty, the user's terminal, prefers its own protocol; a GUI: a
  toolkit dependency for one command).
- `info.yaml` is loaded with a loader that rejects duplicate keys (PyYAML's `safe_load`
  silently kept the last, which would drop a file listed twice; ruamel.yaml rejects them by
  default).
- **YAML** (amo-j24.4): ruamel.yaml, YAML 1.2 (`yes`, `on`, `no` are strings), with its C
  parser (ruamel.yaml.clib) where installed. amo writes an info file it read by changing only
  the keys whose values changed, in the text it read: comments, key order, flow style and
  quoting survive, a new key goes after the key that precedes it in the schema, a removed one
  goes. New files are dumped in PyYAML's shape (what earlier versions wrote): two-space
  mappings, sequences not indented, `null` spelt out, timestamps as `2026-10-27 18:00:00+00:00`.
  Lines never fold (ruamel puts a long unfoldable scalar, a URL, on a line of its own, and a
  round trip writes every scalar again). A string YAML 1.1 or 1.2 would read as another type
  (`yes`, `y`, `1:30`, `012`, `1e5`) is quoted, so PyYAML reads amo's files as amo does. An old
  file PyYAML wrote with an unquoted `1e5`-like string reads as a number under 1.2 (rare: a
  Wallhaven id of digits and one `e`).
- **Thumbnail** (amo-hq0): a path relative to the record directory naming a small image, for
  picker previews (`amo list --format rofi`). amontillado writes it at `.amo/thumbnail.jpg`:
  in a sub-directory, which the scan of a record never enters, so no version of amontillado
  (v0.1.0 included) takes it for one of the picture's files, and the record schema stays 2 (an
  older version keeps the key as an unknown one). `amo fetch` keeps Wallhaven's `large`
  thumbnail, as served, which it downloads anyway; `amo add` and `amo index` make one of the
  default file: a JPEG (quality 85) at most 400 pixels on its longer side (*initial*), EXIF
  orientation applied. A thumbnail set by hand to another path inside the record is kept. It
  is not remade when the picture changes: delete it and `amo index` makes it again.

**Finding records.** A record is a directory under a root holding `info.yaml` or `info.yml`;
both at once is a conflict, and the record is not indexed until one is removed. Its files are
the images directly inside it: the scan does not descend into a record, so records do not nest.
An `info.yaml` directly in a root is reported and ignored (it would claim every loose image).

**Loose images** (images under a root but not in a record) are reported by `amo index` and not
indexed; `amo index` never moves files. `amo add FILE` makes a record of one: it creates the
record directory beside the file (or, for a file outside the roots, in the first library root,
or the NSFW root with `--nsfw`), moves the file in, and writes `info.yaml`. A hand-made
directory with images and an empty or partial `info.yaml` is a record too: `amo index` fills
in the rest.

**Provenance** (amo-k9j; ticket from chezmoi, 2026-10-30). `amo add` records where a picture
came from in `source`, from options (`--source-url`, `--image-url`, `--site`, `--title`,
`--author`, `--license`, `--purity`, `--category`, `--tags`, `--uploaded`) or, for several
pictures, `--from-json FILE`: a list of objects with `file` (relative to the JSON file),
optional `name` and `nsfw`, and the same keys (`url`, `image_url`, `site`, `title`, `author`,
`license`, `purity`, `category`, `tags` as a list, `uploaded`), unknown keys refused. Only the
keys given are written, in that order; with none, `source` is null as before. `url` is the
picture's page and `image_url` the file downloaded, as for Wallhaven; `site` defaults to the
URL's host (`commons.wikimedia.org`). Three keys are new, and only hand-added pictures have them
so far: `license` (an SPDX identifier, `CC0-1.0`, `CC-BY-4.0`, ..., or `public-domain`, which
SPDX lacks; US spelling as in SPDX and PyPI), `author` (the creator; `source.source` stays the
uploader's credited source) and `title`. No record schema bump: `source` is an authored mapping
that every version keeps as written. `fetched` stays null: amontillado did not download the
picture, so it does not know when it was. A `--purity` other than sfw puts a file from outside
the roots in the NSFW root and is refused for a file under a library root, which default
queries would show. Wallhaven's API gives no licence and only the uploader, so fetched records
have none of the three.

**Healing** (`amo index`) splits the fields in two:

- **Derived** fields are recomputed whenever they are missing, invalid or out of date, without
  asking: `schema` and `id` when absent (a new record), `thumbnail` when absent, invalid or
  naming no file (a thumbnail that cannot be made is a warning only), and per file `sha256`,
  `width`, `height` and `metrics`. A file whose content hash changed is measured again.
  **Hash cache**: the index keeps each file's size and mtime (ns) beside its hash, and a file
  whose size and mtime both match what the last index saw is not hashed again (hashing runs at
  about 1 GB/s, so a large library would otherwise be read in full on every run). The cost: an
  edit that leaves both as they were (a tool that restores the mtime, or a filesystem with
  coarse timestamps) goes unnoticed until `amo index --rehash`, which ignores the cache. The cache is read without changing the database, so `--check` uses
  it too.
- **Authored** fields are never rewritten, because nothing could recompute them: `id` once set
  (usage keys off it), `name`, `default_file`, `source`, `fetched`, the shape of `files`,
  `derived_from` and `crop`. If one is invalid, or `info.yaml` does not parse (including a
  duplicate key), or its `schema` is not one this program knows, the record is reported and
  not indexed until fixed by hand; nothing is written to it. Unknown keys are kept as written.

**Per-file re-pairing**, within one record: an image in the directory that `files` does not
list, whose hash is that of a listed file that is missing, is that file renamed: its entry
moves to the new name, and `default_file` and `derived_from` follow. Any other unlisted image is
measured and added. A listed file that is missing with no match keeps its entry, is reported,
and fails `--check`; the rest of the record is still indexed, and a missing `default_file` falls
back to the rule above with a warning.

**Absent content** (git-annex, amo-qnn.2): a listed file whose annex content is not here is
*absent*, not missing. It is told from the file alone, without running git-annex: a locked
file's symlink into `annex/objects` that leads nowhere, or an unlocked file's pointer (a file of
at most 1 KiB starting `/annex/objects/`). It keeps its entry, is never hashed or measured,
does not fail `--check` (dropping content is routine), and is counted ("N files not here") by
`amo index`. Measured elsewhere (the info file travels in git), it is indexed from its entry,
flagged `absent`, so a record whose every file is absent stays in the index; the default file
is chosen among the files that are here first. `amo list` skips absent files (a record with
none here is not printed), and `amo palette` and `amo theme apply` on one fail naming
`git annex get`. An image that is absent and not listed cannot be added until its content is
got, and is warned about. Hidden directories under a root (`.git`, whose `annex/objects` hold
images) are never searched for records. A file moved to another record is not re-paired: it is added
there, and reported missing from the first. A record directory renamed or moved needs no
healing at all: its identity is inside it.

**Duplicates.** Two records with the same `id` (a copied directory) are both reported and
neither is indexed; deleting the `id` line from one gives it a new id at the next
`amo index`. The same `sha256` in two files anywhere in the library is a warning only.

### Index and usage (SQLite)

One database, `$XDG_STATE_HOME/amontillado/index.sqlite` (state, not cache: the usage table
cannot be rebuilt):

- `records`: one row per record (id, name, directory, root, whether it is under the NSFW root,
  purity, category, tags as JSON, source site and id, thumbnail path, license, author, title,
  and the info file as JSON),
  and `files`: one row per file present (path, record id, sha256 (indexed), whether it is the
  default file, size, every metric, and for the hash cache its size in bytes and mtime in ns),
  and one per file whose annex content is not here, from its entry, flagged `absent` (no hash
  cache; only when it was measured).
  **Rebuilt from the info files** by `amo index`, in one transaction (dropped and recreated, so
  their schema needs no migrations): delete the database and nothing is lost but the usage
  table (from schema 10, the state tables of "Saved looks" too: `current_group`, `history`,
  `theme_usage`; an upgrade from schema 9 creates them empty). The database's `PRAGMA user_version` is its schema version (10); a newer one than the
  program knows is refused. Schema 2 lacked the hash-cache columns, schemas 2 and 3 the
  thumbnail column, schemas 2 to 4 the `license`, `author` and `title` columns of `records`,
  schemas 2 to 5 its `info` column (the whole info file as JSON, for `amo list --where`),
  schemas 2 to 6 the `absent` column of `files`, schemas 2 to 8 its `palette` column (JSON,
  "Grouping (v0.7)"; last in the table, since an upgrade appends it); upgrading adds them empty,
  for the next `amo index` to fill. The `pictures` view (columns
  under "CLI") is recreated on every open, so changing it needs no migration.
- `directories` (schema 8, amo-50c.3): the snapshot the index was built from, one row per
  record directory `amo index` found (indexable or not: a conflict is a record directory too)
  with its record's id and the images directly in it. `amo index` rewrites it; commands that
  update the index themselves (`amo add`, `crop`, `add-derived`, `edit`, `name`, `fetch`) update
  their record's row, a rename moving it. Upgrading from schema 7 or earlier leaves it out
  until the next `amo index`, so nothing is reported as changed before then.
- `usage`: `id` (the record's), `shown_count`, `last_shown` (ISO 8601, UTC); later perhaps a
  rating. Keyed by record, so it follows a picture through renames and moves. Kept across
  rebuilds. The only mutable data; never written to info files, which keeps them stable under
  git-annex or sync tools. Schema 1 keyed usage by content hash; upgrading discards it.

Classification (dark, muted, ...) is **not stored**: it is computed from the raw metrics at query
time, so retuning a threshold needs no recomputation.

### Config

`$XDG_CONFIG_HOME/amontillado/config.yaml`, all keys optional:

```yaml
library_roots: [~/Pictures/wallpapers]   # searched in addition to the default root
nsfw_root: ~/private/wallpapers-nsfw     # replaces the default NSFW root
api_key_command: pass show wallhaven/api-key
edit:                                    # amo edit's editors ("Editing")
  default_tool: gimp
  tools:
    gimp: {cmd: 'gimp -n "$AMO_INPUT"', description: GIMP}
```

**Every command in the config runs under `sh -c`**, its inputs as `AMO_*` environment variables,
never substituted into the text (agreed 2026-11-07, amo-j24.3): `theme.wallpaper.reload` and
`theme.apps.<app>.reload` get `AMO_WALLPAPER`, `AMO_PROFILE`, `AMO_DIR`, `AMO_VARIANT` and
`AMO_TONE` (v0.11);
`crop.viewer` gets `AMO_FILE`; `amo edit`'s tools get `AMO_INPUT`, `AMO_OUTPUT` and
`AMO_WORKDIR`; `group.setter` gets `AMO_MONITOR` and `AMO_WALLPAPER`, and `group.predicates`
`AMO_PRIMARY`, `AMO_CANDIDATE` and `AMO_MONITOR`; `api_key_command` gets none. So pipelines
and fallbacks need no wrapper script, and quoting is the user's job (`"$AMO_WALLPAPER"`). The prefix keeps generic names such as
`PROFILE` or `DIR` from silently colliding with the user's own environment; an `AMO_*` variable
amo itself was started with never reaches a reload hook. The `{placeholder}` syntax of v0.2 and
v0.3 is gone: a leftover `{wallpaper}`, `{profile}`, `{dir}`, `{variant}` or `{file}` (not
`${...}`) is a config error naming its variable.

The template has commented examples for GIMP, Krita, Pinta, darktable and `darktable-cli`,
RawTherapee and `rawtherapee-cli`, satty, ImageMagick and Inkscape.

Every key is described in the commented template `amo config init` writes
([`config.template.yaml`](../src/amontillado/config.template.yaml)). Paths must be absolute (`~`
is expanded). The NSFW root may not be, contain, or lie inside a
library root, symlinks resolved; that is a config error, since a recursive search would then
reach NSFW images. Unknown keys are warned about and ignored. The API key comes from
`WALLHAVEN_API_KEY` first, then the first line printed by `api_key_command` (run by `sh -c`); it
is never written anywhere and never logged.

## Metrics

### Preparation

1. Open with Pillow, apply the EXIF orientation, convert to RGB (alpha composited on black;
   palette and CMYK images converted). Keep Pillow's decompression-bomb guard. For JPEG, use
   `Image.draft` so large files decode at reduced size.
2. Resize to **432 px wide** (Lanczos), height in proportion. That is the width of Wallhaven's
   `large` thumbnail, so a thumbnail and its full image are measured at the same scale.
3. Convert sRGB → linear RGB → OKLab (Björn Ottosson's matrices) → OKLCH (L 0-1, C ≥ 0, h in
   degrees). Pure sRGB primaries for reference: red h ≈ 29°, yellow ≈ 110°, green ≈ 142°,
   cyan ≈ 195°, blue ≈ 264°, magenta ≈ 328°.

### Definitions

"Chromatic pixels" are pixels with C > 0.03 (*initial*). Hue statistics use chromatic pixels
only, each weighted by its chroma, so a few vivid pixels count more than many near-grey ones.

| Metric | Definition | Why it matters |
|---|---|---|
| `lightness` | mean L | dark vs light theme; a light wallpaper behind a dark theme is the classic failure |
| `chroma` | mean C over all pixels | muted images give generators almost no hue (grey palettes); saturated ones test whether accents turn garish |
| `colourful_share` | share of chromatic pixels | separates "a little colour everywhere" from "a vivid patch on grey" |
| `hue` | chroma-weighted circular mean of h | the image's overall hue |
| `hue_name`, `hue_share` | the heaviest 60° arc of chroma-weighted hues: the named sector (below) holding its weighted mean hue, and its share of all chromatic weight | "red-heavy" |
| `hue_spread` | circular variance of the chroma-weighted hues, 1 − R (0 = one hue, 1 = all hues evenly) | monochrome vs multi-hued: does the generator find distinct accents when the image offers one hue? |
| `warmth` | (warm weight − cool weight) / total chromatic weight, in −1..1 | warm vs cool; warm sectors are red, orange, yellow, pink |
| `busy` | edge density: share of interior pixels whose Sobel gradient magnitude on L exceeds 0.08 (*initial*) | legibility of text over translucent, blurred windows |
| `palette` | up to 6 (*initial*) `[hex, share]` pairs: k-means in OKLab over every 4th pixel, largest share first ("Grouping (v0.7)") | which pictures go together: `amo list --like`, `amo group` |
| `letterbox` | the picture between dark bars, `[x, y, width, height]` in the file's pixels; absent without bars ("Letterboxes (v0.8)") | bars dominate a palette; `amo crop --letterbox` cuts them off |

The Sobel kernels are divided by 8, so the gradient magnitude is the change in L per pixel: a
hard black-to-white edge scores 0.5 on the pixels either side of it. The one-pixel border is
left out.

Hue sectors (degrees, OKLCH; boundaries halfway between the reference hues, *initial*; each
sector includes its lower bound): red 358-44, orange 44-80, yellow 80-125, green 125-170,
cyan 170-230, blue 230-280, purple 280-310, pink 310-358. They name hues and split `warmth`;
`hue_share` measures an arc instead (arcs start on whole degrees), so one hue that straddles a
boundary is not split, and the arc follows the peak rather than the mean hue, so a dominant hue
keeps its share when a second hue pulls the mean away (metrics version 2; version 1 used the
heaviest sector).

A greyscale image has no chromatic pixels: `hue`, `hue_name` are null, `hue_share`,
`hue_spread` and `warmth` are 0. It is muted, never monochrome.

Values are rounded when written: `hue` to 0.1°, the others (palette shares too) to 3 decimals.

### Classes (query-time, calibrated thresholds)

| Flag | Rule | Share of the sample |
|---|---|---|
| `--dark` / `--light` | `lightness` < 0.35 / > 0.65 | 21% / 22% |
| `--muted` / `--saturated` | `chroma` < 0.02 / > 0.075 | 19% / 18% |
| `--sparse` / `--busy` | `busy` < 0.03 / > 0.15 | 17% / 17% |
| `--hue NAME` | `hue_name` = NAME and `hue_share` ≥ 0.40, and not muted | 4-23% per hue; 80% have one |
| `--monochrome` / `--multi-hue` | has chromatic pixels and `hue_spread` < 0.03 / `hue_spread` > 0.50 | 20% / 15% |
| `--warm` / `--cool` | `warmth` > 0.8 / < −0.8, and not muted | 29% / 14% |

**Calibration** (2026-10-28, `tools/calibrate.py`, `just calibrate`): 400 thumbnails from a
random sfw Wallhaven search with no other filters (279 general, 121 anime; the sample stays
outside the repository), thresholds set so each class holds roughly a fifth. Findings:

- Most wallpapers sit close to one hue: median `hue_spread` 0.12, and the initial monochrome
  bound (0.30) took 70% of the sample. 0.03 is about all chromatic weight within ±25° of the
  mean hue.
- `warmth` is nearly binary for the same reason (p25 −0.47, p75 0.94), so the threshold barely
  moves the warm share; leaving out muted images (whose warmth is only a tint) does. Warm stays
  the largest class: the sample leans warm (red is the top hue, 20%).
- Fixed hue sectors split one hue: 11 of the 278 images with `hue_spread` < 0.30 had a
  heaviest-sector share < 0.40. Metrics version 2 (2026-10-29) measures the heaviest 60° arc
  instead: none of the 11 stays below 0.40, no image loses its `--hue` class, 47 gain one
  (images with a dominant hue among others; one hue now holds 80% of the sample, was 68%) and
  15 change name (a hue near a boundary, named by where its weight centres). An arc centred on
  the mean hue was tried first and rejected: it drops images whose two hues put the mean
  between them (22 lost their class). 0.40 was kept: the share it asks for is unchanged.
- Thumbnails measure like their full images (40 pairs): median |difference| in `busy` 0.002,
  p90 0.021; in `lightness` 0.003 / 0.022. JPEG artefacts in thumbnails do not inflate `busy`.
- The metric constants (chromatic C > 0.03, edge 0.08, the hue sectors) were not changed:
  changing them changes stored metrics and needs a `metrics.version` bump.

## Fetcher (Wallhaven)

### API facts (checked 2026-10-27)

- Search: `GET https://wallhaven.cc/api/v1/search`. Parameters: `q` (tags; `+tag`, `-tag`),
  `categories` and `purity` (three-flag strings: general/anime/people, sfw/sketchy/nsfw),
  `sorting=random` with `seed` (the response's `meta.seed` keeps paging stable), `atleast`,
  `resolutions`, `ratios`, `colors` (one hex from Wallhaven's fixed swatch list), `page`.
  24 results per page.
- Rate limit: **45 API requests per minute** (`x-ratelimit-limit`/`-remaining` headers).
  Thumbnail requests to `th.wallhaven.cc` carried no rate-limit headers.
- Each result has `id`, `url`, `path` (the full image), `file_type` (`image/jpeg` or
  `image/png`), `dimension_x/y`, `purity`, `category`, `colors`, `source`, `created_at`, and
  `thumbs.small|large|original`. `large` was 432×243 for a 16:9 image (aspect kept);
  `original` 300 px wide.
- Search results carry **no tags**; tags come only from `GET /api/v1/w/<id>` (one more API call,
  made only for images that are kept).
- NSFW results need an API key (`apikey` parameter or `X-API-Key` header).
- Send a descriptive `User-Agent`.

### Flow

1. Search with the server-side filters (tags, purity, category, size, swatch), `sorting=random`;
   later pages pass the first page's `meta.seed`.
2. For each result not already in the library (by Wallhaven id: from the index, and from the
   `source` of every info file under the roots, so a record synced in before `amo index` is
   not fetched twice), and of a purity that was asked for: fetch the `large` thumbnail and measure it. Skip it if it fails a
   look filter.
3. `--busy-from thumb` (default) judges busy/sparse on the thumbnail. `--busy-from full` leaves
   that filter for the full image (thumbnail JPEG artefacts add edges).
4. Download the full image to a temporary `.part` file in its root (not an image suffix, so a
   scan never takes it for a loose image), refuse it if its content is already in the index,
   call `/w/<id>` for tags, name the record from them (below), then move it into a new record
   directory of that name (sfw: the first library root; sketchy and nsfw: the NSFW root), keep
   the thumbnail as the record's `thumbnail`, and write the record with metrics measured on the **full** image (so stored metrics never come
   from a thumbnail); add it to the index. A failure at any step leaves nothing behind; an
   existing directory of that name is refused (the index is stale: run `amo index`).
   **Every look filter is judged again on the full image**, so that `amo list` with the same
   filters finds what `amo fetch` kept. A full image that no longer matches (a borderline
   thumbnail) is still kept as a record by default, since the download has been paid for, but
   is not printed and does not count towards `--count`; `--discard-mismatches` deletes it
   instead (decided 2026-10-28).
5. Stop at `--count` (default 1) matching images kept (with `--test-set`, when every bucket is
   filled), or at `--max-candidates` (default 100, *initial*)
   thumbnails examined (results already in the library do not count).
6. API calls keep 1.5 s apart (40 a minute, under the limit of 45); thumbnail and image
   downloads are not paced. On HTTP 429 from any host, wait `Retry-After` if given, else 10 s
   doubling, up to 5 retries.

**Names of fetched records** (amo-0z2, rules from the 400 tag lists of the calibration sample,
*initial*): up to 3 of the wallpaper's tags, in Wallhaven's order (in the sample it puts the
subject first), as slugs joined by hyphens, then `-<id>`: `batman-joker-dc-comics-g8mq6e`,
`food-dessert-ice-cream-4l36wr`. A slug is the tag in lowercase ASCII (accents folded,
apostrophes dropped, other runs of characters a hyphen) without a trailing qualifier in
brackets (`Joker (DC)` is `joker`). Passed over: tags in the categories Artists, Companies &
Logos, Digital and Photography (credits and technique, not subject), a short list of tags that
fit nearly any picture (`artwork`, `digital art`, `simple background`, `fan art`, ...; the list
is `NAME_SKIP_TAGS` in `fetch.py`), a tag whose words all appear in a chosen tag, and one that
would take the tag part past 40 characters; a tag holding all of a chosen tag's words takes its
place (`anime girls` over `anime`). No usable tag: the category (`general-k92q1d`; 2 of 400).
The suffix is the Wallhaven id, not a counter (decided 2026-10-28): a counter comes from each
machine's index, so two machines would assign the same name and a sync would make a
duplicate-name conflict. A name already taken (by a hand-named record) leaves the record
unnamed, in `wallhaven-<id>`, with a warning. Records fetched before names existed keep theirs
(none) until `amo name --from-tags` names them from the tags their info.yaml keeps (under
"CLI"), applying the same rules with the categories in `source.tag_categories` (amo-ugu; kept by
`amo fetch` since 0.9), so naming itself never needs the network. Tags kept before that have no
categories, so the category rule cannot apply to them (an artist's or a technique's tag may make
it into the name; `NAME_SKIP_TAGS` still applies) until `amo fetch --refresh-tags` re-asks
Wallhaven for them (under "CLI"); `amo name --from-tags --force` then re-derives names already
given.

**Revisit:** the info-file scan in step 2 parses every info file on each `amo fetch`
(decided 2026-10-28). If that makes fetching noticeably slow on a large library, drop it and
rely on the index (with `amo index` after a sync), or cache the scan keyed on directory mtimes.

The API key travels in the `X-API-Key` header, never in a URL, so URLs can be logged. It is
looked up only when `--purity` includes `nsfw` (its command may ask for a passphrase), and the
command's output and errors are never shown.

### Test set

`amo fetch --test-set` keeps one image per bucket: dark, light, muted, saturated, busy, sparse,
monochrome, multi-hue; one image fills one bucket only. Other filters (size, category) still
apply. It is the input for comparing palette generators. Decided 2026-10-28:

- A thumbnail is downloaded if it belongs to any bucket still open. The full image then fills
  the **first** open bucket it belongs to, in the order above (greedy; a black image fills
  dark, not muted or sparse). A full image in no open bucket is a mismatch, as in step 4.
- Look filters and `--count` are refused with `--test-set`: they would contradict buckets.
- Output is one `BUCKET<TAB>PATH` line per filled bucket, in bucket order (page URLs with
  `--dry-run`); exit non-zero, naming the empty buckets, if any bucket stays empty.
- A dry run with `--busy-from full` cannot fill busy or sparse (the full image is never seen).
- With the calibrated thresholds every bucket holds 15-22% of a random sample; a default dry run
  (2026-10-28) filled all eight from 12 thumbnails. Narrow server-side filters (`--tags`,
  `--color`) can still leave a bucket empty: raise `--max-candidates`.

## CLI (v0.1)

```text
amo measure FILE...                  metrics and classes for any image, as YAML (no library needed)
amo index [--check] [--rehash]       heal records, rebuild the index; --check reports only
amo list [FILTERS] [--aspect W:H] [--purity LIST]
         [--order path|least-shown] [--random N] | [--like PICTURE [--max-distance D]]
         [--format path|rofi]
         [--non-interactive] [--tag T]... [--site S] [--category C] [--license L] [--author A]
         [--where SQL]
                                     matching paths, one per line
amo fetch [FILTERS | --test-set] [WALLHAVEN] [--count N] [--max-candidates N]
          [--busy-from thumb|full] [--discard-mismatches] [--keep-letterboxed] [--dry-run]
amo fetch --refresh-tags [PICTURE...] [--dry-run]   tag categories for records fetched before 0.9
amo group [PICTURE] --monitor NAME=W:H... [FILTERS] [--purity LIST] [--order least-shown|nearest]
          [--max-distance D] [--keep-category] [--predicate NAME]... [--predicate-cmd CMD]
          [--format tsv|json] [--non-interactive] [--apply] [--dry-run]
                                     one picture per monitor, colours going together ("Grouping")
amo shown PICTURE... [--dry-run]     record that pictures were shown (for the usage table)
amo add FILE... [--name N] [--nsfw] [--force] [--non-interactive] [--dry-run] [PROVENANCE]
                                     make each file a record
amo add --from-json FILE [--force] [--dry-run]              the pictures a JSON file lists
amo crop PICTURE W:H [--at F] [--interactive] [--force] [--dry-run]   crop a record's original; prints it
amo crop PICTURE --letterbox [--force] [--dry-run]   crop the bars off ("Letterboxes"); prints it
amo add-derived PICTURE FILE [--name N] [--from FILE] [--dry-run]   add a hand-made derived file
amo edit PICTURE [--tool NAME | --extcmd CMD] [--name N] [--from FILE] [--dry-run]
                                     edit a copy in an editor, add the result; prints it
amo edit --list-tools                the editors under edit.tools
amo name PICTURE NAME [--no-rename-directory] [--dry-run]      name or rename a record
amo name --from-tags [--force] [PICTURE...] [--no-rename-directory] [--dry-run]   name fetched records from their tags
amo info diff OLD NEW [--json]       the key paths that differ between two info files
amo info merge BASE OURS THEIRS [--name PATH] [--stdout]   three-way merge (a git merge driver)
amo hook git-commit                  as on_change: commit amo's changes to the root's git repository
amo hook gtk3-theme [--app NAME] [--dry-run]   as libadwaita's reload: recolour running GTK3 apps
```

`amo index` fails (non-zero exit, after indexing everything it could) when images cannot be read,
an info file needs fixing by hand, or records conflict (both info files, a shared id or name).
`--check` is its dry run: it measures and writes nothing, and also fails if any record needs
healing, an image is outside a record, or a listed file is missing.
It ends with one INFO summary (records indexed or checked, healed, files measured, renamed,
and any loose, missing, conflicting or failed). Routine heals (a new record, a file measured)
log at DEBUG, so a first index of a large library stays quiet; a changed file or a rename logs at
INFO, problems at WARNING or ERROR. On a terminal, a progress bar runs on stderr while records
are hashed and measured.

`amo list` prints the default file of each matching record, sfw records outside the NSFW root
only unless `--purity` (comma-separated: `sfw`, `sketchy`, `nsfw`) asks for more; the NSFW-root
test uses the current config and resolves symlinks, so a stale index cannot leak an image.
Opposite class flags (`--dark --light`) are rejected. Indexed files that are gone are skipped
with a warning. No match exits non-zero, so a pipeline into a wallpaper setter notices.
`--aspect W:H` picks each record's file as in "Records". Records left without a matching file
(after `--random`, so only what is printed) are offered a crop each, centred or placed by hand
("Interactive crops"), in one question, when a prompt is allowed ("Prompts";
`--non-interactive` never asks); a crop is printed in
place of its default file. Otherwise, or declined, they take the fallback (the default file,
one warning).
**Provenance filters** (amo-mag) match what a record's `source` says, exactly: `--tag T`
(repeatable; each must be one of its tags), `--site`, `--category`, `--author`, and `--license`
in any case (`CC0-1.0` matches `cc0-1.0`). A record without the field does not match.
`--where SQL` is a SQL boolean expression over the index's read-only `pictures` view, ANDed
with the other filters. Its columns: `id`, `name`, `directory`, `purity`, `site`, `source_id`,
`category`, `tags` (a JSON array), `license`, `author`, `title`, `shown_count` (0 if never
shown), `last_shown`, and `info`, the whole info file as JSON (as fresh as the rest of the
index: written by `amo index`). Any field is reached with SQLite's JSON functions:

```text
amo list --where "shown_count = 0"
amo list --where "json_extract(info, '$.source.uploaded') >= '2024'"
amo list --where "info ->> '$.files.\"night.png\".width' >= 3840"          # SQLite >= 3.38
amo list --where "EXISTS (SELECT 1 FROM json_each(tags) WHERE value LIKE 'night%')"
```

The expression runs in one statement (a `;` is an error) with `PRAGMA query_only` and an
authorizer that allows only reads and function calls (no `PRAGMA` functions, no
`load_extension`); it selects records, and purity and the NSFW root are applied after it in
Python as for every `amo list`, so no expression widens what is printed. `->` and `->>` need
SQLite 3.38 (Python uses the system's on Linux; Ubuntu 22.04 ships 3.37, believed, unverified):
on an older one the error says so and names `json_extract`. **Decision** (MH 2026-11-03): SQL
over the index rather than reading each `info.yaml` per query (slow: a pure-Python YAML loader)
and no jq runtime dependency; `sqlite-jq` was rejected (a loadable C extension: Python builds
without loadable-extension support exist, and pipx cannot ship per-platform binaries).

**Order** (amo-50c.2): by file path, or with `--order least-shown` by the usage table:
fewest showings (`amo shown`) first, then the longest since last shown, never-shown pictures
first, ties in random order, so a rotation reaches every picture before repeating one and still
varies. `--random N` then takes the first N in that order instead of N at random:
`amo list --dark --order least-shown --random 1` is a wallpaper timer's next picture. Decided
2026-11-13 (scope of v0.6), resolving the open question; `amo group` picks its primary this way.

**Stale index** (amo-50c.3): `amo list` walks the roots as `amo index` does, reading no info
file and hashing nothing, and compares the record directories and the image names in each with
the `directories` snapshot; any difference is one warning (`the library has changed since the
last amo index (1 record added, 1 record changed); run amo index`). It never re-indexes.
`check_stale_index: false` in the config turns it off. Not seen: an image whose content changed
under the same name (the hash cache's case, "Healing"). Cost: about 0.3 s warm for 10,000
records (a synthetic annexed-style library; about 30 ms per 1,000). **Decision** (MH
2026-11-13): names, not directory mtimes against the time of the last `amo index`, which was the
first proposal: amo's own incremental commands change mtimes (so they would warn right after
`amo add`), and so does the git-annex hook's `git annex add` (files replaced by symlinks)
after amo has finished.

`--format rofi` follows each path with its record's thumbnail as the icon and a display label
(`PATH\0icon\x1fTHUMBNAIL\x1fdisplay\x1fLABEL`, for `rofi -dmenu -show-icons`; rofi-script(5),
"Parsing row options"): rofi shows LABEL and still filters on and returns PATH. The label is
the record's directory name, or the file name when the record has several files (crops). A
record without a thumbnail, or whose thumbnail is gone, gets `PATH\0display\x1fLABEL`
(amo-2f0).

`amo shown` takes any PICTURE form under "Lookup" (a file found nowhere in the index is looked
up by content); one that matches no record, or more than one, exits non-zero before anything is
recorded.

`amo add` refuses (per file; the others are still added) a file already in a record, a
directory that already exists, a `--name` that is invalid or taken, and, without `--force`, a
file whose content the index already holds. It measures before it moves anything, and adds
the new record to the index itself.

`amo name PICTURE NAME` (amo-uc5) gives a record a name, or a new one, and renames its
directory to the name where it is (`foo/bar/img-0412` becomes `foo/bar/harbour-dawn`, never a
move to the root); `--no-rename-directory` keeps the directory. Renaming by default, decided
MH 2026-11-05: the directory name means nothing to the tool, and no rule tells a directory amo
named from one the user named the same way (a user can call one `wallhaven-x8ye3z` too), so
the user opts out instead; under git-annex storage (amo-qnn) an unwanted rename shows in the log
and is reverted there. `amo name --from-tags [PICTURE...]` names records fetched from
Wallhaven without a name (see "Names of fetched records"): the PICTUREs given, or every indexed
one without a name; it renames a named record only with `--force` (amo-ugu, MH 2026-11-20:
whatever gave the record its name, since asking for it is the point; with no PICTURE, every
indexed Wallhaven record), and leaves one whose tags give the name it has as it is. Naming is
never `amo index`'s job, since a name is authored, not derived. Refused (per record; the others
are still named): an invalid name, the record's own, a name already taken (as `amo add` does),
a record that needs `amo index` first, an existing directory for the name, and under
`--from-tags` a named record without `--force` or one not fetched from Wallhaven. It writes the
name, then renames the directory (restoring info.yaml if that fails), and updates the index and
any theme profile's wallpaper link into the directory, so neither needs a re-run. Prints the
directory of each record named; `--dry-run` logs the names instead.

FILTERS are the class flags above, and `--hue`. WALLHAVEN: `--tags QUERY` (Wallhaven's `q`),
`--purity LIST` (default sfw), `--category LIST` (general, anime, people; default all),
`--atleast WxH`, `--ratio LIST` (`W:H` or `WxH`), `--color HEX`. Wallhaven's `colors`
parameter takes only its 29 fixed swatches (`SWATCHES` in `wallhaven.py`), which have no names;
any other colour is replaced by the nearest swatch by OKLab distance, with a log line. `amo fetch` prints the path of each file kept, one per line,
and exits non-zero if it kept fewer than `--count` (`--test-set` prints and fails as under
"Test set"). `--dry-run` measures thumbnails, downloads
nothing, and prints the page URL of each wallpaper it would keep.

`amo fetch --refresh-tags [PICTURE...]` (amo-ugu; MH 2026-11-20 put it under `fetch`, which
already holds the API key, the pacing and the purity rules) asks Wallhaven again (`/w/<id>`,
paced as a search) for the tags of records already kept and writes `source.tags` and
`source.tag_categories` (see "Names of fetched records"): the PICTUREs given, or every indexed
Wallhaven record whose info file has no `tag_categories`, so a second run asks nothing. No image
is downloaded; the API key is looked up only when an nsfw record is among them. A tag list that
changed on Wallhaven is written too, with a warning naming what was added and removed. It takes
no search, look or keeping options, updates the index, and prints the directory of each record
written; `--dry-run` asks Wallhaven and writes nothing. A record that fails (gone from
Wallhaven, not fetched from it, needing `amo index`) is logged, the others still refreshed, and
the exit status is non-zero. `amo name --from-tags --force --dry-run` then shows the names the
categories give.

## Theme engine (v0.2)

**Status: agreed with MH 2026-10-30** (proposed 2026-10-29; the decisions are under "Theme
engine: decisions" at the end of this section). Background, sources and the rejected options:
[research/tinted-theming.md](research/tinted-theming.md) (its "Direction" is the input; points
where this section departs from it are marked **departs**).

amontillado makes a palette (from a picture, a palette file or a tinted-theming scheme), checks
its contrast, renders one file per configured app into a per-profile cache, and runs each app's
reload command. It never edits an app's own config: the user's config (chezmoi's, for MH)
includes the rendered file, as pywal's `~/.cache/wal` is included (chezmoi D39). It runs neither
tinty nor pywal; matugen or wallust generate palettes, and matugen renders an app's template only
when that app asks for it (`render_with: matugen`).

### Flow

```text
amo theme apply PICTURE            1. generate a palette, both variants (generator adapter), or load one
                                   2. check contrast per variant, adjust colours that fail
                                   3. render every app into <cache>/.<profile>.new/
                                   4. swap it in for <cache>/<profile>/, point `current` at it
                                   5. run each app's reload command, then the wallpaper hook
```

A render error (a missing template, a template that does not parse, an unknown variable) stops
the apply before step 4: the old theme stays whole. A reload that fails is a warning (the app may
not be running). Nothing in `apply` uses the network; template sources are fetched beforehand by
`amo theme sync`.

### Palette

A palette is a YAML file: per variant, base24 plus roles. A palette generated from a picture
always holds both variants; a preset or scheme holds what it was given (usually one).

```yaml
version: 1                      # palette format version
name: wallhaven-xed63v          # the picture's name or id, the preset's or scheme's name
source:                         # informational
  picture: 01HXYZ...            # record id, when generated from a picture
  file: wallhaven-xed63v.jpg
  lightness: 0.31               # the picture's lightness metric, for variant: auto
  generator: matugen 4.2.0
  hues: amontillado             # who assigned base08-base0F ("Generators")
  generated: 2026-10-29T18:00:00+00:00
tone: transform                 # optional (v0.11): a preset opts in to tone ("Tone: decisions" 3)
variants:
  dark:
    base24:                     # base00-base17, "#rrggbb"
      base00: "#1b1d2b"
      # ...
      base17: "#e48bff"
    roles:                      # any role left out is derived (below)
      accent: "#7aa2f7"
      on_accent: "#1b1d2b"
      secondary: "#bb9af7"
      on_secondary: "#1b1d2b"
      border: "#7aa2f7"
      border_inactive: "#565f89"
      selection: "#33467c"
      on_selection: "#c0caf5"
      error: "#f7768e"
      warning: "#e0af68"
      success: "#9ece6a"
      info: "#7dcfff"
    adjusted: [base03, on_accent]   # written by the contrast check: colours it changed
  light:
    base24: {}                  # same keys
    roles: {}
```

**base24** follows the tinted-theming base24 styling guide: `base00`-`base07` a neutral ramp
(background to lightest foreground), `base08`-`base0F` the named accents (red, orange, yellow,
green, cyan, blue, magenta, brown), `base10`-`base11` darker backgrounds, `base12`-`base17` the
bright red, yellow, green, cyan, blue and magenta. A base16-only input gets the base24 keys
derived in OKLCH: `base10`, `base11` step `base00` darker (L −0.03, −0.06, *initial*; lighter for a
light variant), `base12`-`base17` are `base08`, `base0A`, `base0B`, `base0C`, `base0D`, `base0E` 0.08 L away
from the background (lighter for dark, darker for light; calibrated 2026-11-13, below), clipped
to the sRGB gamut by lowering chroma.

**Roles** fill the gap the research found: base16 has no accent. Derived when the generator or
the file does not give them:

| Role | Derived from |
|---|---|
| `accent` | the generator's accent (matugen's primary, wallust's most chromatic colour); else the `base08`-`base0E` accent nearest in hue to the picture's `hue` metric; for a scheme or preset, `base0D` (the convention templates follow) |
| `on_accent`, `on_secondary` | whichever of `base00` and `base07` contrasts more with it |
| `secondary` | the generator's secondary; else the next accent by hue distance from `accent` |
| `border`, `border_inactive` | `accent`, `base03` |
| `selection`, `on_selection` | `base02`, `base05` |
| `error`, `warning`, `success`, `info` | `base08`, `base0A`, `base0B`, `base0C` |

`warning` is `base0A` (yellow) rather than base24's `base0F` ("warning elements", usually brown):
status bars and notifications expect yellow; a palette file can set it.

**Variant** chooses which of the palette's variants is applied: `auto`, `dark`, `light` or
`system`. It is set globally (`theme.variant`, default `auto`), per run (`--variant`), and per app
(`apps.<app>.variant`, which wins over both). `auto` is light when the picture's `lightness`
metric is above the `--light` threshold (0.65), dark otherwise; for a palette without a picture,
its dark variant if it has one. `system` follows the desktop's colour scheme, read once per
`amo theme apply` (and only when some variant in play is `system`): the xdg settings portal's
`org.freedesktop.appearance color-scheme` through `gdbus` (1 dark, 2 light), else gsettings'
`org.gnome.desktop.interface color-scheme` (`prefer-dark`, `prefer-light`). With no preference
from either (portal 0, gsettings `default`) or neither readable (no session bus, no GLib tools),
it is `auto` with a warning naming why. It lets something else own the dark/light choice (a
timer, darkman) while every later apply, a wallpaper change included, keeps to it
([colour-scheme-hooks.md](colour-scheme-hooks.md), "Following the scheme"). A variant the palette lacks (a one-variant preset) is a warning,
and the app gets the variant the palette has: amontillado never makes a variant by inverting a
palette (the chezmoi plan dropped inversion: it does not give good contrast). Formats that
address both variants at once (the matugen view's `.dark` and `.light`) get both when the
palette has both.

**Presets.** Palette files in `$XDG_CONFIG_HOME/amontillado/palettes/<name>.yaml`
(`--palette NAME` or a path). `amo palette --from-scheme FILE [FILE]` converts a tinted-theming
scheme (base16 or base24 YAML, e.g. from the `tinted-theming/schemes` catalogue) into a palette,
deriving the missing keys and roles as above; given two files (a family's dark and light
schemes, as gruvbox and solarized ship), it makes one palette with both variants, each file
placed by its `variant` key. Both scheme formats are read: the current one (`system`, `name`,
`variant`, colours under `palette`) and the legacy one (`scheme`, colours at the top level
without `#`); a scheme without a `variant` is dark when its `base00` has OKLCH lightness below
0.5. The palette's `name` is the scheme's, or for two the words their names begin with
("Gruvbox dark, hard" and "Gruvbox light, hard" make "Gruvbox"); `source.schemes` records each
variant's scheme name, author and file. Colour values must be quoted strings (an unquoted
`282828` is a YAML integer). A palette file is validated on load: `version: 1`, a name, at least
one of `dark` and `light`, all of `base00`-`base0F` per variant, colours as `"#rrggbb"`, and no
unknown key inside a variant (a misspelt role would otherwise be silently derived); an unknown
top-level key is a warning.

### Contrast checks

WCAG 2 contrast ratios on the sRGB colours (widely understood, and what most theme checkers
report; APCA is the alternative, see decisions). Pairs and minimums (*initial*):

| Foreground on background | Minimum | Why |
|---|---|---|
| `base05` on `base00`, `base01` | 7.0 | body text |
| `base04` on `base01` | 4.5 | status bar text |
| `base03` on `base00` | 3.0 | comments, inactive text |
| `base08`-`base0E`, `base12`-`base17` on `base00`, `base01` | 4.5 | syntax and terminal colours |
| `on_accent` on `accent`, `on_secondary` on `secondary` | 4.5 | labels on focused elements |
| `on_selection` on `selection` | 4.5 | selected text |
| `border` on `base00` | 3.0 | non-text UI (WCAG 1.4.11) |

Each variant is checked on its own. `theme.contrast` sets what happens to a failing pair:
`adjust` (default), `report` (log failures, change nothing) or `off`; `--no-adjust` gives
`report` for one run. `amo palette --check FILE` reports on a palette file.

Adjusting moves a colour in OKLCH lightness (away from the other colour of the pair, hue kept,
chroma lowered only to stay in gamut) by the smallest step that passes; if even the end of that
side (black or white) does not pass, it crosses the other colour instead, to the nearest
lightness on the far side that passes (amo-1xk: a foreground darker than a dark background goes
light). Each change is logged and listed under `adjusted`. What may move, in order:

1. the foreground of the pair;
2. `accent` (and `secondary`), only when no foreground fixes the pair: in practice `border`
   (the accent) on `base00`. A label always can at 4.5, since black or white reaches 4.5 on any
   colour (the worst, at middle luminance, still gives about 4.58), so a label on an accent
   flips side rather than the accent moving;
3. never the ramp backgrounds `base00`, `base01`, `base10`, `base11`.

Foregrounds first, because each fix then touches one pair only: a background sits under every
foreground, so moving it to fix one pair changes all the others. The accent is the palette's
link to the picture, so it moves last and as little as possible.

After each move every pair is checked again, so a colour moved for one pair is seen by the
next. A role that is the moved colour moves with it (amo-z9z): `border` with the accent,
`success` with `base0B`, `border_inactive` with `base03`, and so on, so a derived role keeps
the colour that passed; a role a palette file sets apart is a foreground like any other. A pair no allowed move fixes (body text at 7 on a background of
middle lightness, which neither black nor white reaches) stays as it is, with a warning. `--no-adjust` turns `adjust` into `report`; it does not turn checking back on under
`off`. `amo palette --check FILE` prints the accent metrics (below) and each failing pair
(`dark: base03 on base00: 2.52, needs 3`) on stdout and exits non-zero if there are any; it
never adjusts. It also reports, per variant and never as a failure, how xterm's fixed colours
16-255 read on `base00` ("Light variants and fixed colours"). (A first run on gruvbox,
2026-10-30: dark needed five moves, light twelve, mostly its accents on `base01`; the light
variant's brightened `base12`-`base17` came back down to about their base colours.)
**Bright step, calibrated** (amo-50c.4, MH 2026-11-13): over the 13 pictures of MH's library
(`amontillado` hues), a light variant whose brights were L +0.08 had 76 colours adjusted, all
of them brights, which ended a mean 0.041 L above their base colours and 3 of 6 within 0.04
OKLab of them (0.005 at the closest: the same colour), at a lower contrast on `base00` than the
normal colours (4.85 against 4.96-6.76). At L −0.08 nothing is adjusted, every bright is 0.08
OKLab from its base colour, and contrast rises to 7.0-9.5; MH preferred it in kitty side by
side. So the step goes away from the background, as `base10`-`base11` do (and as
gruvbox-light's brights, which are darker).

### Accent metrics

The contrast check cannot see two failures that matter for terminal colours: an accent off the
hue its ANSI name promises (git, ls and compiler errors rely on red being red), and two accents
too close to tell apart. Two numbers per variant, over ANSI colours 1-6 (`base08` red, `base0B`
green, `base0A` yellow, `base0D` blue, `base0E` magenta, `base0C` cyan, base16-shell's mapping):

- **hues**: how many of the six are *on their hue*: chroma at least 0.03 (OKLCH) and hue within
  45° of the OKLCH hue of the sRGB primary their name promises (`#ff0000` 29°, `#00ff00` 143°,
  `#ffff00` 110°, `#0000ff` 264°, `#ff00ff` 328°, `#00ffff` 195°).
- **distinct**: the smallest OKLab distance between two of the six, x100, to one decimal. Under
  about 8 two accents are hard to tell apart in a diff or a listing.

45°, 0.03 and 8 are *initial* (chezmoi's `palette-compare` definitions, which these mirror). The
nominal hues are not evenly spaced: yellow and green are 33° apart, so at one lightness and a
chroma of 0.13 they sit at about 7; a palette separates them in lightness (yellow lighter).

Report only (MH, 2026-11-02): `amo palette --check FILE` prints `dark: hues 6/6, distinct 13.3`
per variant before any failing pair, and its exit status reflects contrast failures alone.
Enforcement may follow calibration under `theme.hues` (amo-aqp.20). The functions are public in
`amontillado.accents` (`score`, `hue_fidelity`, `distinctness`, `on_hue`, `nominal_hues`,
`accent_colours`, and the thresholds) so chezmoi's `palette-compare` can import or mirror them.

### Generators

An adapter takes a picture path and returns, per variant, the neutral ramp (`base00`-`base07`),
the accents it knows (`accent`, `secondary`) and its own sixteen colours (used only under
`theme.hues: generator`, below); amontillado completes the palette as above. Generators are
external programs, detected at run time (`pipx install` works without them; the commands that
need one say so):

- **matugen ≥ 4.0** (first): one run gives both variants: Material roles (`primary` as
  `accent`, `secondary`, the surfaces) and tonal palettes (`neutral` at tones 0-100, for the
  ramp). Its `base16` block does **not** assign the named hues (checked on 4.2.0, 2026-10-30, by
  chezmoi's generator comparison on the 8 test-set pictures): the only backend is `wal`,
  pywal-style clustering independent of the Material engine (`-t` and `--contrast` leave it
  byte-identical); 0-2 of colours 1-6 lie within 45° of their ANSI hue, and nothing enforces
  contrast (the accents on `base00` reach 1.00:1 on every picture, collapsing into the background
  on dark or muted ones). Command line (4.2): `matugen image PICTURE -c CONFIG --dry-run -j hex -q
  --source-color-index 0`. CONFIG must hold a `[templates]` table (empty will do; an empty
  `[config]` alone does not parse), and off a terminal `--source-color-index` or `--prefer` is
  required ("Multiple source colors found"). JSON keys: `base16`, `colors`, `image`,
  `is_dark_mode`, `mode`, `palettes`; `colors.<role>.{dark,light}.color`,
  `base16.baseXX.{dark,light,default}.color`, `palettes.<name>.<tone>`. Fedora ships 3.1.0,
  whose JSON and command line differ (4.0, 2026-02, added the base16 backend, `hex_alpha` and the
  `format` / `set_alpha` filters, and changed the default JSON): amontillado reports the version
  and refuses rather than parse an untested format. The adapter (`amontillado.generators`) runs
  matugen in a throwaway config, cache and state home and takes, per variant: `accent` and
  `secondary` from `colors.primary` and `colors.secondary`; the ramp `base00`-`base07` from
  `palettes.neutral` at tones 5, 10, 20, 50, 70, 95, 98, 100 for dark and 98, 95, 90, 50, 40,
  10, 5, 0 for light (*initial*, calibrated below); its own sixteen colours from `base16`. On a cloudscape from
  the library (2026-11-03) `base16`'s `base08`-`base0F` were all near-black (`#03080c` to
  `#090e12`), darker than the ramp's `base00`; the contrast check moves them across it, light
  (it once only moved a foreground away from its background, here darker, which black could not
  fix: amo-1xk).
- **wallust ≥ 3.0** (second; built and checked on 3.5.1, amo-aqp.16): 16 colours clustered
  from the image, in no reliable order (red lands anywhere). Useful when matugen is not
  installed. The adapter runs it twice, in a throwaway config and cache home, with `run PICTURE
  -N -n -s -T -q --print-scheme` (no config, cache, terminal sequences or templates; the
  colours on stdout after a log line):
  - `-p dark16` gives the ramp and the accent, for both variants. The ramp is a grey at the
    matugen ramp's tones (OKLCH lightness of Material tone T: the cube root of its luminance),
    at the hue of wallust's background (colour 0), chroma at most 0.006 (about matugen's
    neutral; *initial*): the named hues' lightness targets were calibrated against that ramp, so
    the two generators share it. The accent is the most chromatic of colours 1-6 (*initial*) at
    the lightness of Material tone 80 (dark) or 40 (light), matugen's primary tones, since the
    clustered colour's own lightness ranged 0.30-0.71 over the library.
  - `-k -c lchansi -p ansidark16` gives its own colours (`hues: generator`): the settings that
    put each hue in its ANSI slot (by holding most accents fixed: green, yellow, blue, magenta
    and cyan were identical on all 13 library pictures, red and the background follow the
    picture), mapped onto `base08`-`base0E` by the ANSI table in reverse. ANSI has no orange or
    brown: `base09` and `base0F` are the named hues'. **Departs**: the agreed text had a second
    run with `ansilight16` for the light variant, but wallust 3.5.1 has no light ANSI palette
    (`light16`, `softlight16` and the other light palettes hold 0-4 of the 6 hues on their
    name), so both variants take these colours and the contrast check darkens them for light.

  Checked 2026-11-03 on the 13 library pictures, contrast adjusted (as the calibration below):

  | | tc fails | adjusted | hues | distinct |
  |---|---|---|---|---|
  | wallust, `amontillado`, dark / light | 0 / 0 | 0 / 5-6 | 6/6 | 8.9-12.2 / 9.2-10.9 |
  | wallust, `generator`, dark / light | 0 / 0 | 3-6 / 10-12 | 6/6 | 8.7-12.8 / 7.2-8.1 |
  | matugen, `generator`, dark / light | 0 / 0 | 0-13 / 0-13 | 0-2/6 | 0.0-5.4 / 0.0-1.9 |

  (`tc fails` here is amontillado's own contrast check, not `palette-compare`'s.) Under
  `amontillado` wallust matches matugen; under `generator` it holds every hue, matugen none.
  (matugen's `generator` row had 0-16 / 0-2 failures before the check could cross a
  background, amo-1xk.)

`theme.generator` in the config picks one; default the first installed in that order.

**Named hues** (`theme.hues`, per run `--hues`) say who assigns `base08`-`base0F`, and so ANSI
colours 1-6 and 9-14:

- `amontillado` (default), for either generator: each named hue keeps a fixed nominal OKLCH hue
  (no blending toward the picture); its chroma follows the picture's (the accent's, scaled) and
  its lightness a target per variant (both *initial*); the contrast check then adjusts as for
  any palette. The picture shows in the ramp, the accent and the chroma: a named hue cannot
  follow the picture's hue and stay that colour. Values (`amontillado.hues`, *initial*):

  | | red `base08` | orange `09` | yellow `0A` | green `0B` | cyan `0C` | blue `0D` | magenta `0E` | brown `0F` |
  |---|---|---|---|---|---|---|---|---|
  | hue of | `#ff0000` 29° | `#ff8000` 53° | `#ffff00` 110° | `#00ff00` 143° | `#00ffff` 195° | `#0000ff` 264° | `#ff00ff` 328° | orange's |
  | L dark | 0.72 | 0.76 | 0.86 | 0.76 | 0.80 | 0.625 | 0.74 | 0.62 |
  | L light | 0.50 | 0.53 | 0.53 | 0.45 | 0.50 | 0.52 | 0.48 | 0.42 |

  Chroma is the accent's (scale 1.0) within 0.09-0.16, brown at 0.6 of it; a colour outside
  sRGB loses chroma. Every target passes 4.5:1 on `base01` before adjusting; yellow sits
  lighter than green (their hues are 33° apart, "Accent metrics"); the dark variant's blue is
  the darkest accent because terminals use it as a background under `base05` (fast-syntax-
  highlighting's paired brackets, less's prompt), which needs 3:1 while blue still needs 4.5:1
  on `base01`. That pair of constraints set the ramp: with `base00`/`base01` at tones 5/10
  (Material's surface is 6) and `base05` at 95 the window for blue is L 0.62-0.63; at tones
  10/15 and 90 there is none.

  **Calibration** (2026-11-03, the 13 library pictures including the 8 of the test set, scored
  with chezmoi's `palette-compare` metrics, contrast adjusted):

  | | tc fails | fg/bg | accent min | distinct | hues |
  |---|---|---|---|---|---|
  | Blazer (the live kitty baseline) | 0 | 13.89 | 4.43 | 7.9 | 6/6 |
  | `amontillado`, dark | 0 | 16.6-16.7 | 5.25-5.29 | 8.9-11.0 | 6/6 |
  | `amontillado`, light | 2 | 16.3-16.4 | 4.95-4.98 | 9.2-9.5 | 6/6 |
  | `generator` (matugen `base16`), dark | 1-25 | 13.2-13.3 | 1.01-6.84 | 0.0-5.4 | 0-2/6 |

  The dark variant matches or beats the baseline on every picture with no colour adjusted.
  The light variant's two failures are fast-syntax-highlighting styles on 256-colour cube
  entries (`bg=18`, `fg=113`), which no 16-colour palette sets and which assume a dark
  terminal; its 5-6 adjusted colours were all the bright `base12`-`base17`, then L +0.08 from
  their base colour: the light variant's brights are darker since (amo-50c.4, "Contrast
  checks").
- `generator`: the generator's own sixteen colours (matugen's `base16` block; wallust's ANSI
  settings above), then the contrast check, which fixes contrast but not a wrong or collapsed
  hue. For comparison, or for a user who prefers them.

`source.hues` in the palette records which. Rejected: matugen's `custom_colors` with
`blend = true` (Material's harmonization), checked on 3 pictures 2026-10-30. It solves contrast
(every hue at tone 80, 10.9:1 on the surface) but moves each hue 10-30° toward the picture's
source colour, so neighbours collapse (on an orange picture red `#ffb595` beside orange
`#ffb878`; blue 32° toward purple), and every accent gets the same lightness.

### Template sources

| Source | Format | Where templates come from |
|---|---|---|
| `builtin` | mustache | shipped in the package (`amontillado/templates/`), variables-only |
| `tinted` | mustache | tinted-theming template repositories (MIT), e.g. `tinted-terminal`, `base16-rofi` |
| `matugen-themes` | matugen | `InioX/matugen-themes` (MIT) |
| `pywal` | pywal | `eylles/pywal16`'s `pywal/templates/` (MIT) |
| `url` | stated | one file at a commit URL, with its `sha256` |
| `path` | stated | a local file (the user's own template) |

**The registry** (`amontillado/registry.yaml`, shipped) names per source its templates, each by
the app it is for (`sources.tinted.rofi`; a second template for one app gets a suffix:
`rofi-colors`, `hyprland-conf`, `rofi-light`), with its output file and whether the result is a
complete theme or variables only; a fetched source's entry also has its repository, path in it
and the file's `sha256`, and each repository one pinned commit. The built-in templates are
entries of `builtin`. A release of amontillado moves the pins: `tools/registry.py --update`
takes each repository's default-branch head, fetches every registered file at it and records
its hash, and checks that a tinted template is one its `templates/config.yaml` builds for base16
or base24 (not `tinted8`, whose variables differ). The user's config overrides an entry with
`source: url` (its own pinned URL and hash) or `source: path`. `amo theme sync` downloads each
file the config needs (one HTTPS request per file at the pinned commit, no git) into
`$XDG_CACHE_HOME/amontillado/sources/`, named by its `sha256`: a file kept there is the right
one when its name matches its content, so a pin that moves fetches anew and an unchanged file is
never fetched twice. A file whose hash differs is an error and is not kept; `--check` fetches
nothing and fails on a missing or changed file. `amo theme apply` checks each file's hash
again as it reads it. `theme.yaml` records each app's source, template, and for a fetched one
the pinned commit and hash. Templates fetched this way are not redistributed by amontillado;
any template copied into `builtin` keeps its copyright notice in `THIRD-PARTY.md` (none is, so
far).

Initial registry (2026-11-01): `tinted`: kitty and foot (tinted-terminal's base24 templates),
rofi and rofi-colors (base16-rofi), dunst, waybar (variables), shell (tinted-shell, base24),
vivid (base16-vivid, added in v0.10); `matugen-themes`: kitty, gtk, css, rofi, dunst, sway, swaybar, hyprland (Lua), hyprland-conf,
mako, foot, tmux, nvim (`nvim-colors.vim`), nvim-lua (`neovim/matugen.lua`, a colourscheme of
`nvim_set_hl` calls over Material roles; the directory's `init.lua` is example glue and
`template.lua` needs the `nvim-base16` plugin), zed; `pywal`: kitty, waybar, css, rofi,
rofi-light, sway, hyprland-conf, mako, shell, json. Not taken: tinted-nvim's templates (each
renders `require("tinted-nvim").load("base24-<slug>")`, which loads only a scheme the plugin
bundles; the plugin can instead take amontillado's palette as a custom scheme, `setup({ schemes
= { ["base24-amo"] = dofile(".../palette.lua") } })`, needing no template), and
base16-gtk-flatcolor (GTK 2 and 3 legacy colour names for the FlatColor theme, which its README
has the user clone and patch by hand to import them; nothing for libadwaita: the built-in
`libadwaita` covers it).

**Built-in templates** (variables-only, every role included, initial set from the chezmoi plan's
app table): `kitty` (`color0`-`color15`, background, foreground, cursor, selection; an `include`
file; with `palette_generate semantic`, so kitty derives colours 22-255 from them: "Light variants
and fixed colours") and `kitty-fixed` (the same without it, for kitty before 0.47), `gtk` (`@define-color` for every key: imported by waybar, swaync and wlogout styles, and by
GTK3 `gtk.css` and libadwaita's `gtk-4.0/gtk.css`), `rofi` (a `* { ... }` block of variables),
`hyprland` (a Lua table, D62), `hyprlock` (hyprlang `$variables`), `sway` (`set $variable`),
`dunst` (a `dunstrc.d` drop-in with the urgency colours: dunst has no variables, so this one is a
small complete theme), `libadwaita` and `libadwaita-vars` (below), `nvim` (`palette.lua`),
`shell` (`export
AMO_BASE00=...`), `json` (the palette as JSON, for anything else) and `vivid` (below). `amo
theme templates` lists them with their variables.

`vivid` (amo-c0i, v0.10) is a complete [vivid](https://github.com/sharkdp/vivid) theme,
`vivid.yml`: `LS_COLORS="$(vivid generate vivid.yml)"` (truecolour, or `vivid -m 8-bit`). amo
renders it and never runs vivid (MH 2026-11-21: the consumer runs `vivid generate`, e.g. from a
reload command). It exists because LS_COLORS sets such as trapd00r/LS_COLORS are fixed 256-cube
colours for dark backgrounds: under a light variant (picture 3qz176, `base00` #f8f9fb) 42 of
their pairs are below 3:1. Every foreground is a colour the contrast check holds on `base00`
(the accents and brights at 4.5, `base03` at 3.0 for unimportant files and licences), and a
cell background is always an accent under `base00` text, the same pair the other way round
(WCAG ratios are symmetric), so the palette's check covers the whole theme and adds no pair; a
test walks the rendered theme to keep it so. Per-file-type shading comes from the hues and the
base24 brights (`base12`-`base17`, a step further from the background than their accents):

| vivid category | Colour |
|---|---|
| directory | `base0D` bold |
| symlink; fifo; socket, door; block and character devices | `base0C`; `base0A`; `base0E`; `base0A` bold |
| executable file, `executable` | `base0B` bold |
| missing symlink target | `base08` bold |
| broken symlink, setuid; setgid; file with capability; sticky and other-writable; other-writable; sticky | `base00` on `base08`; on `base0A`; on `base09`; on `base0B`; on `base0D`; on `base0E` |
| `text`: special and todo; licences; configuration; other | `base13` bold; `base03`; `base0A`; `base05` |
| `markup` | `base09` |
| `programming`: source; tooling (its CI files `base0B`) | `base0B`; `base14` |
| `media`: image; audio; video; fonts; 3d | `base0E`; `base0C`; `base17`; `base15`; `base16` |
| `office` | `base12` |
| `archives` | `base08` bold |
| `unimportant` | `base03` |

Regular files, normal text and hard links are uncoloured (the terminal's foreground).
**Decision** (MH 2026-11-21, from comparison sheets of 3qz176's palette): rare file types keep
a cell background, as `base00` on an accent (option B). Rejected: base16-vivid's own pairs
checked as new contrast pairs (option A: setuid's `base05` on `base08` is 2.27:1 in dark,
other-writable's `base0E` on `base0B` 1.15:1, and adjusting would move the body text or magenta
in every app); kept in view: no background, bold accent text (option C, calmer), to review
after use (amo-z9h).

**Prior art** (design gates, amo-c0i): tinted-theming/base16-vivid (MIT) renders from a base16
scheme, and is in the registry as `tinted` `vivid` (`base16-vivid.yml`). It fails MH's
requirement of per-file-type shading: seven categories (text, markup, programming,
configuration, office, fonts, video) share one colour, `base07`, which in amo's palette is the
strongest foreground beside `base05` regular files, and it uses neither `base09` nor the base24
brights. Its cell backgrounds are option A above. vivid's `ansi` theme follows the terminal's
ANSI 0-15, which MH ruled out (too few colours for the shading); its other bundled themes
(gruvbox, solarized, ...) are fixed colours, not the palette's. Checked with vivid 0.11.1,
base16-vivid at 546a950.

`libadwaita` (amo-aqp.21) is complete like `dunst`, since libadwaita's colour names are a fixed
API: it defines libadwaita's named colours (checked against libadwaita 1.9.1's own stylesheet)
from the roles and ramp, so one file serves as `gtk-4.0/gtk.css` and, under adw-gtk3,
`gtk-3.0/gtk.css`. `accent_bg_color`/`accent_fg_color` are `accent`/`on_accent`; destructive and
error are `error`, success `success`, warning `warning`, each on `base00` (a contrast pair when
the role is derived from `base08`, `base0B`, `base0A`); window and the secondary sidebar are
`base00`, view `base10` (darker than the window in dark, lighter in light, as in Adwaita);
headerbar, sidebar, card, dialog, popover and thumbnail `base01`; every foreground `base05`;
borders `base02`; shadows black at Adwaita's strengths per variant. Only `@define-color`, plus
one plain rule: GTK3 fails on a `:root` block of CSS variables, and libadwaita 1.9 still reads
its variables from these names (`--accent-bg-color: @accent_bg_color`). The rule (amo-inx) sets
`color: @accent_fg_color` on `button.suggested-action` (and its `:hover`, `:active`, `:checked`)
and `.terminal selection`/`.terminal text selection`, where adw-gtk3 6.4 hard-codes white text
on the accent: with a dark variant's light accent that text was white on light blue (chezmoi
measured the fix at 11.72:1 dark, 4.88:1 light). adw-gtk3's other white text sits on its own
near-black OSD backgrounds, independent of the palette. Under libadwaita the rule restates what
the stylesheet already does; `libadwaita-vars` carries it too, and a test checks both templates
hold the same rule and that `accent_fg_color` reaches 4.5:1 on `accent_bg_color`. Not the standalone `accent_color`,
`destructive_color`, `success_color`, `warning_color`, `error_color`: libadwaita ≥ 1.6 derives
those from the `*_bg_color` in OKLab by its own colour scheme (lightness at most 0.5 for light,
at least 0.85 for dark), so the desktop's `color-scheme` (`prefer-dark` for a dark variant)
must match the variant applied, or a dark palette gets dark accent text. amontillado does not
set the scheme (a global setting other apps and tools read); a reload command reading
`$AMO_VARIANT` does, written by the user: [colour-scheme-hooks.md](colour-scheme-hooks.md). Not defined: the GNOME palette (`blue_1` … `dark_5`, fixed hues apps name on
purpose), the names libadwaita derives itself (`theme_*`, `insensitive_*`), and the
variables-only `--active-toggle-*` and `--overview-*`: `libadwaita-vars` sets those.

`libadwaita-vars` (amo-j24.2) is the same `@define-color` block followed by a `:root` block of
libadwaita's CSS variables, so it serves `gtk-4.0/gtk.css` only (with it, `libadwaita` serves
`gtk-3.0` alone). It **departs** from the planned `@import` of `libadwaita.css`: a
relative `@import` resolves against the path GTK loaded, so a copied or symlinked `gtk.css`
would look for `libadwaita.css` in `~/.config/gtk-4.0/`; the block is repeated instead, and a
test keeps the two templates' colours equal. The `:root` block pins the standalone
`--accent-color` (`accent`), `--destructive-color` and `--error-color` (`error`),
`--success-color` and `--warning-color`, which libadwaita otherwise derives from the
`*_bg_color` by the desktop's colour scheme; `.osd` widgets still derive theirs (libadwaita
redefines them there), and the symbolic-icon palette follows the pinned ones.
The active toggle follows Adwaita's construction, since a toggle group's track is its text
colour at 10 % over whatever surface holds it: in dark, `--active-toggle-bg-color` is `base05` at
20 % over the track (always lighter than it) with `base07` text; in light, `base11` (the
lightest ramp colour) with `base05`. An opaque `selection` (`base02`), the first choice, measured
1.05:1 against the track on a `base01` card in the live test (gruvbox dark), all but invisible.
`--overview-bg-color`/`-fg-color`
`base01`/`base05`. Then GNOME's palette, `--blue-1` … `--dark-5`, which libadwaita 1.9
defines as literals (so `@define-color` cannot reach an app naming `var(--blue-3)`), from the
view's `gnome-*-hex` ("Formats and views"). Not set: the accent presets `--accent-blue` …
`--accent-slate` (the system accent's choices, which the stylesheet never reads and the named
accent overrides) and the non-colour variables (`--border-opacity`, `--window-radius`, ...).
The colour-scheme hook stays useful: GtkSourceView styles and app assets still follow the
scheme. Tests: every colour variable of libadwaita 1.9's `:root` blocks is defined (the accent
presets aside), and each standalone colour reaches 4.5:1 on every libadwaita surface, the
overview pair 4.5:1, and on every surface the active toggle 1.15:1 against the track (about
Adwaita's own on its white view) with its text at 4.5:1, on gruvbox after the contrast check.
Checked live (`tools/libadwaita-live-test.sh`): screenshots with gruvbox and Lumina Polaire
(2026-11-06), and MH's visual check with Catppuccin Mocha and Latte (2026-11-07).
GTK3 apps follow live through `amo hook gtk3-theme` (amo-lfk, decision 12 under "Theme engine:
decisions"), the `libadwaita` app's reload: it sets `org.gnome.desktop.interface gtk-theme` to
`amontillado-$AMO_VARIANT`, through `Adwaita` when the value is already set (an unchanged value
notifies no one), and writes that theme's `gtk-3.0/gtk.css` under `$XDG_DATA_HOME/themes` when
missing, never over an existing one: an `@import` of adw-gtk3 (`adw-gtk3-dark` for dark, found
under `$XDG_DATA_HOME` or `$XDG_DATA_DIRS`), then of `<cache>/current/libadwaita.css`, both as
absolute `file://` URLs (a relative one resolves against the theme's path; `current` so a reload
reads the swapped-in profile). It exits 1 without touching `gtk-theme` when `gsettings` or
adw-gtk3 is missing. The user setup, GTK3 and GTK4 together: [gtk-theming.md](gtk-theming.md).
Variables keep the palette's names (`base0A`, `on_accent`) except in rofi, whose parser rejects
`_` (rofi 2.0): there roles are hyphenated (`on-accent`). The hyprland and hyprlock colours are
`rrggbb` without `#`, so a config can add alpha (`"rgba(" .. c.accent .. "ee)"`, `rgb($accent)`);
the others are `#rrggbb`. kitty's file sets `color0`-`color21` (the ANSI table under "Formats and
views", then base16-shell's extras `base09`, `base0F`, `base01`, `base02`, `base04`, `base06`),
the tab, border, selection and URL colours, and `palette_generate semantic` (`kitty-fixed`: not).
Headers name the palette by its slug, never its
name, so no quote in a name can break a Lua, shell or JSON file. Default output files: `kitty.conf`,
`colors.css`, `colors.rasi`, `hyprland.lua`, `hyprlock.conf`, `sway`, `dunst.conf`,
`libadwaita.css`, `libadwaita-vars.css`, `palette.lua`, `colors.sh`, `palette.json`.

### Formats and views

Each format gets a *view* of the palette: the variables its templates expect.

- **mustache** (tinted-theming's builder spec, rendered with `pystache`, MIT): for every base24 key
  *and every role* the spec's variables (`accent-hex`, `accent-hex-r`, `accent-rgb-r`,
  `accent-rgb16-r`, `accent-dec-r`, `accent-hex-bgr`, ...), and `scheme-name`, `scheme-slug`,
  `scheme-slug-underscored`, `scheme-system` (`base24`), `scheme-variant`,
  `scheme-is-dark-variant` / `scheme-is-light-variant`; also `scheme-tone` (`full`, `soft` or
  `dim`, outside the spec: "Tone: decisions"), `scheme-author` (the scheme's, or
  empty) and `scheme-description` (empty), which template headers name. Outside the spec,
  amontillado adds `gnome-<colour>-hex` for GNOME's palette remapped onto the palette
  (`gnome-blue-1-hex` … `gnome-dark-5-hex`, hex only; `amontillado/gnome.py`): each hue family
  keeps libadwaita 1.9's OKLCH lightness ladder (steps 1-5, *initial*: blue 0.80 0.70 0.61
  0.56 0.49, green 0.88 0.82 0.76 0.72 0.63, yellow 0.94 0.91 0.87 0.84 0.76, orange 0.85 0.79
  0.72 0.65 0.57, red 0.68 0.62 0.58 0.52 0.47, purple 0.75 0.64 0.53 0.49 0.42, brown 0.76
  0.65 0.56 0.52 0.42), the same in both variants as in GNOME's, and takes hue and chroma from
  its colours: red `base08`/`base12`, orange `base09`, yellow `base0A`/`base13`, green
  `base0B`/`base14`, blue `base0D`/`base16`, purple `base0E`/`base17`, brown `base0F`. A step
  darker than both colours takes the darker one's hue and chroma, lighter than both the
  lighter one's, and in between both are interpolated by lightness (hue the short way round);
  chroma drops only to stay in gamut. `light-1` … `light-5` and `dark-1` … `dark-5` are the
  ten ramp colours (`base00`-`base07`, `base10`, `base11`) sorted lightest first, so
  `light-1` is the lightest and `dark-5` the darkest in either variant. Decimals have eight
  places (`0.48627451`), `rgb16` is the 8-bit value times 257. The output is not HTML-escaped,
  and partials (`{{> name}}`) are a render error: a template is one file, never one read from
  the working directory. pystache renders an unclosed section to the end of the template rather
  than failing. A tinted template written for base16 only
  renders unchanged (base24 is a superset). Tinted repositories hold several templates
  (`templates/config.yaml`); the registry names which one.
- **pywal** (pywal16's syntax: `{color0}`, `{color0.strip}`, `{color0.rgb}`, `{color0.lighten(10)}`,
  ...; a small renderer of its own, since pywal16 parses markers itself rather than with
  `str.format`): `color0`-`color15` by the base24 ANSI table (0 `base00`, 1 `base08`, 2 `base0B`,
  3 `base0A`, 4 `base0D`, 5 `base0E`, 6 `base0C`, 7 `base05`, 8 `base03`, 9 `base12`, 10 `base14`,
  11 `base13`, 12 `base16`, 13 `base17`, 14 `base15`, 15 `base07`), `background` (`base00`),
  `foreground` and `cursor` (`base05`), `wallpaper`, `alpha` (100). Every colour property pywal16
  defines, and its `lighten` / `darken` calls. An unknown property is a render error.
  Checked against pywal16's source at the registry's pin (`pywal/util.py`, `export.py`): the
  properties (`strip`, `rgb`, `rgbspace`, `rgba`, `xrgba`, `hex_argb`, `alpha`, `alpha_dec`,
  `alpha_hex`, `decimal`, `octal` and their `_strip` forms, `red`/`green`/`blue` and their
  `_hex`/`_dec` forms, `w3_luminance`) and the functions `lighten`, `darken`, `saturate` (sets
  the HLS saturation), `foxify` and `adjust_alpha`, chained (`{color4.lighten(10).strip}`),
  with pywal16's arithmetic: channels truncated, a percentage stripped of every non-digit
  (`lighten(2.5)` is 25 %, `darken(-10)` is 10 %), and an `adjust_alpha` undone by any later
  function (each returns a new colour at the default alpha). `tests/test_pywal_parity.py`
  checks every property and function against pywal16 itself (a dev dependency pinned to the
  release matching the registry's commit). `{{` and `}}` are literal braces. Where
  pywal16 logs and goes on, amontillado fails: a `{...}` that does not parse (pywal16 skips the
  whole file), an unknown colour or property, a function on `wallpaper`, `alpha` or `checksum`,
  and arithmetic that leaves 0-255 (pywal16 prints a three-digit channel). Markers are replaced
  where they stand (pywal16 replaces a marker's first occurrence in its line, which can be an
  escaped copy). `checksum` (pywal16: the picture's MD5, for its cache) is the palette's slug;
  `wallpaper` is the profile's picture, or empty.
- **matugen** (**departs**: the direction had matugen render these with `--import-json`):
  amontillado renders the subset of matugen's template language that matugen-themes uses, over a
  Material view of the palette. Counted over all 74 matugen-themes templates (2026-10-29): 4,476
  of 4,680 markers (96%) are plain colour fields (`{{colors.<role>.<mode>.hex}}`, `hex_stripped`,
  `red`, `green`, `blue`); the rest are the fields `rgb`, `rgba`, `hex_alpha`, the filters
  `set_alpha`, `set_lightness`, `auto_lightness`, `saturate` (with `hsl`), `lighten` and
  `replace` (each in a few templates), `for` loops over `colors` and `base16` with
  `if loop.last`, `{{image}}`, and the `base16.*` keys. One template loops over `palettes`
  (Material's tonal palettes, which the palette does not have): not supported. Anything else is
  a render error naming it.

  Built (`amontillado.matugen`, 2026-11-03) and checked byte for byte against matugen 4.2.0 on
  all 73 files of matugen-themes at the registry's pin (68 templates and READMEs; three source
  colours, both modes; `quickshell.json`'s `palettes` loop is the one refusal); the committed
  test is our own probe template with matugen's recorded output. What parity took, from
  matugen's and colorsys 0.6.7's source: channels are floats from csscolorparser's f32 ratios
  (231 is 231.0000014), which shows wherever a format truncates; `hex` rounds, `rgb`, `red`,
  `green`, `blue` and `hex_alpha` (upper case) truncate, `rgba` rounds half to even with the
  alpha printed Rust-style (`1`, `0.1`); `lighten`, `auto_lightness` (lighter below HSL
  lightness 50, darker above) and `saturate` step HSL and clamp; `set_lightness` *sets* HSL
  lightness, so matugen-themes' negative values give black, as under matugen; loops run in key
  order with `loop.index`, `first`, `last`; whitespace after `<* if ... *>` and `<* else *>` is
  dropped. The view also has `mode` and `is_dark_mode`, and the custom colours
  `neovim/matugen.lua` names (`red`, `orange`, `yellow`, `green`, `teal`, `blue`, `purple` from
  `base08`-`base0E`; `maroon`, `mint`, `sky`, `lavender`, `pink` from `base12`, `base14`-`base17`);
  `image` is the profile's picture, or empty (matugen prints `Null`). This settles the research's open question: matugen's
  `--import-json` only *adds* variables, its `colors.*` always come from its own generation, so
  with matugen rendering, a preset or wallust palette could not drive matugen-themes templates
  at all. Rendering ourselves works for every palette and needs no matugen at theme switch.
  An app can still choose matugen as its renderer (`render_with: matugen`, below).

  The Material view is a table that computes every Material role name those templates use
  (`colors.primary`, `colors.surface_container_high`, ...) from the palette at render time: `primary` from `accent`, `secondary`
  from `secondary`, `tertiary` from the `base08`-`base0E` accent farthest in hue from `accent`,
  `error` from `error`, each with its `on_*` (`on_accent`, `on_secondary`, else whichever of
  `base00` and `base07` contrasts more), `*_container` (the colour at `base02`'s OKLCH
  lightness, chroma × 0.6, *initial*, for either variant: `base02` is the selection background
  in both; the agreed text had `base06` for a light variant, but base16 light palettes put
  their darkest colours there), `on_*_container` (at `base06`'s lightness), and the `*_fixed`
  family (mode-independent, as in Material: `fixed`, `fixed_dim`, `on_fixed`,
  `on_fixed_variant` at L 0.92, 0.84, 0.22, 0.40, *initial*); surfaces from the neutral ramp
  (`surface`, `background` = `base00`; `surface_container_lowest` … `_highest` = `base11`,
  `base10`, `base01`, `base02`, and `base02` moved 0.03 further from `base00` in L;
  `surface_dim` and `surface_bright` = `base00` and that, swapped for light; `surface_variant`,
  `outline_variant` = `base02`; `on_surface`, `on_background` = `base05`, `on_surface_variant`
  = `base04`, `outline` = `base03`); `inverse_surface` = `base05`, `inverse_on_surface` =
  `base01`, `inverse_primary` the other variant's accent (else the accent); `shadow`, `scrim`
  black; `source_color`, `surface_tint` the accent. The full table lives in code, with a test that it covers
  every role matugen 4.2 exports. `.dark` and `.light` give the palette's dark and light
  variants, `.default` the applied one; with a one-variant palette all three give that variant.
  Of the 74 templates, only `zed-colors.json` uses both modes (a dark and a light Zed theme in
  one file); six use only `.dark`, which under matugen stays dark in light mode and here gives the
  palette's dark variant.

### Per-app configuration

In `config.yaml`, under `theme` (all keys optional):

```yaml
theme:
  cache: ~/.cache/theme                 # default $XDG_CACHE_HOME/theme
  profile: default                      # the profile `amo theme apply` writes without --profile
  generator: matugen                    # default: the first installed of matugen, wallust
  hues: amontillado                     # amontillado | generator ("Generators")
  variant: auto                         # auto | dark | light
  contrast: adjust                      # adjust | report | off
  wallpaper: {reload: 'hyprctl hyprpaper wallpaper ",$AMO_WALLPAPER,cover"'}
  apps:
    kitty:    {reload: "pkill -USR1 kitty"}                   # source defaults to builtin
    rofi:     {source: tinted}                                 # complete theme from base16-rofi
    waybar:   {source: builtin, template: gtk, output: waybar-colors.css, reload: "pkill -USR2 waybar"}
    hyprland: {source: matugen-themes, reload: "hyprctl reload"}  # hyprland-colors.lua
    zed:      {source: matugen-themes, render_with: matugen}
    rofi-alt: {source: tinted, template: rofi, variant: light, output: rofi-light.rasi}
    nvim:     {}                                               # palette.lua, for a lush spec
    mytool:   {source: path, path: ~/.config/mytool/theme.mustache, format: mustache, output: mytool.conf}
```

Each key's meaning, default and trade-offs are in the commented template `amo config init`
writes, [`src/amontillado/config.template.yaml`](../src/amontillado/config.template.yaml),
generated from one table in code (`amontillado.config_keys`, which also writes the `--help` of
each flag that overrides a key; `just config-template` regenerates the file, and a test fails
when it is stale). Not repeated here. What the keys do that the template does not say:

- `url` + `sha256` pin a template, since some outputs are code (`hyprland.lua`, sourced shell
  files): an unpinned template would run someone else's code at every theme switch.
- `render_with: matugen` (amo-aqp.14, `amontillado.generators.matugen_render`): amontillado
  writes a matugen config holding every such app's template and runs matugen once per apply and
  variant those apps ask for (`matugen image PICTURE --source-color-index 0 -m MODE`, or `matugen
  color hex ACCENT -m MODE` with the variant's accent for a palette without a picture), in a
  throwaway config, cache and state home; it reads the rendered files back and writes them with
  the others, so the profile still swaps in whole and a failing matugen run stops the apply.
  `theme.yaml` records the app's `renderer` (`matugen 4.2.0`). The colours are matugen's own,
  since matugen cannot take colours in (`--import-json` only adds variables): checked
  2026-11-03, on one picture matugen's surface was `#1a1110` against the palette's `base00`
  `#15100f`. Config-only, no CLI override.

The block is checked whenever the config is loaded (any `amo` command), so a mistake fails at
once, naming its key (`theme.apps.kitty.reload: ...`); unknown keys warn, as at the top level.
Beyond the types and choices above: a profile name is a single path component that does not
start with `.` and is not `current` (both name other things in the cache); `output` is a plain
file name, not `palette.yaml`, `theme.yaml` or `wallpaper`, and no two apps give the same one;
`url` is `https://`; a reload command (`sh -c`, "Config") names none of the old
`{placeholder}`s; its `AMO_VARIANT` is the app's variant, `auto` resolved (for the wallpaper hook,
that of an app without its own), and with no wallpaper `AMO_WALLPAPER` is unset and a command
naming it is skipped; `render_with:
matugen` needs `format: matugen` (or `source: matugen-themes`, whose format it is).

`amo config check [FILE]` loads a config as every command does and fails on an error, an
unknown key, an app whose template cannot be found or read (a fetched one not yet synced), two
apps that would write one output file, or a command (`sh -c`, "Config") that `sh -n` cannot
parse. `--shellcheck` also runs shellcheck on each command as a POSIX sh script, its findings
problems too (quoting advice, mostly; opt-in, so a plain check stays a check). Loading the
config never runs `sh -n`, so other commands pay nothing for it. At run time a command's exit
status 127 or 126 is named (command not found, not executable); `api_key_command`, whose own
errors are never shown since they could hold the key, is parsed with `sh -n` first so a syntax
error is named too.

Whether a result is complete or variables-only comes from the registry (`amo theme templates`
shows it); a variables-only file does nothing until the app's own config maps the variables.

### Cache

`<cache>/<profile>/` (chezmoi D39, default `~/.cache/theme/default/`) holds every rendered
file, plus `palette.yaml` (the palette applied), `wallpaper` (a symlink to the picture) and
`theme.yaml` (what was applied: time, palette name, and per app the source, template, pinned
commit and output). `<cache>/current` is a symlink to the profile last applied (`--no-activate`
renders a profile without moving it). App configs include from `current/`, or from a fixed
profile; the "falling back to `current/`" of D39 is the user's include line, which amontillado
does not need to know about. `<cache>/<profile>` is itself a symlink, to a generation directory
`<cache>/.profiles/<profile>/<time>-<random>/`: each apply writes a new generation, then renames
a new symlink over the profile's (and over `current`; `ln -sfn` is not atomic). A directory
cannot be renamed over a non-empty one, so swapping real directories would leave a moment with
no profile at all; with symlinks an app reading during an apply sees the old theme or the new
one, never a mix and never nothing. The previous generation is kept for a reader still inside
it; older ones are deleted. A real directory at `<cache>/<profile>` is not amontillado's: apply
refuses to touch it. `--no-activate` renders the profile without moving `current` and runs no
reload command (the profile is not live).

A file watcher must watch a directory that is never replaced: `<cache>/` itself, reacting to
`current` (or a profile name) being renamed. A watch on `current/palette.lua` watches the
profile directory the link pointed to when the watch began, and goes deaf when that directory
is swapped out; a watch on a file goes deaf whenever the file is replaced by rename. (Tested
2026-11-02: a watch on `current/palette.lua` saw no event on the first apply, three when its
generation was deleted one apply later, then none.) An apply with `--no-activate` to the profile
`current` points to renames only the profile's link, so a watcher reacts to that name too. (A real
`current/` directory, files copied in, was considered: its watch path is stable, but the switch
is no longer all-or-nothing, and an app reading mid-copy can see two themes.)

`--app NAME` (repeatable) re-renders only those apps: the new profile directory starts as a copy
of the current one. Without a PICTURE or `--palette` that is always consistent (after a config
change). With one, the named apps get the new palette and the others keep the old; `theme.yaml`
records each app's palette, and `amo theme current` warns when they differ.

### nvim and lush

The built-in `nvim` template renders `palette.lua`:

```lua
return {
  variant = "dark",
  base00 = "#1b1d2b", -- ... base17
  accent = "#7aa2f7", on_accent = "#1b1d2b", -- ... every role
}
```

A watcher on the cache directory (`~/.cache/theme/`, filtered on `current` and the profile it
points to; see "Cache" for why not on `palette.lua`) re-runs `colorscheme`, so nvim needs no
reload command. Three ways to turn the palette into highlight groups, all sharing that watcher
([docs/examples/nvim/](examples/nvim/README.md), documentation, not a plugin):

| | Who maps colours to groups | Gives | Costs |
|---|---|---|---|
| **lush.nvim** spec over `palette.lua` (`docs/examples/nvim/`, amo-aqp.17) | the user's spec | the roles exactly as the bar, borders and terminal use them; colour operations | writing and keeping the coverage (treesitter, LSP, plugins) |
| **tinted-nvim** v1, the palette as custom scheme `base24-amontillado` (`docs/examples/nvim/lua/amontillado/tinted.lua`, amo-aqp.22) | the plugin | upstream-kept coverage of core, treesitter, LSP and many plugins, no authoring | base16 conventions (no accent role: `base0D`); a plugin |
| **matugen-themes** `neovim/matugen.lua` (`template: nvim-lua`, `docs/examples/nvim/lua/amontillado/matugen.lua`, amo-aqp.13; upstream's pinned file has a stray last line, see the example's README) | upstream's file | accent-aware (Material roles), one pinned file, no plugin | upstream's choices; colours through the Material view |

Which one is the user's choice (chezmoi D73 plans lush). The lush example passes the palette's
`#rrggbb` strings to lush rather than `lush.hsl()` values, which round-trip through rounded HSL
and moved a channel by one in a test (`#1d2021` became `#1d2020`).

### CLI (v0.2)

```text
amo palette PICTURE [--generator G] [--hues H] [--no-adjust]   a palette (both variants) as YAML
amo palette --from-scheme FILE [FILE] [--no-adjust]   one or two tinted-theming schemes as a palette
amo palette --check FILE                       accent metrics and contrast report; non-zero if a pair fails
amo theme apply [PICTURE | --palette NAME|FILE] [--profile P] [--variant V] [--hues H] [--app NAME]...
                [--no-adjust] [--no-activate] [--no-reload] [--dry-run]   render, swap in, reload
amo theme sync [--check]                       fetch (or verify) every template the config needs
amo theme templates [APP]                      registry entries, sources and their variables
amo theme current [--profile P]                the applied palette's name, picture and time
amo config init [--stdout] [--force]           write the commented config template
amo config check [--shellcheck] [FILE]         validate a config file
```

PICTURE is any form under "Lookup": its record's default file, or the file named; without one,
`amo theme apply` re-renders the profile's current palette (after a config change), keeping its
wallpaper link. `--dry-run` renders into a temporary directory, prints its path and what would
be reloaded, and changes nothing. `amo theme apply PICTURE` points the profile's wallpaper link
at the picture and records it as shown (`amo shown`), so the usage table sees theme switches;
not under `--dry-run` or `--no-activate` (nothing is shown). PICTURE with `--app` is refused:
a new picture re-renders every app. The generator is `theme.generator` (`amo palette` also
takes `--generator`).

New runtime dependency: `pystache` (MIT). matugen and wallust are optional external programs.

### Theme engine: decisions

Settled in the research: amontillado renders, no tinty; base24 plus roles; variables-only
built-ins; per-app YAML; pinned URLs; `palette.lua` for lush; matugen ≥ 4 before wallust.
Agreed with MH, 2026-10-30:

1. **matugen-format templates are rendered by amontillado** over the Material view (**departs**
   from the research's direction), with `render_with: matugen` per app, config-only, its caveats
   documented. If the filter subset proves too costly, support the plain colour fields only (96%
   of markers) and let the templates using filters fail.
2. **Palettes from pictures hold both variants** (free with matugen, a second wallust run);
   `variant` (global, `--variant`, per app) chooses which is applied. Presets hold what they are
   given; a missing variant warns and falls back. No inversion.
3. **Contrast: WCAG 2 ratios, `theme.contrast: adjust | report | off`** (default `adjust`;
   `--no-adjust` per run). Foregrounds move first, then the accent as a last resort, never the
   ramp backgrounds. APCA models perceived contrast better for dark themes but has no settled
   thresholds.
4. **`current` is a symlink**, swapped atomically; watchers watch the cache directory.
5. **No network in `apply`.** Templates are fetched only by `amo theme sync`; a missing one is an
   error naming the command. A timer-driven switch then never waits on GitHub.
6. **`variant: auto` from the `lightness` metric** (light above 0.65).
7. **`warning` is `base0A`** (yellow), not base24's `base0F`.
8. **The wallpaper hook lives in amontillado's config** (`theme.wallpaper.reload`), so wallpaper
   and theme switch as one step; the command itself (hyprpaper, swaybg) is still the user's.
9. **matugen 3 is refused** until Fedora ships 4.x or MH installs it from COPR, cargo or a
   release binary (chezmoi plan, step 1).
10. **`--app NAME`** (repeatable) applies to a subset of apps ("Cache").
11. **amontillado builds the named hues** (`theme.hues: amontillado`, default; MH, 2026-10-30,
    from chezmoi's generator comparison): matugen 4.2's `base16` block is clustering, not named
    hues, and wallust's colours are unordered, so neither generator's ANSI 0-15 is usable as is.
    Fixed nominal hues, chroma and lightness from the picture, the ramp and accent from the
    generator. `hues: generator` keeps the generator's own colours as an option, a palette-level
    key beside `theme.generator` rather than an app: it changes the palette every app gets.
    matugen's `blend` harmonization was rejected (neighbouring hues collapse). wallust stays.
12. **amontillado ships the GTK3 live reload** (`amo hook gtk3-theme`; MH, 2026-11-21, from a
    dotfiles request to document the setup): a helper, not only docs, so dotfiles drop their own
    script. MH confirmed before the build: it sits under `amo hook` (whose description now
    covers reload commands as well as `on_change`), and it **writes the two theme
    directories' `gtk.css` when missing** rather than only checking them. Prior art, each failing
    a requirement: adw-gtk3 alone (fixed colours; it is the base the theme imports), wpgtk (its
    own pywal pipeline, not amontillado's palette), base16-gtk-flatcolor (hand-patched, legacy),
    Gradience (archived 2024), Themix/oomox (a sassc rebuild per apply), a user
    `gtk-3.0/gtk.css` (read at app start: not live). Machine-specific setup (installing
    adw-gtk3, X11's xsettingsd) stays with the user.

## git-annex libraries (v0.4)

Each library root may be a git-annex repository: info files in git, images annexed (epic
`amo-qnn`; "Roadmap", item 6). Repository and remote setup is git configuration owned by the
dotfiles, not amontillado config; the layout, locked and unlocked files, the merge driver, the
hook payload and a short encrypted setup are in [version-control.md](version-control.md)
(amo-qnn.5); key management and restore are machine setup, outside amo.

### git-annex libraries: decisions

1. **The NSFW library is encrypted off-machine with git-remote-gcrypt, never git-crypt**
   (spike amo-qnn.1, agreed with MH 2026-11-07). Tested with git-annex 10.20260115, git 2.54,
   git-remote-gcrypt 1.5 and git-crypt 0.8 on throwaway repositories, checking the remotes for
   plaintext with git objects decompressed:
   - **gcrypt** (the git side through a `gcrypt::` remote, the images in a git-annex special
     remote with `encryption=hybrid`): nothing readable off-machine: info files, record names
     (paths), the git-annex branch (every image's SHA-256 and location log) and commit messages
     are all encrypted. A fresh clone restores with `git clone gcrypt::URL`, `git annex init`,
     `git annex enableremote <special remote>`, `git annex get`; the clone's git remote must not
     carry the special remote's name (`clone -o <that name>` makes enableremote refuse).
   - **git-crypt fails twice.** First, `git annex init` writes `* filter=annex` into
     `.git/info/attributes`, which outranks `.gitattributes`, so a `filter=git-crypt` there
     never applies: info files were pushed in plaintext, silently. Adding the line to
     `.git/info/attributes` fixes one clone only (it is not versioned), and a clone without it
     commits plaintext at its first sidecar edit. Second, even when it works it encrypts file
     contents only: record names (tag-derived with `amo name --from-tags`), the git-annex
     branch with each image's hash (which identifies a known Wallhaven image) and commit
     messages stay readable. So the two filters cannot share paths, and git-crypt does not meet
     the goal anyway.
2. **MH's setup: git on GitHub, images on the SSD backup drive.** The gcrypt remote is a GitHub
   repository (opaque there: a few encrypted files; it needs force pushes allowed, since gcrypt
   rewrites its branch, and `gcrypt.require-explicit-force-push` set so that is explicit).
   git-annex cannot keep image content in a hosted git repository, so the images go to a second
   special remote with `encryption=hybrid` (a `directory` remote on the drive). The other
   setup, one gcrypt remote holding git and images together (`type=gcrypt` on an ssh host or a
   local or USB path, as tested), is named beside it in version-control.md.
   Rehearsal findings (2026-11-21: git-annex 10.20260115, git-remote-gcrypt 1.5, gpg 2.4.9,
   Cv25519 keys, a bare repository as the gcrypt git backend):
   - **`git annex sync` cannot push** with `gcrypt.require-explicit-force-push` set (it pushes
     without `--force`). The working routine is `git annex pull <git remote>`, `git annex push
     <special remote>`, then `git push --force <git remote> <branch> git-annex`.
   - **The first push must be `--force` too**: one without it records a `gcrypt-id` that makes
     every later push abort, until `git config --unset remote.<name>.gcrypt-id`.
   - **Push cost**: a push uploads about twice the new git data, and after more than 25 packs
     gcrypt repacks and uploads everything again (2,000 records with ~19 KB thumbnails: about
     40 MB per repack). Acceptable at that scale, so the decision holds.
3. **One OpenPGP key per machine, Curve25519** (`gpg --quick-gen-key "<name>" default default
   never`: Ed25519 signing, Cv25519 encryption; the data itself is AES-256, chosen by OpenPGP
   and gcrypt, not configured), **plus an offline backup key** as one more recipient, so that
   losing every machine loses nothing. Separate keys, not per-machine subkeys of one key:
   OpenPGP encrypts to one encryption subkey per key. Every key is a recipient of both remotes:
   `gcrypt-participants` lists them and the special remote's cipher is encrypted to each.
   - **Adding a machine** (from one that has access, tested): add its key to
     `remote.<name>.gcrypt-participants` and push (the manifest, which holds each pack's key,
     is encrypted to all participants at every push, so the new key reads the whole history; no
     rewrite), and `git annex enableremote <special remote> keyid+=<key>` (re-encrypts the
     cipher only, not the images; a `directory` remote also needs `directory=<path>` there).
     A key never added cannot decrypt (tested). `initremote keyid=A keyid+=B` silently ignores
     the `keyid+=`: create with one key, add the others with `enableremote`.
   - **Removing a machine does not revoke what it holds**: `keyid-=` and dropping it from the
     participants stop it reading what comes later, but it knows the special remote's cipher
     and has every pack it fetched. Real revocation is a new remote and a new upload.
   - **`gcrypt-publish-participants` is required with Curve25519 keys.** It stores the
     recipients' key ids in the remote (it hides no content but shows whose keys open it).
     git-annex turns it on only for a `type=gcrypt` special remote; for a `gcrypt::` git remote
     it is off unless set by hand (`git config remote.<name>.gcrypt-publish-participants
     true`). Off, the recipients are hidden, and with two or more Cv25519 recipients gpg logs
     `ecdh failed in gcry_cipher_decrypt: Checksum error` and exits 2 even though it decrypted,
     so gcrypt reports `Failed to decrypt manifest`: every participant but one is locked out
     (with RSA keys gpg exits 0 and hidden recipients work).
   - **Signing key per remote.** gcrypt signs the manifest with
     `remote.<name>.gcrypt-signingkey`, else `user.signingkey`, and accepts only manifests
     signed by a participant. A global signing key that is not a participant (a YubiKey for
     commits, say) makes every machine reject the remote, so set `gcrypt-signingkey` to the
     machine's own key in each clone.
4. **`annex.largefiles` takes one pattern per line** (found in the spike, for every annexed
   root): a gitattributes value cannot contain spaces, so `* annex.largefiles=(include=*.jpg
   or include=*.png)` is cut to `(include=*.jpg` and the images went into git. The layout uses
   `* annex.largefiles=nothing`, then `*.jpg annex.largefiles=anything` and so on for `.jpeg`,
   `.png` and `.webp`.
5. **amontillado stays VCS-agnostic; version control is an opt-in hook** (agreed with MH
   2026-11-10). A library is plain files and works the same under git, git-annex, Syncthing,
   rsync, a backup tool or nothing. amo itself never runs git, git-annex, gpg or gcrypt;
   recognising annexed files from the file alone ("Absent content") is the only awareness.
   - **`on_change`** (top-level config key, unset by default, amo-qnn.3): a command run under
     `sh -c` once per root per run that wrote files, with a JSON payload on stdin: each info
     file's text before and after amo's write, new files, renames and deletes. amo's writes
     stand whatever the hook does; a failing hook is a warning.
     Built (amo-qnn.3): the writers report to `amontillado.changes` as they write (info files
     with the text the record was read from, images and thumbnails, moves); the CLI records
     every command and, after it (a failed one too: what was written stands), runs the hook
     per root written to, under `sh -c` with AMO_ROOT and AMO_COMMAND (`index`, `fetch`,
     `add`, `crop`, `add-derived`, `edit`, `name`) and the payload on stdin; the hook's
     stdout goes to stderr (amo's stdout is data). The payload (`changes` module docstring):
     `version` 1, `command`, `root`, and `changes` of `rename` (from, to: within the root,
     listed first), `info` (path, before or null for a new file, after; a path in a renamed
     directory is its new one) and `file` (made or replaced, or moved in from outside the
     root or from a record's `.amo/`). An info file written back as it was read is no change.
     No command deletes files under a root, so there is no delete change yet.
   - **`amo hook git-commit`** is the shipped reference hook: one commit per root, limited to
     the payload's paths. Info files are merged with `amo info merge` (BASE: as amo read it,
     OURS: the committed version, THEIRS: as amo wrote it) and staged with `git hash-object` +
     `git update-index`, so a user's uncommitted edit stays unstaged and only amo's change is
     committed. In an annex root new images go in with `git annex add` (amo-qnn.4), which
     honours the user's `annex.largefiles`, `annex.addunlocked` and `annex.thin`; `git add`
     would always add them unlocked. A missing `git` or `git-annex` is a clear message, never
     a traceback, and `amo config check` flags it.
     Built (amo-qnn.3, `amontillado.gitcommit`): a root outside a git work tree is a
     warning. The commit is built in a temporary index (`GIT_INDEX_FILE`, read from HEAD):
     renames move the committed entries, merged info files go in as blobs, new files with
     `git add` unless git ignores them; then `git commit` on that index, so the user's hooks
     and signing apply and whatever they staged is neither committed nor lost. Afterwards the
     real index takes the new commit's entry for each path whose entry was the old commit's;
     a path the user had staged is left, with a warning. A conflict (or an info file that does
     not parse) leaves that record's paths out, with a warning naming it. Message:
     `amo <command>: <record names>` (three, then "and N more"), then each path.
     In a git-annex repository (annex.uuid set, or a git-annex branch: a clone where `git
     annex init` has not run must not get images into git either) new files go in with `git
     annex add` on the temporary index (it honours GIT_INDEX_FILE; tested with git-annex
     10.20260115), so the user's `annex.largefiles` decides what is annexed (thumbnails stay
     in git under `**/.amo/** annex.largefiles=nothing`) and `annex.addunlocked` whether it
     is locked; `annex.thin` applies as git-annex applies it. Without git-annex the new files
     are left uncommitted with a warning, the info files committed (amo-qnn.4). `amo config
     check` finds an annexed root from its files (a `.git` with an `annex` directory), since
     it runs no git.
   - **`amo info diff` / `amo info merge`** (amo-qnn.6): a schema-aware diff and three-way
     merge with git's merge-driver contract, also usable as a real merge driver for info files
     edited on two machines. Conflicts are by unit, not by line: a top-level key, except that
     each `files` entry is one unit; `default_file` goes with the `files` keys, `name` with the
     record directory. On conflict OURS is left untouched (no conflict markers, which would
     make the YAML unparseable). Needs comment-preserving YAML: ruamel.yaml replaced pyyaml
     (amo-j24.4, done), and info files are updated in place rather than re-dumped ("Records").
     Built (amo-qnn.6, `amontillado.infomerge`; the CLI is the interface): a unit changed on
     one side takes that side, changed alike on both is that value, changed differently on
     both is a conflict; the merge goes into OURS through the round trip (its comments stay)
     and must parse as a record (`derived_from` naming a file THEIRS removed is a conflict);
     a differing `schema` among the three is a conflict, never an upgrade; an empty BASE (git's
     add/add) is an empty mapping. Exit status: 0 merged (OURS rewritten only if THEIRS
     changed something), 1 a conflict (the units on stderr), 2 an unreadable or non-mapping
     file. `--name %P` names the path in messages (git passes temporary files), `--stdout`
     prints the result and writes nothing. `amo info diff` prints `+`/`-`/`~` lines per key
     path (mappings by key, lists whole; a key with a dot bracketed: `files["a.png"].width`)
     or `--json`, and exits 0 same, 1 different, 2 unreadable, as diff(1). As git's driver:
     `info.yaml merge=amo-info` (and `info.yml`) in `.gitattributes`, and
     `git config merge.amo-info.driver 'amo info merge %O %A %B --name %P'`.
   - Rejected: a built-in `git_commit: true` that runs git from amo's core (couples amo to git;
     the hook payload carries everything a targeted commit needs), and line-based patches
     (`git apply --cached`: context lines make unrelated nearby edits conflict, and say nothing
     about which keys belong together).
   - Encrypted remotes (gcrypt) are documentation only; key management and restore are machine
     setup, outside amo.

## Grouping (v0.7)

**Status: agreed with MH 2026-11-13** (spike amo-50c.1), built in epic `amo-6f0` and released
in v0.7.0 (2026-11-18), the distance recalibrated with MH (decision 6; the decisions are under
"Grouping: decisions" below). Pictures that go together, for several monitors, with
the theme taken from the primary monitor's picture ("Roadmap", item 2). Monitor detection and
the wallpaper setter stay in the user's desktop configuration: amo takes monitors as arguments.

**Colour signature** (amo-6f0.1). Each file's `metrics` gain a `palette`: 6 colours (*initial*)
from k-means in OKLab over the measured image (432 px wide, every 4th pixel), each with its
share of the pixels, largest first, as `[hex, share]` pairs (shares to 3 decimals):

```yaml
      palette: [['#1b2330', 0.412], ['#3d4a5e', 0.233], ['#c9a46b', 0.118], ...]
```

The k-means is deterministic (k-means++ from a fixed seed, at most 20 Lloyd steps, stopping
early when no pixel changes centre), so measuring a file again writes the same palette and an
info file under version control does not churn. Centres that round to the same hex colour are
merged, so an image with fewer distinct colours has a shorter palette (a solid colour has one).
It is written on one line (flow style), and `amo info merge` keeps it so. The k-means costs
about 60 ms per picture on noise, the worst case (the spike's 123 ms was a slower loop).
Metrics version 3: `amo index` measures every file again once (the other metrics are
unchanged). The index stores the palette as JSON in `files` (index schema 9). A file measured
before version 3 that is absent (annexed content not here) keeps its version 2 metrics, which
are still read and written back unchanged, and stays indexed without a palette until its
content is got; grouping skips it.

**Distance** between two pictures (calibrated with MH, decision 6): each palette colour's
distance to the nearest colour of the other palette, weighted, averaged over both directions,
in OKLab with three corrections (`amontillado.grouping`):

- the colour axes (a, b) count 2.5 times as much as lightness;
- near-black and near-white colours (L < 0.2 or > 0.95) count a quarter of their share, the
  weights then renormalised, so two mostly dark pictures are compared mostly on their accents;
- the difference in contrast (the share-weighted standard deviation of the palette's lightness)
  is added, a quarter of it;

and a **warmth gate**: a picture whose `warmth` is above 0.5 and one below -0.5 never go
together (infinite distance: never a companion, last in `amo list --like`). 0 is identical
colours. A cheap stand-in for earth mover's distance, which would need a linear-programming
solver (scipy). The distance is computed at query time from the stored palette and metrics, so
changing it needs no re-measuring. Two pictures are **compatible** when their distance is at
most `group.max_distance`, 0.09 (calibrated; on the calibration sample the median distance to
a picture's nearest neighbour is 0.065 and between any two pictures 0.167).

**`amo list --like PICTURE`** (amo-6f0.2) orders the matches by distance to PICTURE, nearest
first (ties by path), PICTURE's record left out; each record is compared through the file `amo
list` would print (its default file, or the `--aspect` match: a crop measures differently).
PICTURE is any form under "Lookup"; a file path compares that file, anything else the file
`amo list` would print for its record. `--max-distance D` keeps only those within D (it needs
`--like`; there is no default bound here, unlike `amo group`). It is an order, so it excludes
`--order` and `--random` (an error, not a silent choice). A PICTURE without a palette (indexed
before metrics version 3, or absent and measured before it) is an error naming `amo index`
(and `git annex get`); matches without one are left out with one warning.

**`amo group`** (amo-6f0.3) picks one picture per monitor:

```text
amo group [PICTURE] --monitor NAME=W:H [--monitor NAME=W:H]... [FILTERS] [--purity LIST]
          [--order least-shown|nearest] [--max-distance D] [--keep-category]
          [--predicate NAME]... [--predicate-cmd CMD] [--format tsv|json]
          [--non-interactive] [--apply] [--dry-run]
amo group --list-predicates
```

- **Monitors** are given in order, at least one, each name once; the first is the primary. Each
  monitor's file is chosen for its W:H as `--aspect` does, with the same crop offer (one
  question for all the monitors lacking a file of their ratio) and fallback ("Records");
  `--dry-run` never crops, taking the fallback.
- **The primary** is PICTURE if given (any form under "Lookup"; a file path is that file; it
  need not match the filters, and must be here and have a palette), else the first record
  matching the filters in `amo list --order least-shown` order (never shown first, ties at
  random) that has a compatible companion for every other monitor (amo-6f0.8): a picture too
  particular in its colours to fill the set is passed over, so the fallback beyond the bound
  happens only for a PICTURE given, or when no matching picture can fill the set (then the
  least shown, with a warning). Such pictures stay first in least-shown order, so each run
  tries them again: each monitor ratio's candidates are filtered once and their palettes
  stacked (`grouping.Pool`), one primary against the pool being one array operation, about 6
  ms for 5,000 pictures (some 8 s if a quarter of a 5,000-picture library cannot fill a set; a
  few hundred pictures take well under a second).
- **Companions** are the other records matching the same filters (and purity), through their
  file for their monitor's ratio, and compatible with the primary, distinct, taken in
  `--order`: `least-shown` (default, `group.order`) explores the library, `nearest` gives the
  most coherent set. Monitors are filled in the order given, each with the first such record
  left. Compatibility is to the primary only: the theme comes from it. Too few compatible
  records: the nearest beyond the bound (`--max-distance`, default `group.max_distance`) fill
  the rest, with a warning naming the monitors; a monitor with no matching record left is an
  error. Records without a palette yet are left out with one warning.
- **`--keep-category`** (amo-6f0.7, MH 2026-11-14): only companions of the primary's category
  (`source.category`, the index's `category`: general, anime or people for Wallhaven), since a
  palette does not see style and a photo beside a drawing clashes. A filter like the class
  flags, not a preference: too few such pictures is an error, though within them the nearest
  beyond the bound still fill in. A primary without a category is refused, and records without
  one are never companions (or automatic primaries) under it. Opt-in.
- **Predicates** (amo-6x6, MH 2026-11-14, shape agreed 2026-11-18): the user's own test of a
  companion, for what amo does not measure (a tag, a source, a rule per monitor).
  `group.predicates.<name>: {cmd, description}` (as `edit.tools`), `--predicate NAME`
  (repeatable: all must accept, the first rejection ending the round) and a one-off
  `--predicate-cmd CMD` (as `amo edit --extcmd`); `--list-predicates` lists them. A predicate
  runs under `sh -c` with `AMO_PRIMARY` and `AMO_CANDIDATE`, paths to JSON files amo writes in
  a temporary directory, never the info files: `{"record": ..., "file": {"path", "width",
  "height", "default", "metrics"}, "monitor": {"name", "aspect"}, "distance"}`, the record as
  `amo list --where` sees it (a row of the `pictures` view, `tags` and `info` parsed), the
  metrics as the info file has them (palette included), the distance to the primary to 3
  decimals (0 for the primary). `AMO_MONITOR` is the candidate's monitor; an `AMO_*` variable
  amo was started with never reaches it. Exit 0 accepts, 1 rejects (`jq -e` gives both);
  anything else (126, 127, a signal) stops `amo group` with an error. Its standard output goes
  to standard error; amo waits for it (no timeout: a predicate may ask the user). It is called
  lazily, in the order candidates are taken (least-shown, or nearest), stopping at the first
  accepted, the nearest beyond the bound included, and each pair's verdict is kept for the
  run. A hard filter like `--keep-category`: no candidate accepted is an error. It judges
  companions, not the primary itself, but an automatic primary needs a compatible companion it
  accepts for every other monitor (amo-6f0.8), so a primary it leaves alone is passed over;
  each one tried costs predicate runs, up to one per compatible picture. Later perhaps for `amo
  list --like` too.
- **Output**: `--format tsv` (default) prints `NAME<TAB>PATH` per monitor in the order given, so
  the first line is the primary and `amo theme apply` takes its path; `--format json` prints
  `{"primary": NAME, "monitors": [{"name", "aspect", "path", "record", "distance"}, ...]}`, the
  record by name or else id, the distance to the primary's palette to 3 decimals (0 for the
  primary).
- **Setting the wallpapers** (amo-6f0.6): `group.setter`, a config command run once per monitor
  under `sh -c` with `AMO_MONITOR` and `AMO_WALLPAPER` ("Config"; it must name
  `$AMO_WALLPAPER`), only with `--apply`, after the choice is printed. Its standard output goes
  to standard error. Each picture it set is recorded as shown (as `amo shown`); a setter that
  fails for a monitor (non-zero exit, or 30 s) is tried for every other monitor first, then
  fails `amo group`. `--apply` without a setter is refused; `--apply --dry-run` logs each
  command and records nothing. The config template carries commented examples, checked against
  each tool's documentation (November 2026): hyprpaper >= 0.8 (`hyprctl hyprpaper wallpaper`),
  awww (swww, renamed in its 0.12), `swaymsg output ... bg`, wpaperd (`wpaperctl set`) and
  xwallpaper; amo holds no setter's syntax in code. swaybg and feh get notes instead of setter
  examples: swaybg sets every output from one process, and feh assigns pictures by screen order
  in one call, so both are run from a script reading `amo group`'s output (tsv or json).

**Known limitations** (calibration, amo-6f0.4):

- A letterboxed picture's bars dominate its palette, so it groups with mostly black pictures (1
  of the 400 sample pictures). The fix belongs at add and fetch, not in grouping: v0.8 detects
  the bars and offers a crop to the picture as the default file ("Letterboxes (v0.8)").
- Palettes do not see style: within the bound, 30-33% of pairs are anime next to a photo (42%
  at random). `amo group --keep-category` is the cheap remedy; style measures (sharpness,
  perhaps a learned embedding) are amo-abc.

**Later** (amo-0k6, not v0.7): saved sets, now "Saved looks" (a set the user liked
with its theme, kept by name), and ratings of pictures and sets, with ratings feeding the
companion order (deferred).

### Grouping: decisions

Agreed with MH 2026-11-13 (spike amo-50c.1). The experiment: 8 random anchors from the 400
calibration thumbnails, the 5 nearest of each under the existing metrics (a mean colour from
`lightness`, `chroma` and `hue`, plus `hue_spread`) and under a 6-colour k-means palette, judged
by eye on a contact sheet (`just grouping-sheet` reproduces it).

1. **A stored palette, not the existing metrics.** The palette's neighbours were clearly better
   for 5 anchors and as good for the rest; the two agreed on 1.1 of 5 neighbours on average. A
   mean colour hides structure: neon green on black matched a green forest, colourful cubes a
   grey misty castle. Cost: k-means took 123 ms per thumbnail in plain numpy (measuring, 21 ms),
   and a metrics version bump. A fixed OKLab histogram (deterministic without a seed) was not
   taken: unreadable in an info file.
2. **Distance to the primary, not clusters.** Distances form a continuum with no natural
   clusters, so cluster boundaries would be arbitrary and move as pictures are added; ranking a
   whole library against one picture costs milliseconds, so precomputing saves nothing. Each use
   case is an order inside one distance bound: `nearest` (theming coherence), `least-shown`
   (exploring the library), later ratings. The "sensible presets" clusters would have given are
   saved sets instead (amo-0k6).
3. **`amo list --like`, and a separate `amo group`.** Ranking by one picture belongs to
   `amo list`; a set across monitors is a different output and gets its own command, not a
   `--monitor` mode of `amo list` (MH: unintuitive). Not `amo set` (reads as setting the
   wallpaper) or `amo create-set` (implies a stored set, which saved sets will be).
4. **Monitors are arguments** (`--monitor NAME=W:H`, the first the primary); detecting them
   stays in the desktop configuration.
5. **Output tsv or json, and an optional setter hook**, not built-in setter formats: setter
   command lines drift between versions, and the config command convention (`sh -c`, `AMO_*`)
   already covers it, with examples in the config template.
6. **The distance, k and the bound, calibrated by eye** (amo-6f0.4, MH 2026-11-14 to 11-18;
   `just grouping-sheet`, its threshold, sets, k, letterbox and variants modes, on the 400
   calibration thumbnails). Plain OKLab nearest-colour distance (the spike's) failed MH's
   judgment where colours differed but lightness matched: pictures sharing a hue on different
   backgrounds were far apart, mostly-black pictures matched whatever their accents, warm next
   to black-and-white, red next to blue. Measured cause: palette colours vary 7-8 times more in
   lightness than in colour (standard deviation 0.28 against 0.035 and 0.041), so lightness
   made up a median 61% of a distance. Variants were judged side by side on the same anchors:
   colour weighted 2.5 times (V1), plus extremes down-weighted (V2, best overall), plus a
   contrast term at 0.5 with the warmth gate (V3; MH liked most of its sets), then contrast
   alone at 0.25 and 0.5 and with the gate: 0.25 slightly better than 0.5; the gate changed
   one neighbour in 18 anchors but has no downside, so it stays. **k** stays 6: choosing k per
   picture by cluster validity (silhouette) gave 2 for 86% of pictures, since a wallpaper's
   colours form gradients, not clusters (the palette quantises; it does not find clusters),
   and on the sheets k = 4, 6 and 8 differed mostly in order, MH preferring 6 by a little.
   **The bound** 0.09: under the new distance, at 0.08 / 0.09 / 0.10, 64 / 74 / 85% of
   pictures have two companions (three monitors without falling back), 28 / 19 / 10% of the
   sample is never shown by automatic grouping once primaries that cannot fill a set are
   skipped (amo-6f0.8), and companions within it differ from the primary by a median hue of 16
   / 20 / 23 degrees (81 at random). MH preferred 0.08 and 0.09 to 0.10 by eye, and the
   companions between 0.09 and 0.10 were the visibly weaker ones; 0.09 keeps most of 0.08's
   coherence with a larger pool for the least-shown rotation. A larger or more uniform library
   than the sample has more companions per picture, so it could afford a tighter bound.

## Letterboxes (v0.8)

**Status: built in amo-5o8, thresholds calibrated with MH 2026-11-19** (decisions below).
Dark bars framing a picture (a film still's letterbox, a pillarbox around a narrower picture)
dominate its palette and metrics: it groups with black pictures and reads as dark. Detected
when a file is measured, cropped off on request.

**Detection** (`amontillado.letterbox`), on the measured image's OKLab lightness: a *bar row* is
a row whose mean lightness is below 0.15 and whose standard deviation is below 0.03; a
letterbox is a run of bar rows from the top edge and another from the bottom, each at least 3%
of the height, with a lit picture between them: at most 15% of the middle third of the rows
between the bars may be darker than 0.15. A pillarbox is the same along columns; a letterbox
wins over a pillarbox. The test is where the dark lies, not how uniform it is: a logo on black
also has uniform dark rows at both edges, but its middle is dark too. Off-the-shelf trimmers
(ImageMagick `-trim`, ffmpeg `cropdetect`, Pillow's `getbbox` recipe) cannot tell the two
apart. The bars found at the measuring width (432 px) are found again at the file's own
resolution along the axis they lie on (the image scaled to 432 px across the bars and kept
whole along them), so the box is exact in the file's pixels.

**Stored** as the file's `metrics.letterbox`, `[x, y, width, height]` (as `crop`), absent
without bars: metrics version 4, so the first `amo index` after upgrading measures every file
again once (a file whose git-annex content is not here keeps its version 2 or 3 metrics,
read and written back unchanged). Not in the index's `files` table: `amo index` counts from the
info files it reads.

**Commands:**

- `amo crop PICTURE --letterbox` (instead of `W:H`; no `--at` or `--interactive`) writes the
  box of the record's original as `<stem>-content.<ext>` (`derived_from`, `crop`, measured)
  and makes it the record's `default_file`, so `amo list`, `--like` and `amo group` use the
  picture without its bars; the original is kept. Refused: an original without bars, a record
  that needs `amo index`, and without `--force` a content crop already there (`--force`
  replaces it, never a file that is not a crop).
- `amo crop PICTURE W:H` of a letterboxed original cuts the largest W:H box inside the bars
  (`--at` places it there), so no aspect crop takes them in; `--interactive` starts from that
  box (a smaller scale) and can still be moved anywhere.
- `amo add` asks `... is letterboxed; crop the bars off? [Y/n]` when it may ask ("Records",
  Prompts), else (or on no) warns, naming `amo crop DIR --letterbox`. `--non-interactive`
  never asks.
- `amo index` counts the records whose default file is letterboxed in its summary (`N
  letterboxed (amo crop --letterbox)`); it never crops.
- `amo fetch` passes over a result whose thumbnail is letterboxed (counted in its summary):
  the bars skew the look the filters judge, and Wallhaven has more. `--keep-letterboxed` keeps
  them as downloaded, each with a warning naming `amo crop --letterbox` (fetch never crops; it
  runs unattended). A full image with bars its thumbnail did not show is kept, with the same
  warning.

### Letterboxes: decisions

Agreed with MH 2026-11-19 (amo-5o8). Calibrated on 542 Wallhaven thumbnails: the 400 of the
calibration sample and 150 from the queries "film stills", "movie scenes" and "screen shot"
(`just letterbox-sheet`: a sheet of the pictures found, one of those with bars at both ends
rejected for a dark middle, one of thin or one-sided bars).

1. **The thresholds.** All 9 pictures found (7 letterboxes, 2 pillarboxes) were true, with the
   content box right; 3 of them are among the 400 random pictures (0.75%). Of the 17 rejected
   for a dark middle, 15 are logos or figures on black (the middle 27-96% dark) and 2 are
   dark film scenes (24% and 71%). Nothing measured separates the 71% scene from the logos
   (the share of content pixels the bars' colour, the darkness next to the bars), so the
   bound is 15%: dark film scenes stay as they are rather than a logo's background being
   cropped. At 25% one scene more is found, with a logo at 27%. Bars thinner than 3% (two
   pictures with a 1% bar on one side, one with text in its bar) are left alone.
2. **Stored in the metrics** (version 4), so `amo index` counts letterboxes across the library
   and `amo crop` reuses the box; the cost is one re-measure of every file, and a changed
   `version` line in every info file.
3. **The crop is the default file, the original kept**: a derived file like any crop, so it can
   be made again; `default_file` makes every consumer use it without knowing about bars.
4. **`amo fetch` skips letterboxed thumbnails, `--keep-letterboxed` keeps them** (MH: an
   opt-in to keep them).

## Tone (designed in v0.10)

**Status: agreed with MH 2026-11-21 (amo-4rf)**, from comparison sheets and kitty windows of
3qz176 in every proposal; the decisions are under "Tone: decisions". Designed in v0.10, built in
v0.11 (epic amo-k79); its values are *initial*.

Full-contrast dark and light get tiring in a terminal all day. *Tone* is a gentler version of
a variant: **soft** light (cream paper, darker than white, dark-grey text) and **dim** dark
(charcoal, not near-black). It is not a third variant: the desktop's colour scheme (GTK's
`color-scheme`, the settings portal, `prefers-color-scheme`) is binary, so `variant: system`
could not pick a third, and `AMO_VARIANT` and `{{scheme-variant}}` stay `dark` or `light`.

### Tone: prior art

Checked 2026-11-21 on 3qz176 (`vocaloid-hatsune-miku-anime-girls-3qz176`) unless marked.

| Candidate | What it does | Fails |
|---|---|---|
| matugen 4.2 `--contrast -1` (tested) | Material's contrast level: lowers `on_surface` and the accents (dark `on_surface` `#dee3e6` → `#9ea4a6`, 7.35:1) | the backgrounds: `surface` is `#0f1416` / `#f5fafd` at −1, 0 and 1, and `palettes.neutral` (our ramp) is unchanged. It is less contrast on the same near-black, not a dimmer background. |
| matugen 4.2 `--type` (tested: tonal-spot, neutral, fidelity, content, monochrome) | Material scheme variants: chroma and hue rules | surfaces stay at Material's tones 6 / 98 in every type (`#111415`-`#131313` dark). |
| wallust 3.5.1 `softlight16`, `softdark16` (tested) | pastel palettes | background `#c8b5b1` (OKLCH L about 0.77, far below paper), colours in no hue order and no contrast check: decision 11's reasons wallust's own colours are not used. |
| Scheme families with a hardness axis: gruvbox hard/medium/soft (light soft `#f2e5bc`, dark soft `#32302f`), everforest, solarized light `#fdf6e3` (values from the bead's ticket) | a fixed scheme per tone | serves a preset only, not a palette from a picture. Already usable today: `amo palette --from-scheme` the soft files. The vocabulary comes from here. |
| nvim colourscheme options (gruvbox-material, everforest `background = "soft"`; from their docs, not tested) | the same axis inside one app | one app; the bar, GTK and kitty stay full. |

No candidate makes a gentler variant of a palette from a picture, so amontillado would build
it: a transform of a palette's full variant, the same for every app.

### Tone: prototype

A throwaway prototype (not in the repository) made the toned variants from each of the 13
library pictures' palettes (matugen, `amontillado` hues), then ran the contrast check and the
accent metrics:

- the ramp `base00`-`base07` re-derived at other Material tones: soft light 92, 89, 84, 55,
  42, 24, 18, 12 (full: 98, 95, 90, 50, 40, 10, 5, 0); dim dark 18, 22, 30, 55, 68, 86, 90,
  94 (full: 5, 10, 20, 50, 70, 95, 98, 100). Hue and chroma: the picture's neutral for dim;
  for soft either the picture's or a cream tint (hue 80°, chroma 0.024 on the backgrounds
  falling to 0.006 on `base07`);
- each accent (`base08`-`base0F`, `accent`, `secondary`) keeps hue and chroma (×1.15 for soft,
  so the accents stay apart) and takes the lightness whose contrast on the new `base01` is
  its full contrast moved 40 % of the way down to 4.7; brights and `base10`-`base11` derived
  as for any palette.

| 13 pictures | base00 (3qz176) | fg/bg | base04/base01 | comment | accents on base01 | hues | distinct | base05 on base0D | adjusted |
|---|---|---|---|---|---|---|---|---|---|
| light full (today) | `#f8f9fb` | 16.3-16.4 | 5.7 | 4.2-4.3 | 4.6-9.0 | 6/6 | 9.2-9.5 | 3.1 | 0 |
| light soft, cream | `#f1e7d7` | 9.4 | 4.5 | 3.1 | 4.7-8.1 | 6/6 | 7.5-8.2 | 1.8 | 1 (`base04`) |
| light soft, neutral | `#e6e8e9` | 9.4-9.5 | 4.5-4.6 | 3.1 | 4.7-8.1 | 6/6 | 7.5-8.0 | 1.8 | 0 |
| dark full (today) | `#0e1113` | 16.6-16.7 | 7.4-7.5 | 4.2 | 4.8-14.7 | 6/6 | 8.9-11.0 | 3.2 | 0 |
| dark dim | `#2a2d2e` | 9.6-9.8 | 5.0-5.1 | 3.7 | 4.7-11.2 | 6/6 | 8.4-10.4 | 1.8 | 0 |

Every toned variant passes every pair of "Contrast checks" (one `base04` move in soft cream,
a ramp tone to retune). Two costs show:

- **Blue as a background.** The dark ramp was set so that `base05` on `base0D` reaches 3:1
  (fast-syntax-highlighting's paired brackets, less's prompt) while `base0D` reaches 4.5:1 on
  `base01` ("Generators", named hues). Under dim there is no such blue: with `base01` at tone
  22 (luminance 0.035) blue needs luminance ≥ 0.33 for 4.5:1, and `base05` at tone 86
  (0.68) allows at most 0.19 for 3:1. It falls to 1.8:1. (Not a checked pair.)
- **Accents closer together in soft light.** Darker paper leaves a narrower lightness band
  between 4.5:1 and the text, so the six ANSI accents sit closer: distinct 7.5-8.2, against the
  8 under which two are hard to tell apart ("Accent metrics"; report only).

A second round compared proposals for each cost on 3qz176, every kitty window with
`LS_COLORS` from its own palette through the `vivid` template. Light: cream as above (L1),
accent chroma ×1.4 (L2), a lighter paper `#f9f0e1` at tones 95/92 (L3). Dark: dim as above
(D1); *muted* (D2: ramp 18, 22, 30, 52, 64, 83, 88, 92, accents 80 % of the way down to 4.7,
as everforest keeps its accents at 4.5-6.8:1 under its text's 7.4); D2 with blue kept as a
background (D3: blue at 3:1 under `base05`, so blue text falls to 3.0:1 on `base00`); and the
dimmest ramp that keeps a blue window at all (D4: `base00` tone 10, `#191c1d`, with `base05`
at tone 95; with a dimmer `base05` there is none). For reference, everforest's own six ANSI
accents score distinct 4.5, hues 5/6. MH chose L2 and D3. Over the 13 pictures:

| 13 pictures | base00 | fg/bg | accents on base01 | blue text on base00 / base01 | base05 on blue | hues | distinct | adjusted |
|---|---|---|---|---|---|---|---|---|
| soft (L2) | `#f1e7d7` | 9.4 | 4.7-8.1 | 5.2-5.3 / 4.8-4.9 | 1.8 | 6/6 | 8.5-9.2 | `base04` |
| dim (D3) | `#2a2d2e` | 8.9-9.0 | 6.0-7.9 (blue 2.6-2.7) | 3.0 / 2.6-2.7 | 3.0 | 6/6 | 6.2-7.5 | `base04`, `base0D` |

**Built (amo-k79.3, 2026-11-21)**, the same 13 palettes through `amo palette --check --tone`
(accents: `base08`-`base0E` and the brights on `base01`, blue apart). Every pair passes with no
adjustment; MH confirmed the `base04` retune on kitty windows of 3qz176:

| 13 pictures | base00 | fg/bg | base04/base01 | accents on base01 | blue text on base00 / base01 | base05 on blue | hues | distinct | adjusted |
|---|---|---|---|---|---|---|---|---|---|
| soft | `#f1e7d7` | 9.4 | 4.69 | 4.70-8.07 | 5.24-5.27 / 4.81-4.85 | 1.8 | 6/6 | 8.5-9.3 | none |
| dim | `#2a2d2e` | 8.9-9.0 | 4.57-4.63 | 5.08-7.97 | 2.94-2.99 / 2.61-2.65 | 3.0 | 6/6 | 6.1-7.4 | none |

**Fixed colours are not tone.** The first round's light windows had yellow and green file
names that were hard to read in every tone. They came from MH's `LS_COLORS`
(trapd00r/LS_COLORS, `*.md=38;5;184`, read by lsd as well), which names 256-colour cube
entries that no palette sets. With `LS_COLORS` from the palette (the `vivid` template) they
took the palette's colours. That is the terminal docs' fixed-colour rule and the kitty grey
ramp (amo-wtt, amo-7a0), not a tone.

### Tone: decisions

Agreed with MH, 2026-11-21:

1. **A tone per variant, made by amontillado** (no tool in "Tone: prior art" dims a picture's
   palette). Light: `full` (default) or `soft`. Dark: `full` (default) or `dim`. A toned
   variant is made at apply time from the palette's full variant, never stored in the palette
   file: the ramp `base00`-`base07` at the tone's Material tones, each accent keeping its hue
   and taking its lightness from a contrast target on the new `base01`, then derived and
   checked as any palette. *Initial* values, from the comparison:
   - `soft` (L2): cream paper, ramp tones 92, 89, 84, 55, 42, 24, 18, 12 at hue 80° and chroma
     0.024 on the backgrounds down to 0.006 on `base07` (the cream is part of `soft`, not a
     separate setting); accent chroma ×1.4, each accent's contrast on `base01` 40 % of the way
     from its full contrast down to 4.7.
   - `dim` (D3): the picture's neutral, ramp tones 18, 22, 30, 52, 64, 83, 88, 92; each accent
     80 % of the way down to 4.7 (muted, as everforest); blue (`base0D`) at 3:1 under `base05`
     (decision 4).
   - In the build, retune the ramp so that `base04` on `base01` passes without the adjustment
     both tones needed. **Built (amo-k79.1):** `base04` at tone 41 for soft (4.69:1 over the 13
     pictures) and 65 for dim (4.57-4.63:1), the smallest steps that pass. The ramp's hue and
     chroma for dim are the full variant's `base02`'s, so the transform needs only the palette
     file (any generator, or a preset). Each accent keeps its own hue and chroma (not the
     named hues'), so `hues: generator` palettes and presets tone the same way; `accent` and
     `secondary` are toned like the accents, the other roles derived. Under dim, bright blue
     `base16` is derived from blue before blue is fitted as a background, so it stays text.
2. **Set per variant, globally, per app and per run.** `theme.tone: {light: soft, dark: dim}`
   (each key optional, default `full`); `apps.<app>.tone` with the same shape, winning over
   the global one as `apps.<app>.variant` does; `--tone VARIANT=TONE` on `amo theme apply`
   (repeatable). **Built (amo-k79.4, .5):** resolved key by key, `apps.<app>.tone` then `--tone`
   then `theme.tone` then `full`, so `{light: full}` on an app leaves its dark to the others;
   `full` alone means both variants. `--tone` is per run, as `--variant`: an `--app` re-render
   tones from the config. Each app renders from a toned copy of the profile's (full,
   contrast-checked) palette, toned then checked with the tone's pairs; `palette.yaml` stays
   full. Under `variant: system` (or `auto`) each variant keeps its own tone. A
   template sees `{{scheme-tone}}` (`full`, `soft`, `dim`), a reload command `AMO_TONE`, and
   `theme.yaml` records each app's tone.
3. **Palettes from pictures take a tone; presets opt in; matugen cannot.** A palette from a
   picture is toned. A preset (or a palette from `--from-scheme`) is applied as it is, with
   one info line, unless its file sets `tone: transform` (built in amo-k79.6: the key's only
   value, kept in the profile's `palette.yaml`; the info line comes once per apply, only when a
   tone other than `full` was asked for): a scheme is a chosen look, and
   families such as gruvbox ship their own soft scheme (as amontillado never inverts a
   palette, decision 2 of the theme engine). No CLI flag. An app with `render_with: matugen`,
   whose colours are matugen's own (its `--contrast` does not dim the background, "Tone: prior
   art"), gets `full` with a warning from `amo config check` and `amo theme apply`;
   `apps.<app>.tone: full` silences it (built in amo-k79.7: a warning, never a failing problem;
   it names the variants asked for, from `theme.tone` and at apply time `--tone`, and apply
   warns only for a palette that takes a tone). Every other app, `libadwaita` and `libadwaita-vars`
   included, renders from the toned palette.
4. **The toned variant is checked with the same pairs and minimums, one exception.** Under
   `dim`, blue serves as a background instead of as text: `base05` on `base0D` at 3:1
   replaces `base0D` on `base00` and `base01` at 4.5:1 (blue text 3.0:1 and 2.6-2.7:1;
   bright blue `base16` keeps 4.5:1; built in amo-k79.2: the pair sits where blue's text
   pairs were, and adjusting it moves blue, never `base05`). MH chose this over 4.5:1 blue text (D2), seen side by
   side on tree, fd, bat and `git branch -vv` output, **to review after a week or two of use**
   (amo-yyu). `amo palette --check FILE --tone VARIANT=TONE` checks and reports the accent metrics per
   tone; distinct under `dim` (6.2-7.5) is below 8, accepted as the cost of muted accents
   (the metric is report only).
5. **Docs: the comparison table above now; swatches with the build.** The build adds a
   swatch sheet of one picture in all four (light full and soft, dark full and dim) to
   `docs/images/`, made by a `just` recipe from the code rather than by hand. **Built
   (amo-k79.8):** [tone-swatches.png](images/tone-swatches.png), by `just tone-sheet`
   (`tools/tone_sheet.py`, the panels as apply renders them), swatches and measured ratios
   only, never the picture; full colour, since a 256-colour PNG shifted the swatches. Users:
   [terminal-theming.md](terminal-theming.md), "Tone: soft and dim".

## Light variants and fixed colours (v0.10)

**Status: agreed with MH 2026-11-21 (amo-7a0)**, from kitty windows of 3qz176 side by side.
For users: [terminal-theming.md](terminal-theming.md).

A palette sets ANSI colours 0-15, which every terminal tool's 16-colour output follows. Tools
that name a 256-colour slot (`38;5;252`) or a truecolour value get xterm's fixed table, made for
a dark background: under a light variant they are unreadable (`bd show` draws notes in 252,
`#d0d0d0`, at 1.5:1 on 3qz176's `#f8f9fb`; trapd00r's `LS_COLORS` names `*.md` 184 at 1.5:1).

**Prior art.** kitty 0.47 has `palette_generate` (`fixed`, the default; `semantic`; `legacy`):
it fills every slot from 16 to 255 that the config leaves unset from colours 0-15, background
and foreground, by jake-stewart's algorithm
(<https://gist.github.com/jake-stewart/0a8ea46159a7da2c808e5be2177e1783>). `semantic` puts 232
near the background and 255 near the foreground, and maps the cube the same way: under light,
what a tool meant as "dim but readable on dark" stays readable. Tested on kitty 0.47.1
(2026-11-21): it keeps colours set explicitly (amo's 16-21), works from an included file, and
a SIGUSR1 reload switches it both ways. foot has `0`-`255` keys but no generator. So the plan in
the bead (amo computes a grey ramp 232-255 per variant) was dropped: it would duplicate kitty's
feature and cover the ramp only.

Measured on 3qz176 (slots below 4.5:1 on the background, from kitty's own colour table):

| | cube 22-231 | ramp 232-255 | 252 | 245 | 184 |
|---|---|---|---|---|---|
| light, `fixed` | 174/210 | 13/24 | 1.5 | 3.3 | 1.5 |
| light, `semantic` | 61/210 | 14/24 | 10.9 | 4.5 | 5.0 |
| dark, `fixed` | 47/210 | 12/24 | 12.3 | 5.5 | 12.3 |
| dark, `semantic` | 33/210 | 12/24 | 11.3 | 5.1 | 10.0 |

The cost of `semantic`: the cube's darkest steps (22-24, 52-54, ...) now sit near the
background, as 232-240 do, so a tool using them as dark-on-light text gets faint text.

Decisions:

1. **The built-in `kitty` template sets `palette_generate semantic` in both variants** (MH
   preferred dark semantic slightly, tinted toward the palette). kitty before 0.47 warns about
   the unknown key and ignores it.
2. **`kitty-fixed`** is the same template without it (`apps.kitty.template: kitty-fixed`): xterm's
   colours 22-255, or kitty before 0.47 without the warning. A test keeps the two files equal
   but for that line.
3. **A report, not a check.** `amo palette --check` prints, per variant, how many of xterm's
   fixed colours fall below 4.5:1 on `base00` and the ratio of 252 (`light: xterm's fixed
   colours below 4.5:1 on base00: cube 174/216, grey ramp 13/24 (252 at 1.5:1)`). It never
   fails, and `amo theme apply` does not warn: amo cannot see whether the terminal generates its
   palette, and the answer is the same for every light background.
4. **Not fixable by a theme:** truecolour output (Claude Code's diff context `#f8f8f2` at
   1.05:1 under light) needs the tool's own setting, e.g. an ANSI-only theme. A tool's 256-colour
   config (`LS_COLORS` with cube numbers) is better replaced by one built from the palette
   (`vivid`). Lightness-mapping the cube in amo (amo-yol) is left open: `semantic` does it in kitty.

## Saved looks (designed in v0.12)

**Status: agreed with MH 2026-11-22 (amo-0k6), the whole design in one release; built in v0.13.0
(amo-0k6.1-.7), the experimental parts awaiting their evaluation (amo-0k6.8).** User guide:
[saved-looks.md](saved-looks.md). Decisions are marked **MH** with their date. Ratings stay deferred
(MH 2026-11-21) until there is more use of `amo group`. `/project-review` (2026-11-22) recommended
shipping only the format, `save` and apply, and shelving history, usage, ids, `list` and `preview`
until a client existed. MH kept them: amontillado's role is exploratory support for MH's theming
work in the dotfiles, where a feature is evaluated live and then kept or removed, so these ship
marked experimental ("Saved looks: evaluation"). The review's defects are fixed below (history
numbering, the save warning, the index invariant, no palette dedupe) and its smaller alternative
added to the prior art.

A *look* is a set of pictures across monitors that the user liked, together with the theme they
saw: kept by name and applied again later. **MH (2026-11-21):** it holds the whole look,
pictures and theme (palette snapshot, variant, tone); pictures by record id; an optional
description; a YAML file in the library, versioned with it. **MH (2026-11-22):** the file lives
in the root of its most private picture; monitors by position (primary first) and aspect, not by
name; the palette embedded in the file, not a path to one.

This replaces the "sensible presets" that computed clusters would have given ("Grouping:
decisions" 2). The bead called them *saved sets*. The commands sit under `amo theme` (MH
2026-11-22: `amo theme save`, beside `apply`), not `amo set`, which reads as setting the
wallpaper ("Grouping: decisions" 3).

### Saved looks: prior art

Checked 2026-11-22: the dotfiles' own glue by reading it, the rest from their docs or wikis (not
run). The requirements, MH's (2026-11-21 and 11-22, set before this entry was written, as the
review noted): several monitors with their theme, kept by name; pictures by record id;
versioned with the library; the SFW roots never naming an NSFW record.

| Candidate | What it does | Fails |
|---|---|---|
| pywal: `wal -p NAME` saves the colours to `$XDG_CONFIG_HOME/wal/colorschemes`, `wal --theme NAME` applies, `wal -R` restores the last (pywal16 wiki) | named colour schemes; `-R` restores the last scheme and wallpaper | one wallpaper, by path, and only the last one: a named theme holds no pictures, no monitors and no tone. Its own pipeline (decision 11's reasons). |
| wpgtk (wiki, "Colorschemes") | a colour scheme stored per wallpaper | one wallpaper per scheme, pywal's pipeline, no monitors. |
| waypaper (`--restore`, `config.ini`) | restores the last wallpaper state | the last state only, no names, no theme; paths. hyprpaper, awww (`restore`) and wpaperd are the same: last state per output. |
| HyDE (Hyprland dotfiles framework; FAQ) | a theme is a directory of colours plus its own `wallpapers/` | the pictures are copied into the theme (not library records), one theme engine of its own, and the whole framework replaces the user's dotfiles. |
| KDE Plasma global themes (look-and-feel packages) | colours, wallpaper and more, by name | Plasma only; MH runs Hyprland. |
| **No build in amo:** a dotfiles script saving `~/.local/state/wallpaper/group.json` and the profile's `palette.yaml` under a name, restoring with `hyprctl` and `amo theme apply --palette` (the `wallpaper` script's `restore` does half of this today) | the whole look, on MH's machine | three of MH's decisions: group.json holds paths and names, which renames and crops break (ids need amo to resolve); "versioned with the library" means writing into a root, through amo's `on_change` hook, from outside amo; and putting a look in the root of its most private picture needs each record's purity, which only amo knows. Re-fitting a look to other monitors also needs amo's aspect matching and crop offer, which `amo group` has but cannot be given companions. |
| **A smaller change in amo** (from `/project-review`): record ids in `amo group --format json` (it prints a name today) and a way to pin companions (`--pin MONITOR=RECORD`); the dotfiles keep group files and presets under a name | most of the look, in about 30 lines of dotfiles glue, without the `look` block, placement or state | MH's requirement that looks are versioned with the library (they would live in the dotfiles' state), and the NSFW placement needs purity, which the glue would query from amo per save. |
| Variety (wallpaper changer; from its docs as recalled, not run) | a history of wallpapers to step back through, favourites | one wallpaper at a time, no theme, its own downloader and library. The history idea is taken (below). |

No candidate keeps named multi-monitor sets of library pictures with their theme, so amontillado
builds it. The build stays small by reusing what `amo group --apply` and `amo theme apply`
already do; amo still detects no monitors and sets no wallpaper itself (the setter hook).

### Saved looks: design

**One format: a look is a palette file with pictures** (MH 2026-11-22). A palette file
("Palette") gains an optional `look` block; a palette without one is a preset, as today. So
`amo theme apply --palette NAME` applies both, and a look whose pictures are gone is still a
palette.

```yaml
version: 1
id: 5e0c1a7b...                 # uuid4, written once by amo; usage keys off it ("Identity")
name: blade-and-iss
source: {picture: c2bb9ad4..., ...}   # as generated; see "Where it lives" for presets
variants: {dark: {...}, light: {...}}  # the profile's palette.yaml, whole
look:
  description: Stellar Blade signs with the ISS morning   # optional
  saved: 2026-11-22T12:00:00+00:00
  variant: system               # as the last apply asked (run level)
  tone: {light: soft, dark: full}
  monitors:                     # by position: the first is the primary
    - record: c2bb9ad4...       # the record's id: survives renames and moves
      file: stellar-blade-playstation-signs-xed63v-21x9.jpg   # the file shown
      aspect: "21:9"            # the monitor's ratio when saved
    - record: 627f7597...
      file: commons-good-morning-iss.jpg
      aspect: "16:9"
```

- **The palette** is the profile's `palette.yaml` (full, contrast-checked; `tone: transform`
  kept for a preset), embedded (MH), so a look applies the same colours after a generator
  upgrade, a hues recalibration, or when the theme came from a preset.
- **Pictures by id and file.** The file name pins what was on screen (an edit or a hand-made
  derived file has the same ratio as the original, so the aspect alone could pick another
  file). If that file is gone, the monitor's aspect picks one as `--aspect` does, with a
  warning. Monitors by position and aspect, not name (MH): names are machine-specific.
- **The profile's `palette.yaml`** keeps an applied file's `id` but not its `look`: the pictures
  set are the index's state (`current_group`, `history`).
- **Variant and tone** are the run's (`--variant`, `--tone`, else the config's), stored (MH);
  `apply --variant` and `--tone` override them. `theme.yaml` records each app's resolved
  values today, so it gains the run's `variant` and `tone` at the top level. Per-app settings
  stay config.

**Where it lives.**

- **With pictures:** `<root>/.amo/palettes/<name>.yaml` in the root of its most private
  picture (MH): the NSFW root if any of its records is not sfw, else the primary's root. The SFW
  roots never name an NSFW record. Under `.amo/`, which `amo index` never searches and the
  version-control layout keeps in git, not the annex. One file per look: two machines saving
  different looks never touch the same file, and a look is deleted by deleting its file.
- **Without pictures** (`--palette-only`, or no pictures known): a preset in
  `$XDG_CONFIG_HOME/amontillado/palettes/`, as today. From a non-sfw picture its `source` is
  left out (with an info line): it names the picture's file and record, and the config dir is
  often a public dotfiles repository (MH 2026-11-22).
- **Lookup** (`--palette NAME`): the library roots' `.amo/palettes/` (the NSFW root's too: an
  explicit name, as for a picture), then the config's `palettes/`. **The library wins** a name
  found in both, with a warning naming both paths (MH 2026-11-22): a preset copied into the
  config, edited and saved again into the library takes over its name. Every apply prints the
  resolved path; a path instead of NAME picks one file exactly. Saving a name that shadows or is
  shadowed warns too. A name in two library roots is an error (it cannot be ordered).

**Identity** (MH 2026-11-22). Every palette file amo writes gets a top-level `id` (uuid4, 32
lowercase hex digits, as a record's), written once and never rewritten: `amo theme save`
(`--palette-only` too) and `amo palette --from-scheme`. Statistics and history key off it, never
off the name, so shadowing only decides which file a name resolves to. A hand-written preset
without an `id` (amo does not edit the user's config files) is keyed by its resolved path
instead: moving it loses its statistics, and `amo config check` says so, suggesting an `id`
line. A palette made from a picture at apply time is not a saved theme: its use is the
picture's, counted as shown. A hand-changed `id` orphans its statistics, as for records
(amo-n0o).

**Current group, history and usage** (state, `index.sqlite`, kept across rebuilds as `usage`
is):

- **`current_group`** (one row): the last `amo group --apply`: each monitor's name, ratio,
  record and file. It is what `amo theme save` saves, and the monitors `apply` uses when no
  `--monitor` is given. It replaces the dotfiles keeping `amo group`'s output themselves.
- **`history`**: one row per activated `amo theme apply` (not `--dry-run` or `--no-activate`):
  time, the theme's id (or path) when a saved theme was applied, the palette applied, the run's
  variant and tone, and the current group's monitors if its primary is the picture applied
  (the same record: the group may show another file of it; else just that picture). Each row has a number, increasing and never reused, which `list
  --history` prints and `--history N` takes, so a row keeps its number whatever `--purity`
  hides. The palette is stored whole in each row (about 2.3 KB; 200 rows under 0.5 MB).
  `theme.history_size` (default 200,
  *initial*; 0 keeps none, as zsh's `HISTSIZE`) bounds it, oldest dropped. A group applied
  without a theme apply (a monitor change regrouping companions) changes `current_group` only.
- **`theme_usage`**: per saved theme (id, or path for one without), `applied_count` and
  `last_applied`, as `usage` is per record (MH 2026-11-22). Never trimmed with history, so
  counts survive `history_size`.
- **Privacy:** a history row naming a non-sfw record is listed only with `--purity`, as `amo
  list` does: a history picker is what would otherwise put one on screen during a screen share.

**Commands:**

```text
amo theme save NAME [--palette-only] [--description TEXT] [--profile P] [--force] [--dry-run]
amo theme apply --palette NAME|FILE [--monitor NAME=W:H]... [--palette-only] [...as today]
amo theme apply --history N [--monitor NAME=W:H]... [--palette-only] [...]
amo theme list [--history] [--purity LIST] [--order name|recent|most-applied|least-applied]
               [--limit N] [--format tsv|json|rofi]
amo theme preview [PICTURE | --palette NAME|FILE | --history N] [--monitor NAME=W:H]...
                  [--variant V] [--tone VARIANT=TONE]... [--palette-only] [-o FILE]
```

- **`save`** writes the profile's palette (default `theme.profile`) with the current group's
  pictures when that group's primary is the profile's wallpaper; otherwise, or with
  `--palette-only`, a preset. No prompt. It prints the path written; saving a preset without
  `--palette-only` warns that the pictures were left out and why (no group applied, or the
  group's primary is not the profile's wallpaper). A name that exists where it
  would write is refused without `--force`. A write under a root goes to `on_change` as a
  `file` change. Settled in the build (amo-0k6.3): `--force` keeps the replaced file's `id` (written
  once); a name saved in another library root is refused, `--force` or not (lookup could not
  order the two); `--description` for a preset warns and is left out (no `look` to hold it);
  a preset's `source` is left out when its picture's purity is unknown too; the look's
  variant and tone are `theme.yaml`'s (the config's for a profile applied before it kept
  them); `--dry-run` prints the file and logs where it would go.
- **`apply` of a look** sets the pictures as well as the palette, by default, interactive or not
  (MH): the monitors from `--monitor`, else from `current_group`; position *i* gets entry *i*,
  its saved file if the ratio matches, else the record's file for the monitor's ratio, with
  `amo group`'s crop offer and fallback. Then as `amo group --apply`: `group.setter` per monitor
  (none configured: a warning, the palette applied alone), each picture recorded as shown, and
  the profile's wallpaper link on the primary's file. A record that no longer exists, or absent
  content, fails the apply naming it; `--palette-only` applies the palette alone. Fewer
  monitors than the look has: the rest left out, with a warning. **More monitors**: a warning
  and an offer to fill them with companions of the look's primary, as `amo group` picks them
  (MH 2026-11-22); without a terminal they are filled. A preset (no `look`) applies as today.
  Settled in the build (amo-0k6.4; MH confirmed them 2026-11-23, with the record match, the
  profile's `id` and `current_group` written only when every setter succeeds): the setter runs
  after the reloads, so a wallpaper hook that sets every monitor does not undo the look;
  companions are of the purities the look's own pictures have (an all-sfw look takes SFW ones
  only, never from the NSFW root; MH 2026-11-23, changed from SFW only), by
  `group.max_distance` and `group.order`, never one of the look's own pictures; no monitor
  known (no `--monitor`, no `current_group`) applies the palette alone with a warning;
  `--no-activate` sets no pictures (nothing is on screen); `--app` with a look is refused (its
  pictures re-render every app) unless `--palette-only`.
- **`--history N`** applies history row number N as a look (its palette, variant, tone and
  pictures). The newest row is the last theme applied, not necessarily what is on screen: a
  regroup without a theme apply, or a setter run outside amo, changes the pictures without a
  row.
- **`list`** (MH 2026-11-22: one list for a picker of every theme) prints the saved looks and
  presets with their paths (shadowed ones marked), from the SFW roots and the config; with
  `--purity` asking for sketchy or nsfw, the NSFW root's looks too. `--history` lists the
  history rows instead, with their numbers, newest first; rows naming a non-sfw record
  only with `--purity`. `--order` (named as `amo list --order`): `name` (default for saved
  themes), `recent` (default for history), `most-applied`, `least-applied` from
  `theme_usage`; json carries the counts. `rofi` rows carry each theme's preview (below).
  Settled in the build (amo-0k6.6): tsv is `NAME<TAB>KIND<TAB>PATH` (`look`, `preset`, or
  `shadowed` for a preset a library file of its name hides, in any root, as lookup sees it),
  history `NUMBER<TAB>APPLIED<TAB>PALETTE<TAB>PRIMARY FILE`; a rofi row returns the path (a
  history row its number), its icon the cached preview card, a look whose pictures are gone
  drawn as its palette alone; `recent` for saved themes is last applied first, never applied
  after; a history row naming a record no longer indexed is listed only with `--purity` (its
  purity is unknown); without an index the saved themes still list, without counts.
  `apply --history N` (amo-0k6.6): a row without pictures applies its palette alone, with
  the row's variant and tone; the row's saved theme is counted again.
- **`preview`** (MH 2026-11-22: for a look at a theme before applying it, and for docs images)
  draws the preview of a saved theme, a history row, or PICTURE (the palette it would give,
  beside that picture alone; previewing a whole `amo group` set first is left open). Without
  `-o` it is shown as `amo crop --interactive` shows its box: the kitty graphics protocol, else
  `crop.viewer` (`crop.preview` decides); `-o FILE` writes a PNG. The picker's rows and this
  command use the same function.
- **Not built:** remove and rename (the file is the look), `amo group --save` (a look is saved
  after it has been seen), ratings (deferred, MH 2026-11-21).

**The preview** (MH 2026-11-22: one format for every theme):

- **With pictures:** each monitor's thumbnail side by side in monitor order, the primary first,
  each at its aspect and a common height (*initial* 160 px), so a 21:9 beside a 16:9 looks like
  the desk; under them a swatch strip.
- **Without pictures** (a preset, or `--palette-only`): the same card, the strip enlarged to
  fill it, so presets and looks line up in one picker.
- **The strip:** `base00`-`base07` then `base08`-`base0F`, one row per variant the theme would
  apply (dark over light under `system` or `auto`; one for a fixed variant or a one-variant
  preset), in the colours after tone: what the screen would show.
- **Cache:** keyed by the hash of what the preview shows. SFW previews in
  `$XDG_CACHE_HOME/amontillado/previews/`; one showing a non-sfw picture in
  `$XDG_RUNTIME_DIR/amontillado/previews/` (tmpfs: never backed up, gone at logout), since it
  copies the picture's pixels out of the NSFW root.
- **Settled in the build (amo-0k6.5):** each thumbnail is the file cropped about its centre to
  the monitor's ratio; strip rows are 24 px (*initial*); a preset's card is one 16:9 thumbnail
  wide, its strip rows sharing the card's height; the cache key hashes each file's path, size
  and modification time with the ratios and the strip's colours (not the pixels: hashing every
  picture on each draw is slow); without `XDG_RUNTIME_DIR` a non-sfw card is refused (`-o`
  still writes one); a history row's single picture shows at its own ratio; in kitty the card
  is printed inline (no image id, so a later one does not replace it), at most the terminal's
  width and half its height.

### Saved looks: evaluation

The core (the `look` block, `save`, apply of a look, `current_group`) is the feature. History,
`theme_usage` and `--order`, `list`, `preview` and the rofi format ship **experimental**:
named so in `--help`, the CHANGELOG and the user docs, and free to change or go in a minor
release. After MH has used them in the dotfiles for a week or two, each is kept (the label
dropped) or removed, and the decision recorded here.

### Saved looks: build beads

Under amo-0k6; one release (MH 2026-11-22). 1-7 done, in v0.13.0; 8 open.

1. **State:** `current_group`, `history` (numbered rows, `theme.history_size`) and
   `theme_usage` (index schema 10; kept across rebuilds), written by `amo group --apply` and
   `amo theme apply`; the run's `variant` and `tone` in `theme.yaml`.
2. **Format, identity and lookup:** the `id` and `look` keys (validation, round trip; ids
   written by `--from-scheme`), lookup over the library roots and the config with the library
   first, the shadowing warning, the resolved path printed, `amo config check`'s hint for a
   preset without an id.
3. **`amo theme save`:** placement by purity, `--palette-only`, `source` left out for a non-sfw
   preset, `--force`, `on_change`. Needs 1, 2.
4. **`amo theme apply` of a look:** monitors from `--monitor` or state, fitting by position and
   aspect, the setter, shown, `--palette-only`, failures, extra monitors filled. Needs 1, 2.
5. **`amo theme preview`:** the preview card, its cache (runtime dir for non-sfw), kitty or
   viewer display, `-o`. Needs 2. Clients: MH at the terminal, docs images.
6. **`amo theme list` and `--history N`:** saved themes and history, purity-filtered,
   `--order` from `theme_usage`, the rofi format with previews. Needs 4, 5. Client: the
   dotfiles' theme picker (ticket filed 2026-11-22).
7. **Docs and release:** this section's status, a user doc section with a preview image made
   by `amo theme preview`, the config template's comments (`theme.history_size`), the
   experimental labels. Needs 3-6.
8. **Evaluation** (after the release, MH's use): keep or remove each experimental part.

## Testing

- No network in tests: the HTTP layer is one small function, replaced by a stub that serves
  recorded API responses (`tests/fixtures/`, trimmed to the fields used) and generated images.
- Images are generated in the tests (solid colours, gradients, noise), never committed.
- Metric tests use images whose answer is known: black is dark, a solid red is saturated,
  monochrome and red, grey noise is busy and muted, a smooth gradient is sparse.
- The nvim examples run in an embedded nvim (`tests/test_nvim.py`, marker `nvim`, pynvim):
  themes applied in-process, highlights read back, nvim's loop pumped with `vim.wait`.
  Pre-installed plugins only; skipped without nvim or a plugin.

## Roadmap

1. v0.1 (released 2026-10-28): the CLI above, calibrated thresholds, tests, CI, a tagged
   release.
2. Palette-aware grouping (epic `amo-6f0`; released in v0.7, 2026-11-18; designed in v0.6,
   "Grouping (v0.7)"): a stored palette per file, `amo list --like`, and `amo group`, a
   coherent set for several monitors, the theme taken from the primary monitor's picture.
   Later: saved sets and ratings (amo-0k6), style measures (amo-abc).
3. v0.2, the theme engine (epic `amo-aqp`; released 2026-11-03): palette files, generator
   adapters, per-app templates. Direction agreed in principle (2026-10-29): amontillado renders templates itself
   from optional sources (built-in variables-only templates, tinted-theming, matugen-themes,
   pywal), without running tinty: [research/tinted-theming.md](research/tinted-theming.md).
   Design agreed 2026-10-30: "Theme engine (v0.2)".
   Also for v0.2, **a commented config template** (built, amo-aqp.18): `amo config init`,
   `amo config check` ("Per-app configuration").
4. v0.3 (epic `amo-e0d`; released 2026-11-05): the `libadwaita` template, the `{variant}`
   reload placeholder for a colour-scheme hook, `amo name`, `amo add-derived`.
5. v0.4 (epic `amo-j24`; released 2026-11-13): `libadwaita-vars` (amo-j24.2), `amo edit`
   (amo-2mf), config commands under `sh -c` with AMO_* variables (amo-j24.3), ruamel.yaml
   with info files updated in place (amo-j24.4), and the git-annex libraries below.
6. git-annex libraries (epic `amo-qnn`, released in v0.4: absent content, `amo info
   diff`/`merge`, the `on_change` hook and `amo hook git-commit`, docs/version-control.md):
   each root a git-annex repository, info files in git,
   images annexed (SHA-256 keys, the same hash as each file's `sha256`); the index stays outside, in
   `$XDG_STATE_HOME`. The NSFW library is encrypted off-machine with git-remote-gcrypt and an
   encrypted annex remote, not git-crypt (spike amo-qnn.1, 2026-11-07: "git-annex libraries:
   decisions").
   **This brings the first non-Python dependencies** (git, and for an annexed or encrypted
   library git-annex, written in Haskell, git-remote-gcrypt and gnupg). They stay optional:
   amo never runs them itself, only the opt-in `on_change` hook does (`amo hook git-commit`
   runs git and git-annex; gcrypt and gnupg only through git's remotes), and `pipx install`
   keeps working without them ("git-annex libraries: decisions", 5).
7. v0.5 (released 2026-11-13): the `system` variant, following the desktop's colour scheme
   (amo-8zi, from chezmoi D78's clock-driven variant; "Variant").
8. v0.6 (epic `amo-50c`; released 2026-11-13): `amo list --order least-shown` (amo-50c.2), the
   stale-index warning (amo-50c.3), the light variant's darker bright colours (amo-50c.4), and
   the grouping spike (amo-50c.1) that designs item 2 for v0.7.
9. v0.8 (epic `amo-soq`; released 2026-11-19): `amo group --predicate` (amo-6x6) and letterbox
   detection with a crop offer (amo-5o8).
10. v0.9 (epic `amo-301`, planned as v0.8.1; released 2026-11-20): the hyprpaper >= 0.8 reload
    example (amo-qu4), and Wallhaven tag categories kept for naming, with a backfill and `amo
    name --from-tags --force` (amo-ugu); a minor release because those add options.

## Open questions

- `HUE_SHARE_MIN`: kept at 0.40 when metrics version 2 raised `--hue` coverage from 68% to 80%
  of the calibration sample ("Calibration"). Raising it narrows `--hue` to images dominated by
  one hue: 0.45 leaves 77%, 0.50 73%, 0.55 67% (about the old coverage). Revisit if `--hue`
  results look too loose in use; it is a query-time threshold, so no metrics version is needed.
