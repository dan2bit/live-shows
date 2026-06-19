#!/usr/bin/env python3
"""
validate_current.py

Validates live_shows_current.tsv on every push that touches it.

Checks (public, post-privacy-split schema — 19 columns):
  1. Column count — every row must have exactly 19 columns.
  2. Status values — every row must have status 'upcoming' or 'attended'.
  3. Flag columns — Seat Type must be 'GA' or 'Seated'; VIP and Group must be
     'Y' or blank. (These replace the old Private Notes sentinel, which moved to
     the live-shows-private sidecar, and catch a column-shift corruption well.)
  4. Sentinel values — upcoming rows must have:
       - Setlist.fm URL == '-' (or blank)
       - Playlist URL == '-' (or blank)

Exits non-zero on any violation so the GitHub Actions workflow fails visibly.
"""

import sys
from pathlib import Path

CURRENT_PATH = Path("live_shows_current.tsv")
EXPECTED_COLS = 19

# Column indices (0-based) — new public schema
COL_SEAT_TYPE = 9
COL_VIP = 10
COL_GROUP = 11
COL_SETLIST = 13
COL_STATUS = 14
COL_PLAYLIST = 16

VALID_STATUSES = {"upcoming", "attended"}
VALID_SEAT_TYPES = {"GA", "Seated"}
VALID_FLAGS = {"", "Y"}


def main() -> int:
    if not CURRENT_PATH.exists():
        print(f"ERROR: {CURRENT_PATH} not found", file=sys.stderr)
        return 1

    lines = CURRENT_PATH.read_text(encoding="utf-8").strip().splitlines()
    headers = lines[0].split("\t")

    if len(headers) != EXPECTED_COLS:
        print(f"ERROR: Header has {len(headers)} columns, expected {EXPECTED_COLS}")
        return 1

    errors = []

    for i, line in enumerate(lines[1:], start=2):
        cols = line.split("\t")
        row_id = cols[0] if cols else f"row {i}"

        # 1. Column count
        if len(cols) != EXPECTED_COLS:
            errors.append(
                f"Row {i} ({row_id}): {len(cols)} columns, expected {EXPECTED_COLS}"
            )
            continue  # Can't safely check other fields if cols are wrong

        status = cols[COL_STATUS].strip().lower()

        # 2. Status value
        if status not in VALID_STATUSES:
            errors.append(
                f"Row {i} ({row_id}): invalid status {cols[COL_STATUS]!r} "
                f"(expected 'upcoming' or 'attended')"
            )

        # 3. Flag columns
        seat = cols[COL_SEAT_TYPE].strip()
        if seat not in VALID_SEAT_TYPES:
            errors.append(
                f"Row {i} ({row_id}): invalid Seat Type {cols[COL_SEAT_TYPE]!r} "
                f"(expected 'GA' or 'Seated')"
            )
        if cols[COL_VIP].strip() not in VALID_FLAGS:
            errors.append(
                f"Row {i} ({row_id}): invalid VIP {cols[COL_VIP]!r} (expected 'Y' or blank)"
            )
        if cols[COL_GROUP].strip() not in VALID_FLAGS:
            errors.append(
                f"Row {i} ({row_id}): invalid Group {cols[COL_GROUP]!r} (expected 'Y' or blank)"
            )

        # 4. Sentinel checks for upcoming rows
        if status == "upcoming":
            setlist = cols[COL_SETLIST].strip()
            playlist = cols[COL_PLAYLIST].strip()

            if setlist and setlist != "-":
                errors.append(
                    f"Row {i} ({row_id}): upcoming row has non-sentinel Setlist URL: {setlist!r}"
                )
            if playlist and playlist != "-":
                errors.append(
                    f"Row {i} ({row_id}): upcoming row has non-sentinel Playlist URL: {playlist!r}"
                )

    if errors:
        print(f"{len(errors)} validation error(s) found in {CURRENT_PATH}:\n")
        for e in errors:
            print(f"  {e}")
        return 1

    attended = sum(1 for l in lines[1:] if l.split("\t")[COL_STATUS].strip().lower() == "attended")
    upcoming = sum(1 for l in lines[1:] if l.split("\t")[COL_STATUS].strip().lower() == "upcoming")
    print(f"OK — {len(lines)-1} rows validated ({attended} attended, {upcoming} upcoming).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
