#!/usr/bin/env python3
"""
validate_current.py

Validates live_shows_current.tsv on every push that touches it.

Checks:
  1. Column count — every row must have exactly 26 columns.
  2. Sentinel values — upcoming rows must have:
       - Setlist.fm URL == '-'
       - Playlist URL == '-'
       - Private Notes not blank or empty
  3. Status values — every row must have status 'upcoming' or 'attended'.

Exits non-zero on any violation so the GitHub Actions workflow fails visibly.
"""

import sys
from pathlib import Path

CURRENT_PATH = Path("live_shows_current.tsv")
EXPECTED_COLS = 26

# Column indices (0-based)
COL_STATUS = 17
COL_SETLIST = 16
COL_PLAYLIST = 22
COL_PRIVATE = 24

VALID_STATUSES = {"upcoming", "attended"}


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

        # 3. Sentinel checks for upcoming rows
        if status == "upcoming":
            setlist = cols[COL_SETLIST].strip()
            playlist = cols[COL_PLAYLIST].strip()
            private = cols[COL_PRIVATE].strip()

            if setlist and setlist != "-":
                errors.append(
                    f"Row {i} ({row_id}): upcoming row has non-sentinel Setlist URL: {setlist!r}"
                )
            if playlist and playlist != "-":
                errors.append(
                    f"Row {i} ({row_id}): upcoming row has non-sentinel Playlist URL: {playlist!r}"
                )
            if not private:
                errors.append(
                    f"Row {i} ({row_id}): upcoming row has blank Private Notes "
                    f"(use '-' if nothing to note)"
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
