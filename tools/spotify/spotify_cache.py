#!/usr/bin/env python3
"""
spotify_cache.py — Build data/artist_spotify.json from every artist in the repo.

Pulls Spotify catalog metadata + top tracks for the full set of artists that
appear anywhere in the live-shows repo and writes a single deterministic JSON
cache, keyed by canonical artist name. Consumers:

  - sampler MCP workflow     -> top_tracks[].uri for playlist assembly (#73)
  - artist research          -> signature songs, popularity, genres for a new artist
  - follow-tier decisions    -> popularity / followers / genre fit
  - (optional) the site       -> clickable artist name -> top tracks

AUTH
    Spotify Client Credentials (app-only) — the same SPOTIFY_CLIENT_ID /
    SPOTIFY_CLIENT_SECRET already used by tools/youtube/youtube_fill_handles.py.
    No user OAuth, no quota limit. ONLY non-deprecated endpoints are used:
    GET /artists/{id} and GET /artists/{id}/top-tracks both survived the
    2024-11-27 Web API cull. Related-artists and recommendations did NOT and are
    intentionally absent (they 403 on a Development-mode app).

USAGE
    python3 spotify_cache.py                 # add artists not yet in the cache
    python3 spotify_cache.py --refresh       # full re-pull (meta + tracks) for ALL
    python3 spotify_cache.py --refresh --prune   # ...and drop artists no longer in the repo
    python3 spotify_cache.py --artist "Larkin Poe"   # one artist (substring, case-insensitive)
    python3 spotify_cache.py --dry-run       # report planned changes, write nothing

OUTPUT  data/artist_spotify.json — deterministic (sorted keys, tracks by rank), so a
        periodic full refresh produces small, localized diffs. Committed to the repo
        on purpose: a fresh agentic session and the site both read it from there.

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
MARKET            = "US"      # top-tracks popularity is global; market picks the catalog/availability
TOP_N             = 10
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


def build_entry(name: str, sources: set, aid: str, url: str, creds) -> dict | None:
    meta = api_get(f"/artists/{aid}", {}, creds)
    if not meta:
        return None
    top = api_get(f"/artists/{aid}/top-tracks", {"market": MARKET}, creds) or {}
    tracks = []
    for rank, t in enumerate(top.get("tracks", [])[:TOP_N], 1):
        tracks.append({
            "rank": rank,
            "name": t.get("name", ""),
            "uri": t.get("uri", ""),
            "popularity": t.get("popularity"),
            "album": (t.get("album") or {}).get("name", ""),
        })
    return {
        "spotify_id": aid,
        "spotify_url": url or meta.get("external_urls", {}).get("spotify", ""),
        "popularity": meta.get("popularity"),
        "followers": (meta.get("followers") or {}).get("total"),
        "genres": meta.get("genres", []),
        "sources": sorted(sources),
        "last_refreshed": date.today().isoformat(),
        "top_tracks": tracks,
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


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true",
                    help="Re-pull metadata + top tracks for ALL repo artists "
                         "(default only adds artists missing from the cache).")
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
        n_tracks = len(entry["top_tracks"])
        print(f"[{i}/{len(names)}] {name}  → pop {entry['popularity']}, "
              f"{n_tracks} tracks, genres: {', '.join(entry['genres'][:3]) or '—'}")
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
