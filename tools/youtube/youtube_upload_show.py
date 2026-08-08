#!/usr/bin/env python3
"""
youtube_upload_show.py — Staged bootleg upload + song-ID for the @dan2bit channel

Drives a night's phone clips from a local folder to a titled, ordered, public
playlist. Four stages against one durable per-show manifest.

  --scan       Inspect the local files. No network, no OAuth, nothing uploaded.
               Writes the manifest: capture order, durations, set segments,
               fragment flags, position estimates. Song titles stay blank.

  --upload     Resumable videos.insert. Clips land PRIVATE and addressable.
               Records each video ID in the manifest as it goes.

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

WORKING OUT WHICH SHOW

  --show is optional. The clips already know the date, so for --scan the
  capture dates are collected and intersected with the attended shows in the
  show files. Exactly one match is used and announced; none or several stop
  with a report rather than a guess. A set running past midnight yields two
  candidate dates and still resolves, because only one of them is a show.

  For the later stages there are no clips to read, so the date comes from the
  manifests directory when exactly one manifest is present.

  --clips defaults to the working directory when it contains video files, and
  --upload remembers the scanned folder, so the path is typed once per show.

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

  # 1. Look before uploading anything. The date comes from the clips.
  python3 youtube_upload_show.py --clips ~/Downloads/pier6 --scan

  # 2. Upload once the scan looks right (dry run first).
  python3 youtube_upload_show.py --upload --dry-run
  python3 youtube_upload_show.py --upload

  # Interrupted? Run the same command again — it resumes where it stopped.
  # Feeling cautious? --limit 1 uploads a single clip and stops.

  # 3. After YouTube has finished scanning, seed the song IDs.
  python3 youtube_upload_show.py --identify

  # 4. Correct the manifest by hand, then write it back.
  python3 youtube_upload_show.py --apply --dry-run
  python3 youtube_upload_show.py --apply --publish

REQUIRES:
  ffprobe on PATH for exact durations (brew install ffmpeg). Degrades without it.
"""

import argparse
import glob
import json
import os
import random
import sys
import time
from datetime import datetime, timezone

import yt_clipscan
from yt_clipscan import human_duration
from yt_common import (
    DATA_DIR,
    REPO_ROOT,
    append_log,
    artist_handle,
    data_path,
    get_authenticated_service,
    read_tsv,
    script_path,
    slugify,
    venue_short,
    write_tsv,
)


# ── constants ──────────────────────────────────────────────────────────────

MANIFEST_DIR = script_path("manifests")

SHOWS_CURRENT_TSV = data_path("live_shows_current.tsv")
HISTORY_GLOB      = data_path("history", "*.tsv")

LOG_TSV    = os.path.join(REPO_ROOT, "logs", "upload_log.tsv")
LOG_FIELDS = ["Timestamp", "Show Date", "Clip", "Video ID", "Status",
              "Size MB", "Seconds", "Title"]

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

# Upload tuning. 8 MB chunks keep progress reporting useful on a phone-video
# sized file without paying a round trip per megabyte.
UPLOAD_CHUNK_BYTES  = 8 * 1024 * 1024
UPLOAD_MAX_RETRIES  = 6
RETRIABLE_STATUSES  = {500, 502, 503, 504}
CATEGORY_MUSIC      = "10"
UPLOAD_PRIVACY      = "private"


# ── show lookup ────────────────────────────────────────────────────────────

def _iter_show_rows():
    """Yield normalized show dicts from the current file, then the archives.

    The two files spell the same fields differently (Venue Name vs Venue,
    Supporting Artist vs Supporting Acts), so callers see one shape.
    """
    for row in read_tsv(SHOWS_CURRENT_TSV):
        date_str = row.get("Show Date", "").strip()
        if date_str:
            yield {
                "date":        date_str,
                "artist":      row.get("Artist", "").strip(),
                "venue":       row.get("Venue Name", "").strip(),
                "support":     row.get("Supporting Artist", "").strip(),
                "setlist_url": row.get("Setlist.fm URL", "").strip(),
                "status":      row.get("Status", "").strip(),
                "_source":     SHOWS_CURRENT_TSV,
            }

    for path in sorted(glob.glob(HISTORY_GLOB)):
        for row in read_tsv(path):
            date_str = row.get("Show Date", "").strip()
            if date_str:
                yield {
                    "date":        date_str,
                    "artist":      row.get("Artist", "").strip(),
                    "venue":       row.get("Venue", "").strip(),
                    "support":     row.get("Supporting Acts", "").strip(),
                    "setlist_url": row.get("Setlist.fm URL", "").strip(),
                    "status":      "attended",
                    "_source":     path,
                }


def shows_by_date() -> dict[str, dict]:
    """Every known show keyed by date. First hit wins, so current beats history."""
    index = {}
    for show in _iter_show_rows():
        index.setdefault(show["date"], show)
    return index


def load_show(date_str: str) -> dict:
    """Find one show by date, or stop with a report of where we looked."""
    show = shows_by_date().get(date_str)
    if show:
        return show

    sys.exit(
        f"No show found for {date_str}.\n"
        f"Looked in {os.path.relpath(SHOWS_CURRENT_TSV, DATA_DIR)} and "
        f"{os.path.relpath(HISTORY_GLOB, DATA_DIR)}.\n"
        "Check the date, or add the show row first."
    )


def infer_show_from_clips(clips: list) -> dict:
    """Resolve the show from the clips' own capture dates.

    The clips carry the answer already, so no filename or folder convention is
    required. Collect the local dates present and intersect them with known
    shows. A set running past midnight produces two candidate dates and still
    resolves cleanly, because only one of them is a show — which is why this
    matches against the show files rather than just picking the modal date.

    Ambiguity is reported, never guessed through.
    """
    dates = sorted({clip.capture_start.date().isoformat()
                    for clip in clips if clip.capture_start})
    if not dates:
        sys.exit("Could not read a capture date from any clip. Pass --show DATE.")

    index   = shows_by_date()
    matches = [d for d in dates if d in index]

    if len(matches) == 1:
        return index[matches[0]]

    span = ", ".join(dates)
    if not matches:
        sys.exit(
            f"No show matches the clips' capture date(s): {span}.\n"
            "Either the show row is missing, or these clips are from another "
            "night. Pass --show DATE to override."
        )

    sys.exit(
        f"The clips span more than one known show ({', '.join(matches)}).\n"
        "Pass --show DATE to say which one this folder is."
    )


def infer_date_from_manifests() -> str:
    """Resolve the show for a post-scan stage from the manifests directory."""
    paths = sorted(glob.glob(os.path.join(MANIFEST_DIR, "*.tsv")))
    if len(paths) == 1:
        return os.path.basename(paths[0])[:10]

    if not paths:
        sys.exit(
            "No manifest found. Run --scan first, or pass --show DATE.\n"
            f"Looked in {MANIFEST_DIR}"
        )

    names = "\n  ".join(os.path.basename(p) for p in paths)
    sys.exit(f"Several manifests exist — pass --show DATE to pick one:\n  {names}")


def support_acts(show: dict) -> list[str]:
    """Split the supporting-acts field into individual artist names."""
    raw = show.get("support", "")
    parts = [p.strip() for p in raw.replace("&", "/").split("/")]
    return [p for p in parts if p]


# ── manifest ───────────────────────────────────────────────────────────────

def manifest_path(show: dict) -> str:
    """Per-show manifest location, keyed on date and headliner."""
    return os.path.join(MANIFEST_DIR, f"{show['date']}-{slugify(show['artist'])}.tsv")


def sidecar_path(manifest: str) -> str:
    """Companion file recording how a manifest was scanned."""
    return manifest[:-4] + ".scan.json"


def write_sidecar(manifest: str, clip_dir: str) -> None:
    """Record the scanned folder so later stages need not be told again."""
    payload = {"clip_dir": os.path.abspath(clip_dir),
               "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    os.makedirs(os.path.dirname(manifest), exist_ok=True)
    with open(sidecar_path(manifest), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def read_sidecar(manifest: str) -> dict:
    """The recorded scan settings, or {} when absent or unreadable."""
    try:
        with open(sidecar_path(manifest), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


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


# ── titles and descriptions ────────────────────────────────────────────────

SONG_PLACEHOLDER = "#song-title"


def build_title(row: dict, show: dict) -> str:
    """Video title in the channel's one shape: ARTIST LIVE - SONG (bootleg).

    The segment's own artist is used rather than the headliner, so a support-set
    clip carries the opener's name — someone searching for the opener should
    find it.

    An unidentified clip keeps that same shape and fills the song slot with a
    numbered placeholder. Nothing structural changes between an identified and
    an unidentified clip, and the date stays out of the title: the channel puts
    the date and venue in the description, not the title.

    The placeholder is numbered so each clip's is unique and greppable. Bare
    placeholders have reached the public channel more than once, so --apply
    must refuse to publish a title that still contains one.
    """
    artist = (row.get("Set Artist") or "").strip() or show["artist"]
    song   = (row.get("Song") or "").strip()
    if not song:
        song = f"{SONG_PLACEHOLDER}-{row.get('Capture Order', '?')}"
    return f"{artist} LIVE - {song} (bootleg)"


def format_show_date(date_str: str) -> str:
    """YYYY-MM-DD to the MM/DD/YY the channel's descriptions use."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%m/%d/%y")
    except ValueError:
        return date_str


def build_description(row: dict, show: dict) -> str:
    """Description in the channel's convention: where, when, and who.

        from Wolf Trap (VA) on 07/18/26 @TromboneShorty
        Solomon Burke cover from Wolf Trap (VA) on 07/18/26 @TromboneShorty

    A cover note leads, matching how the channel already annotates covers —
    in the description rather than the title, where a parenthetical would
    compete with the (bootleg) suffix.

    Each piece degrades on its own: an unrecognized venue prints as written, a
    venue with no parseable state loses only the state, and an artist with no
    usable handle simply has no mention. The setlist link is deliberately
    absent — that belongs on the playlist description, not the video.
    """
    artist = (row.get("Set Artist") or "").strip() or show["artist"]
    venue  = venue_short(show.get("venue", ""))
    parts  = []

    cover = (row.get("Cover") or "").strip()
    if cover:
        parts.append(f"{cover} cover")

    parts.append(f"from {venue}" if venue else "from an unrecorded venue")
    parts.append(f"on {format_show_date(show['date'])}")

    handle = artist_handle(artist)
    if handle:
        parts.append(handle)

    return " ".join(parts)


# ── upload ─────────────────────────────────────────────────────────────────

def upload_clip(youtube, file_path: str, title: str, description: str,
                privacy: str = UPLOAD_PRIVACY) -> str:
    """Resumably upload one file and return its video ID.

    Chunked so a dropped connection costs one chunk rather than the whole file,
    with exponential backoff on the transient server errors the API is expected
    to emit under load. A non-retriable error is raised to the caller, which
    records the failure against that clip and moves on to the next.
    """
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(file_path, chunksize=UPLOAD_CHUNK_BYTES, resumable=True)
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title[:100],           # API rejects titles over 100 chars
                "description": description[:5000],
                "categoryId": CATEGORY_MUSIC,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            },
        },
        media_body=media,
    )

    response = None
    attempt  = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            attempt = 0
            if status:
                print(f"      {int(status.progress() * 100):3d}%", end="\r", flush=True)
        except HttpError as error:
            if getattr(error, "resp", None) is None or \
                    error.resp.status not in RETRIABLE_STATUSES:
                raise
            attempt += 1
            if attempt > UPLOAD_MAX_RETRIES:
                raise
            _backoff(attempt, f"HTTP {error.resp.status}")
        except (OSError, ConnectionError) as error:
            attempt += 1
            if attempt > UPLOAD_MAX_RETRIES:
                raise
            _backoff(attempt, type(error).__name__)

    return response["id"]


def _backoff(attempt: int, reason: str) -> None:
    """Sleep before a retry, with jitter so parallel retries do not sync up."""
    delay = min(2 ** attempt, 60) + random.random()
    print(f"      {reason} — retry {attempt}/{UPLOAD_MAX_RETRIES} in {delay:.0f}s")
    time.sleep(delay)


def pending_uploads(rows: list[dict]) -> list[dict]:
    """Rows still needing an upload: marked got, with no Video ID yet.

    This IS the work queue. Nothing else is tracked, which is what makes an
    interrupted run resume by simply being run again.
    """
    return [row for row in rows
            if (row.get("Decision") or "").strip() == "got"
            and not (row.get("Video ID") or "").strip()]


# ── stages ─────────────────────────────────────────────────────────────────

def resolve_clip_dir(args) -> str | None:
    """The folder of clips: explicit, else the working directory if it has video."""
    if args.clips:
        return os.path.expanduser(args.clips)
    cwd = os.getcwd()
    try:
        if yt_clipscan.list_clip_files(cwd):
            return cwd
    except NotADirectoryError:
        pass
    return None


def stage_scan(args) -> None:
    """Inspect local files and write the seeded manifest. Touches nothing remote."""
    clip_dir = resolve_clip_dir(args)
    if not clip_dir:
        sys.exit("No clips found. Pass --clips DIR, or run from the clip folder.")

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

    show = load_show(args.show) if args.show else infer_show_from_clips(clips)

    print(f"\n{'=' * 72}")
    print(f"{show['artist']} — {show['date']} — {show['venue'] or 'venue unknown'}")
    if show["support"]:
        print(f"support: {show['support']}")
    if not args.show:
        print(f"(resolved from {len(clips)} clips; pass --show to override)")
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
    write_sidecar(path, clip_dir)
    print(f"\nManifest written: {path}")

    if existing:
        print(f"  merged with {len(existing)} existing row(s); "
              "Song and other corrections preserved")

    if not show["setlist_url"]:
        print("  NOTE: no Setlist.fm URL on this show row. Song identification "
              "will fall back to the structural skeleton — ordering and "
              "fragment flags still work.")

    keepers = sum(1 for row in rows if row.get("Decision") == "got")
    print(f"\nNext: review the manifest, then upload {keepers} clip(s)")
    print(f"  python3 {os.path.basename(__file__)} --upload --dry-run")


def stage_upload(args, show: dict, youtube) -> None:
    """Upload every clip marked got that has no Video ID yet.

    The manifest is rewritten after EACH successful upload rather than once at
    the end. That is the whole resume story: a crash, a closed lid, or a
    deliberate stop leaves every completed clip recorded, so re-running the
    same command picks up exactly where it stopped.
    """
    path = args.manifest or manifest_path(show)
    rows = read_tsv(path)
    if not rows:
        sys.exit(f"No manifest at {path}. Run --scan first.")

    clip_dir = (resolve_clip_dir(args)
                or read_sidecar(path).get("clip_dir"))
    if not clip_dir or not os.path.isdir(clip_dir):
        sys.exit("Cannot find the clip folder. Pass --clips DIR.\n"
                 f"(the scan recorded: {read_sidecar(path).get('clip_dir', 'nothing')})")

    queue = pending_uploads(rows)
    done  = sum(1 for row in rows if (row.get("Video ID") or "").strip())
    total = sum(1 for row in rows if (row.get("Decision") or "").strip() == "got")

    print(f"\n{show['artist']} — {show['date']}")
    print(f"{done} of {total} already uploaded, {len(queue)} to go")

    if not queue:
        print("\nNothing to upload. Every clip marked got already has a Video ID.")
        return

    if args.limit:
        queue = queue[:args.limit]
        print(f"  --limit {args.limit}: uploading {len(queue)} this run")

    log_rows = []
    for index, row in enumerate(queue, start=1):
        file_path = os.path.join(clip_dir, row["Clip"])
        title     = build_title(row, show)

        print(f"\n  [{index}/{len(queue)}] {row['Clip']}  "
              f"({row.get('Size MB', '?')} MB, {row.get('Duration', '?')})")
        print(f"      {title}")

        if not os.path.exists(file_path):
            print(f"      SKIPPED: file not found at {file_path}")
            row["Upload Status"] = "failed:missing-file"
            _persist(path, rows, args.dry_run)
            continue

        if args.dry_run:
            print("      [DRY RUN] would upload as "
                  f"{UPLOAD_PRIVACY}, category {CATEGORY_MUSIC}")
            continue

        started = time.monotonic()
        try:
            video_id = upload_clip(youtube, file_path, title,
                                   build_description(row, show))
        except KeyboardInterrupt:
            print("\n      interrupted — progress so far is saved; "
                  "re-run to resume")
            _persist(path, rows, dry_run=False)
            sys.exit(1)
        except Exception as error:                      # noqa: BLE001
            print(f"      FAILED: {error}")
            row["Upload Status"] = "failed:upload"
            _persist(path, rows, dry_run=False)
            log_rows.append(_log_row(show, row, "", "failed", 0))
            continue

        elapsed = time.monotonic() - started
        row["Video ID"]      = video_id
        row["Upload Status"] = "uploaded"
        row["Title Set"]     = title

        # Persist immediately. Anything less and a crash on the next clip
        # loses the ID of this one, which is the only proof it was uploaded.
        _persist(path, rows, dry_run=False)

        print(f"      done in {elapsed:.0f}s — https://youtu.be/{video_id}")
        log_rows.append(_log_row(show, row, video_id, "uploaded", elapsed))

    if args.dry_run:
        print(f"\n[DRY RUN] {len(queue)} clip(s) would be uploaded. "
              "Nothing was written.")
        return

    append_log(LOG_TSV, LOG_FIELDS, log_rows)
    remaining = len(pending_uploads(rows))
    print(f"\nManifest updated: {path}")
    if remaining:
        print(f"  {remaining} clip(s) still pending — re-run to continue.")
    else:
        print("  All clips uploaded. Monetization and Submit Rating are next, "
              "in Studio.")
    print(f"  Log: {LOG_TSV}")


def _persist(path: str, rows: list[dict], dry_run: bool) -> None:
    """Write the manifest back unless this is a rehearsal."""
    if not dry_run:
        write_tsv(path, rows, MANIFEST_FIELDS)


def _log_row(show: dict, row: dict, video_id: str, status: str,
             seconds: float) -> dict:
    """One line of the append-only upload log."""
    return {
        "Timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "Show Date": show["date"],
        "Clip":      row["Clip"],
        "Video ID":  video_id,
        "Status":    status,
        "Size MB":   row.get("Size MB", ""),
        "Seconds":   f"{seconds:.0f}",
        "Title":     row.get("Title Set", ""),
    }


def stage_not_implemented(name: str) -> None:
    """Honest stop for a stage whose change has not landed yet."""
    sys.exit(
        f"--{name} is not implemented yet.\n"
        "--scan and --upload have landed. The remaining stages ship in their "
        "own changes so each can be reviewed on its own."
    )


# ── cli ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Staged bootleg upload and song identification for the @dan2bit channel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument("--show", metavar="DATE",
                        help="Show date (YYYY-MM-DD). Optional: --scan infers it "
                             "from the clips' capture dates, later stages from "
                             "the manifests directory.")

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
                        help="Folder of exported clips. Defaults to the working "
                             "directory when it contains video files; --upload "
                             "falls back to the folder --scan recorded.")
    parser.add_argument("--manifest", metavar="PATH",
                        help="Override the manifest location. Defaults to "
                             "manifests/DATE-artist-slug.tsv.")
    parser.add_argument("--limit", type=int, metavar="N",
                        help="Upload at most N clips this run. Use 1 for a "
                             "cautious first upload.")
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

    if args.scan:
        stage_scan(args)
        return

    show = load_show(args.show or infer_date_from_manifests())

    if args.upload:
        youtube = None if args.dry_run else get_authenticated_service()
        stage_upload(args, show, youtube)
    elif args.identify:
        stage_not_implemented("identify")
    elif args.apply:
        stage_not_implemented("apply")


if __name__ == "__main__":
    main()
