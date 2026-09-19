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

WHY DISPLAY NAMES ARE A SEPARATE FILE FROM THE ALIAS TABLE

The posters do NOT use the canonical name, and that is deliberate rather than
sloppy. The crescendo poster grades type size by slot, so the closer is set in
the largest face on the page - `Christone "Kingfish" Ingram` breaks that line.
The timeline poster's column is narrower still and needed a third spelling,
`Trombone Shorty & Orleans Ave.`

So a generator emitting one name everywhere would regress both layouts, and a
generator storing only the short name would lose the link back to artist data
(`identity_keys()` resolves the canonical form, not the poster's abbreviation).

`data/artist_display.tsv` holds `Canonical | Medium | Short | Poster`:

  - `Short`  - the MAP only: a label beside a 3-pixel dot
  - `Medium` - the map's roomier contexts
  - `Poster` - both festival posters, sparse: present only where the poster wants
               something other than `Medium`
  - blank    - fall back to `Medium`, then to the canonical name

`Short` is map-only by decision. The map abbreviates hard because its labels sit
beside a dot - `St. Paul & The Broken Bones` becomes `Broken Bones` - and those
cuts read as mistakes at poster size. `Poster` exists because the two surfaces are
answering different questions, not because one of them is wrong.

It lives in `data/` rather than `festival/` because it is not festival-specific:
the map has the same problem, where a long name overflows a settlement label. A
second copy under `tools/map/` did appear and has since been merged back into this
one - which is why the header reads `Canonical` rather than `Artist`, and why this
parser reads by column NAME. Most rows in it are the map's and name acts that are
not on any festival bill; that is expected, not drift.

IT IS NOT recommend_aliases.tsv, AND MUST NOT BE MERGED WITH IT

The two look alike and run in opposite directions:

  recommend_aliases.tsv  many spellings -> one canonical. Identity, on the way IN.
  artist_display.tsv     one canonical -> one name per width. Rendering, on the way OUT.

`identity_keys()` expands the alias table BIDIRECTIONALLY, so a display row living
there would leak into every join as a claim that two names mean the same artist.

The decisive case is Kingfish. `recommend_aliases.tsv` already carries
`Kingfish -> Christone 'Kingfish' Ingram`, but the poster wants neither of those:
it wants `Kingfish Ingram`, a third form in neither file. A display name cannot be
derived from an alias even when a shorter alias exists.

Lookups resolve through `identity_keys()` rather than raw string equality, because
the repo carries two spellings of that act - `artists.tsv` and the alias table use
`Christone 'Kingfish' Ingram`, the festival markdown uses `Christone "Kingfish"
Ingram`. They normalize to the same key; an exact match would silently stop
applying the moment either file changed quote style.

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
sys.path.insert(0, str(ROOT / "scripts"))
from name_forms import identity_keys  # noqa: E402  (path set above)

SOURCE = ROOT / "festival" / "festival_lineup.md"
OVERRIDES = ROOT / "data" / "artist_display.tsv"
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
    """-> {canonical: {short, medium}}. Absent file is fine - most acts need none.

    Read by COLUMN NAME, not position. This file is shared with the map builder,
    whose header is `Canonical | Medium | Short` - a positional read of that order
    silently swaps the two widths, and a positional header guard looking for the
    literal "Artist" lets the header row through as an override for an act called
    "Canonical". Both happened. tools/map/build_fantasy_map.py has always read it
    by name, which is why only this side broke.

    The identity column answers to `Canonical` or `Artist`, so either header works.
    """
    if not path.exists():
        return {}
    lines = [l for l in path.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    if not lines:
        return {}
    header = [c.strip().lower() for c in lines[0].split("\t")]
    if header[0] not in ("canonical", "artist"):
        raise SystemExit("FATAL: %s has an unrecognised header %r - expected a "
                         "Canonical (or Artist) column first" % (path, lines[0]))
    idx = {name: header.index(name) for name in ("short", "medium", "poster")
           if name in header}

    out = {}
    for raw in lines[1:]:
        cells = [c.strip() for c in raw.split("\t")]
        if not cells[0]:
            continue
        entry = {}
        for width, col in idx.items():
            if col < len(cells) and cells[col]:
                entry[width] = cells[col]
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

    seen, acts, lineup_keys = {}, 0, set()
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
            lineup_keys |= identity_keys(s["artist"])

    if acts and acts != 60:
        problems.append("parsed %d acts, expected 60" % acts)

    # NOT an error when a row names an act that is not on the bill: this file is
    # shared with the map, which carries a row for every settlement that needs a
    # shorter label. Most of its rows will never appear in a festival lineup. The
    # check that used to live here assumed a festival-scoped file of two rows and
    # fired 56 times the moment the two files were merged.
    return problems


def resolve_display(days, overrides):
    """Attach short/medium to each slot, keyed through identity_keys.

    The canonical name stays on every slot regardless. A renderer needs the short
    form for the layout AND the canonical form to link back to artist data - the
    short form does not resolve on its own ("Kingfish Ingram" shares no identity
    key with the canonical spelling).
    """
    index = {}
    for name, entry in overrides.items():
        for k in identity_keys(name):
            index[k] = entry
    for d in days:
        for slot in d["slots"]:
            entry = next((index[k] for k in sorted(identity_keys(slot["artist"]))
                          if k in index), None)
            if entry:
                slot["display"] = dict(entry)
    return days


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

    if not problems:
        days = resolve_display(days, overrides)

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
