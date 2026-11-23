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
- **Group** pictures whose colours go together, so that several monitors show a coherent set:
  `amo group` picks one per monitor, the theme taken from the first. See
  [docs/design.md](docs/design.md) for the reasoning behind it.

## Status

Pre-alpha. v0.1.0 brought measuring, the library, the index, queries, the Wallhaven fetcher
and test sets, with class thresholds calibrated on a Wallhaven sample; v0.2.0 adds the theme
engine, interactive crops and search over the index; v0.3.0 a libadwaita template with a
colour-scheme hook, record naming and hand-made derived files; v0.4.0 optional version control
(an `on_change` hook that can commit to git or git-annex, info files that keep their comments
and merge by key), `amo edit`, and a GTK4 `libadwaita-vars` template; v0.5.0 a `system`
variant that follows the desktop's dark/light colour scheme; v0.6.0 `amo list --order
least-shown`, a warning when the index is out of date, and darker bright colours for light
themes; v0.7.0 palette-aware grouping: a palette per picture, `amo list --like`, and `amo
group`, one picture per monitor whose colours go together; v0.8.0 your own predicates for `amo
group` and letterbox detection with a crop to the picture; v0.9.0 Wallhaven tag categories,
so names from tags pass over artists and brands; v0.10.0 terminal theming under light
variants; v0.11.0 gentler tones, soft light and dim dark; v0.12.0 GTK3 apps recoloured live;
v0.13.0 saved looks, the pictures on screen kept with their theme ([CHANGELOG.md](CHANGELOG.md)).
`amontillado` and its short alias `amo` are the same command.

## Install

Pin a tag:

```sh
pipx install git+https://github.com/antimike/amontillado@v0.9.0
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
amo list --dark --order least-shown --random 1   # the dark picture shown least, for a timer
amo list --dark --format rofi | rofi -dmenu -show-icons   # pick one, with thumbnails
amo measure some.png                       # metrics and classes of any image, as YAML
amo list --tag night --where "shown_count = 0"   # search provenance and the whole record
amo list --like forest --max-distance 0.09   # pictures whose colours go with forest's
amo group --monitor DP-1=21:9 --monitor HDMI-1=16:9   # a picture per monitor, colours together
amo group --monitor DP-1=21:9 --monitor HDMI-1=16:9 --apply   # ... and set them (group.setter)
amo group --monitor DP-1=21:9 --monitor HDMI-1=16:9 --predicate same-site   # your own test
amo crop forest 21:9 --interactive         # place the crop by hand
amo crop film --letterbox                  # crop a film still's black bars off
amo fetch --refresh-tags                   # tag categories for records fetched before 0.9
amo name --from-tags --force --dry-run     # the names their tags would give them now
amo edit forest                            # retouch a copy in your editor, keep the result

amo config init                            # a commented config: every key, its meaning
amo palette forest                         # a picture's palette, both variants, as YAML
amo theme sync                             # fetch the pinned templates the config uses
amo theme apply forest                     # theme every configured app from it, reload them
amo theme apply --tone dark=dim            # the same, gentler: charcoal instead of near-black
amo theme save iss-morning                 # keep the pictures on screen with their theme
amo theme apply --palette iss-morning      # ... and bring both back later
```

**Saved looks** keep a set of wallpapers, one per monitor, with the theme they were seen with:
`amo theme save` after an `amo group --apply` and a theme from its primary, `amo theme apply
--palette NAME` to restore them. See [docs/saved-looks.md](docs/saved-looks.md).

**Experimental** (may change or go in a minor release; kept or removed after use):

- [History](docs/saved-looks.md#history-experimental): `amo theme apply --history N`,
  `theme.history_size`
- [`amo theme list`](docs/saved-looks.md#choosing-one-experimental), with `--order` and the
  rofi format
- [`amo theme preview`](docs/saved-looks.md#choosing-one-experimental)

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
- [docs/terminal-theming.md](docs/terminal-theming.md): terminals and shell tools under a
  palette: fixed colours, LS_COLORS with vivid, prompt hooks, p10k and fast-syntax-highlighting,
  and the soft and dim tones
- [docs/gtk-theming.md](docs/gtk-theming.md): GTK3 apps recoloured live under adw-gtk3
  (`amo hook gtk3-theme`) and GTK4 apps through `libadwaita-vars`
- [docs/saved-looks.md](docs/saved-looks.md): saving the pictures on screen with their theme,
  applying them again, and the experimental history, list and preview
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
