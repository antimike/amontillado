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

> Next: design amo-0k6 (saved sets: the whole look, pictures by record id + embedded palette;
> MH's decisions are on the bead), under epic amo-wn0; prior-art entry first, `/project-review`
> before acceptance; amo-abc stays parked. Small fix any time: amo-0jw (fetch indexes records
> without their name; workaround `amo index`), a v0.12.1 candidate. amo-yyu (review dim's blue, D3) is due after 1-2 weeks of MH using dim (from about
> 2026-12-05). Outside: amo-wn0, amo-mdi, amo-tyy, amo-dvv (P4, design open).
