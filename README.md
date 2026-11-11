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
- **Theme the desktop** from a picture: make a palette (with matugen or wallust, both
  optional), check its contrast and fix what fails, render it into each app's file
  (amontillado's own templates, or tinted-theming, matugen-themes and pywal16 ones, pinned),
  and swap them all in at once, with each app's reload command.

Later, the same measurements are meant to drive palette-aware selection: grouping images whose
colours go together, so that several monitors show a coherent set. See
[docs/design.md](docs/design.md) for the plan and the reasoning behind it.

## Status

Pre-alpha. v0.1.0 brought measuring, the library, the index, queries, the Wallhaven fetcher
and test sets, with class thresholds calibrated on a Wallhaven sample; v0.2.0 adds the theme
engine, interactive crops and search over the index; v0.3.0 a libadwaita template with a
colour-scheme hook, record naming and hand-made derived files ([CHANGELOG.md](CHANGELOG.md)).
Unreleased on main, for v0.4: a GTK4-only `libadwaita-vars` template that also sets
libadwaita's CSS variables and GNOME's palette from the theme.
`amontillado` and its short alias `amo` are the same command.

## Install

Pin a tag:

```sh
pipx install git+https://github.com/antimike/amontillado@v0.3.0
```

From a checkout, for development: `just install-dev` (an editable pipx install), or
`uv run amo …` without installing.

## Usage

```sh
amo fetch --dark --sparse --count 3        # keep 3 dark, uncluttered wallpapers from Wallhaven
amo fetch --hue blue --ratio 21:9 --dry-run   # show what would be kept; download nothing
amo fetch --test-set                       # one wallpaper per bucket: dark, light, muted, ...
amo add --name forest ~/Downloads/forest.jpg   # make your own image a record
amo index                                  # heal records and rebuild the index
amo crop forest 21:9                       # a 21:9 crop of a record, for an ultrawide
amo list --dark --muted --random 1         # a path, for a wallpaper setter
amo shown "$(amo list --dark --random 1)"  # count a showing in the usage history
amo list --dark --format rofi | rofi -dmenu -show-icons   # pick one, with thumbnails
amo measure some.png                       # metrics and classes of any image, as YAML
amo list --tag night --where "shown_count = 0"   # search provenance and the whole record
amo crop forest 21:9 --interactive         # place the crop by hand
amo edit forest                            # retouch a copy in your editor, keep the result

amo config init                            # a commented config: every key, its meaning
amo palette forest                         # a picture's palette, both variants, as YAML
amo theme sync                             # fetch the pinned templates the config uses
amo theme apply forest                     # theme every configured app from it, reload them
```

`amo COMMAND --help` documents every option. The class thresholds (what counts as dark, busy,
...), the record format and the fetcher's behaviour are in [docs/design.md](docs/design.md).

## Optional: version control

A library is plain files, and amo works the same under git, git-annex, Syncthing, a backup
tool or nothing; it never runs git, git-annex, gpg or git-remote-gcrypt on its own, and none of
them is needed to install or use it. To keep a root in git, opt in:

```yaml
on_change: amo hook git-commit   # in the config: commit what each amo command writes
```

Each command that writes under a root then makes one commit there with only its changes, your
own uncommitted edits left alone; in a git-annex repository new images go in with `git annex
add`. Without git (or git-annex, for an annexed root) the hook says so and amo's own work is
unaffected. [docs/version-control.md](docs/version-control.md) has the git-annex layout, locked
and unlocked files, `amo info merge` as a git merge driver for info files edited on two
machines, writing your own hook, and one tested encrypted setup.

## Images and their licences

amontillado downloads images for your personal use. Each image belongs to its creator and stays
under the terms it was published with; this repository contains no wallpapers and never will.
The fetcher uses Wallhaven's public API and stays within its rate limit. Anything beyond
safe-for-work content needs your own Wallhaven API key, read from the environment or a command
you configure, never stored by the tool.

## Documentation

- [docs/design.md](docs/design.md): storage layout, metric definitions, the fetcher, the CLI
- [docs/version-control.md](docs/version-control.md): a library root in git or git-annex, the
  on_change hook, merging info files, an encrypted setup
- [docs/colour-scheme-hooks.md](docs/colour-scheme-hooks.md): keeping the desktop's dark/light
  scheme in step with the theme (libadwaita needs it)
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
