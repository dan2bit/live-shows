# live-shows — Data Schemas & Repo Conventions

Reference for the data-file layouts and the repository/commit conventions used when editing this project with Claude. Operational procedures live in the workflow docs (see `README.md` for the map); this file should rarely need updating.

---

## Data file schemas

### live_shows_current.tsv — 19 columns (public schema)

Rows are `attended` or `upcoming`, ordered chronologically by Show Date.

1. Show ID
2. Artist
3. Supporting Artist
4. Show Date
5. Doors Time
6. Start Time
7. Venue Name
8. Venue Address
9. Venue Event URL
10. Seat Type (`GA` | `Seated`)
11. VIP (`Y` or blank)
12. Group (`Y` or blank)
13. Ticket Access
14. Setlist.fm URL
15. Status
16. Artist Interaction
17. Playlist URL
18. Notes / Memories
19. Photo URL

Financial and seat detail (Seat Info, Ticket Quantity, Face Value, Fees, Total Cost, Purchase Date, Food & Bev, Parking, Merch, Private Notes) lives in `dan2bit/live-shows-private → current_private.tsv`, keyed by `Show Date` + `Artist`.

**Multi-act shows:** when a date has multiple performers, column 14 (Setlist.fm URL) holds `MULTI:YYYY-MM-DD`, and the per-act setlist links live under that date key in `setlists/<year>.json` — support acts first, headliner last.

**Known issue — trailing-tab strip:** the GitHub MCP `create_or_update_file` tool strips trailing tabs from each line, so rows that end in empty columns can arrive short. The `parseTsv()` function in `index.html` compensates at parse time by padding/realigning rows back to the full column count.

### live_shows_potential.tsv — 19 columns (public schema)

`Artist | Support | Date | Decision | Watching For | Venue | Venue City | Tier | Ticket Service | Purchase URL | Event URL | Face Price | Fees Notes | Availability Notes | Prev Show | Next Show | Notes | BIT URL | Box Office`

- **Decision values:** `Buy`, `Buy (paper @ [show])`, `Choose`, `Sell`, `Pass`. Never leave Decision blank — use `Choose` for undecided.
- **Sort:** Buy → Choose → Sell → Pass (alpha within group), date ascending within each group. Re-sort the full file on every change.
- **Prev/Next Show brackets:** reference only purchased upcoming shows (status `upcoming` in `live_shows_current.tsv`) — never potentials, never attended shows. Re-check on every purchase or move to attended.
- **`Sell`** is read-only — set when a confirmed ticket is listed for resale; not editable via the index.html dropdown.
- **Tier** uses the follows_master vocabulary (`Strong`, `Medium-Strong`, `Medium`, `Lower`/`Low`) — cross-reference `tools/research/follows/follows_master.tsv` rather than writing `TBD` for artists already tiered there.
- **Pricing is public here by design:** what a potential ticket *costs* (Face Price, Fees Notes) is public; what was actually *spent* on purchased shows is private.
- **No Private Notes column** — private notes go to `dan2bit/live-shows-private → potential_private.tsv`, keyed by `Artist` + `Date`.

### artists.tsv — 9 columns

`Artist | Times Seen | First Seen | Most Recent Seen | YouTube Channel | Spotify URL | Book Autograph | VIP Count | Via`

- **Via** attributes combined-bill sightings (e.g. Joe Satriani via `SatchVai Band`, Taj Mahal via `TajMo`) — the builder borrows the bill's sightings for the component artist.
- Photo and hat completions are **not** columns here — they derive from Photo URLs on show rows and `data/show_goals/hat_signatures.tsv` respectively (see `docs/GOALS_SPEC.md`).

### venues.tsv

One row per venue: parking, transit, seating, box office hours, notes. Canonical source for venue defaults.

### data/show_goals/

Goal eligibility files (`hat_eligibility.tsv`, `autograph_books_eligibility.tsv`) and signature event logs (`hat_signatures.tsv`, `book_signatures.tsv`), plus photo album mappings (`artist-albums.tsv`, `artist-photos.tsv`). Schemas and the attribution vocabulary are specified in `docs/GOALS_SPEC.md`.

---

## Repository & commit conventions

### staging → main pipeline

`main` requires the `guard` CI status check. **Do not push directly to `main` via MCP — it will be rejected.** All MCP data commits go to `staging`; `auto-promote.yml` fast-forwards `main` after the guard passes.

**`push_files` quirk:** `push_files` (multi-file Git Data API) does **not** fire the `push` trigger on `staging` and therefore does **not** auto-promote. After a `push_files` call, follow up with a single-file `create_or_update_file` nudge commit to `staging` to trigger promotion — or use sequential `create_or_update_file` calls instead.

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

- **Hat signing:** female musicians only. Do not infer gender across all `artists.tsv` entries — apply only when context makes it clear (e.g., during show processing or explicit mention).
- **Autograph book check:** required before creating any new calendar event.
- **Artist Interaction values:** `Photo`, `Autograph`, `Both`, or blank.
- **Goal badges are config-driven** from `data/show_goals/` event logs and eligibility files (see `docs/GOALS_SPEC.md`) — the site no longer parses note-strings. `HAT:` / `BRING RHBS` / `BRING APS` prefixes in Notes remain as inert human reminders only (and in calendar event descriptions).

---

## Reference

- **Spending budget:** $500/month. Multi-ticket orders count 1 ticket against budget; extras tracked as "shared." Wolf Trap food/bev = $0 (Lary donor access).
- **YouTube channel:** `@dan2bit`, OAuth under `dan2bit@gmail.com` (not `redhat.bootlegs`). See `HOWTO_CHANNEL.md`.
- **Key people:** Lary Chinowsky (frequent companion; Wolf Trap donor; recommendations), Jennifer (occasional companion), Bob Lubbehusen, Ed Warburton, Steve Goodman (blues-community contacts; recommendations), Joe Murphy (Friday Night Tunes DJ, tastemaker)
