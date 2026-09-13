#!/usr/bin/env python3
"""
build_lineup.py - turn the curated festival markdown into machine-readable JSON.

`festival/festival_lineup.md` is the thing a human edits: running order, notes,
cut list, prose about why an act sits where it does. The posters cannot read it,
so today each poster carries its own hand-written copy of the same 60 acts. That
is three places to edit and three places to drift - and the lineup has already
been revised at least once.

This reads the markdown and emits `festival/lineup.json`. The markdown stays the
source; the JSON is a generated artifact, committed like `recommend_index.json`
and `artist_modal_index.json`.

    python3 tools/festival/build_lineup.py                # write the JSON
    python3 tools/festival/build_lineup.py --check        # verify, write nothing
    python3 tools/festival/build_lineup.py --json         # print, write nothing

WHY DISPLAY NAMES ARE A SEPARATE FILE

The posters do NOT use the canonical name, and that is deliberate rather than
sloppy. The crescendo poster grades type size by slot, so the closer is set in
the largest face on the page - `Christone "Kingfish" Ingram` breaks that line.
The timeline poster's column is narrower still and needed a third spelling,
`Trombone Shorty & Orleans Ave.`

So a generator emitting one name everywhere would regress both layouts, and a
generator storing only the short name would lose the link back to artist data
(`identity_keys()` resolves the canonical form, not the poster's abbreviation).

`festival/display_overrides.tsv` holds `Artist | Short | Medium`:

  - `Short`  - the crescendo poster, where type is largest
  - `Medium` - the timeline poster's two-column list
  - neither  - the canonical name is already short enough, which is the case for
               58 of the 60 acts

An override naming an artist who is not in the lineup is reported, because that
is how the file goes stale: the act gets cut, the override stays, and nothing
notices.

TYPOGRAPHY IS NOT AN OVERRIDE

Both posters render apostrophes as `&rsquo;` (`Keb&rsquo; Mo&rsquo;`). That is a
rendering concern for whatever emits the HTML, not a name difference - the source
keeps ASCII punctuation per the repo's TSV rule, and a renderer escapes on the
way out. Do not add typographic variants to the overrides file; it is for
editorial shortening only.

WHAT IS NOT PARSED

The notes under each day, the cut list, and the header prose. They are editorial
and have no rendering target. Parsing them would invite the generator to own
content it cannot round-trip.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "festival" / "festival_lineup.md"
OVERRIDES = ROOT / "festival" / "display_overrides.tsv"
OUTPUT = ROOT / "festival" / "lineup.json"

# "## Day 1 (Friday) - Blues"
_DAY = re.compile(r"^##\s+Day\s+(\d+)\s*\(([^)]+)\)\s*[\u2014-]\s*(.+?)\s*$")
_BOLD = re.compile(r"^\*\*(.+)\*\*$")


def parse_markdown(text):
    """-> [{number, name, theme, slots:[{stage, time, artist, favorite}]}]

    Stage 1 is Main, stage 2 is Second - the column order in the table, which is
    also the order both posters render.
    """
    days, day = [], None
    for raw in text.splitlines():
        line = raw.rstrip()

        m = _DAY.match(line)
        if m:
            day = {"number": int(m.group(1)), "name": m.group(2).strip(),
                   "theme": m.group(3).strip(), "slots": []}
            days.append(day)
            continue

        if day is None or not line.startswith("|"):
            continue

        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 4:
            continue
        if cells[0].lower() == "time" or set(cells[0]) <= set("-: "):
            continue  # header row or its separator

        for time_cell, artist_cell, stage in ((cells[0], cells[1], 1),
                                              (cells[2], cells[3], 2)):
            if not artist_cell:
                continue
            bold = _BOLD.match(artist_cell)
            name = bold.group(1) if bold else artist_cell
            day["slots"].append({"stage": stage, "time": time_cell,
                                 "artist": name.strip(), "favorite": bool(bold)})
    return days


def parse_overrides(path):
    """-> {canonical: {short, medium}}. Absent file is fine - most acts need none."""
    if not path.exists():
        return {}
    out = {}
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        cells = [c.strip() for c in raw.split("\t")]
        if i == 0 and cells[0].lower() == "artist":
            continue
        if not cells[0]:
            continue
        entry = {}
        if len(cells) > 1 and cells[1]:
            entry["short"] = cells[1]
        if len(cells) > 2 and cells[2]:
            entry["medium"] = cells[2]
        if entry:
            out[cells[0]] = entry
    return out


def check(days, overrides):
    """Conditions that must hold. Returns a list of failures.

    Each guards a way this can produce believable but wrong output - a missing
    day reads as a shorter festival, not as a parse failure, and a silently
    dropped row reads as a shorter bill.
    """
    problems = []
    if len(days) != 3:
        problems.append("parsed %d days, expected 3 - the '## Day N (Name) - Theme' "
                        "heading format probably changed" % len(days))

    seen, acts = {}, 0
    for d in days:
        if len(d["slots"]) != 20:
            problems.append("day %d has %d slots, expected 20 (10 per stage)"
                            % (d["number"], len(d["slots"])))
        for s in d["slots"]:
            acts += 1
            key = s["artist"].lower()
            if key in seen:
                problems.append("%s appears twice (%s and %s) - the lineup states "
                                "no act plays twice" % (s["artist"], seen[key],
                                                        "day %d" % d["number"]))
            seen[key] = "day %d" % d["number"]

    if acts and acts != 60:
        problems.append("parsed %d acts, expected 60" % acts)

    for name in overrides:
        if name.lower() not in seen:
            problems.append("display override for %r, which is not in the lineup - "
                            "cut act, or a typo in the override" % name)
    return problems


def build(days, overrides):
    return {
        "source": "festival/festival_lineup.md",
        "generated_by": "tools/festival/build_lineup.py",
        "acts": sum(len(d["slots"]) for d in days),
        "days": days,
        "display_overrides": overrides,
    }


def main():
    try:
        import signal
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (ImportError, AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--source", help="override the markdown path")
    ap.add_argument("--out", help="override the JSON output path")
    ap.add_argument("--check", action="store_true",
                    help="parse and validate, write nothing")
    ap.add_argument("--json", action="store_true",
                    help="print the JSON to stdout, write nothing")
    args = ap.parse_args()

    src = Path(args.source) if args.source else SOURCE
    if not src.exists():
        raise SystemExit("FATAL: no such file: %s" % src)

    days = parse_markdown(src.read_text(encoding="utf-8"))
    overrides = parse_overrides(OVERRIDES)
    problems = check(days, overrides)

    if problems:
        for p in problems:
            print("FATAL: %s" % p, file=sys.stderr)
        return 3

    doc = build(days, overrides)

    if args.json:
        print(json.dumps(doc, indent=2, ensure_ascii=False))
        return 0

    summary = "%d days, %d acts, %d display override(s)" % (
        len(doc["days"]), doc["acts"], len(overrides))
    if args.check:
        print("OK - " + summary)
        return 0

    out = Path(args.out) if args.out else OUTPUT
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print("wrote %s - %s" % (out, summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
