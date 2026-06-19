#!/usr/bin/env python3
"""
rollover.py — Migrate attended shows from live_shows_current.tsv to history/<year>.tsv

Usage:
    python3 scripts/rollover.py --year 2026 [--private-repo PATH] [--dry-run] [--force]

For each attended row in live_shows_current.tsv whose Show Date falls within <year>:
  1. Converts it to the abbreviated public history format
  2. Appends it to history/<year>.tsv (creates the file with a header if it doesn't exist)
  3. Removes the row from live_shows_current.tsv

Privacy-split architecture (since PR #59):
  Sensitive per-show data (seat info, ticket quantity, cost breakdown, private notes)
  lives in a SEPARATE private repo: live-shows-private/current_private.tsv, keyed by
  Show Date + Artist. The public files carry only denormalized flags (Seat Type / VIP /
  Group). When --private-repo PATH is supplied, this script also:
  4. Archives each migrated show's private row into
     <PATH>/history_private/<year>.tsv (preserves seat info + private notes for posterity)
  5. Prunes that row from <PATH>/current_private.tsv so it doesn't accumulate orphans

  Per-show spend is NOT re-archived here — live-shows-private/spending.tsv is the authority for money and
  already holds it once a show moves to 'attended'. The full private row (cost columns
  included) is archived as-is purely because it's the cheapest lossless thing to keep.

  If --private-repo is omitted, the private repo is left completely untouched and the
  script prints a reminder that current_private.tsv will retain orphan rows.

Edge cases handled:
  - No rows found for the requested year → prints summary, exits cleanly
  - history/<year>.tsv already exists with some of the same rows → skips duplicates
    (dedup key: Show Date + Artist), and still prunes the stale row from current
  - Row status is not 'attended' → skipped with a warning
  - Partial runs → safe to re-run; duplicates are detected and skipped (public + private)
  - --dry-run → prints what would happen without writing any files
  - --force → suppresses the confirmation prompt
  - --private-repo given but current_private.tsv missing → aborts before any writes
    (prevents a public-only migration that silently skips the private side)
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

# Columns in live_shows_current.tsv (public, post-privacy-split) — fallback only;
# the actual file header is preferred when rewriting current.
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
    "Seat Type",
    "VIP",
    "Group",
    "Ticket Access",
    "Setlist.fm URL",
    "Status",
    "Artist Interaction",
    "Playlist URL",
    "Notes / Memories",
    "Photo URL",
]

# Columns in history/<year>.tsv (public, in order). NOTE: Photo URL sits between
# Playlist URL and Match Type — must match the real files or appends corrupt them.
HISTORY_COLS = [
    "Show Date",
    "Artist",
    "Supporting Acts",
    "Venue",
    "Setlist.fm URL",
    "Playlist URL",
    "Photo URL",
    "Match Type",
    "YT Title",
    "Notes / Memories",
]

# Columns in current_private.tsv / history_private/<year>.tsv (private repo, in order).
PRIVATE_COLS = [
    "Show Date",
    "Artist",
    "Seat Info / GA",
    "Ticket Quantity",
    "Face Value (per ticket)",
    "Fees",
    "Total Cost",
    "Purchase Date",
    "Food & Bev",
    "Parking",
    "Merch",
    "Private Notes",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def resolve_paths(year: int, private_repo: str = None) -> tuple:
    """Return (current, history, private_current, private_archive) paths.

    private_current / private_archive are None when --private-repo is not given.
    """
    script_dir = Path(__file__).parent.parent  # repo root (script is in scripts/)
    current_path = script_dir / "data" / "live_shows_current.tsv"
    history_path = script_dir / "data" / "history" / f"{year}.tsv"

    private_current = private_archive = None
    if private_repo:
        priv = Path(private_repo).expanduser()
        private_current = priv / "current_private.tsv"
        private_archive = priv / "history_private" / f"{year}.tsv"

    return current_path, history_path, private_current, private_archive


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
    Convert a public live_shows_current.tsv row to the abbreviated history format.

    Money, seat, quantity and private-notes columns no longer exist in the public
    source (they live in the private sidecar / live-shows-private/spending.tsv), so there is nothing to
    drop here — only public fields are read.

    Venue is the bare Venue Name; the app keys display off the substring before the
    first comma, so the city/state suffix on older reverse-engineered rows is cosmetic.

    Match Type and YT Title are left blank — youtube_correlate.py fills them when the
    pipeline runs after video upload.
    """
    return {
        "Show Date":       row.get("Show Date", "").strip(),
        "Artist":          row.get("Artist", "").strip(),
        "Supporting Acts": row.get("Supporting Artist", "").strip(),
        "Venue":           row.get("Venue Name", "").strip(),
        "Setlist.fm URL":  row.get("Setlist.fm URL", "").strip(),
        "Playlist URL":    row.get("Playlist URL", "").strip(),
        "Photo URL":       row.get("Photo URL", "").strip(),
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

def run(year: int, dry_run: bool, force: bool, private_repo: str = None) -> int:
    """Execute the rollover. Returns 0 on success, 1 on error."""
    current_path, history_path, private_current_path, private_archive_path = \
        resolve_paths(year, private_repo)

    if not current_path.exists():
        print(f"ERROR: {current_path} not found.", file=sys.stderr)
        return 1

    # Fail fast: if the private side was requested, its source must exist BEFORE we
    # write anything, so we never do a public-only migration that skips the sidecar.
    if private_repo and not private_current_path.exists():
        print(f"ERROR: --private-repo given but {private_current_path} not found.",
              file=sys.stderr)
        print("       Check the path; no files were modified.", file=sys.stderr)
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

    # Every row leaving current (fresh migrations + already-in-history dupes) is a
    # candidate for private archive + prune, so the sidecar stays in sync with current.
    removed_keys = ({dedup_key(r) for r in to_migrate}
                    | {dedup_key(r) for r in skipped_duplicate})

    # --- Private side: classify (read-only here; writes happen after confirmation) ---
    priv_rows = []
    priv_archive_existing = set()
    priv_to_archive = []
    priv_to_prune = []
    priv_missing = []
    if private_repo:
        priv_rows = read_tsv(private_current_path)
        priv_archive_existing = {dedup_key(r) for r in read_tsv(private_archive_path)}
        priv_by_key = {dedup_key(r): r for r in priv_rows}
        for key in removed_keys:
            pr = priv_by_key.get(key)
            if pr is None:
                priv_missing.append(key)
                continue
            priv_to_prune.append(pr)
            if key not in priv_archive_existing:
                priv_to_archive.append(pr)

    # --- Summary ---
    print()
    print(f"Year {year} summary:")
    print(f"  {len(to_migrate):3d}  rows to migrate to history/{year}.tsv")
    print(f"  {len(skipped_duplicate):3d}  already in history/{year}.tsv (will be removed from current)")
    print(f"  {len(skipped_status):3d}  in year {year} but not 'attended' (kept in current)")
    print(f"  {len(skipped_wrong_year):3d}  in a different year (kept in current)")
    if skipped_bad_date:
        print(f"  {len(skipped_bad_date):3d}  rows with unparseable dates (kept in current) ⚠️")

    if private_repo:
        print()
        print(f"  Private archive (--private-repo):")
        print(f"    {len(priv_to_archive):3d}  rows to archive to history_private/{year}.tsv")
        print(f"    {len(priv_to_prune):3d}  rows to prune from current_private.tsv")
        if priv_missing:
            print(f"    {len(priv_missing):3d}  migrated shows with NO matching private row "
                  f"(nothing to archive) ⚠️")
            for (d, a) in priv_missing:
                print(f"         {d}  {a}")
    else:
        print()
        print("  --private-repo not given: current_private.tsv left untouched "
              "(orphan rows will remain).")

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

    # --- Write public history (copy before delete) ---
    history_rows_to_write = [current_to_history(r) for r in to_migrate]

    if not history_path.exists():
        write_tsv(history_path, history_rows_to_write, HISTORY_COLS)
        print(f"Created {history_path} with {len(history_rows_to_write)} rows.")
    else:
        append_tsv(history_path, history_rows_to_write, HISTORY_COLS)
        print(f"Appended {len(history_rows_to_write)} rows to {history_path}.")

    # --- Archive private rows (copy before prune) ---
    if private_repo:
        if priv_to_archive:
            if not private_archive_path.exists():
                write_tsv(private_archive_path, priv_to_archive, PRIVATE_COLS)
                print(f"Created {private_archive_path} with {len(priv_to_archive)} rows.")
            else:
                append_tsv(private_archive_path, priv_to_archive, PRIVATE_COLS)
                print(f"Appended {len(priv_to_archive)} rows to {private_archive_path}.")
        else:
            print("No new private rows to archive.")

    # --- Rewrite current (keeping only to_keep rows) ---
    # Preserve the actual column order from the file header
    with open(current_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        actual_cols = reader.fieldnames or CURRENT_COLS

    write_tsv(current_path, to_keep, list(actual_cols))
    removed_count = len(to_migrate) + len(skipped_duplicate)
    print(f"Removed {removed_count} rows from {current_path.name} "
          f"({len(to_keep)} rows remaining).")

    # --- Prune current_private (remove migrated keys) ---
    if private_repo:
        prune_keys = {dedup_key(r) for r in priv_to_prune}
        kept_priv = [r for r in priv_rows if dedup_key(r) not in prune_keys]
        with open(private_current_path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            priv_actual_cols = reader.fieldnames or PRIVATE_COLS
        write_tsv(private_current_path, kept_priv, list(priv_actual_cols))
        print(f"Pruned {len(priv_to_prune)} rows from {private_current_path.name} "
              f"({len(kept_priv)} rows remaining).")

    print()
    print("Done.")
    if private_repo:
        print("Remember to commit BOTH repos (live-shows and live-shows-private).")
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
        "--private-repo",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to the live-shows-private repo clone. When given, archives each "
             "migrated show's private row to history_private/<year>.tsv and prunes it "
             "from current_private.tsv. When omitted, the private repo is left untouched.",
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

    sys.exit(run(args.year, args.dry_run, args.force, args.private_repo))


if __name__ == "__main__":
    main()
