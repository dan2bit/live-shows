#!/usr/bin/env python3
"""
close_playlist_issue.py

Called by the playlist-close GitHub Actions workflow when a Playlist: issue
is closed with a comment containing a YouTube playlist URL.

Usage:
    python scripts/close_playlist_issue.py <show_date> <playlist_url> [artist]

Arguments:
    show_date     ISO date string extracted from the issue title (YYYY-MM-DD)
    playlist_url  YouTube playlist URL from the closing comment
    artist        Optional headliner, also from the issue title. Required when
                  more than one show shares the date.

Finds the matching row in live_shows_current.tsv and writes the playlist URL
to the Playlist URL column (col index 16, 0-based, in the 19-column public
post-privacy-split schema).

WHY ARTIST EXISTS

Show Date is not unique - 2026-11-21 currently carries both Fruition at Pearl
Street Warehouse and They Might Be Giants at 9:30 Club, and data/history/2024.tsv
has two shows on 2024-02-24 with different playlists.

Matching on date alone did not pick the wrong row; it wrote the URL to EVERY row
sharing the date, and exited 0. Closing the second issue then overwrote both
again, leaving two shows pointing at one playlist and the other playlist
recorded nowhere. Nothing reported an error in either direction.

So a date that matches several rows is now an error rather than a guess. A
wrong playlist on the wrong show is worse than a failed workflow run that says
why.

Artist is matched through scripts/name_forms.py and data/recommend_aliases.tsv
rather than by string equality. name_forms alone handles "Robert Cray" against a
row filed as "Robert Cray Band"; the alias table handles the billing-name folds
it cannot derive, such as an issue titled "John Primer" against the row
"John Primer & The Real Deal Blues Band". Playlist issue titles carry the
headliner, so that difference is the normal case, not an edge case. Inventing a
second identity rule here is how these drift apart.

Exits:
    0  - success (row found and updated, or URL already set to same value)
    1  - error (no row, ambiguous date, wrong column count, file missing, etc.)
"""

import sys
from pathlib import Path

from name_forms import norm, surface_forms

CURRENT_PATH = Path("data/live_shows_current.tsv")
ALIASES_PATH = Path("data/recommend_aliases.tsv")
PLAYLIST_COL = 16  # 0-based
SHOW_DATE_COL = 3
ARTIST_COL = 1
EXPECTED_COLS = 19


def _base_keys(name):
    return {k for k in (norm(f) for f in surface_forms(name or "")) if k}


def _alias_pairs():
    """(alias_keys, canonical_keys) from recommend_aliases.tsv. Absent file is fine."""
    if not ALIASES_PATH.exists():
        return []
    pairs = []
    for raw in ALIASES_PATH.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) < 2:
            continue
        alias, canon = parts[0].strip(), parts[1].strip()
        if alias.lower() == "alias" or not alias or not canon:
            continue
        pairs.append((_base_keys(alias), _base_keys(canon)))
    return pairs


def identity_keys(name, pairs=None):
    """Every normalized form one artist name can legitimately be spelled under.

    Expanded across the alias table in both directions, so the match works
    whichever side of an alias row the issue title happens to use.
    """
    keys = _base_keys(name)
    if not keys:
        return keys
    for alias_keys, canon_keys in (pairs if pairs is not None else _alias_pairs()):
        if keys & alias_keys:
            keys = keys | canon_keys
        elif keys & canon_keys:
            keys = keys | alias_keys
    return keys


def main() -> int:
    if len(sys.argv) not in (3, 4):
        print(
            f"Usage: {sys.argv[0]} <show_date> <playlist_url> [artist]",
            file=sys.stderr,
        )
        return 1

    show_date = sys.argv[1].strip()
    playlist_url = sys.argv[2].strip()
    artist = sys.argv[3].strip() if len(sys.argv) == 4 else ""

    if not CURRENT_PATH.exists():
        print(f"ERROR: {CURRENT_PATH} not found", file=sys.stderr)
        return 1

    lines = CURRENT_PATH.read_text(encoding="utf-8").splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        print("ERROR: file is empty", file=sys.stderr)
        return 1

    # Pass 1 - identify the target row. Nothing is written until exactly one
    # row is known to be the right one.
    candidates = []  # (line_index, artist_name)
    for i, line in enumerate(lines[1:], start=2):
        cols = line.split("\t")
        if len(cols) != EXPECTED_COLS:
            print(
                f"WARNING: row {i} has {len(cols)} columns (expected {EXPECTED_COLS}), skipping",
                file=sys.stderr,
            )
            continue
        if cols[SHOW_DATE_COL].strip() == show_date:
            candidates.append((i, cols[ARTIST_COL].strip()))

    if not candidates:
        print(
            f"ERROR: no row found with Show Date == {show_date!r} in {CURRENT_PATH}",
            file=sys.stderr,
        )
        return 1

    if len(candidates) > 1:
        if not artist:
            print(
                f"ERROR: {len(candidates)} rows share Show Date {show_date!r} and no "
                f"artist was supplied. Pass the headliner as a third argument.",
                file=sys.stderr,
            )
            for i, name in candidates:
                print(f"  row {i}: {name}", file=sys.stderr)
            return 1

        pairs = _alias_pairs()
        wanted = identity_keys(artist, pairs)
        matched = [(i, name) for i, name in candidates
                   if identity_keys(name, pairs) & wanted]

        if not matched:
            print(
                f"ERROR: no row on {show_date!r} matches artist {artist!r}.",
                file=sys.stderr,
            )
            for i, name in candidates:
                print(f"  row {i}: {name}", file=sys.stderr)
            return 1
        if len(matched) > 1:
            print(
                f"ERROR: artist {artist!r} matches {len(matched)} rows on {show_date!r}. "
                f"Cannot choose between them.",
                file=sys.stderr,
            )
            for i, name in matched:
                print(f"  row {i}: {name}", file=sys.stderr)
            return 1
        candidates = matched

    elif artist:
        # Single candidate, but an artist was given - verify rather than ignore
        # it. A mismatch means the date or the title is wrong, and writing the
        # URL anyway would put a playlist on a show it does not belong to.
        i, name = candidates[0]
        pairs = _alias_pairs()
        if not (identity_keys(name, pairs) & identity_keys(artist, pairs)):
            print(
                f"ERROR: row {i} on {show_date!r} is {name!r}, not {artist!r}. "
                f"Refusing to write a playlist URL to a show it may not belong to.",
                file=sys.stderr,
            )
            return 1

    target_index, target_artist = candidates[0]

    # Pass 2 - write, preserving every other line byte for byte.
    out_lines = [lines[0]]
    for i, line in enumerate(lines[1:], start=2):
        if i != target_index:
            out_lines.append(line)
            continue

        cols = line.split("\t")
        current_url = cols[PLAYLIST_COL].strip()
        if current_url and current_url not in ("-", ""):
            if current_url == playlist_url:
                print(
                    f"Row {i} ({show_date}, {target_artist}): playlist URL already "
                    f"set to same value. No change."
                )
                return 0
            print(
                f"WARNING: row {i} ({show_date}, {target_artist}) already has playlist "
                f"URL {current_url!r}. Overwriting with {playlist_url!r}."
            )
        cols[PLAYLIST_COL] = playlist_url
        out_lines.append("\t".join(cols))
        print(
            f"Updated row {i} ({show_date}, {target_artist}): playlist URL = {playlist_url}"
        )

    CURRENT_PATH.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
