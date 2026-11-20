# amontillado

A local wallpaper library (Python, uv, pipx). Read [README.md](README.md) for the goal and
[docs/design.md](docs/design.md) for the agreed design before changing anything;
[CONTRIBUTING.md](CONTRIBUTING.md) holds the coding standards, commit and release rules, and
is the source of truth for them in this repo.

- **Public repository.** No secrets, API keys, client or employer names. gitleaks runs as a
  pre-commit hook; on MH's machine also run `~/.local/share/chezmoi/tools/public-scan/public-scan`
  before each commit.
- **Never commit images**, except docs screenshots in `docs/images/` under the rules in
  CONTRIBUTING.md ("Tests"), and never commit real Wallhaven responses with more than the fields
  the tests use.
- Tests never touch the network. Run `just lint` and `just test` fresh before claiming anything
  passes.
- Keep `docs/design.md` in step with the code: thresholds, schema, CLI. Calibrated values replace
  the *initial* ones there.
- Confirm with MH before pushing, tagging, creating the GitHub repository, or anything else
  outward-facing.
- Commits written with Claude end with the `Co-Authored-By` trailer (the README's provenance
  note relies on it).
- Consumer: MH's dotfiles (`~/.local/share/chezmoi`) install a pinned tag with pipx and use the
  library for theming (that repo's `docs/plans/theming.md`). Machine-specific glue (wallpaper
  setters, timers, pickers) stays there, not here.

## Beads

Work items are tracked with `bd` (prefix `amo`, embedded mode). `.beads/` is gitignored: this
repo is public, and bead notes are working notes. Settings: `dolt.auto-commit batch`, `no-push`,
`no-git-ops` (so `bd` never commits to this repo; `bd init` did, before that was set). No Dolt
remote: never add one pointing at this repo. bd-track's daily cleanup timer covers the project.

- Use `bd ready` / `bd show` / `bd update` / `bd close` for the v0.1 work; no TODO lists in files.
- **Interim backup** until bd-track's state repo exists (draft design:
  `~/.local/src/bd-track/docs/dev/design-beads-state-repo.md`): at session end run
  `bd dolt commit` and `bd export --output .beads/issues.jsonl`. That copy is local only.
- Never `bd dolt push` (MH's rule: it stalls; Dolt-side pushes are MH's, by hand).

## Start prompt

The current epic's prompt (replace it when an epic closes):

> No release epic is planned. v0.9.0 (amo-301) shipped 2026-11-20. Open: amo-wn0 (grouping
> research: saved sets/ratings, style measures; design work, plan it with MH first), amo-mdi
> (`amo list --like --predicate`), amo-tyy (letterboxes the detector misses), and one triage
> ticket from 2026-11-13 (`/triage`). Ask MH which to plan into the next epic.
