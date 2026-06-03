# Analysis Workflows — Live Show Archive

Five standing workflows for periodic show discovery, artist research, and file
maintenance. These are independent of the email routines in `EMAIL_WORKFLOWS.md` —
they are triggered by calendar reminders, file editing events, or on-demand requests,
not inbox events.

---

## Workflow 1 — Bandsintown DC Recommends Refresh

**Cadence:** Monthly — 1st Tuesday of each month
**Trigger:** Recurring calendar event "🔄 Re-fetch Recommendations pages"
**Account:** rhbl (redhat.bootlegs@gmail.com)

### Pre-scrape manual prep (required)

The BIT DC Recommends page uses **progressive disclosure** — artists load as you
scroll and some sections are collapsed. You must:
1. Open the URL yourself
2. Scroll to the very bottom of the page
3. Click "View All" on any collapsed sections

**Do this before handing off to Claude in Chrome.** If you skip it, Claude will
only capture the first screenful and the file will be incomplete.

### What to do

Use Claude in Chrome (logged in as rhbl) to fetch the fully loaded page:

```
https://www.bandsintown.com/c/washington-dc?came_from=278&utm_medium=web&utm_source=city_page&utm_campaign=recommended_event&recommended_artists_filter=Recommended
```

Parse and save as:

```
web-src/rhbl-bandsintown-dc-recommends.tsv
```

Schema: `Artist | Venue/Event | Date | Time | Tracking`

### Artist diff analysis

Diff the new file against the previous version to find new and removed artists.
The goal of the diff is **finding artists of interest** — not just confirming
already-known shows.

For every artist that is new (present in the new file but not the old):

**1. Cross-reference against all five sources:**
- `live_shows_current.tsv` (upcoming rows) — already purchased, note and skip
- `live_shows_potential.tsv` (all decisions) — already evaluated, note decision
- `fast_track.tsv` — pre-authorized buy; surface any open date immediately
- `follows/follows_master.tsv` — tracked follow; note tier and surface show
- `follows/new_artist_research.tsv` — in research pipeline; note and surface

**2. Flag by tier for artists not already tracked:**
- **Strong** (seen before, in `artists.tsv`) — surface immediately; likely a buy
- **Medium** (in autograph books but not yet seen) — surface for review
- **New name** (not in any of the above) — note in conversation; no file action
  unless the taste profile fit is strong enough to add to NAR

Do not silently discard new entries. Every new artist name should appear in the
diff output, even if the conclusion is "pass."

---

## Workflow 2 — HereForTheBands DC Region Refresh

**Cadence:** Monthly — 1st Tuesday of each month (same session as Workflow 1)
**Trigger:** Recurring calendar event "🔄 Re-fetch Recommendations pages"
**Account:** rhbl (redhat.bootlegs@gmail.com)

### What to do

Use Claude in Chrome (logged in as rhbl) to fetch:

```
https://www.hereforthebands.com/washington-dc
```

Scroll to bottom before scraping to load all events. Parse and save as:

```
web-src/rhbl-hereforthebands-dc.tsv
```

Schema: `Artist | Venue | Date | Venue URL`

Note: HFTB provides one URL per venue, not per event — all shows at the same
venue share the same Venue URL.

### Artist diff analysis

Diff the new file against the previous version. Because HFTB entries are show
listings (not a follow list), the meaningful signal is **new artist names**
appearing for the first time, not churn in show listings for already-known artists.

For every artist name appearing in new rows that wasn't in any old row:

**Cross-reference against all five sources** (same as Workflow 1):
- `live_shows_current.tsv` — already purchased, note and skip
- `live_shows_potential.tsv` — already evaluated, note decision
- `fast_track.tsv` — surface immediately
- `follows/follows_master.tsv` — note tier and surface show
- `follows/new_artist_research.tsv` — note and surface

**Flag by tier** (same tier logic as Workflow 1).

Also note new venues appearing in HFTB for the first time — these may represent
new booking relationships worth tracking in `venues.tsv`.

Note: The rhbl account receives venue newsletters directly from Rams Head On
Stage, Hamilton Live, and Wolf Trap — those gaps in HFTB coverage are handled
separately via email.

---

## Workflow 3 — Fast Track Tour Page Scrape

**Cadence:** Monthly — same session as Workflows 1 and 2
**Trigger:** Recurring calendar event "🔄 Re-fetch Recommendations pages"

### Pre-scrape manual prep (required)

Before opening Claude in Chrome, **ask Claude for the current list of tour page
URLs and their corresponding `follows/` filenames** from
`follows/fast-track-artist-tour-pages.tsv`. Open all tabs at once before handing
off — it is much faster than opening them one at a time mid-session.

### What to do

For each artist in `follows/fast-track-artist-tour-pages.tsv`:

1. Open their tour page URL in Claude in Chrome
2. Click "All Shows", "Load More", or equivalent expansion controls before scraping
3. Capture upcoming dates only (ignore past events)
4. Overwrite the corresponding `follows/fast-track-[artist]-tour-dates.tsv`

Schema: `Date | Day | Time | Event/Venue | Venue | City | State (or Country if non-USA)`

If no upcoming events exist: leave the file with the header row only, and update
the Notes column in `fast-track-artist-tour-pages.tsv`.

### DMV scan

After all files are updated, ask Claude to scan each file for dates within the
DMV region (~60 miles of Arlington VA: DC/MD/VA + Baltimore). Any hit is a
**Fast Track buy** — surface immediately. Do not add out-of-region dates to any
potentials list.

---

## Workflow 4 — Quarterly Artist Research: Festivals & Awards

**Cadence:** Quarterly — 1st Tuesday of January, April, July, and October
**Trigger:** Recurring calendar event "🔍 Quarterly Artist Research — Festivals & Awards"

### Purpose

Blues cruises, major festivals, and annual award nominees are curated signals
for discovering artists in the taste profile who aren't yet on the radar.
This workflow cross-references those external sources against `artists.tsv`
and feeds new discoveries into `follows/new_artist_research.tsv`.

### Sources to check each quarter

**Awards** (check when newly published):

- **Blues Music Awards (BMA)** — Blues Foundation nominees and winners,
  published each spring (Jan/Feb).
  URL: https://blues.org/blues-music-awards/
- **Americana Music Association Awards** — nominees and winners published
  each fall (summer announcement).
  URL: https://americanamusic.org/ama-awards

**Festival lineups** (check when newly published):

- **Hardly Strictly Bluegrass** — San Francisco, free, early October;
  lineup announced ~August
- **Americanafest / AmericanaFest** — Nashville, September
- **Big Blues Bender** — Las Vegas, late September
  URL: https://bigbluesbender.com
- **Blues cruise lineups:**
  - Keeping the Blues Alive at Sea (Joe Bonamassa, annual, Caribbean)
  - Rock Legends Cruise (annual, Caribbean)
  - Legendary Rhythm & Blues Cruise (annual, Caribbean/Mexico)
- **Stagecoach** — Indio CA, April (country/Americana crossover)
- **Telluride Bluegrass Festival** — Colorado, June

### Process

1. For each source that has published new content since the last quarterly
   check, pull the current lineup or nominee list
2. Cross-reference each artist name against `artists.tsv`:
   - **Strong tier** (Times Seen ≥ 1) — flag immediately; may already be
     tracked for upcoming shows
   - **Medium tier** (in autograph books but not seen) — flag for review
   - **New name** (not in either) — research and add to
     `follows/new_artist_research.tsv` if they fit the taste profile
3. For any Strong-tier discoveries playing DC/MD/VA in the near term,
   surface as a potential buy recommendation
4. For any Strong-tier new discoveries not yet followed, consider adding
   to Bandsintown and/or Seated follows

### Output

New artist discoveries go into `follows/new_artist_research.tsv`.
No separate output file — the workflow produces either TSV additions
or conversation-level recommendations.

---

## Workflow 5 — Fast Track Entry: Follow Coverage Audit

**Cadence:** Ad hoc — run whenever a new artist is added to `fast_track.tsv`
**Trigger:** Editing `fast_track.tsv` (no calendar event; part of the same session)

### Purpose

When an artist is added to the Fast Track list, they are being elevated to
pre-authorized buy status — which means the signal pipeline needs to be strong
enough to actually surface a local show before it sells out. This workflow
ensures follow coverage is complete at the time of entry, rather than
discovering a gap after missing a show.

### Process

For each newly added artist, look them up in `follows_master.tsv` and assess:

**1. Bandsintown follow**
- Is the artist followed on BIT (rhbl account)?
- If not: recommend adding. BIT is the primary real-time show alert pipeline.
- If yes and no DC show has surfaced recently: note whether a targeted off-cycle
  BIT DC Recommends refresh (Workflow 1) or an artist-specific BIT page check
  might surface current availability.

**2. Songkick / Seated follow**
- Is the artist tracked on Songkick or Seated?
- If not: recommend adding if they are likely to be listed on those platforms
  (Songkick skews well-established; Seated skews smaller/independent venues).

**3. Direct mailing list**
- Does the artist have a mailing list? Is it subscribed under redhat.bootlegs?
- If a list exists and isn't subscribed: recommend subscribing, especially for
  Strong-tier Fast Track artists where tour announcements may come before BIT
  alert propagation.

**4. HereForTheBands**
- Will the artist likely appear in HFTB DC region results?
- HFTB is more useful for artists with consistent mid-size DC bookings;
  less reliable for debut or rare DC appearances.

**5. Off-cycle refresh recommendation**
- If the artist has no coverage gap but also no recent DC signal, flag whether
  an off-cycle run of Workflow 1 (BIT DC Recommends) or Workflow 2 (HFTB)
  is warranted to check current listings immediately rather than waiting for
  the monthly cadence.

**Autograph books as a taste signal:** The presence of an artist in RHBS or APS
is a valid supporting factor when evaluating alignment to taste tiers, but it is
one factor among many — not determinative. RHBS's roster is more central to Dan's
core taste than APS. An APS entry alone is not sufficient to elevate tier.

### Output

Present coverage gaps and recommendations in conversation. No automatic file
changes — any `follows_master.tsv` updates or service follow actions require
confirmation before committing.

If a gap is confirmed and filled (e.g., a BIT follow is added), note it in
the same session log or commit message.

### Example

An artist like Danielle Ponder is added to `fast_track.tsv`. The audit finds:
- Not in `follows_master.tsv` at all → recommend adding row with BIT + Seated
- No direct mailing list subscription → recommend checking if one exists
- HFTB coverage likely (plays the size of rooms HFTB tracks) → no action needed
- Off-cycle BIT check recommended since she's touring actively

Result: a proposed `follows_master.tsv` row is presented for approval, and a
note to check her BIT page directly for any current DC-area dates.

---

## Workflow 6 — Potentials Availability Check

**Cadence:** On demand
**Trigger:** Say "check availability" or "availability check" in a project conversation
**Requires:** Claude in Chrome

### Purpose

Ticket availability for Buy and Choose rows can change between when a show is
added to the potential list and when a purchase decision is made. This workflow
proactively checks current availability against what was recorded, so that
decisions aren't forced by a sold-out situation rather than made deliberately.
The Anthony Gomes front-row situation (Apr 2026) is the reference case: a Choose
row where a preferred ticket tier sold out before a decision was reached.

### What to do

1. Fetch `live_shows_potential.tsv` from the repo
2. For every **Buy** and **Choose** row that has a `Purchase URL` or `Event URL`:
   open the page in Claude in Chrome and check current ticket availability
3. **Opendate venues (Jammin' Java, Union Stage, Pearl Street, Howard):** read
   text only — never infer sold out from an SVG badge; badge state is unreliable
4. Compare findings against the `Watching For` field for that row
5. Report a summary in conversation: what has changed, what is newly concerning
   (low inventory, a ticket tier gone, sold out), what is unchanged
6. For any row where availability has materially changed:
   - Propose an update to `Watching For` and/or `Availability Notes` in the TSV
   - Flag explicitly whether a decision is now urgent

### Out of scope

- Pass and Sell rows — no action needed
- Rows with no `Purchase URL` and no `Event URL` — nothing to check
- Rows where the `Watching For` field is already "sold out" or the show is free
  (e.g. NGA lottery) — note but do not re-check unless specifically asked
