# amontillado

A local wallpaper library (Python, uv, pipx). Read [README.md](README.md) for the goal and
[docs/design.md](docs/design.md) for the agreed design before changing anything;
[CONTRIBUTING.md](CONTRIBUTING.md) holds the coding standards, commit and release rules, and
is the source of truth for them in this repo.

**Role (MH 2026-11-22):** exploratory support for MH's theming work in the dotfiles. MH tries an
idea live and then keeps or drops it, so features MH approves are built in full and quickly.
Extras ship marked *experimental* (`--help`, CHANGELOG, docs), with a bead to keep or remove
each after use. The D81 gates still run, as input to MH's decision rather than a veto.
Infrastructure nobody asked for still gets pushback. Publishing it as a portfolio piece is a
later goal.

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

> Next: build amo-0k6 (saved looks, accepted in full 2026-11-22: docs/design.md "Saved looks"),
> beads amo-0k6.1-.7 in dependency order (`bd ready`; Opus for .1 and .4), extras marked
> experimental; amo-0k6.8 evaluates them after MH's use. Fix amo-0jw (fetch indexes records
> without their name) first. amo-n0o (hand-changed record ids) is a v0.12.x candidate. amo-yyu
> (review dim's blue, D3) is due after 1-2 weeks of MH using dim (from about 2026-12-05).
> amo-abc stays parked. Outside: amo-mdi, amo-tyy, amo-dvv (P4, design open).
