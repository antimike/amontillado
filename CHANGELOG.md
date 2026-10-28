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

### Fixed

- Log messages go to stderr, not stdout.
