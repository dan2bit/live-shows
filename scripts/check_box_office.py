#!/usr/bin/env python3
"""check_box_office.py  (#186) — warn-only guardrail for the Box Office flag.

For every live_shows_potential.tsv row with Box Office = Y, look the venue up in
data/venues.tsv (same key normalization as app.js _venueKey: lowercase, strip a
leading "The", strip punctuation) and emit a GitHub Actions ::warning when:

  * the venue is marked `In Person Box Office` = No (no advance in-person
    purchase possible there — e.g. Hank Dietle's, JV's), or
  * the venue isn't in venues.tsv at all (name drift also silently breaks the
    badge's venue cross-reference in app.js — same normalization, same miss).

Blank `In Person Box Office` means untested — no warning; that blank IS the
discovery signal. Always exits 0: this advises, it never blocks the pipeline.
"""

import re
import sys
from pathlib import Path

POTENTIALS_PATH = Path("data/live_shows_potential.tsv")
VENUES_PATH = Path("data/venues.tsv")


def venue_key(v: str) -> str:
    s = (v or "").lower()
    s = re.sub(r"^the\s+", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def read_tsv(path: Path) -> tuple[list[str], list[dict]]:
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    headers = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        cols = line.split("\t")
        while len(cols) < len(headers):
            cols.append("")
        rows.append(dict(zip(headers, cols)))
    return headers, rows


def main() -> int:
    if not POTENTIALS_PATH.exists() or not VENUES_PATH.exists():
        print("::warning::check_box_office: required TSV files not found — skipping")
        return 0

    _, venues = read_tsv(VENUES_PATH)
    capability = {venue_key(v.get("Venue Name", "")): (v.get("In Person Box Office") or "").strip()
                  for v in venues}

    warned = 0
    _, pots = read_tsv(POTENTIALS_PATH)
    for r in pots:
        if (r.get("Box Office") or "").strip().upper() != "Y":
            continue
        name = (r.get("Venue") or "").strip()
        key = venue_key(name)
        if key not in capability:
            print(f"::warning::Box Office flag on '{r.get('Artist','?')}' at '{name}' — "
                  f"venue not found in venues.tsv (name drift also breaks the badge venue match)")
            warned += 1
        elif capability[key] == "No":
            print(f"::warning::Box Office flag on '{r.get('Artist','?')}' at '{name}' — "
                  f"venues.tsv marks this venue 'In Person Box Office' = No")
            warned += 1

    print(f"check_box_office: {warned} warning(s)." if warned else "check_box_office: clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
