# Version control for a library

A library is plain files: a directory per picture, holding its images and an `info.yaml`.
amontillado works the same whether a root is a git repository, a git-annex repository, a
Syncthing folder, a backup target or none of these, and it never runs git, git-annex, gpg or
git-remote-gcrypt itself. None of them is required. This page is for when you want a root
under version control:

- [What amo does when you opt in](#the-on_change-hook): the `on_change` hook and `amo hook
  git-commit`.
- [A git-annex root](#a-git-annex-root): the `.gitattributes` layout amo expects, and locked
  or unlocked files.
- [Merging info files](#merging-info-files-edited-on-two-machines) edited on two machines.
- [Writing your own hook](#writing-your-own-hook).
- [One tested encrypted setup](#one-tested-encrypted-setup).

The design and the reasoning are in [design.md](design.md), "git-annex libraries: decisions".

## The on_change hook

Unset by default. Set it in the config (`amo config init` writes a commented template) to a
command line, and amo runs it under `sh -c` after any command that wrote under a library root
(`amo index`, `fetch`, `add`, `crop`, `add-derived`, `edit`, `name`): once per root written to,
with the changes as JSON on stdin (below). amo's writes stand whatever the hook does; a hook
that fails is a warning.

The shipped hook commits to git:

```yaml
on_change: amo hook git-commit
```

For each root inside a git work tree, it makes one commit holding amo's changes and nothing
else, with a message like `amo fetch: night-sky-aaa111`:

- **Your uncommitted edits stay uncommitted.** Each info file is merged with `amo info merge`
  (base: the file as amo read it; ours: the committed version; theirs: as amo wrote it), and the
  merge is what is committed. If you had added a comment to an `info.yaml` and amo then changed
  it, the commit has amo's change only; your comment stays in the working tree. If amo and
  your edit changed the same key, that record is left out of the commit, with a warning naming
  it; commit it yourself.
- **What you have staged is neither committed nor lost.** The commit is built in a separate
  index, and committed with `git commit`, so your git hooks and commit signing apply.
- **New images and thumbnails** are added with `git add`, or `git annex add` in a git-annex
  repository (next section); files git ignores are left alone. Renames (`amo name`) are
  committed as renames.
- A root outside git is skipped with a warning. Without git (or without git-annex, for an
  annexed root) the hook says so; `amo config check` flags both.

## A git-annex root

[git-annex](https://git-annex.branchable.com/) keeps the images out of git (git stores a key,
the image's SHA-256, the same hash as each file's `sha256` in `info.yaml`) while the info files
and thumbnails stay in git, small and diffable. amo works with any root, annexed or not; what
it needs of an annexed one:

**Images annexed, everything else in git.** In the root's `.gitattributes`, one pattern per
line (a gitattributes value cannot contain spaces, so `(include=*.jpg or include=*.png)` does
not work: it is cut at the space, silently, and the images go into git):

```gitattributes
* annex.largefiles=nothing
*.jpg annex.largefiles=anything
*.jpeg annex.largefiles=anything
*.png annex.largefiles=anything
*.webp annex.largefiles=anything
**/.amo/** annex.largefiles=nothing
```

The last line keeps each record's thumbnail (`<record>/.amo/thumbnail.jpg`) in git, so a
picker (`amo list --format rofi`) can show pictures whose content is not on this machine. It
must come after the image lines, and must start with `**/`: a pattern with a slash is anchored
at the directory of the `.gitattributes`, so `.amo/**` would match only a `.amo` in the root
itself. git-annex already keeps files in dot-directories in git (unless `annex.dotfiles` is set),
so the line is a guard rather than a necessity. Check it with:

```sh
git check-attr annex.largefiles -- some-record/some-record.jpg some-record/.amo/thumbnail.jpg
```

**Dropped content is fine.** A file whose content is not on this machine (`git annex drop`, or
a clone that has not run `git annex get`) is *absent*, not missing: `amo index` keeps its entry
and indexes it, `amo list` skips it, and `amo palette` / `amo theme apply` on it tell you to
`git annex get` it ([design.md](design.md), "Absent content").

### Locked or unlocked

git-annex adds a file **locked** by default: the working tree has a read-only symlink into
`.git/annex/objects`, where the content lives. Or **unlocked**: an ordinary file, with git
holding a small pointer. amo handles both, and `amo hook git-commit` adds new images the way
your configuration says (with `git annex add`; a plain `git add` would always add them
unlocked). The choice is yours:

| | locked (default) | unlocked | unlocked + `annex.thin` |
|---|---|---|---|
| In the working tree | a symlink to the content | a copy of the content | a hard link to the content |
| Disk use | one copy | two copies (working tree and annex) | one copy |
| Editing a file in place | refused until `git annex unlock` | fine; the annexed old version is kept | changes the annexed copy too: the old version can be lost if it was the only copy |
| Tools that dislike symlinks | may show the hashed object name | fine | fine |

amo never edits an image in place (`amo crop`, `amo edit` and `amo add-derived` make new files),
and wallpaper setters follow symlinks, so locked files suit a library well. Where the settings
live:

- `annex.addunlocked` (add new files unlocked): per clone with `git config annex.addunlocked
  true`, or for every clone with `git annex config --set annex.addunlocked true` (stored in the
  git-annex branch; a clone's git config overrides it).
- `annex.thin` (hard links instead of a second copy, for unlocked files): per clone only,
  `git config annex.thin true`; `git annex config` refuses it. Hard links need the working tree
  and `.git/annex` on one filesystem.
- Changing an existing file: `git annex unlock FILE` / `git annex lock FILE`.

## Merging info files edited on two machines

git merges `info.yaml` line by line, so two machines that changed nearby lines conflict, and
the conflict markers make the file unparseable YAML. `amo info merge` merges by key instead: a
top-level key is one unit, the file names under `files` with `default_file` are one, and each
`files` entry is one. A unit changed on one side takes that side; changed differently on both,
it is a conflict, and the file is left as yours (no markers). Register it as a merge driver:

```sh
# Once per root, versioned (in the root's .gitattributes):
printf 'info.yaml merge=amo-info\ninfo.yml merge=amo-info\n' >> .gitattributes
# Once per clone (git config is not versioned):
git config merge.amo-info.name "amontillado info files"
git config merge.amo-info.driver 'amo info merge %O %A %B --name %P'
```

`git pull`, `git merge` and `git annex sync` then merge info files by key; a real conflict is
reported with the conflicting keys and left for you, as any merge conflict.
`amo info diff OLD NEW` shows what differs between two versions by key path, ignoring comments
and layout.

## Writing your own hook

`on_change` can be any command line. It runs under `sh -c` from amo's working directory, with
`AMO_ROOT` (the root) and `AMO_COMMAND` (`index`, `fetch`, ...) set, once per root, after the
command; its standard output goes to amo's standard error (amo's own output is data). Its
standard input is one JSON object:

```json
{
  "version": 1,
  "command": "name",
  "root": "/home/me/.local/share/amontillado/library",
  "changes": [
    {"type": "rename", "from": "wallhaven-x8ye3z", "to": "harbour-morning"},
    {"type": "info", "path": "harbour-morning/info.yaml", "before": "schema: 2\n...", "after": "schema: 2\n..."},
    {"type": "file", "path": "harbour-morning/.amo/thumbnail.jpg"}
  ]
}
```

Paths are relative to the root. `rename` changes come first (a record directory renamed by `amo
name`, or a loose image moved into its record by `amo add`); an `info` change's path is where
the file is now, `before` its text as amo read it (`null` for a new file) and `after` as amo
wrote it; a `file` is an image or thumbnail amo made or replaced. No amo command deletes files
under a root. `amo info diff` and `amo info merge` take files, so to compare `before` and
`after`, write them out first. For example, to log what changed:

```yaml
on_change: jq -r '.command as $c | .changes[] | "\($c): \(.type) \(.path // .to)"' | logger -t amo
```

## One tested encrypted setup

For a library that should leave the machine only encrypted (tested in the amo-qnn.1 spike;
[design.md](design.md), "git-annex libraries: decisions" 1 to 4):

- **git-remote-gcrypt** for the git side (`git remote add backup gcrypt::<url>`): info files,
  record names, the git-annex branch (every image's hash) and commit messages are all encrypted.
  The remote can be a hosted git repository (it needs force pushes allowed; set
  `gcrypt.require-explicit-force-push`).
- **an encrypted git-annex special remote** for the images (`git annex initremote <name>
  type=directory directory=<path> encryption=hybrid keyid=<key>`, on a backup drive say), or a
  `type=gcrypt` special remote on an ssh host or local path holding git and images together.
- **One OpenPGP key per machine**, plus an offline backup key, each a recipient of both
  remotes.
- **Not git-crypt**: `git annex init` writes a `* filter=annex` that outranks a
  `filter=git-crypt` in `.gitattributes`, so info files were pushed in plaintext, silently; and
  git-crypt would leave paths, hashes and commit messages readable anyway.

Keys, adding and removing a machine, and restoring on a new one are machine setup, not amo's:
the step-by-step runbook lives with the dotfiles that set the machines up.
