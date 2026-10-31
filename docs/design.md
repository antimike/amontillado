# Design

Status: agreed for v0.1 (2026-10-27); the library, index, query commands and the fetcher are
implemented, test sets included; class thresholds calibrated (2026-10-28). v0.2's theme engine is
agreed (2026-10-30) and being built: the palette model and `amo palette --from-scheme` are
implemented, with contrast checks and the `theme:` config block; "Theme engine (v0.2)". Values marked
*initial* are starting points to calibrate on real images; change them here when they change in code.

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
it creates after the record's `name`, the file's stem, or (later) the Wallhaven id. Images are
`.jpg`, `.jpeg`, `.png` and `.webp` files. `info.yaml` holds only facts that do not change
about the picture; usage history lives in the index, so records stay stable under sync tools.
It is written atomically (temporary file, then rename).

```yaml
schema: 2
id: 3f2a9c1e0b7d4e8f9a6b5c4d3e2f1a0b   # generated once (uuid4), never changes; usage keys off it
name: night-city                    # optional; unique in the library; [a-z0-9][a-z0-9._-]*
default_file: night-city.png        # optional; see below
source:                             # null for pictures added by hand
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
- `info.yaml` is loaded with a loader that rejects duplicate keys: `yaml.safe_load` silently
  keeps the last, which would drop a file listed twice.

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

**Healing** (`amo index`) splits the fields in two:

- **Derived** fields are recomputed whenever they are missing, invalid or out of date, without
  asking: `schema` and `id` when absent (a new record), and per file `sha256`, `width`,
  `height` and `metrics`. A file whose content hash changed is measured again.
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
measured and added. A listed file that is missing with no match keeps its entry (so does an
annexed file whose content is not present: a broken symlink), is reported, and fails
`--check`; the rest of the record is still indexed, and a missing `default_file` falls back to
the rule above with a warning. A file moved to another record is not re-paired: it is added
there, and reported missing from the first. A record directory renamed or moved needs no
healing at all: its identity is inside it.

**Duplicates.** Two records with the same `id` (a copied directory) are both reported and
neither is indexed; deleting the `id` line from one gives it a new id at the next
`amo index`. The same `sha256` in two files anywhere in the library is a warning only.

### Index and usage (SQLite)

One database, `$XDG_STATE_HOME/amontillado/index.sqlite` (state, not cache: the usage table
cannot be rebuilt):

- `records`: one row per record (id, name, directory, root, whether it is under the NSFW root,
  purity, category, tags as JSON, source site and id), and `files`: one row per file present
  (path, record id, sha256 (indexed), whether it is the default file, size, every metric,
  and for the hash cache its size in bytes and mtime in ns).
  **Rebuilt from the info files** by `amo index`, in one transaction (dropped and recreated, so
  their schema needs no migrations): delete the database and nothing is lost but the usage
  table. The database's `PRAGMA user_version` is its schema version (3); a newer one than the
  program knows is refused. Schema 2 lacked the hash-cache columns; upgrading adds them empty.
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
```

Paths must be absolute (`~` is expanded). The NSFW root may not be, contain, or lie inside a
library root, symlinks resolved; that is a config error, since a recursive search would then
reach NSFW images. Unknown keys are warned about and ignored. The API key comes from
`WALLHAVEN_API_KEY` first, then the first line printed by `api_key_command` (split into words
as a shell would, and run without one); it is never written anywhere and never logged.

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
   call `/w/<id>` for tags, then move it into a new record directory `wallhaven-<id>` (sfw: the
   first library root; sketchy and nsfw: the NSFW root) and write the record with metrics
   measured on the **full** image (so stored metrics never come from a thumbnail); add it to
   the index. The record has no `name`. A failure at any step leaves nothing behind; an
   existing `wallhaven-<id>` directory is refused (the index is stale: run `amo index`).
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
amo list [FILTERS] [--aspect W:H] [--purity LIST] [--random N]   matching paths, one per line
amo fetch [FILTERS | --test-set] [WALLHAVEN] [--count N] [--max-candidates N]
          [--busy-from thumb|full] [--discard-mismatches] [--dry-run]
amo shown PICTURE... [--dry-run]     record that pictures were shown (for the usage table)
amo add FILE... [--name N] [--nsfw] [--force] [--dry-run]   make each file a record of its own
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
`--aspect W:H` picks each record's file as in "Records"; no prompt to create a crop yet, so
records without a matching file always take the fallback (the default file, one warning).

`amo shown` takes any PICTURE form under "Lookup" (a file found nowhere in the index is looked
up by content); one that matches no record, or more than one, exits non-zero before anything is
recorded.

`amo add` refuses (per file; the others are still added) a file already in a record, a
directory that already exists, a `--name` that is invalid or taken, and, without `--force`, a
file whose content the index already holds. It measures before it moves anything, and adds
the new record to the index itself.

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
| `accent` | the generator's primary colour if it has one (matugen); else the `base08`-`base0E` accent nearest in hue to the picture's `hue` metric; for a scheme or preset, `base0D` (the convention templates follow) |
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
chroma lowered only to stay in gamut) by the smallest step that passes; each change is logged
and listed under `adjusted`. What may move, in order:

1. the foreground of the pair;
2. `accent` (and `secondary`), only when no foreground fixes the pair: `border` (the accent) on
   `base00`, or an accent at middle lightness that neither `base00` nor `base07` labels at 4.5;
3. never the ramp backgrounds `base00`, `base01`, `base10`, `base11`.

Foregrounds first, because each fix then touches one pair only: a background sits under every
foreground, so moving it to fix one pair changes all the others. The accent is the palette's
link to the picture, so it moves last and as little as possible.

After each move every pair is checked again, so a colour moved for one pair is seen by the
next. A `border` that is the accent moves with it; one a palette file sets apart is a
foreground like any other. A pair no allowed move fixes (a background other than the accent
or secondary, such as `selection`, whose label cannot reach the minimum) stays as it is, with a
warning. `--no-adjust` turns `adjust` into `report`; it does not turn checking back on under
`off`. `amo palette --check FILE` prints each failing pair (`dark: base03 on base00: 2.52, needs
3`) on stdout and exits non-zero if there are any; it never adjusts. (A first run on gruvbox,
2026-10-30: dark needed five moves, light twelve, mostly its accents on `base01`; the light
variant's brightened `base12`-`base17` come back down to about their base colours, so a light
variant's bright step may want to be darker instead: to calibrate.)

### Generators

An adapter takes a picture path and returns a partial palette for each variant (base16 or
base24, and any roles it knows); amontillado completes it as above. Generators are external programs,
detected at run time (`pipx install` works without them; the commands that need one say so):

- **matugen ≥ 4.0** (first): its base16 backend assigns the named hues and its Material roles give
  `accent` (primary), `secondary` and the surfaces; one run gives both variants. Fedora ships
  3.1.0, which has Material roles only and no base16 output (4.0, 2026-02, added the base16
  backend, `hex_alpha` and the `format` / `set_alpha` filters, and changed the default JSON):
  amontillado reports the version and refuses rather than invent six named hues from three
  Material accents. The exact command line and JSON keys are checked against matugen 4.2 when the adapter
  is written.
- **wallust** (second): 16 colours clustered from the image, mapped onto base16 by the ANSI table
  in reverse. Its `color1` need not be red, so the named-hue slots are only nominal; roles are
  derived. Two runs, one with a dark palette setting and one with a light (the setting names are
  checked when the adapter is written). Useful when matugen is not installed.

`theme.generator` in the config picks one; default the first installed in that order.

### Template sources

| Source | Format | Where templates come from |
|---|---|---|
| `builtin` | mustache | shipped in the package (`amontillado/templates/`), variables-only |
| `tinted` | mustache | tinted-theming template repositories (MIT), e.g. `tinted-terminal`, `base16-rofi` |
| `matugen-themes` | matugen | `InioX/matugen-themes` (MIT) |
| `pywal` | pywal | `eylles/pywal16`'s `pywal/templates/` (MIT) |
| `url` | stated | one file at a commit URL, with its `sha256` |
| `path` | stated | a local file (the user's own template) |

**The registry** (`amontillado/registry.yaml`, shipped) maps each app to its template in each
source: repository, path in it, pinned commit, and the file's `sha256`; and per entry whether the
result is a complete theme or variables only. A release of amontillado moves the pins
(`tools/registry.py` checks for new commits and records hashes); the user's config can override
an entry. `amo theme sync` downloads each file the config needs (one HTTPS request per file at
the pinned commit, no git) into `$XDG_CACHE_HOME/amontillado/sources/` and checks its hash; a
mismatch is an error and nothing is kept. Templates fetched this way are not redistributed by
amontillado; any template copied into `builtin` keeps its copyright notice in
`THIRD-PARTY.md`.

**Built-in templates** (variables-only, every role included, initial set from the chezmoi plan's
app table): `kitty` (`color0`-`color15`, background, foreground, cursor, selection; an `include`
file), `gtk` (`@define-color` for every key: imported by waybar, swaync and wlogout styles, and by
GTK3 `gtk.css` and libadwaita's `gtk-4.0/gtk.css`), `rofi` (a `* { ... }` block of variables),
`hyprland` (a Lua table, D62), `hyprlock` (hyprlang `$variables`), `sway` (`set $variable`),
`dunst` (a `dunstrc.d` drop-in with the urgency colours: dunst has no variables, so this one is a
small complete theme), `nvim` (`palette.lua`), `shell` (`export AMO_BASE00=...`), and `json` (the
palette as JSON, for anything else). `amo theme templates` lists them with their variables.
Variables keep the palette's names (`base0A`, `on_accent`) except in rofi, whose parser rejects
`_` (rofi 2.0): there roles are hyphenated (`on-accent`). The hyprland and hyprlock colours are
`rrggbb` without `#`, so a config can add alpha (`"rgba(" .. c.accent .. "ee)"`, `rgb($accent)`);
the others are `#rrggbb`. kitty's file sets `color0`-`color21` (the ANSI table under "Formats and
views", then base16-shell's extras `base09`, `base0F`, `base01`, `base02`, `base04`, `base06`),
the tab, border, selection and URL colours. Headers name the palette by its slug, never its
name, so no quote in a name can break a Lua, shell or JSON file. Default output files: `kitty.conf`,
`colors.css`, `colors.rasi`, `hyprland.lua`, `hyprlock.conf`, `sway`, `dunst.conf`, `palette.lua`,
`colors.sh`, `palette.json`.

### Formats and views

Each format gets a *view* of the palette: the variables its templates expect.

- **mustache** (tinted-theming's builder spec, rendered with `pystache`, MIT): for every base24 key
  *and every role* the spec's variables (`accent-hex`, `accent-hex-r`, `accent-rgb-r`,
  `accent-rgb16-r`, `accent-dec-r`, `accent-hex-bgr`, ...), and `scheme-name`, `scheme-slug`,
  `scheme-slug-underscored`, `scheme-system` (`base24`), `scheme-variant`,
  `scheme-is-dark-variant` / `scheme-is-light-variant`; also `scheme-author` (the scheme's, or
  empty) and `scheme-description` (empty), which template headers name. Decimals have eight
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
- **matugen** (**departs**: the direction had matugen render these with `--import-json`):
  amontillado renders the subset of matugen's template language that matugen-themes uses, over a
  Material view of the palette. Counted over all 74 matugen-themes templates (2026-10-29): 4,476
  of 4,680 markers (96%) are plain colour fields (`{{colors.<role>.<mode>.hex}}`, `hex_stripped`,
  `red`, `green`, `blue`); the rest are the fields `rgb`, `rgba`, `hex_alpha`, the filters
  `set_alpha`, `set_lightness`, `auto_lightness`, `saturate` (with `hsl`), `lighten` and
  `replace` (each in a few templates), `for` loops over `colors` and `base16` with
  `if loop.last`, `{{image}}`, and the `base16.*` keys. One template loops over `palettes`
  (Material's tonal palettes, which the palette does not have): not supported. The filters must match matugen's
  arithmetic (HSL lightness, alpha), checked against matugen's output in tests. Anything else is
  a render error naming it. This settles the research's open question: matugen's
  `--import-json` only *adds* variables, its `colors.*` always come from its own generation, so
  with matugen rendering, a preset or wallust palette could not drive matugen-themes templates
  at all. Rendering ourselves works for every palette and needs no matugen at theme switch.
  An app can still choose matugen as its renderer (`render_with: matugen`, below).

  The Material view is a table that computes every Material role name those templates use
  (`colors.primary`, `colors.surface_container_high`, ...) from the palette at render time: `primary` from `accent`, `secondary`
  from `secondary`, `tertiary` from the `base08`-`base0E` accent farthest in hue from `accent`,
  `error` from `error`, each with its `on_*`, `*_container` (the colour at `base02`'s lightness,
  chroma reduced, for a dark variant; at `base06`'s for a light one), `on_*_container`, and the
  `*_fixed` family; surfaces from the neutral ramp (`surface`, `background` = `base00`;
  `surface_container_lowest` … `_highest` = `base11`, `base10`, `base01`, `base02`, and `base02`
  lightened by L +0.03; `on_surface` = `base05`, `on_surface_variant` = `base04`, `outline` =
  `base03`, `outline_variant` = `base02`); `inverse_*`, `shadow`, `scrim`, `source_color`,
  `surface_tint` by the obvious rule. The full table lives in code, with a test that it covers
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
  variant: auto                         # auto | dark | light
  contrast: adjust                      # adjust | report | off
  wallpaper: {reload: "hyprctl hyprpaper reload ,{wallpaper}"}
  apps:
    kitty:    {reload: "pkill -USR1 kitty"}                   # source defaults to builtin
    rofi:     {source: tinted}                                 # complete theme from base16-rofi
    waybar:   {source: builtin, template: gtk, output: waybar-colors.css, reload: "pkill -USR2 waybar"}
    hyprland: {source: matugen-themes, template: hyprland-colors.lua, reload: "hyprctl reload"}
    zed:      {source: matugen-themes, template: zed-colors.json, render_with: matugen}
    rofi-alt: {source: tinted, template: rofi, variant: light, output: rofi-light.rasi}
    nvim:     {}                                               # palette.lua, for a lush spec
    mytool:   {source: path, path: ~/.config/mytool/theme.mustache, format: mustache, output: mytool.conf}
```

- `source`: as in the table. Default per app: the first source with a template in the registry,
  in the order builtin, tinted, matugen-themes, pywal (most role-aware first).
- `template`: the registry entry within the source, when the app has several; defaults to the
  app's name.
- `format`: from the source; required for `url` and `path`.
- `url` + `sha256` for `source: url` (a commit URL; an unpinned template would run someone else's
  code at every theme switch, since some outputs are code: `hyprland.lua`, sourced shell files).
- `output`: the file name in the profile directory; default from the registry.
- `reload`: a command run after the swap, split as a shell would split it and run without one
  (as `api_key_command`); `{wallpaper}`, `{profile}` and `{dir}` are substituted. No shell, so
  a pipeline needs a script.
- `variant`: this app's variant, over `theme.variant` and `--variant` ("Palette").
- `render_with`: `amontillado` (default) or `matugen`, for `format: matugen` only. With `matugen`,
  amontillado writes a matugen config holding every such app's template and runs matugen once
  per apply (`matugen image PICTURE`, or `matugen color hex ACCENT` for a palette without a
  picture), rendering into the new profile directory. **Caveats**: the colours are matugen's own,
  not the palette's, since matugen cannot take colours in (`--import-json` only adds variables):
  the app misses the contrast adjustments, and with a preset or wallust palette it gets colours of
  the same accent hue but not the same colours. matugen ≥ 4 must be installed for every apply.
  Config-only, no CLI override.
- `wallpaper.reload`: run last, with the picture's path. Setting a wallpaper stays the user's
  command; amontillado only knows which picture belongs to the theme.

The block is checked whenever the config is loaded (any `amo` command), so a mistake fails at
once, naming its key (`theme.apps.kitty.reload: ...`); unknown keys warn, as at the top level.
Beyond the types and choices above: a profile name is a single path component that does not
start with `.` and is not `current` (both name other things in the cache); `output` is a plain
file name, not `palette.yaml`, `theme.yaml` or `wallpaper`, and no two apps give the same one;
`url` is `https://`; a reload command names no placeholder other than the three; `render_with:
matugen` needs `format: matugen` (or `source: matugen-themes`, whose format it is).

Whether a result is complete or variables-only comes from the registry (`amo theme templates`
shows it); a variables-only file does nothing until the app's own config maps the variables.

### Cache

`<cache>/<profile>/` (chezmoi D39, default `~/.cache/theme/default/`) holds every rendered
file, plus `palette.yaml` (the palette applied), `wallpaper` (a symlink to the picture) and
`theme.yaml` (what was applied: time, palette name, and per app the source, template, pinned
commit and output). `<cache>/current` is a symlink to the profile last applied (`--no-activate`
renders a profile without moving it). App configs include from `current/`, or from a fixed
profile; the "falling back to `current/`" of D39 is the user's include line, which amontillado
does not need to know about. A profile directory is built beside the old one and swapped in by
rename, and `current` is moved by renaming a new symlink over it (`ln -sfn` is not atomic), so
an app reading during an apply sees the old theme or the new one, never a mix.

A file watcher must watch a directory that is never replaced: `<cache>/` itself, reacting to
`current` (or a profile name) being renamed. A watch on `current/palette.lua` watches the
profile directory the link pointed to when the watch began, and goes deaf when that directory
is swapped out; a watch on a file goes deaf whenever the file is replaced by rename. (A real
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

A lush spec in the user's nvim config `dofile`s it and maps roles onto highlight groups; a
`vim.uv` file watcher on the cache directory (`~/.cache/theme/`, filtered on `current`; see
"Cache" for why not on `palette.lua`) re-runs `colorscheme`, so nvim needs no reload command.
`docs/examples/lush/` carries an example spec and the watcher (documentation, not a plugin).
Without lush, `source: tinted` (tinted-nvim) or `source: matugen-themes` (`neovim`) theme nvim
directly.

### CLI (v0.2)

```text
amo palette PICTURE [--generator G] [--no-adjust]   a palette (both variants) as YAML on stdout
amo palette --from-scheme FILE [FILE] [--no-adjust]   one or two tinted-theming schemes as a palette
amo palette --check FILE                       contrast report; non-zero if a pair fails
amo theme apply [PICTURE | --palette NAME|FILE] [--profile P] [--variant V] [--app NAME]...
                [--no-adjust] [--no-activate] [--no-reload] [--dry-run]   render, swap in, reload
amo theme sync [--check]                       fetch (or verify) every template the config needs
amo theme templates [APP]                      registry entries, sources and their variables
amo theme current [--profile P]                the applied palette's name, picture and time
```

PICTURE is any form under "Lookup"; without one, `amo theme apply` re-renders the profile's
current palette (after a config change). `--dry-run` renders into a temporary directory, prints
its path and what would be reloaded, and changes nothing. `amo theme apply` records the picture
as shown (`amo shown`), so the usage table sees theme switches.

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

## Testing

- No network in tests: the HTTP layer is one small function, replaced by a stub that serves
  recorded API responses (`tests/fixtures/`, trimmed to the fields used) and generated images.
- Images are generated in the tests (solid colours, gradients, noise), never committed.
- Metric tests use images whose answer is known: black is dark, a solid red is saturated,
  monochrome and red, grey noise is busy and muted, a smooth gradient is sparse.

## Roadmap

1. v0.1: the CLI above, calibrated thresholds, tests, CI, a tagged release.
2. Palette-aware grouping: features per image, clusters of compatible images, a coherent set
   for several monitors, the palette taken from the primary monitor's image.
3. v0.2, the theme engine (epic `amo-aqp`): palette files, generator adapters, per-app
   templates. Direction agreed in principle (2026-10-29): amontillado renders templates itself
   from optional sources (built-in variables-only templates, tinted-theming, matugen-themes,
   pywal), without running tinty: [research/tinted-theming.md](research/tinted-theming.md).
   Design agreed 2026-10-30: "Theme engine (v0.2)".
   Also for v0.2, **a commented config template**: `amo config init` writes `config.yaml` from a
   template shipped in the package, every key commented with its meaning and trade-offs (e.g.
   `render_with: matugen`'s caveats); `amo config check` validates a config. The key
   descriptions live in one table in code that generates the template's comments and the
   `--help` text of any flag overriding a key; this document links to the template rather than
   repeating it.
4. git-annex libraries (epic `amo-qnn`): each root a git-annex repository, info files in git,
   images annexed (SHA-256 keys, the same hash as each file's `sha256`); the index stays outside, in
   `$XDG_STATE_HOME`. Encryption of the NSFW library off-machine is a spike (git-remote-gcrypt
   and an encrypted annex remote, or git-crypt, which does not cover annexed content).
   **This brings the first non-Python dependencies** (git-annex, written in Haskell;
   git-remote-gcrypt and gnupg). They stay optional and detected at runtime: `pipx install`
   keeps working without them, and the commands that need them say so.

## Open questions

- `HUE_SHARE_MIN`: kept at 0.40 when metrics version 2 raised `--hue` coverage from 68% to 80%
  of the calibration sample ("Calibration"). Raising it narrows `--hue` to images dominated by
  one hue: 0.45 leaves 77%, 0.50 73%, 0.55 67% (about the old coverage). Revisit if `--hue`
  results look too loose in use; it is a query-time threshold, so no metrics version is needed.
- Whether `amo list` should prefer images shown least recently (it has the usage table).
- Index staleness: `amo list` trusts the index; whether it should detect changes since the last
  `amo index` (a stat walk of the roots) and warn or refresh.
