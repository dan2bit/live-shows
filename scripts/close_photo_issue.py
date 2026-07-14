#!/usr/bin/env python3
"""
close_photo_issue.py

Called by the photo-close GitHub Actions workflow
(.github/workflows/close-photo-issue.yml) when a `Photo:` issue receives a
comment containing a Google Photos share link.

Usage:
    python scripts/close_photo_issue.py <issue_title> <share_link>

Parses the artist, show date, and venue from the issue title
    Photo: [Artist] — [YYYY-MM-DD] ([Venue short name])
and appends one row to data/show_goals/artist-photos.tsv:
    Date <tab> Share Link <tab> Caption / Artist Info

The file's UTF-8 BOM header is preserved. Columns written:
    Date     "Mon D, YYYY" derived from the show date (to-the-day; the exact
             Google Photos capture timestamp is not available to the workflow)
    Caption  "[Artist] [(again)] @ [Venue] M/D/YY"  — "(again)" when the artist
             already appears somewhere in the file

Idempotent: if the share link's /photo/<ID> is already present, no change is made.

Album-needed check (#117): after appending, the artist's photographed-show count is
recomputed from the BUILT artist index (data/artist_modal_index.json — whose universe
includes seen_with-only names like Brandon Miller; never artists.tsv). If the artist
now has photos at 2+ distinct shows and no data/show_goals/artist-albums.tsv row, an
"album needed" reminder is printed and exported as the `album_note` step output for
the close comment. If a row exists, the reminder says to add the photo to the existing
album (the share link is stable — no repo change needed).

Exits:
    0  — row appended, or the photo was already present
    1  — error (title unparseable, file missing)
"""

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

from name_forms import goal_norm

PHOTOS_PATH = Path("data/show_goals/artist-photos.tsv")
ALBUMS_PATH = Path("data/show_goals/artist-albums.tsv")
INDEX_PATH = Path("data/artist_modal_index.json")

# Photo: [Artist] — [YYYY-MM-DD] ([Venue])   (em dash or hyphen as the separator)
TITLE_RE = re.compile(
    r"^Photo:\s*(?P<artist>.+?)\s*[—-]\s*(?P<date>\d{4}-\d{2}-\d{2})\s*\((?P<venue>.+)\)\s*$"
)
PHOTO_ID_RE = re.compile(r"/photo/([A-Za-z0-9_-]+)")


def load_albums():
    """goal_norm(Artist) -> Album URL from artist-albums.tsv. Album URL is deliberately
    NOT unique across rows (shared band albums are legitimate) — no uniqueness check."""
    out = {}
    if ALBUMS_PATH.exists():
        for ln in ALBUMS_PATH.read_text(encoding="utf-8").splitlines()[1:]:
            c = ln.split("\t")
            if len(c) >= 2 and c[0].strip() and c[1].strip():
                out[goal_norm(c[0])] = c[1].strip()
    return out


def find_index_record(arts, artist):
    """Look up an artist in the built index: canonical key first, then a display-name
    scan (covers alias-canonicalized keys). Joining the built index — not artists.tsv —
    is what keeps seen_with-only names (e.g. Brandon Miller, #121) resolvable."""
    key = goal_norm(artist)
    rec = arts.get(key)
    if rec is None:
        for v in arts.values():
            if goal_norm((v or {}).get("name") or "") == key:
                return v
    return rec


def album_check(artist, iso_date):
    """#117: return a reminder line, or None. Trigger is photos at 2+ DISTINCT shows
    (the badge's show_log[].photo_url count — not times_seen), with the just-logged
    show date unioned in since the index may predate this photo's row."""
    if not INDEX_PATH.exists():
        return None
    try:
        idx = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except ValueError:
        return None
    rec = find_index_record(idx.get("artists") or {}, artist)
    if rec is None:
        return None
    log = ((rec.get("seen") or {}).get("show_log")) or []
    photo_dates = {e.get("date") for e in log if e.get("photo_url") and e.get("date")}
    photo_dates.add(iso_date)
    url = load_albums().get(goal_norm(artist))
    if url:
        return f"ALBUM: add this photo to the existing Google Photos album for {artist}: {url}"
    if len(photo_dates) >= 2:
        return (f"ALBUM NEEDED: {artist} now has photos at {len(photo_dates)} shows and no "
                f"artist-albums.tsv row - create the Google Photos album and add the row to "
                f"data/show_goals/artist-albums.tsv.")
    return None


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <issue_title> <share_link>", file=sys.stderr)
        return 1

    title = sys.argv[1].strip()
    link = sys.argv[2].strip()

    m = TITLE_RE.match(title)
    if not m:
        print(f"ERROR: could not parse issue title: {title!r}", file=sys.stderr)
        return 1
    artist = m.group("artist").strip()
    iso = m.group("date")
    venue = m.group("venue").strip()

    if not PHOTOS_PATH.exists():
        print(f"ERROR: {PHOTOS_PATH} not found", file=sys.stderr)
        return 1

    # Read with utf-8 so the leading BOM stays as part of the content and is
    # written back verbatim; artist-photos.tsv is BOM-headed by design.
    raw = PHOTOS_PATH.read_text(encoding="utf-8")

    pid = PHOTO_ID_RE.search(link)
    if pid and pid.group(1) in raw:
        print("Photo already present (share-link id found in file); no change.")
        return 0

    y, mo, d = (int(x) for x in iso.split("-"))
    dt = date(y, mo, d)
    date_col = f"{dt.strftime('%b')} {d}, {y}"          # e.g. "May 9, 2026"
    mdy = f"{mo}/{d}/{str(y)[2:]}"                        # e.g. "5/9/26"
    again = " (again)" if artist in raw else ""
    caption = f"{artist}{again} @ {venue} {mdy}"
    row = f"{date_col}\t{link}\t{caption}"

    if not raw.endswith("\n"):
        raw += "\n"
    PHOTOS_PATH.write_text(raw + row + "\n", encoding="utf-8")
    print(f"Appended row: {row}")

    note = album_check(artist, iso)
    if note:
        print(note)
        gh_out = os.environ.get("GITHUB_OUTPUT")
        if gh_out:
            with open(gh_out, "a", encoding="utf-8") as fh:
                fh.write(f"album_note={note}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
