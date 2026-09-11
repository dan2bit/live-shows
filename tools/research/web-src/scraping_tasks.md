**Conventions:** monthly files carry a `-YYYY-MM` suffix. After a successful month-over-month diff, move the superseded prior-month file to `tools/archive/`.

*BIT recommended shows list MONTHLY**

1. log in as rhbl to bandsintown
2. open https://www.bandsintown.com/c/washington-dc?came_from=278&utm_medium=web&utm_source=city_page&utm_campaign=recommended_event&recommended_artists_filter=Recommended
3. choose view all, and scroll until all the progressive disclosure is exposed

_Prompt_
create rhbl-bandsintown-dc-recommends-2026-MM.tsv for download
use the current two-digit month in place of MM
Schema: Artist | Venue/Event | Date | Time | Tracking
Capture: artist name, venue/event name, date, time, attending count (Tracking)
Dates must always include the year (e.g. "Jul 04, 2026")

4. Save the file in `/tools/research/web-src`
5. Have Claude Desktop diff the file against the previous month

_Faster path: the pagination endpoint (verified 2026-09-07)_

The DOM route is fragile here. "View All" is a bare `div` (not a button) inside a
`react-infinite-scroll` component, and scrolling stalls around 72 rows, so a DOM
scrape silently yields a partial file. The component pages through a JSON endpoint
that can be fetched directly from the page context with `credentials: 'include'`:

```
https://www.bandsintown.com/all-dates/fetch-next/upcomingEvents
  ?came_from=278&utm_medium=web&utm_source=city_page
  &utm_campaign=recommended_event&recommended_artists_filter=Recommended
  &longitude=-77.03637&latitude=38.89511&page_type=cityPage&page=N
```

Page N starts at 1 and returns 36 events per page under `events`; loop until the
array comes back empty (Sep 2026: pages 1-6 full, page 7 empty, 194 unique events).
Dedupe on `id`. Field mapping to the schema above:

- Artist -> `artistName`
- Venue/Event -> `title` if present, else `venueName` (BIT shows the tour/festival
  name in place of the venue when `title` is set - about a quarter of rows)
- Date / Time -> `startsAt`, a naive local string like `2026-09-18T19:30:00`; parse
  the string directly, do NOT construct a Date object or the container's UTC clock
  will shift evening shows to the next day
- Tracking -> `rsvpCountInt`

Sanity gate: compare the row count against the prior month before saving. A result
near 36 or 72 means the pagination loop did not run and the file is partial.

This view is personalised to the rhbl follow graph, so it needs the logged-in
session. It cannot be scraped headless - without the session you get either an
error or a generic DC listing that looks plausible and silently is not yours.

**Establish the date from a source other than the container clock.** The sandbox
clock has been observed running days behind wall time, which silently mis-dates
provenance notes and "days until show" math. Cross-check against the newest dated
entries in the potentials file before writing any date into a scrape artifact.

*Here for the Bands shows list MONTHLY*

1. open https://www.hereforthebands.com/shows.php and choose dc
2. scroll to the bottom and click ALL, wait for the load to complete

_Prompt_
create rhbl-hereforthebands-dc-2026-MM.tsv for download
use the current two-digit month in place of MM
Schema: Artist | Venue | Date | Venue URL
Capture: artist name, venue, date, venue URL
Dates must always include the year
all shows at the same venue share the same Venue URL

3. Save the file in `/tools/research/web-src`
4. Have Claude Desktop diff the file against the previous month

_Faster path: the per-day JSON endpoint (verified 2026-09-07)_

The shows page ships no event markup at all - the table is built client-side by
calling one endpoint per calendar day, which is why the DOM appears to grow while
you watch it and why a scroll-and-scrape stops early at an arbitrary date:

```
https://www.hereforthebands.com/jc.php?region=1&page=ALL&date=YYYY-MM-DD
```

Returns JSON shaped `{ "<date>": { "<venue>": { venue_url, shows: [...] } } }`
- note the payload is itself keyed by the date, so unwrap that layer before reading
venues. Empty days return `{}`. Loop day by day from today; Sep 2026 ran to
2027-07-16 before the tail went empty (191 populated days, 1551 rows). Decode HTML
entities in venue and show names (`&ndash;` and `&amp;` arrive raw). `venue_url` is
sometimes absent - leave it blank.

**`region` is a bitmask, not a rotating id** (verified 2026-09-11): dc=1, bal=2,
wd=4, phi=8. So `region=3` returns DC **and** Baltimore in one pass. The `■`
toggles in the site's region box read 14/13/11/7 - those are 15 minus each bit,
i.e. "everything except this one", computed from current selection state, which is
what makes the ids look like they rotate. The named region links are stable.

Every scrape through 2026-09 used `region=1`, so Baltimore-area rooms that appear
in potentials and history (The 8x10, Ottobar, Baltimore Soundstage) have never been
in the HFTB half of the diff. Switching to `region=3` closes that - but the first
`region=3` file diffed against a `region=1` prior month reports every Baltimore act
as new. Re-baseline deliberately rather than reading that as signal.

**Works headless** - plain HTTP, no cookies, normal User-Agent (verified
2026-09-11). Unlike the BIT view above, nothing here is personalised.

Caution: the Artist column holds an entire bill, comma-separated ("Cheekface, Apes
Of The State"). Tokenize before comparing against tracking files or the join silently
misses nearly everything - see websrc_diff.py.

*Venue calendars scrape MONTHLY*

1. ask Claude Desktop for the calendar URLs of venues in data/venues.tsv whose `Coverage` column contains `scrape`

   (This replaced the old free-text `Calendar Coverage` column in 2026-09. `Coverage`
   is a pipe-separated controlled vocabulary - `hftb`, `email`, `scrape`, `watch`,
   `artist-platform`, `none` - so this is now an exact membership test rather than a
   substring match on prose. `Newsletter Source`, `Subscription` and `Coverage Checked`
   carry the rest of what that column used to imply.)

As of 2026-09-07 that is three venues: Collective Encore, Hub City Vinyl, and
Bethesda Theater. None of the three publishes prices on its calendar page, and
Hub City's list view carries no times or per-event links either, so expect the
Price and Ticket URL columns to come back mostly empty.

_Prompt 1_
open each of these URLs in a new tab in this window

_Prompt 2_

for each venue with an open tab
create venue-calendar-<venue>-2026-MM.tsv for download
use the current two-digit month in place of MM
Capture: upcoming events only. ignore past events
Click All Events, Load More, or equivalent expansion or pagination controls
Schema: Date | Day | Time | Artist/Event | Price | Ticket URL
Dates must always include the year
Flag any entry that is not a live-music event (trivia, private events, venue rentals) instead of including it silently
offer the completed file before moving on to the next venue

3. save the files in `tools/research/web-src`
4. Have Claude Desktop diff each file against the previous month

*Bandsintown scrape follows list ON CHANGE*

1. log in as rhbl to bandsintown
2. open https://www.bandsintown.com/u/tracked-artists and make sure View All is active

_Prompt_
create rhbl-bandsintown.tsv for download. one column: Artist
Capture: the artist names only from the tracked-artists page
Flag any entry that is not an artist name (page titles, tour-schedule pages, stray UI text) instead of including it silently

3. Save the file in `/tools/research/follows`, overwriting the existing file

*Seated scrape follows list ON CHANGE*

1. login as rhbl to seated.com
2. open https://go.seated.com/notifications and make sure all artists are visible

_Prompt_
create rhbl-seated.tsv for download. one column: Artist
Capture: only the artists names in the Following section of this page. 
skip over the "Recommended for You" list
Flag any entry that is not an artist name (page titles, stray UI text) instead of including it silently

3. Save the file in `/tools/research/follows`, overwriting the existing file

*Fast track tour pages scrape MONTHLY*

1. ask Claude Desktop to produce just the list of tour page URLs from data/fast_track.tsv

_Prompt 1_
open each of these URLs in a new tab in this window

2. review the pages for completely empty lists (Bell, Ponder) and close the tabs

_Prompt 2_

for each artist with an open tab, in turn
append rows to a single fast-track-tour-dates.tsv for download
Capture: upcoming dates only. ignore past events
Click All Shows, Load More, or equivalent expansion or pagination controls
Schema: Artist | Date | Day | Time | Event/Venue | Venue | City | State (or Country if non-USA)
The Artist column repeats the artist's name (as spelled in data/fast_track.tsv) on every one of that artist's rows
offer the running file after each artist before moving on to the next

3. save the single file as `tools/research/web-src/fast-track-tour-dates.tsv`, overwriting the prior copy
   (this replaced the former per-artist fast-track-<artist>-tour-dates.tsv files, consolidated 2026-07-23)

Each tour page is a different platform, so budget one browser permission grant per
domain. Angelique Francis paginates through a Turbo Stream endpoint rather than a
normal pager; Beth Hart and Kat Riggins publish no set times. Recompute the Day
column from the date rather than trusting the site's own weekday label.

*Youtube Playlist Inventory ON DEMAND*

Reference: provide `dom-reference-youtube-setlist.md` (this folder) to the Claude for Chrome session before starting — it has the tested selectors, extraction scripts, and verification gates.

1. login to Youtube Studio and navigate to Content -> Playlists
2. set Rows Per Page to 50

_Prompt_
create `youtube_playlists_YYYYMMDD.tsv` for download, using the current date in the filename
Schema: Title | Description | Shareable Link | Video Count
Capture: do not use the clipboard tool `Get shareable link` - build the link programmatically
use the pagination controls to collect all playlists
follow the attached dom-reference-youtube-setlist.md for selectors and extraction

3. save the file in `tools/archive` and optionally delete the prior file

*Setlist Attendances Inventory ON DEMAND*

Reference: provide `dom-reference-youtube-setlist.md` (this folder) to the Claude for Chrome session before starting — it has the tested selectors, extraction scripts, and verification gates.

1. login to setlist.fm and navigate to https://www.setlist.fm/attended/dan2bit
2. change Setlists shown per page to 500 and scroll to the bottom

_Prompt_
create `setlist_attendances_YYYYMMDD.tsv` for download, using the current date in the filename
Schema: Date | Band Name | Description | URL
Capture: use the pagination controls to collect all setlists if necessary
follow the attached dom-reference-youtube-setlist.md for selectors and extraction

3. save the file in `tools/archive` and optionally delete the prior file




