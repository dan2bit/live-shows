#!/usr/bin/env python3
"""
youtube_upload_show.py — Staged bootleg upload + song-ID for the @dan2bit channel

Drives a night's phone clips from a local folder to a titled, ordered, public
playlist. Four stages against one durable per-show manifest.

  --scan       Inspect the local files. No network, no OAuth, nothing uploaded.
               Writes the manifest: capture order, durations, set segments,
               fragment flags, position estimates. Song titles stay blank.

  --upload     Resumable videos.insert. Clips land PRIVATE and addressable.
               Records each video ID in the manifest.

  --identify   Seed song titles: Content-ID locks, setlist bracketing, lyric
               hints, confidence scores. No writes to YouTube.

  --apply      Write the corrected titles and descriptions. With --publish,
               flip privacy to public.

WHY STAGES AND NOT ONE PASS

  Two unbounded waits sit inside this workflow. YouTube's Content ID scan
  finishes minutes to hours after upload, and the correction pass is human.
  A single run cannot straddle either. The manifest is what survives between
  them, and it doubles as the upload ledger: a blank Video ID is the only work
  queue, so an interrupted upload, or one deliberately split across days,
  resumes for free.

WHAT THIS DOES NOT DO

  Playlist assembly stays with youtube_create_playlists.py, which already
  creates, populates, orders and describes. Once these videos carry exact
  setlist titles, its setlist matching becomes near-exact. Hand off with:

      python3 youtube_fetch.py
      python3 youtube_create_playlists.py --new-show YYYY-MM-DD --update-history

  Monetization and Submit Rating remain manual in Studio. There is no API
  surface for either.

THE MANIFEST IS YOURS

  Every seeded value is a starting point, not a verdict. --scan and --identify
  refresh only the columns they own and never overwrite a Song you have typed
  or a Decision you have changed. Pass --reseed to deliberately discard seeds
  and start the automated columns over.

USAGE:

  # 1. Look before uploading anything.
  python3 youtube_upload_show.py --show 2026-08-04 --clips ~/Downloads/pier6 --scan

  # 2. Upload once the scan looks right (dry run first).
  python3 youtube_upload_show.py --show 2026-08-04 --upload --dry-run
  python3 youtube_upload_show.py --show 2026-08-04 --upload

  # 3. After YouTube has finished scanning, seed the song IDs.
  python3 youtube_upload_show.py --show 2026-08-04 --identify

  # 4. Correct the manifest by hand, then write it back.
  python3 youtube_upload_show.py --show 2026-08-04 --apply --dry-run
  python3 youtube_upload_show.py --show 2026-08-04 --apply --publish

REQUIRES:
  ffprobe on PATH for exact durations (brew install ffmpeg). Degrades without it.
"""

import argparse
import glob
import os
import sys

import yt_clipscan
from yt_clipscan import human_duration
from yt_common import (
    DATA_DIR,
    data_path,
    read_tsv,
    script_path,
    slugify,
    write_tsv,
)


# ── constants ──────────────────────────────────────────────────────────────

MANIFEST_DIR = script_path("manifests")

SHOWS_CURRENT_TSV = data_path("live_shows_current.tsv")
HISTORY_GLOB      = data_path("history", "*.tsv")

MANIFEST_FIELDS = [
    "Clip", "Capture Order", "Capture Start", "Duration", "Size MB", "Integrity",
    "Set", "Set Artist",
    "Decision", "Skip Reason",
    "Song", "Confidence", "Evidence", "Candidates", "Lyric Hint",
    "Setlist Pos", "Cover",
    "Video ID", "Upload Status", "Title Set",
]

# Columns --scan recomputes on every run. Everything else is preserved.
SCAN_OWNED = {"Clip", "Capture Order", "Capture Start", "Duration",
              "Size MB", "Integrity", "Set"}

# Columns seeded once, then left alone unless --reseed.
SEEDED_ONCE = {"Set Artist", "Decision", "Skip Reason"}


# ── show lookup ────────────────────────────────────────────────────────────

def load_show(date_str: str) -> dict:
    """Find a show by date in live_shows_current.tsv, then the history archives.

    Normalizes the two column spellings so callers see one shape:
    Artist, Venue, Supporting Acts, Setlist.fm URL.
    """
    for row in read_tsv(SHOWS_CURRENT_TSV):
        if row.get("Show Date", "").strip() == date_str:
            return {
                "date":       date_str,
                "artist":     row.get("Artist", "").strip(),
                "venue":      row.get("Venue Name", "").strip(),
                "support":    row.get("Supporting Artist", "").strip(),
                "setlist_url": row.get("Setlist.fm URL", "").strip(),
                "_source":    SHOWS_CURRENT_TSV,
            }

    for path in sorted(glob.glob(HISTORY_GLOB)):
        for row in read_tsv(path):
            if row.get("Show Date", "").strip() == date_str:
                return {
                    "date":       date_str,
                    "artist":     row.get("Artist", "").strip(),
                    "venue":      row.get("Venue", "").strip(),
                    "support":    row.get("Supporting Acts", "").strip(),
                    "setlist_url": row.get("Setlist.fm URL", "").strip(),
                    "_source":    path,
                }

    sys.exit(
        f"No show found for {date_str}.\n"
        f"Looked in {os.path.relpath(SHOWS_CURRENT_TSV, DATA_DIR)} and "
        f"{os.path.relpath(HISTORY_GLOB, DATA_DIR)}.\n"
        "Check the date, or add the show row first."
    )


def support_acts(show: dict) -> list[str]:
    """Split the supporting-acts field into individual artist names."""
    raw = show.get("support", "")
    parts = [p.strip() for p in raw.replace("&", "/").split("/")]
    return [p for p in parts if p]


# ── manifest ───────────────────────────────────────────────────────────────

def manifest_path(show: dict) -> str:
    """Per-show manifest location, keyed on date and headliner."""
    return os.path.join(MANIFEST_DIR, f"{show['date']}-{slugify(show['artist'])}.tsv")


def read_manifest(path: str) -> dict[str, dict]:
    """Existing manifest rows keyed by clip filename. Missing file returns {}."""
    return {row["Clip"]: row for row in read_tsv(path) if row.get("Clip")}


def blank_row() -> dict:
    """An empty manifest row with every column present."""
    return {field: "" for field in MANIFEST_FIELDS}


def seed_set_artist(clip, show: dict, segment_count: int) -> str:
    """Propose which artist played the segment this clip belongs to.

    On a night with support, the first segment is usually the opener and the
    rest are the headliner. That is a proposal, not a finding — a headliner
    playing an acoustic set and then a full-band set also produces two
    segments, with the same artist in both. Correct it in the manifest.
    """
    openers = support_acts(show)
    if openers and segment_count > 1 and clip.segment == 1:
        return openers[0]
    return show["artist"]


def seed_rows(clips: list, show: dict, existing: dict[str, dict],
              reseed: bool = False) -> list[dict]:
    """Merge a fresh scan into the manifest, preserving human-owned columns.

    Scan-owned columns are always refreshed. Seeded-once columns are filled
    only for clips the manifest has not seen before, unless --reseed. Every
    other column — Song above all — is carried through untouched.
    """
    segment_count = len({c.segment for c in clips})
    rows = []

    for clip in clips:
        previous = existing.get(clip.name)
        row = blank_row()

        if previous:
            row.update({k: v for k, v in previous.items() if k in MANIFEST_FIELDS})

        row["Clip"]          = clip.name
        row["Capture Order"] = str(clip.capture_order)
        row["Capture Start"] = (clip.capture_start.strftime("%Y-%m-%d %H:%M:%S")
                                if clip.capture_start else "")
        row["Duration"]      = human_duration(clip.duration_s)
        row["Size MB"]       = f"{clip.size_mb:.0f}"
        row["Integrity"]     = clip.integrity
        row["Set"]           = f"seg{clip.segment}"

        if previous is None or reseed:
            row["Set Artist"]  = seed_set_artist(clip, show, segment_count)
            row["Decision"]    = "skip" if clip.is_fragment else "got"
            row["Skip Reason"] = clip.skip_reason
            row["Upload Status"] = row["Upload Status"] or "pending"

        rows.append(row)

    return rows


def carry_orphans(clips: list, existing: dict[str, dict]) -> list[dict]:
    """Manifest rows whose clip file is no longer in the directory.

    These are retained, never dropped. A row can hold a Video ID — the only
    record that a clip was already uploaded — and a Song typed by hand. If the
    local file is renamed, moved, or cleared out after upload, dropping its row
    would silently lose both and break upload resume. Retaining costs a stale
    line the person can delete; dropping costs a re-upload and a re-decode.
    """
    present = {c.name for c in clips}
    return [row for name, row in sorted(existing.items()) if name not in present]


# ── stages ─────────────────────────────────────────────────────────────────

def stage_scan(args, show: dict) -> None:
    """Inspect local files and write the seeded manifest. Touches nothing remote."""
    if not args.clips:
        sys.exit("--scan requires --clips DIR (the folder of exported clips).")

    clip_dir = os.path.expanduser(args.clips)
    if not yt_clipscan.ffprobe_available():
        print("  WARNING: ffprobe not found on PATH — durations will use the "
              "file-size proxy (+/-10-30%) and the untrimmed-original check "
              "cannot run. Install with: brew install ffmpeg")

    clips = yt_clipscan.scan_dir(
        clip_dir,
        timezone_name=args.timezone,
        fragment_seconds=args.fragment_seconds,
        min_gap_minutes=args.min_gap_minutes,
        outlier_factor=args.outlier_factor,
        avg_song_seconds=args.avg_song_seconds,
    )
    if not clips:
        sys.exit(f"No video files found in {clip_dir}")

    print(f"\n{'=' * 72}")
    print(f"{show['artist']} — {show['date']} — {show['venue'] or 'venue unknown'}")
    if show["support"]:
        print(f"support: {show['support']}")
    print(f"{'=' * 72}\n")
    print(yt_clipscan.summarize(clips))

    path     = args.manifest or manifest_path(show)
    existing = read_manifest(path)
    rows     = seed_rows(clips, show, existing, reseed=args.reseed)

    orphans = carry_orphans(clips, existing)
    if orphans:
        rows.extend(orphans)
        uploaded = sum(1 for row in orphans if row.get("Video ID"))
        print(f"\n  WARNING: {len(orphans)} manifest row(s) have no matching file "
              f"in {clip_dir}.\n  They were kept, not dropped"
              + (f" — {uploaded} already carry a Video ID." if uploaded else ".")
              + "\n  Names: " + ", ".join(row["Clip"] for row in orphans))

    if args.dry_run:
        print(f"\n[DRY RUN] would write {len(rows)} rows to {path}")
        return

    write_tsv(path, rows, MANIFEST_FIELDS)
    print(f"\nManifest written: {path}")

    if existing:
        print(f"  merged with {len(existing)} existing row(s); "
              "Song and other corrections preserved")

    if not show["setlist_url"]:
        print("  NOTE: no Setlist.fm URL on this show row. Song identification "
              "will fall back to the structural skeleton — ordering and "
              "fragment flags still work.")

    print("\nNext: review the manifest, then")
    print(f"  python3 {os.path.basename(__file__)} --show {show['date']} --upload --dry-run")


def stage_not_implemented(name: str) -> None:
    """Honest stop for a stage whose PR has not landed yet."""
    sys.exit(
        f"--{name} is not implemented yet.\n"
        "Only --scan has landed. The remaining stages ship in their own "
        "changes so the upload path can be reviewed on its own."
    )


# ── cli ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Staged bootleg upload and song identification for the @dan2bit channel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument("--show", metavar="DATE", required=True,
                        help="Show date (YYYY-MM-DD). Looked up in "
                             "live_shows_current.tsv, then history/*.tsv.")

    stage = parser.add_mutually_exclusive_group(required=True)
    stage.add_argument("--scan", action="store_true",
                       help="Inspect local clips and write the manifest. "
                            "No network, no OAuth, nothing uploaded.")
    stage.add_argument("--upload", action="store_true",
                       help="Resumable upload of every clip marked got. "
                            "Videos land private.")
    stage.add_argument("--identify", action="store_true",
                       help="Seed song titles from Content ID, setlist and lyrics.")
    stage.add_argument("--apply", action="store_true",
                       help="Write corrected titles and descriptions to YouTube.")

    parser.add_argument("--clips", metavar="DIR",
                        help="Folder of exported clips. Required for --scan.")
    parser.add_argument("--manifest", metavar="PATH",
                        help="Override the manifest location. Defaults to "
                             "manifests/DATE-artist-slug.tsv.")
    parser.add_argument("--publish", action="store_true",
                        help="With --apply, flip privacy from private to public.")
    parser.add_argument("--reseed", action="store_true",
                        help="Discard seeded Decision/Set Artist values and "
                             "recompute them. Typed Song values are still kept.")

    tuning = parser.add_argument_group("Scan tuning")
    tuning.add_argument("--timezone", metavar="TZ",
                        default=yt_clipscan.DEFAULT_TIMEZONE,
                        help=f"Local timezone of the show. Default: "
                             f"{yt_clipscan.DEFAULT_TIMEZONE}.")
    tuning.add_argument("--fragment-seconds", type=float,
                        default=yt_clipscan.DEFAULT_FRAGMENT_SECS,
                        help=f"Clips at or under this length are pre-flagged as "
                             f"skip candidates. Default: "
                             f"{yt_clipscan.DEFAULT_FRAGMENT_SECS:.0f}.")
    tuning.add_argument("--min-gap-minutes", type=float,
                        default=yt_clipscan.DEFAULT_MIN_GAP_MINS,
                        help=f"Absolute floor for a dark gap to open a new "
                             f"segment. Default: "
                             f"{yt_clipscan.DEFAULT_MIN_GAP_MINS:.0f}.")
    tuning.add_argument("--outlier-factor", type=float,
                        default=yt_clipscan.DEFAULT_OUTLIER_FACTOR,
                        help=f"A gap must also exceed this multiple of the "
                             f"night's median gap. Default: "
                             f"{yt_clipscan.DEFAULT_OUTLIER_FACTOR}.")
    tuning.add_argument("--avg-song-seconds", type=float,
                        default=yt_clipscan.DEFAULT_AVG_SONG_SECS,
                        help=f"Average song length used for position estimates "
                             f"only. Default: "
                             f"{yt_clipscan.DEFAULT_AVG_SONG_SECS:.0f}.")

    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without writing anything.")

    args = parser.parse_args()
    show = load_show(args.show)

    if args.scan:
        stage_scan(args, show)
    elif args.upload:
        stage_not_implemented("upload")
    elif args.identify:
        stage_not_implemented("identify")
    elif args.apply:
        stage_not_implemented("apply")


if __name__ == "__main__":
    main()
