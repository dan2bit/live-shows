# Analysis Workflows — Live Show Archive

Five standing workflows for periodic show discovery, artist research, and data maintenance. These are independent of the email routines in `EMAIL_WORKFLOWS.md` — they run on a schedule (quarterly or monthly) or on demand.

---

## Workflow 1 — Monthly Web-Src Diff + BIT/Seated Roster Refresh

**Frequency:** Monthly (first weekend of the month)
**Tracked by:** GitHub Issue #42

### Purpose

Compare the current BIT/Seated follow roster against `tools/research/follows/follows_master.tsv` to catch:
- Artists added to BIT/Seated who are not yet in `follows_master.tsv`
- Artists in `follows_master.tsv` marked as BIT/Seated follows who are missing from the actual roster
- Any new web-src exports that differ from the cached copies

### Steps

1. **Export BIT and Seated rosters** from the respective apps/sites and save to `web-src/` with the current date in the filename.
2. **Diff the new exports** against the most recent previous exports:
   ```bash
   diff web-src/rhbl-bandsintown-PREV.tsv web-src/rhbl-bandsintown-NEW.tsv
   diff web-src/rhbl-seated-PREV.tsv web-src/rhbl-seated-NEW.tsv
   ```
3. **Reconcile against `tools/research/follows/follows_master.tsv`:**
   - For each new artist in the export not in follows_master: add a row with appropriate tier
   - For each artist missing from the export but marked Y in follows_master: investigate (unfollowed? account issue?)
4. **Update `tools/research/follows/follows_master.tsv`** as needed and commit.
5. **Close issue #42** with a comment summarizing changes, then reopen for next month.

---

## Workflow 2 — Quarterly Artist Research

**Frequency:** Quarterly (first run Jul 7, 2026)
**Sources:** Festival lineups, award nominees, Gnoosic

### Purpose

Discover new artists to follow. The primary sources are:
- Blues/Americana festival lineups (curated to taste profile)
- Award nominees (Blues Music Awards, Americana Music Awards)
- Gnoosic artist similarity engine

### Steps

#### Festival lineups

1. Identify 3–5 festivals curated to taste profile (blues, blues-rock, Americana, roots).
2. For each lineup, extract artist names.
3. For each artist not already in `tools/research/follows/follows_master.tsv` or `artists.tsv`:
   - Check `tools/research/follows/new_artist_research.tsv` — if present, review existing notes
   - If not present, add a pending-review row to NAR with Signal = `festival-lineup YYYY` and Source = festival name
4. Focus on artists appearing in multiple lineups or in lineups that have historically surfaced good matches.

#### Award nominees

1. Pull current year nominees for:
   - Blues Music Awards (BMA) — announced spring
   - Americana Music Awards — announced summer
2. For each nominee in categories relevant to taste (Contemporary Blues, Traditional Blues, Blues Artist, etc.):
   - Check against `tools/research/follows/follows_master.tsv` — note tier and surface show
   - Check against `tools/research/follows/new_artist_research.tsv` — note and surface
   - If not present in either, add to NAR with Signal = `award-nominee YYYY` and category as Source

#### Gnoosic

Gnoosic provides artist similarity discovery at `https://www.gnoosic.com/artist/[artist+name]`.

1. Use Claude in Chrome (agentic browsing) starting from `https://www.gnoosic.com/artist/larkin+poe`
2. For each recommended artist, evaluate against taste profile
3. Check against `tools/research/follows/follows_master.tsv` and `tools/research/follows/new_artist_research.tsv`
4. Add new discoveries to NAR

### NAR row format

```
Artist | Signal | Category | Official Site | Bandcamp | Overview & Niche | USA Touring | Most Recent Release | Status | Source
```

- Signal: source identifier (e.g. `festival-lineup 2026`, `gnoosic 2x unprompted`)
- Status: `pending-review` until evaluated
- Source: where discovered

---

## Workflow 3 — Fast Track Artist Tour Monitoring

**Frequency:** Weekly or on-demand (when expecting tour announcement)
**Sources:** `tools/research/follows/fast-track-artist-tour-pages.tsv`

### Purpose

Monitor tour page URLs for Fast Track artists — artists who would be immediate buys for any DMV date but whose shows don’t reliably surface via BIT/Seated/venue newsletters in time.

### Steps

1. Open all tour page URLs from `tools/research/follows/fast-track-artist-tour-pages.tsv`. Open all tabs at once before handing off to Claude in Chrome for review.
2. For each artist in `tools/research/follows/fast-track-artist-tour-pages.tsv`:
   a. Check the artist’s official tour page URL
   b. Look for DC/MD/VA dates not yet in `live_shows_potential.tsv` or `live_shows_current.tsv`
   c. If a new DMV date is found, surface it as a fast-track buy
3. Update the tour dates file:
   - 4. Overwrite the corresponding `tools/research/follows/fast-track-[artist]-tour-dates.tsv`
   - Note the scrape date in the file header

### Fast Track cap override

If a date exceeds a Fast Track cap (price, distance, venue size), present as a Choose potential instead, noting which cap was exceeded.

### Fast Track data file notes

Fast Track Artists data is stored in data/fast_track.tsv and loaded on demand on the Waiting tab
1. PURPOSE: Pre-authorized buy list for artists with sparse or no DC show history (or no headlining history) 
- where a local show should be treated as an immediate buy without going through the potential list evaluation cycle.
2. DISCIPLINE: This file is ONLY for artists who would NOT already be caught as a strong buy based on show history.
- If an artist has been seen multiple times or has a strong prior history (Kingfish, Larkin Poe, The Lone Bellow, ZZ Ward, etc.), 
- they do NOT belong here — they are handled automatically by the existing tier system.
3. FIRST TOUR: Y = artist has not yet toured DC/MD/VA region at all 
- (festivals, cruises, and award shows don't count).
-  Blank = has played the region, just haven't caught them.
4. Tour URL: artist's own tour page preferred; use BIT URL if no dedicated page.


---

## Workflow 4 — NAR Triage

**Frequency:** Quarterly or when NAR grows unwieldy
**Source:** `tools/research/follows/new_artist_research.tsv`

### Purpose

Review the `pending-review` rows in NAR and assign follow tiers or mark as pass.

### Steps

1. Filter NAR to `Status = pending-review`
2. For each artist, research:
   - Genre fit (blues, blues-rock, Americana, roots)
   - US touring activity
   - Recent releases
   - Online presence (official site, Spotify, YouTube)
3. Assign a tier (Strong, Medium-Strong, Medium, Low) or mark as pass
4. Update `Status` to `active` or `pass` and add research notes to Overview & Niche
5. For artists assigned a tier, add to `tools/research/follows/follows_master.tsv`

### Tier guidelines

- **Strong:** automatic buy for any DMV date at any in-scope venue; add to fast_track if not yet seen live
- **Medium-Strong:** buy for DC/MD/VA core venues; Hub City only if no closer date expected
- **Medium:** regional cap — pass on Hub City, wait for Rams Head/Hamilton/Birchmere/9:30
- **Low:** watch only; no active purchase intent

---

## Workflow 5 — Show History Integrity Check

**Frequency:** Ad hoc (before rollover, or when data anomalies are suspected)

### Purpose

Verify consistency between `live_shows_current.tsv`, `history/*.tsv`, and `artists.tsv`. Catch duplicate rows, missing artists entries, incorrect status flags.

### Steps

1. Run `scripts/validate_current.py` — checks column count and sentinel values
2. Check `artists.tsv` against show history:
   - Every artist with an attended row should appear in `artists.tsv`
   - Times Seen count should match the number of attended rows
3. Check for shows in `history/*.tsv` not in `artists.tsv` (pre-2021 shows may predate the tracking system)
4. Spot-check Setlist.fm URLs and Playlist URLs for 404s on a sample of rows
5. Report anomalies; do not auto-fix — present for manual review

### Note on history coverage

Pre-2021 show history (2002–2019) is tracked in a separate issue (#4). The `history/*.tsv` files currently cover 2021 onward. Do not attempt to reconstruct pre-2021 history from memory — source documents only.

---

## Workflow 6 — Gnoosic Discovery (Claude in Chrome)

**Status:** In progress — resume from `https://www.gnoosic.com/artist/larkin+poe`

Gnoosic provides semi-automatic artist discovery via URL syntax:
```
https://www.gnoosic.com/artist/[artist+name]
```

The discovery workflow uses Claude in Chrome to navigate the similarity graph, evaluate each recommended artist against taste profile, and feed new discoveries into `tools/research/follows/new_artist_research.tsv`.

**Interrupted at:** Larkin Poe (last session ended before completing the chain)
**Next step:** Resume from `https://www.gnoosic.com/artist/larkin+poe`, take first recommendation, note but do not re-check unless specifically asked