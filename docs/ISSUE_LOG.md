# Issue & Incident Log

Reference log for the issue numbers and incident dates behind CI and workflow
design decisions. Kept here so the workflow docs can stay evergreen while the
history remains findable.

| Reference | Date | What happened / what it drove |
|-----------|------|-------------------------------|
| [#76](https://github.com/dan2bit/live-shows/issues/76) | 2026-06-27 | **Private-data leak incident.** An inbox routine wrote the private purchasing sidecar to a `live-shows-private/` folder inside this public repo instead of the separate private repo, exposing the cost/seat/qty/notes ledger. Removal required a git history rewrite + force-push. Drove the entire `staging` → `main` pipeline: the required `guard` status check (`private-data-guard.yml`), `auto-promote.yml`, and the deploy-key commit pattern used by all bots. |
| [#119](https://github.com/dan2bit/live-shows/issues/119) | — | Times Seen drift between `artists.tsv` and the canonical ledger. Drove the blocking `audit-times-seen.yml` check. |
| [#131](https://github.com/dan2bit/live-shows/issues/131) | — | Photo URL integrity (item 4): every show Photo URL must match a Share Link row in `artist-photos.tsv`. Drove `reconcile-photos.yml` (CORRUPT fails, MISSING reports). |
| [#152](https://github.com/dan2bit/live-shows/issues/152) | — | Purchased shows reflected into potentials + fast_track + new-artist research. Drove the `reconcile_purchases.py` step in `potentials-maintenance.yml`. |
| [#186](https://github.com/dan2bit/live-shows/issues/186) | — | Box Office flag guardrail (warn-only). Drove the `check_box_office.py` step in `potentials-maintenance.yml`. |
