#!/usr/bin/env python3
"""
fix_defunct_rows.py — realign the two shifted rows in data/venues.tsv

Both DEFUNCT rows were hand-authored with too few tabs, so values landed left
of where they belong. Padding the file to full width froze the mistake rather
than causing it: the shortfall is absorbed by surplus blanks before State, so
every row still counts 16 fields and no width check can see the problem.

    City Winery         note at 9 -> 10                     (one shift)
    AMP by Strathmore   note at 9 -> 10, short name 12 -> 14 (compounding)

Run from the repo root. Report-only unless --write:

    python3 fix_defunct_rows.py
    python3 fix_defunct_rows.py --write
    git diff data/venues.tsv

Safe to re-run. Each move is verified against the file's current contents
before anything changes, so a row that is already correct is skipped rather
than shifted again.
"""

import os
import sys

VENUES_TSV = os.path.join("data", "venues.tsv")

# venue name -> [(from_index, to_index), ...], 0-based, applied in order
FIXES = {
    "City Winery":       [(9, 10)],
    "AMP by Strathmore": [(9, 10), (12, 14)],
}


def main() -> None:
    write = "--write" in sys.argv

    if not os.path.exists(VENUES_TSV):
        sys.exit(f"Not found: {VENUES_TSV}\nRun this from the repo root.")

    raw = open(VENUES_TSV, encoding="utf-8").read()
    ends_with_newline = raw.endswith("\n")
    lines = raw.split("\n")
    if ends_with_newline:
        lines = lines[:-1]

    header = lines[0].split("\t")
    width  = len(header)
    changed = 0

    for index, line in enumerate(lines[1:], start=1):
        fields = line.split("\t")
        name = fields[0]
        if name not in FIXES:
            continue

        print(f"\n{'=' * 68}\n{name}  (line {index + 1})")

        if len(fields) != width:
            print(f"  SKIP: {len(fields)} fields, expected {width}. "
                  "Run venues_reconcile.py --add-state first.")
            continue

        print("  before:")
        for i, value in enumerate(fields):
            if value:
                print(f"    {i:2}  {header[i]:<30} {value[:70]}")

        moves = []
        for src, dst in FIXES[name]:
            if not fields[src] and fields[dst]:
                print(f"    already correct: {header[dst]} is populated, "
                      f"{header[src]} is empty")
                continue
            if not fields[src]:
                print(f"    SKIP: {header[src]} (index {src}) is empty — "
                      "nothing to move")
                continue
            if fields[dst]:
                print(f"    REFUSING: {header[dst]} (index {dst}) already holds "
                      f"{fields[dst][:40]!r} — would overwrite")
                continue
            moves.append((src, dst))

        if not moves:
            print("  nothing to do")
            continue

        for src, dst in moves:
            fields[dst], fields[src] = fields[src], ""
            print(f"    move  {header[src]} -> {header[dst]}")

        print("  after:")
        for i, value in enumerate(fields):
            if value:
                print(f"    {i:2}  {header[i]:<30} {value[:70]}")

        assert len(fields) == width, "field count changed — aborting"
        lines[index] = "\t".join(fields)
        changed += 1

    print(f"\n{'=' * 68}")
    if not changed:
        print("No rows needed changing.")
        return

    if not write:
        print(f"{changed} row(s) would change. Re-run with --write to apply.")
        return

    with open(VENUES_TSV, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + ("\n" if ends_with_newline else ""))
    print(f"Wrote {VENUES_TSV} ({changed} row(s)). "
          f"Review with: git diff {VENUES_TSV}")


if __name__ == "__main__":
    main()
