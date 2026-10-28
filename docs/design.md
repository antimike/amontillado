# Design

Status: agreed for v0.1 (2026-10-27), not yet implemented. Values marked *initial* are starting
points to calibrate on real images; change them here when they change in code.

## Scope

**v0.1, the library:** measure images, keep sidecars, build the index, query it, fetch from
Wallhaven with filters, and build test sets. No GUI, no wallpaper setter, no timer: those belong
to the user's desktop configuration and call `amo list`.

**Later (see "Roadmap"):** palette-aware grouping and selection across monitors, and possibly a
theme engine layer.

## Storage

### Library

- **Library roots**: directories of images, searched recursively; the layout under a root is
  up to the user (as in papis: sub-directories are allowed and carry no meaning to the tool).
  Default root `$XDG_DATA_HOME/amontillado/library`; more roots from the config file.
- **One exception: purity.** Sketchy and NSFW images go to a separate root (default
  `$XDG_DATA_HOME/amontillado/library-nsfw`) that is searched only when a command asks for it
  (`--purity`). A default query can never return one, so a picker bug cannot put one on screen
  during a screen share, and backups or syncs can treat that tree separately.
- **File names**: `wallhaven-<id>.<ext>` for fetched images (the original file as served, never
  re-encoded: JPEG or PNG); any name for images added by hand.

### Sidecars (source of truth)

`<image>.yaml` next to each image (`wallhaven-abc123.jpg` → `wallhaven-abc123.yaml`); an
image pairs with the sidecar of the same name stem, and `.yml` is read as well (new sidecars
are written as `.yaml`). Only facts
that do not change about the image:

```yaml
schema: 1
id: sha256:<hex>            # local id: content hash, so renames and moves do not matter
file: wallhaven-abc123.jpg  # relative to the sidecar
width: 3840
height: 2160
source:                     # null for images added by hand
  site: wallhaven
  id: abc123
  url: https://wallhaven.cc/w/abc123
  image_url: https://w.wallhaven.cc/full/ab/wallhaven-abc123.jpg
  purity: sfw               # sfw | sketchy | nsfw
  category: general         # general | anime | people
  tags: [landscape, night]
  colors: ["#000000", "#424153"]   # Wallhaven's own swatches
  source: ""                # the uploader's credited source, if any
  uploaded: 2024-06-02T21:53:31
fetched: 2026-10-27T18:00:00+00:00
metrics:
  version: 1                # bump when a metric's definition changes: forces recomputation
  lightness: 0.31
  chroma: 0.042
  colourful_share: 0.38
  hue: 262.0
  hue_name: blue
  hue_share: 0.71
  hue_spread: 0.18
  warmth: 0.12
  busy: 0.06
```

Read with `yaml.safe_load` only. Written atomically (temporary file, then rename).

**Healing** (`amo index`): an image without a sidecar first looks for an orphaned sidecar whose
`id` is its content hash, anywhere in the roots: the image was renamed or moved on its own, so
that sidecar is moved next to it (keeping its suffix) and its `file` updated, without measuring.
Otherwise it gets a new sidecar (`source: null`, `fetched: null`). An orphan is adopted once;
a second copy of the same content gets a sidecar of its own. A sidecar that does not parse, lacks fields, or has an older `metrics.version` is rewritten,
keeping whatever `source` block still parses. A sidecar that is not valid YAML is first kept as
`<name>.bad` (`a.yaml.bad`), so a typo in a hand edit loses nothing. A changed content hash means new
content: `id`, size and metrics are all recomputed. A renamed image (sidecar renamed with it)
only has `file` updated. Sidecars without an image are reported, not deleted. An ambiguous
pairing (two images that would share a sidecar, `a.jpg` and `a.png`, or one image with both
`a.yaml` and `a.yml`) is reported and not indexed until it is resolved by hand.

Images are `.jpg`, `.jpeg`, `.png` and `.webp` files; directory symlinks under a root are not
followed. **Purity** is the sidecar's `source.purity`; without one, an image under the NSFW root
counts as `nsfw` and any other as `sfw`. A non-sfw image outside the NSFW root is warned about.

### Records (agreed 2026-10-27, not yet implemented)

Replaces "Sidecars" above in bead `amo-3fg.9`, before the fetcher writes any library; until
then the code follows "Sidecars". Breaking changes like this are expected in 0.x.

A **record** is one picture: a directory holding `info.yaml` (or `info.yml`) and the picture's
files, all inside the directory: formats of the same image, crops per aspect ratio, and later
generated theme files. The directory name carries no meaning to the tool; `amo` names the ones
it creates after the record's `name` or Wallhaven id.

```yaml
schema: 2
id: 3f2a9c1e0b7d4e8f9a6b5c4d3e2f1a0b   # generated once (uuid4), never changes; usage keys off it
name: night-city                    # optional; unique in the library; [a-z0-9][a-z0-9._-]*
default_file: night-city.png        # optional; see below
source: {...}                       # as in "Sidecars"; null for pictures added by hand
fetched: 2026-10-27T18:00:00+00:00
files:
  night-city.png:
    sha256: <hex>                   # required: content lookups, duplicates, re-pairing
    width: 3840
    height: 2160
    metrics: {version: 1, lightness: 0.31, ...}   # per file: a crop measures differently
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

- `images`: one row per image (path, id, root, whether it is under the NSFW root, purity,
  category, tags as JSON, source site and id, size, every metric). **Rebuilt from the sidecars**
  by `amo index`, in one transaction (dropped and recreated, so its schema needs no
  migrations): delete the database and nothing is lost but the usage table. The database's
  `PRAGMA user_version` is its schema version; a newer one than the program knows is refused.
- `usage`: `id` (content hash), `shown_count`, `last_shown` (ISO 8601, UTC); later perhaps a
  rating. Keyed by content, so it follows an image through renames and moves. Kept across
  rebuilds. The only mutable data; never written to sidecars, which keeps them stable under
  git-annex or sync tools.

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
`WALLHAVEN_API_KEY` first, then `api_key_command`; it is never written anywhere and never logged.

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
| `hue_name`, `hue_share` | the named sector (below) with the largest chroma weight, and its share of all chromatic weight | "red-heavy" |
| `hue_spread` | circular variance of the chroma-weighted hues, 1 − R (0 = one hue, 1 = all hues evenly) | monochrome vs multi-hued: does the generator find distinct accents when the image offers one hue? |
| `warmth` | (warm weight − cool weight) / total chromatic weight, in −1..1 | warm vs cool; warm sectors are red, orange, yellow, pink |
| `busy` | edge density: share of interior pixels whose Sobel gradient magnitude on L exceeds 0.08 (*initial*) | legibility of text over translucent, blurred windows |

The Sobel kernels are divided by 8, so the gradient magnitude is the change in L per pixel: a
hard black-to-white edge scores 0.5 on the pixels either side of it. The one-pixel border is
left out.

Hue sectors (degrees, OKLCH; boundaries halfway between the reference hues, *initial*; each
sector includes its lower bound): red 358-44, orange 44-80, yellow 80-125, green 125-170,
cyan 170-230, blue 230-280, purple 280-310, pink 310-358.

A greyscale image has no chromatic pixels: `hue`, `hue_name` are null, `hue_share`,
`hue_spread` and `warmth` are 0. It is muted, never monochrome.

Values are rounded when written: `hue` to 0.1°, the others to 3 decimals.

### Classes (query-time, *initial* thresholds)

| Flag | Rule |
|---|---|
| `--dark` / `--light` | `lightness` < 0.35 / > 0.65 |
| `--muted` / `--saturated` | `chroma` < 0.03 / > 0.08 |
| `--sparse` / `--busy` | `busy` < 0.04 / > 0.12 |
| `--hue NAME` | `hue_name` = NAME and `hue_share` ≥ 0.40, and not muted |
| `--monochrome` / `--multi-hue` | has chromatic pixels and `hue_spread` < 0.30 / `hue_spread` > 0.60 |
| `--warm` / `--cool` | `warmth` > 0.3 / < −0.3 |

Calibrate before v0.1: measure a few hundred thumbnails from a random Wallhaven sample, look at
the distributions, and set thresholds so each class holds a sensible minority. Record the result
here.

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

1. Search with the server-side filters (tags, purity, category, size, swatch), `sorting=random`.
2. For each result not already in the library (by Wallhaven id): fetch the `large` thumbnail and
   measure it. Skip it if it fails a look filter.
3. `--busy-from thumb` (default) judges busy/sparse on the thumbnail. `--busy-from full` leaves
   that filter until after the full download (thumbnail JPEG artefacts add edges), and deletes
   the download if it fails.
4. Download the full image atomically, call `/w/<id>` for tags, write the sidecar with metrics
   measured on the **full** image (so sidecar metrics never come from a thumbnail), update the
   index.
5. Stop at `--count` images kept, or at `--max-candidates` (default 100, *initial*) examined.
   Pace API calls to stay under the rate limit; on HTTP 429, back off and retry.

### Test set

`amo fetch --test-set` keeps one image per bucket: dark, light, muted, saturated, busy, sparse,
monochrome, multi-hue; one image fills one bucket only. Other filters (size, category) still
apply. It is the input for comparing palette generators.

## CLI (v0.1)

```text
amo measure FILE...                  metrics and classes for any image, as YAML (no library needed)
amo index [--check]                  heal sidecars, rebuild the index; --check reports only
amo list [FILTERS] [--purity LIST] [--random N]   matching paths, one per line
amo fetch [FILTERS] [WALLHAVEN] [--count N] [--test-set] [--busy-from thumb|full] [--dry-run]
amo shown PATH... [--dry-run]        record that images were shown (for the usage table)
```

`amo index` fails (non-zero exit, after indexing everything it could) when images cannot be read
or two images would share a sidecar. `--check` is its dry run: it measures and writes nothing,
and fails if any sidecar needs healing or has no image.

`amo list` prints sfw images outside the NSFW root unless `--purity` (comma-separated: `sfw`,
`sketchy`, `nsfw`) asks for more; the NSFW-root test uses the current config and resolves
symlinks, so a stale index cannot leak an image. Opposite class flags (`--dark --light`) are
rejected. Indexed files that are gone are skipped with a warning. No match exits non-zero, so a
pipeline into a wallpaper setter notices.

FILTERS are the class flags above. WALLHAVEN: `--tags`, `--purity`, `--category`, `--atleast`,
`--ratio`, `--color HEX`. `--dry-run` measures thumbnails and reports what it would keep.

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
3. Possibly a theme engine layer (palette files, generator adapters, per-app templates); under
   discussion.
4. git-annex libraries (epic `amo-qnn`): each root a git-annex repository, sidecars in git,
   images annexed (SHA-256 keys, the same hash as `id`); the index stays outside, in
   `$XDG_STATE_HOME`. Encryption of the NSFW library off-machine is a spike (git-remote-gcrypt
   and an encrypted annex remote, or git-crypt, which does not cover annexed content).
   **This brings the first non-Python dependencies** (git-annex, written in Haskell;
   git-remote-gcrypt and gnupg). They stay optional and detected at runtime: `pipx install`
   keeps working without them, and the commands that need them say so.

## Open questions

- Thresholds: calibrate (above).
- Whether `amo list` should prefer images shown least recently (it has the usage table).
- Index staleness: `amo list` trusts the index; whether it should detect changes since the last
  `amo index` (a stat walk of the roots) and warn or refresh.
