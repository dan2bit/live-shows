# live-shows

Concert tracking system for the [@dan2bit](https://www.youtube.com/@dan2bit) YouTube channel.

Tracks attended and upcoming shows, potential purchases, venue intelligence, artist follow lists, and YouTube bootleg playlist management — managed collaboratively with [Claude](https://claude.ai) via MCP tools.

---

## Key Files

| File | Purpose |
|---|---|
| `live_shows_current.tsv` | Confirmed shows — attended and upcoming |
| `live_shows_potential.tsv` | Shows under consideration (Buy / Choose / Sell / Pass) |
| `artists.tsv` | Artist follow list with show history |
| `venues.tsv` | Venue details — parking, transit, seating, box office |
| `autograph_books_combined.tsv` | Autograph book inventory |
| `spending.tsv` | Annual spending summary |
| `index.html` | Browser-based show dashboard (GitHub Pages) |

## Directories

| Directory | Purpose |
|---|---|
| `follows/` | Artist follow lists by tier |
| `history/` | Archived yearly show history |
| `web-src/` | Raw service exports (prefixed by account) |
| `archive/` | Superseded files |
| `logs/` | Script run logs |

## Scripts

| Script | Purpose |
|---|---|
| `youtube_create_playlists.py` | Create and update YouTube playlists from show history |
| `youtube_fix_descriptions.py` | Sync playlist descriptions |
| `youtube_fetch.py` | Fetch video metadata from YouTube API |
| `youtube_correlate.py` | Correlate videos to shows |
| `youtube_fill_handles.py` | Fill missing YouTube channel handles in artists.tsv |
| `youtube_audit_blanks.py` | Audit shows missing playlist URLs |
| `rollover.py` | Year-end migration from live_shows_current.tsv to history/ |

## Setup

```bash
cd live-shows
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # if present
cp .env.example .env              # fill in your credentials
```

See `.env.example` for required credentials (YouTube API, Spotify, GitHub PAT).

## Documentation

- `PROJECT.md` — comprehensive project reference and workflow rules
- `ANALYSIS_WORKFLOWS.md` — quarterly and monthly research workflows
- `EMAIL_WORKFLOWS.md` — inbox processing routines (Gmail label-based)

## Dashboard

The `index.html` dashboard is served via GitHub Pages at:

`https://dan2bit.github.io/live-shows/`

Decision editing (Buy/Choose/Pass) requires a GitHub PAT entered via the 🔑 auth button.
