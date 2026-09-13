#!/usr/bin/env python3
"""
potentials_digest.py - what the potentials list needs looked at this week.

The purchase funnel leaks between the potentials row and the purchase, and the
leak is entirely visible in public data that nothing re-reads between sessions:
an on-sale date written into `Watching For` and never swept, a Buy row whose
show is next week with no purchase recorded, a row with no price or link.

Read-only. Reads two committed TSVs and today's date, writes nothing, and takes
no decision - downgrading a stale Choose to Pass is a judgement, not maintenance.

    python3 scripts/potentials_digest.py
    python3 scripts/potentials_digest.py --today 2026-09-13   # for testing
    python3 scripts/potentials_digest.py --json

SILENT WHEN THERE IS NOTHING TO SAY. Every section empty means no output at all
and exit 0, so notify_email.py's empty-body rule suppresses the mail rather than
sending a weekly note that nothing happened.

PARSING `Watching For` IS DELIBERATELY NARROW

That column is free text and mostly is not a date at all - of the values present
when this was written, three carried an on-sale date and the rest were prose
("distance and density", "revisit if it comes closer", a spring-break block).

So a date is only read when the text actually says on-sale. The alternative,
matching any month-day, misreads exactly the row that proves the point:

    "During Spring Break - NO SHOWS block Mar 20-27 2027 (out of town)"

which contains a perfectly good `Mar 20` and means the opposite of an on-sale.

Anything not matched is counted and reported as unparsed rather than dropped
silently, so the size of the gap stays visible. If that count stays high, the
answer is a machine-readable column, not a cleverer regex - see the non-goals in
the issue.
"""

import argparse
import csv
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POTENTIAL = ROOT / "data" / "live_shows_potential.tsv"
CURRENT = ROOT / "data" / "live_shows_current.tsv"

ONSALE_WINDOW = 7     # section 1: on-sale coming up
BUY_WINDOW = 30       # section 3: Buy show date approaching, nothing purchased
CHOOSE_WINDOW = 14    # section 4: decide or drop

# A date is only read out of `Watching For` when the text says on-sale.
_ONSALE_CUE = re.compile(r"on[\s-]?sale", re.I)
_ISO = re.compile(r"\b(20\d\d)-(\d{2})-(\d{2})\b")
_MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()
# Optional weekday, month name, day. The weekday is captured because it
# disambiguates the year better than any heuristic - see infer_year().
_MONTH_DAY = re.compile(
    r"\b(?:(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?,?\s+)?"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b",
    re.I)
_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

STALE_GRACE = 60      # days a bare month-day may sit in the past before it reads as next year


def infer_year(month, day, today, weekday=None):
    """Pick the year for a bare month-day.

    Default rule: this year, unless that puts it more than STALE_GRACE days in
    the past, in which case next year. An on-sale note two months old is stale
    data; one six months old is far more likely to be next year's.

    A weekday in the text beats the rule outright: "Fri Jul 31" resolves to 2026
    only because that day of that year actually falls on a Friday. That is real
    evidence rather than a heuristic, so it wins when present and unambiguous.
    """
    cands = []
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            cands.append(date(y, month, day))
        except ValueError:
            continue  # Feb 29 in a non-leap year
    if not cands:
        return None

    if weekday is not None:
        matching = [c for c in cands if c.weekday() == weekday]
        if len(matching) == 1:
            return matching[0]
        cands = matching or cands

    this_year = [c for c in cands if c.year == today.year]
    if this_year and (today - this_year[0]).days <= STALE_GRACE:
        return this_year[0]
    future = [c for c in cands if c >= today]
    if future:
        return min(future)
    return max(cands) if cands else None


def parse_watching_for(text, today):
    """-> (date, why) or (None, reason). Never raises.

    `why` is the matched substring, so the report can show what it read and a
    misparse is visible rather than silent.
    """
    t = (text or "").strip()
    if not t or t == "-":
        return None, "empty"

    m = _ISO.search(t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(0)
        except ValueError:
            return None, "malformed ISO date"

    if not _ONSALE_CUE.search(t):
        return None, "no on-sale cue"

    m = _MONTH_DAY.search(t)
    if not m:
        return None, "on-sale but no date given"

    # [:3] folds "sept" to "sep" and "thurs" to "thu" without a special case.
    dow, mon, day = m.group(1), m.group(2)[:3].lower(), int(m.group(3))
    if mon not in _MONTHS:
        return None, "unrecognised month"
    wd = _WEEKDAYS.get(dow.lower()[:3]) if dow else None
    d = infer_year(_MONTHS.index(mon) + 1, day, today, wd)
    return (d, m.group(0)) if d else (None, "impossible date")


def read_tsv(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh, delimiter="\t")]


def blank(v):
    v = (v or "").strip()
    return not v or v == "-"


def build(today, potential=None, current=None):
    pot = read_tsv(potential or POTENTIAL)
    cur = read_tsv(current or CURRENT)
    purchased = {((r.get("Show Date") or "")[:10], (r.get("Artist") or "").strip())
                 for r in cur}

    out = {"onsale_soon": [], "onsale_passed": [], "buy_aging": [],
           "choose_deciding": [], "missing_fields": [],
           "watching_for_unparsed": [], "today": today.isoformat()}

    for r in pot:
        dec = (r.get("Decision") or "").strip()
        if dec not in ("Buy", "Choose"):
            continue
        artist = (r.get("Artist") or "").strip()
        show = (r.get("Date") or "")[:10]
        venue = (r.get("Venue") or "").strip()
        link = next((r.get(c) for c in ("Purchase URL", "Event URL", "BIT URL")
                     if not blank(r.get(c))), "")
        base = {"artist": artist, "date": show, "decision": dec,
                "venue": venue, "link": (link or "").strip()}

        wf = (r.get("Watching For") or "").strip()
        d, why = parse_watching_for(wf, today)
        if d:
            if today <= d <= today + timedelta(days=ONSALE_WINDOW):
                out["onsale_soon"].append(dict(base, onsale=d.isoformat(), read=why))
            elif d < today:
                out["onsale_passed"].append(dict(base, onsale=d.isoformat(), read=why))
        elif wf and why not in ("empty",):
            out["watching_for_unparsed"].append(dict(base, text=wf, reason=why))

        try:
            sd = date.fromisoformat(show)
        except ValueError:
            sd = None

        if sd and dec == "Buy" and today <= sd <= today + timedelta(days=BUY_WINDOW) \
                and (show, artist) not in purchased:
            out["buy_aging"].append(dict(base, days=(sd - today).days))

        if sd and dec == "Choose" and today <= sd <= today + timedelta(days=CHOOSE_WINDOW):
            out["choose_deciding"].append(dict(base, days=(sd - today).days))

        gaps = [label for label, col in (("price", "Face Price"),
                                         ("purchase URL", "Purchase URL"),
                                         ("event URL", "Event URL"))
                if blank(r.get(col))]
        if gaps:
            out["missing_fields"].append(dict(base, gaps=gaps))

    for k in ("onsale_soon", "onsale_passed"):
        out[k].sort(key=lambda x: x["onsale"])
    for k in ("buy_aging", "choose_deciding", "missing_fields"):
        out[k].sort(key=lambda x: x["date"])
    return out


ACTION_SECTIONS = ("onsale_soon", "onsale_passed", "buy_aging",
                   "choose_deciding", "missing_fields")


def render(d):
    """Empty string when nothing needs attention - the caller sends no mail."""
    if not any(d[k] for k in ACTION_SECTIONS):
        return ""

    out = ["POTENTIALS DIGEST  %s" % d["today"], "=" * 62]

    def section(title, rows, fmt):
        if not rows:
            return
        out.append("")
        out.append("%s (%d)" % (title, len(rows)))
        out.append("-" * 62)
        for r in rows:
            out.append("  " + fmt(r))
            if r.get("link"):
                out.append("      %s" % r["link"])

    section("On-sale in the next %d days" % ONSALE_WINDOW, d["onsale_soon"],
            lambda r: "%s  %s - %s at %s" % (r["onsale"], r["decision"],
                                             r["artist"], r["venue"]))
    section("On-sale passed, row still open", d["onsale_passed"],
            lambda r: "%s  %s - %s at %s (show %s)" % (r["onsale"], r["decision"],
                                                       r["artist"], r["venue"],
                                                       r["date"]))
    section("Buy rows with no purchase recorded", d["buy_aging"],
            lambda r: "%s  %s at %s - %d days out" % (r["date"], r["artist"],
                                                      r["venue"], r["days"]))
    section("Choose rows inside %d days" % CHOOSE_WINDOW, d["choose_deciding"],
            lambda r: "%s  %s at %s - %d days to decide" % (r["date"], r["artist"],
                                                            r["venue"], r["days"]))
    section("Missing price or link", d["missing_fields"],
            lambda r: "%s  %s - %s at %s - missing %s" % (
                r["date"], r["decision"], r["artist"], r["venue"],
                ", ".join(r["gaps"])))

    if d["watching_for_unparsed"]:
        out.append("")
        out.append("Watching For, not read as a date (%d)"
                   % len(d["watching_for_unparsed"]))
        out.append("-" * 62)
        for r in d["watching_for_unparsed"]:
            out.append("  %s - %s" % (r["artist"], r["reason"]))
            out.append("      %s" % r["text"][:100])

    out.append("")
    out.append("--")
    out.append("Read-only: nothing here has been changed. Calendar conflicts are "
               "not checked - that stays in session.")
    return "\n".join(out)


def main():
    try:
        import signal
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (ImportError, AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--today", help="YYYY-MM-DD, for testing")
    ap.add_argument("--potential", help="override the potentials TSV path")
    ap.add_argument("--current", help="override the current-shows TSV path")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    today = date.fromisoformat(args.today) if args.today else date.today()
    d = build(today,
              Path(args.potential) if args.potential else None,
              Path(args.current) if args.current else None)

    if args.json:
        d["action_count"] = sum(len(d[k]) for k in ACTION_SECTIONS)
        print(json.dumps(d, indent=2, ensure_ascii=False))
        return 0

    text = render(d)
    if text:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
