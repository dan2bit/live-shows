#!/usr/bin/env python3
"""
youtube_fix_descriptions.py — Bulk and targeted description editor for @dan2bit YouTube channel

Supports search-and-replace, search-and-append, and targeted single-item or
per-playlist-video operations on video and/or playlist descriptions.

REQUIRES OAuth with https://www.googleapis.com/auth/youtube scope (same token.json
used by youtube_create_playlists.py).

QUOTA NOTE:
    Each description update costs approximately 50 quota units (videos.update or
    playlists.update). Reads are cheap (~1-3 units). The --cap flag (default: 10)
    prevents runaway runs. Always use --dry-run first, then raise --cap deliberately.

    By default, bulk video operations read from youtube_videos.tsv (zero quota).
    Pass --live to fetch descriptions live from the API instead.

USAGE:

  ── Search & replace across videos, playlists, or both ──────────────────────────

    # Replace a substring in all matching video descriptions (dry run first)
    # Reads from youtube_videos.tsv by default (no quota cost for reads)
    python3 youtube_fix_descriptions.py \\
        --search "Ram's Head" --replace "Rams Head" --target videos --dry-run

    # Apply for real, capped at 60 items
    python3 youtube_fix_descriptions.py \\
        --search "Ram's Head" --replace "Rams Head" --target videos --cap 60

    # Use live API fetch instead of TSV (costs read quota)
    python3 youtube_fix_descriptions.py \\
        --search "Ram's Head" --replace "Rams Head" --target videos --cap 60 --live

    # Same for playlists only (playlists always use live API)
    python3 youtube_fix_descriptions.py \\
        --search "Ram's Head" --replace "Rams Head" --target playlists --cap 20

    # Both videos and playlists
    python3 youtube_fix_descriptions.py \\
        --search "Ram's Head" --replace "Rams Head" --target both --cap 80

  ── Search & append ─────────────────────────────────────────────────────────────

    # Append a string to all video descriptions that contain a search term
    python3 youtube_fix_descriptions.py \\
        --search "Birchmere" --append "\\\\n\\\\n#Alexandria #Virginia" --target videos --dry-run

    # Append to ALL video descriptions (no --search filter)
    python3 youtube_fix_descriptions.py \\
        --append "\\\\n\\\\n#livemusic #bootleg" --target videos --cap 20 --dry-run

  ── Optional title filter (reduces items considered) ────────────────────────────

    # Only consider videos whose title matches a regex
    python3 youtube_fix_descriptions.py \\
        --search "Ram's Head" --replace "Rams Head" --target videos \\
        --title-filter "Ram" --cap 30 --dry-run

  ── Single item: full replace or append by video/playlist ID ────────────────────

    # Replace the entire description of one video
    python3 youtube_fix_descriptions.py \\
        --id dQw4w9WgXcQ --item-type video \\
        --replace-desc "New description text here." --dry-run

    # Append to one video's description
    python3 youtube_fix_descriptions.py \\
        --id dQw4w9WgXcQ --item-type video \\
        --append-desc "\\\\n\\\\nAdditional line."

    # Full replace on a playlist description
    python3 youtube_fix_descriptions.py \\
        --id PLJ7S-K0cjvGKiu9D23lUv6bKPDFn4yeF0 --item-type playlist \\
        --replace-desc "Select tracks from https://www.setlist.fm/..."

    # Append to a playlist description
    python3 youtube_fix_descriptions.py \\
        --id PLJ7S-K0cjvGKiu9D23lUv6bKPDFn4yeF0 --item-type playlist \\
        --append-desc "\\\\n\\\\n#livemusic"

  ── All videos in a playlist ────────────────────────────────────────────────────

    # Append a string to every video description in a playlist
    python3 youtube_fix_descriptions.py \\
        --playlist-videos PLJ7S-K0cjvGKiu9D23lUv6bKPDFn4yeF0 \\
        --append-desc "\\\\n\\\\n#Birchmere" --dry-run

    # Full replace on every video description in a playlist
    python3 youtube_fix_descriptions.py \\
        --playlist-videos PLJ7S-K0cjvGKiu9D23lUv6bKPDFn4yeF0 \\
        --replace-desc "New unified description." --dry-run

OUTPUT LOG:
    logs/description_fix_log.tsv — one row per item updated:
        Timestamp, Item Type, Item ID, Title, Operation, Old Description, New Description

NOTES:
    - --cap default is 10. Raise it deliberately after reviewing --dry-run output.
    - If the number of matching items exceeds --cap, the script warns you and stops
      after --cap items. Use --title-filter to narrow scope, or raise --cap.
    - Escape sequences like \\\\n in --append / --append-desc / --replace-desc are
      interpreted (i.e. \\\\n becomes a real newline).
    - TSV source (default): reads video_id, title, description from youtube_videos.tsv.
      Zero quota cost for reads. Use --live to fetch from API instead.
"""

import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime

# ── dependency check ──────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
except ImportError:
    sys.exit("Missing dependency: python-dotenv\nRun: pip install python-dotenv")

try:
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
except ImportError:
    sys.exit(
        "Missing dependencies. Run:\n"
        "  pip install google-api-python-client google-auth-oauthlib\n"
    )

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ── constants ─────────────────────────────────────────────────────────────────
SCOPES         = ["https://www.googleapis.com/auth/youtube"]
CLIENT_SECRETS = os.environ.get("YOUTUBE_CLIENT_SECRETS", "client_secrets.json")
TOKEN_FILE     = os.environ.get("YOUTUBE_TOKEN_FILE", "token.json")
VIDEOS_TSV     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "youtube_videos.tsv")
LOG_TSV        = os.path.join("logs", "description_fix_log.tsv")
LOG_FIELDS     = ["Timestamp", "Item Type", "Item ID", "Title",
                  "Operation", "Old Description", "New Description"]
API_DELAY      = 0.3   # seconds between write calls

# ── auth ──────────────────────────────────────────────────────────────────────
def get_authenticated_service():
    script_dir          = os.path.dirname(os.path.abspath(__file__))
    client_secrets_path = os.path.join(script_dir, CLIENT_SECRETS)
    token_path          = os.path.join(script_dir, TOKEN_FILE)

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
            flow  = InstalledAppFlow.from_client_secrets_file(client_secrets_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)


# ── logging ───────────────────────────────────────────────────────────────────
def write_log(rows):
    os.makedirs(os.path.dirname(LOG_TSV), exist_ok=True)
    write_header = not os.path.exists(LOG_TSV)
    with open(LOG_TSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS, delimiter="\t")
        if write_header:
            w.writeheader()
        for row in rows:
            w.writerow(row)


# ── fetch helpers ─────────────────────────────────────────────────────────────
def fetch_videos_from_tsv(title_filter_re=None):
    """Return list of {video_id, title, description} from youtube_videos.tsv (zero quota)."""
    if not os.path.exists(VIDEOS_TSV):
        sys.exit(
            f"youtube_videos.tsv not found at: {VIDEOS_TSV}\n"
            "Run youtube_fetch.py to generate it, or use --live to fetch from the API."
        )
    videos = []
    with open(VIDEOS_TSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            title = row.get("title", "")
            if title_filter_re and not title_filter_re.search(title):
                continue
            videos.append({
                "video_id":    row.get("video_id", ""),
                "title":       title,
                "description": row.get("description", ""),
            })
    return videos


def fetch_all_channel_videos(youtube, title_filter_re=None):
    """
    Return list of {video_id, title, description} for all channel uploads via API.

    Two-pass approach:
      Pass 1 — collect video IDs and titles from playlistItems (cheap reads).
               Note: playlistItems snippets contain playlist-level descriptions,
               NOT the actual video descriptions — so we do not use them for desc.
      Pass 2 — batch-fetch real video descriptions via videos.list (50 per call).
    """
    channels_resp       = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads_playlist_id = (
        channels_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    )

    # Pass 1: collect video IDs and titles
    candidates = []
    page_token = None
    while True:
        kwargs = dict(part="snippet", playlistId=uploads_playlist_id, maxResults=50)
        if page_token:
            kwargs["pageToken"] = page_token
        resp = youtube.playlistItems().list(**kwargs).execute()
        for item in resp.get("items", []):
            sn    = item["snippet"]
            title = sn.get("title", "")
            if title_filter_re and not title_filter_re.search(title):
                continue
            candidates.append({
                "video_id": sn["resourceId"]["videoId"],
                "title":    title,
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    if not candidates:
        return []

    # Pass 2: fetch real video descriptions in batches of 50
    videos = []
    for i in range(0, len(candidates), 50):
        batch = candidates[i:i + 50]
        ids   = ",".join(v["video_id"] for v in batch)
        resp  = youtube.videos().list(part="snippet", id=ids).execute()
        desc_map = {
            item["id"]: item["snippet"].get("description", "")
            for item in resp.get("items", [])
        }
        for v in batch:
            videos.append({
                "video_id":    v["video_id"],
                "title":       v["title"],
                "description": desc_map.get(v["video_id"], ""),
            })
    return videos


def fetch_all_channel_playlists(youtube, title_filter_re=None):
    """Return list of {playlist_id, title, description} for all channel playlists."""
    playlists  = []
    page_token = None
    while True:
        kwargs = dict(part="snippet", mine=True, maxResults=50)
        if page_token:
            kwargs["pageToken"] = page_token
        resp = youtube.playlists().list(**kwargs).execute()
        for item in resp.get("items", []):
            sn    = item["snippet"]
            title = sn.get("title", "")
            if title_filter_re and not title_filter_re.search(title):
                continue
            playlists.append({
                "playlist_id":  item["id"],
                "title":        title,
                "description":  sn.get("description", ""),
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return playlists


def fetch_video(youtube, video_id):
    """Return {video_id, title, description} for a single video."""
    resp = youtube.videos().list(part="snippet", id=video_id).execute()
    if not resp.get("items"):
        sys.exit(f"Video not found: {video_id}")
    sn = resp["items"][0]["snippet"]
    return {"video_id": video_id, "title": sn.get("title", ""),
            "description": sn.get("description", "")}


def fetch_playlist(youtube, playlist_id):
    """Return {playlist_id, title, description} for a single playlist."""
    resp = youtube.playlists().list(part="snippet", id=playlist_id).execute()
    if not resp.get("items"):
        sys.exit(f"Playlist not found: {playlist_id}")
    sn = resp["items"][0]["snippet"]
    return {"playlist_id": playlist_id, "title": sn.get("title", ""),
            "description": sn.get("description", "")}


def fetch_videos_in_playlist(youtube, playlist_id):
    """Return list of {video_id, title, description} for all videos in a playlist."""
    candidates = []
    page_token = None
    while True:
        kwargs = dict(part="snippet", playlistId=playlist_id, maxResults=50)
        if page_token:
            kwargs["pageToken"] = page_token
        resp = youtube.playlistItems().list(**kwargs).execute()
        for item in resp.get("items", []):
            sn = item["snippet"]
            candidates.append({
                "video_id": sn["resourceId"]["videoId"],
                "title":    sn.get("title", ""),
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    # Fetch real video descriptions in batches of 50
    result = []
    for i in range(0, len(candidates), 50):
        batch = candidates[i:i + 50]
        ids   = ",".join(v["video_id"] for v in batch)
        resp  = youtube.videos().list(part="snippet", id=ids).execute()
        desc_map = {
            item["id"]: item["snippet"].get("description", "")
            for item in resp.get("items", [])
        }
        for v in batch:
            result.append({
                "video_id":    v["video_id"],
                "title":       v["title"],
                "description": desc_map.get(v["video_id"], ""),
            })
    return result


# ── update helpers ────────────────────────────────────────────────────────────
def update_video_description(youtube, video_id, new_description, dry_run):
    if dry_run:
        return
    resp    = youtube.videos().list(part="snippet", id=video_id).execute()
    snippet = resp["items"][0]["snippet"]
    snippet["description"] = new_description
    youtube.videos().update(
        part="snippet",
        body={"id": video_id, "snippet": snippet}
    ).execute()
    time.sleep(API_DELAY)


def update_playlist_description(youtube, playlist_id, new_description, dry_run):
    if dry_run:
        return
    resp    = youtube.playlists().list(part="snippet", id=playlist_id).execute()
    snippet = resp["items"][0]["snippet"]
    snippet["description"] = new_description
    youtube.playlists().update(
        part="snippet",
        body={"id": playlist_id, "snippet": snippet}
    ).execute()
    time.sleep(API_DELAY)


# ── compute new description ───────────────────────────────────────────────────
def apply_operation(old_desc, operation, search, replacement, append_str, replace_desc):
    """
    Returns (new_desc, changed: bool, op_label: str).

    Operations:
      'search_replace'  — replace all occurrences of search with replacement
      'search_append'   — append append_str if search found (or always if search is None)
      'full_replace'    — replace entire description with replace_desc
      'append'          — unconditional append of append_str
    """
    if operation == "full_replace":
        new_desc = replace_desc
        return new_desc, new_desc != old_desc, "full_replace"

    if operation == "append":
        new_desc = old_desc + append_str
        return new_desc, True, "append"

    if operation == "search_replace":
        if search not in old_desc:
            return old_desc, False, "search_replace"
        new_desc = old_desc.replace(search, replacement)
        return new_desc, new_desc != old_desc, "search_replace"

    if operation == "search_append":
        if search is not None and search not in old_desc:
            return old_desc, False, "search_append"
        new_desc = old_desc + append_str
        return new_desc, True, "search_append"

    raise ValueError(f"Unknown operation: {operation}")


# ── process a list of items ───────────────────────────────────────────────────
def process_items(youtube, items, item_type, id_key, operation,
                  search, replacement, append_str, replace_desc,
                  cap, dry_run):
    """
    items: list of dicts with id_key, 'title', 'description'
    Returns number of items updated.
    """
    matched = [it for it in items
               if _matches_filter(it["description"], operation, search)]

    total_matched = len(matched)
    if total_matched == 0:
        print(f"  No matching {item_type}s found.")
        return 0

    if total_matched > cap:
        print(
            f"  ⚠️  Found {total_matched} matching {item_type}s — exceeds --cap {cap}.\n"
            f"  Only the first {cap} will be processed. Use --title-filter to narrow\n"
            f"  scope, or raise --cap explicitly if you intend to process all of them."
        )
        matched = matched[:cap]

    log_rows = []
    updated  = 0
    for it in matched:
        old_desc = it["description"]
        new_desc, changed, op_label = apply_operation(
            old_desc, operation, search, replacement, append_str, replace_desc
        )
        item_id = it[id_key]
        title   = it["title"]

        status = ""
        if not changed:
            status = " (no change)"

        print(f"  {'[DRY RUN] ' if dry_run else ''}"
              f"{item_type.upper()} {item_id[:16]}… — {title[:60]}{status}")
        if changed:
            print(f"    OLD: {old_desc[:120].replace(chr(10), '↵')}")
            print(f"    NEW: {new_desc[:120].replace(chr(10), '↵')}")

        if changed:
            if item_type == "video":
                update_video_description(youtube, item_id, new_desc, dry_run)
            else:
                update_playlist_description(youtube, item_id, new_desc, dry_run)
            updated += 1
            log_rows.append({
                "Timestamp":       datetime.utcnow().isoformat(),
                "Item Type":       item_type,
                "Item ID":         item_id,
                "Title":           title,
                "Operation":       op_label,
                "Old Description": old_desc,
                "New Description": new_desc,
            })

    if log_rows and not dry_run:
        write_log(log_rows)

    return updated


def _matches_filter(description, operation, search):
    """Return True if this item should be considered for the operation."""
    if operation in ("full_replace", "append"):
        return True   # unconditional
    if search is None:
        return True   # search_append with no filter = all items
    return search in description


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Bulk and targeted YouTube description editor for @dan2bit channel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # ── mode A: bulk search/replace/append across videos and/or playlists ────
    bulk_group = parser.add_argument_group("Bulk mode (videos / playlists / both)")
    bulk_group.add_argument("--search",
        metavar="STR",
        help="Substring to search for in descriptions.")
    bulk_group.add_argument("--replace",
        metavar="STR",
        help="Replace all occurrences of --search with this string.")
    bulk_group.add_argument("--append",
        metavar="STR",
        help="Append this string to descriptions that contain --search "
             "(or to all descriptions if --search is omitted).")
    bulk_group.add_argument("--target",
        choices=["videos", "playlists", "both"],
        default="videos",
        help="What to operate on in bulk mode. Default: videos.")
    bulk_group.add_argument("--title-filter",
        metavar="REGEX",
        help="Only consider items whose title matches this regex.")
    bulk_group.add_argument("--cap",
        type=int,
        default=10,
        help="Max items to update in bulk mode. Default: 10. Raise deliberately.")
    bulk_group.add_argument("--live",
        action="store_true",
        help="Fetch video descriptions live from the YouTube API instead of reading "
             "from youtube_videos.tsv. Costs read quota. Playlists always use live API.")

    # ── mode B: single item by ID ─────────────────────────────────────────────
    single_group = parser.add_argument_group("Single-item mode (--id)")
    single_group.add_argument("--id",
        metavar="ID",
        help="Video ID or playlist ID to operate on.")
    single_group.add_argument("--item-type",
        choices=["video", "playlist"],
        default="video",
        help="Whether --id refers to a video or playlist. Default: video.")
    single_group.add_argument("--replace-desc",
        metavar="TEXT",
        help="Replace the entire description of the item with TEXT.")
    single_group.add_argument("--append-desc",
        metavar="TEXT",
        help="Append TEXT to the description of the item.")

    # ── mode C: all videos in a playlist ─────────────────────────────────────
    playlist_group = parser.add_argument_group("Playlist-videos mode (--playlist-videos)")
    playlist_group.add_argument("--playlist-videos",
        metavar="PLAYLIST_ID",
        help="Apply --replace-desc or --append-desc to every video in this playlist.")

    # ── shared ────────────────────────────────────────────────────────────────
    parser.add_argument("--dry-run",
        action="store_true",
        help="Preview changes without making any API write calls.")
    parser.add_argument("--auth-only",
        action="store_true",
        help="Authenticate and cache token.json, then exit.")

    args = parser.parse_args()

    # ── authenticate ──────────────────────────────────────────────────────────
    print("Authenticating with YouTube...")
    youtube = get_authenticated_service()
    print("Authenticated.")
    if args.auth_only:
        print("Auth complete.")
        return

    dry_run = args.dry_run
    if dry_run:
        print("[DRY RUN — no writes will be made]\n")

    # Interpret escape sequences in text arguments
    def unescape(s):
        return s.encode("raw_unicode_escape").decode("unicode_escape") if s else s

    # ── mode B: single item ───────────────────────────────────────────────────
    if args.id:
        if not args.replace_desc and not args.append_desc:
            parser.error("--id requires --replace-desc or --append-desc")

        replace_desc = unescape(args.replace_desc)
        append_desc  = unescape(args.append_desc)
        operation    = "full_replace" if replace_desc else "append"
        text         = replace_desc if replace_desc else append_desc

        if args.item_type == "video":
            item = fetch_video(youtube, args.id)
            old_desc = item["description"]
            new_desc, changed, op_label = apply_operation(
                old_desc, operation, None, None, text, text
            )
            print(f"{'[DRY RUN] ' if dry_run else ''}VIDEO {args.id} — {item['title']}")
            print(f"  OLD: {old_desc[:200].replace(chr(10), '↵')}")
            print(f"  NEW: {new_desc[:200].replace(chr(10), '↵')}")
            if changed and not dry_run:
                update_video_description(youtube, args.id, new_desc, dry_run=False)
                write_log([{
                    "Timestamp": datetime.utcnow().isoformat(),
                    "Item Type": "video", "Item ID": args.id,
                    "Title": item["title"], "Operation": op_label,
                    "Old Description": old_desc, "New Description": new_desc,
                }])
        else:
            item = fetch_playlist(youtube, args.id)
            old_desc = item["description"]
            new_desc, changed, op_label = apply_operation(
                old_desc, operation, None, None, text, text
            )
            print(f"{'[DRY RUN] ' if dry_run else ''}PLAYLIST {args.id} — {item['title']}")
            print(f"  OLD: {old_desc[:200].replace(chr(10), '↵')}")
            print(f"  NEW: {new_desc[:200].replace(chr(10), '↵')}")
            if changed and not dry_run:
                update_playlist_description(youtube, args.id, new_desc, dry_run=False)
                write_log([{
                    "Timestamp": datetime.utcnow().isoformat(),
                    "Item Type": "playlist", "Item ID": args.id,
                    "Title": item["title"], "Operation": op_label,
                    "Old Description": old_desc, "New Description": new_desc,
                }])
        return

    # ── mode C: all videos in a playlist ─────────────────────────────────────
    if args.playlist_videos:
        if not args.replace_desc and not args.append_desc:
            parser.error("--playlist-videos requires --replace-desc or --append-desc")

        replace_desc = unescape(args.replace_desc)
        append_desc  = unescape(args.append_desc)
        operation    = "full_replace" if replace_desc else "append"
        text         = replace_desc if replace_desc else append_desc

        print(f"Fetching videos in playlist {args.playlist_videos}...")
        videos = fetch_videos_in_playlist(youtube, args.playlist_videos)
        print(f"Found {len(videos)} video(s).\n")

        updated = process_items(
            youtube, videos, "video", "video_id",
            operation, None, None, text, text,
            cap=len(videos),  # no cap for explicit playlist mode
            dry_run=dry_run,
        )
        print(f"\n{'[DRY RUN] ' if dry_run else ''}Updated {updated} video(s).")
        if not dry_run:
            print(f"Log written to: {LOG_TSV}")
        return

    # ── mode A: bulk ─────────────────────────────────────────────────────────
    if not args.search and not args.replace and not args.append:
        parser.print_help()
        return

    # Validate combinations
    if args.replace and args.append:
        parser.error("--replace and --append are mutually exclusive in bulk mode.")
    if args.replace and not args.search:
        parser.error("--replace requires --search.")

    search      = args.search
    replacement = unescape(args.replace)
    append_str  = unescape(args.append)
    operation   = "search_replace" if replacement else "search_append"

    title_filter_re = None
    if args.title_filter:
        try:
            title_filter_re = re.compile(args.title_filter, re.IGNORECASE)
        except re.error as e:
            parser.error(f"Invalid --title-filter regex: {e}")

    total_updated = 0

    if args.target in ("videos", "both"):
        if args.live:
            print("Fetching channel videos from API (live)...")
            videos = fetch_all_channel_videos(youtube, title_filter_re)
            source_note = " (after title filter)" if title_filter_re else ""
        else:
            print(f"Loading videos from {os.path.basename(VIDEOS_TSV)}...")
            videos = fetch_videos_from_tsv(title_filter_re)
            source_note = " (after title filter)" if title_filter_re else ""
        print(f"  {len(videos)} video(s) loaded{source_note}.\n")
        updated = process_items(
            youtube, videos, "video", "video_id",
            operation, search, replacement, append_str, None,
            cap=args.cap, dry_run=dry_run,
        )
        total_updated += updated

    if args.target in ("playlists", "both"):
        print("\nFetching channel playlists from API...")
        playlists = fetch_all_channel_playlists(youtube, title_filter_re)
        print(f"  {len(playlists)} playlist(s) loaded"
              f"{' (after title filter)' if title_filter_re else ''}.\n")
        updated = process_items(
            youtube, playlists, "playlist", "playlist_id",
            operation, search, replacement, append_str, None,
            cap=args.cap, dry_run=dry_run,
        )
        total_updated += updated

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Total updated: {total_updated}")
    if not dry_run and total_updated:
        print(f"Log written to: {LOG_TSV}")


if __name__ == "__main__":
    main()
