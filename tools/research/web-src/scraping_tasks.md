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
5. Run `python3 tools/research/websrc_diff.py` once this month's HFTB file is also committed

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

*Here for the Bands shows list - AUTOMATED (weekly CI)*

No manual step. `weekly-hftb-diff.yml` runs Fridays, fetches the endpoint below
headless via `scrape_hftb.py`, and commits `rhbl-hereforthebands-dc-YYYY-MM.tsv`
(region=3, DC + Baltimore) to staging. The first Friday of a month writes that
month's file, so the monthly `websrc_diff.py` run waits for it. To get it sooner,
dispatch the workflow by hand from the Actions tab.

Schema: Artist | Venue | Date | Venue URL - all shows at the same venue share the
same Venue URL. The notes below are the reference for the scraper.

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

*Venue calendars scrape MONTHLY - Bethesda Theater only*

Collective Encore and Hub City Vinyl moved to the daily page watch on 2026-10-03
(`tools/watch/watches.tsv`, extractors in `extractors.py`); a new date there arrives
as a `[watch]` mail. Bethesda Theater stays a manual, interactive Chrome scrape: its
robots.txt names AI crawlers with Disallow, which is honored (see its `venues.tsv`
row), so it is never put on the headless watch. The alternative is the venue's own
email list.

1. open the Bethesda Theater calendar URL from data/venues.tsv in a tab
   (its `Coverage` value is `scrape`; any venue that gains that value joins this step)

Bethesda does not publish prices on its calendar, so expect the Price column to
come back mostly empty.

_Prompt_
create venue-calendar-bethesda-theater-2026-MM.tsv for download
use the current two-digit month in place of MM
Capture: upcoming events only. ignore past events
Click All Events, Load More, or equivalent expansion or pagination controls
Schema: Date | Day | Time | Artist/Event | Price | Ticket URL
Dates must always include the year; compute Day from the date
Flag any entry that is not a live-music event (trivia, private events, venue rentals) instead of including it silently

2. save the file in `tools/research/web-src`
3. compare it against the prior month's file in `tools/archive/` by eye - it is
   short, and websrc_diff.py does not read venue calendars

*Bandsintown scrape follows list ON CHANGE*

1. log in as rhbl to bandsintown
2. open https://www.bandsintown.com/u/tracked-artists

_Prompt_
Export my tracked artists to rhbl-bandsintown.tsv for download. One column, header "Artist".
Use the paged endpoint (below) from the page console rather than scrolling. Artist names only, as displayed. Flag any entry that is not a plain artist name instead of dropping it.
Sanity gate: compare the count against the previous export; a result of exactly 50 means the cursor loop did not run.

3. Save the file in `/tools/research/follows`, overwriting the existing file. Put the export date in the commit message - the file carries none.

**Faster path - the tracked-artists endpoint (verified 2026-09-12).** The page pages
through a same-origin JSON endpoint, fetchable from the page context with
`credentials: 'include'`:

    GET https://www.bandsintown.com/u/trackedArtists?max=50&cursor=<cursor>

Response is `{ artists: [...], nextCursorArtist }`. Start with no cursor and pass
`nextCursorArtist` back until it comes back empty (Sep 2026: 50/50/48/24 = 172).
Artist -> `artists[].name`. That is the account's display name, which is
occasionally a page title rather than a bare artist name ("Albert Castiglia Tour
Schedule Page"): map those in `data/recommend_aliases.tsv`, do not hand-edit the
export - the export is evidence of what the account follows.

**No search-results URL.** The header search is a type-ahead; Enter lands on
`/a/<id>-<slug>`. Reminder mail cannot deep-link a name to a search.

*Seated scrape follows list ON CHANGE*

1. login as rhbl to seated.com
2. open https://go.seated.com/notifications - the whole Following list renders at once (no pagination)

_Prompt_
Export my followed artists to rhbl-seated.tsv for download. One column, header "Artist".
Capture only the names in the Following section; skip "Recommended for You" entirely.
Sanity gate: the count should match the page's own "Following (N)" heading and be close to the previous export.
Flag any entry that is not an artist name instead of dropping it. Do not follow, unfollow, or change any notification setting.

3. Save the file in `/tools/research/follows`, overwriting the existing file. Put the export date in the commit message.

**No usable endpoint (verified 2026-09-12).** The page loads its list from
`https://api.seated.com/api/v1/artist-followers?include=artist-profile`, which is
cross-origin from `go.seated.com` and CORS-blocked from the console. Read the DOM.
The artist search is an in-page overlay with no results URL.

**After either export:** `python3 tools/research/reconcile_follows.py` from the repo
root reports ledger-vs-platform drift (empty output = clean). This is Workflow 1-B
in `ANALYSIS_WORKFLOWS.md`.

*Bandcamp follows export ON CHANGE*

Read-only, from a **logged-out** bandcamp.com tab (the dan2bit profile is public;
fan_id `4498338`). Claude in Chrome only: Bandcamp blocks GitHub-hosted runners.
Page each endpoint with `{"fan_id":4498338,"older_than_token":"<epoch>::a::","count":100}`.
The list comes back under `followeers`; follow `last_token` while `more_available`
is true.

- `POST /api/fancollection/1/following_bands`: artists and labels. There is no
  label flag, so classify by name or page and write Kind `artist` or `label`.
- `POST /api/fancollection/1/following_fans`: Kind `fan`.
- `POST /api/fancollection/1/following_genres`: Kind `genre` (taste context only).

Write `tools/research/follows/dan2bit-bandcamp.tsv`:
`Name | Bandcamp URL | Kind | Location | Date Followed`. Use the full page URL,
including custom domains (Sparkbird, Whitney Mongé). `-` marks empty cells. Put the
export date in the commit message. Then run `python3 tools/research/reconcile_follows.py`.
Bandcamp drift is reported in one direction only (see `FOLLOWS_PIPELINE.md`).

First export 2026-11-07: 89 artists, 10 labels, 3 fans, 21 genres. The profile says
"following 125", and the genre endpoint returned 22 entries with "roots" listed
twice, so the profile count includes that duplicate.

*Label rosters ON CHANGE (Bandcamp-sourced)*

The rosters behind `websrc_diff.py`'s "Untracked, on a label roster" section (the
`ROSTERS` table in that script). Alligator and Ruf come from the labels' own sites;
the rest come from Bandcamp, logged out, in Chrome:

- A label with an artists page (`https://<label>.bandcamp.com/artists`): take the
  names in the artists grid.
- A label without one (Tompkins Square, Continental): take the distinct artist
  names from the `/music` grid (`.artist-override` plus the grid's client items).
  Strip release-date and "feat." annotations, and drop compilations and samplers.

File shape: `Artist Name | URL | Status`, with URL being the label page the names
came from. Only in-lane labels get a roster. A mostly-indie roster (Fat Possum,
Nettwerk) turns the section into noise, so those two are deliberately left out even
though dan2bit follows them. Built 2026-11-07: Stax 45, Rounder 104, Arhoolie 67,
Tompkins Square 65, Fantasy 64, Smithsonian Folkways 197, Continental 230.

*Fast track tour pages - AUTOMATED (daily page watch)*

No manual step. Since 2026-10-03 all ten fast-track artists are rows in
`tools/watch/watches.tsv` (check_every_days 1): Evan Nicole Bell, Nikki Hill,
Beth Hart, Angelique Francis and Kat Riggins as plain server-rendered pages;
Danielle Ponder and Miko Marks via the Seated tour API; Sugaray Rayford,
Grace Bowers and Garret T. Willie via Bandsintown's public events endpoint. A
DC/MD/VA date arrives as a `[watch]` mail; the fast-track buy decision (cap check
per DATA_WRITE_PROTOCOLS.md) is still a human one.

Every new `data/fast_track.tsv` row gets a watch row with it - see
DATA_WRITE_PROTOCOLS.md -> fast_track.tsv protocol -> Adding a row.

`fast-track-tour-dates.tsv` in this folder is the last consolidated Chrome scrape
(2026-09) and is no longer refreshed.

*Bandcamp artist lookup ON CHANGE + MONTHLY sweep*

Fills the `Bandcamp URL` column of `data/artists.tsv`. Runs when a routine adds a
new artist row, and as a monthly sweep over blank cells alongside the BIT scrape
(both need a Chrome session). **Chrome only:** Bandcamp returns a bot-challenge page
to GitHub-hosted runners (tested 2026-11-07). The block arrives as HTTP 200 with a
small HTML page, so a 200 is never proof of success. Stay logged out; read-only.

Search, from a bandcamp.com tab:

    POST /api/bcsearch_public_api/1/autocomplete_elastic
    {"search_text":"<name>","search_filter":"b","full_page":false,"fan_id":null}

Results are in `auto.results` (`name`, `item_url_root`, `location`, `genre_name`).
Match on the normalized name (lowercase, no accents, no leading "the", "&" -> "and",
no punctuation); accept a prefix match either way ("Robert Randolph" vs "Robert
Randolph and The Family Band"). If nothing matches, retry with ", The" moved to the
front, then the lead name before " & " / " and " / " with " / ":", then without a
trailing "Band".

Validate every candidate before using it:

- **Releases:** open `https://<subdomain>.bandcamp.com/music` and count the grid
  items. Do NOT count with the album search: it returns only a few results and
  undercounts. 0 releases means an empty or squatter page (the Larkin Poe
  `1235agejghahanl` case, Calhoun GA, no content).
- **Location and genre** fit the act.
- **Big acts** (arena / major-label) need extra proof: Dan follows the page
  (https://bandcamp.com/dan2bit), or it links the official site or socials, or it has
  3+ releases matching the real discography. Many big acts are rightly NONE.
- **Never a label's page.** If the music is only on a label's page, the value is `-`;
  note the label for the label rosters.

Resolve: one candidate passes -> write it. Several pass -> Dan picks (show link,
location, release count, newest release; default to the more complete or newer
page). Possibly a different act -> ask, leave blank. None -> `-`.

The initial backfill (2026-11-07) is
`tools/research/web-src/artists-bandcamp-final-2026-11-07.tsv`, merged from
`...-backfill-...` (pass 1) and `...-pass2-...` (pass 2); its `Basis` column records
where each value came from.

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




