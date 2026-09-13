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
| `close-photo-issue.yml` | owner comment **beginning with** a `photos.redhat-bootlegs.net/share/` link on an issue titled `Photo:…` | `scripts/close_photo_issue.py` → `show_photos.add_asset()`: tags the photo, files it in its show / artist / kind albums (creating and link-minting as needed), writes the show-album link to the show row and the artist-album link to `data/show_goals/artist-albums.tsv`, commits to `staging`, closes the issue. Needs the `IMMICH_API_KEY` secret. |

### Scheduled digests (mail out; no commits)

Each builds a plain-text report from committed files and mails it to the project
inbox through `scripts/notify_email.py` (Resend, `RESEND_API_KEY`). None commits
anything, and none holds a calendar credential — conflict checks stay in
session.

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `weekly-potentials-digest.yml` | Monday 12:00 UTC | `scripts/potentials_digest.py` — sweeps the gap between a potentials row and the purchase: on-sale within 7 days, on-sale passed with the row still Buy/Choose, Buy rows whose show is inside 30 days with nothing purchased, Choose rows inside 14 days, and rows missing price or links. Read-only (`permissions: contents: read`); `--today` dispatch input for testing windows. |
| `weekly-hftb-diff.yml` | Friday 11:00 UTC | Re-scrapes HereForTheBands and diffs against last week's committed copy, then mails the report. This one *does* commit the refreshed scrape — see `tools/playbooks/ANALYSIS_WORKFLOWS.md` Workflow 1-W. |
| `refresh-releases.yml` | daily 06:47 UTC | Refreshes the Spotify release cache, then `scripts/release_digest.py` renders what the sweep found and mails it when there are hits. Commits the cache to `staging`. |

**All three are silent when there is nothing to report.** A digest that mails
weekly to say nothing happened is one you stop reading, so each either produces
an empty body — which `notify_email.py` refuses to send — or checks its own
counts before calling it. `refresh-releases` and `weekly-hftb-diff` need the
explicit count check because their reports always print a header.

**Digest steps run before their commit step** where both exist. `release_digest.py`
compares the working copy against `HEAD`, so a commit first would leave it
reporting nothing, every time, with no error.

### Read-only checks (no commits; run on `main` post-promotion)

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `validate-current.yml` | push to `main` touching `live_shows_current.tsv` | `scripts/validate_current.py` — 19-column count and sentinel validation. |
| `audit-times-seen.yml` | push to `main` touching ledger sources | `scripts/audit_times_seen.py` — blocking check that artists.tsv "Times Seen" equals the canonical ledger count from the artist-index builder. |
| `reconcile-photos.yml` | push to `main` touching show TSVs or the album TSVs | `scripts/reconcile_photos.py`: offline lint of every photo link — MALFORMED or DUPLICATE share key fails; OFF-HOST (a retired Google link) only reports. Server-side invariants are `tools/photos/show_photos.py audit`, run locally with the automation key. |

## Conventions

- **Secrets:** `PROMOTE_DEPLOY_KEY` (SSH deploy key, ruleset bypass),
  `IMMICH_API_KEY` (the least-privilege image-server key used only by
  `close-photo-issue.yml`; see `tools/playbooks/IMAGE_SERVER.md`) and
  `RESEND_API_KEY` (outbound mail for the digests above) are the custom
  secrets; everything else uses `GITHUB_TOKEN`. A job that holds a third-party
  key must gate on `github.event.comment.author_association == 'OWNER'`.
  `RESEND_API_KEY` can only push mail through Resend — it reads no mailbox, so
  it is not a send-as credential for the inbox it writes to. A digest job that
  finds it unset emits a `::warning::` naming the count that went unmailed
  rather than failing, so a missing secret never costs the run.
- **Concurrency:** every committing workflow has its own `concurrency` group
  with `cancel-in-progress: false` so runs queue rather than clobber.
- **Race safety:** all bot pushes `git pull --rebase`/rebase before `git push`
  to prevent bot-vs-bot races.
- **Retrigger safety:** each generator's output file is deliberately absent
  from its own `paths:` filter; maintenance jobs are idempotent on the second
  (post-promotion) run.
- **`workflow_dispatch`:** every scheduled/path-triggered workflow can also be
  run manually from the Actions tab.
