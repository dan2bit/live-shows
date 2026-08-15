#!/usr/bin/env python3
"""
youtube_create_playlists.py — Automated playlist assembler for @dan2bit bootleg channel

Creates YouTube playlists from youtube_videos.tsv by matching videos to a show's date,
orders them (headliner first, then supporting acts, each in setlist.fm order if available),
and writes the resulting playlist URLs back to the appropriate show tracking file.

REQUIRES OAuth (not just an API key) because playlist creation and description updates
are write operations. The scope https://www.googleapis.com/auth/youtube is required.

FIRST-TIME SETUP:
    1. Copy live-shows/.env.example to live-shows/.env
    2. Place client_secrets.json in the live-shows/ directory
       (download from Google Cloud Console → Credentials → OAuth 2.0 Client IDs)
    3. pip install google-api-python-client google-auth-oauthlib python-dotenv
    4. Run once: python3 youtube_create_playlists.py --auth-only
       This opens a browser, you approve access, token.json is cached for future runs.
    See utils/HOWTO.md → "YouTube API credentials" for full setup instructions.

USAGE:

  ── Creating playlists ─────────────────────────────────────────────

    # Create a playlist for a single show (primary workflow).
    # Show is looked up in history/*.tsv OR live_shows_current.tsv automatically.
    python3 youtube_create_playlists.py --new-show 2026-03-29
    python3 youtube_create_playlists.py --new-show 2026-03-29 --update-history

    # Create playlists for all attended shows since a date that have no playlist yet.
    # Skips any show whose Playlist URL column is already populated.
    python3 youtube_create_playlists.py --new-show since:2026-01-11 --update-history --dry-run
    python3 youtube_create_playlists.py --new-show since:2026-01-11 --update-history

    # Override the headliner if the date lookup is ambiguous (single-date mode only)
    python3 youtube_create_playlists.py --new-show 2026-03-29 --headliner "Selwyn Birchwood"

    # Dry run — shows what would be created without calling the API
    python3 youtube_create_playlists.py --new-show 2026-03-29 --dry-run

    # Process shows in the WORKLIST (backfill shows with videos in youtube_videos.tsv)
    python3 youtube_create_playlists.py --worklist --dry-run
    python3 youtube_create_playlists.py --worklist --update-history

    # Process a single show by date using youtube_videos.tsv
    python3 youtube_create_playlists.py --date 2022-12-16

  ── Fixing playlist descriptions ────────────────────────────────────

    # Find playlists with blank descriptions and add the headliner setlist.fm link.
    # Scans all channel playlists, matches back to history/current, fills in descriptions.
    # ALWAYS use --dry-run first or --date to limit scope — avoids burning write quota.
    python3 youtube_create_playlists.py --fix-descriptions --dry-run
    python3 youtube_create_playlists.py --fix-descriptions --date 2023-06-11 2023-07-05

    # Custom description template (use {setlist_url} and/or {venue} as placeholders)
    # Default: "Select tracks from {setlist_url}"
    python3 youtube_create_playlists.py --fix-descriptions \\
        --description-template "Select tracks from my vantage point center-left: {setlist_url}"

OUTPUT LOG (always written, gitignored — lives in logs/ subdirectory):
    logs/playlist_creation_log.tsv — one row per show processed:
        Show Date, Artist, Playlist Title, Playlist URL, Video Count,
        Setlist URL Checked, Setlist Order Used, Videos Added (titles)

NAMING CONVENTION (matches existing channel playlists):
    "{Headliner} LIVE @ {Venue Short} ({City/State abbrev}) {M/D/YY}"
    e.g. "They Might Be Giants LIVE @ Lincoln Theatre (DC) 12/16/22"
    Override per-show with --title if needed.

ORDERING LOGIC:
    1. Fetch setlist.fm URL for the show (from history/*.tsv or live_shows_current.tsv)
    2. Parse song titles from setlist.fm HTML (via requests + BeautifulSoup)
    3. Match video titles against setlist songs using fuzzy title matching
    4. Unmatched videos for the headliner go after matched ones
    5. Supporting act videos follow in their own setlist order (if available)
    6. Within each group, unordered videos sort by upload date as fallback

VIDEO MATCHING (--new-show):
    Primary: videos uploaded on the show date via the channel uploads API
    (publishedAt == show date). Picks up brand-new private videos not yet
    in youtube_videos.tsv.
    Fallback: youtube_videos.tsv matched by show date in video description.

NOTE ON WRITE-BACK TO HISTORY FILES:
    When --update-history is used, the playlist URL is written back to whichever
    source file the show was loaded from. For shows in live_shows_current.tsv this
    is the primary workflow. For shows in history/*.tsv (older years), write-back
    is LEGACY/BACKFILL-ONLY — once you are current on playlist creation, history
    year files will rarely if ever need updating this way.

NOTE ON PRIVATE/DRAFT VIDEOS (--new-show):
    The YouTube Data API returns private videos when authenticated. Videos that are
    still processing or in a true draft state (never submitted) will NOT appear.
    Upload your videos first, then run --new-show. Private videos are fine.

NOTE: setlist.fm is fetched live. If it blocks or returns no songs, ordering falls
back to upload-date order and the log records "no setlist data" for that URL.
"""

import csv
import glob
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

# ── dependency check ──────────────────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
except ImportError:
    sys.exit(
        "Missing dependency: python-dotenv\n"
        "Run: pip install python-dotenv"
    )

try:
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
except ImportError:
    sys.exit(
        "Missing dependencies. Run:\n"
        "  pip install google-api-python-client google-auth-oauthlib\n"
    )

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit(
        "Missing dependencies for setlist.fm fetching. Run:\n"
        "  pip install requests beautifulsoup4\n"
    )

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ── constants ─────────────────────────────────────────────────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/youtube",
          "https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRETS    = os.environ.get("YOUTUBE_CLIENT_SECRETS", "client_secrets.json")
TOKEN_FILE        = os.environ.get("YOUTUBE_TOKEN_FILE",     "token.json")
CHANNEL_HANDLE    = "dan2bit"

# ── paths ─────────────────────────────────────────────────────────────────────────────────
# Anchored to this file's location so the script works from any working directory.
# The bare relative names these replace predate the repo reorganization that moved
# the show data under data/ and this script under tools/youtube/ — they matched no
# actual working directory, so the venue/show lookups silently degraded unless run
# from exactly the right place.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT  = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
DATA_DIR   = os.path.join(REPO_ROOT, "data")

# Input files
VIDEOS_TSV        = os.path.join(SCRIPT_DIR, "youtube_videos.tsv")
HISTORY_GLOB      = os.path.join(DATA_DIR, "history", "*.tsv")       # per-year archive files
SHOWS_CURRENT_TSV = os.path.join(DATA_DIR, "live_shows_current.tsv") # current year

# Log file — written to logs/ at the repo root, which is gitignored
LOG_TSV = os.path.join(REPO_ROOT, "logs", "playlist_creation_log.tsv")

# Default description template for --fix-descriptions
DEFAULT_DESCRIPTION_TEMPLATE = "Select tracks from {setlist_url}"

# Setlist.fm fetch headers (polite browser impersonation)
SETLIST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; dan2bit-playlist-tool/1.0)"
}
SETLIST_DELAY = 2.0  # seconds between setlist.fm requests

# ── WORKLIST ──────────────────────────────────────────────────────────────────────────────
# Backfill shows: videos are already in youtube_videos.tsv, no live API query needed.
# Process with: python3 youtube_create_playlists.py --worklist --update-history
# (Use --dry-run first to verify video matching looks correct.)

WORKLIST = [
    # (show_date, headliner, title_override)
    # title_override=None means auto-generate from history venue + date
]

# ── auth ──────────────────────────────────────────────────────────────────────────────
def get_authenticated_service():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    client_secrets_path = os.path.join(script_dir, CLIENT_SECRETS)
    token_path = os.path.join(script_dir, TOKEN_FILE)

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                # Dead refresh token (invalid_grant: revoked, or 7-day expiry on a
                # Testing-status OAuth app). Discard and fall through to fresh consent.
                print(f"Stored token in {TOKEN_FILE} can no longer be refreshed "
                      "(invalid_grant) — starting a fresh OAuth flow; a browser "
                      "window will open for consent. USE THE BRAND ACCOUNT...")
                creds = None
        if not creds or not creds.valid:
            if not os.path.exists(client_secrets_path):
                sys.exit(
                    f"OAuth credentials file not found: {client_secrets_path}\n"
                    "Download it from Google Cloud Console → Credentials → OAuth 2.0 Client IDs.\n"
                    "See utils/HOWTO.md → \"YouTube API credentials\" for instructions."
                )
            flow = InstalledAppFlow.from_client_secrets_file(client_secrets_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)

# ── data loading ────────────────────────────────────────────────────────────────────────────
def load_tsv(filename):
    with open(filename, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def load_videos():
    videos = load_tsv(VIDEOS_TSV)
    print(f"Loaded {len(videos)} videos from {VIDEOS_TSV}")
    return videos


def load_history():
    """
    Load show index from history/*.tsv (per-year archive) and live_shows_current.tsv.

    Returns (history_rows, index) where:
      - history_rows: raw rows from history/*.tsv only (used for legacy write-back)
      - index: dict keyed by (Show Date, Artist) covering both sources.
        Rows from live_shows_current.tsv are normalised so process_show sees
        the same field names regardless of source:
            Venue Name        → Venue
            Supporting Artist → Supporting Acts
        A "_source_file" key is added to each row so update_history_playlist_url
        knows which file to write back to.

    NOTE: history/*.tsv write-back via --update-history is legacy/backfill-only.
    The primary workflow is: new show attended → playlist created → URL written to
    live_shows_current.tsv. History year files are frozen once rolled over.
    """
    history_rows = []
    index = {}

    for path in sorted(glob.glob(HISTORY_GLOB)):
        rows = load_tsv(path)
        for r in rows:
            r["_source_file"] = path
            history_rows.append(r)
            index[(r["Show Date"], r["Artist"])] = r

    print(f"Loaded {len(history_rows)} history shows from history/*.tsv")

    if os.path.exists(SHOWS_CURRENT_TSV):
        rows_current = load_tsv(SHOWS_CURRENT_TSV)
        attended = [r for r in rows_current if r.get("Status", "") == "attended"]
        for r in attended:
            normalised = dict(r)
            normalised["Venue"]           = r.get("Venue Name", "")
            normalised["Supporting Acts"] = r.get("Supporting Artist", "")
            normalised["_source_file"]    = SHOWS_CURRENT_TSV
            index[(r["Show Date"], r["Artist"])] = normalised
        print(f"Loaded {len(attended)} attended shows from {SHOWS_CURRENT_TSV}")

    return history_rows, index


# ── date utilities ───────────────────────────────────────────────────────────────────────
def date_variants(date_str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return []
    return [
        f"{d.month}/{d.day}/{d.strftime('%y')}",
        f"{d.month}/{d.day}/{d.year}",
        f"{d.strftime('%m')}/{d.strftime('%d')}/{d.strftime('%y')}",
        f"{d.strftime('%m')}/{d.strftime('%d')}/{d.year}",
    ]

def format_date_short(date_str):
    """YYYY-MM-DD → M/D/YY"""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{d.month}/{d.day}/{d.strftime('%y')}"

# ── venue short name (#189: data/venues.tsv + data/venue_aliases.tsv) ───────────────────────
# The old hardcoded VENUE_SHORT dict moved to shared data. Resolution chain matches
# app.js (_venueKey / shortVenueName) and scripts/check_box_office.py:
#   first-comma-truncate -> key-fold (case, leading "The", punctuation) -> alias -> canonical
# Short Name column (blank = canonical name) supplies the display name; the (VA)/(DC)/(MD)
# tag comes from the venues.tsv State column, falling back to parsing the Address for a
# row whose State is blank. Missing files degrade to plain first-comma truncation, same
# as before.
VENUES_TSV        = os.path.join(DATA_DIR, "venues.tsv")
VENUE_ALIASES_TSV = os.path.join(DATA_DIR, "venue_aliases.tsv")


def _venue_key(v):
    s = re.sub(r"^the\s+", "", (v or "").lower())
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _load_venue_identity():
    aliases, short, state = {}, {}, {}
    try:
        for r in load_tsv(VENUE_ALIASES_TSV):
            a = _venue_key((r.get("Alias") or "").split(",")[0])
            c = (r.get("Venue Name") or "").strip()
            if a and c:
                aliases[a] = c
    except FileNotFoundError:
        pass
    try:
        for r in load_tsv(VENUES_TSV):
            name = (r.get("Venue Name") or "").strip()
            k = _venue_key(name)
            if not k:
                continue
            short[k] = (r.get("Short Name") or "").strip() or name
            st = (r.get("State") or "").strip()
            if not st:
                m = re.search(r",\s*([A-Z]{2})[\s,]", (r.get("Address") or "") + " ")
                st = m.group(1) if m else ""
            if st:
                state[k] = st
    except FileNotFoundError:
        pass
    return aliases, short, state


_VENUE_ALIASES, _VENUE_SHORT, _VENUE_STATE = _load_venue_identity()


def venue_short(venue_str):
    base = (venue_str or "").split(",")[0].strip()
    canonical = _VENUE_ALIASES.get(_venue_key(base), base)
    k = _venue_key(canonical)
    name = _VENUE_SHORT.get(k, canonical)
    st = _VENUE_STATE.get(k)
    return f"{name} ({st})" if st else name


def make_playlist_title(headliner, venue_str, date_str):
    name = re.sub(r'\s*"[^"]+"\s*', ' ', headliner).strip()
    return f"{name} LIVE @ {venue_short(venue_str)} {format_date_short(date_str)}"

# ── video matching ───────────────────────────────────────────────────────────────────────────
def find_videos_for_date(date_str, videos):
    dvs = date_variants(date_str)
    return [v for v in videos if any(dv in v.get("description", "") for dv in dvs)]

def normalize_title(s):
    return re.sub(r"[^\w\s]", "", s.lower()).strip()

def artist_words(artist):
    noise = {"band", "the", "and", "live", "feat", "featuring", "with", "ingram"}
    words = normalize_title(artist).split()
    return [w for w in words if len(w) > 3 and w not in noise]

def video_is_for_artist(video_title, artist):
    vt = normalize_title(video_title)
    for w in artist_words(artist):
        if w in vt:
            return True
    return False

def partition_videos(show_date, headliner, supporting_acts_str, all_date_videos):
    acts = [a.strip() for a in re.split(r"[/&]", supporting_acts_str) if a.strip()] if supporting_acts_str else []
    headliner_vids = []
    support_vids = {act: [] for act in acts}
    unattributed = []
    for v in all_date_videos:
        title = v["title"]
        if video_is_for_artist(title, headliner):
            headliner_vids.append(v)
        else:
            matched_act = None
            for act in acts:
                if video_is_for_artist(title, act):
                    matched_act = act
                    break
            if matched_act:
                support_vids[matched_act].append(v)
            else:
                unattributed.append(v)
    return headliner_vids, support_vids, unattributed

# ── setlist.fm ordering ───────────────────────────────────────────────────────────────────────
def resolve_setlist_url(setlist_url, artist):
    """The per-act setlist URL a show row's Setlist.fm field points at.

    A direct URL belongs to the headliner and is returned as-is (a support
    act gets "" — the field never described their set). MULTI:YYYY-MM-DD
    means every act's link lives in data/setlists/<year>.json under that
    date; the entry for this artist is looked up by case-folded name. Any
    miss returns "" and the caller's no-setlist fallback handles it — the
    string MULTI:date must never reach requests.get, which raises a
    connection-adapter error on it.
    """
    raw = (setlist_url or "").strip()
    if not raw.upper().startswith("MULTI:"):
        return raw
    date_key = raw.split(":", 1)[1].strip()
    path = os.path.join(DATA_DIR, "setlists", f"{date_key[:4]}.json")
    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
    except (OSError, ValueError):
        return ""
    entry = entries.get(date_key) or {}
    wanted = (artist or "").strip().casefold()
    for item in entry.get("setlists", []):
        if (item.get("artist") or "").strip().casefold() == wanted:
            return (item.get("url") or "").strip()
    return ""

def fetch_setlist_songs(setlist_url):
    if not setlist_url:
        return [], "no setlist URL"
    try:
        resp = requests.get(setlist_url, headers=SETLIST_HEADERS, timeout=10)
        time.sleep(SETLIST_DELAY)
        if resp.status_code != 200:
            return [], f"HTTP {resp.status_code}"
        soup = BeautifulSoup(resp.text, "html.parser")
        songs = []
        for tag in soup.find_all(class_="songLabel"):
            t = tag.get_text(strip=True)
            if t:
                songs.append(t)
        if not songs:
            return [], "fetched but no songs found"
        return songs, f"ok ({len(songs)} songs)"
    except Exception as e:
        return [], f"fetch error: {e}"

def order_by_setlist(videos, songs):
    if not songs:
        return sorted(videos, key=lambda v: v.get("published", ""))

    def best_match(video_title, songs):
        vt = normalize_title(video_title)
        vt = re.sub(r"\bbootleg\b", "", vt)
        vt = re.sub(r"\blive\b", "", vt)
        vt = vt.strip()
        best_idx = None
        best_score = 0
        for i, song in enumerate(songs):
            sn = normalize_title(song)
            vwords = set(vt.split())
            swords = set(sn.split())
            shared = len(vwords & swords)
            if shared > best_score and shared >= 1:
                best_score = shared
                best_idx = i
        return best_idx

    placed = {}
    unmatched = []
    for v in videos:
        idx = best_match(v["title"], songs)
        if idx is not None and idx not in placed:
            placed[idx] = v
        else:
            unmatched.append(v)
    ordered = [placed[i] for i in sorted(placed.keys())]
    ordered += sorted(unmatched, key=lambda v: v.get("published", ""))
    return ordered

# ── YouTube API: channel uploads (upload-date match only) ───────────────────────────────
def fetch_uploads_by_date(youtube, date_str):
    channels_resp = youtube.channels().list(
        part="contentDetails",
        mine=True
    ).execute()
    uploads_playlist_id = (
        channels_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    )

    videos = []
    page_token = None
    print(f"  Fetching uploads playlist for {date_str}...")
    while True:
        kwargs = dict(
            part="snippet",
            playlistId=uploads_playlist_id,
            maxResults=50,
        )
        if page_token:
            kwargs["pageToken"] = page_token
        resp = youtube.playlistItems().list(**kwargs).execute()

        for item in resp.get("items", []):
            snippet = item["snippet"]
            published = snippet.get("publishedAt", "")[:10]
            if published == date_str:
                videos.append({
                    "video_id":    snippet["resourceId"]["videoId"],
                    "title":       snippet.get("title", ""),
                    "description": snippet.get("description", ""),
                    "published":   published,
                })

        page_token = resp.get("nextPageToken")

        if resp.get("items"):
            oldest_on_page = min(
                item["snippet"].get("publishedAt", "")[:10]
                for item in resp["items"]
            )
            if oldest_on_page < date_str:
                break

        if not page_token:
            break

    print(f"  Found {len(videos)} video(s) uploaded on {date_str}")
    return videos

# ── YouTube API: playlist operations ──────────────────────────────────────────────────
def create_playlist(youtube, title, description=""):
    resp = youtube.playlists().insert(
        part="snippet,status",
        body={
            "snippet": {"title": title, "description": description},
            "status": {"privacyStatus": "public"},
        }
    ).execute()
    return resp["id"], f"https://www.youtube.com/playlist?list={resp['id']}"

# playlistItems.insert flakes transiently — 409/SERVICE_UNAVAILABLE is a
# known burst failure right after playlist creation, and it once stranded a
# freshly created playlist with zero videos on the first insert. Retry with
# backoff; only a persistent failure propagates.
ADD_RETRIABLE_STATUSES = {409, 500, 502, 503, 504}
ADD_MAX_RETRIES = 5

def add_video_to_playlist(youtube, playlist_id, video_id, position):
    from googleapiclient.errors import HttpError
    for attempt in range(ADD_MAX_RETRIES + 1):
        try:
            youtube.playlistItems().insert(
                part="snippet",
                body={"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}, "position": position}}
            ).execute()
            return
        except HttpError as error:
            status = getattr(getattr(error, "resp", None), "status", None)
            if status not in ADD_RETRIABLE_STATUSES or attempt == ADD_MAX_RETRIES:
                raise
            delay = min(2 ** (attempt + 1), 30)
            print(f"    HTTP {status} adding {video_id} — retry "
                  f"{attempt + 1}/{ADD_MAX_RETRIES} in {delay}s")
            time.sleep(delay)

def fetch_playlist_video_ids(youtube, playlist_id):
    """Video IDs already in a playlist — what makes a re-run resumable."""
    ids = set()
    page_token = None
    while True:
        kwargs = dict(part="snippet", playlistId=playlist_id, maxResults=50)
        if page_token:
            kwargs["pageToken"] = page_token
        resp = youtube.playlistItems().list(**kwargs).execute()
        for item in resp.get("items", []):
            ids.add(item["snippet"]["resourceId"].get("videoId", ""))
        page_token = resp.get("nextPageToken")
        if not page_token:
            return ids

def fetch_all_channel_playlists(youtube):
    playlists = []
    page_token = None
    while True:
        kwargs = dict(part="snippet,contentDetails", mine=True, maxResults=50)
        if page_token:
            kwargs["pageToken"] = page_token
        resp = youtube.playlists().list(**kwargs).execute()
        for item in resp.get("items", []):
            playlists.append({
                "playlist_id":  item["id"],
                "title":        item["snippet"]["title"],
                "description":  item["snippet"].get("description", ""),
                "item_count":   item["contentDetails"]["itemCount"],
                "url":          f"https://www.youtube.com/playlist?list={item['id']}",
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return playlists

def update_playlist_description(youtube, playlist_id, title, new_description):
    youtube.playlists().update(
        part="snippet",
        body={
            "id": playlist_id,
            "snippet": {
                "title": title,
                "description": new_description,
            }
        }
    ).execute()

# ── show file write-back ─────────────────────────────────────────────────────────────────────────
def update_history_playlist_url(date_str, artist, playlist_url, show_row=None):
    """
    Write the playlist URL back to the appropriate source file.

    For shows in live_shows_current.tsv this is the primary workflow — new
    playlists created during the current year are written back here.

    For shows in history/*.tsv (older years), write-back is LEGACY/BACKFILL-ONLY.
    The source file is determined by the '_source_file' key set at load time,
    which for history shows will be the specific year file (e.g. 'history/2023.tsv').
    """
    source_file = (show_row or {}).get("_source_file") or SHOWS_CURRENT_TSV

    artist_col    = "Artist"
    date_col      = "Show Date"
    url_col       = "Playlist URL"
    # History year files have Match Type; current file does not
    match_type_col = "Match Type" if source_file != SHOWS_CURRENT_TSV else None

    _write_playlist_url_to_file(
        source_file, date_str, artist, playlist_url,
        artist_col=artist_col, date_col=date_col,
        url_col=url_col, match_type_col=match_type_col
    )


def _write_playlist_url_to_file(filepath, date_str, artist, playlist_url,
                                 artist_col, date_col, url_col, match_type_col):
    rows = load_tsv(filepath)
    if not rows:
        print(f"  WARNING: {filepath} is empty")
        return
    fieldnames = list(rows[0].keys())
    updated = False
    for r in rows:
        if r.get(date_col) == date_str and r.get(artist_col) == artist:
            r[url_col] = playlist_url
            if match_type_col and match_type_col in r:
                r[match_type_col] = "Playlist (assembled)"
            updated = True
            break
    if updated:
        # Plain tab-joined lines, LF endings, no quoting — the repo's TSVs
        # are never csv-quoted. csv.DictWriter's defaults (QUOTE_MINIMAL +
        # CRLF lineterminator) once rewrote the whole current file with CRLF
        # endings and quote-wrapped the two Notes fields that legitimately
        # contain double quotes, corrupting rows the update never touched.
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\t".join(fieldnames) + "\n")
            for r in rows:
                f.write("\t".join(r.get(k) or "" for k in fieldnames) + "\n")
        print(f"  Updated {filepath} with playlist URL")
    else:
        print(f"  WARNING: could not find {date_str} / {artist} in {filepath}")

# ── log ──────────────────────────────────────────────────────────────────────────────────
LOG_FIELDNAMES = ["Show Date", "Artist", "Playlist Title", "Playlist URL", "Video Count", "Setlist URL Checked", "Setlist Order Used", "Videos Added"]

def write_log_row(log_rows):
    os.makedirs(os.path.dirname(LOG_TSV), exist_ok=True)
    write_header = not os.path.exists(LOG_TSV)
    with open(LOG_TSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDNAMES, delimiter="\t")
        if write_header:
            writer.writeheader()
        for row in log_rows:
            writer.writerow(row)


# ── metadata refresh (issue #278 item 3) ──────────────────────────────────────────────────
def refresh_metadata_tsvs():
    """Refresh youtube_videos.tsv / youtube_playlists.tsv by running
    youtube_fetch once, so a freshly created playlist and the now-titled
    videos are captured without a manual second pass (#278 item 3).

    A single fetch after creation captures both — the videos already carry
    their applied titles and the new playlist now exists — replacing the
    old run-fetch-before-and-after chore. Best-effort by design: youtube_fetch
    owns its own API key, runs with --since auto (cheap and idempotent), and
    any failure here is reported but never undoes the playlist just created.
    """
    fetch = os.path.join(SCRIPT_DIR, "youtube_fetch.py")
    if not os.path.exists(fetch):
        print(f"\nSkipping metadata refresh — {fetch} not found; "
              "run youtube_fetch.py manually.")
        return
    print("\nRefreshing YouTube metadata (youtube_fetch.py --since auto)...")
    try:
        result = subprocess.run([sys.executable, fetch, "--since", "auto"],
                                cwd=SCRIPT_DIR)
        if result.returncode != 0:
            print(f"  WARNING: youtube_fetch.py exited {result.returncode} — "
                  "run it manually to refresh the metadata TSVs.")
    except Exception as e:
        print(f"  WARNING: could not run youtube_fetch.py ({e}) — "
              "run it manually to refresh the metadata TSVs.")

# ── core per-show processing ────────────────────────────────────────────────────────────────
def process_show(youtube, date_str, headliner, title_override, videos, history_index,
                 dry_run=False, update_history=False, use_channel_uploads=False):
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Processing: {date_str} — {headliner}")

    show = history_index.get((date_str, headliner))
    if not show:
        matches = [(k, v) for k, v in history_index.items() if k[0] == date_str and headliner.lower()[:8] in k[1].lower()]
        if matches:
            show = matches[0][1]
            print(f"  Fuzzy match: {matches[0][0][1]}")
        else:
            print(f"  WARNING: show not found in history or current file — proceeding without venue/setlist data")
            show = {}

    source_file = show.get("_source_file", SHOWS_CURRENT_TSV)
    print(f"  Source file: {source_file}")

    venue_str      = show.get("Venue", "")
    supporting_str = show.get("Supporting Acts", "")
    setlist_url    = show.get("Setlist.fm URL", "")

    date_vids = []
    if use_channel_uploads and youtube and not dry_run:
        date_vids = find_videos_for_date(date_str, videos)
        if not date_vids:
            print(f"  No videos in youtube_videos.tsv for {date_str} — trying channel uploads API")
            date_vids = fetch_uploads_by_date(youtube, date_str)
        else:
            print(f"  Found {len(date_vids)} video(s) in youtube_videos.tsv — skipping uploads API")
    else:
        if use_channel_uploads and dry_run:
            print("  [DRY RUN] Would check youtube_videos.tsv first, then channel uploads API if needed")
        date_vids = find_videos_for_date(date_str, videos)

    if not date_vids:
        print(f"  No videos found for {date_str} — skipping")
        return None

    print(f"  Found {len(date_vids)} video(s) for this date")
    headliner_vids, support_vids, unattributed = partition_videos(date_str, headliner, supporting_str, date_vids)
    print(f"  Headliner: {len(headliner_vids)} | Support: {sum(len(v) for v in support_vids.values())} | Unattributed: {len(unattributed)}")
    headliner_vids += unattributed

    headliner_url = resolve_setlist_url(setlist_url, headliner)
    setlist_songs, setlist_status = fetch_setlist_songs(headliner_url)
    print(f"  Setlist.fm ({headliner_url or setlist_url or 'none'}): {setlist_status}")
    headliner_vids = order_by_setlist(headliner_vids, setlist_songs)

    ordered_support = []
    for act, act_vids in support_vids.items():
        if act_vids:
            act_url = resolve_setlist_url(setlist_url, act)
            act_songs, act_status = fetch_setlist_songs(act_url)
            if act_songs:
                act_sorted = order_by_setlist(act_vids, act_songs)
                note = f"setlist order — {act_status}"
            else:
                act_sorted = sorted(act_vids, key=lambda v: v.get("published", ""))
                note = f"upload order — {act_status}"
            ordered_support.extend(act_sorted)
            print(f"  Supporting act '{act}': {len(act_vids)} video(s) ({note})")

    final_order = headliner_vids + ordered_support

    playlist_title = title_override or make_playlist_title(headliner, venue_str, date_str)
    # The playlist description carries the setlist link (video descriptions
    # deliberately do not — see youtube_upload_show.build_description). Built
    # here so the CREATE path writes it; historically only the separate
    # --fix-descriptions backfill ever set descriptions, so every new playlist
    # shipped blank (found via the 2026-08-12 Southern Avenue playlist).
    playlist_desc = (DEFAULT_DESCRIPTION_TEMPLATE.format(
        setlist_url=headliner_url, venue=venue_str)
        if headliner_url else "")
    print(f"  Playlist title: {playlist_title}")
    print(f"  Playlist description: {playlist_desc or '[none - no setlist URL]'}")
    for i, v in enumerate(final_order, 1):
        print(f"    {i:2}. {v['title'][:80]}")

    playlist_url = "[dry run — no playlist created]"
    if not dry_run:
        # A crashed earlier run may have left this playlist already created
        # (possibly empty, possibly partial). Reuse it and add only what is
        # missing, so a re-run resumes instead of minting a duplicate.
        playlist_id = None
        existing_ids = set()
        for pl in fetch_all_channel_playlists(youtube):
            if pl["title"] == playlist_title:
                playlist_id = pl["playlist_id"]
                playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
                existing_ids = fetch_playlist_video_ids(youtube, playlist_id)
                print(f"  Reusing existing playlist ({len(existing_ids)} "
                      f"video(s) already in it): {playlist_url}")
                if playlist_desc and not pl["description"].strip():
                    update_playlist_description(
                        youtube, playlist_id, pl["title"], playlist_desc)
                    print("  Backfilled blank playlist description")
                break
        if playlist_id is None:
            print("  Creating playlist...")
            playlist_id, playlist_url = create_playlist(
                youtube, playlist_title, playlist_desc)
            print(f"  Playlist created: {playlist_url}")
        added = 0
        for pos, v in enumerate(final_order):
            if v["video_id"] in existing_ids:
                continue
            add_video_to_playlist(youtube, playlist_id, v["video_id"], pos)
            added += 1
            time.sleep(0.3)
        print(f"  Added {added} video(s)"
              + (f" ({len(existing_ids)} were already present)"
                 if existing_ids else ""))
        if update_history:
            update_history_playlist_url(date_str, headliner, playlist_url, show_row=show)

    log_row = {
        "Show Date": date_str, "Artist": headliner, "Playlist Title": playlist_title,
        "Playlist URL": playlist_url, "Video Count": len(final_order),
        "Setlist URL Checked": setlist_url or "none", "Setlist Order Used": setlist_status,
        "Videos Added": " | ".join(v["title"] for v in final_order),
    }
    write_log_row([log_row])
    return playlist_url

# ── fix-descriptions mode ────────────────────────────────────────────────────────────────────
def run_fix_descriptions(youtube, history_index, description_template, date_filter=None, dry_run=False):
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Fetching all channel playlists...")
    playlists = fetch_all_channel_playlists(youtube)
    print(f"  Found {len(playlists)} playlists on channel")

    url_to_history = {}
    for (date_str, artist), row in history_index.items():
        purl = row.get("Playlist URL", "")
        if purl and purl.startswith("https://www.youtube.com/playlist"):
            url_to_history[purl.strip()] = row

    updated = 0
    skipped_has_desc = 0
    skipped_no_match = 0
    skipped_no_setlist = 0

    for pl in playlists:
        if pl["description"].strip():
            skipped_has_desc += 1
            continue

        if date_filter:
            history_row = url_to_history.get(pl["url"])
            if not history_row or history_row.get("Show Date") not in date_filter:
                continue

        history_row = url_to_history.get(pl["url"])
        if not history_row:
            skipped_no_match += 1
            print(f"  SKIP (no history match): {pl['title']}")
            continue

        setlist_url = history_row.get("Setlist.fm URL", "").strip()
        if not setlist_url:
            skipped_no_setlist += 1
            print(f"  SKIP (no setlist URL): {pl['title']}")
            continue

        venue_str = history_row.get("Venue", "")
        new_desc = description_template.format(
            setlist_url=setlist_url,
            venue=venue_short(venue_str),
        )

        print(f"  {'[DRY RUN] ' if dry_run else ''}UPDATE: {pl['title']}")
        print(f"    → {new_desc}")

        if not dry_run:
            update_playlist_description(youtube, pl["playlist_id"], pl["title"], new_desc)
            time.sleep(0.5)

        updated += 1

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Fix-descriptions summary:")
    print(f"  Updated:              {updated}")
    print(f"  Already had desc:     {skipped_has_desc}")
    print(f"  No history match:     {skipped_no_match}")
    print(f"  No setlist URL:       {skipped_no_setlist}")

# ── main ──────────────────────────────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Create/manage YouTube playlists for @dan2bit shows")

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--new-show",        metavar="DATE",
                            help=(
                                "Create playlist(s) for attended show(s). "
                                "Pass a single date (YYYY-MM-DD) to create one playlist, "
                                "or since:YYYY-MM-DD to create playlists for all attended shows "
                                "on or after that date whose Playlist URL is not yet populated. "
                                "Tries channel uploads API first (for brand-new private videos), "
                                "then falls back to youtube_videos.tsv."
                            ))
    mode_group.add_argument("--fix-descriptions", action="store_true",
                            help="Find playlists with blank descriptions and fill in setlist.fm link. Always use --dry-run first or --date to limit scope.")
    mode_group.add_argument("--worklist",         action="store_true",
                            help="Process shows in WORKLIST using youtube_videos.tsv (backfill mode).")
    mode_group.add_argument("--date",             nargs="+", metavar="DATE",
                            help="Process show(s) by date from youtube_videos.tsv.")

    parser.add_argument("--headliner",            metavar="NAME",
                        help="Override headliner name (single-date --new-show only).")
    parser.add_argument("--title",                metavar="TITLE",
                        help="Override playlist title instead of auto-generating.")
    parser.add_argument("--description-template", metavar="TEMPLATE",
                        default=DEFAULT_DESCRIPTION_TEMPLATE,
                        help=f"Template for --fix-descriptions. Placeholders: {{setlist_url}}, {{venue}}. "
                             f"Default: \"{DEFAULT_DESCRIPTION_TEMPLATE}\"")
    parser.add_argument("--update-history",       action="store_true",
                        help="Write created playlist URL back to the source show file "
                             "(live_shows_current.tsv for new shows; history/*.tsv for backfill).")
    parser.add_argument("--dry-run",              action="store_true",
                        help="Show what would happen without making any API calls.")
    parser.add_argument("--auth-only",            action="store_true",
                        help="Authenticate and save token.json, then exit.")

    args = parser.parse_args()

    youtube = None
    if not args.dry_run or args.fix_descriptions:
        print("Authenticating with YouTube...")
        youtube = get_authenticated_service()
        print("Authenticated.")
        if args.auth_only:
            print("Auth complete. token.json saved.")
            return

    videos = load_videos()
    history_rows, history_index = load_history()
    print(f"Loaded {len(history_rows)} history shows")

    if args.fix_descriptions:
        date_filter = set(args.date) if args.date else None
        run_fix_descriptions(
            youtube, history_index,
            description_template=args.description_template,
            date_filter=date_filter,
            dry_run=args.dry_run,
        )
        return

    if args.new_show:
        new_show_arg = args.new_show

        if new_show_arg.startswith("since:"):
            since_date = new_show_arg[len("since:"):]
            try:
                datetime.strptime(since_date, "%Y-%m-%d")
            except ValueError:
                sys.exit(f"Invalid date in since: prefix — expected since:YYYY-MM-DD, got: {new_show_arg}")

            if args.headliner:
                sys.exit("--headliner cannot be used with since: range mode.")

            queue = sorted(
                [
                    (date_str, artist, show)
                    for (date_str, artist), show in history_index.items()
                    if date_str >= since_date and not (show.get("Playlist URL") or "").strip()
                ],
                key=lambda t: t[0],
            )

            if not queue:
                print(f"No shows without playlists found on or after {since_date}.")
                return

            print(f"\nShows to process ({len(queue)} total, since {since_date}):")
            for date_str, artist, _ in queue:
                print(f"  {date_str}  {artist}")

            results = []
            for date_str, artist, show in queue:
                url = process_show(
                    youtube, date_str, artist, args.title, videos, history_index,
                    dry_run=args.dry_run,
                    update_history=args.update_history,
                    use_channel_uploads=True,
                )
                results.append((date_str, artist, url))

            print(f"\n{'='*60}")
            print(f"{'DRY RUN ' if args.dry_run else ''}SUMMARY — {len(results)} show(s) processed")
            for date_str, artist, url in results:
                status = url or "skipped (no videos)"
                print(f"  {date_str}  {artist:<35}  {status}")
            print(f"\nLog written to: {LOG_TSV}")
            if args.update_history and not args.dry_run:
                print("Source files updated with playlist URLs")
            if not args.dry_run and any(url for _, _, url in results):
                refresh_metadata_tsvs()
            return

        date_str = new_show_arg
        headliner = args.headliner
        if not headliner:
            matches = [(k, v) for k, v in history_index.items() if k[0] == date_str]
            if len(matches) == 1:
                headliner = matches[0][0][1]
                print(f"Found in history/current: {date_str} — {headliner}")
            elif len(matches) > 1:
                print(f"Multiple shows on {date_str}:")
                for k, v in matches:
                    print(f"  {k[1]}")
                sys.exit("Use --headliner to specify which one.")
            else:
                sys.exit(
                    f"No show found for {date_str} in history/*.tsv or {SHOWS_CURRENT_TSV}.\n"
                    f"Use --headliner to specify the artist, or add the show to the tracking file first."
                )

        url = process_show(
            youtube, date_str, headliner, args.title, videos, history_index,
            dry_run=args.dry_run,
            update_history=args.update_history,
            use_channel_uploads=True,
        )
        print(f"\nResult: {url or 'skipped'}")
        if not args.dry_run and url:
            refresh_metadata_tsvs()
        return

    if args.worklist:
        if not WORKLIST:
            print("WORKLIST is empty — nothing to process.")
            print("Use --new-show DATE to create a playlist for a recent show.")
            return
        queue_tuples = [(d, a, t) for d, a, t in WORKLIST]
        print(f"Processing {len(queue_tuples)} shows from WORKLIST")

    elif args.date:
        worklist_index = {d: (d, a, t) for d, a, t in WORKLIST}
        queue_tuples = []
        for date_str in args.date:
            if date_str in worklist_index:
                queue_tuples.append(worklist_index[date_str])
            else:
                matches = [(k, v) for k, v in history_index.items() if k[0] == date_str]
                if matches:
                    artist = matches[0][0][1]
                    queue_tuples.append((date_str, artist, None))
                    print(f"  Found in history/current: {date_str} — {artist}")
                else:
                    print(f"  WARNING: {date_str} not found in history, current file, or worklist — skipping")
    else:
        parser.print_help()
        return

    results = []
    for date_str, headliner, title_override in queue_tuples:
        url = process_show(
            youtube, date_str, headliner, args.title or title_override, videos, history_index,
            dry_run=args.dry_run,
            update_history=args.update_history,
            use_channel_uploads=False,
        )
        results.append((date_str, headliner, url))

    print(f"\n{'='*60}")
    print(f"{'DRY RUN ' if args.dry_run else ''}SUMMARY — {len(results)} show(s) processed")
    for date_str, headliner, url in results:
        print(f"  {date_str}  {headliner:<35}  {url or 'skipped'}")
    print(f"\nLog written to: {LOG_TSV}")
    if args.update_history and not args.dry_run:
        print("Source files updated with playlist URLs")

if __name__ == "__main__":
    main()
