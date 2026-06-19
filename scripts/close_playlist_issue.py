#!/usr/bin/env python3
"""
close_playlist_issue.py

Called by the playlist-close GitHub Actions workflow when a Playlist: issue
is closed with a comment containing a YouTube playlist URL.

Usage:
    python scripts/close_playlist_issue.py <show_date> <playlist_url>

Arguments:
    show_date     ISO date string extracted from the issue title (YYYY-MM-DD)
    playlist_url  YouTube playlist URL from the closing comment

Finds the matching row in live_shows_current.tsv by Show Date and writes
the playlist URL to the Playlist URL column (col index 16, 0-based, in the
19-column public post-privacy-split schema).

Exits:
    0  — success (row found and updated, or URL already set to same value)
    1  — error (row not found, wrong column count, file missing, etc.)
"""

import sys
from pathlib import Path

CURRENT_PATH = Path("data/live_shows_current.tsv")
PLAYLIST_COL = 16  # 0-based
SHOW_DATE_COL = 3
EXPECTED_COLS = 19


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <show_date> <playlist_url>", file=sys.stderr)
        return 1

    show_date = sys.argv[1].strip()
    playlist_url = sys.argv[2].strip()

    if not CURRENT_PATH.exists():
        print(f"ERROR: {CURRENT_PATH} not found", file=sys.stderr)
        return 1

    lines = CURRENT_PATH.read_text(encoding="utf-8").splitlines()
    if not lines:
        print("ERROR: file is empty", file=sys.stderr)
        return 1

    header = lines[0]
    updated = False
    out_lines = [header]

    for i, line in enumerate(lines[1:], start=2):
        cols = line.split("\t")
        if len(cols) != EXPECTED_COLS:
            print(
                f"WARNING: row {i} has {len(cols)} columns (expected {EXPECTED_COLS}), skipping",
                file=sys.stderr,
            )
            out_lines.append(line)
            continue

        if cols[SHOW_DATE_COL].strip() == show_date:
            current_url = cols[PLAYLIST_COL].strip()
            if current_url and current_url not in ("-", ""):
                if current_url == playlist_url:
                    print(f"Row {i} ({show_date}): playlist URL already set to same value. No change.")
                    return 0
                else:
                    print(
                        f"WARNING: row {i} ({show_date}) already has playlist URL {current_url!r}. "
                        f"Overwriting with {playlist_url!r}."
                    )
            cols[PLAYLIST_COL] = playlist_url
            out_lines.append("\t".join(cols))
            updated = True
            print(f"Updated row {i} ({show_date}): playlist URL = {playlist_url}")
        else:
            out_lines.append(line)

    if not updated:
        print(
            f"ERROR: no row found with Show Date == {show_date!r} in {CURRENT_PATH}",
            file=sys.stderr,
        )
        return 1

    CURRENT_PATH.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
