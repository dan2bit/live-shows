# live-shows

Concert tracking system for the [@dan2bit](https://www.youtube.com/@dan2bit) YouTube channel — attended and upcoming shows, potential purchases, venue intelligence, artist follow lists, and YouTube bootleg playlist management. Maintained collaboratively with [Claude](https://claude.ai) via MCP tools.

Dashboard (GitHub Pages): **https://dan2bit.github.io/live-shows/**

---

## Key files

| File | Purpose |
|---|---|
| `live_shows_current.tsv` | Confirmed shows — attended and upcoming |
| `live_shows_potential.tsv` | Shows under consideration (Buy / Choose / Sell / Pass) |
| `artists.tsv` | Artist follow list with show history |
| `venues.tsv` | Venue details — parking, transit, seating, box office |
| `fast_track.tsv` | Pre-authorized quick-buy artist list |
| `autograph_books_combined.tsv` | Autograph book inventory |
| `spending.tsv` | Annual spending summary |
| `setlists/<year>.json` | Per-date multi-act setlist links (MULTI shows), one file per year |
| `index.html` | Browser-based dashboard (served via GitHub Pages) |

## Directories

| Directory | Purpose |
|---|---|
| `follows/` | Artist follow lists by tier |
| `history/` | Archived yearly show history |
| `web-src/` | Raw service exports (prefixed by account) |
| `archive/` | Superseded files |
| `logs/` | Script run logs |

## Documentation

| Doc | Scope |
|---|---|
| `PROJECT.md` | Data-file schemas and repository/commit conventions |
| `AGENTIC_WORKFLOWS.md` | System architecture and collaboration model |
| `ANALYSIS_WORKFLOWS.md` | Quarterly/monthly research workflows |
| `CALENDAR_WORKFLOWS.md` | Concert calendar event rules |
| `EMAIL_WORKFLOWS.md` | Inbox processing routines (Gmail label-based) |
| `EMAIL_SETUP.md` | Gmail labels, filters, subscriptions, follow services |
| `HOWTO_CHANNEL.md` | YouTube scripts, Python venv, credentials, playlist conventions |

## Scripts

YouTube playlist management and year-end rollover. See `HOWTO_CHANNEL.md` for environment setup (venv, credentials) and per-script usage.

| Script | Purpose |
|---|---|
| `youtube_create_playlists.py` | Create/update YouTube playlists from show history |
| `youtube_fix_descriptions.py` | Sync playlist descriptions |
| `youtube_fetch.py` | Fetch video metadata from the YouTube API |
| `youtube_correlate.py` | Correlate videos to shows |
| `youtube_fill_handles.py` | Fill missing YouTube channel handles in `artists.tsv` |
| `youtube_audit_blanks.py` | Audit shows missing playlist URLs |
| `rollover.py` | Year-end migration of `live_shows_current.tsv` into `history/` |

## Setup

Scripts run in a local Python venv with credentials supplied via `.env` (copy from `env.example` — YouTube API key, OAuth client, Spotify, GitHub PAT). Full setup steps are in `HOWTO_CHANNEL.md`.

## Dashboard

`index.html` is served via GitHub Pages. Decision editing (Buy / Choose / Pass) requires a GitHub PAT entered through the 🔑 auth button.
