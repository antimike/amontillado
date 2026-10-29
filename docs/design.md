# Design

Status: agreed for v0.1 (2026-10-27); the library, index, query commands and the fetcher are
implemented, test sets included; class thresholds calibrated (2026-10-28). Values marked
*initial* are starting points to calibrate on real images; change them here when they change in code.

## Scope

**v0.1, the library:** measure images, keep records, build the index, query it, fetch from
Wallhaven with filters, and build test sets. No GUI, no wallpaper setter, no timer: those belong
to the user's desktop configuration and call `amo list`.

**Later (see "Roadmap"):** palette-aware grouping and selection across monitors, and possibly a
theme engine layer.

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
      version: 1                    # bump when a metric's definition changes: forces recomputation
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
  (path, record id, sha256 (indexed), whether it is the default file, size, every metric).
  **Rebuilt from the info files** by `amo index`, in one transaction (dropped and recreated, so
  their schema needs no migrations): delete the database and nothing is lost but the usage
  table. The database's `PRAGMA user_version` is its schema version (2); a newer one than the
  program knows is refused.
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

### Classes (query-time, calibrated thresholds)

| Flag | Rule | Share of the sample |
|---|---|---|
| `--dark` / `--light` | `lightness` < 0.35 / > 0.65 | 21% / 22% |
| `--muted` / `--saturated` | `chroma` < 0.02 / > 0.075 | 19% / 18% |
| `--sparse` / `--busy` | `busy` < 0.03 / > 0.15 | 17% / 17% |
| `--hue NAME` | `hue_name` = NAME and `hue_share` ≥ 0.40, and not muted | 2-20% per hue; 68% have one |
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
- Fixed hue sectors split one hue rarely: 11 of the 278 images with `hue_spread` < 0.30 have
  `hue_share` < 0.40. A share within ±30° of the mean hue would recover about half of them; not
  worth a metric version for v0.1 (see "Open questions").
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
amo index [--check]                  heal records, rebuild the index; --check reports only
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
4. git-annex libraries (epic `amo-qnn`): each root a git-annex repository, info files in git,
   images annexed (SHA-256 keys, the same hash as each file's `sha256`); the index stays outside, in
   `$XDG_STATE_HOME`. Encryption of the NSFW library off-machine is a spike (git-remote-gcrypt
   and an encrypted annex remote, or git-crypt, which does not cover annexed content).
   **This brings the first non-Python dependencies** (git-annex, written in Haskell;
   git-remote-gcrypt and gnupg). They stay optional and detected at runtime: `pipx install`
   keeps working without them, and the commands that need them say so.

## Open questions

- Hue sectors: whether `hue_share` should be the weight within ±30° of the mean hue (and
  `hue_name` the sector holding the mean hue), so a hue on a sector boundary is not split;
  about 4% of narrow-hued images are affected ("Calibration").
- Whether `amo list` should prefer images shown least recently (it has the usage table).
- Index staleness: `amo list` trusts the index; whether it should detect changes since the last
  `amo index` (a stat walk of the roots) and warn or refresh.
