#!/usr/bin/env python3
"""
websrc_diff.py - month-over-month triage of the web-src scrapes.

Answers the question the monthly Workflow 1-A pass exists to answer: of everything
that appeared in this month's scrapes, what is new, what is already tracked, and
what is worth a tier decision.

Reads committed files only. No network, no writes - this is a report.

WHY THIS EXISTS
---------------
HereForTheBands puts an entire bill in its Artist column:

    Willow Avalon, Tiffany Stringer, Macy Todd
    Cheekface, Apes Of The State
    Nino Paid, It's All Temporary Tour, with 1up Tee

Joining that against the tracking files on the raw cell only ever hits when a
tracked artist happens to headline alone. Measured on the 2026-09 export, over
all rows: the naive join finds 20 tracked artists, the tokenized join finds 43.
Restricted to acts new since the prior month, where the triage value actually
is, the gap is 1 against 9. Nothing about the tracking data changed between
those numbers - the join was asking the wrong question. The failure is silent,
and it suppresses openers specifically, which is where most of the discovery
value is.

The same asymmetry exists on the other side of the join: potentials rows are
often filed under a billing name rather than an artist name ("Allman Betts
Family Revival" carries Larry McCray and Devon Allman; Taylor Ashton appears
only as a Support-column value). So the Support column is part of the join, and
potentials names are tokenized too.

Run from anywhere:
    python3 tools/research/websrc_diff.py
    python3 tools/research/websrc_diff.py --month 2026-09 --prior 2026-08
    python3 tools/research/websrc_diff.py --source hftb --json

HOW THIS IS CHECKED
-------------------
Two mechanisms, neither of which involves a synthetic corpus.

The name-handling rules - acts(), key(), keys_of() - are pure string functions
and carry doctests, sitting next to the prose that justifies each rule:

    python3 -m doctest tools/research/websrc_diff.py

The rest is checked against the real data on every run. check_invariants()
hard-fails rather than printing a number to be eyeballed, because the failures
this tool is prone to all look like plausible output: an empty roster reads as
"no matches", and a broken tokenizer reads as "nothing new is tracked". A wrong
answer that exits 0 is the thing to prevent.

The issue history behind these designs is logged in docs/ISSUE_LOG.md.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from name_forms import norm as _norm, surface_forms  # noqa: E402  (path set above)

WEBSRC = ROOT / "tools" / "research" / "web-src"
ARCHIVE = ROOT / "tools" / "archive"

HFTB_PAT = "rhbl-hereforthebands-dc-%s.tsv"
BIT_PAT = "rhbl-bandsintown-dc-recommends-%s.tsv"

TRACKING = {
    "current":    ROOT / "data" / "live_shows_current.tsv",
    "potential":  ROOT / "data" / "live_shows_potential.tsv",
    "fast_track": ROOT / "data" / "fast_track.tsv",
    "follows":    ROOT / "tools" / "research" / "follows" / "follows_master.tsv",
    "NAR":        ROOT / "tools" / "research" / "follows" / "new_artist_research.tsv",
    "artists":    ROOT / "data" / "artists.tsv",
}

ROSTERS = {
    "Alligator": WEBSRC / "alligator_records_artists.tsv",
    "Ruf":       WEBSRC / "ruf_records_artists.tsv",
}

# Normalized venue fragments. Matched as substrings of the normalized venue cell
# because the two sources spell the same room differently - HereForTheBands says
# "The Hamilton", Bandsintown says "The Hamilton Live", and Jammin Java shows up
# as "Music School At Jammin Java".
CORE_VENUES = [
    "birchmere", "hamilton", "jammin java", "pearl street", "9 30 club",
    "union stage", "barns at wolf trap", "filene center", "state theatre",
    "lincoln theatre", "strathmore", "rams head on stage", "howard theatre",
    "hylton", "collective encore",
]

# Bill separators. Commas and the "with"/"w/" family only.
#
# NOT "&" or "and": in this data every ampersand sits inside a band name
# ("Robert Randolph & The Family Band", "JJ Grey & Mofro", "The War and
# Treaty"), so splitting on it would shatter real acts and manufacture
# nonsense tokens. name_forms.bill_components() does split on & / and / with
# and is therefore wrong here - it answers a different question, for the goal
# badges, where over-splitting is cheap and a miss is not.
BILL_SPLIT = re.compile(r",|\bwith\b|\bw/|\+", re.I)

# Tokens that describe an event rather than name a performer. Word-boundary
# anchored on purpose: a bare "night" substring would eat "The Nighthawks".
NOISE = re.compile(
    r"\b(tour|presents?|showcase|tribute|celebrat\w*|residency|festival|night|"
    r"album release|record release|anniversary|feat)\b", re.I)

PARENTHETICAL = re.compile(r"\([^()]*\)")
QUOTES = re.compile(r"[\"'\u2018\u2019\u201c\u201d]")


def key(s):
    """Normalization key shared by every join in this file.

    name_forms.norm() is the repo's one index normalizer; the only addition is
    folding "&" to "and" first, so "The War and Treaty" and "War & Treaty" land
    on the same key. norm() strips punctuation rather than expanding it, which
    would otherwise leave those two a word apart.

    >>> key("The War and Treaty") == key("War & Treaty")
    True
    >>> key("Ana Popovic")
    'ana popovic'
    """
    return _norm((s or "").replace("&", " and "))


def keys_of(s):
    """Every identity key one name can legitimately be spelled under.

    Runs the repo's surface_forms expansion (de-invert "X, The", drop a trailing
    " Band") through key(). Without it a scrape billing "Robert Cray" misses the
    tracking row filed as "Robert Cray Band" and reports a long-tracked artist as
    an untracked discovery.

    Identity only. surface_forms never splits a bill - that is acts() above, and
    the two must not be confused (see name_forms.py).

    >>> sorted(keys_of("Robert Cray Band"))
    ['robert cray', 'robert cray band']
    >>> sorted(keys_of("Lone Bellow, The"))
    ['lone bellow', 'lone bellow the']
    """
    return {k for k in (key(f) for f in surface_forms(s)) if k}


def acts(bill):
    """Individual performer names inside a bill string, normalization aside.

    A plain artist name yields itself. Returns a list in bill order so callers
    can report which component matched.

    An ampersand is part of the name, never a separator:

    >>> acts("Shovels & Rope")
    ['Shovels & Rope']

    A comma is a separator, and "night" must not eat a band called Nighthawks:

    >>> acts("Cheekface, The Nighthawks")
    ['Cheekface', 'The Nighthawks']

    Tour and event labels are dropped, the acts around them kept:

    >>> acts("Nino Paid, It's All Temporary Tour, with 1up Tee")
    ['Nino Paid', '1up Tee']

    A trailing parenthetical is not part of the name:

    >>> acts("Yola (DJ set)")
    ['Yola']
    """
    bill = (bill or "").strip()
    if not bill:
        return []
    out, seen = [], set()
    for part in BILL_SPLIT.split(bill):
        part = QUOTES.sub("", PARENTHETICAL.sub(" ", part)).strip(" -.:")
        if len(part) < 3 or NOISE.search(part):
            continue
        k = key(part)
        if k and k not in seen:
            seen.add(k)
            out.append(part)
    return out


def read_rows(path):
    if not path.exists():
        return []
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return []
    header = lines[0].split("\t")
    rows = []
    for ln in lines[1:]:
        cells = ln.split("\t")
        rows.append({h.strip(): (cells[i].strip() if i < len(cells) else "")
                     for i, h in enumerate(header)})
    return rows


def find_scrape(pattern, month):
    """Current month lives in web-src; the prior month has usually been archived."""
    for base in (WEBSRC, ARCHIVE):
        p = base / (pattern % month)
        if p.exists():
            return p
    return None


def latest_month(pattern):
    months = []
    for base in (WEBSRC, ARCHIVE):
        for p in base.glob(pattern % "*"):
            m = re.search(r"(\d{4}-\d{2})\.tsv$", p.name)
            if m:
                months.append(m.group(1))
    return max(months) if months else None


def prior_month(month):
    y, m = (int(x) for x in month.split("-"))
    return "%04d-%02d" % (y - 1, 12) if m == 1 else "%04d-%02d" % (y, m - 1)


def load_scrape(source, month):
    """-> list of {acts: [...], venue, date, bill}."""
    pattern, artist_col, venue_col = (
        (HFTB_PAT, "Artist", "Venue") if source == "hftb"
        else (BIT_PAT, "Artist", "Venue/Event"))
    path = find_scrape(pattern, month)
    if path is None:
        return None, None
    out = []
    for r in read_rows(path):
        bill = r.get(artist_col, "")
        # Bandsintown rows name a single artist; only HereForTheBands packs a bill.
        components = acts(bill) if source == "hftb" else ([bill] if bill else [])
        out.append({"bill": bill, "acts": components,
                    "venue": r.get(venue_col, ""), "date": r.get("Date", "")})
    return out, path


def load_tracking():
    """{normalized name -> {'name': display, 'files': set()}} across the six files.

    Potentials contribute their Support column as well as Artist, and both are
    tokenized: a tracked artist filed only as part of a billing string would
    otherwise read as untracked forever.
    """
    index = {}

    def add(raw, fname):
        for name in (acts(raw) or ([raw] if raw else [])):
            slot = None
            for k in keys_of(name):
                slot = index.setdefault(k, slot or {"name": name.strip(),
                                                    "files": set()})
            if slot is not None:
                slot["files"].add(fname)

    for fname, path in TRACKING.items():
        for r in read_rows(path):
            add(r.get("Artist", ""), fname)
            if fname == "potential":
                add(r.get("Support", ""), fname)
    return index


def raw_tracking_keys():
    """Artist cells only, untokenized - the join this tool exists to replace.

    Kept solely to feed the diagnostic. Never use it for matching.
    """
    return {key(r.get("Artist", "")) for path in TRACKING.values()
            for r in read_rows(path) if r.get("Artist", "")} - {""}


def load_rosters():
    """{normalized artist -> [label, ...]} from the label roster exports.

    These files head their first column "Artist Name", not "Artist" like every
    other source here, and Ruf suffixes a country ("Albert Castiglia (USA)").
    Reading the wrong header silently yields an empty roster and reports every
    artist as a non-match, which reads identically to a real negative result.
    That is why a roster file that exists but parses to nothing is a hard error
    here rather than a warning: "no blues-label artists are playing this month"
    and "I could not read the roster" must never look the same in the output.
    A roster that is simply absent is a legitimate state and only warns.
    """
    out = {}
    for label, path in ROSTERS.items():
        if not path.exists():
            print("WARN: roster %s absent - skipping %s" % (path.name, label),
                  file=sys.stderr)
            continue
        rows = read_rows(path)
        parsed = 0
        for r in rows:
            raw = r.get("Artist Name") or r.get("Artist") or ""
            raw = PARENTHETICAL.sub("", raw).strip()
            if not raw or "/" in raw:  # "Various Artists/Anthologies" is not an act
                continue
            parsed += 1
            for k in keys_of(raw):
                if label not in out.setdefault(k, []):
                    out[k].append(label)
        if parsed == 0:
            raise SystemExit(
                "FATAL: roster %s exists but parsed 0 artists. Expected an "
                "'Artist Name' or 'Artist' column; found %s. Refusing to report "
                "zero label hits from a roster that was not read."
                % (path.name, rows[0].keys() if rows else "no rows"))
    return out


def is_core(venue):
    v = key(venue)
    return any(frag in v for frag in CORE_VENUES)


def analyse(month, prior, sources):
    tracking = load_tracking()
    rosters = load_rosters()
    result = {"month": month, "prior": prior, "sources": {}, "missing": []}

    scrapes, present = {}, {}
    for src in sources:
        rows, path = load_scrape(src, month)
        if rows is None:
            result["missing"].append("%s %s" % (src, month))
            continue
        prev, _ = load_scrape(src, prior)
        scrapes[src] = rows
        present[src] = {"path": str(path.relative_to(ROOT)),
                        "rows": len(rows),
                        "prior_rows": len(prev) if prev else 0,
                        "prior_found": prev is not None}
        prior_keys = {key(a) for r in (prev or []) for a in r["acts"]}
        cur = {}
        for r in rows:
            for a in r["acts"]:
                cur.setdefault(key(a), {"name": a, "shows": []})["shows"].append(
                    "%s, %s" % (r["venue"], r["date"]))
        present[src]["acts"] = len(cur)
        present[src]["new"] = sorted(k for k in cur if k not in prior_keys)
        present[src]["_cur"] = cur

    result["sources"] = {k: {kk: vv for kk, vv in v.items() if kk != "_cur"}
                         for k, v in present.items()}

    # Diagnostic that motivated the script. Compares the join this tool performs
    # against the naive one it replaces, so a refactor that quietly reverts the
    # tokenizer shows up as a collapsing number rather than a silent miss.
    if "hftb" in scrapes:
        naive_tracking = raw_tracking_keys()
        naive = {key(r["bill"]) for r in scrapes["hftb"]} & naive_tracking
        toks = {a for r in scrapes["hftb"] for a in r["acts"]
                if keys_of(a) & set(tracking)}
        result["join_diagnostic"] = {
            "naive": len(naive), "tokenized": len(toks),
            "bills_split": sum(1 for r in scrapes["hftb"] if len(r["acts"]) > 1),
        }

    all_keys = {}
    for src, info in present.items():
        for k, v in info["_cur"].items():
            slot = all_keys.setdefault(k, {"name": v["name"], "sources": set(),
                                           "shows": [], "new_in": set()})
            slot["sources"].add(src)
            slot["shows"].extend(v["shows"])
            if k in set(info["new"]):
                slot["new_in"].add(src)

    tracked, corroborated, single_core, label_hits = [], [], [], []
    for k, v in sorted(all_keys.items(), key=lambda kv: kv[1]["name"].lower()):
        entry = {"name": v["name"], "sources": sorted(v["sources"]),
                 "shows": v["shows"][:4]}
        hit = next((tracking[kk] for kk in keys_of(v["name"]) if kk in tracking),
                   None)
        if hit:
            if v["new_in"]:
                entry["files"] = sorted(hit["files"])
                entry["new_in"] = sorted(v["new_in"])
                tracked.append(entry)
            continue
        labels = next((rosters[kk] for kk in keys_of(v["name"]) if kk in rosters),
                      None)
        if labels:
            label_hits.append(dict(entry, labels=labels))
        if len(v["sources"]) > 1:
            corroborated.append(entry)
        elif v["new_in"] and any(is_core(s.split(", ")[0]) for s in v["shows"]):
            # New only. Without that filter this is every act that has ever played
            # a core room - around 750 names, which is a catalogue, not a triage list.
            single_core.append(entry)

    result["tracked_new"] = tracked
    result["untracked_corroborated"] = corroborated
    result["untracked_single_source_core_venue"] = single_core
    result["label_roster_hits"] = label_hits
    return result


def check_invariants(res):
    """Conditions that must hold on real data. Returns a list of failures.

    These are not unit tests; they run against the month's actual scrapes every
    time. Each one guards a failure mode that produces believable output rather
    than an error, which is the only kind worth an automatic check here.
    """
    problems = []
    d = res.get("join_diagnostic")
    if d:
        if d["bills_split"] == 0:
            problems.append(
                "tokenizer split no HereForTheBands bill into multiple acts. "
                "That source always carries multi-act bills, so the tokenizer "
                "is a no-op and every join below is understated.")
        if d["tokenized"] < d["naive"]:
            problems.append(
                "tokenized join (%d) found fewer tracked artists than the naive "
                "join (%d). Tokenizing can only widen the match, so this means "
                "the tracking index is being built differently from the scrape "
                "side." % (d["tokenized"], d["naive"]))
    for src, info in res["sources"].items():
        if info["prior_found"] and info["prior_rows"] and not info["rows"]:
            problems.append(
                "%s: current month is empty but the prior month had %d rows - "
                "the scrape almost certainly failed rather than the calendar "
                "being empty." % (src, info["prior_rows"]))
    return problems


def render(res):
    out = []
    add = out.append
    add("web-src diff  %s vs %s" % (res["month"], res["prior"]))
    add("=" * 62)
    for src, info in res["sources"].items():
        prior_note = "" if info["prior_found"] else "  (no prior file found)"
        add("%-6s %-52s" % (src, info["path"]))
        add("       %d rows, %d distinct acts, %d new vs prior (%d rows)%s"
            % (info["rows"], info["acts"], len(info["new"]),
               info["prior_rows"], prior_note))
    for m in res["missing"]:
        add("MISSING: no scrape found for %s" % m)

    d = res.get("join_diagnostic")
    if d:
        add("")
        add("Bill-tokenization check (HereForTheBands, all rows):")
        add("  naive join, raw cells both sides   : %d tracked artists" % d["naive"])
        add("  tokenized join, this tool          : %d tracked artists" % d["tokenized"])

    def section(title, items, show_files=False):
        add("")
        add("%s (%d)" % (title, len(items)))
        add("-" * 62)
        if not items:
            add("  none")
            return
        for e in items:
            tag = "+".join(e["sources"])
            extra = ("  [" + ",".join(e["files"]) + "]") if show_files and e.get("files") else ""
            if e.get("labels"):
                extra += "  [" + "+".join(e["labels"]) + "]"
            add("  %-38s %-14s%s" % (e["name"][:38], tag, extra))
            for s in e["shows"][:2]:
                add("      %s" % s)

    section("Already tracked, new this month", res["tracked_new"], show_files=True)
    section("Untracked, corroborated in both sources", res["untracked_corroborated"])
    section("Untracked, single source, core venue, new this month",
            res["untracked_single_source_core_venue"])
    section("Untracked, on a blues label roster", res["label_roster_hits"])
    return "\n".join(out)


def main():
    # This report is long and will be piped to head or less; a broken pipe is the
    # normal way that ends, not an error worth a traceback.
    try:
        import signal
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (ImportError, AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--month", help="YYYY-MM (default: latest scrape present)")
    ap.add_argument("--prior", help="YYYY-MM to compare against (default: month - 1)")
    ap.add_argument("--source", choices=["hftb", "bit", "both"], default="both")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    month = args.month or latest_month(BIT_PAT) or latest_month(HFTB_PAT)
    if not month:
        print("no scrapes found under %s" % WEBSRC, file=sys.stderr)
        return 2
    prior = args.prior or prior_month(month)
    sources = ["hftb", "bit"] if args.source == "both" else [args.source]

    res = analyse(month, prior, sources)

    problems = check_invariants(res)
    if problems:
        for p in problems:
            print("FATAL: %s" % p, file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
