#!/usr/bin/env python3
"""check_box_office.py  (#186) — warn-only guardrail for the Box Office flag.

For every live_shows_potential.tsv row with Box Office = Y, resolve the venue
through data/venue_aliases.tsv (#189) and look it up in data/venues.tsv (same
chain as app.js: first-comma-truncate -> _venueKey normalization -> alias ->
canonical) and emit a GitHub Actions ::warning when:

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
ALIASES_PATH = Path("data/venue_aliases.tsv")


def venue_key(v: str) -> str:
    s = (v or "").lower()
    s = re.sub(r"^the\s+", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_aliases() -> dict:
    """#189 — venue_aliases.tsv rows (Alias -> canonical Venue Name), keyed the
    same way as app.js: first-comma-truncate then venue_key. Missing file = {}."""
    if not ALIASES_PATH.exists():
        return {}
    aliases = {}
    lines = ALIASES_PATH.read_text(encoding="utf-8").strip().splitlines()
    for line in lines[1:]:
        cols = line.split("\t")
        if len(cols) >= 2 and cols[0] and cols[1]:
            aliases[venue_key(cols[0].split(",")[0])] = cols[1].strip()
    return aliases


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
    aliases = load_aliases()

    warned = 0
    _, pots = read_tsv(POTENTIALS_PATH)
    for r in pots:
        if (r.get("Box Office") or "").strip().upper() != "Y":
            continue
        name = (r.get("Venue") or "").strip()
        base = name.split(",")[0].strip()
        canonical = aliases.get(venue_key(base), base)
        key = venue_key(canonical)
        if key not in capability:
            print(f"::warning::Box Office flag on '{r.get('Artist','?')}' at '{name}' — "
                  f"venue not found in venues.tsv even after alias resolution; add a "
                  f"data/venue_aliases.tsv row or a venues.tsv entry (unresolved names "
                  f"also break the badge venue match)")
            warned += 1
        elif capability[key] == "No":
            print(f"::warning::Box Office flag on '{r.get('Artist','?')}' at '{name}' — "
                  f"venues.tsv marks this venue 'In Person Box Office' = No")
            warned += 1

    print(f"check_box_office: {warned} warning(s)." if warned else "check_box_office: clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
