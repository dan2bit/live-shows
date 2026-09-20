# SPOTIFY_WORKFLOWS.md

The three agentic Spotify workflows (#73), run conversationally with two tools:

- **`spotify-write` MCP** (marcelmarais server, user-OAuth) — the only component
  holding an account-capable token. Creates/modifies playlists, reads own private
  playlists, searches. Setup lore: `docs/FORK_SETUP.md` § Spotify.
- **`data/artist_spotify.json`** (the cache, built by `scripts/spotify_cache.py`
  under read-only client credentials) — the durable name→id/URL map plus
  `latest_release` and Last.fm enrichment. Prefer cached ids over live search;
  fall back to `searchSpotify` only for artists outside the cache, and eyeball
  same-name matches (Dev-mode search caps at ~10 results and occasionally grabs
  the wrong artist).

**Sequencing convention:** resolve artists from repo data first (cache →
`recommend_aliases.tsv` variants → live search), then read tracks, then write the
playlist, then hand back the `open.spotify.com/playlist/...` URL in-chat.

---

## Workflow A — Show sampler

"Make a sampler for all the bands I'm seeing in July."

1. Pull upcoming rows from `data/live_shows_current.tsv` (`Status = upcoming`,
   date-windowed per the ask) — headliners **and** `Supporting Artist` values
   (split multi-act strings on `/`).
2. Resolve each to a Spotify id (cache first).
3. A few top tracks per artist — or one per artist for a tight sampler.
4. `createPlaylist` + `addTracksToPlaylist`; return the URL.

Precedent: the "July Live Shows" and "New Music <Month>" playlists; monthly
new-release adds follow the one-representative-track-per-release convention
(singles: the title track; albums: opener or focus track; avoid duplicating a
track already carried by an earlier month's list).

## Workflow B — Multi-artist bill top tracks

"The most-played songs from all the artists who played the John Prine show."

1. Get the bill from `live_shows_current.tsv` / `data/history/*.tsv`
   (`Supporting Acts`) or the `data/setlists/<year>.json` entry for MULTI shows.
2. Per-artist top tracks ("most played" = **global Spotify popularity** — personal
   play counts are not available per-arbitrary-artist; confirmed acceptable).
3. Return a ranked list, a playlist, or both.

## Workflow C — Unseen-playlist → research

"Add the artists in this playlist I haven't seen to research."

1. Read the playlist's tracks (`getPlaylistTracks` — user token covers own
   private playlists; public ones read with anything).
2. Unique artists → cross-reference the seen set (`data/artists.tsv`,
   `data/history/*`, attended current rows, via the alias map).
3. Append not-seen / not-tracked artists to
   `tools/research/follows/new_artist_research.tsv` — **a GitHub commit via the
   MCP (staging), not a Spotify write**. `spotify_cache.py --add-artist --to
   research` builds cache-ready rows.

---

## Playlist-link persistence (decided 2026-07-02)

**Ephemeral by default.** Created playlists live on Spotify; the URL is handed
back in-chat and not recorded in the repo. The `Playlist URL` column in
`live_shows_current.tsv` is YouTube's, and a sampler spans multiple shows, so no
per-show field fits. If retention is ever wanted, the designated home is a new
`tools/personal-data/spotify_playlists.tsv` ledger — create it only when Dan
says "persist"; until then, don't.

## Cadence notes

- The daily `--refresh-releases` cron always passes an **explicit**
  `--stale-days` — never bare. `_infer_stale_days()`'s band-aware auto-inference
  exists in the script, but only a manual, bare invocation ever exercises it;
  the schedule doesn't rely on it. Normal days: `--limit 25`.
- **End-of-month ramp:** two distinct phases raise the budget to `--limit 45`
  around the month boundary — the last 5 days of the month (backlog-clear,
  `--stale-days` unchanged) and the first 3 days of the next month (a
  deliberate re-verify pass, `--stale-days` dropped to 5 so whoever the
  tail-end ramp already checked becomes re-checkable in time to catch a
  release in their last few days of the covered month). Full rationale lives
  in the workflow's own header comment and `docs/ISSUE_LOG.md`. Schedule-only
  — a manual `workflow_dispatch` always gets exactly the limit/stale-days
  typed (or the 25/25 default), ramp or no ramp.
- `--count-pending` previews how many artists a given `--stale-days` value
  would actually touch, before spending real quota.
- A bare (no explicit `--stale-days`) manual run self-resumes across
  rate-limit bails via that auto-inferred, band-aware heuristic,
  oldest-checked-first — the ad-hoc path, not what the schedule uses.
- Bare `--new-artist` populates every cache entry still missing a `spotify_id`
  (known unresolvables excluded); run it before a release sweep so new artists
  get stamped in the same cycle.
