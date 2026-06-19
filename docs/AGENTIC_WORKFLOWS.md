# AGENTIC_WORKFLOWS.md

> **Audience:** This document is Dan-specific and not part of the forkable template. It describes how agentic AI (Claude, via claude.ai Projects with MCP tool access) is used to manage the live-shows dataset. It is written as an annotated architecture reference for technically inclined forkers who want to build similar workflows — the patterns are general even when the specifics are Dan's.

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
    history/                  ← year TSVs (2021–2025)
    setlists/                 ← multi-setlist JSON (by year)

live-shows-private/ (private)
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

The system prompt (Claude Instructions, pinned to the Project) carries the standing rules, defaults, and schema knowledge so each session starts with full context. The memory system carries the dynamic facts that accumulate over time.

---

## Inbox + Data Sessions (Routines 1–5)

Triggered by: forwarded ticket receipts, post-show note emails, newsletter emails

Each routine follows a strict pre-flight + execute + label + log pattern defined in `tools/playbooks/EMAIL_WORKFLOWS.md`.

### Routine 1 — Ticket receipt

**Trigger:** Dan forwards ticket confirmation to rhbl inbox
**Data written:** `data/live_shows_current.tsv` (public), `current_private.tsv` (private), Google Calendar
**Key rules:** Venue defaults, autograph book check, Prev/Next bracket update in potentials

### Routine 2 — Post-show notes

**Trigger:** Dan sends post-show email to rhbl
**Data written:** `live-shows-private/spending.tsv`, `data/live_shows_current.tsv`, `artists.tsv`, optionally `autograph_books_combined.tsv`
**Key rules:** spending.tsv write is mandatory even if all zeros

### Routine 3 — Ticket alert newsletter

**Trigger:** Venue/artist newsletter tagged `ticket-alert`
**Data written:** `data/live_shows_potential.tsv` (after explicit confirmation), Google Calendar (on-sale events)
**Key rules:** Calendar conflict check before any recommendation; purchasing/fee notes go to `potential_private.tsv`

### Routine 4 — Artist newsletter

**Trigger:** Email tagged `artist-mail`
**Data written:** `data/live_shows_potential.tsv` (after confirmation), Google Calendar
**Key rules:** Same calendar conflict rule as Routine 3

### Routine 5 — Artist follow / signup

**Trigger:** BIT/Songkick alert or artist mailing list signup response, tagged `artist-follow`
**Data written:** `tools/research/follows/follows_master.tsv`, `data/live_shows_potential.tsv` (after confirmation)
**Key rules:** Reminder suppression if show already in current or potentials; BIT “Just Announced” requires full HTML parse

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
**Code files:** `index.html`, `app.js`, `recommend.js`, `styles.css`, `scripts/`

Key safety rule: always fetch live file from repo before patching; show diff before committing; verify line count reduction < 10% before pushing any JS/CSS file.

---

## Strategy Sessions

Triggered by: artist research, follow tier decisions, discovery workflows, architecture planning

**Data sources read:** `live_shows_history.tsv`, `live_shows_potential.tsv`, `artists.tsv`, `tools/research/follows/` directory
**Data written:** Claude's memory system (persistent cross-session summaries), `tools/research/follows/new_artist_research.tsv`

Strategy sessions use web search and Claude in Chrome for artist discovery (Gnoosic, festival lineups, award nominees).

---

## GitHub Actions (CI)

Five workflows run on push to main:

| Workflow | Trigger | Action |
|---|---|---|
| `validate-current` | `data/live_shows_current.tsv` | Schema + sentinel check |
| `potentials-maintenance` | `data/live_shows_potential.tsv` or `data/live_shows_current.tsv` | Prune past-dated rows, check brackets |
| `recommend-index` | Source TSVs or `scripts/build_recommend_index.py` | Regenerate `data/recommend_index.json` |
| `cache-bust` | `app.js`, `recommend.js`, `styles.css` | Update `?v=` fingerprints in `index.html` |
| `close-playlist-issue` | Issue comment containing YouTube playlist URL | Write URL to `data/live_shows_current.tsv` |

All bot commits use `[skip ci]` sentinel. All bot workflows use `git pull --rebase` before push to prevent bot-vs-bot race conditions.

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