#!/usr/bin/env python3
"""
reconcile_photos.py

Cross-checks the Photo URL values recorded on shows (live_shows_current.tsv and
data/history/*.tsv) against the Share Link values in
data/show_goals/artist-photos.tsv, matched on the Google Photos /photo/<ID>
segment. Reports only — never auto-fixes:

  MISSING  — a show carries a Photo URL whose /photo/<ID> is absent from
             artist-photos.tsv (the photo has no row yet; expected for a new
             show until its `photo` issue is processed)
  CORRUPT  — a show's Photo URL /photo/<ID> is a near-miss for an id that IS in
             artist-photos.tsv (within 2 edits). This is the transcription-typo
             case: one of the two URLs is almost certainly broken.

Standing album audit (#117):

  ALBUM GAP — an artist has photos at 2+ distinct shows (counted from the BUILT
             index data/artist_modal_index.json show_log[].photo_url — never
             times_seen, never artists.tsv, so seen_with-only names like Brandon
             Miller resolve) but no data/show_goals/artist-albums.tsv row. This
             is the backstop for the close_photo_issue.py reminder path; it
             catches backfilled / manually-added photos. Album URL uniqueness is
             deliberately NOT checked (shared band albums are legitimate).

Usage:
    python scripts/reconcile_photos.py [--strict]

Exit codes:
    0  — clean, or only MISSING / ALBUM GAP findings (informational)
    1  — one or more CORRUPT findings; or any finding when --strict is passed

Rationale for the split: CORRUPT is a real bug (a dead link on the live site),
so it fails the run by default. MISSING and ALBUM GAP are to-dos, not errors,
so they only fail under --strict.
"""

import json
import re
import sys
from pathlib import Path

from name_forms import goal_norm

CURRENT = Path("data/live_shows_current.tsv")
HISTORY_DIR = Path("data/history")
PHOTOS = Path("data/show_goals/artist-photos.tsv")
ALBUMS = Path("data/show_goals/artist-albums.tsv")
INDEX = Path("data/artist_modal_index.json")

PHOTO_ID_RE = re.compile(r"/photo/([A-Za-z0-9_-]+)")
DATE_HEADERS = ("Show Date", "Date")
ARTIST_HEADERS = ("Artist", "Headliner")


def photo_id(url):
    m = PHOTO_ID_RE.search(url or "")
    return m.group(1) if m else None


def within_edits(a, b, max_dist):
    """Bounded Levenshtein: True iff edit distance(a, b) <= max_dist."""
    if abs(len(a) - len(b)) > max_dist:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
        if min(prev) > max_dist:
            return False
    return prev[-1] <= max_dist


def _col(header, names, default=None):
    for n in names:
        if n in header:
            return header.index(n)
    return default


def load_show_photos():
    """Return list of (source, date, artist, pid) for every show-side Photo URL."""
    out = []
    files = []
    if CURRENT.exists():
        files.append(CURRENT)
    if HISTORY_DIR.is_dir():
        files.extend(sorted(HISTORY_DIR.glob("*.tsv")))

    for path in files:
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines:
            continue
        header = lines[0].split("\t")
        if "Photo URL" not in header:
            continue
        pi = header.index("Photo URL")
        di = _col(header, DATE_HEADERS, 0)
        ai = _col(header, ARTIST_HEADERS, 1)
        src = "current" if path == CURRENT else path.name
        for ln in lines[1:]:
            c = ln.split("\t")
            if len(c) <= pi:
                continue
            url = c[pi].strip()
            if not url or url == "-":
                continue
            pid = photo_id(url)
            date = c[di].strip() if di is not None and di < len(c) else ""
            artist = c[ai].strip() if ai is not None and ai < len(c) else ""
            out.append((src, date, artist, pid))
    return out


def load_file_ids():
    ids = set()
    if PHOTOS.exists():
        for ln in PHOTOS.read_text(encoding="utf-8").splitlines()[1:]:
            c = ln.split("\t")
            if len(c) > 1:
                pid = photo_id(c[1])
                if pid:
                    ids.add(pid)
    return ids


def load_album_keys():
    """goal_norm(Artist) keys present in artist-albums.tsv."""
    keys = set()
    if ALBUMS.exists():
        for ln in ALBUMS.read_text(encoding="utf-8").splitlines()[1:]:
            c = ln.split("\t")
            if len(c) >= 2 and c[0].strip() and c[1].strip():
                keys.add(goal_norm(c[0]))
    return keys


def album_gaps():
    """#117 backstop: [(display name, photographed-show count)] for artists with
    photos at 2+ distinct shows and no artist-albums.tsv row. None if the built
    index is absent (report skipped, not failed)."""
    if not INDEX.exists():
        return None
    try:
        idx = json.loads(INDEX.read_text(encoding="utf-8"))
    except ValueError:
        return None
    album_keys = load_album_keys()
    gaps = []
    for key, rec in (idx.get("artists") or {}).items():
        log = ((rec.get("seen") or {}).get("show_log")) or []
        dates = {e.get("date") for e in log if e.get("photo_url") and e.get("date")}
        if len(dates) < 2:
            continue
        name = rec.get("name") or key
        if key in album_keys or goal_norm(name) in album_keys:
            continue
        gaps.append((name, len(dates)))
    return sorted(gaps)


def main():
    strict = "--strict" in sys.argv[1:]
    file_ids = load_file_ids()
    shows = load_show_photos()

    missing, corrupt = [], []
    for src, date, artist, pid in shows:
        if pid is None or pid in file_ids:
            continue
        near = next((fid for fid in file_ids if within_edits(pid, fid, 2)), None)
        if near:
            corrupt.append((src, date, artist, pid, near))
        else:
            missing.append((src, date, artist, pid))

    if corrupt:
        print("CORRUPT — show Photo URL near-misses an artist-photos.tsv id (likely a typo in one):")
        for src, date, artist, pid, near in corrupt:
            print(f"  [{src}] {date} {artist}")
            print(f"      show id: {pid}")
            print(f"      file id: {near}")
    if missing:
        print("MISSING — show photo has no row in artist-photos.tsv yet:")
        for src, date, artist, pid in missing:
            print(f"  [{src}] {date} {artist}  ({pid})")
    if not corrupt and not missing:
        print("OK — every show Photo URL is present in artist-photos.tsv.")

    gaps = album_gaps()
    if gaps is None:
        print("ALBUM AUDIT skipped — data/artist_modal_index.json not found.")
        gaps = []
    elif gaps:
        print("ALBUM GAP — 2+ photographed shows but no artist-albums.tsv row (#117):")
        for name, cnt in gaps:
            print(f"  {name}  ({cnt} photographed shows)")
    else:
        print("OK — every 2+-photographed artist has an artist-albums.tsv row.")

    print(f"\nsummary: {len(corrupt)} corrupt, {len(missing)} missing, "
          f"{len(gaps)} album gaps, {len(shows)} show photos checked.")

    if corrupt or (strict and (missing or gaps)):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
