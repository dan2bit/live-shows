# live-shows — Data Schemas & Repo Conventions

Reference for the data-file layouts and the repository/commit conventions used when editing this project with Claude. Operational procedures live in the workflow docs (see `README.md` for the map); this file should rarely need updating.

---

## Data file schemas

### live_shows_current.tsv — 26 columns

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
10. Seat Info / GA
11. Ticket Access
12. Ticket Quantity
13. Face Value (per ticket)
14. Fees
15. Total Cost
16. Purchase Date
17. Setlist.fm URL
18. Status
19. Food & Bev
20. Parking
21. Merch
22. Artist Interaction
23. Playlist URL
24. Notes / Memories
25. Private Notes
26. Photo URL

**Multi-act shows:** when a date has multiple performers, column 17 (Setlist.fm URL) holds `MULTI:YYYY-MM-DD`, and the per-act setlist links live under that date key in `setlists/<year>.json` (split by year, named for the show’s year) — support acts first, headliner last.

**Known issue — trailing-tab strip:** the GitHub MCP `create_or_update_file` tool strips trailing tabs from each line, so rows that end in empty columns can arrive short. The `parseTsv()` function in `index.html` compensates at parse time by padding/realigning rows back to the full column count.

### live_shows_potential.tsv — 17 columns

`Artist | Support | Date | Decision | Watching For | Venue | Venue City | Tier | Ticket Service | Purchase URL | Event URL | Face Price | Fees Notes | Availability Notes | Prev Show | Next Show | Notes`

- **Decision values:** `Buy`, `Buy (paper @ [show])`, `Choose`, `Sell`, `Pass`. Never leave Decision blank — use `Choose` for undecided.
- **Sort:** Buy → Choose → Sell → Pass (alpha within group), date ascending within each group. Re-sort the full file on every change.
- **Prev/Next Show brackets:** reference only purchased upcoming shows (status `upcoming` in `live_shows_current.tsv`) — never potentials, never attended shows. Re-check on every purchase or move to attended.
- **`Sell`** is read-only — set when a confirmed ticket is listed for resale; not editable via the index.html dropdown.

### artists.tsv

One row per artist: Times Seen, First Seen, Most Recent Seen, YouTube Channel, Spotify URL, Photo (Y), Book Autograph (Y), Hat Autograph (Y), VIP Count.

### venues.tsv

One row per venue: parking, transit, seating, box office hours, notes. Canonical source for venue defaults.

---

## Repository & commit conventions

- **Non-executable files** (`.tsv`, `.json`, `.md`, `index.html`, config) → commit directly to `main` via MCP `create_or_update_file`. The official MCP binary handles Unicode correctly.
- **Executable scripts** (`.py`, `.sh`, `.js`) → PR branch; Dan merges.
- **index.html** → simple/non-logic edits may commit directly to `main`; significant logic changes go via a PR branch.
- Always **fetch a fresh SHA** immediately before each `create_or_update_file` call — a SHA from earlier in the session is stale after any intervening commit to that file.
- Always **push full file content** — never targeted/patch commits (they have clobbered files).
- **Large files (50KB+)** commit fine via `create_or_update_file` — attempt it first; fall back to manual check-in only if it fails.
- Use `delete_file` to remove a file. Avoid `push_files` with empty content (it silently commits empty blobs).
- **No commits without explicit confirmation from Dan.**

---

## Artist interaction

- **Hat signing:** female musicians only. Do not infer gender across all `artists.tsv` entries — apply only when context makes it clear (e.g., during show processing or explicit mention).
- **Autograph book check:** required before creating any new calendar event.
- **Artist Interaction values:** `Photo`, `Autograph`, `Both`, or blank.
- **`HAT:` flag:** prefix Notes / Memories in upcoming and potential rows to trigger the 🎩 badge in `index.html`.

---

## Reference

- **Spending budget:** $500/month. Multi-ticket orders count 1 ticket against budget; extras tracked as "shared." Wolf Trap food/bev = $0 (Lary donor access).
- **YouTube channel:** `@dan2bit`, OAuth under `dan2bit@gmail.com` (not `redhat.bootlegs`). See `HOWTO_CHANNEL.md`.
- **Key people:** Lary Chinowsky (frequent companion; Wolf Trap donor; recommendations), Jennifer (occasional companion), Bob Lubbehusen, Ed Warburton, Steve Goodman (blues-community contacts; recommendations), Joe Murphy (Friday Night Tunes DJ, tastemaker)
