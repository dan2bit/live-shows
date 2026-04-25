#!/usr/bin/env python3
"""
rollover.py — Migrate attended shows from live_shows_current.tsv to history/<year>.tsv

Usage:
    python3 rollover.py --year 2026 [--dry-run] [--force]

For each attended row in live_shows_current.tsv whose Show Date falls within <year>:
  1. Converts it to the abbreviated history format
  2. Appends it to history/<year>.tsv (creates the file with a header if it doesn't exist)
  3. Removes the row from live_shows_current.tsv

Edge cases handled:
  - No rows found for the requested year → prints summary, exits cleanly
  - history/<year>.tsv already exists with some of the same rows → skips duplicates
    (dedup key: Show Date + Artist)
  - Row status is not 'attended' → skipped with a warning
  - Partial runs → safe to re-run; duplicates are detected and skipped
  - --dry-run → prints what would happen without writing any files
  - --force → suppresses the confirmation prompt
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

# Columns in live_shows_current.tsv (in order)
CURRENT_COLS = [
    "Show ID",
    "Artist",
    "Supporting Artist",
    "Show Date",
    "Doors Time",
    "Start Time",
    "Venue Name",
    "Venue Address",
    "Venue Event URL",
    "Seat Info / GA",
    "Ticket Access",
    "Ticket Quantity",
    "Face Value (per ticket)",
    "Fees",
    "Total Cost",
    "Purchase Date",
    "Setlist.fm URL",
    "Status",
    "Food & Bev",
    "Parking",
    "Merch",
    "Artist Interaction",
    "Playlist URL",
    "Notes / Memories",
]

# Columns in history/<year>.tsv (in order)
HISTORY_COLS = [
    "Show Date",
    "Artist",
    "Supporting Acts",
    "Venue",
    "Setlist.fm URL",
    "Playlist URL",
    "Match Type",
    "YT Title",
    "Notes / Memories",
]

# Spending columns dropped during migration (authority is spending.tsv)
SPENDING_COLS = {"Food & Bev", "Parking", "Merch", "Artist Interaction",
                 "Total Cost", "Face Value (per ticket)", "Fees"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def resolve_paths(year: int) -> tuple:
    """Return (current_path, history_path) relative to this script's location."""
    script_dir = Path(__file__).parent
    current_path = script_dir / "live_shows_current.tsv"
    history_path = script_dir / "history" / f"{year}.tsv"
    return current_path, history_path


def read_tsv(path: Path) -> list:
    """Read a TSV file and return a list of dicts. Returns [] if file doesn't exist."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return list(reader)


def write_tsv(path: Path, rows: list, fieldnames: list) -> None:
    """Write rows to a TSV file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=fieldnames, delimiter="\t",
            extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def append_tsv(path: Path, rows: list, fieldnames: list) -> None:
    """Append rows to an existing TSV file (no header written)."""
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=fieldnames, delimiter="\t",
            extrasaction="ignore", lineterminator="\n"
        )
        writer.writerows(rows)


def dedup_key(row: dict) -> tuple:
    return (row.get("Show Date", "").strip(), row.get("Artist", "").strip())


def current_to_history(row: dict) -> dict:
    """
    Convert a live_shows_current.tsv row to the abbreviated history format.

    Spending columns (Food & Bev, Parking, Merch, Artist Interaction, Total Cost,
    Face Value, Fees) are intentionally dropped — spending.tsv is the authority.

    Match Type and YT Title are left blank — youtube_correlate.py fills them
    when the pipeline is run after video upload.
    """
    return {
        "Show Date":       row.get("Show Date", "").strip(),
        "Artist":          row.get("Artist", "").strip(),
        "Supporting Acts": row.get("Supporting Artist", "").strip(),
        "Venue":           row.get("Venue Name", "").strip(),
        "Setlist.fm URL":  row.get("Setlist.fm URL", "").strip(),
        "Playlist URL":    row.get("Playlist URL", "").strip(),
        "Match Type":      "",   # filled by youtube_correlate.py
        "YT Title":        "",   # filled by youtube_correlate.py
        "Notes / Memories": row.get("Notes / Memories", "").strip(),
    }


def validate_date(date_str: str):
    """Parse YYYY-MM-DD; return datetime or None if invalid."""
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d")
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def run(year: int, dry_run: bool, force: bool) -> int:
    """Execute the rollover. Returns 0 on success, 1 on error."""
    current_path, history_path = resolve_paths(year)

    if not current_path.exists():
        print(f"ERROR: {current_path} not found.", file=sys.stderr)
        return 1

    current_rows = read_tsv(current_path)
    history_rows = read_tsv(history_path)

    print(f"Read {len(current_rows)} rows from {current_path.name}")
    if history_rows:
        print(f"Read {len(history_rows)} existing rows from {history_path.name}")
    else:
        print(f"History file {history_path.name} does not exist yet")

    # Build set of already-migrated (date, artist) keys
    existing_keys = {dedup_key(r) for r in history_rows}

    # Classify every row in current
    to_migrate = []
    to_keep = []
    skipped_status = []
    skipped_wrong_year = []
    skipped_duplicate = []
    skipped_bad_date = []

    for row in current_rows:
        date_str = row.get("Show Date", "").strip()
        status = row.get("Status", "").strip().lower()

        dt = validate_date(date_str)
        if dt is None:
            skipped_bad_date.append(row)
            to_keep.append(row)
            continue

        if dt.year != year:
            skipped_wrong_year.append(row)
            to_keep.append(row)
            continue

        if status != "attended":
            skipped_status.append(row)
            to_keep.append(row)
            continue

        key = dedup_key(row)
        if key in existing_keys:
            # Already in history — remove from current but don't re-append
            skipped_duplicate.append(row)
            continue

        to_migrate.append(row)

    # --- Summary ---
    print()
    print(f"Year {year} summary:")
    print(f"  {len(to_migrate):3d}  rows to migrate to history/{year}.tsv")
    print(f"  {len(skipped_duplicate):3d}  already in history/{year}.tsv (will be removed from current)")
    print(f"  {len(skipped_status):3d}  in year {year} but not 'attended' (kept in current)")
    print(f"  {len(skipped_wrong_year):3d}  in a different year (kept in current)")
    if skipped_bad_date:
        print(f"  {len(skipped_bad_date):3d}  rows with unparseable dates (kept in current) ⚠️")

    if skipped_status:
        print()
        print(f"  Non-attended {year} rows (kept in current):")
        for r in skipped_status:
            print(f"    [{r.get('Status', '?')}] {r.get('Show Date', '?')}  {r.get('Artist', '?')}")

    if skipped_duplicate:
        print()
        print(f"  Already-migrated rows (removed from current):")
        for r in skipped_duplicate:
            print(f"    {r.get('Show Date', '?')}  {r.get('Artist', '?')}")

    if to_migrate:
        print()
        print(f"  Rows to migrate:")
        for r in to_migrate:
            print(f"    {r.get('Show Date', '?')}  {r.get('Artist', '?')}")

    if not to_migrate and not skipped_duplicate:
        print()
        print("Nothing to do — no attended rows found for this year that need migration.")
        return 0

    if dry_run:
        print()
        print("DRY RUN — no files written.")
        return 0

    if not force:
        print()
        try:
            answer = input("Proceed? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return 0
        if answer != "y":
            print("Aborted.")
            return 0

    # --- Write history ---
    history_rows_to_write = [current_to_history(r) for r in to_migrate]

    if not history_path.exists():
        write_tsv(history_path, history_rows_to_write, HISTORY_COLS)
        print(f"Created {history_path} with {len(history_rows_to_write)} rows.")
    else:
        append_tsv(history_path, history_rows_to_write, HISTORY_COLS)
        print(f"Appended {len(history_rows_to_write)} rows to {history_path}.")

    # --- Rewrite current (keeping only to_keep rows) ---
    # Preserve the actual column order from the file header
    with open(current_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        actual_cols = reader.fieldnames or CURRENT_COLS

    write_tsv(current_path, to_keep, list(actual_cols))
    removed_count = len(to_migrate) + len(skipped_duplicate)
    print(f"Removed {removed_count} rows from {current_path.name} "
          f"({len(to_keep)} rows remaining).")

    print()
    print("Done.")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate attended shows from live_shows_current.tsv to history/<year>.tsv"
    )
    parser.add_argument(
        "--year",
        type=int,
        required=True,
        help="The calendar year to migrate (e.g. 2026)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without writing any files",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip the confirmation prompt",
    )
    args = parser.parse_args()

    if args.year < 2021 or args.year > datetime.now().year + 1:
        print(f"ERROR: --year {args.year} looks wrong. "
              f"Expected between 2021 and {datetime.now().year + 1}.", file=sys.stderr)
        sys.exit(1)

    sys.exit(run(args.year, args.dry_run, args.force))


if __name__ == "__main__":
    main()
