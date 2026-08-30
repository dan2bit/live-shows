# AGENTIC_WORKFLOWS.md

> **Audience:** This document is Dan-specific and not part of the forkable template. It describes how agentic AI (Claude, via claude.ai Projects with MCP tool access) is used to manage the live-shows dataset. It is written as an annotated architecture reference for technically inclined forkers who want to build similar workflows — the patterns are general even when the specifics are Dan's.

The issue numbers and incident history behind these designs are logged in
[`ISSUE_LOG.md`](ISSUE_LOG.md).

---

## Overview

The live-shows system uses three types of agentic Claude sessions, each with a dedicated context-setting prompt:

| Session type | Trigger | Key tools |
|---|---|---|
| **Inbox + Data** | Email arrives | Gmail MCP, GitHub MCP, Google Calendar MCP |
| **Site + Repo** | Code change needed | GitHub MCP, bash |
| **Strategy** | Research / planning | GitHub MCP, web search, Claude in Chrome |

Each session type has a prompt in the Claude Project that sets the operational context: which repo, which files, which rules, which schema. The Project memory carries dynamic facts across sessions.

---

## Architecture

### Data layer

All canonical data lives in the GitHub repo. The site reads it via the GitHub API. No separate database.

```
live-shows/ (public)
  data/
    live_shows_current.tsv    ← attended + upcoming shows
    live_shows_potential.tsv  ← Buy/Choose/Sell/Pass
    artists.tsv               ← artist history + Spotify/YouTube
    fast_track.tsv            ← auto-buy artists
    venues.tsv                ← venue metadata
    recommend_aliases.tsv     ← surface form overrides
    recommend_index.json      ← generated lookup index
    artist_modal_index.json   ← generated artist-modal payload
    artist_spotify.json       ← Spotify/last.fm enrichment cache
    history/                  ← year TSVs (2021–2025)
    setlists/                 ← multi-setlist JSON (by year)
    show_goals/               ← goal eligibility files + signature event logs
                                (see docs/GOALS_SPEC.md)

live-shows-private/ (private repo — dan2bit/live-shows-private)
  current_private.tsv         ← cost/seat/qty per show
  potential_private.tsv       ← private notes per potential
  fast_track_caps.tsv         ← per-artist cap overrides
  spending.tsv                ← spending authority
```

The `tools/` directory contains Dan-only pipeline files: YouTube scripts, follow lists, playbooks, personal data. None of it is read by the site.

### Auth layer

The site has two modes:
- **Public (unauthenticated):** reads all public data, shows bystander UI
- **Authed (PAT in local storage):** merges private sidecar data, shows edit controls

The PAT is a fine-grained GitHub token scoped to `live-shows` + `live-shows-private` with Contents + Issues read/write.

### Agentic layer

Claude sessions operate via MCP tools:
- **Gmail MCP** — search threads, read bodies, label threads, create drafts
- **GitHub MCP** — read/write files, open issues/PRs, list commits
- **Google Calendar MCP** — create/update events, check availability
- **bash** — fetch files, run scripts, diff content

**A tool operating on a resource is not the same as that tool understanding the
resource's conventions.** `github:issue_write`, for instance, can create or update
any issue, but it has no notion of `.github/ISSUE_TEMPLATE/` — unlike the GitHub
web UI's "New Issue" picker, it will not offer or apply a template. Any Claude
workflow that produces a templated artifact (an issue, a file with a fixed schema,
etc.) is responsible for fetching the template/schema live and filling it in itself;
the MCP tool layer does not do this for you. See the playlist-issue template-fetch
rule under Routine 2 below for the concrete instance that motivated writing this
down.

The system prompt (Claude Instructions, pinned to the Project) carries the standing rules, defaults, and schema knowledge so each session starts with full context. The memory system carries the dynamic facts that accumulate over time.

---

## Inbox + Data Sessions (Routines 1–6)

Triggered by: forwarded ticket receipts, post-show note emails, newsletter emails, resale sale notifications

These sessions are launched by the `live-shows-inbox` Claude Skill
(`tools/playbooks/skills/live-shows-inbox/SKILL.md`) - it establishes the
current date, fetches live current/potential state, runs a read-only triage
snapshot across all six routine queues (depth, staleness, missing show-notes
and ticket-receipt nudges), and reports a recommended run order before any
routine actually executes.

Each routine follows a strict pre-flight + execute + label + log pattern defined in `tools/playbooks/EMAIL_WORKFLOWS.md`.

### Routine 1 — Ticket receipt

**Trigger:** Dan forwards ticket confirmation to rhbl inbox
**Data written:** `data/live_shows_current.tsv` (public → `staging`), `dan2bit/live-shows-private → current_private.tsv` (private → private repo `main`), Google Calendar
**Key rules:** Venue defaults, autograph book check, Prev/Next bracket update in potentials

### Routine 2 — Post-show notes

**Trigger:** Dan sends post-show email to rhbl
**Data written:** `dan2bit/live-shows-private → spending.tsv`, `data/live_shows_current.tsv` (→ `staging`), `artists.tsv` (→ `staging`), optionally `data/show_goals/book_signatures.tsv` (book) / `data/show_goals/hat_signatures.tsv` (hat), and a `playlist`-labeled issue (+ `photo`-labeled issue if applicable)
**Key rules:** spending.tsv write is mandatory even if all zeros. The `playlist`/`photo` issue bodies must be built from a **live fetch of the matching `.github/ISSUE_TEMPLATE/*.md` file**, never reconstructed from memory or a prior issue — see `EMAIL_WORKFLOWS.md` → Routine 2 Step 6 for the full procedure and the incident (#296/#297/#300/#308) that made this explicit.

### Routine 3 — Ticket alert newsletter

**Trigger:** Venue/artist newsletter tagged `ticket-alert`
**Data written:** `data/live_shows_potential.tsv` (→ `staging`, after explicit confirmation), Google Calendar (on-sale events)
**Key rules:** Calendar conflict check before any recommendation; purchasing/fee notes go to `dan2bit/live-shows-private → potential_private.tsv`

### Routine 4 — Artist newsletter

**Trigger:** Email tagged `artist-mail`
**Data written:** `data/live_shows_potential.tsv` (→ `staging`, after confirmation), Google Calendar
**Key rules:** Same calendar conflict rule as Routine 3

### Routine 5 — Artist follow / signup

**Trigger:** BIT/Songkick alert or artist mailing list signup response, tagged `artist-follow`
**Data written:** `tools/research/follows/follows_master.tsv` (→ `staging`), `data/live_shows_potential.tsv` (→ `staging`, after confirmation)
**Key rules:** Reminder suppression if show already in current or potentials; BIT "Just Announced" requires full HTML parse

### Routine 6 — Ticket sold (resale)

**Trigger:** Email tagged `ticket-sold` (forwards from dan2bit@gmail.com with `sold` in subject)
**Data written:** `data/live_shows_current.tsv` (→ `staging`, remove/update row), `dan2bit/live-shows-private → current_private.tsv` (remove/update), `dan2bit/live-shows-private → spending.tsv` (negative cost row), Google Calendar (delete event)
**Key rules:** Rarest routine; records net proceeds as a negative Ticket Cost in spending.tsv to offset the original purchase

---

## Recommendation Issues

The `recommend.js` frontend allows visitors to submit artist or show recommendations as GitHub issues (label: `recommendation`). These are processed in Inbox+Data sessions:

1. Read the issue
2. Research the artist (web search, Spotify, YouTube, BIT)
3. Assign a follow tier or mark as pass
4. Add to `tools/research/follows/follows_master.tsv` if actionable
5. Comment on the issue with the decision and close

---

## Site + Repo Sessions

Triggered by: code changes, PR reviews, issue work

**Data sources read:** `data/live_shows_current.tsv`, `data/live_shows_potential.tsv`, `data/fast_track.tsv`, `data/venues.tsv`
**Code files:** `index.html`, `app.js`, `recommend.js`, `artist-modal.js`, `styles.css`, `scripts/`

Key safety rule: always fetch live file from repo before patching; show diff before committing; verify line count reduction < 10% before pushing any JS/CSS file.

---

## Strategy Sessions

Triggered by: artist research, follow tier decisions, discovery workflows, architecture planning

**Data sources read:** `data/history/*.tsv`, `data/live_shows_potential.tsv`, `data/artists.tsv`, `tools/research/follows/` directory
**Data written:** Claude's memory system (persistent cross-session summaries), `tools/research/follows/new_artist_research.tsv`

Strategy sessions use web search and Claude in Chrome for artist discovery (Gnoosic, festival lineups, award nominees).

---

## Repo Management

### Branch pipeline

`main` has a required `guard` CI status check — **direct pushes to `main` are
rejected by branch protection**. The correct flow for all commits:

1. Commit to **`staging`** branch
2. `auto-promote.yml` fires on push to `staging`, re-runs `private-data-guard`, and
   fast-forwards `main` via the `PROMOTE_DEPLOY_KEY` deploy key if clean
3. A commit that fails the guard is reset off `staging` and never reaches `main`

**`push_files` promotes normally:** the multi-file Git Data API fires the `push`
trigger on `staging` like any other push — batches auto-promote with no follow-up
commit (verified 2026-08-24).

**In-page UI writes also ride `staging`:** the authenticated browser editor
(decision changes, notes edits, revokes, config saves) reads `site.data_branch`
from `config.yaml` via `dataBranch()` in `app.js` and targets that branch in
every public-repo PUT, so in-page writes flow through the same
staging → guard → auto-promote pipeline. Private sidecar writes are unaffected —
they target the private repo's `main` directly.

Private sidecar TSVs (`dan2bit/live-shows-private`) are committed directly to that
repo's `main`. The private repo does not use the staging pipeline.

Full commit-target table: see `tools/playbooks/DATA_WRITE_PROTOCOLS.md`.

### CI workflows

The full, current catalog — triggers, behavior, and conventions — lives in
[`.github/workflows/README.md`](../.github/workflows/README.md). Summary:

| Group | Workflows |
|---|---|
| Pipeline & gating | `private-data-guard`, `auto-promote` |
| Generated-output bots | `artist-modal-index`, `recommend-index`, `cache-bust`, `potentials-maintenance` |
| Issue-driven bots | `close-playlist-issue`, `close-photo-issue` |
| Read-only checks | `validate-current`, `audit-times-seen`, `reconcile-photos` |

`close-playlist-issue` and `close-photo-issue` both parse the issue body/comment
against the structure their respective `.github/ISSUE_TEMPLATE/*.md` file defines
(e.g. the `Playlist: <url>` line the closer looks for in the body). An issue whose
body drifted from the current template — see the Routine 2 note above — doesn't
just look wrong to Dan; it risks not matching what these bots expect either, on
top of missing pipeline steps. Both failure modes trace to the same root cause
(the issue wasn't built from a live template fetch) and the same fix.

Bot commits do **not** use `[skip ci]` — auto-promote is wanted; retrigger loops
are prevented by excluding each bot's output file from its own trigger paths.
All bot pushes rebase onto `staging` before pushing to prevent bot-vs-bot races.

**`cache-bust` note:** fires on any of the four JS/CSS files (`app.js`,
`recommend.js`, `artist-modal.js`, `styles.css`). After any cache-bust run,
re-fetch `index.html`'s blob SHA before any subsequent `index.html` commit.

### PR strategy

Two lanes, decided by change depth:

**Staging auto-promote lane** — use for:
- TSV and data file writes (all routines)
- `index.html` changes
- `app.js` / `styles.css` / `recommend.js` / `artist-modal.js` typo fixes, config
  additions, and single-function changes where the full diff is reviewed in
  conversation before commit

**PR branch lane** — use for:
- JS logic changes spanning multiple functions or introducing new behavior
- All `.py` and `.sh` scripts (Dan merges)
- Any change where a staging rollback would be disruptive

**`github:create_branch` fails reliably via MCP** — branch creation must be done
manually by Dan. When a PR branch is needed, state that clearly and wait for Dan to
create it before proceeding.

A long-running `dev` branch was considered and **rejected as not useful at this
stage of the project** (see `ISSUE_LOG.md`). The two-branch model above
(`staging` → `main`) stands; the `?dataref` / `site.data_branch` override design
proceeds against the transient/PR-branch model described in `PR strategy` above,
not a long-running integration branch.

---

## Memory System

Claude Projects memory carries:
- Current potentials state (Buy/Choose/Sell/Pass with dates)
- Recent hat autograph records
- Key follow tier decisions
- Schema change history (privacy split, data/ move, etc.)
- Active strategic threads

Memory updates happen via the `memory_user_edits` tool. Sensitive content (health, finances, personal crises) is excluded from memory.

---

## Invocation Patterns

The workflows are invoked conversationally — "run Routine 3" or "process inbox" — rather than through scripts or cron jobs. This keeps the human in the loop at each step and makes it easy to deviate from the routine when something unexpected comes up.
