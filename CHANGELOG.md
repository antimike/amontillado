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
- `amo index [--check]`: gives every image in the library a YAML sidecar, heals broken or
  outdated ones (`.yaml` or `.yml`), re-pairs an image renamed or moved without its sidecar
  by content hash, and rebuilds the SQLite index, keeping the usage history.
- `amo list`: paths of indexed images by class (`--dark`, `--muted`, `--sparse`, `--hue blue`,
  `--monochrome`, `--warm`, ...), `--random N`; NSFW images only with `--purity`.
- `amo shown PATH...`: records that images were shown, by content, in the usage history.

### Fixed

- Log messages go to stderr, not stdout.
