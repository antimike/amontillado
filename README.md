# amontillado

A local wallpaper library that knows what its images look like.

## What it is for

Wallpaper tools usually treat images as opaque files: pick one at random, or pick one by name.
Desktop theming wants more than that. A dark theme needs a dark wallpaper. A palette generator
needs an image with some colour in it. Text over a translucent window needs a wallpaper that is
not too busy behind it. amontillado aims to make those properties something you can ask for:

- **Measure** every image once, in a perceptual colour space (OKLCH): how light it is, how
  colourful, its dominant hue and how much of the image it covers, how many hues it has, and
  how much fine detail.
- **Keep the metadata with the image.** Each picture is a directory holding its files and an
  `info.yaml` (in the style of [papis](https://github.com/papis/papis)): readable, editable, and
  still valid when the directory is moved or synced. A SQLite index is rebuilt from the info
  files for fast queries; usage history (when a picture was last shown) is kept separately, so
  the info files stay stable.
- **Fetch** from [Wallhaven](https://wallhaven.cc) by tags, purity, category and resolution,
  and by look: `--dark`, `--muted`, `--sparse`, `--hue blue`, `--monochrome`. Thumbnails are
  measured before anything is downloaded.
- **Query** the local library the same way (`amo list --dark --hue blue`) and print paths, so
  any wallpaper setter, picker or timer can use the result.
- **Build test sets**: one image for each visual extreme, for exercising palette generators and
  theme templates against the images that break them.

Later, the same measurements are meant to drive palette-aware selection: grouping images whose
colours go together, so that several monitors show a coherent set. See
[docs/design.md](docs/design.md) for the plan and the reasoning behind it.

## Status

Pre-alpha; v0.1.0 is the first release. Measuring, the library, the index, queries, the
Wallhaven fetcher and test sets work, with class thresholds calibrated on a Wallhaven sample.
`amontillado` and its short alias `amo` are the same command.

## Install

Pin a tag:

```sh
pipx install git+https://github.com/antimike/amontillado@v0.1.0
```

From a checkout, for development: `just install-dev` (an editable pipx install), or
`uv run amo …` without installing.

## Usage

```sh
amo fetch --dark --sparse --count 3        # keep 3 dark, uncluttered wallpapers from Wallhaven
amo fetch --hue blue --ratio 21:9 --dry-run   # show what would be kept; download nothing
amo fetch --test-set                       # one wallpaper per bucket: dark, light, muted, ...
amo add ~/Downloads/forest.jpg             # make your own image a record
amo index                                  # heal records and rebuild the index
amo list --dark --muted --random 1         # a path, for a wallpaper setter
amo shown "$(amo list --dark --random 1)"  # count a showing in the usage history
amo measure some.png                       # metrics and classes of any image, as YAML
```

`amo COMMAND --help` documents every option. The class thresholds (what counts as dark, busy,
...), the record format and the fetcher's behaviour are in [docs/design.md](docs/design.md).

## Images and their licences

amontillado downloads images for your personal use. Each image belongs to its creator and stays
under the terms it was published with; this repository contains no wallpapers and never will.
The fetcher uses Wallhaven's public API and stays within its rate limit. Anything beyond
safe-for-work content needs your own Wallhaven API key, read from the environment or a command
you configure, never stored by the tool.

## Documentation

- [docs/design.md](docs/design.md): storage layout, metric definitions, the fetcher, the CLI
- [CONTRIBUTING.md](CONTRIBUTING.md): development setup, coding standards, commits and releases
- [CHANGELOG.md](CHANGELOG.md)

## The name

In Poe's *The Cask of Amontillado*, a man is walled up in a wine cellar. This program walls up
pictures: a cellar of wallpapers, each one catalogued.

## License

MIT; see [LICENSE.md](LICENSE.md).

## Provenance

amontillado is developed by Michael Haynes in collaboration with Claude, Anthropic's AI model,
working through Claude Code. Michael sets the direction and makes the design decisions; much of
the code and documentation is drafted by Claude and reviewed by Michael. Commits written with
Claude carry a `Co-Authored-By` trailer.
