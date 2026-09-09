# live-shows — Data Schemas & Repo Conventions

Machine-facing reference for the data files and commit rules. Prose explanations of
*why* live in the playbooks; this file is the lookup table.

---

## Data file schemas

### live_shows_current.tsv — 19 columns (public schema)

| # | Column |
|---|---|
| 0 | Show ID |
| 1 | Artist |
| 2 | Supporting Artist |
| 3 | Show Date |
| 4 | Doors Time |
| 5 | Start Time |
| 6 | Venue Name |
| 7 | Venue Address |
| 8 | Venue Event URL |
| 9 | Seat Type (`GA` \| `Seated`) |
| 10 | VIP (`Y` \| blank) |
| 11 | Group (`Y` \| blank) |
| 12 | Ticket Access |
| 13 | Setlist.fm URL |
| 14 | Status (`upcoming` \| `attended`) |
| 15 | Artist Interaction |
| 16 | Playlist URL |
| 17 | Notes / Memories |
| 18 | Photo URL |

Cost, seat info, ticket quantity and private notes live in
`dan2bit/live-shows-private → current_private.tsv`, keyed on **Show Date + Artist**.

Upcoming rows carry `-` sentinels in Setlist.fm URL (13) and Playlist URL (16).
`validate_current.py` enforces the column count, the status vocabulary, the flag
columns and those sentinels.

### live_shows_potential.tsv — 19 columns (public schema)

| # | Column |
|---|---|
| 0 | Artist |
| 1 | Support |
| 2 | Date |
| 3 | Decision (`Buy` \| `Choose` \| `Sell` \| `Pass`) |
| 4 | Watching For |
| 5 | Venue |
| 6 | Venue City |
| 7 | Tier |
| 8 | Ticket Service |
| 9 | Purchase URL |
| 10 | Event URL |
| 11 | Face Price |
| 12 | Fees Notes |
| 13 | Availability Notes |
| 14 | Prev Show (2026) |
| 15 | Next Show (2026) |
| 16 | Notes |
| 17 | BIT URL |
| 18 | Box Office |

Sort order: `Buy` → `Choose` → `Sell` → `Pass`, date ascending within each group;
re-sort on every change. Prev/Next brackets are computed for `Buy`/`Choose` from
purchased **upcoming** shows only and cleared to `-` on `Sell`/`Pass` — see
`reconcile_purchases.py`, the canonical implementation. Private notes live in
`dan2bit/live-shows-private → potential_private.tsv`, keyed on **Artist + Date**.

Never reintroduce a `#` comment block: the in-page editor derives its header from
line 1, so a comment block wipes every row on save.

### artists.tsv — 9 columns

Artist | Times Seen | First Seen | Most Recent Seen | Spotify URL | YouTube Channel |
Hat Autograph (deprecated) | Notes | Portrait URL

Never reconstruct this file from memory — fetch it live, make targeted string
replacements, and push full content.

### venues.tsv

Canonical venue names plus a Short Name display column and a Calendar Coverage
column that drives the monthly scrape set. Blank Short Name means identity.

### data/show_goals/

Eligibility and signature files per goal (hat, autograph books). Eligibility answers
"meets the criteria"; signatures answer "already obtained". A signature never removes
eligibility — completed wins at render time.

---

## Repository & commit conventions

### staging → main pipeline

`main` requires the `guard` CI status check. **Do not push directly to `main` via MCP — it will be rejected.** All MCP data commits go to `staging`; `auto-promote.yml` fast-forwards `main` after the guard passes.

**`push_files` promotes normally:** the multi-file Git Data API fires the `push` trigger on `staging` like any other push — batches auto-promote with no follow-up commit (verified 2026-08-24).

**A blob SHA is only valid on the branch it was read from.** `main` and `staging` are usually identical, so a SHA read from one works against the other — until a bot commit lands on `staging` and `main` lags for as long as auto-promote takes to re-run the guard and fast-forward. Any write that reads a SHA from one branch and PUTs it to another races that window, and the failure is a bare 409 that looks like a permissions problem. This is why the in-page editor fetches write SHAs with `?ref=dataBranch()` rather than through the read path, whose preview ref resolves to the default branch. Reads may target any branch; a write must read from the branch it writes to.

### File-type rules

- **Public non-executable files** (`.tsv`, `.json`, `.md`, `index.html`, config) → commit to `staging` in `dan2bit/live-shows` via MCP.
- **Private sidecar TSVs** → commit to **`main`** in `dan2bit/live-shows-private` via MCP. (The private repo does not use the staging pipeline.)
- **Executable scripts** (`.py`, `.sh`, `.js`) → PR branch; Dan merges.
- **index.html** → simple/non-logic edits commit to `staging`; significant logic changes go via a PR branch.
- Always **fetch a fresh SHA** immediately before each `create_or_update_file` call — a SHA from earlier in the session is stale after any intervening commit to that file.
- Always **push full file content** — never targeted/patch commits (they have clobbered files).
- **Large files (50KB+)** commit fine via `create_or_update_file` — attempt it first; fall back to manual check-in only if it fails.
- **No commits without explicit confirmation from Dan.**

### Private file notation

Throughout this project, private files are written as **`dan2bit/live-shows-private → <file>`** — meaning the file `<file>` at the root of the separate private repo. Never a path inside `dan2bit/live-shows`. See the project instructions CRITICAL section for the full boundary rules.

---

## Artist interaction

Hat signing targets female musicians who have not already signed. Eligibility lives in
`data/show_goals/hat_eligibility.tsv`; actual signers in
`data/show_goals/hat_signatures.tsv`, which is canonical. The `artists.tsv` Hat
Autograph column is deprecated — do not set it.

Autograph books follow the same eligibility/signatures split via
`autograph_books_eligibility.tsv` and `book_signatures.tsv`. There is no combined file.

Artist Interaction field values: `Photo`, `Autograph`, `Both`, or blank.

---

## Reference

- Write protocols and per-file transaction rules: `tools/playbooks/DATA_WRITE_PROTOCOLS.md`
- Inbox routines: `tools/playbooks/EMAIL_WORKFLOWS.md`
- Analysis and monthly passes: `tools/playbooks/ANALYSIS_WORKFLOWS.md`
- Scrape prompts and endpoints: `tools/research/web-src/scraping_tasks.md`
- Issue history behind these designs: `docs/ISSUE_LOG.md`
