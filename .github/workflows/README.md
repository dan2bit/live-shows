# Workflows

## The `staging` → `main` pipeline

`main` requires the `guard` status check (the private-data backstop),
so nothing is pushed to `main` directly. All commits land on `staging`.

`auto-promote.yml` runs on every push to `staging`: it re-runs the private-data
guard and, only if clean, fast-forwards `main` using the `PROMOTE_DEPLOY_KEY`
deploy key — the sole ruleset bypass actor. A failing commit is reset off
`staging` (force-reset to `origin/main`) and never reaches `main`.

The bots that commit generated output (`cache-bust`, `artist-modal-index`,
`recommend-index`, `potentials-maintenance`, `close-photo-issue`,
`close-playlist-issue`) therefore push to `staging` via that same deploy key —
a `GITHUB_TOKEN` push would not trigger `auto-promote`. None use `[skip ci]`:
auto-promote is *wanted*. Each bot's output file is excluded from its own
trigger paths, so promotion back to `main` does not retrigger it.

Writing via MCP: push to `staging` and let `auto-promote` carry it to `main`.
A multi-file Git Data API commit (`push_files`) does not fire the `push`
trigger; use a single-file `create_or_update_file` commit to nudge promotion.

The issue numbers and incident history behind these designs are logged in
[`docs/ISSUE_LOG.md`](../../docs/ISSUE_LOG.md).

## Workflow catalog

### Pipeline & gating

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `private-data-guard.yml` | every push & PR | **The required `guard` check on `main`.** Fails any commit that introduces private sidecar paths (`live-shows-private/`, `*_private.tsv`, `*_caps.tsv`) or a TSV with a `Private Notes` header into this public repo. Backstop for the private-data leak incident (see `docs/ISSUE_LOG.md`). |
| `auto-promote.yml` | push to `staging` | Mirrors the guard, then fast-forwards `main` via `PROMOTE_DEPLOY_KEY`. On guard failure, force-resets `staging` back to `origin/main` so the bad commit never promotes. |

### Generated-output bots (commit to `staging` via deploy key)

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `artist-modal-index.yml` | push to `main` touching any artist-modal payload/score source (config, core TSVs, `show_goals`, `artist_spotify.json`, aliases, `follows_master.tsv`, the builder script) | Runs `scripts/build_artist_index.py` and commits a regenerated `data/artist_modal_index.json` if changed. |
| `recommend-index.yml` | push to `main` touching recommend-index sources (artists, fast_track, potentials, follows, aliases, the builder script) | Runs `scripts/build_recommend_index.py` and commits a regenerated `data/recommend_index.json` if changed. |
| `cache-bust.yml` | push to `main` touching `app.js`, `recommend.js`, `artist-modal.js`, or `styles.css` | Rewrites the `?v=` query strings on those assets in `index.html` to the current short SHA, forcing browser/CDN refresh. |
| `potentials-maintenance.yml` | push to `main` touching potentials or current TSVs | Runs `reconcile_purchases.py` (purchased shows reflected into potentials + fast_track + new-artist research) and `prune_potentials.py` (drops past-dated Pass rows), commits if changed; then warn-only checks: `check_brackets.py` (Prev/Next brackets) and `check_box_office.py` (Box Office flag guardrail). Idempotent on the promote-back retrigger. |

All four use the same push loop: rebase onto `promote/staging`, push, retry up
to 5× with backoff on races; bail on a real rebase conflict.

### Issue-driven bots

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `close-playlist-issue.yml` | comment containing a `youtube.com/playlist` URL on an issue titled `Playlist:…` | Extracts the ISO show date from the title and the playlist URL from the comment, writes the URL into `data/live_shows_current.tsv` via `scripts/close_playlist_issue.py`, commits to `staging`, closes the issue. |
| `close-photo-issue.yml` | comment containing a `photos.google.com/share` link on an issue titled `Photo:…` | Appends a row to `data/show_goals/artist-photos.tsv` via `scripts/close_photo_issue.py`, commits to `staging`, closes the issue. |

### Read-only checks (no commits; run on `main` post-promotion)

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `validate-current.yml` | push to `main` touching `live_shows_current.tsv` | `scripts/validate_current.py` — 19-column count and sentinel validation. |
| `audit-times-seen.yml` | push to `main` touching ledger sources | `scripts/audit_times_seen.py` — blocking check that artists.tsv "Times Seen" equals the canonical ledger count from the artist-index builder. |
| `reconcile-photos.yml` | push to `main` touching show TSVs or `artist-photos.tsv` | `scripts/reconcile_photos.py`: every show Photo URL must match a Share Link row keyed on the Google Photos `/photo/<ID>`. CORRUPT (near-miss ID) fails; MISSING only reports. |

## Conventions

- **Secrets:** `PROMOTE_DEPLOY_KEY` (SSH deploy key, ruleset bypass) is the only
  custom secret; everything else uses `GITHUB_TOKEN`.
- **Concurrency:** every committing workflow has its own `concurrency` group
  with `cancel-in-progress: false` so runs queue rather than clobber.
- **Race safety:** all bot pushes `git pull --rebase`/rebase before `git push`
  to prevent bot-vs-bot races.
- **Retrigger safety:** each generator's output file is deliberately absent
  from its own `paths:` filter; maintenance jobs are idempotent on the second
  (post-promotion) run.
- **`workflow_dispatch`:** every scheduled/path-triggered workflow can also be
  run manually from the Actions tab.
