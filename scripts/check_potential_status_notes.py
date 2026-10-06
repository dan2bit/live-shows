#!/usr/bin/env python3
"""check_potential_status_notes.py — advisory scan of potentials prose for status text.

Decisions on `data/live_shows_potential.tsv` rows are often made on the web - the
in-page editor, or off-site while buying a ticket - and the row's `Decision` column
changes without anyone touching `Notes`. Any prose that states what a row's decision
is or was ("upgraded to Choose per Dan", "see Choose entry above", "already
purchased") then contradicts the row it sits on, and nothing re-validates it.

The convention this check serves (`DATA_WRITE_PROTOCOLS.md` → potentials write
protocol → "Notes records facts and reasons, never status"): the `Decision` column
is the only place a row's status lives; `Notes` and `Availability Notes` carry why
a show fits or does not, who is on the bill, how it surfaced, and what it collides
with - naming the other show by artist, venue and date, never by its decision.

Two classes of finding, reported as two sections:

  status wording   - a phrase that records a decision or purchase state. A text
                     heuristic with real false positives ("purchased" inside a
                     venue's own notes, say), so advisory: it never blocks.
  cross-row        - a `Decision` named in one row's prose for a sibling row
                     ("(Choose)", "Choose entry above") that disagrees with the
                     sibling's actual `Decision` now. A stronger signal, kept
                     distinct so it is not lost among the wording hits.

Exit code is always 0 - advisory, same reasoning as check_name_drift.py. Findings
land in the job summary through hygiene_report.py.

    python3 scripts/check_potential_status_notes.py            # scan, summary, exit 0
    python3 scripts/check_potential_status_notes.py --quiet    # tallies only
    python3 -m doctest scripts/check_potential_status_notes.py # silent means pass

The issue history behind this check is logged in docs/ISSUE_LOG.md.
"""

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hygiene_report import Report  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
POTENTIAL = ROOT / "data" / "live_shows_potential.tsv"

DECISIONS = ("Buy", "Choose", "Sell", "Pass")
_D = "(?:Buy|Choose|Sell|Pass)"

# Phrases that record a decision or purchase state. Each is deliberately narrow -
# a bare "Pass" or "purchase" would hit the Watching For vocabulary, venue notes
# and ticketing prose that are not status at all.
STATUS_PATTERNS = [
    (re.compile(r"\b(?:up|down)graded to\b", re.I), "decision change recorded in prose"),
    (re.compile(r"\badded as " + _D + r"\b", re.I), "row's own decision recorded in prose"),
    (re.compile(r"\bleft as " + _D + r"\b", re.I), "row's own decision recorded in prose"),
    (re.compile(r"\b" + _D + r" per Dan\b", re.I), "row's own decision recorded in prose"),
    (re.compile(r"\bper Dan\b", re.I), "decision attribution ('per Dan') - the Decision column already says so"),
    (re.compile(r"\b(?:once|already|now|not yet) purchased\b", re.I), "purchase state of this or another row"),
    (re.compile(r"\bpurchased the\b", re.I), "purchase state of another row"),
    (re.compile(r"\(" + _D + r"\)", re.I), "another row's decision cited in parentheses"),
    (re.compile(r"\b" + _D + r" (?:entry|row)\b", re.I), "another row's decision cited by name"),
    (re.compile(r"\bsee " + _D + r"\b", re.I), "another row's decision cited by name"),
]

# "(Choose)" or "Choose entry/row" with a nearby artist name: the cross-row form.
CROSS_RE = re.compile(
    r"(?P<pre>[A-Z][\w'&.\- ]{1,50}?)\s*\((?P<dec>" + _D + r")\)"   # Chris Smither (Choose)
    r"|\b(?P<dec2>" + _D + r") (?:entry|row)\b",                    # see Choose entry above
    re.I)


def find_status(text):
    """Status phrases in one prose cell, deduplicated by reason.

    >>> [r for _, r in find_status("Upgraded to Choose per Dan; see the Pass entry below")]
    ['decision change recorded in prose', "row's own decision recorded in prose", "another row's decision cited by name"]
    >>> find_status("Same band as the Oct 9 Hamilton Live show")
    []
    >>> [m for m, _ in find_status("Already purchased the Oct 9 show")]
    ['Already purchased', 'purchased the']
    """
    out, seen = [], set()
    text = text or ""
    for pat, reason in STATUS_PATTERNS:
        m = pat.search(text)
        if not m or reason in seen:
            continue
        # "Choose per Dan" is already the stronger decision-form hit; the bare
        # attribution only adds information when no decision word is attached.
        if reason.startswith("decision attribution") and re.search(r"\b" + _D + r" per Dan\b", text, re.I):
            continue
        seen.add(reason)
        out.append((m.group(0), reason))
    return out


def cross_refs(text):
    """(cited decision, artist-or-None) pairs from one prose cell.

    >>> cross_refs("Chris Smither (Choose) is Sep 19")
    [('Choose', 'Chris Smither')]
    >>> cross_refs("See Choose entry above")
    [('Choose', None)]
    >>> cross_refs("Pass on density")
    []
    """
    out = []
    for m in CROSS_RE.finditer(text or ""):
        if m.group("dec"):
            out.append((m.group("dec").capitalize(), m.group("pre").strip(" ,;-")))
        else:
            out.append((m.group("dec2").capitalize(), None))
    return out


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def rows():
    with POTENTIAL.open(encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    rdr = csv.DictReader(lines, delimiter="\t")
    # line numbers: header is line 1, first data row line 2
    return [(i + 2, r) for i, r in enumerate(rdr)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="tallies only, no per-finding lines")
    args = ap.parse_args()

    if not POTENTIAL.exists():
        print(f"{POTENTIAL} missing - nothing to scan.")
        return 0

    data = rows()
    rel = POTENTIAL.relative_to(ROOT)
    by_artist = {}
    for ln, r in data:
        by_artist.setdefault(_norm(r.get("Artist")), []).append((ln, r))

    wording = Report("check_potential_status_notes")
    cross = Report("check_potential_status_notes (cross-row Decision disagreement)")

    for ln, r in data:
        artist, decision = r.get("Artist", ""), r.get("Decision", "")
        for col in ("Notes", "Availability Notes"):
            text = r.get(col, "") or ""
            if text in ("", "-"):
                continue
            for phrase, reason in find_status(text):
                msg = f"{artist} {r.get('Date','')[:10]} [{decision}] {col}: '{phrase}' - {reason}"
                if args.quiet:
                    wording.findings.append((str(rel), ln, msg))
                else:
                    wording.warn(msg, path=rel, line=ln)
            for cited, who in cross_refs(text):
                # Resolve the referenced row(s): a named artist, else this artist's
                # sibling rows (the "see Choose entry above" form).
                if who:
                    key = next((k for k in by_artist if _norm(who).endswith(k) or k.endswith(_norm(who))), None)
                    targets = [t for t in by_artist.get(key, []) if t[0] != ln] if key else []
                    label = who
                else:
                    targets = [t for t in by_artist.get(_norm(artist), []) if t[0] != ln]
                    label = f"a sibling {artist} row"
                if not targets:
                    continue  # nothing to compare against - the wording hit above still stands
                actual = sorted({t[1].get("Decision", "") for t in targets})
                if cited not in actual:
                    msg = (f"{artist} {r.get('Date','')[:10]} {col} cites {label} as '{cited}' "
                           f"but that row is now {'/'.join(actual)}")
                    if args.quiet:
                        cross.findings.append((str(rel), ln, msg))
                    else:
                        cross.warn(msg, path=rel, line=ln)

    code = wording.finish()
    code = max(code, cross.finish())
    print(f"rows scanned: {len(data)}; rows with status wording: "
          f"{len({f[1] for f in wording.findings})}; cross-row disagreements: {cross.count}")
    return code


if __name__ == "__main__":
    sys.exit(main())
