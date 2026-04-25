# Analysis Workflows — Live Show Archive

Five standing workflows for periodic show discovery, artist research, and file
maintenance. These are independent of the email routines in `EMAIL_WORKFLOWS.md` —
they are triggered by calendar reminders, file editing events, or on-demand requests,
not inbox events.

---

## Workflow 1 — Bandsintown DC Recommends Refresh

**Cadence:** Monthly — 1st Tuesday of each month
**Trigger:** Recurring calendar event "🔄 Re-fetch Bandsintown DC Recommends page"
**Account:** rhbl (redhat.bootlegs@gmail.com)

### What to do

Use Claude in Chrome (logged in as rhbl) to fetch:

```
https://www.bandsintown.com/c/washington-dc?came_from=278&utm_medium=web&utm_source=city_page&utm_campaign=recommended_event&recommended_artists_filter=Recommended
```

Parse the page and save the full listing as:

```
live-shows/web-src/rhbl-bandsintown-dc-recommends.tsv
```

Schema: `Artist | Venue | Date | Event URL`

Then ask Claude to diff the new file against the previous version and surface
any artists not previously present. Flag by tier:

- **Strong** (artist seen before) — surface immediately for review
- **Medium** (artist in autograph books) — surface for review
- **Low** (artist not in either) — log only, no action needed

---

## Workflow 2 — HereForTheBands DC Region Refresh

**Cadence:** Monthly — 1st Tuesday of each month (same session as Workflow 1)
**Trigger:** Recurring calendar event "🔄 Re-fetch Bandsintown DC Recommends page"
**Account:** rhbl (redhat.bootlegs@gmail.com)

### What to do

Use Claude in Chrome (logged in as rhbl) to fetch:

```
https://www.hereforthebands.com/washington-dc
```

Parse the page and save the full listing as:

```
live-shows/web-src/rhbl-hereforthebands-dc.tsv
```

Schema: `Artist | Venue | Date | Venue URL`

Note: HFTB provides one URL per venue, not per event — all shows at the same
venue share the same URL.

Then diff against the previous version and flag new entries by tier (same
tiers as Workflow 1).

Note: The rhbl account receives venue newsletters directly from Rams Head On
Stage, Hamilton Live, and Wolf Trap — those gaps in HFTB coverage are handled
separately via email.

---

## Workflow 3 — Quarterly Artist Research: Festivals & Awards

**Cadence:** Quarterly — 1st Tuesday of January, April, July, and October
**Trigger:** Recurring calendar event "🔍 Quarterly Artist Research — Festivals & Awards"

### Purpose

Blues cruises, major festivals, and annual award nominees are curated signals
for discovering artists in the taste profile who aren't yet on the radar.
This workflow cross-references those external sources against `artists.tsv`
and feeds new discoveries into `new_artist_research.tsv`.

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
     `new_artist_research.tsv` if they fit the taste profile
3. For any Strong-tier discoveries playing DC/MD/VA in the near term,
   surface as a potential buy recommendation
4. For any Strong-tier new discoveries not yet followed, consider adding
   to Bandsintown and/or Seated follows

### Output

New artist discoveries go into `live-shows/new_artist_research.tsv`.
No separate output file — the workflow produces either TSV additions
or conversation-level recommendations.

---

## Workflow 4 — Fast Track Entry: Follow Coverage Audit

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

## Workflow 5 — Potentials Availability Check

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

1. Fetch `live-shows/live_shows_potential.tsv` from the repo
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

- Pass rows — no action needed
- Rows with no `Purchase URL` and no `Event URL` — nothing to check
- Rows where the `Watching For` field is already "sold out" or the show is free
  (e.g. NGA lottery) — note but do not re-check unless specifically asked
