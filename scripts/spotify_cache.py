#!/usr/bin/env python3
"""
spotify_cache.py — Build data/artist_spotify.json from every artist in the repo.

Pulls a Spotify resolution anchor (artist id + URL) and the most recent release
for the full set of artists that appear anywhere in the live-shows repo, and
writes a single deterministic JSON cache, keyed by canonical artist name.
Consumers:

  - sampler MCP workflow      -> spotify_id / spotify_url as a resolution anchor
  - artist research / follow  -> latest-release recency (popularity/followers/
                                 genres are no longer available app-only — see
                                 STRIPPED METADATA below)
  - (optional) the site       -> clickable artist name -> Spotify page

AUTH
    Spotify Client Credentials (app-only) — the same SPOTIFY_CLIENT_ID /
    SPOTIFY_CLIENT_SECRET already used by tools/youtube/youtube_fill_handles.py.
    No user OAuth, no quota limit. Only endpoints still reachable app-only on a
    Development-mode app are used: GET /search (id resolution, only when there's
    no stored or cached id) and GET /artists/{id}/albums (latest release). The
    plain GET /artists/{id} call was dropped — see RATE LIMITS.

METADATA-ONLY (no top tracks)  — updated 2026-06-22
    This cache deliberately does NOT store per-artist top tracks. Spotify's
    Feb/Mar-2026 API migration (effective 2026-02-11; all Dev-mode apps by
    2026-03-09) restricted GET /artists/{id}/top-tracks for app-only auth — it
    now returns 403 Forbidden under Client Credentials on a Dev-mode app. The
    user-OAuth path (the marcelmarais MCP server) is no substitute: it exposes
    only the *user's own* top tracks (/me/top/tracks), not an arbitrary artist's,
    and there is no public artist-top-tracks endpoint reachable from it. So track
    selection for samplers happens at assembly time via the MCP's searchSpotify
    (results come back in relevance order — Spotify search has no sort param —
    so picks must be eyeballed, not trusted as a true top-10). Related-artists
    and recommendations were removed in the 2024-11-27 cull and are likewise
    absent. If the app is ever promoted out of Dev mode (Extended Quota), revisit
    restoring a top_tracks field here.

STRIPPED METADATA (no popularity / followers / genres)  — added 2026-06-23
    These three fields were the cache's original analytical payload. Spotify's
    Feb/Mar-2026 Dev-mode migration removed them from the /artists/{id} response
    under app-only (Client Credentials) auth. It's a field-level removal tied to
    Development mode, not to the auth flow, so the user-OAuth path (the
    marcelmarais MCP token) does NOT recover them either — only Extended Quota
    Mode would, which is out of reach for a personal app. So build_entry no longer
    stores them; the cache is now a resolution map (id/url) + latest_release.
    The lost popularity/genre signal is backfilled from a separate source
    (Last.fm) as its own refreshable layer, in a follow-on change — not here.

RATE LIMITS  — added 2026-06-23
    Spotify's Feb/Mar-2026 Dev-mode limits are tight: a 429 can carry a multi-HOUR
    Retry-After (observed ~22h). So api_get caps its sleep at MAX_BACKOFF and
    raises RateLimited on anything longer — and on exhausted retries — so the run
    BAILS, keeping its periodic checkpoints, instead of sleeping for hours or
    churning every remaining artist into a false 'unresolved'. To keep request
    volume down per build: build_entry makes ONE call (latest_release); a stored
    or cached id skips the /search; and non-artist rows (festival/event names in
    the Artist column of Pass potentials) are dropped before resolution via
    _is_non_artist (explicit set + "festival" substring) so they never cost a call.
    Pace the calls with --delay (default 2.0s) — raise it on a big first build to
    stay under the limit, lower it once limits relax or for the lighter passes.
    A multi-day --refresh-releases back-audit resumes across the daily cap with
    --stale-days (see LATEST RELEASE / that flag's help).

LATEST RELEASE  — added 2026-06-23
    Each entry carries a `latest_release` object — the artist's most recent
    album/single — from GET /artists/{id}/albums (a plain catalog read, reachable
    app-only; not in the migrated-restricted set). include_groups is album,single
    only (the releases most likely to be played at an upcoming show); compilation
    and appears_on are excluded so a best-of or a guest feature can't make a
    dormant artist look active. Shape:
        "latest_release": {
          "date": "2026-06-19", "precision": "day",   # day|month|year
          "name": "...", "type": "single",            # album|single
          "spotify_id": "...", "url": "..."
        }
    plus "latest_release_checked": "YYYY-MM-DD". `precision` is stored because
    Spotify's release_date can be year- or month-only (back catalogue); any
    "days since" math downstream must tolerate that. `name`/`type` make a
    re-release / anniversary edition (a fresh date on old material) auditable by
    eye. `latest_release` is null when the artist has no qualifying album/single.
    NOTE: one /albums call with limit=10 — the endpoint's MAX (it 400s "Invalid
    limit" above 10, unlike most Spotify list endpoints which allow 50). Results
    come back newest-first, so the most recent is effectively always in-window;
    a hyper-prolific artist's newest could in theory fall past item 10, which a
    later --refresh-releases would self-correct. (Sample across the cache once it
    exists to confirm 10 never misses; bump to pagination only if it does.)

    The "most recent" pick pads partial dates to the *start* of their period for
    comparison only (a year-only 2026 sorts as 2026-01-01, so a dated 2026-06-19
    in the same year correctly outranks it); the original release_date + precision
    are what get stored.

    MISATTRIBUTION GUARD (#100)  — added 2026-06-27
        /artists/{id}/albums has been observed returning an album that belongs to
        a different artist for the given id (a Bach recording surfaced under
        Angelique Francis). Since the bad album was the newest, it won the pick
        and was cached as her latest_release, then rode into a "new releases"
        list. latest_release now filters the page through _album_credits_artist
        (our id among the album's credited artists, or an alias-aware name match
        as a backstop) BEFORE selecting the newest, so a mis-link can neither be
        stored nor displace the real release — the correct one is recovered from
        elsewhere in the same page. Drops are logged rejected-only (bounded by
        anomaly count, not traffic). The guard runs in both the build and the
        refresh paths, so a full --refresh-releases re-validates the whole cache
        as a side effect at no extra quota. That sweep is ~317 calls ≈ 3-4 days
        under the cap; --stale-days makes it resumable day to day (see below).

    RESUMABLE RELEASE SWEEP (--stale-days)  — added 2026-06-27
        refresh_releases walks sorted(cache) top-down and, by default, re-pulls
        every entry — so a naive daily re-run under the ~100/day cap re-burns the
        first ~100 names and never advances. --stale-days N skips entries whose
        latest_release_checked is within the last N days, so each daily run picks
        up past what an earlier run in the same sweep already refreshed. Opt-in:
        unset = refresh everything (unchanged behavior), so a deliberate full
        re-pull still does exactly that. Pick N > sweep length (7 covers the 3-4
        day, ~317-artist sweep).

    NULL-PRESERVE GUARD (#109)  — added 2026-06-29
        A null pull (no album/single credited to the id, app-only / market=US)
        must NOT overwrite a non-null cached latest_release. App-only Dev-mode
        returns ∅ for artists who demonstrably have releases (confirmed via the
        user-OAuth path); the old code stored that ∅ AND stamped the entry fresh,
        so a real release was both lost and then skipped by the next --stale-days
        sweep. Both write paths (refresh_releases and the main build loop) now
        keep the cached release when a pull comes back null, and refresh_releases
        leaves latest_release_checked untouched so the entry is retried rather
        than locked as a false null. Genuinely new artists (no prior entry) still
        store null correctly — the guard only fires when there's data to protect.

    Display/badging on this date (a "NEW" badge in the show lists) and recency
    weighting in follow-tier / potentials decisions are deliberately OUT of scope
    here — this only captures and caches the data. See #85 / follow-on tickets.

LAST.FM ENRICHMENT  — added 2026-06-25
    A separate, independently-refreshable `lastfm` block backfills the analytical
    signal Spotify's Dev-mode migration stripped (popularity/followers/genres).
    Populated ONLY by --refresh-lastfm; the Spotify build/refresh never reads it,
    and a Spotify --refresh PRESERVES any existing block. Needs no Spotify creds —
    it uses the free Last.fm API (api_key only).
    --refresh-lastfm also SEEDS: it collects the full repo artist set and creates a
    Spotify-null skeleton (spotify_id / spotify_url / latest_release = null) for any
    artist Spotify hasn't resolved yet, so one Last.fm pass covers the whole roster
    even while the Spotify side drips in over the daily Dev-mode quota. The next
    Spotify build fills those skeletons in (default add-missing mode treats a null
    spotify_id as "not yet resolved") and preserves the lastfm block. Per-artist
    shape:
        "lastfm": {
          "mbid": "...",                 # MusicBrainz id (cross-source join key)
          "url": "https://www.last.fm/music/...",
          "listeners": 123456,           # global popularity proxy (null if unknown)
          "playcount": 9876543,
          "tags": ["blues", "americana", ...],   # <= LASTFM_TAGS, folksonomy
          "similar": ["...", ...]                 # <= LASTFM_SIMILAR, discovery feed
        }
    plus "lastfm_checked": "YYYY-MM-DD"; both absent until --refresh-lastfm runs,
    and "lastfm" is null for an artist Last.fm can't find. Tags are crowd-sourced
    (mood / "seen live" noise mixed with real genres) — filter before trusting
    them as a genre signal.

USAGE
    python3 spotify_cache.py                 # add artists not yet in the cache
    python3 spotify_cache.py --refresh       # full re-pull (metadata + release) for ALL
    python3 spotify_cache.py --refresh-releases  # re-pull ONLY latest_release for cached artists
    python3 spotify_cache.py --refresh-releases --stale-days 7  # resumable multi-day release back-audit (skips entries refreshed in the last 7 days)
    python3 spotify_cache.py --refresh-lastfm    # seed all repo artists + enrich them from Last.fm
    python3 spotify_cache.py --refresh --prune   # ...and drop artists no longer in the repo
    python3 spotify_cache.py --artist "Larkin Poe"   # one artist (substring, case-insensitive)
    python3 spotify_cache.py --add-artist "Eric Ambel" --to research  # resolve + append a cache-ready row (--to: research | fast_track | seen_with)
    python3 spotify_cache.py --delay 1       # speed up the lighter passes (default 2.0s)
    python3 spotify_cache.py --dry-run       # report planned changes, write nothing

OUTPUT  data/artist_spotify.json — deterministic (sorted keys), so a periodic
        full refresh produces small, localized diffs. Committed to the repo on
        purpose: a fresh agentic session and the site both read it from there.

ENV     SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET in scripts/.env (gitignored)
        or inherited from the environment. LASTFM_API_KEY (same .env) is required
        only for --refresh-lastfm; the Spotify build does not need it.

NOTE    Canonicalization here applies the explicit data/recommend_aliases.tsv map
        plus a de-invert step ("Wood Brothers, The" -> "The Wood Brothers", so the
        sortable form artists.tsv uses shares one cache key with the natural form).
        collect_artists also splits '/'-joined support bills into their individual
        acts and folds "X Band" into a collected bare "X" (see there) — both
        mirroring scripts/build_recommend_index.py. It does NOT replicate that
        script's de-accent / strip-apostrophe normalization, so an accent- or
        apostrophe-only variant can still split into two entries; fix those at the
        source or extend this step if they accumulate.
"""

import argparse
import csv
import glob
import json
import os
import re
import sys
import time
import unicodedata
from datetime import date

try:
    import requests
except ImportError:
    sys.exit("Missing dependency: requests\nRun: pip install requests")

try:
    from dotenv import load_dotenv
except ImportError:
    sys.exit("Missing dependency: python-dotenv\nRun: pip install python-dotenv")


# ── Paths ─────────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))           # scripts
REPO_ROOT  = os.path.dirname(SCRIPT_DIR)         # repo root
DATA_DIR   = os.path.join(REPO_ROOT, "data")
FOLLOWS    = os.path.join(REPO_ROOT, "tools", "research", "follows")

ALIASES_TSV = os.path.join(DATA_DIR, "recommend_aliases.tsv")
OUTPUT_JSON = os.path.join(DATA_DIR, "artist_spotify.json")

load_dotenv(os.path.join(SCRIPT_DIR, ".env"))


# ── Spotify config ────────────────────────────────────────────────────────────

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API       = "https://api.spotify.com/v1"
MARKET            = "US"      # /artists/{id}/albums market filter (release availability)
ALBUMS_LIMIT      = 10        # /artists/{id}/albums MAX page size (>10 => 400 "Invalid limit")
DELAY             = 2.0       # default inter-call spacing (s); override per-run with --delay
SAVE_EVERY        = 25        # incremental checkpoint so a long run survives an interruption
SEARCH_MIN_SCORE  = 0.55      # min name-match confidence to accept a search hit
MAX_BACKOFF       = 60        # cap 429 sleeps; longer Retry-After => bail (Dev-mode lockouts run hours)
DEFAULT_RETRY_AFTER = 5       # assumed wait when a 429 carries no Retry-After header

# Last.fm enrichment (separately refreshable; only --refresh-lastfm uses these)
LASTFM_API     = "https://ws.audioscrobbler.com/2.0/"
LASTFM_UA      = "live-shows-artist-cache/1.0 (+https://github.com/dan2bit/live-shows)"
LASTFM_TAGS    = 5    # max tags stored per artist
LASTFM_SIMILAR = 5    # max similar artists stored per artist

_ARTIST_ID_RE = re.compile(r"artist[:/]([A-Za-z0-9]+)")


class RateLimited(Exception):
    """Spotify 429 with a Retry-After above MAX_BACKOFF — Dev-mode lockouts can be
    many hours. Raised so the run bails (preserving checkpoints) instead of
    sleeping for hours or churning every remaining artist into a false
    'unresolved'."""

    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"rate-limited; Retry-After {retry_after}s")


# ── Source files: (path, [artist-bearing columns], [url columns]) ─────────────
# Comment-prefixed (#) and blank lines are stripped before the header is read,
# so fast_track.tsv and recommend_aliases.tsv parse cleanly. Missing files and
# missing columns are tolerated.

def _tsv_sources():
    sources = [
        (os.path.join(DATA_DIR, "artists.tsv"),               ["Artist"], ["Spotify URL"]),
        (os.path.join(DATA_DIR, "live_shows_current.tsv"),    ["Artist", "Supporting Artist"], []),
        (os.path.join(DATA_DIR, "live_shows_potential.tsv"),  ["Artist", "Support"], []),
        (os.path.join(DATA_DIR, "fast_track.tsv"),            ["Artist"], ["Spotify URL"]),
        (os.path.join(FOLLOWS,  "follows_master.tsv"),        ["Artist"], []),
        (os.path.join(FOLLOWS,  "new_artist_research.tsv"),   ["Artist"], []),
        # seen_with.tsv (#97): session/sit-in/supergroup members. Read the "Seen
        # With" column (the member); its "Spotify URL" is the member's own URL, a
        # free resolution hint. Headliner is NOT read here — those names already
        # come from the show files, so re-reading them adds only redundant source
        # tags. Placed after artists.tsv so the ledger's URL wins for any member
        # who is also a tracked headliner (first-wins in collect_artists' add()).
        (os.path.join(DATA_DIR, "seen_with.tsv"),             ["Seen With"], ["Spotify URL"]),
    ]
    sources += [(p, ["Artist", "Supporting Artist"], []) for p in sorted(glob.glob(os.path.join(DATA_DIR, "history", "*.tsv")))]
    # Multi-artist setlist files: read an "Artist" column if one exists, else skip.
    # (Setlist schema isn't fixed; refine here if a dedicated bill format lands.)
    sources += [(p, ["Artist"], []) for p in sorted(glob.glob(os.path.join(DATA_DIR, "setlists", "*.tsv")))]
    return sources


def _source_tag(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


# ── Name normalisation & similarity (mirrors youtube_fill_handles.py) ─────────

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"^the\s+", "", s).strip()
    return s


def _tokens(s: str) -> set:
    noise = {"and", "the", "feat", "with", "live", "official", "music", "band"}
    return {w for w in _norm(s).split() if len(w) > 2 and w not in noise}


def similarity(a: str, b: str) -> float:
    if _norm(a) == _norm(b):
        return 1.0
    wa, wb = _tokens(a), _tokens(b)
    if not wa or not wb:
        return 0.0
    jaccard = len(wa & wb) / len(wa | wb)
    an, bn = _norm(a), _norm(b)
    shorter, longer = (an, bn) if len(an) <= len(bn) else (bn, an)
    if len(shorter) > 5 and shorter in longer:
        jaccard = max(jaccard, 0.75)
    return jaccard


# Non-artist rows that pollute the collected set — festival/event names sitting
# in the Artist column of Pass potentials. Skipped before Spotify resolution so
# they don't waste a resolve call. The "festival" substring catches future rows;
# add oddly-named events (no "festival" in the name — e.g. a tribute/celebration
# concert) to _SKIP_ARTISTS by hand.
_SKIP_ARTISTS = {"all things go music festival", "hot august music festival",
                 "john prine celebration"}

# Real-looking strings that resolve to NO single Spotify artist and should be
# dropped before resolution so they stop costing a /search call every run
# (#97 / #73). Keep this list TIGHT — it is NOT a dumping ground for "didn't
# resolve". Only two kinds belong here:
#   1. A genuine artist with zero Spotify presence (e.g. Eli Kollman — a support
#      act seen once, no catalogue anywhere).
#   2. A bill name that exists ONLY as an amalgamation of members who each have
#      their own Spotify entity, with no entry for the combined name (e.g.
#      "SatchVai Band" — Spotify lists their joint EP under Joe Satriani AND
#      Steve Vai separately, never under "SatchVai Band"; both members are already
#      in seen_with.tsv, so skipping the bill suppresses nothing).
# Do NOT add combined "X & Y" bills whose components are real, separately-resolvable
# artists you want in the cache/NAR (JD Simo & Luther Dickinson, Sarah Borges &
# Eric Ambel, Laka Soul). Those are a SPLIT problem, not a skip — splitting
# "&"-bills into their components is tracked in #94. Suppressing them here would
# also hide real artists (e.g. Luther Dickinson = North Mississippi Allstars,
# already seen). Normalised through _norm so "&"/accents match the collected names.
_UNRESOLVABLE_ARTISTS = {_norm(x) for x in (
    "Eli Kollman",
    "SatchVai Band",
    "TJ Turqman",          # local session bassist (seen_with only) — no Spotify catalogue
    "The Side Cars Band",  # tribute band — no independent Spotify entity
)}


def _is_non_artist(name: str) -> bool:
    n = _norm(name)
    return n in _SKIP_ARTISTS or n in _UNRESOLVABLE_ARTISTS or "festival" in n


# ── TSV reading (comment-tolerant) ────────────────────────────────────────────

def read_tsv_rows(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        lines = [ln for ln in f if not ln.lstrip().startswith("#") and ln.strip()]
    if not lines:
        return []
    return list(csv.DictReader(lines, delimiter="\t"))


def load_aliases() -> dict[str, str]:
    """Map _norm(alias) -> canonical surface form, from data/recommend_aliases.tsv."""
    amap: dict[str, str] = {}
    for row in read_tsv_rows(ALIASES_TSV):
        alias = (row.get("Alias") or "").strip()
        canon = (row.get("Canonical") or "").strip()
        if alias and canon:
            amap[_norm(alias)] = canon
    return amap


_INVERTED_ARTICLE_RE = re.compile(r"^(.*),\s*(the|a|an)$", re.IGNORECASE)


def _deinvert(name: str) -> str:
    """Fold a sortable inverted form into natural order: 'Wood Brothers, The' ->
    'The Wood Brothers'. Other names pass through unchanged. artists.tsv stores the
    inverted form for its own A-Z sort, while the history/current rows and the
    follow lists use natural order, so the same band otherwise lands under two
    cache keys (the inverted one and the natural one)."""
    m = _INVERTED_ARTICLE_RE.match(name)
    return f"{m.group(2).capitalize()} {m.group(1)}" if m else name


def canonical(name: str, amap: dict[str, str]) -> str:
    # Explicit nickname/expansion aliases first (Kingfish -> Christone 'Kingfish'
    # Ingram), THEN fold the inverted 'X, The' article so the sortable form used in
    # artists.tsv shares one cache key with the natural form used everywhere else.
    name = name.strip()
    return _deinvert(amap.get(_norm(name), name))


# ── Collect the repo-wide artist universe ─────────────────────────────────────

_BILL_MORE_RE = re.compile(r"\s*\+\s*\d*\s*more$", re.IGNORECASE)


def _split_support(cell: str):
    """Yield the individual acts on a support bill. A Support / Supporting Artist
    cell can list several acts on one '/'-separated line ("A / B / C + more");
    collected whole it becomes a single bogus cache key that resolves to nothing.
    Splits on '/' and trims a trailing '+ N more', mirroring the support-harvest in
    scripts/build_recommend_index.py so both consumers read bills the same way."""
    for tok in (cell or "").split("/"):
        tok = _BILL_MORE_RE.sub("", tok.strip()).strip()
        if len(tok) > 2 and tok.lower() != "more":
            yield tok


def collect_artists(amap: dict[str, str]) -> tuple[dict[str, set], dict[str, str]]:
    """Return ({canonical_name: {source tags}}, {canonical_name: spotify_url_hint})."""
    artists: dict[str, set] = {}
    url_hints: dict[str, str] = {}

    def add(raw: str, tag: str, url: str | None = None):
        raw = (raw or "").strip()
        if not raw or _is_non_artist(raw):
            return
        canon = canonical(raw, amap)
        artists.setdefault(canon, set()).add(tag)
        if url:
            url = url.strip()
            if url and canon not in url_hints:
                url_hints[canon] = url

    for path, name_cols, url_cols in _tsv_sources():
        tag = _source_tag(path)
        for row in read_tsv_rows(path):
            url = next((row.get(c, "").strip() for c in url_cols if row.get(c, "").strip()), None)
            # name_cols[0] is the headliner (one act, carries the url hint);
            # name_cols[1:] are support column(s), each a possible '/'-joined bill.
            if name_cols:
                add(row.get(name_cols[0], ""), tag, url)
            for col in name_cols[1:]:
                for act in _split_support(row.get(col, "")):
                    add(act, tag, None)

    # Fold "X Band" into "X" when the bare "X" is itself a collected artist, so
    # "Ally Venable Band" and "Ally Venable" share one entry (build_recommend_index
    # treats them as one via a drop-Band match key). Conditional on the bare form
    # already existing — a blanket drop-Band would mangle standalone names whose
    # last word is "Band" (Tedeschi Trucks Band, The Dirty Dozen Brass Band) and
    # break their Spotify resolution; a lone "Lilly Hiatt Band" with no bare twin
    # likewise keeps its full name (it still resolves — _tokens drops "band").
    for key in [k for k in artists if re.search(r"\S\s+[Bb]and$", k)]:
        bare = re.sub(r"\s+[Bb]and$", "", key)
        if bare in artists:
            artists[bare] |= artists.pop(key)
            if key in url_hints:
                url_hints.setdefault(bare, url_hints[key])
                del url_hints[key]

    return artists, url_hints


# ── Spotify Web API ───────────────────────────────────────────────────────────

_token_cache: dict = {}


def _get_token(client_id: str, client_secret: str, force: bool = False) -> str:
    if not force and _token_cache.get("token"):
        return _token_cache["token"]
    resp = requests.post(
        SPOTIFY_TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=15,
    )
    resp.raise_for_status()
    _token_cache["token"] = resp.json()["access_token"]
    return _token_cache["token"]


def _retry_after_seconds(resp) -> int:
    """Retry-After in seconds. Per spec it's delta-seconds or an HTTP-date; on a
    date or an unparseable value, assume a long wait so the caller bails rather
    than guesses. Missing header => DEFAULT_RETRY_AFTER."""
    raw = resp.headers.get("Retry-After")
    if raw is None:
        return DEFAULT_RETRY_AFTER
    try:
        return int(raw)
    except ValueError:
        return MAX_BACKOFF + 1


def api_get(path: str, params: dict, creds: tuple[str, str]) -> dict | None:
    """GET {SPOTIFY_API}{path} with one 401 refresh-retry and CAPPED 429 backoff.

    Raises RateLimited when Spotify asks for a wait above MAX_BACKOFF (Dev-mode
    lockouts run to hours) — the caller checkpoints and exits instead of sleeping
    for hours. Also raises once retries are exhausted while still throttled, so a
    sustained 429 doesn't churn every remaining artist into a false 'unresolved'.
    """
    url = f"{SPOTIFY_API}{path}"
    for attempt in range(4):
        token = _get_token(*creds)
        resp = requests.get(url, params=params,
                            headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if resp.status_code == 401:
            _get_token(*creds, force=True)
            continue
        if resp.status_code == 429:
            wait = _retry_after_seconds(resp)
            if wait > MAX_BACKOFF:
                raise RateLimited(wait)
            print(f"    rate-limited; sleeping {wait + 1}s")
            time.sleep(wait + 1)
            continue
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    raise RateLimited(MAX_BACKOFF)


def extract_artist_id(url: str) -> str | None:
    if not url:
        return None
    m = _ARTIST_ID_RE.search(url)
    return m.group(1) if m else None


def resolve_artist_id(name: str, url_hint: str | None, creds,
                      cached_id: str | None = None, cached_url: str = "") -> tuple[str | None, str]:
    """Prefer the id parsed from a stored Spotify URL (free, picks up corrections);
    then a cached id (avoids re-searching on --refresh); else search by name."""
    aid = extract_artist_id(url_hint or "")
    if aid:
        return aid, url_hint
    if cached_id:
        return cached_id, cached_url or url_hint or ""
    data = api_get("/search", {"q": name, "type": "artist", "limit": 5}, creds)
    items = (data or {}).get("artists", {}).get("items", [])
    best, best_score = None, 0.0
    for it in items:
        score = similarity(name, it.get("name", ""))
        if score > best_score and it.get("id"):
            best, best_score = it, score
    if best and best_score >= SEARCH_MIN_SCORE:
        return best["id"], best.get("external_urls", {}).get("spotify", "")
    return None, ""


def _release_sort_key(rd: str) -> str:
    # Pad a partial release_date to YYYY-MM-DD for comparison ONLY, anchored at the
    # START of the period (year-only 2026 -> 2026-01-01), so a more precise date in
    # the same period outranks it. The original release_date is what gets stored.
    parts = (rd or "").split("-")
    y = parts[0] if parts and parts[0] else "0000"
    m = parts[1] if len(parts) > 1 and parts[1] else "01"
    d = parts[2] if len(parts) > 2 and parts[2] else "01"
    return f"{y.zfill(4)}-{m.zfill(2)}-{d.zfill(2)}"


def _album_credits_artist(album: dict, aid: str, artist_name: str | None) -> bool:
    """True if the album is actually credited to this artist (#100 guard).

    /artists/{id}/albums has been observed returning an album that belongs to a
    different artist for the given id (a Bach recording under Angelique Francis).
    Accept on an exact Spotify-ID match against the album's credited artists; fall
    back to an alias-aware name match (same `similarity`/threshold the resolver
    uses) so a legitimate album whose id representation differs isn't false-
    rejected. An album matching on neither — our id absent and only an unrelated
    name credited, which is the #100 case — returns False and is dropped by the
    caller. Residual: a *bidirectional* mis-link that also injects our id into the
    album's own artist list is internally consistent and passes the id check;
    that one is uncatchable from the payload alone (noted on #100)."""
    album_artists = album.get("artists") or []
    if any((a.get("id") or "") == aid for a in album_artists):
        return True
    if artist_name:
        for a in album_artists:
            if similarity(artist_name, a.get("name", "")) >= SEARCH_MIN_SCORE:
                return True
    return False


def latest_release(aid: str, creds, artist_name: str | None = None) -> dict | None:
    """Most recent album/single for an artist, or None if they have none.

    Uses GET /artists/{id}/albums (app-only reachable). include_groups is
    album,single only — compilations and guest features are excluded so they
    can't masquerade as new activity. One call, limit=ALBUMS_LIMIT (10 — the
    endpoint's max; >10 returns 400 "Invalid limit"). Results are newest-first,
    so the most recent is effectively always within the window.

    #100 guard: items not actually credited to this artist (see
    _album_credits_artist) are dropped BEFORE the newest is picked, so a Spotify
    mis-link can neither be stored nor displace the real latest — the correct
    release is recovered automatically when it sits elsewhere in the page. Each
    drop is logged rejected-only (one stderr line), bounded by anomaly count
    rather than traffic. Pass artist_name to enable the name backstop; with it
    None, the guard is id-only.

    Returns None when the artist genuinely has no qualifying release OR when the
    app-only page comes back empty/all-rejected. Callers MUST NOT let a None here
    overwrite a non-null cached latest_release — see the #109 null-preserve guard
    in refresh_releases() and the main build loop.
    """
    data = api_get(f"/artists/{aid}/albums",
                   {"include_groups": "album,single", "market": MARKET, "limit": ALBUMS_LIMIT},
                   creds)
    items = (data or {}).get("items", [])
    if not items:
        return None
    credited, rejected = [], []
    for it in items:
        (credited if _album_credits_artist(it, aid, artist_name) else rejected).append(it)
    for it in rejected:
        credit = ", ".join(a.get("name", "") for a in (it.get("artists") or [])) or "?"
        print(f"    ⚠ #100 guard: dropped '{it.get('name', '')}' ({it.get('id', '')}) — "
              f"credited to [{credit}], not {artist_name or aid}", file=sys.stderr)
    if not credited:
        return None
    best = max(credited, key=lambda it: _release_sort_key(it.get("release_date", "")))
    return {
        "date": best.get("release_date", ""),
        "precision": best.get("release_date_precision", ""),
        "name": best.get("name", ""),
        "type": best.get("album_type", best.get("type", "")),
        "spotify_id": best.get("id", ""),
        "url": (best.get("external_urls") or {}).get("spotify", ""),
        "image_url": _pick_image(best.get("images"), 300),  # album cover — 0 extra calls (#125)
    }


def _pick_image(images, target):
    """URL of the image nearest `target` px wide (Spotify sorts images largest-first)."""
    if not images:
        return ""
    best = min(images, key=lambda im: abs((im.get("width") or 0) - target))
    return best.get("url", "")


def artist_image(aid: str, creds) -> str:
    """Artist portrait URL from GET /artists/{id}.

    Dev-mode Client Credentials strips popularity/followers/genres from this
    endpoint but KEEPS images[] (verified 2026-07-04, #125). One call; batch
    /artists?ids= is 403 under the Dev app, so this is per-artist. Returns "" when
    the artist has no portrait or the pull is empty — callers MUST NOT let that
    overwrite a cached image_url (null-preserve).
    """
    data = api_get(f"/artists/{aid}", {}, creds)
    return _pick_image((data or {}).get("images"), 300)


def build_entry(name: str, sources: set, aid: str, url: str, creds) -> dict:
    # Resolution anchor (id/url) + the artist's latest album/single (see LATEST
    # RELEASE). Still one Spotify call here: spotify_url comes from the resolver
    # or is derived from the id. The portrait (image_url) is fetched separately by
    # --refresh-images (GET /artists/{id} keeps images[] despite the Dev-mode
    # metadata strip, #125), so a build never spends that call — image_url and
    # images_checked start null and are filled by that pass.
    rel = latest_release(aid, creds, name)
    return {
        "spotify_id": aid,
        "spotify_url": url or f"https://open.spotify.com/artist/{aid}",
        "sources": sorted(sources),
        "last_refreshed": date.today().isoformat(),
        "latest_release": rel,
        "latest_release_checked": date.today().isoformat(),
        "image_url": None,          # artist portrait — populated by --refresh-images (#125)
        "images_checked": None,     # cadence anchor for --refresh-images
    }


# ── Output ────────────────────────────────────────────────────────────────────

def load_cache() -> dict:
    if not os.path.exists(OUTPUT_JSON):
        return {}
    with open(OUTPUT_JSON, encoding="utf-8") as f:
        return json.load(f)


def save_cache(cache: dict) -> None:
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


# ── Latest-release-only refresh ───────────────────────────────────────────────

def refresh_releases(cache: dict, creds, args) -> None:
    """Re-pull ONLY latest_release for already-cached artists; leave the rest of
    each entry untouched. Honors --artist, --stale-days, and --dry-run.

    --stale-days N skips entries whose latest_release_checked is within the last N
    days, which makes a multi-day back-audit resumable across the ~100/day cap:
    each daily run advances past what an earlier run already refreshed instead of
    restarting from the top. Unset (default) refreshes every cached artist.

    #109 null-preserve: a null pull never overwrites a non-null cached release,
    and on such a keep the entry's latest_release_checked is left untouched so the
    sweep retries it rather than locking in a false null (and skipping it)."""
    names = sorted(cache)
    if args.artist:
        sub = args.artist.lower()
        names = [n for n in names if sub in n.lower()]
    if not names:
        print("No cached artists to refresh releases for "
              "(run a normal build first, or check --artist).")
        return
    print(f"Refreshing latest_release for {len(names)} cached artist(s)"
          + (f" [skip checked < {args.stale_days}d]" if args.stale_days is not None else "")
          + (" [DRY RUN]" if args.dry_run else "") + "\n")

    updated = 0
    skipped = 0
    kept = 0
    for i, name in enumerate(names, 1):
        entry = cache[name]
        aid = entry.get("spotify_id")
        if not aid:
            print(f"[{i}/{len(names)}] {name}  → no spotify_id, skipped")
            continue
        # --stale-days: skip entries refreshed within the window so a multi-day
        # back-audit resumes across the daily cap instead of re-burning the first
        # ~100 names each run. Entries never checked (null) fall through and
        # refresh. Opt-in: with --stale-days unset, nothing here is skipped.
        if args.stale_days is not None:
            checked = entry.get("latest_release_checked")
            if checked:
                try:
                    if (date.today() - date.fromisoformat(checked)).days < args.stale_days:
                        skipped += 1
                        print(f"[{i}/{len(names)}] {name}  → checked {checked}, "
                              f"skipped (--stale-days {args.stale_days})")
                        continue
                except ValueError:
                    pass  # unparseable stored date → fall through and refresh
        try:
            rel = latest_release(aid, creds, name)
        except RateLimited:
            if not args.dry_run:
                save_cache(cache)
                print(f"    …flushed {len(cache)} cached entries before bailing")
            raise
        time.sleep(DELAY)
        old_rel = entry.get("latest_release")
        old = (old_rel or {}).get("date")
        new = (rel or {}).get("date")
        # Null-preserve guard (#109): a null pull must not wipe a known release.
        # App-only Dev-mode + market=US filtering can transiently return no albums
        # for an artist who has them; overwriting good data with null AND stamping
        # it fresh would both lose the release and hide it from the next
        # --stale-days sweep. Keep the cached release and leave
        # latest_release_checked untouched, so the entry stays eligible for a real
        # refresh instead of locking in a false null.
        if rel is None and old_rel is not None:
            kept += 1
            print(f"[{i}/{len(names)}] {name}  → null pull; kept {old} (not re-checked)")
            print(f"    ⚠ app-only null for {name}; preserved cached {old}", file=sys.stderr)
            continue
        # Secondary (#100 Option 3): a new date older than the stored one is a
        # regression worth a look (stale-cache overwrite or a pulled release).
        # Cheap and rejected-only; does NOT catch the #100 case (its bad date was
        # newer) — that's the membership guard's job, above.
        if old and new and _release_sort_key(new) < _release_sort_key(old):
            print(f"    ⚠ release date regressed {old} → {new} for {name}", file=sys.stderr)

        if args.dry_run:
            change = "unchanged" if old == new else f"{old or '∅'} → {new or '∅'}"
            print(f"[{i}/{len(names)}] {name}  → {change}")
            continue

        entry["latest_release"] = rel
        entry["latest_release_checked"] = date.today().isoformat()
        if old != new:
            updated += 1
            print(f"[{i}/{len(names)}] {name}  → {new or '∅'}"
                  + (f"  (was {old})" if old else ""))
        else:
            print(f"[{i}/{len(names)}] {name}  → {new or '∅'} (unchanged)")
        if (i % SAVE_EVERY) == 0:
            save_cache(cache)
            print("    …checkpoint saved")

    if args.dry_run:
        print("\n[DRY RUN] no changes written"
              + (f"; {kept} kept on null pulls" if kept else "")
              + (f"; {skipped} skipped as still-fresh (--stale-days {args.stale_days})"
                 if args.stale_days is not None else "")
              + ".")
        return
    save_cache(cache)
    print("\n" + "=" * 60)
    print(f"Updated {updated} release date(s) across {len(names)} artist(s)"
          + (f"; kept {kept} on null pulls" if kept else "")
          + (f"; skipped {skipped} still-fresh (--stale-days {args.stale_days})"
             if args.stale_days is not None else "")
          + f". Written: {OUTPUT_JSON}")


def refresh_images(cache: dict, creds, args) -> None:
    """Re-pull ONLY the artist portrait (image_url) for already-cached artists;
    leave the rest of each entry untouched. Mirrors refresh_releases().

    GET /artists/{id} per artist (+1 call each — batch /artists?ids= is 403 under
    the Dev-mode app, #125). Honors --artist, --stale-days (gating on
    images_checked), and --dry-run, so a multi-day portrait back-audit resumes
    across the ~100/day cap. Null-preserve: an empty pull never wipes a cached
    image_url, and leaves images_checked untouched so the sweep retries it rather
    than locking in a false null.
    """
    names = sorted(cache)
    if args.artist:
        sub = args.artist.lower()
        names = [n for n in names if sub in n.lower()]
    if not names:
        print("No cached artists to refresh images for "
              "(run a normal build first, or check --artist).")
        return
    print(f"Refreshing artist portrait for {len(names)} cached artist(s)"
          + (f" [skip checked < {args.stale_days}d]" if args.stale_days is not None else "")
          + (" [DRY RUN]" if args.dry_run else "") + "\n")

    updated = 0
    kept = 0
    skipped = 0
    for i, name in enumerate(names, 1):
        entry = cache[name]
        aid = entry.get("spotify_id")
        if not aid:
            print(f"[{i}/{len(names)}] {name}  → no spotify_id, skipped")
            continue
        if args.stale_days is not None:
            checked = entry.get("images_checked")
            if checked:
                try:
                    if (date.today() - date.fromisoformat(checked)).days < args.stale_days:
                        skipped += 1
                        print(f"[{i}/{len(names)}] {name}  → checked {checked}, "
                              f"skipped (--stale-days {args.stale_days})")
                        continue
                except ValueError:
                    pass  # unparseable stored date -> fall through and refresh
        try:
            img = artist_image(aid, creds)
        except RateLimited:
            if not args.dry_run:
                save_cache(cache)
                print(f"    …flushed {len(cache)} cached entries before bailing")
            raise
        time.sleep(DELAY)
        old = entry.get("image_url")
        # Null-preserve (#109 pattern): an empty pull must not wipe a cached
        # portrait or stamp it fresh — keep it eligible for the next sweep.
        if not img and old:
            kept += 1
            print(f"[{i}/{len(names)}] {name}  → empty pull; kept cached portrait (not re-checked)")
            print(f"    ⚠ app-only empty image for {name}; preserved cached", file=sys.stderr)
            continue
        if args.dry_run:
            change = "unchanged" if (old or "") == (img or "") else ("set" if img else "∅")
            print(f"[{i}/{len(names)}] {name}  → {change}")
            continue
        entry["image_url"] = img or None
        entry["images_checked"] = date.today().isoformat()
        if (old or "") != (img or ""):
            updated += 1
            print(f"[{i}/{len(names)}] {name}  → {'portrait set' if img else '∅ (no image)'}")
        else:
            print(f"[{i}/{len(names)}] {name}  → unchanged")
        if (i % SAVE_EVERY) == 0:
            save_cache(cache)
            print("    …checkpoint saved")

    if args.dry_run:
        print("\n[DRY RUN] no changes written"
              + (f"; {kept} kept on empty pulls" if kept else "")
              + (f"; {skipped} skipped as still-fresh (--stale-days {args.stale_days})"
                 if args.stale_days is not None else "")
              + ".")
        return
    save_cache(cache)
    print("\n" + "=" * 60)
    print(f"Updated {updated} portrait(s) across {len(names)} artist(s)"
          + (f"; kept {kept} on empty pulls" if kept else "")
          + (f"; skipped {skipped} still-fresh (--stale-days {args.stale_days})"
             if args.stale_days is not None else "")
          + f". Written: {OUTPUT_JSON}")


# ── Last.fm enrichment (separately refreshable; --refresh-lastfm only) ─────────

def lastfm_get(params: dict, api_key: str) -> dict | None:
    """GET the Last.fm 2.0 API; parsed JSON or None on transport/HTTP error.
    Last.fm answers HTTP 200 with an {"error": N, ...} body for logical failures
    (e.g. artist not found), so callers must check the body, not just the status."""
    q = {**params, "api_key": api_key, "format": "json"}
    for attempt in range(3):
        try:
            resp = requests.get(LASTFM_API, params=q,
                                headers={"User-Agent": LASTFM_UA}, timeout=15)
        except requests.RequestException:
            return None
        if resp.status_code == 429:
            time.sleep(2 * (attempt + 1))
            continue
        if resp.status_code != 200:
            return None
        try:
            return resp.json()
        except ValueError:
            return None
    return None


def _as_list(v):
    """Last.fm gives a bare dict for a single tag/similar, a list for many, and
    omits the key for none. Normalize to a list."""
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _to_int(x) -> int | None:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def lastfm_artist_info(name: str, api_key: str) -> dict | None:
    """artist.getInfo -> a compact enrichment block, or None if not found / failed.
    autocorrect=1 lets Last.fm fix minor name variants."""
    data = lastfm_get(
        {"method": "artist.getInfo", "artist": name, "autocorrect": "1"}, api_key)
    if not data or "error" in data or "artist" not in data:
        return None
    a = data["artist"]
    stats = a.get("stats") or {}
    tags = [t.get("name", "").strip()
            for t in _as_list((a.get("tags") or {}).get("tag"))
            if isinstance(t, dict) and t.get("name")]
    similar = [s.get("name", "").strip()
               for s in _as_list((a.get("similar") or {}).get("artist"))
               if isinstance(s, dict) and s.get("name")]
    return {
        "mbid": a.get("mbid", "") or "",
        "url": a.get("url", "") or "",
        "listeners": _to_int(stats.get("listeners")),
        "playcount": _to_int(stats.get("playcount")),
        "tags": tags[:LASTFM_TAGS],
        "similar": similar[:LASTFM_SIMILAR],
    }


def _spotify_placeholder(sources: set) -> dict:
    """Cache skeleton for an artist Last.fm has seeded but Spotify hasn't resolved
    yet: spotify_id is null so the next Spotify build (default add-missing mode)
    picks it up, fills in id/url/latest_release, and preserves the lastfm block."""
    return {
        "spotify_id": None,
        "spotify_url": None,
        "sources": sorted(sources),
        "last_refreshed": None,
        "latest_release": None,
        "latest_release_checked": None,
    }


def refresh_lastfm(cache: dict, api_key: str, args) -> None:
    """Last.fm enrichment AND seed. First ensures every repo artist has a cache
    entry — creating a Spotify-null skeleton (see _spotify_placeholder) for any
    Spotify hasn't reached — so one Last.fm pass covers the whole roster even while
    the Spotify side drips in over the daily Dev-mode quota. Then writes each
    artist's lastfm block. Existing Spotify data is left untouched. Independent of
    Spotify (no Spotify creds, no cap). Honors --artist and --dry-run."""
    # Seed: a null-Spotify skeleton for any repo artist not yet cached.
    repo_artists, _ = collect_artists(load_aliases())
    seeded = 0
    for nm, srcs in repo_artists.items():
        if nm not in cache:
            cache[nm] = _spotify_placeholder(srcs)
            seeded += 1

    names = sorted(cache)
    if args.artist:
        sub = args.artist.lower()
        names = [n for n in names if sub in n.lower()]
    if not names:
        print("No artists to enrich (check --artist, or the repo artist sources).")
        return
    print(f"Refreshing Last.fm enrichment for {len(names)} artist(s)"
          + (f"  [{seeded} newly seeded]" if seeded else "")
          + (" [DRY RUN]" if args.dry_run else "") + "\n")

    enriched = 0
    for i, name in enumerate(names, 1):
        info = lastfm_artist_info(name, api_key)
        time.sleep(DELAY)
        listeners = (info or {}).get("listeners")

        if args.dry_run:
            shown = f"{listeners:,} listeners" if listeners is not None else "not found"
            print(f"[{i}/{len(names)}] {name}  → {shown}")
            continue

        cache[name]["lastfm"] = info
        cache[name]["lastfm_checked"] = date.today().isoformat()
        if info:
            enriched += 1
            if listeners is not None:
                tags = ", ".join(info["tags"][:3]) or "—"
                print(f"[{i}/{len(names)}] {name}  → {listeners:,} listeners, tags: {tags}")
            else:
                print(f"[{i}/{len(names)}] {name}  → enriched (listeners unknown)")
        else:
            print(f"[{i}/{len(names)}] {name}  → not found on Last.fm")
        if (i % SAVE_EVERY) == 0:
            save_cache(cache)
            print("    …checkpoint saved")

    if args.dry_run:
        print("\n[DRY RUN] no changes written.")
        return
    save_cache(cache)
    print("\n" + "=" * 60)
    print(f"Enriched {enriched}/{len(names)} artist(s) from Last.fm. "
          f"Written: {OUTPUT_JSON}")


# ── --add-artist: append a cache-ready row to a low-commitment list (#94) ─────
# Resolve an artist on Spotify and append a schema-valid row to research /
# fast_track / seen_with. artists.tsv is REFUSED — a row there asserts Times Seen
# / First Seen, derived from a real show row, which this tool won't fabricate (the
# dual-bill ledger question is #103). Append is header-driven (uses each file's
# own column order) and append-mode, so the rest of the file is left untouched; it
# never writes a '#' comment block (the in-page editor derives the header from
# line 1 and a comment block wipes the file — #80).

NAR_TSV        = os.path.join(FOLLOWS,  "new_artist_research.tsv")
FAST_TRACK_TSV = os.path.join(DATA_DIR, "fast_track.tsv")
SEEN_WITH_TSV  = os.path.join(DATA_DIR, "seen_with.tsv")

_ADD_DESTINATIONS = {
    "research": NAR_TSV, "new_artist_research": NAR_TSV, "new_artist_research.tsv": NAR_TSV,
    "fast_track": FAST_TRACK_TSV, "fast_track.tsv": FAST_TRACK_TSV,
    "seen_with": SEEN_WITH_TSV, "seen_with.tsv": SEEN_WITH_TSV,
}

_ARTISTS_TSV_GUIDANCE = (
    "artists.tsv is the seen-artist ledger — a row there asserts Times Seen / First "
    "Seen, which derive from a real show row. This tool won't fabricate ledger "
    "facts. Record the sighting via the post-show flow, or use new_artist_research "
    "/ fast_track / seen_with.")


def _tsv_header(path: str) -> list[str]:
    with open(path, encoding="utf-8", newline="") as f:
        return f.readline().rstrip("\r\n").split("\t")


def _append_tsv_row(path: str, row: dict) -> None:
    """Append one row aligned to the file's existing header order, in append mode
    so the rest of the file stays byte-for-byte intact. csv handles any quoting;
    no '#' comment block is ever introduced (#80)."""
    header = _tsv_header(path)
    with open(path, "rb") as f:
        ends_nl = f.read()[-1:] == b"\n"
    with open(path, "a", encoding="utf-8", newline="") as f:
        if not ends_nl:
            f.write("\n")
        csv.writer(f, delimiter="\t", lineterminator="\n").writerow(
            [row.get(col, "") for col in header])


def _search_candidates(name: str, creds, limit: int = 8) -> list[tuple[float, dict]]:
    data = api_get("/search", {"q": name, "type": "artist", "limit": limit}, creds)
    items = (data or {}).get("artists", {}).get("items", [])
    scored = [(similarity(name, it.get("name", "")), it) for it in items if it.get("id")]
    scored.sort(key=lambda t: t[0], reverse=True)
    return scored


def _choose_artist(name: str, creds, dry_run: bool):
    """Resolve `name` to (id, url, resolved_name). Auto-accepts a confident,
    unambiguous top hit; else prints candidates and prompts (writes nothing on
    dry-run or cancel). Returns None if declined / no hit."""
    cands = _search_candidates(name, creds)
    if not cands:
        print(f"  No Spotify results for '{name}'.")
        return None

    def _info(it):
        return it["id"], (it.get("external_urls") or {}).get("spotify", ""), it.get("name", "")

    top_score, top = cands[0]
    runner = cands[1][0] if len(cands) > 1 else 0.0
    if top_score >= SEARCH_MIN_SCORE and (top_score - runner) >= 0.15:
        aid, url, rn = _info(top)
        print(f"  Resolved '{name}' → {rn}  ({url})  [score {top_score:.2f}]")
        return aid, url, rn

    print(f"  '{name}' is low-confidence or ambiguous — candidates:")
    for i, (s, it) in enumerate(cands[:8], 1):
        print(f"    {i}. {it.get('name','')}  "
              f"({(it.get('external_urls') or {}).get('spotify','')})  [score {s:.2f}]")
    if dry_run:
        print("  [DRY RUN] would prompt for a pick; nothing written.")
        return None
    raw = input("  Pick number (Enter/'q' to cancel): ").strip().lower()
    if not raw or raw == "q":
        print("  Cancelled — nothing written.")
        return None
    try:
        return _info(cands[int(raw) - 1][1])
    except (ValueError, IndexError):
        print("  Invalid pick — nothing written.")
        return None


def add_artist(args, creds) -> None:
    name = args.add_artist.strip()
    dest = (args.to or "").strip().lower()
    if dest in ("artists", "artists.tsv"):
        sys.exit("Refused: " + _ARTISTS_TSV_GUIDANCE)
    path = _ADD_DESTINATIONS.get(dest)
    if not path:
        sys.exit(f"Unknown --to '{args.to}'. Allowed: research, fast_track, seen_with. "
                 f"(artists.tsv is refused: {_ARTISTS_TSV_GUIDANCE})")

    is_sw = path == SEEN_WITH_TSV
    if is_sw and not (args.date and args.headliner):
        sys.exit('--to seen_with requires --date YYYY-MM-DD and --headliner "<show-row Artist>".')

    # Dedup: Artist for research/fast_track; Seen With + Date + Headliner for seen_with.
    rows = read_tsv_rows(path)
    if is_sw:
        key = (_norm(name), args.date.strip(), _norm(args.headliner))
        dup = any((_norm(r.get("Seen With", "")), r.get("Show Date", "").strip(),
                   _norm(r.get("Headliner", ""))) == key for r in rows)
    else:
        dup = any(_norm(r.get("Artist", "")) == _norm(name) for r in rows)
    if dup:
        print(f"'{name}' already in {os.path.basename(path)} (dedup key matched) — skipped.")
        return

    chosen = _choose_artist(name, creds, args.dry_run)
    if not chosen:
        return
    aid, url, _resolved = chosen

    if is_sw:
        row = {"Show Date": args.date.strip(), "Headliner": args.headliner.strip(),
               "Seen With": name, "Role": (args.role or "").strip(),
               "Spotify URL": url, "Notes": (args.notes or "").strip()}
    elif path == FAST_TRACK_TSV:
        row = {"Artist": name, "Spotify URL": url}            # descriptive cols left blank
    else:  # NAR — no Spotify URL column; the cache re-resolves it on the next build
        row = {"Artist": name, "Status": "pending-review", "Source": "added via --add-artist"}

    if args.dry_run:
        print(f"  [DRY RUN] would append to {os.path.basename(path)}: {row}")
        return
    _append_tsv_row(path, row)
    print(f"  ✓ appended '{name}' to {os.path.basename(path)}")

    # Cache it in the same run (one /albums call) unless --no-cache.
    if not args.no_cache:
        canon = canonical(name, load_aliases())
        cache = load_cache()
        try:
            entry = build_entry(canon, {_source_tag(path)}, aid, url, creds)
        except RateLimited:
            save_cache(cache)
            raise
        prev = cache.get(canon)
        if prev and "lastfm" in prev:
            entry["lastfm"] = prev["lastfm"]
            entry["lastfm_checked"] = prev.get("lastfm_checked")
        cache[canon] = entry
        save_cache(cache)
        print(f"  ✓ cached {canon} → {aid}  "
              f"latest {(entry.get('latest_release') or {}).get('date') or '—'}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    global DELAY
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true",
                    help="Re-pull metadata + latest release for ALL repo artists "
                         "(default only adds artists missing from the cache).")
    ap.add_argument("--refresh-releases", action="store_true",
                    help="Re-pull ONLY each cached artist's latest release "
                         "(album/single); leaves the rest of each entry "
                         "untouched. Honors --artist, --stale-days, and --dry-run.")
    ap.add_argument("--refresh-images", action="store_true",
                    help="Re-pull ONLY each cached artist's portrait (image_url) "
                         "via GET /artists/{id}; leaves the rest of each entry "
                         "untouched. Honors --artist, --stale-days (on "
                         "images_checked), and --dry-run — a resumable multi-day "
                         "portrait back-audit across the ~100/day cap.")
    ap.add_argument("--refresh-lastfm", action="store_true",
                    help="Re-pull ONLY the Last.fm enrichment block (listeners, "
                         "playcount, tags, similar) for cached artists. Independent "
                         "of Spotify; needs LASTFM_API_KEY, not Spotify creds. "
                         "Honors --artist and --dry-run.")
    ap.add_argument("--prune", action="store_true",
                    help="With --refresh: drop cached artists no longer present in the repo.")
    ap.add_argument("--artist", metavar="NAME",
                    help="Only process artists whose canonical name contains NAME "
                         "(case-insensitive substring).")
    ap.add_argument("--add-artist", metavar="NAME",
                    help="Resolve NAME on Spotify and append a cache-ready row to the "
                         "list chosen with --to. Caches it the same run unless --no-cache.")
    ap.add_argument("--to", metavar="DEST",
                    help="Destination for --add-artist: research | fast_track | seen_with "
                         "(bare filenames accepted). seen_with also needs --date/--headliner.")
    ap.add_argument("--date", metavar="YYYY-MM-DD",
                    help="With --add-artist --to seen_with: the show date.")
    ap.add_argument("--headliner", metavar="ARTIST",
                    help="With --add-artist --to seen_with: the verbatim show-row "
                         "Artist the member was seen with (the join key).")
    ap.add_argument("--role", metavar="ROLE",
                    help="With --add-artist --to seen_with: optional role (e.g. guitar).")
    ap.add_argument("--notes", metavar="TEXT",
                    help="With --add-artist --to seen_with: optional notes.")
    ap.add_argument("--no-cache", action="store_true",
                    help="With --add-artist: append the row but skip the same-run cache "
                         "build (avoids the /albums call when rate-limited).")
    ap.add_argument("--stale-days", type=int, default=None, metavar="N",
                    help="With --refresh-releases / --refresh-images: skip artists whose latest_release (or portrait) "
                         "was checked within the last N days. Default unset = refresh "
                         "every cached artist (unchanged behavior — a deliberate full "
                         "re-pull still re-pulls everyone). Pass a value (e.g. 7) to "
                         "make the multi-day, rate-limited release back-audit "
                         "RESUMABLE across the ~100/day Dev-mode cap: each daily run "
                         "skips what an earlier run in the same sweep already "
                         "refreshed and continues where it left off. Choose N larger "
                         "than the sweep length (a ~317-artist sweep is 3-4 days, so "
                         "7 is safe). No effect on the build or --refresh paths.")
    ap.add_argument("--delay", type=float, default=DELAY, metavar="SECONDS",
                    help="Seconds to sleep between Spotify calls (default "
                         "%(default)s). The build packs ~1-2 calls/artist; raise "
                         "this to stay under Dev-mode 429 lockouts on a big run, "
                         "lower it (e.g. 0.3) for speed once limits relax or for "
                         "the lighter --refresh-* passes.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would change; write nothing.")
    args = ap.parse_args()

    DELAY = args.delay

    # Last.fm enrichment is fully independent of Spotify — handle it before the
    # Spotify credential check so it runs with only LASTFM_API_KEY set.
    if args.refresh_lastfm:
        lastfm_key = os.environ.get("LASTFM_API_KEY", "")
        if not lastfm_key:
            sys.exit("LASTFM_API_KEY must be set (scripts/.env or environment).")
        cache = load_cache()
        print(f"Already cached: {len(cache)}")
        refresh_lastfm(cache, lastfm_key, args)
        return

    client_id     = os.environ.get("SPOTIFY_CLIENT_ID", "")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        sys.exit("SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set "
                 "(scripts/.env or environment).")
    creds = (client_id, client_secret)

    # --add-artist: resolve + append one artist to a low-commitment list (#94).
    # Needs Spotify creds (for resolution), so it sits after the credential check.
    if args.add_artist:
        if not args.to:
            sys.exit("--add-artist requires --to (research | fast_track | seen_with).")
        add_artist(args, creds)
        return

    # Releases-only path operates on the existing cache, not the collected repo set.
    if args.refresh_releases:
        cache = load_cache()
        print(f"Already cached: {len(cache)}")
        refresh_releases(cache, creds, args)
        return

    if args.refresh_images:
        cache = load_cache()
        print(f"Already cached: {len(cache)}")
        refresh_images(cache, creds, args)
        return

    amap = load_aliases()
    artists, url_hints = collect_artists(amap)
    cache = load_cache()
    print(f"Repo artists collected: {len(artists)}  |  already cached: {len(cache)}")

    # Selection
    names = sorted(artists)
    if args.artist:
        sub = args.artist.lower()
        names = [n for n in names if sub in n.lower()]
    elif not args.refresh:
        # Add-missing: brand-new artists AND Last.fm-seeded skeletons with no
        # Spotify id yet (so the drip fills them in); skip fully-resolved entries.
        names = [n for n in names if not (cache.get(n) or {}).get("spotify_id")]

    if not names:
        print("Nothing to do (use --refresh to re-pull existing entries).")
        return
    print(f"To process: {len(names)}" + (" [DRY RUN]" if args.dry_run else "") + "\n")

    resolved = 0
    unresolved: list[str] = []

    def _flush_on_bail():
        # On a RateLimited bail, persist everything collected so far. Without this
        # the exception propagates to __main__ and exits, discarding entries added
        # since the last SAVE_EVERY checkpoint (the 76-100 lost-on-bail bug).
        if not args.dry_run:
            save_cache(cache)
            print(f"    …flushed {len(cache)} cached entries before bailing")

    for i, name in enumerate(names, 1):
        cached = cache.get(name) or {}
        try:
            aid, url = resolve_artist_id(name, url_hints.get(name), creds,
                                         cached.get("spotify_id"), cached.get("spotify_url", ""))
        except RateLimited:
            _flush_on_bail()
            raise
        time.sleep(DELAY)
        if not aid:
            print(f"[{i}/{len(names)}] {name}  → unresolved")
            unresolved.append(name)
            continue

        if args.dry_run:
            action = "refresh" if name in cache else "add"
            print(f"[{i}/{len(names)}] {name}  → {aid}  [would {action}]")
            resolved += 1
            continue

        try:
            entry = build_entry(name, artists[name], aid, url, creds)
        except RateLimited:
            _flush_on_bail()
            raise
        time.sleep(DELAY)
        # Preserve any Last.fm enrichment from a prior --refresh-lastfm; the Spotify
        # build/refresh owns the Spotify fields only and must not wipe the rest.
        prev = cache.get(name)
        if prev and "lastfm" in prev:
            entry["lastfm"] = prev["lastfm"]
            entry["lastfm_checked"] = prev.get("lastfm_checked")
        # Preserve any portrait from a prior --refresh-images: the build owns the
        # Spotify anchor + release only and must not reset image_url/images_checked.
        if prev and prev.get("images_checked"):
            entry["image_url"] = prev.get("image_url")
            entry["images_checked"] = prev.get("images_checked")
        # Null-preserve guard (#109): don't let a null pull wipe a known release
        # (app-only /market-filter flakiness). Keep the cached release AND its
        # check-date so the entry stays eligible for a real refresh instead of
        # locking in a false null. New artists (no prev) still store null.
        prev_rel = (prev or {}).get("latest_release")
        if entry.get("latest_release") is None and prev_rel is not None:
            entry["latest_release"] = prev_rel
            entry["latest_release_checked"] = prev.get("latest_release_checked")
            print(f"    ⚠ null pull for {name}; kept cached {prev_rel.get('date')}", file=sys.stderr)
        cache[name] = entry
        rel = entry.get("latest_release") or {}
        print(f"[{i}/{len(names)}] {name}  → {aid}  latest {rel.get('date') or '—'}")
        resolved += 1
        if resolved % SAVE_EVERY == 0:
            save_cache(cache)
            print(f"    …checkpoint saved ({resolved} written)")

    if args.refresh and args.prune and not args.dry_run:
        stale = [k for k in cache if k not in artists]
        for k in stale:
            del cache[k]
        if stale:
            print(f"\nPruned {len(stale)} artist(s) no longer in the repo: {', '.join(sorted(stale))}")

    if not args.dry_run:
        save_cache(cache)

    print("\n" + "=" * 60)
    print(f"{'[DRY RUN] ' if args.dry_run else ''}Resolved {resolved}, "
          f"{len(unresolved)} unresolved. Cache now holds {len(cache)} artists.")
    if not args.dry_run:
        print(f"Written: {OUTPUT_JSON}")
    if unresolved:
        print("\nUnresolved (need a manual Spotify URL in artists.tsv/fast_track.tsv, "
              "or an alias entry):")
        for n in unresolved:
            print(f"  {n}")


if __name__ == "__main__":
    try:
        main()
    except RateLimited as e:
        hrs = e.retry_after / 3600
        sys.exit(f"\n⚠ Spotify rate-limited (Retry-After ~{e.retry_after}s ≈ {hrs:.1f}h). "
                 f"Progress through the last checkpoint is saved; re-run to resume "
                 f"once the lockout clears.")
