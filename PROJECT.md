# songs-for-my-funeral — Live Shows Project

Comprehensive live concert tracking and YouTube bootleg management system for the `@dan2bit` YouTube channel. Managed collaboratively with Claude (Anthropic) via MCP tools.

---

## Repository Structure

```
live-shows/
├── PROJECT.md                        ← this file
├── ANALYSIS_WORKFLOWS.md             ← quarterly/monthly research workflows
├── EMAIL_WORKFLOWS.md                ← inbox processing routines
├── TASKS.md                          ← outstanding tasks
├── index.html                        ← browser-based show dashboard
├── live_shows_current.tsv            ← confirmed shows (attended + upcoming)
├── live_shows_potential.tsv          ← shows under consideration (Buy/Choose/Pass)
├── artists.tsv                       ← artist follow list with show history
├── venues.tsv                        ← venue details (parking, transit, seating)
├── autograph_books_combined.tsv      ← autograph book inventory
├── spending.tsv                      ← annual spending summary
├── fast_track.tsv                    ← quick-add artist pipeline
├── rollover.py                       ← year-end rollover script
├── youtube_*.py                      ← YouTube playlist management scripts
├── follows/                          ← artist follow lists by tier
│   └── new_artist_research.tsv       ← newly researched artists
├── web-src/                          ← raw service exports (prefixed by account)
├── history/                          ← archived yearly show history
├── archive/                          ← superseded files
└── logs/                             ← script run logs
```

---

## Core Data Files

### live_shows_current.tsv
24-column TSV. Rows are either `attended` or `upcoming`, ordered chronologically. Columns: Show ID, Artist, Supporting Artist, Show Date, Doors Time, Start Time, Venue Name, Venue Address, Venue Event URL, Seat Info / GA, Ticket Access, Ticket Quantity, Face Value (per ticket), Fees, Total Cost, Purchase Date, Setlist.fm URL, Status, Food & Bev, Parking, Merch, Artist Interaction, Playlist URL, Notes / Memories.

**Known issue:** The GitHub MCP `create_or_update_file` tool strips trailing tabs from each line. For rows where Playlist URL is empty and Notes is the last non-empty field, the notes text lands in the Playlist URL column. The `parseTsv()` function in `index.html` compensates for this at parse time by detecting non-URL content in the Playlist URL column and swapping it to Notes.

### live_shows_potential.tsv
17-column TSV. Decision values: `Buy`, `Choose`, `Pass`. Sort order: Buy → Choose → Pass (alpha within group), date ascending within each group. Re-sort the full file on every row change. Prev Show and Next Show columns reference only **purchased upcoming shows** — never potential shows, never attended shows.

### artists.tsv
One row per artist. Tracks: Times Seen, First Seen, Most Recent Seen, YouTube Channel, Spotify URL, Photo (Y), Book Autograph (Y), Hat Autograph (Y), VIP Count.

### venues.tsv
Parking, transit, seating, box office hours, and notes per venue.

---

## Workflow Rules

### GitHub Commits
- **TSVs and HTML/config files** → commit directly to `main` via MCP `create_or_update_file`
- **Executable files** (`.py`, `.sh`, `.js`, `.pl`) → PR branch required; Dan merges
- Always fetch a fresh SHA immediately before each `create_or_update_file` call — stale SHAs cause failures
- Always push full file content — never attempt targeted/patch commits; this has clobbered files
- `push_files` with empty string content silently commits empty blobs — always use `create_or_update_file`
- Large files (50KB+) such as `live_shows_history.tsv`, `youtube_create_playlists.py` → present in conversation for manual check-in
- No commits without explicit confirmation from Dan
- **index.html** → always write via Python and present the file; never commit via MCP (JSON encoding issue strips Unicode)

### Potentials Bracket Rule
Prev Show and Next Show in `live_shows_potential.tsv` reference only **purchased upcoming shows** (status = `upcoming` in `live_shows_current.tsv`). Potentials, attended shows, and shows under consideration are never used as brackets. Re-check all brackets whenever a new show is purchased or a show moves to attended.

### Playlist Issues
When closing a GitHub playlist issue, edit the issue **body** to add `Playlist: <url>` before closing. Comments are not readable via MCP — only the issue body is.

### Calendar
- Concert calendar: `redhat.bootlegs@gmail.com` ("Dan Concert Calendar")
- Search concert events against `redhat.bootlegs@gmail.com`, not `primary`
- Fall back to `timeMin`/`timeMax` date-bounded listing when `q` search returns nothing
- Calendar MCP may fail silently on Android — ask Dan to switch to macOS desktop before retrying

---

## Ticket Service Notes

| Service | Venues | Notes |
|---|---|---|
| AXS | Rams Head On Stage | Mobile app; paper ticket at box office saves fees |
| Opendate | Jammin' Java, Union Stage, Pearl Street, Howard Theatre | Never infer sold out from SVG badge — text only |
| Eventim | Hamilton Live, Hub City Vinyl | Remind Dan to photo barcode for Google Wallet |
| Eventbrite | Collective Encore | Remind Dan to photo barcode for Google Wallet |
| Ticketmaster SafeTix | 9:30 Club, Wolf Trap (some), general | Mobile only |
| Wolf Trap | Wolf Trap Filene Center | Paper ticket (donor); no fees |
| HyltonCenter.org | Hylton Performing Arts Center | Own platform |

---

## Venue Defaults

| Venue | Parking | Notes |
|---|---|---|
| Rams Head On Stage | $9.45 | AXS Mobile |
| Hamilton Live | $13.00 | Eventim/See Tickets |
| The Birchmere | Free | Doors 6:00 PM / Show 7:30 PM |
| Wolf Trap Filene Center | Free | Paper ticket / donor; $0 food/bev (Lary donor) |
| 9:30 Club | $0 | Street / garage varies |
| Collective Encore | $0 | Free lot |
| Jammin' Java | $0 | Free on-site |
| Hylton Performing Arts Center | Free | Tower Lot; HyltonCenter.org |

---

## Artist Interaction Rules

- **Hat signing eligibility:** Female musicians only. Do not infer gender for all `artists.tsv` entries — apply only when context makes it clear (e.g., during show processing or explicit mention).
- **Autograph book check:** Required before every new calendar event creation.
- Artist Interaction field values: `Photo`, `Autograph`, `Both`, or blank.

---

## Email Inbox Routines

Defined in `EMAIL_WORKFLOWS.md`. Summary:

| Routine | Query | Purpose |
|---|---|---|
| 1 | `from:dan2bit -label:processed` | Show notes from Dan |
| 3 | `label:ticket-alert -label:processed` | Venue newsletters, ticket alerts |
| 4 | `label:artist-mail -label:processed` | Artist mailing lists |

- `processed` label ID: `Label_421272830174798850`
- `ticket-alert` label ID: `Label_8111132848568068688`
- Applying `processed` label is always manual — flag at end of each routine
- `rhbl` account receives direct venue newsletters from Rams Head, Hamilton Live, Wolf Trap
- Flag if 7+ days since last inbox run

---

## YouTube Channel

- Channel: `@dan2bit` (OAuth under `dan2bit@gmail.com` — **not** `redhat.bootlegs`)
- Scripts: `youtube_create_playlists.py`, `youtube_fix_descriptions.py`
- Use setlist.fm for song ordering within playlists
- Python venv: `live-shows/.venv/`; credentials via `.env` + `python-dotenv`

---

## Quarterly & Monthly Workflows

- **Quarterly artist research:** First Tuesday of Jan/Apr/Jul/Oct — next: Jul 7, 2026
- **Monthly BIT DC Recommends + HereForTheBands DC region:** Shared recurring calendar event
- **Inbox processing:** Flag if 7+ days since last run

---

## Spending Budget

- Monthly budget: $500
- For multi-ticket orders: 1 ticket counts against budget; additional tickets tracked separately as "shared" (to collect from others)
- Wolf Trap food/bev: $0 (Lary Chinowsky donor pre-show access included)

---

## Key People

- **Lary Chinowsky** — frequent concert companion; Wolf Trap donor; source of recommendations
- **Jennifer** — concert companion for Sarah McLachlan (Jul 5), Trombone Shorty (Jul 18), Jon Batiste (Aug 21)
- **Bob Lubbehusen** — blues community contact; source of recommendations
- **Ed Warburton** — blues community contact
- **Steve Goodman** — blues community contact
