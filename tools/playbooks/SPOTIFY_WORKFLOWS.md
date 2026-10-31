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

**Choosing a "New Music <Month>" list from the cache:** an artist belongs to the
month when `latest_release.date` **or** `previous_release.date` falls in it. A
refresh in the first days of the next month can replace a late-month release
with an early-next-month one; the replaced release moves to `previous_release`
rather than disappearing, so reading `latest_release` alone silently drops those
artists. Build when the **`[releases] ready for <Month> New Releases`** mail
arrives: it is sent by the run that finishes the month-end window, and its body
already lists every cached release dated in the month. If the window hit its
hard stop first, the subject says how many artists were left unchecked and the
body names them. (#433)

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
- **End-of-month window** (#396, #433): `scripts/release_window.py` holds the
  calendar maths. The **anchor** is the month's last Friday when the month ends
  Sat/Sun/Mon, otherwise the month's last day. From the anchor until nothing is
  pending (hard stop on the 7th), each scheduled run spends up to 85 calls with
  `--stale-days` = days since the anchor + 1 and `--active-first` (artists with
  a release in the last two years before the quiet tail). The weekly
  `--new-artist` resolve skips while the window is open and the portrait heal
  runs on the 8th, so the window gets the day's whole budget. Window runs pace
  calls 4s apart and sleep through a short 429 (up to 10 minutes) instead of
  bailing - the first window run, 10/30, tripped a ~5-minute burst throttle after
  75 calls at the default 2s spacing. Expected finish:
  active artists about 3-4 days after month end, the whole ~500 roster about
  4-5. The regular trickle rate doesn't change that - every entry is re-checked
  after the anchor anyway. Schedule-only: a manual `workflow_dispatch` always
  gets exactly the limit/stale-days typed (or the 25/25 default).
- Before building a playlist inside the window, remember the window is spending
  most of the app's ~100/day ceiling; build the day the ready mail arrives
  (the window is idle from then on) or later.
- `--count-pending` previews how many artists a given `--stale-days` value
  would actually touch, before spending real quota.
- A bare (no explicit `--stale-days`) manual run self-resumes across
  rate-limit bails via that auto-inferred, band-aware heuristic,
  oldest-checked-first — the ad-hoc path, not what the schedule uses.
- Bare `--new-artist` populates every cache entry still missing a `spotify_id`
  (known unresolvables excluded); run it before a release sweep so new artists
  get stamped in the same cycle.
- **Where names come from:** `collect_artists()` reads a fixed list of
  `(file, columns)` pairs in `_tsv_sources()`, matched by **exact** column name
  with no fallback. The support column is named differently in each file:
  `Supporting Artist` (current), `Support` (potentials), `Supporting Acts`
  (history). A wrong name drops that column silently. Fixing one, or adding a
  source, seeds every newly collected name as a null-id skeleton on the next
  `--refresh-lastfm`, and the weekly `--new-artist` pass then resolves them by
  name, ~3 Spotify calls each.
- **Before a source change lands,** list the names it adds and park the ones a
  name-only search would mis-resolve (hyperlocal acts, one-off benefit bills,
  short or common names) in `data/spotify_unresolvable.tsv` as `no_presence`,
  in a `staging` commit that lands first. Parked names are dropped before
  seeding, so they never become skeletons. Size the weekly `--limit` to the
  backlog (about 3 calls per name), finish it before the month-end window opens,
  then put the limit back.
