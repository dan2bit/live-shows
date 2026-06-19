#!/usr/bin/env python3
"""
check_brackets.py

Validates that every Buy and Choose row in live_shows_potential.tsv has
Prev/Next bracket fields that match actual purchased upcoming shows in
live_shows_current.tsv.

Reports mismatches as warnings (non-zero exit) so the GitHub Actions workflow
can surface them as a failed check without blocking the commit.

Pass and Sell rows are exempt — they should not have brackets.
"""

import re
import sys
from datetime import date
from pathlib import Path

POTENTIALS_PATH = Path("data/live_shows_potential.tsv")
CURRENT_PATH = Path("data/live_shows_current.tsv")


def extract_first_date(date_str: str) -> date | None:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", (date_str or "").strip())
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def extract_last_date(date_str: str) -> date | None:
    parts = (date_str or "").split(" - ")
    return extract_first_date(parts[-1].strip())


def read_tsv(path: Path) -> tuple[list[str], list[dict]]:
    text = path.read_text(encoding="utf-8")
    lines = text.strip().splitlines()
    headers = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        cols = line.split("\t")
        while len(cols) < len(headers):
            cols.append("")
        rows.append(dict(zip(headers, cols)))
    return headers, rows


def bracket_date(bracket_str: str) -> date | None:
    """Extract date from bracket field like '2026-08-04 Lake Street Dive (Pier Six)'."""
    return extract_first_date(bracket_str)


def main() -> int:
    if not POTENTIALS_PATH.exists() or not CURRENT_PATH.exists():
        print("ERROR: Required TSV files not found", file=sys.stderr)
        return 1

    _, pot_rows = read_tsv(POTENTIALS_PATH)
    _, cur_rows = read_tsv(CURRENT_PATH)

    today = date.today()

    # Build sorted list of purchased upcoming shows: (date, short_label)
    upcoming = []
    for r in cur_rows:
        if r.get("Status", "").lower() != "upcoming":
            continue
        d = extract_first_date(r.get("Show Date", ""))
        if d and d >= today:
            artist = r.get("Artist", "")
            venue = r.get("Venue Name", "").split(",")[0].strip()
            upcoming.append((d, f"{r.get('Show Date','')[:10]} {artist} ({venue})"))
    upcoming.sort()

    def expected_brackets(show_date: date) -> tuple[str, str]:
        prev_label = next_label = "-"
        for d, label in upcoming:
            if d < show_date:
                prev_label = label
            elif d > show_date and next_label == "-":
                next_label = label
        return prev_label, next_label

    issues = []
    checked = 0

    for row in pot_rows:
        decision = row.get("Decision", "").lower()
        if decision not in ("buy", "choose"):
            continue

        show_date = extract_last_date(row.get("Date", ""))
        if not show_date or show_date < today:
            continue  # Past or undated — skip

        checked += 1
        artist = row.get("Artist", "")
        actual_prev = row.get("Prev Show (2026)", "-").strip()
        actual_next = row.get("Next Show (2026)", "-").strip()
        exp_prev, exp_next = expected_brackets(show_date)

        def dates_match(actual: str, expected: str) -> bool:
            if actual in ("-", "") and expected in ("-", ""):
                return True
            d_actual = bracket_date(actual)
            d_expected = bracket_date(expected)
            if d_actual and d_expected:
                return d_actual == d_expected
            # Fall back to string containment for the date portion
            if actual == "-" or expected == "-":
                return actual == expected
            return actual[:10] == expected[:10]

        prev_ok = dates_match(actual_prev, exp_prev)
        next_ok = dates_match(actual_next, exp_next)

        if not prev_ok:
            issues.append(
                f"BRACKET MISMATCH — {artist} ({row.get('Date','')[:10]}) Prev:\n"
                f"  current:  {actual_prev!r}\n"
                f"  expected: {exp_prev!r}"
            )
        if not next_ok:
            issues.append(
                f"BRACKET MISMATCH — {artist} ({row.get('Date','')[:10]}) Next:\n"
                f"  current:  {actual_next!r}\n"
                f"  expected: {exp_next!r}"
            )

    print(f"Checked {checked} Buy/Choose row(s).")
    if issues:
        print(f"\n{len(issues)} bracket issue(s) found:\n")
        for issue in issues:
            print(issue)
        return 1
    else:
        print("All brackets match purchased upcoming shows.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
