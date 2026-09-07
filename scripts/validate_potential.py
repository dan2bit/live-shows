#!/usr/bin/env python3
"""
validate_potential.py

Validates live_shows_potential.tsv on every push that touches it.

Exists because eight rows were silently corrupted by a column shift that no
existing check could see: an empty Fees Notes value was omitted at write time,
everything from index 12 rightward slid one position left, and the row was
padded back to 19 fields with a trailing empty. Field count stayed valid,
punctuation stayed valid, sort order stayed valid, and the Notes paragraph
ended up rendering inside the Next Show bracket.

Checks:
  1. Column count - every row must have exactly 19 columns. Read raw, never
     padded: a reader that tops short rows up to the header width cannot see
     the defect it exists to catch. (check_brackets.py pads, which is why the
     one 18-field row read as well-formed there.)
  2. Decision - must be Buy, Choose, Sell or Pass.
  3. Date - must begin YYYY-MM-DD. Where a weekday abbreviation follows, it
     must agree with the date.
  4. Bracket columns - Prev Show and Next Show must be blank, '-', or begin
     with a date. This is the check that catches the shift above, and it earns
     its place mainly by planting a typed column at index 14/15.
  5. Sort order - Buy, Choose, Sell, Pass, with dates ascending inside each
     group.
  6. No leading '#' row - the in-page editor derives its header from the first
     line, so a comment block wipes every row on save.

A column shift is only visible where a strongly-typed column sits downstream of
where the shift begins. Everything from Fees Notes to Box Office in this file is
free prose, which is exactly why the corruption ran silently to the end of the
row. Keep that in mind before appending more free-text columns.

Exits non-zero on any violation so the GitHub Actions workflow fails visibly.
"""

import datetime
import re
import sys
from pathlib import Path

POTENTIAL_PATH = Path("data/live_shows_potential.tsv")
EXPECTED_COLS = 19

# Column indices (0-based)
COL_ARTIST = 0
COL_DATE = 2
COL_DECISION = 3
COL_PREV_SHOW = 14
COL_NEXT_SHOW = 15

VALID_DECISIONS = ["Buy", "Choose", "Sell", "Pass"]
DECISION_RANK = {d: i for i, d in enumerate(VALID_DECISIONS)}

# A date cell begins with an ISO date. It may carry a weekday, and may describe
# a run of nights ("2026-09-25 Fri - 2026-09-27 Sun"), so this is a prefix test.
DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})\b")
DATE_WITH_WEEKDAY = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b")

BLANK = ("", "-")


def main() -> int:
    if not POTENTIAL_PATH.exists():
        print(f"ERROR: {POTENTIAL_PATH} not found", file=sys.stderr)
        return 1

    # Only trailing NEWLINES are stripped, never trailing whitespace. Box Office
    # is the last column and is usually empty, so the final line legitimately
    # ends in a tab; text.strip() eats it and turns a valid 19-field row into an
    # 18-field one. A validator that manufactures the defect it is looking for
    # is worse than no validator.
    raw = POTENTIAL_PATH.read_text(encoding="utf-8").splitlines()
    while raw and not raw[-1].strip():
        raw.pop()
    if not raw:
        print(f"ERROR: {POTENTIAL_PATH} is empty", file=sys.stderr)
        return 1

    errors = []

    # 6. Comment block (issue history in docs/ISSUE_LOG.md)
    for i, line in enumerate(raw, start=1):
        if line.lstrip().startswith("#"):
            errors.append(
                f"Row {i}: comment line in an in-page-editable TSV. The editor "
                f"derives the header from the first line; a comment block wipes "
                f"every row on save."
            )

    # Report comments before touching the header. If line 1 is a comment then the
    # header check below reads it as a 1-column header and returns early with a
    # confusing count, burying the actual diagnosis.
    if errors:
        print(f"{len(errors)} validation error(s) found in {POTENTIAL_PATH}:\n")
        for e in errors:
            print(f"  {e}")
        return 1

    headers = raw[0].split("\t")
    if len(headers) != EXPECTED_COLS:
        print(f"ERROR: Header has {len(headers)} columns, expected {EXPECTED_COLS}")
        return 1

    ordering = []

    for i, line in enumerate(raw[1:], start=2):
        cols = line.split("\t")
        row_id = cols[COL_ARTIST] if cols else f"row {i}"

        # 1. Column count
        if len(cols) != EXPECTED_COLS:
            errors.append(
                f"Row {i} ({row_id}): {len(cols)} columns, expected "
                f"{EXPECTED_COLS}"
            )
            continue  # every index below would be reading the wrong field

        # 2. Decision
        decision = cols[COL_DECISION].strip()
        if decision not in DECISION_RANK:
            errors.append(
                f"Row {i} ({row_id}): invalid Decision {cols[COL_DECISION]!r} "
                f"(expected one of {', '.join(VALID_DECISIONS)})"
            )

        # 3. Date, and the weekday if one is present
        date_cell = cols[COL_DATE].strip()
        m = DATE_PREFIX.match(date_cell)
        if not m:
            errors.append(
                f"Row {i} ({row_id}): Date {cols[COL_DATE]!r} does not begin "
                f"with YYYY-MM-DD"
            )
        else:
            wd = DATE_WITH_WEEKDAY.match(date_cell)
            if wd:
                try:
                    actual = datetime.date.fromisoformat(wd.group(1)).strftime("%a")
                except ValueError:
                    actual = None
                    errors.append(
                        f"Row {i} ({row_id}): Date {wd.group(1)!r} is not a real "
                        f"calendar date"
                    )
                if actual and actual != wd.group(2):
                    errors.append(
                        f"Row {i} ({row_id}): Date {date_cell!r} says "
                        f"{wd.group(2)} but {wd.group(1)} is a {actual}"
                    )
            ordering.append((i, row_id, DECISION_RANK.get(decision, 99), m.group(1)))

        # 4. Bracket columns must look like show brackets, not prose
        for idx, label in ((COL_PREV_SHOW, headers[COL_PREV_SHOW]),
                           (COL_NEXT_SHOW, headers[COL_NEXT_SHOW])):
            val = cols[idx].strip()
            if val in BLANK:
                continue
            if not DATE_PREFIX.match(val):
                errors.append(
                    f"Row {i} ({row_id}): {label} is not blank, '-', or a dated "
                    f"bracket: {val[:60]!r}. This is the signature of a column "
                    f"shift - compare the row against the header."
                )

    # 5. Sort order
    keys = [(rank, date) for _, _, rank, date in ordering]
    if keys != sorted(keys):
        for prev, cur in zip(ordering, ordering[1:]):
            if (cur[2], cur[3]) < (prev[2], prev[3]):
                errors.append(
                    f"Row {cur[0]} ({cur[1]}): out of order - "
                    f"{VALID_DECISIONS[cur[2]] if cur[2] < 4 else '?'} {cur[3]} "
                    f"follows {VALID_DECISIONS[prev[2]] if prev[2] < 4 else '?'} "
                    f"{prev[3]}. Expected {', '.join(VALID_DECISIONS)} with dates "
                    f"ascending inside each group."
                )

    if errors:
        print(f"{len(errors)} validation error(s) found in {POTENTIAL_PATH}:\n")
        for e in errors:
            print(f"  {e}")
        return 1

    counts = {d: 0 for d in VALID_DECISIONS}
    for line in raw[1:]:
        d = line.split("\t")[COL_DECISION].strip()
        if d in counts:
            counts[d] += 1
    summary = ", ".join(f"{counts[d]} {d}" for d in VALID_DECISIONS)
    print(f"OK — {len(raw)-1} rows validated ({summary}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
