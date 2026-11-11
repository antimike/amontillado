# Design

Status: v0.1 (2026-10-28): the library, index, query commands and the fetcher, test sets
included, class thresholds calibrated. v0.2 (2026-11-03): the theme engine as agreed
(2026-10-30, "Theme engine (v0.2)"), built: palettes from pictures (matugen and wallust, named
hues calibrated), presets and tinted-theming schemes, contrast checks, the mustache, pywal and
matugen formats, the registry and `amo theme sync`, apply with profile swaps; also interactive
crops, `amo list` search over the index, and the commented config template. v0.3
(2026-11-05): the built-in libadwaita template and the `{variant}` reload placeholder for a
colour-scheme hook ([colour-scheme-hooks.md](colour-scheme-hooks.md)), `amo name` (also
`--from-tags`) and `amo add-derived`. Towards v0.4 (on main, unreleased, 2026-11-06): the
GTK4-only `libadwaita-vars` template ("Template sources") with GNOME's palette remapped
(`gnome-*-hex`, "Formats and views"), and a live test that takes any scheme or library picture
and captures without keyboard focus, optionally off screen; `amo edit` with named editor tools
("Editing", 2026-11-07); every config command under `sh -c` with `AMO_*` variables
instead of `{placeholder}`s ("Config", 2026-11-08).
Values marked *initial* are starting points to calibrate on real images; change them here when
they change in code.

## Scope

**v0.1, the library:** measure images, keep records, build the index, query it, fetch from
Wallhaven with filters, and build test sets. No GUI, no wallpaper setter, no timer: those belong
to the user's desktop configuration and call `amo list`.

**v0.2, the theme engine:** palettes from pictures, presets or tinted-theming schemes,
contrast checks, and per-app templates rendered into a per-profile cache, with reload commands.

**Later (see "Roadmap"):** palette-aware grouping and selection across monitors.

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
      version: 2                    # bump when a metric's definition changes: forces recomputation
      lightness: 0.31
      chroma: 0.042
      colourful_share: 0.38
      hue: 262.0
      hue_name: blue
      hue_share: 0.71
      hue_spread: 0.18
      warmth: 0.12
      busy: 0.06
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
  table. The database's `PRAGMA user_version` is its schema version (7); a newer one than the
  program knows is refused. Schema 2 lacked the hash-cache columns, schemas 2 and 3 the
  thumbnail column, schemas 2 to 4 the `license`, `author` and `title` columns of `records`,
  schemas 2 to 5 its `info` column (the whole info file as JSON, for `amo list --where`),
  schemas 2 to 6 the `absent` column of `files`; upgrading adds them empty, for the next `amo index` to fill. The `pictures` view (columns
  under "CLI") is recreated on every open, so changing it needs no migration.
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
`theme.apps.<app>.reload` get `AMO_WALLPAPER`, `AMO_PROFILE`, `AMO_DIR` and `AMO_VARIANT`;
`crop.viewer` gets `AMO_FILE`; `amo edit`'s tools get `AMO_INPUT`, `AMO_OUTPUT` and
`AMO_WORKDIR`; `api_key_command` gets none. So pipelines and fallbacks need no wrapper script,
and quoting is the user's job (`"$AMO_WALLPAPER"`). The prefix keeps generic names such as
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

Values are rounded when written: `hue` to 0.1°, the others to 3 decimals.

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
"CLI"). Those tags are names only, without Wallhaven's tag categories, so the category rule
cannot apply there: an artist's or a technique's tag may make it into the name;
`NAME_SKIP_TAGS` still applies, and the wallpaper's category stands in when no tag is usable.
Planned instead (amo-ugu): `amo fetch` keeps each tag's category in `source.tag_categories`,
and a one-off pass re-asks Wallhaven (`/w/<id>`) for those of records fetched before, so
naming itself never needs the network.

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
amo list [FILTERS] [--aspect W:H] [--purity LIST] [--random N] [--format path|rofi]
         [--non-interactive] [--tag T]... [--site S] [--category C] [--license L] [--author A]
         [--where SQL]
                                     matching paths, one per line
amo fetch [FILTERS | --test-set] [WALLHAVEN] [--count N] [--max-candidates N]
          [--busy-from thumb|full] [--discard-mismatches] [--dry-run]
amo shown PICTURE... [--dry-run]     record that pictures were shown (for the usage table)
amo add FILE... [--name N] [--nsfw] [--force] [--dry-run] [PROVENANCE]   make each file a record
amo add --from-json FILE [--force] [--dry-run]              the pictures a JSON file lists
amo crop PICTURE W:H [--at F] [--interactive] [--force] [--dry-run]   crop a record's original; prints it
amo add-derived PICTURE FILE [--name N] [--from FILE] [--dry-run]   add a hand-made derived file
amo edit PICTURE [--tool NAME | --extcmd CMD] [--name N] [--from FILE] [--dry-run]
                                     edit a copy in an editor, add the result; prints it
amo edit --list-tools                the editors under edit.tools
amo name PICTURE NAME [--no-rename-directory] [--dry-run]      name or rename a record
amo name --from-tags [PICTURE...] [--no-rename-directory] [--dry-run]   name fetched records from their tags
amo info diff OLD NEW [--json]       the key paths that differ between two info files
amo info merge BASE OURS THEIRS [--name PATH] [--stdout]   three-way merge (a git merge driver)
amo hook git-commit                  as on_change: commit amo's changes to the root's git repository
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

`--format rofi` follows each path with its record's thumbnail as the icon
(`PATH\0icon\x1fTHUMBNAIL`, for `rofi -dmenu -show-icons`); a record without one, or whose
thumbnail is gone, prints its path alone.

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
one without a name; it never renames a named record. Naming is never `amo index`'s job, since a
name is authored, not derived. Refused (per record; the others are still named): an invalid
name, the record's own, a name already taken (as `amo add` does), a record that needs `amo
index` first, an existing directory for the name, and under `--from-tags` a named record or one
not fetched from Wallhaven. It writes the name, then renames the directory (restoring info.yaml
if that fails), and updates the index and any theme profile's wallpaper link into the
directory, so neither needs a re-run. Prints each record's directory; `--dry-run` logs the
names instead.

FILTERS are the class flags above, and `--hue`. WALLHAVEN: `--tags QUERY` (Wallhaven's `q`),
`--purity LIST` (default sfw), `--category LIST` (general, anime, people; default all),
`--atleast WxH`, `--ratio LIST` (`W:H` or `WxH`), `--color HEX`. Wallhaven's `colors`
parameter takes only its 29 fixed swatches (`SWATCHES` in `wallhaven.py`), which have no names;
any other colour is replaced by the nearest swatch by OKLab distance, with a log line. `amo fetch` prints the path of each file kept, one per line,
and exits non-zero if it kept fewer than `--count` (`--test-set` prints and fails as under
"Test set"). `--dry-run` measures thumbnails, downloads
nothing, and prints the page URL of each wallpaper it would keep.

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
light variant), `base12`-`base17` are `base08`, `base0A`, `base0B`, `base0C`, `base0D`, `base0E` with
L +0.08 (*initial*), clipped to the sRGB gamut by lowering chroma.

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

**Variant** chooses which of the palette's variants is applied: `auto`, `dark` or `light`. It is
set globally (`theme.variant`, default `auto`), per run (`--variant`), and per app
(`apps.<app>.variant`, which wins over both). `auto` is light when the picture's `lightness`
metric is above the `--light` threshold (0.65), dark otherwise; for a palette without a picture,
its dark variant if it has one. A variant the palette lacks (a one-variant preset) is a warning,
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
never adjusts. (A first run on gruvbox,
2026-10-30: dark needed five moves, light twelve, mostly its accents on `base01`; the light
variant's brightened `base12`-`base17` come back down to about their base colours, so a light
variant's bright step may want to be darker instead: to calibrate.)

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
  terminal; its 5-6 adjusted colours are all the bright `base12`-`base17` (L +0.08 from their
  base colour), so the bright step for a light variant may want to be darker (open, under
  "Contrast checks").
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
rofi and rofi-colors (base16-rofi), dunst, waybar (variables), shell (tinted-shell, base24);
`matugen-themes`: kitty, gtk, css, rofi, dunst, sway, swaybar, hyprland (Lua), hyprland-conf,
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
file), `gtk` (`@define-color` for every key: imported by waybar, swaync and wlogout styles, and by
GTK3 `gtk.css` and libadwaita's `gtk-4.0/gtk.css`), `rofi` (a `* { ... }` block of variables),
`hyprland` (a Lua table, D62), `hyprlock` (hyprlang `$variables`), `sway` (`set $variable`),
`dunst` (a `dunstrc.d` drop-in with the urgency colours: dunst has no variables, so this one is a
small complete theme), `libadwaita` and `libadwaita-vars` (below), `nvim` (`palette.lua`),
`shell` (`export
AMO_BASE00=...`), and `json` (the palette as JSON, for anything else). `amo theme templates`
lists them with their variables.

`libadwaita` (amo-aqp.21) is complete like `dunst`, since libadwaita's colour names are a fixed
API: it defines libadwaita's named colours (checked against libadwaita 1.9.1's own stylesheet)
from the roles and ramp, so one file serves as `gtk-4.0/gtk.css` and, under adw-gtk3,
`gtk-3.0/gtk.css`. `accent_bg_color`/`accent_fg_color` are `accent`/`on_accent`; destructive and
error are `error`, success `success`, warning `warning`, each on `base00` (a contrast pair when
the role is derived from `base08`, `base0B`, `base0A`); window and the secondary sidebar are
`base00`, view `base10` (darker than the window in dark, lighter in light, as in Adwaita);
headerbar, sidebar, card, dialog, popover and thumbnail `base01`; every foreground `base05`;
borders `base02`; shadows black at Adwaita's strengths per variant. Only `@define-color`: GTK3
fails on a `:root` block of CSS variables, and libadwaita 1.9 still reads its variables from
these names (`--accent-bg-color: @accent_bg_color`). Not the standalone `accent_color`,
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
Variables keep the palette's names (`base0A`, `on_accent`) except in rofi, whose parser rejects
`_` (rofi 2.0): there roles are hyphenated (`on-accent`). The hyprland and hyprlock colours are
`rrggbb` without `#`, so a config can add alpha (`"rgba(" .. c.accent .. "ee)"`, `rgb($accent)`);
the others are `#rrggbb`. kitty's file sets `color0`-`color21` (the ANSI table under "Formats and
views", then base16-shell's extras `base09`, `base0F`, `base01`, `base02`, `base04`, `base06`),
the tab, border, selection and URL colours. Headers name the palette by its slug, never its
name, so no quote in a name can break a Lua, shell or JSON file. Default output files: `kitty.conf`,
`colors.css`, `colors.rasi`, `hyprland.lua`, `hyprlock.conf`, `sway`, `dunst.conf`,
`libadwaita.css`, `libadwaita-vars.css`, `palette.lua`, `colors.sh`, `palette.json`.

### Formats and views

Each format gets a *view* of the palette: the variables its templates expect.

- **mustache** (tinted-theming's builder spec, rendered with `pystache`, MIT): for every base24 key
  *and every role* the spec's variables (`accent-hex`, `accent-hex-r`, `accent-rgb-r`,
  `accent-rgb16-r`, `accent-dec-r`, `accent-hex-bgr`, ...), and `scheme-name`, `scheme-slug`,
  `scheme-slug-underscored`, `scheme-system` (`base24`), `scheme-variant`,
  `scheme-is-dark-variant` / `scheme-is-light-variant`; also `scheme-author` (the scheme's, or
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
  wallpaper: {reload: 'hyprctl hyprpaper reload ,"$AMO_WALLPAPER"'}
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

## git-annex libraries (v0.4)

Each library root may be a git-annex repository: info files in git, images annexed (epic
`amo-qnn`; "Roadmap", item 6). Repository and remote setup is git configuration owned by the
dotfiles, not amontillado config; the layout, locked and unlocked files, the merge driver, the
hook payload and a short encrypted setup are in [version-control.md](version-control.md)
(amo-qnn.5), the full key and restore runbook in the dotfiles.

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
     cipher only, not the images). A key never added cannot decrypt (tested).
   - **Removing a machine does not revoke what it holds**: `keyid-=` and dropping it from the
     participants stop it reading what comes later, but it knows the special remote's cipher
     and has every pack it fetched. Real revocation is a new remote and a new upload.
   - `gcrypt-publish-participants` (git-annex turns it on) stores the recipients' key ids in the
     remote: it hides no content but shows whose keys open it; off, gpg tries every secret key.
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
   - Encrypted remotes (gcrypt) are documentation only; the full key and restore runbook lives
     in the dotfiles.

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
2. Palette-aware grouping: features per image, clusters of compatible images, a coherent set
   for several monitors, the palette taken from the primary monitor's image.
3. v0.2, the theme engine (epic `amo-aqp`; released 2026-11-03): palette files, generator
   adapters, per-app templates. Direction agreed in principle (2026-10-29): amontillado renders templates itself
   from optional sources (built-in variables-only templates, tinted-theming, matugen-themes,
   pywal), without running tinty: [research/tinted-theming.md](research/tinted-theming.md).
   Design agreed 2026-10-30: "Theme engine (v0.2)".
   Also for v0.2, **a commented config template** (built, amo-aqp.18): `amo config init`,
   `amo config check` ("Per-app configuration").
4. v0.3 (epic `amo-e0d`; released 2026-11-05): the `libadwaita` template, the `{variant}`
   reload placeholder for a colour-scheme hook, `amo name`, `amo add-derived`.
5. v0.4 (epic `amo-j24`): `libadwaita-vars` (built 2026-11-06, amo-j24.2), `amo edit`
   (built 2026-11-07, amo-2mf), and the git-annex libraries below.
6. git-annex libraries (epic `amo-qnn`, part of v0.4): each root a git-annex repository, info files in git,
   images annexed (SHA-256 keys, the same hash as each file's `sha256`); the index stays outside, in
   `$XDG_STATE_HOME`. The NSFW library is encrypted off-machine with git-remote-gcrypt and an
   encrypted annex remote, not git-crypt (spike amo-qnn.1, 2026-11-07: "git-annex libraries:
   decisions").
   **This brings the first non-Python dependencies** (git-annex, written in Haskell;
   git-remote-gcrypt and gnupg). They stay optional: amo never runs them itself, only the
   opt-in `on_change` hook does ("git-annex libraries: decisions", 5), and `pipx install`
   keeps working without them.

## Open questions

- `HUE_SHARE_MIN`: kept at 0.40 when metrics version 2 raised `--hue` coverage from 68% to 80%
  of the calibration sample ("Calibration"). Raising it narrows `--hue` to images dominated by
  one hue: 0.45 leaves 77%, 0.50 73%, 0.55 67% (about the old coverage). Revisit if `--hue`
  results look too loose in use; it is a query-time threshold, so no metrics version is needed.
- Whether `amo list` should prefer images shown least recently (it has the usage table).
- Index staleness: `amo list` trusts the index; whether it should detect changes since the last
  `amo index` (a stat walk of the roots) and warn or refresh.
