# Changelog

All notable changes to amontillado are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
  keeping the usage history.
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
- `api_key_command` in `config.yaml`, or `WALLHAVEN_API_KEY`: the Wallhaven API key, needed for
  nsfw results, never logged or stored.

### Fixed

- Log messages go to stderr, not stdout.
