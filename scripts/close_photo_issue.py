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

Exits:
    0  — row appended, or the photo was already present
    1  — error (title unparseable, file missing)
"""

import re
import sys
from datetime import date
from pathlib import Path

PHOTOS_PATH = Path("data/show_goals/artist-photos.tsv")

# Photo: [Artist] — [YYYY-MM-DD] ([Venue])   (em dash or hyphen as the separator)
TITLE_RE = re.compile(
    r"^Photo:\s*(?P<artist>.+?)\s*[—-]\s*(?P<date>\d{4}-\d{2}-\d{2})\s*\((?P<venue>.+)\)\s*$"
)
PHOTO_ID_RE = re.compile(r"/photo/([A-Za-z0-9_-]+)")


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
    return 0


if __name__ == "__main__":
    sys.exit(main())
