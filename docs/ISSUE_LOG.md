# Issue & Incident Log

Reference log for the issue numbers and incident dates behind CI, workflow, and
system design decisions. Kept here so the docs can stay evergreen while the
history remains findable.

## CI & pipeline

| Reference | Date | What happened / what it drove |
|-----------|------|-------------------------------|
| [#76](https://github.com/dan2bit/live-shows/issues/76) | 2026-06-27 | **Private-data leak incident.** An inbox routine wrote the private purchasing sidecar to a `live-shows-private/` folder inside this public repo instead of the separate private repo, exposing the cost/seat/qty/notes ledger. Removal required a git history rewrite + force-push. Drove the entire `staging` → `main` pipeline: the required `guard` status check (`private-data-guard.yml`), `auto-promote.yml`, and the deploy-key commit pattern used by all bots. |
| [#89](https://github.com/dan2bit/live-shows/issues/89) | 2026-06-30 | Long-running `dev` integration branch considered and rejected; the two-branch (`staging` → `main`) model stands. The `?dataref` / `site.data_branch` override design proceeds against transient/PR branches. |
| [#111](https://github.com/dan2bit/live-shows/issues/111) | — | In-page (authenticated browser) UI writes routed through `staging` via `site.data_branch` in `config.yaml` / `dataBranch()` in `app.js`. |
| [#119](https://github.com/dan2bit/live-shows/issues/119) | — | Times Seen drift between `artists.tsv` and the canonical ledger. Drove the blocking `audit-times-seen.yml` check. |
| [#131](https://github.com/dan2bit/live-shows/issues/131) | — | Photo URL integrity (item 4): every show Photo URL must match a Share Link row in `artist-photos.tsv`. Drove `reconcile-photos.yml` (CORRUPT fails, MISSING reports). |
| [#152](https://github.com/dan2bit/live-shows/issues/152) | — | Purchased shows reflected into potentials + fast_track + new-artist research. Drove the `reconcile_purchases.py` step in `potentials-maintenance.yml`. |
| [#186](https://github.com/dan2bit/live-shows/issues/186) | — | Box Office flag guardrail (warn-only). Drove the `check_box_office.py` step in `potentials-maintenance.yml`. |

## Show-goals system (`docs/GOALS_SPEC.md`)

| Reference | Date | What happened / what it drove |
|-----------|------|-------------------------------|
| [#85](https://github.com/dan2bit/live-shows/issues/85) | closed 2026-07-10 | **Umbrella.** Badge taxonomy: separated show/ticket *state* badges (code-fixed) from *goal/achievement* badges (config-driven `show_goals`), retiring note-string detection. |
| [#107](https://github.com/dan2bit/live-shows/issues/107) | — | Artist modal + the frozen `artist_modal_index.json` schema (builder ↔ renderer contract). |
| [#115](https://github.com/dan2bit/live-shows/issues/115) | — | Hat eligibility file + `hat_signatures.tsv` event log — the pattern all event-log goals follow. |
| [#116](https://github.com/dan2bit/live-shows/issues/116) | — | Explicit favorite: gauge pinned to full with star marker; earned-max stays asymptotically below 1.0 to keep the distinction. |
| [#117](https://github.com/dan2bit/live-shows/issues/117) | — | Photo badge metric: distinct photographed shows (never `times_seen`); Google Photos album links via `artist-albums.tsv`. |
| [#137](https://github.com/dan2bit/live-shows/issues/137) | 2026-07-09 | GOALS_SPEC ratification. The original attribution table treated `of` and `w/` identically — corrected 2026-07-10 during implementation (see the spec's amendment note). |
| [#138](https://github.com/dan2bit/live-shows/issues/138) / [#139](https://github.com/dan2bit/live-shows/issues/139) / [#140](https://github.com/dan2bit/live-shows/issues/140) | closed 2026-07-10 | The S2 (books split) / S3 (builder rewire) / S4 (app.js row badges) rollout stages. S2+S3 landed together as one atomic change via [PR #141](https://github.com/dan2bit/live-shows/pull/141). |
| [#165](https://github.com/dan2bit/live-shows/issues/165) | 2026-07-14 | Affinity G-term: per-goal weights replaced by a flat diminishing series over completion events (`G = 1 − d^n`); `weight` config fields obsolete. |
