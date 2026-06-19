#!/usr/bin/env python3
"""
merge_notes_into_history.py
===========================
One-time script to merge notes_memories_draft.tsv into live_shows_history.tsv.

Run from the live-shows/ directory:
    python3 merge_notes_into_history.py

DESIGN
------
- Reads notes_memories_draft.tsv as the canonical source of truth.
- Matches each draft row to a history row by (Show Date, normalized Artist).
- Normalized matching strips trailing/leading whitespace and collapses Unicode
  apostrophes (', ') to straight apostrophe ('), en/em dashes to hyphen, and
  ampersands to space — for comparison purposes only. Writes always use the
  canonical artist name already in the history file (or the corrected name for
  rows listed in FIELD_CORRECTIONS).
- OVERWRITES any history note that differs from the draft note (draft is canonical).
- Skips draft rows whose note is blank (nothing to write).
- Reports: updated rows, field-corrected rows, skipped-identical rows,
  skipped-blank-draft rows, and unmatched draft keys.

SPECIAL CASES (handled automatically)
--------------------------------------
- 2023-05-20 | The Wood Brothers (draft) -> 2023-05-20 | Shovels & Rope (history)
  Draft artist key was the opener; history headliner is Shovels & Rope.
  The note describes the Wood Brothers opening set — belongs on the S&R row.

- 2024-07-18 | Mike Zito (draft) -> 2024-07-18 | Tab Benoit & Anders Osborne  (history)
  Mike Zito was the supporting act; Tab Benoit is the history headliner.

- 2023-09-26 | Wu-Tang Clan / Nas — headliner/support swap
  History currently has Artist=Nas, Supporting Artist=Wu-Tang Clan.
  Correct order: Artist=Wu-Tang Clan, Supporting Artist=Nas.
  The script matches on the existing Nas key, then swaps the field values
  and writes the note. Listed in FIELD_CORRECTIONS below.

POST-MERGE CLEANUP
------------------
1. Delete this script (one-time use).
2. Deprecate notes_memories_draft.tsv — replace with a worklist of shows that
   still have a blank Notes / Memories column in history.
3. Update Task 3 in TASKS.md to mark complete.
"""

import csv
import os
import re
import sys

DRAFT_FILE        = "notes_memories_draft.tsv"
HISTORY_FILE      = "live_shows_history.tsv"
NOTES_COL         = "Notes / Memories"
DATE_COL          = "Show Date"
ARTIST_COL        = "Artist"
SUPPORTING_COL    = "Supporting Artist"

# Explicit artist key remaps: (draft_date, draft_artist_norm) -> history_artist_norm
# Used when the draft uses a different artist name than what is in history.
# Values must already be in normalized form (lowercase, & replaced by space, etc.)
ARTIST_REMAPS = {
    ("2023-05-20", "the wood brothers"):    "shovels  rope",         # & -> space
    ("2024-07-18", "mike zito"):            "tab benoit  anders osborne",
    # Wu-Tang Clan: draft key is Wu-Tang Clan; history key is currently Nas
    ("2023-09-26", "wu-tang clan"):         "nas",
}

# Field corrections applied after matching.
# Key: (date, norm_artist_as_it_exists_in_history)
# Value: dict of {column_name: new_value} to write.
# These are applied in addition to (or independently of) the note update.
FIELD_CORRECTIONS = {
    ("2023-09-26", "nas"): {
        ARTIST_COL:     "Wu-Tang Clan",
        SUPPORTING_COL: "Nas",
    },
}


def normalize(s):
    """Normalize an artist name for fuzzy matching only (never for output)."""
    s = s.strip()
    # Normalize Unicode apostrophes and quotes to straight apostrophe
    s = s.replace("\u2019", "'").replace("\u2018", "'").replace("\u0060", "'")
    # Normalize en/em dash to hyphen
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    # Normalize ampersand to space (then collapse)
    s = s.replace("&", " ")
    # Lowercase, collapse whitespace
    s = re.sub(r"\s+", " ", s.lower()).strip()
    return s


def load_draft(path):
    """Returns list of (date, artist_raw, note_raw) from draft TSV."""
    rows = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            date   = row.get(DATE_COL, "").strip()
            artist = row.get(ARTIST_COL, "").strip()
            note   = row.get(NOTES_COL, "").strip()
            if date:
                rows.append((date, artist, note))
    return rows


def load_history(path):
    """Returns (fieldnames, rows) from history TSV."""
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def build_history_index(rows):
    """Returns dict: (date, norm_artist) -> row_index in rows list."""
    index = {}
    for i, row in enumerate(rows):
        date   = row.get(DATE_COL, "").strip()
        artist = row.get(ARTIST_COL, "").strip()
        key    = (date, normalize(artist))
        index[key] = i
    return index


def main():
    for path in (DRAFT_FILE, HISTORY_FILE):
        if not os.path.exists(path):
            sys.exit(f"ERROR: {path} not found. Run from live-shows/ directory.")

    draft_rows = load_draft(DRAFT_FILE)
    fieldnames, hist_rows = load_history(HISTORY_FILE)

    if NOTES_COL not in fieldnames:
        sys.exit(f"ERROR: '{NOTES_COL}' column not found in {HISTORY_FILE}")

    hist_index = build_history_index(hist_rows)

    updated           = 0
    field_corrected   = 0
    skipped_identical = 0
    skipped_blank     = 0
    unmatched         = []

    for draft_date, draft_artist, draft_note in draft_rows:
        # Skip 2026 rows — notes already exist in live_shows_2026.tsv
        if draft_date.startswith("2026"):
            continue

        norm_key = (draft_date, normalize(draft_artist))

        # Resolve lookup key — may be remapped to a different history artist
        remapped_norm = ARTIST_REMAPS.get(norm_key)
        lookup = (draft_date, remapped_norm) if remapped_norm else norm_key

        row_idx = hist_index.get(lookup)
        if row_idx is None:
            row_idx = hist_index.get(norm_key)

        if row_idx is None:
            if not draft_note:
                skipped_blank += 1
            else:
                unmatched.append((draft_date, draft_artist, draft_note))
                print(f"  NO MATCH: {draft_date} | {draft_artist}")
            continue

        # Apply any field corrections (e.g. headliner/support swap)
        hist_norm_key = (draft_date, normalize(hist_rows[row_idx].get(ARTIST_COL, "")))
        corrections = FIELD_CORRECTIONS.get(hist_norm_key) or FIELD_CORRECTIONS.get(lookup)
        if corrections:
            for col, new_val in corrections.items():
                old_val = hist_rows[row_idx].get(col, "")
                if old_val != new_val:
                    hist_rows[row_idx][col] = new_val
                    field_corrected += 1
                    print(f"  FIELD FIX [{col}]: {draft_date} | {old_val!r} -> {new_val!r}")
            # Rebuild index if Artist column changed (affects subsequent lookups)
            if ARTIST_COL in corrections:
                hist_index = build_history_index(hist_rows)

        # Skip blank draft notes — nothing to write to Notes / Memories
        if not draft_note:
            skipped_blank += 1
            continue

        hist_note   = (hist_rows[row_idx].get(NOTES_COL) or "").strip()
        hist_artist = hist_rows[row_idx].get(ARTIST_COL, "").strip()

        if draft_note == hist_note:
            skipped_identical += 1
            continue

        # Draft differs — overwrite (draft is canonical)
        hist_rows[row_idx][NOTES_COL] = draft_note
        updated += 1
        if hist_note:
            print(f"  OVERWRITE: {draft_date} | {hist_artist}")
            print(f"    was: {hist_note[:80]}{'...' if len(hist_note) > 80 else ''}")
            print(f"    now: {draft_note[:80]}{'...' if len(draft_note) > 80 else ''}")
        else:
            print(f"  + {draft_date} | {hist_artist}")

    # Write back
    with open(HISTORY_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t",
                                lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(hist_rows)

    print(f"\n{'='*70}")
    print(f"Updated notes (wrote/overwrote): {updated}")
    print(f"Field corrections applied:       {field_corrected}")
    print(f"Skipped (identical):             {skipped_identical}")
    print(f"Skipped (blank draft note):      {skipped_blank}")
    print(f"Unmatched draft keys:            {len(unmatched)}")

    if unmatched:
        print(f"\nUnmatched rows — manual insertion required:")
        for d, a, n in unmatched:
            print(f"\n  {d} | {a}")
            print(f"  Note: {n}")

    print(f"\nDone. Review with: git diff {HISTORY_FILE}")


if __name__ == "__main__":
    main()
