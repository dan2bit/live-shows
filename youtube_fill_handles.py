#!/usr/bin/env python3
"""
youtube_fill_handles.py — Populator for artists.tsv YouTube Channel and Spotify URL columns

TWO-PHASE WORKFLOW for YouTube handles:

  Phase 1 — fetch from YouTube and cache locally (costs quota):

    python3 youtube_fill_handles.py --fetch
    python3 youtube_fill_handles.py --fetch --limit 10  # spread across days

    Searches YouTube by artist name for every blank YouTube Channel entry.
    Writes results to youtube_handle_candidates.tsv. Safe to re-run —
    already-fetched artists are skipped unless --refetch or
    --refetch-excluded is passed.

    Quota: ~101 units per artist (search.list + channels.list).
    Stops immediately on a 403 quota error — candidates file is saved
    after every artist so nothing is lost.

  Correcting bad YouTube results between runs:

    1. Open youtube_handle_candidates.tsv
    2. For each bad match, add the wrong handle to the excluded_channels
       column (comma-separated if multiple).
    3. Run --refetch-excluded to re-search only those artists:

    python3 youtube_fill_handles.py --fetch --refetch-excluded

  Phase 2 — write from the cached file into artists.tsv (zero quota):

    python3 youtube_fill_handles.py --write              # default threshold 0.8
    python3 youtube_fill_handles.py --write --threshold 0.6
    python3 youtube_fill_handles.py --write --threshold 0.0  # write everything

SPOTIFY WORKFLOW (no quota — uses Client Credentials OAuth):

    python3 youtube_fill_handles.py --spotify            # fill all blank Spotify URLs
    python3 youtube_fill_handles.py --spotify --dry-run  # preview
    python3 youtube_fill_handles.py --spotify --artist "Larkin Poe"  # single artist

    Requires SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env.
    No API quota limit — writes directly to artists.tsv after each match.
    Safe to re-run; already-filled rows are skipped.

LEGACY MODE (subscriptions list — limited utility):

    python3 youtube_fill_handles.py --subscriptions --write-all

    Only matches artists you're already subscribed to on YouTube.

REQUIRES OAuth (YouTube modes) — same token.json / client_secrets.json used by
youtube_create_playlists.py. Run --auth-only once if not yet authenticated.
--write, --spotify, and --subscriptions --dry-run do not need OAuth.

CANDIDATE FILE: youtube_handle_candidates.tsv (gitignored — local working file)
    Columns: artist, handle, channel_title, score, channel_url,
             subscriber_count, excluded_channels
    Edit manually to correct bad matches before running --write.
    Delete a row to skip that artist entirely.

CONFIDENCE SCORES (YouTube):
    1.0   Exact normalized name match
    0.8+  Strong token overlap — auto-written at default threshold
    0.55+ Partial match — in candidates file, skipped at default threshold
    <0.55 No confident match — not written to candidates file

ENVIRONMENT / FILES:
    .env                 — YOUTUBE_API_KEY, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
    client_secrets.json  — OAuth client secret for YouTube write operations
    token.json           — cached OAuth token
    artists.tsv          — read and written in-place
"""

import argparse
import csv
import os
import re
import sys
import time
import unicodedata

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    sys.exit("Missing dependency: python-dotenv\nRun: pip install python-dotenv")

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
except ImportError:
    sys.exit(
        "Missing dependencies. Run:\n"
        "  pip install google-api-python-client google-auth-oauthlib\n"
    )

# ── Config ────────────────────────────────────────────────────────────────────

SCRIPT_DIR       = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(SCRIPT_DIR, ".env"))

SCOPES           = ["https://www.googleapis.com/auth/youtube"]
CLIENT_SECRETS   = os.environ.get("YOUTUBE_CLIENT_SECRETS", "client_secrets.json")
TOKEN_FILE       = os.environ.get("YOUTUBE_TOKEN_FILE",     "token.json")
ARTISTS_TSV      = os.path.join(SCRIPT_DIR, "artists.tsv")
CANDIDATES_TSV   = os.path.join(SCRIPT_DIR, "youtube_handle_candidates.tsv")
CANDIDATE_FIELDS = [
    "artist", "handle", "channel_title", "score",
    "channel_url", "subscriber_count", "excluded_channels",
]

SPOTIFY_TOKEN_URL  = "https://accounts.spotify.com/api/token"
SPOTIFY_SEARCH_URL = "https://api.spotify.com/v1/search"

DEFAULT_WRITE_THRESHOLD = 0.8
MIN_FETCH_THRESHOLD     = 0.55

PAGE_DELAY     = 0.3
SPOTIFY_DELAY  = 0.3


# ── OAuth (YouTube) ───────────────────────────────────────────────────────────

def get_authenticated_service():
    client_secrets_path = os.path.join(SCRIPT_DIR, CLIENT_SECRETS)
    token_path          = os.path.join(SCRIPT_DIR, TOKEN_FILE)

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(client_secrets_path):
                sys.exit(
                    f"OAuth credentials file not found: {client_secrets_path}\n"
                    "Download from Google Cloud Console → Credentials → OAuth 2.0 Client IDs."
                )
            flow = InstalledAppFlow.from_client_secrets_file(client_secrets_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


# ── Name normalisation & similarity ──────────────────────────────────────────

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"^the\s+", "", s).strip()
    s = re.sub(r"\s*(official|music|band|tv|channel|records|vevo)\s*$", "", s).strip()
    return s


def _tokens(s: str) -> set:
    NOISE = {"and", "the", "feat", "with", "live", "official", "music"}
    return {w for w in _norm(s).split() if len(w) > 2 and w not in NOISE}


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


def handle_to_url(handle: str) -> str:
    if handle.startswith("@"):
        return f"https://youtube.com/{handle}"
    return handle


def format_subscriber_count(count_str: str) -> str:
    try:
        n = int(count_str)
    except (ValueError, TypeError):
        return ""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def parse_exclusions(excluded_channels_str: str) -> set[str]:
    if not excluded_channels_str:
        return set()
    return {h.strip() for h in excluded_channels_str.split(",") if h.strip()}


# ── TSV helpers ───────────────────────────────────────────────────────────────

def load_artists() -> tuple[list[dict], list[str]]:
    with open(ARTISTS_TSV, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    return rows, fieldnames


def save_artists(rows: list[dict], fieldnames: list[str]) -> None:
    with open(ARTISTS_TSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t",
                           lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def load_candidates() -> dict[str, dict]:
    if not os.path.exists(CANDIDATES_TSV):
        return {}
    with open(CANDIDATES_TSV, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return {row["artist"]: row for row in reader}


def save_candidates(candidates: dict[str, dict]) -> None:
    with open(CANDIDATES_TSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CANDIDATE_FIELDS, delimiter="\t",
                           lineterminator="\n")
        w.writeheader()
        for row in sorted(candidates.values(), key=lambda r: -float(r["score"])):
            out = {field: row.get(field, "") for field in CANDIDATE_FIELDS}
            w.writerow(out)


# ── YouTube fetch mode ────────────────────────────────────────────────────────

def search_handle_for_artist(
    youtube,
    artist_name: str,
    excluded: set[str],
) -> tuple[str, float, str, str, str]:
    """
    Search YouTube for the artist name.
    Returns (handle, score, channel_title, channel_url, subscriber_count_raw).
    Returns ("", 0.0, "", "", "") if no result meets MIN_FETCH_THRESHOLD
    or all results are excluded.
    Raises HttpError so caller can detect 403 quota errors.
    """
    resp = youtube.search().list(
        part="snippet",
        q=artist_name,
        type="channel",
        maxResults=5,
    ).execute()

    best_handle    = ""
    best_score     = 0.0
    best_title     = ""
    best_sub_count = ""

    for item in resp.get("items", []):
        channel_id    = item["snippet"]["channelId"]
        channel_title = item["snippet"]["title"]
        score         = similarity(artist_name, channel_title)

        if score <= best_score:
            continue

        try:
            ch_resp  = youtube.channels().list(
                part="snippet,statistics",
                id=channel_id,
            ).execute()
            ch_items = ch_resp.get("items", [])
            if ch_items:
                ch        = ch_items[0]
                custom    = ch["snippet"].get("customUrl", "")
                handle    = custom if custom.startswith("@") else f"@{custom}" if custom else f"https://www.youtube.com/channel/{channel_id}"
                sub_count = ch.get("statistics", {}).get("subscriberCount", "")
            else:
                handle    = f"https://www.youtube.com/channel/{channel_id}"
                sub_count = ""
        except HttpError:
            raise
        except Exception:
            handle    = f"https://www.youtube.com/channel/{channel_id}"
            sub_count = ""

        if handle in excluded:
            continue

        best_score     = score
        best_title     = channel_title
        best_handle    = handle
        best_sub_count = sub_count

    if best_score >= MIN_FETCH_THRESHOLD and best_handle:
        return best_handle, best_score, best_title, handle_to_url(best_handle), best_sub_count
    return "", 0.0, "", "", ""


def run_fetch_mode(
    youtube,
    artists: list[dict],
    limit: int | None,
    refetch: bool,
    refetch_excluded: bool,
) -> None:
    blanks = [
        row for row in artists
        if not row.get("YouTube Channel", "").strip()
    ]

    if not blanks:
        print("No blank YouTube Channel entries found — nothing to fetch.")
        return

    candidates = load_candidates()

    if refetch_excluded:
        to_fetch = []
        for row in blanks:
            name = row["Artist"]
            cand = candidates.get(name)
            if not cand:
                continue
            exclusions = parse_exclusions(cand.get("excluded_channels", ""))
            if cand.get("handle", "") in exclusions:
                to_fetch.append(row)
        if not to_fetch:
            print("No artists found with their current handle in excluded_channels.")
            print("Add the bad handle to the excluded_channels column first, then re-run.")
            return
        print(f"Re-fetching {len(to_fetch)} artist(s) with excluded handles:\n")
    else:
        already_done = set(candidates.keys()) if not refetch else set()
        to_fetch = [row for row in blanks if row["Artist"] not in already_done]
        if limit:
            to_fetch = to_fetch[:limit]

        skipped_cached = len(blanks) - len([r for r in blanks if r["Artist"] not in already_done])
        print(f"{len(blanks)} blank entries total.")
        if skipped_cached:
            print(f"  {skipped_cached} already in candidates file — skipping (use --refetch to redo).")
        print(f"  Fetching {len(to_fetch)}" + (f" (--limit {limit})" if limit else "") + ".\n")

    no_match = []

    for idx, row in enumerate(to_fetch, 1):
        artist_name = row["Artist"]
        cand        = candidates.get(artist_name, {})
        exclusions  = parse_exclusions(cand.get("excluded_channels", ""))

        if exclusions:
            print(f"[{idx}/{len(to_fetch)}] {artist_name}  (excluding: {', '.join(sorted(exclusions))})")
        else:
            print(f"[{idx}/{len(to_fetch)}] {artist_name}")

        try:
            handle, score, channel_title, channel_url, sub_count = \
                search_handle_for_artist(youtube, artist_name, exclusions)
        except HttpError as e:
            if e.resp.status == 403:
                print(f"\n  ✗ QUOTA EXCEEDED (403) — stopping early after {idx - 1} searches.")
                print(f"  Candidates file saved. Run again tomorrow to continue.\n")
                break
            print(f"  ERROR {e.resp.status}: {e} — skipping\n")
            no_match.append(artist_name)
            time.sleep(PAGE_DELAY)
            continue

        time.sleep(PAGE_DELAY)

        if not handle:
            print(f"  → No confident match (score < {MIN_FETCH_THRESHOLD}, or all results excluded)\n")
            no_match.append(artist_name)
            continue

        sub_fmt = format_subscriber_count(sub_count)
        flag    = "✓" if score >= DEFAULT_WRITE_THRESHOLD else "?"
        print(f"  → {handle}  ({channel_title})  score {score:.2f} {flag}  {sub_fmt} subs")
        print(f"     {channel_url}\n")

        candidates[artist_name] = {
            "artist":            artist_name,
            "handle":            handle,
            "channel_title":     channel_title,
            "score":             f"{score:.4f}",
            "channel_url":       channel_url,
            "subscriber_count":  sub_fmt,
            "excluded_channels": cand.get("excluded_channels", ""),
        }
        save_candidates(candidates)

    print("=" * 60)
    total_in_file = len(candidates)
    high = sum(1 for c in candidates.values() if float(c["score"]) >= DEFAULT_WRITE_THRESHOLD)
    low  = total_in_file - high
    print(f"Candidates file: {total_in_file} entries "
          f"({high} high-confidence ≥{DEFAULT_WRITE_THRESHOLD}, {low} lower).")
    print(f"Written to: {CANDIDATES_TSV}")

    if no_match:
        print(f"\n{len(no_match)} artist(s) had no confident match — manual YouTube search needed:")
        for name in no_match:
            print(f"  {name}")

    if not refetch_excluded:
        remaining_unfetched = len(blanks) - len(candidates)
        if remaining_unfetched > 0:
            print(f"\n{remaining_unfetched} blank entries not yet fetched. Run again to continue.")

    print(f"\nNext step: python3 youtube_fill_handles.py --write")


# ── YouTube write mode ────────────────────────────────────────────────────────

def run_write_mode(
    artists: list[dict],
    fieldnames: list[str],
    threshold: float,
    dry_run: bool,
) -> None:
    candidates = load_candidates()
    if not candidates:
        sys.exit(
            f"No candidates file found at: {CANDIDATES_TSV}\n"
            "Run --fetch first to populate it."
        )

    print(f"Loaded {len(candidates)} candidates from {os.path.basename(CANDIDATES_TSV)}.")
    print(f"Write threshold: score >= {threshold}\n")

    written      = 0
    skipped_low  = []
    skipped_done = []

    artist_index = {row["Artist"]: i for i, row in enumerate(artists)}

    for artist_name, cand in sorted(candidates.items(), key=lambda x: -float(x[1]["score"])):
        score       = float(cand["score"])
        handle      = cand["handle"]
        title       = cand["channel_title"]
        channel_url = cand.get("channel_url", handle_to_url(handle))
        sub_count   = cand.get("subscriber_count", "")

        row_idx = artist_index.get(artist_name)
        if row_idx is None:
            print(f"  SKIP (not in artists.tsv): {artist_name}")
            continue

        row = artists[row_idx]
        if row.get("YouTube Channel", "").strip():
            skipped_done.append(artist_name)
            continue

        if score < threshold:
            skipped_low.append((artist_name, handle, score, title, channel_url, sub_count))
            continue

        flag     = "✓" if score >= DEFAULT_WRITE_THRESHOLD else "?"
        sub_info = f"  {sub_count} subs" if sub_count else ""
        if dry_run:
            print(f"  {score:.2f} {flag}  {artist_name:<40}  {handle}{sub_info}  [would write]")
            print(f"           {channel_url}")
        else:
            artists[row_idx]["YouTube Channel"] = handle
            save_artists(artists, fieldnames)
            print(f"  {score:.2f} {flag}  {artist_name:<40}  {handle}{sub_info}  ✓ written")
        written += 1

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Results: {written} written, "
          f"{len(skipped_low)} below threshold, {len(skipped_done)} already filled.")

    if skipped_low:
        print(f"\nBelow threshold ({threshold}) — lower it with --threshold to include:")
        for name, handle, score, title, channel_url, sub_count in sorted(skipped_low, key=lambda x: -x[2]):
            sub_info = f"  {sub_count} subs" if sub_count else ""
            print(f"  {score:.2f}  {name:<40}  {handle}{sub_info}")
            print(f"        {channel_url}")

    if not dry_run and written:
        print("\nReview changes with: git diff live-shows/artists.tsv")


# ── Spotify mode ──────────────────────────────────────────────────────────────

_spotify_token_cache: dict = {}


def _get_spotify_token(client_id: str, client_secret: str) -> str:
    if _spotify_token_cache.get("token"):
        return _spotify_token_cache["token"]
    resp = requests.post(
        SPOTIFY_TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=10,
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    _spotify_token_cache["token"] = token
    return token


def spotify_search_artist(artist_name: str, client_id: str, client_secret: str) -> str | None:
    """
    Search Spotify for the artist name. Returns the Spotify URL if a
    confident match is found (similarity >= MIN_FETCH_THRESHOLD), else None.
    No API quota limit — Spotify Client Credentials tokens don't expire mid-run.
    """
    try:
        token = _get_spotify_token(client_id, client_secret)
    except requests.RequestException as e:
        print(f"  [SPOTIFY TOKEN ERROR] {e}")
        return None

    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.get(
            SPOTIFY_SEARCH_URL,
            params={"q": artist_name, "type": "artist", "limit": 5},
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [SPOTIFY ERROR] {e}")
        return None

    items = resp.json().get("artists", {}).get("items", [])
    if not items:
        return None

    best_url   = None
    best_score = 0.0
    for item in items:
        name  = item.get("name", "")
        url   = item.get("external_urls", {}).get("spotify", "")
        score = similarity(artist_name, name)
        if score > best_score and url:
            best_score = score
            best_url   = url

    if best_score >= MIN_FETCH_THRESHOLD:
        return best_url
    return None


def run_spotify_mode(
    artists: list[dict],
    fieldnames: list[str],
    artist_filter: str | None,
    dry_run: bool,
) -> None:
    client_id     = os.environ.get("SPOTIFY_CLIENT_ID", "")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        sys.exit(
            "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set in .env.\n"
            "Create a free app at https://developer.spotify.com/dashboard"
        )

    blanks = [
        (i, row) for i, row in enumerate(artists)
        if not row.get("Spotify URL", "").strip()
        and (artist_filter is None or artist_filter in row["Artist"].lower())
    ]

    if not blanks:
        msg = "No blank Spotify URL entries found"
        if artist_filter:
            msg += f" matching '{artist_filter}'"
        print(msg + " — nothing to do.")
        return

    print(f"{len(blanks)} blank Spotify URL entries to process.\n")

    written      = 0
    no_match     = []

    for idx, (row_idx, row) in enumerate(blanks, 1):
        artist_name = row["Artist"]
        print(f"[{idx}/{len(blanks)}] {artist_name}")

        url = spotify_search_artist(artist_name, client_id, client_secret)
        time.sleep(SPOTIFY_DELAY)

        if not url:
            print(f"  → No confident match\n")
            no_match.append(artist_name)
            continue

        print(f"  → {url}")
        if dry_run:
            print(f"  → [dry-run] would write\n")
            written += 1
        else:
            artists[row_idx]["Spotify URL"] = url
            save_artists(artists, fieldnames)
            print(f"  → Written\n")
            written += 1

    print("=" * 60)
    print(f"{'[DRY RUN] ' if dry_run else ''}Results: {written} written, "
          f"{len(no_match)} no confident match.")

    if no_match:
        print(f"\nNo match found — may need manual Spotify lookup:")
        for name in no_match:
            print(f"  {name}")

    if not dry_run and written:
        print("\nReview changes with: git diff live-shows/artists.tsv")


# ── Subscriptions mode (legacy) ───────────────────────────────────────────────

def fetch_subscriptions(youtube) -> list[dict]:
    subs = []
    page_token = None
    print("Fetching subscriptions...")
    while True:
        kwargs = dict(part="snippet", mine=True, maxResults=50)
        if page_token:
            kwargs["pageToken"] = page_token
        resp = youtube.subscriptions().list(**kwargs).execute()
        for item in resp.get("items", []):
            subs.append({
                "channel_id": item["snippet"]["resourceId"]["channelId"],
                "title":      item["snippet"]["title"],
            })
        page_token = resp.get("nextPageToken")
        print(f"  Fetched {len(subs)} subscriptions so far...")
        if not page_token:
            break
        time.sleep(PAGE_DELAY)
    print(f"Total subscriptions: {len(subs)}")
    return subs


def fetch_handles(youtube, channel_ids: list[str]) -> dict[str, str]:
    handle_map = {}
    for i in range(0, len(channel_ids), 50):
        batch = channel_ids[i:i + 50]
        resp = youtube.channels().list(part="snippet", id=",".join(batch)).execute()
        for item in resp.get("items", []):
            cid    = item["id"]
            custom = item["snippet"].get("customUrl", "")
            handle = custom if custom.startswith("@") else f"@{custom}" if custom else f"https://www.youtube.com/channel/{cid}"
            handle_map[cid] = handle
        time.sleep(PAGE_DELAY)
    return handle_map


def match_subscriptions_to_artists(subs, handle_map, artists):
    candidates = [(i, row) for i, row in enumerate(artists)
                  if not row.get("YouTube Channel", "").strip()]
    matches = []
    for i, row in candidates:
        artist_name = row["Artist"]
        best_score, best_sub = 0.0, None
        for sub in subs:
            score = similarity(artist_name, sub["title"])
            if score > best_score:
                best_score, best_sub = score, sub
        if best_sub and best_score >= MIN_FETCH_THRESHOLD:
            matches.append({
                "artist":        artist_name,
                "channel_title": best_sub["title"],
                "handle":        handle_map.get(best_sub["channel_id"], ""),
                "score":         best_score,
                "row_idx":       i,
            })
    matches.sort(key=lambda m: -m["score"])
    return matches


def run_subscriptions_mode(youtube, artists, fieldnames, write_high, write_all, dry_run):
    subs = fetch_subscriptions(youtube)
    if not subs:
        print("No subscriptions found — nothing to match.")
        return
    print(f"\nResolving @handles for {len(subs)} channels...")
    handle_map = fetch_handles(youtube, [s["channel_id"] for s in subs])
    print(f"Resolved {len(handle_map)} handles.")
    blank_count = sum(1 for r in artists if not r.get("YouTube Channel", "").strip())
    print(f"\nLoaded {len(artists)} artists, {blank_count} with blank YouTube Channel.\n")
    matches = match_subscriptions_to_artists(subs, handle_map, artists)

    if not matches:
        print("No matches found above minimum threshold.")
        return

    print(f"\n{'Score':>6}  {'Artist':<40}  {'Subscribed Channel':<40}  Handle")
    print("-" * 120)
    for m in matches:
        flag = "✓" if m["score"] >= DEFAULT_WRITE_THRESHOLD else "?"
        print(f"  {m['score']:.2f} {flag}  {m['artist']:<40}  {m['channel_title']:<40}  {m['handle']}")
    auto = sum(1 for m in matches if m["score"] >= DEFAULT_WRITE_THRESHOLD)
    print(f"\n{auto} high-confidence, {len(matches)-auto} lower-confidence matches found.")

    if dry_run:
        print("\n[dry-run] No changes written.")
        return

    write_threshold = DEFAULT_WRITE_THRESHOLD if write_high else MIN_FETCH_THRESHOLD
    label = "high-confidence" if write_high else "all"
    print(f"\nWriting {label} matches (score >= {write_threshold})...")
    written = 0
    for m in matches:
        if m["score"] < write_threshold or not m["handle"]:
            continue
        row = artists[m["row_idx"]]
        if row.get("YouTube Channel", "").strip():
            continue
        row["YouTube Channel"] = m["handle"]
        save_artists(artists, fieldnames)
        print(f"  Written: {m['artist']} -> {m['handle']}")
        written += 1
    print(f"\n{written} handle(s) written to artists.tsv.")
    print("\nReview changes with: git diff live-shows/artists.tsv")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--fetch", action="store_true",
        help="Phase 1: search YouTube for blank artists and write results to "
             "youtube_handle_candidates.tsv. Costs quota (~101 units/artist). "
             "Stops on 403. Skips artists already in the candidates file.",
    )
    mode.add_argument(
        "--write", action="store_true",
        help="Phase 2: read youtube_handle_candidates.tsv and write handles into "
             "artists.tsv. Zero quota cost. Use --threshold to control what gets written.",
    )
    mode.add_argument(
        "--spotify", action="store_true",
        help="Fill blank Spotify URL entries in artists.tsv by searching the Spotify "
             "Web API. No quota limit. Writes directly to artists.tsv after each match. "
             "Requires SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env.",
    )
    mode.add_argument(
        "--subscriptions", action="store_true",
        help="Legacy: match against your YouTube subscriptions list. Only finds "
             "artists you're already subscribed to.",
    )
    mode.add_argument(
        "--auth-only", action="store_true",
        help="Authenticate YouTube OAuth and save token.json, then exit.",
    )

    parser.add_argument("--limit", type=int, metavar="N",
                        help="(--fetch) Process at most N artists per run.")
    parser.add_argument("--refetch", action="store_true",
                        help="(--fetch) Re-fetch all artists already in the candidates file.")
    parser.add_argument("--refetch-excluded", action="store_true",
                        help="(--fetch) Re-fetch only artists whose current handle appears "
                             "in their excluded_channels column.")
    parser.add_argument("--threshold", type=float, default=DEFAULT_WRITE_THRESHOLD,
                        metavar="SCORE",
                        help=f"(--write) Minimum confidence score to write. "
                             f"Default: {DEFAULT_WRITE_THRESHOLD}. Range: 0.0–1.0.")
    parser.add_argument("--dry-run", action="store_true",
                        help="(--write / --spotify / --subscriptions) Print what would be "
                             "written without writing anything.")
    parser.add_argument("--artist", metavar="NAME",
                        help="(--spotify) Only process this artist "
                             "(case-insensitive substring match).")
    parser.add_argument("--write-high", action="store_true",
                        help="(--subscriptions) Write high-confidence matches only.")
    parser.add_argument("--write-all", action="store_true",
                        help="(--subscriptions) Write all matches above minimum threshold.")

    args = parser.parse_args()

    if args.refetch_excluded and not args.fetch:
        parser.error("--refetch-excluded requires --fetch")
    if args.refetch and args.refetch_excluded:
        parser.error("--refetch and --refetch-excluded are mutually exclusive")

    # Spotify and --write don't need YouTube OAuth
    needs_auth = args.fetch or args.auth_only or (args.subscriptions and not args.dry_run)
    youtube = None
    if needs_auth:
        print("Authenticating with YouTube...")
        youtube = get_authenticated_service()
        print("Authenticated.")

    if args.auth_only:
        print("Auth complete. token.json saved.")
        return

    artists, fieldnames = load_artists()

    if args.fetch:
        run_fetch_mode(
            youtube, artists,
            limit=args.limit,
            refetch=args.refetch,
            refetch_excluded=args.refetch_excluded,
        )
    elif args.write:
        run_write_mode(artists, fieldnames, threshold=args.threshold, dry_run=args.dry_run)
    elif args.spotify:
        run_spotify_mode(
            artists, fieldnames,
            artist_filter=args.artist.lower() if args.artist else None,
            dry_run=args.dry_run,
        )
    elif args.subscriptions:
        if args.dry_run and youtube is None:
            print("Authenticating with YouTube...")
            youtube = get_authenticated_service()
            print("Authenticated.")
        run_subscriptions_mode(
            youtube, artists, fieldnames,
            write_high=args.write_high,
            write_all=args.write_all,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
