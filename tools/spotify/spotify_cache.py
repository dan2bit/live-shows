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
    Development-mode app are used: GET /artists/{id} (existence check + URL),
    GET /search (id resolution), and GET /artists/{id}/albums (latest release).

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

    Display/badging on this date (a "NEW" badge in the show lists) and recency
    weighting in follow-tier / potentials decisions are deliberately OUT of scope
    here — this only captures and caches the data. See #85 / follow-on tickets.

USAGE
    python3 spotify_cache.py                 # add artists not yet in the cache
    python3 spotify_cache.py --refresh       # full re-pull (metadata + release) for ALL
    python3 spotify_cache.py --refresh-releases  # re-pull ONLY latest_release for cached artists
    python3 spotify_cache.py --refresh --prune   # ...and drop artists no longer in the repo
    python3 spotify_cache.py --artist "Larkin Poe"   # one artist (substring, case-insensitive)
    python3 spotify_cache.py --dry-run       # report planned changes, write nothing

OUTPUT  data/artist_spotify.json — deterministic (sorted keys), so a periodic
        full refresh produces small, localized diffs. Committed to the repo on
        purpose: a fresh agentic session and the site both read it from there.

ENV     SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET in tools/spotify/.env (gitignored)
        or inherited from the environment.

NOTE    Canonicalization here applies only the explicit data/recommend_aliases.tsv map.
        It does NOT replicate build_recommend_index.py's automatic normalization
        (de-invert "X, The", de-accent, strip apostrophes, drop trailing "Band").
        Variants not covered by the alias file may produce separate entries; share
        that normalization here later if duplicates show up.
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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))           # tools/spotify
REPO_ROOT  = os.path.dirname(os.path.dirname(SCRIPT_DIR))         # repo root
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
DELAY             = 0.3       # polite spacing between calls
SAVE_EVERY        = 25        # incremental checkpoint so a long run survives an interruption
SEARCH_MIN_SCORE  = 0.55      # min name-match confidence to accept a search hit

_ARTIST_ID_RE = re.compile(r"artist[:/]([A-Za-z0-9]+)")


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


def canonical(name: str, amap: dict[str, str]) -> str:
    name = name.strip()
    return amap.get(_norm(name), name)


# ── Collect the repo-wide artist universe ─────────────────────────────────────

def collect_artists(amap: dict[str, str]) -> tuple[dict[str, set], dict[str, str]]:
    """Return ({canonical_name: {source tags}}, {canonical_name: spotify_url_hint})."""
    artists: dict[str, set] = {}
    url_hints: dict[str, str] = {}

    def add(raw: str, tag: str, url: str | None = None):
        raw = (raw or "").strip()
        if not raw:
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
            for col in name_cols:
                add(row.get(col, ""), tag, url if col == name_cols[0] else None)

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


def api_get(path: str, params: dict, creds: tuple[str, str]) -> dict | None:
    """GET {SPOTIFY_API}{path} with one 401 refresh-retry and basic 429 backoff."""
    url = f"{SPOTIFY_API}{path}"
    for attempt in range(4):
        token = _get_token(*creds)
        resp = requests.get(url, params=params,
                            headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if resp.status_code == 401:
            _get_token(*creds, force=True)
            continue
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", "2")) + 1
            print(f"    rate-limited; sleeping {wait}s")
            time.sleep(wait)
            continue
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    return None


def extract_artist_id(url: str) -> str | None:
    if not url:
        return None
    m = _ARTIST_ID_RE.search(url)
    return m.group(1) if m else None


def resolve_artist_id(name: str, url_hint: str | None, creds) -> tuple[str | None, str]:
    """Prefer the id parsed from a stored Spotify URL; else search by name."""
    aid = extract_artist_id(url_hint or "")
    if aid:
        return aid, url_hint
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


def latest_release(aid: str, creds) -> dict | None:
    """Most recent album/single for an artist, or None if they have none.

    Uses GET /artists/{id}/albums (app-only reachable). include_groups is
    album,single only — compilations and guest features are excluded so they
    can't masquerade as new activity. One call, limit=ALBUMS_LIMIT (10 — the
    endpoint's max; >10 returns 400 "Invalid limit"). Results are newest-first,
    so the most recent is effectively always within the window.
    """
    data = api_get(f"/artists/{aid}/albums",
                   {"include_groups": "album,single", "market": MARKET, "limit": ALBUMS_LIMIT},
                   creds)
    items = (data or {}).get("items", [])
    if not items:
        return None
    best = max(items, key=lambda it: _release_sort_key(it.get("release_date", "")))
    return {
        "date": best.get("release_date", ""),
        "precision": best.get("release_date_precision", ""),
        "name": best.get("name", ""),
        "type": best.get("album_type", best.get("type", "")),
        "spotify_id": best.get("id", ""),
        "url": (best.get("external_urls") or {}).get("spotify", ""),
    }


def build_entry(name: str, sources: set, aid: str, url: str, creds) -> dict | None:
    # Resolution anchor (id/url) + the artist's latest album/single (see LATEST
    # RELEASE). popularity/followers/genres are no longer stored — see STRIPPED
    # METADATA. The /artists/{id} GET stays as an existence check + URL fallback.
    meta = api_get(f"/artists/{aid}", {}, creds)
    if not meta:
        return None
    rel = latest_release(aid, creds)
    time.sleep(DELAY)
    return {
        "spotify_id": aid,
        "spotify_url": url or meta.get("external_urls", {}).get("spotify", ""),
        "sources": sorted(sources),
        "last_refreshed": date.today().isoformat(),
        "latest_release": rel,
        "latest_release_checked": date.today().isoformat(),
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
    each entry untouched. Honors --artist and --dry-run."""
    names = sorted(cache)
    if args.artist:
        sub = args.artist.lower()
        names = [n for n in names if sub in n.lower()]
    if not names:
        print("No cached artists to refresh releases for "
              "(run a normal build first, or check --artist).")
        return
    print(f"Refreshing latest_release for {len(names)} cached artist(s)"
          + (" [DRY RUN]" if args.dry_run else "") + "\n")

    updated = 0
    for i, name in enumerate(names, 1):
        entry = cache[name]
        aid = entry.get("spotify_id")
        if not aid:
            print(f"[{i}/{len(names)}] {name}  → no spotify_id, skipped")
            continue
        rel = latest_release(aid, creds)
        time.sleep(DELAY)
        old = (entry.get("latest_release") or {}).get("date")
        new = (rel or {}).get("date")

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
        print("\n[DRY RUN] no changes written.")
        return
    save_cache(cache)
    print("\n" + "=" * 60)
    print(f"Updated {updated} release date(s) across {len(names)} artist(s). "
          f"Written: {OUTPUT_JSON}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true",
                    help="Re-pull metadata + latest release for ALL repo artists "
                         "(default only adds artists missing from the cache).")
    ap.add_argument("--refresh-releases", action="store_true",
                    help="Re-pull ONLY each cached artist's latest release "
                         "(album/single); leaves the rest of each entry "
                         "untouched. Honors --artist and --dry-run.")
    ap.add_argument("--prune", action="store_true",
                    help="With --refresh: drop cached artists no longer present in the repo.")
    ap.add_argument("--artist", metavar="NAME",
                    help="Only process artists whose canonical name contains NAME "
                         "(case-insensitive substring).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would change; write nothing.")
    args = ap.parse_args()

    client_id     = os.environ.get("SPOTIFY_CLIENT_ID", "")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        sys.exit("SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set "
                 "(tools/spotify/.env or environment).")
    creds = (client_id, client_secret)

    # Releases-only path operates on the existing cache, not the collected repo set.
    if args.refresh_releases:
        cache = load_cache()
        print(f"Already cached: {len(cache)}")
        refresh_releases(cache, creds, args)
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
        names = [n for n in names if n not in cache]

    if not names:
        print("Nothing to do (use --refresh to re-pull existing entries).")
        return
    print(f"To process: {len(names)}" + (" [DRY RUN]" if args.dry_run else "") + "\n")

    resolved = 0
    unresolved: list[str] = []
    for i, name in enumerate(names, 1):
        aid, url = resolve_artist_id(name, url_hints.get(name), creds)
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

        entry = build_entry(name, artists[name], aid, url, creds)
        time.sleep(DELAY)
        if not entry:
            print(f"[{i}/{len(names)}] {name}  → metadata fetch failed")
            unresolved.append(name)
            continue

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
    main()
