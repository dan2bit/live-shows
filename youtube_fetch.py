#!/usr/bin/env python3
"""
dan2bit YouTube channel metadata fetcher
Pulls all videos and playlists and outputs TSVs for correlation with show history.

Usage:
    python3 youtube_fetch.py [--since DATE|auto|full] [--force]

    --since auto   (default) Read the newest published date already in the TSV
                   files and only fetch items published after that date. Makes
                   re-runs very cheap — typically only a handful of new items.
                   Falls back to a full fetch if the TSVs are absent or empty.
    --since full   Fetch everything regardless of existing TSV content.
                   Use this to rebuild from scratch or after a long gap.
    --since DATE   Only fetch items published after DATE (YYYY-MM-DD).

    --force        Re-fetch and overwrite existing rows for any video published
                   within the --since window. Requires --since DATE (not auto
                   or full). Use this when video descriptions have been edited
                   after initial ingest and the changes haven't propagated to
                   the TSV yet.

                   Example — refresh descriptions for videos uploaded after
                   editing Ram's Head descriptions:
                       python3 youtube_fetch.py --since 2023-01-01 --force

                   Without --force, re-running with --since is safe and
                   idempotent — existing rows are never overwritten.

New rows are merged into existing TSV files (deduplicated by ID). Existing rows
are never deleted, so a partial quota-exhausted run is safe to resume.

Output files:
    youtube_videos.tsv    — all uploads with title, date, duration, URL
    youtube_playlists.tsv — all playlists with title, date, item count, URL

Credentials:
    Copy live-shows/.env.example to live-shows/.env and set YOUTUBE_API_KEY.
    See utils/HOWTO.md -> "YouTube API credentials" for setup instructions.
"""

import argparse
import csv
import os
import re
import sys
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
except ImportError:
    sys.exit(
        "Missing dependency: python-dotenv\n"
        "Run: pip install python-dotenv"
    )

try:
    from googleapiclient.discovery import build
except ImportError:
    sys.exit(
        "Missing dependency: google-api-python-client\n"
        "Run: pip install google-api-python-client"
    )

# Load .env from the same directory as this script
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
if not API_KEY or API_KEY == "your_api_key_here":
    sys.exit(
        "ERROR: YOUTUBE_API_KEY is not set.\n"
        "Copy live-shows/.env.example to live-shows/.env and fill in your API key.\n"
        "See utils/HOWTO.md -> \"YouTube API credentials\" for instructions."
    )

CHANNEL_HANDLE = "dan2bit"
SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
VIDEOS_TSV     = os.path.join(SCRIPT_DIR, "youtube_videos.tsv")
PLAYLISTS_TSV  = os.path.join(SCRIPT_DIR, "youtube_playlists.tsv")

VIDEO_FIELDS    = ["published", "title", "duration", "url", "description", "video_id"]
PLAYLIST_FIELDS = ["published", "title", "item_count", "url", "description", "playlist_id"]


# -- TSV helpers ---------------------------------------------------------------

def read_tsv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def write_tsv(rows: list[dict], fieldnames: list[str], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t",
                                lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows -> {path}")


def merge_rows(existing: list[dict], new_rows: list[dict], id_col: str,
               force_since: str | None = None) -> tuple[list[dict], int, int]:
    """
    Merge new_rows into existing, deduplicating by id_col.

    Normal behaviour (force_since=None): existing rows take precedence —
    new rows for the same ID are ignored. This keeps a partial
    quota-exhausted run resumable and makes re-runs idempotent.

    force_since (YYYY-MM-DD): existing rows whose 'published' date is on
    or after this date are replaced with the freshly fetched row. Use this
    after editing video descriptions so the updated text is picked up.
    Only rows actually present in new_rows can be overwritten; rows outside
    the fetch window are untouched.

    Returns (merged_list, added_count, overwritten_count).
    """
    force_cutoff = force_since  # YYYY-MM-DD string or None

    # Build a mutable index of existing rows keyed by ID
    index = {r[id_col]: r for r in existing}

    added = 0
    overwritten = 0

    for r in new_rows:
        vid_id = r[id_col]
        if vid_id not in index:
            index[vid_id] = r
            added += 1
        elif force_cutoff and r.get("published", "") >= force_cutoff:
            index[vid_id] = r
            overwritten += 1
        # else: keep existing row, skip new one

    merged = sorted(index.values(), key=lambda r: r.get("published", ""))
    return merged, added, overwritten


# -- Since-date logic ----------------------------------------------------------

def max_published(rows: list[dict]) -> str | None:
    """Return the newest 'published' date (YYYY-MM-DD) in a list of rows, or None."""
    dates = [r.get("published", "")[:10] for r in rows if r.get("published")]
    return max(dates) if dates else None


def resolve_cutoff(since_arg: str,
                   existing_videos: list[dict],
                   existing_playlists: list[dict]) -> str | None:
    """
    Return an RFC 3339 timestamp string to use as a publishedAfter cutoff,
    or None for a full fetch.

    since_arg:
      'full'      -> None (fetch everything)
      'auto'      -> newest date across both existing TSVs; None if both empty
      YYYY-MM-DD  -> use that date explicitly
    """
    if since_arg == "full":
        return None

    if since_arg == "auto":
        dates = []
        d = max_published(existing_videos)
        if d:
            dates.append(d)
        d = max_published(existing_playlists)
        if d:
            dates.append(d)
        if not dates:
            print("No existing TSV data — performing full fetch.")
            return None
        cutoff_date = max(dates)
        print(f"Auto-detected newest existing date: {cutoff_date}")
    else:
        cutoff_date = since_arg
        try:
            datetime.strptime(cutoff_date, "%Y-%m-%d")
        except ValueError:
            sys.exit(f"ERROR: --since value '{cutoff_date}' is not a valid YYYY-MM-DD date.")

    rfc3339 = f"{cutoff_date}T00:00:00Z"
    print(f"Fetching items published after: {cutoff_date}")
    return rfc3339


def is_after_cutoff(published_at: str, cutoff_rfc3339: str | None) -> bool:
    """True if the item's publishedAt is strictly after the cutoff, or if no cutoff."""
    if cutoff_rfc3339 is None:
        return True
    try:
        item_dt   = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        cutoff_dt = datetime.fromisoformat(cutoff_rfc3339.replace("Z", "+00:00"))
        return item_dt > cutoff_dt
    except Exception:
        return True  # if we can't parse, include it


# -- YouTube API ---------------------------------------------------------------

def get_channel_id(youtube):
    resp = youtube.channels().list(
        part="id,contentDetails",
        forHandle=CHANNEL_HANDLE
    ).execute()
    items = resp.get("items", [])
    if not items:
        sys.exit(f"Channel @{CHANNEL_HANDLE} not found.")
    channel = items[0]
    channel_id = channel["id"]
    uploads_playlist_id = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    print(f"Channel ID: {channel_id}")
    print(f"Uploads playlist ID: {uploads_playlist_id}")
    return channel_id, uploads_playlist_id


def fetch_new_videos(youtube, uploads_playlist_id: str,
                     cutoff: str | None) -> list[dict]:
    """
    Fetch videos from the uploads playlist newer than cutoff.

    Two-pass approach:
      Pass 1 — collect video IDs, titles, and published dates from
               playlistItems. Note: playlistItems snippets return the
               playlist-level description (always blank), NOT the video's
               own description — so we do NOT read description here.
      Pass 2 — batch-fetch real descriptions and durations via videos().list()
               in groups of 50.

    The uploads playlist is returned newest-first, so we stop paginating as
    soon as we hit an item older than the cutoff — no need to scan everything.
    Without a cutoff (full fetch), all pages are retrieved.
    """
    # Pass 1: collect IDs / titles / dates from playlistItems
    candidates = []
    page_token = None
    done = False

    while not done:
        resp = youtube.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=uploads_playlist_id,
            maxResults=50,
            pageToken=page_token,
        ).execute()

        for item in resp.get("items", []):
            snippet  = item["snippet"]
            video_id = item["contentDetails"]["videoId"]
            pub      = snippet.get("publishedAt", "")

            if not is_after_cutoff(pub, cutoff):
                # Playlist is newest-first; everything from here is older
                done = True
                break

            candidates.append({
                "video_id":  video_id,
                "title":     snippet.get("title", ""),
                "published": pub[:10],
                "url":       f"https://www.youtube.com/watch?v={video_id}",
            })

        page_token = resp.get("nextPageToken")
        if not page_token:
            break
        if not done:
            print(f"  Fetched {len(candidates)} new videos so far...")

    if not candidates:
        return []

    # Pass 2: batch-fetch real descriptions and durations via videos().list()
    videos = []
    for i in range(0, len(candidates), 50):
        batch = candidates[i:i + 50]
        ids   = ",".join(v["video_id"] for v in batch)
        resp  = youtube.videos().list(
            part="snippet,contentDetails",
            id=ids,
        ).execute()
        detail_map = {
            item["id"]: item for item in resp.get("items", [])
        }
        for v in batch:
            detail  = detail_map.get(v["video_id"], {})
            snippet = detail.get("snippet", {})
            content = detail.get("contentDetails", {})
            videos.append({
                "video_id":    v["video_id"],
                "title":       v["title"],
                "published":   v["published"],
                "url":         v["url"],
                "description": snippet.get("description", "").replace("\n", " ")[:200],
                "duration":    parse_duration(content.get("duration", "")),
            })

    return videos


def parse_duration(iso_duration: str) -> str:
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration)
    if not match:
        return ""
    h = int(match.group(1) or 0)
    m = int(match.group(2) or 0)
    s = int(match.group(3) or 0)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fetch_new_playlists(youtube, channel_id: str,
                        cutoff: str | None) -> list[dict]:
    """
    Fetch playlists for the channel newer than cutoff.

    Unlike the uploads playlist, the playlists endpoint is not guaranteed to
    return results newest-first, so we filter every item individually rather
    than stopping early.
    """
    playlists = []
    page_token = None

    while True:
        resp = youtube.playlists().list(
            part="snippet,contentDetails",
            channelId=channel_id,
            maxResults=50,
            pageToken=page_token,
        ).execute()

        for item in resp.get("items", []):
            snippet     = item["snippet"]
            pub         = snippet.get("publishedAt", "")
            playlist_id = item["id"]

            if not is_after_cutoff(pub, cutoff):
                continue

            playlists.append({
                "playlist_id": playlist_id,
                "title":       snippet.get("title", ""),
                "published":   pub[:10],
                "description": snippet.get("description", "").replace("\n", " ")[:200],
                "item_count":  item["contentDetails"]["itemCount"],
                "url":         f"https://www.youtube.com/playlist?list={playlist_id}",
            })

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return playlists


# -- Main ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--since",
        metavar="DATE|auto|full",
        default="auto",
        help=(
            "Fetch only items published after this date. "
            "'auto' (default) reads the newest date from existing TSVs. "
            "'full' fetches everything. "
            "YYYY-MM-DD uses an explicit cutoff date."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Overwrite existing TSV rows for videos published within the "
            "--since window. Requires --since DATE (not auto or full). "
            "Use after editing video descriptions to pick up the changes."
        ),
    )
    args = parser.parse_args()

    # --force requires an explicit date, not auto/full
    if args.force:
        if args.since in ("auto", "full"):
            sys.exit(
                "ERROR: --force requires an explicit --since DATE (YYYY-MM-DD).\n"
                "Example: python3 youtube_fetch.py --since 2023-01-01 --force"
            )
        force_since = args.since
        print(f"--force enabled: existing rows published on or after {force_since} will be overwritten.")
    else:
        force_since = None

    youtube = build("youtube", "v3", developerKey=API_KEY)

    # Load existing TSV data (used both for cutoff detection and merging)
    existing_videos    = read_tsv(VIDEOS_TSV)
    existing_playlists = read_tsv(PLAYLISTS_TSV)
    print(f"Existing data: {len(existing_videos)} videos, "
          f"{len(existing_playlists)} playlists in TSVs")

    cutoff = resolve_cutoff(args.since, existing_videos, existing_playlists)

    print("\nFetching channel info...")
    channel_id, uploads_playlist_id = get_channel_id(youtube)

    # -- Videos ----------------------------------------------------------------
    print("\nFetching new videos...")
    new_videos = fetch_new_videos(youtube, uploads_playlist_id, cutoff)
    print(f"Found {len(new_videos)} video(s) in fetch window.")

    if new_videos:
        merged_videos, added, overwritten = merge_rows(
            existing_videos, new_videos, "video_id", force_since=force_since
        )
        msg = f"Merged: {added} new video(s) added"
        if overwritten:
            msg += f", {overwritten} existing row(s) overwritten"
        msg += f" ({len(merged_videos)} total)."
        print(msg)
        write_tsv(merged_videos, VIDEO_FIELDS, VIDEOS_TSV)
    else:
        print("No videos in fetch window — youtube_videos.tsv unchanged.")

    # -- Playlists -------------------------------------------------------------
    print("\nFetching new playlists...")
    new_playlists = fetch_new_playlists(youtube, channel_id, cutoff)
    print(f"Found {len(new_playlists)} playlist(s) in fetch window.")

    if new_playlists:
        merged_playlists, added, overwritten = merge_rows(
            existing_playlists, new_playlists, "playlist_id", force_since=force_since
        )
        msg = f"Merged: {added} new playlist(s) added"
        if overwritten:
            msg += f", {overwritten} existing row(s) overwritten"
        msg += f" ({len(merged_playlists)} total)."
        print(msg)
        write_tsv(merged_playlists, PLAYLIST_FIELDS, PLAYLISTS_TSV)
    else:
        print("No playlists in fetch window — youtube_playlists.tsv unchanged.")

    print("\nDone! Next step: run youtube_correlate.py --merge to update show history.")


if __name__ == "__main__":
    main()
