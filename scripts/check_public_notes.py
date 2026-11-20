#!/usr/bin/env python3
"""check_public_notes.py - block private details in the public free-text cells.

The private-data guard stops private FILES from landing in this public repo.
It cannot see private CONTENT typed into a public cell: an order number in a
show note, a table and seat on an upcoming show, a calendar block's dates in a
Pass row. Those arrive one row at a time through receipt processing and the
in-page editor, and nothing else in the pipeline looks for them. This does.

What is private, and where (the rule lives in tools/playbooks/EMAIL_WORKFLOWS.md):

  order      order / confirmation references            every scanned cell
  block      a calendar block's label, dates or reason  every scanned cell
  tickets    ticket counts, transfers, resale, payouts  current + history notes
  channel    presale / gift card / who bought it        current notes
  money      a dollar amount                            current + history notes
  seat       table, seat, section, row, box, tier       UPCOMING rows only

Seat detail is private only while a show is upcoming; once it is attended,
where the seat was is a memory and may be explicit. A Pass row may name the
show it conflicts with - that show is already public - but a calendar block is
only ever "Calendar block conflict".

Deliberately not scanned: the potentials Face Price and Fees Notes columns
(listing prices for shows not bought), and the history YT Title column (video
titles, where "$1000000" is a song).

Output never repeats the offending text. CI logs for this repo are public, so
echoing a match would publish it a second time; a finding names the file, the
row key, the column and the rule, and the reader opens the row.

Modes:
  (default)  warn only, exit 0.
  --strict   exit 1 if anything is found. Optionally scoped: --strict FILE...
             judges only those files.
  --self-test  run the built-in synthetic cases and exit.

Exceptions go in data/public_notes_allow.tsv (File, Key, Rule, Reason): a
deliberate exception is recorded there rather than the rule being loosened.

    >>> rules_hit("Order ID 1234567AB. Great band.", ("order",))
    ['order']
    >>> rules_hit("Vantage: front table. Rail for the encore.", ("order", "money", "tickets"))
    []
    >>> rules_hit("Table 12, Seat 3.", ("seat",))
    ['seat']
    >>> rules_hit("Falls in a calendar block; calendar checked.", ("block",))
    []
    >>> rules_hit("inside the Feb 3-9 block (out of town)", ("block",))
    ['block']
    >>> rules_hit("Some Other Band calendar conflict", ("block",))
    []
"""

import argparse
import csv
import glob
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOW_TSV = REPO_ROOT / "data" / "public_notes_allow.tsv"

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
_MD = r"(?:%s \d{1,2})" % _MONTH

RULES = {
    # A reference word followed by a marker or a reference-shaped token. The
    # bare word "order" passes ("pre-order", "in order to").
    "order": re.compile(
        r"\b(?:order|confirmation|conf|booking|transaction)\b\.?\s*(?:#|no\.|number\b|id\b|code\b)\s*:?\s*[A-Za-z0-9]"
        r"|\b(?:order|confirmation)\s+[A-Za-z0-9/-]*\d[A-Za-z0-9/-]{4,}",
        re.I),
    # The calendar's own label, a stated reason, or a date tied to the word
    # "block" on either side. "calendar block" alone is the allowed wording.
    "block": re.compile(
        r"NO SHOWS"
        r"|\bout of town\b|\bspring break\b|\bbeach week\b|\bon vacation\b|\btravel(?:l?ing)? block\b"
        # a date range ahead of the word: "the Feb 3-9 block"
        r"|%s(?:,? \d{4})?\s*(?:-|to|through)\s*(?:%s|\d{1,2})\b[^.;]{0,30}\bblock\b"
        r"|\b(?:conflict|block)\b[^.;]{0,20}\d{4}-\d{2}-\d{2} (?:to|through) \d{4}-\d{2}-\d{2}"
        # a single date qualifying it: "the Jun 2 calendar block"
        r"|%s(?:,? \d{4})?\s+(?:calendar\s+)?block\b"
        # what follows it: "block (Jun 2, 2030)", "block starts the next day"
        r"|\bblock\s*\([^)]*\d[^)]*\)|\bblock\s+(?:starts|ends|begins|runs)\b" % (_MD, _MD, _MD),
        re.I),
    "tickets": re.compile(
        r"\b\d+-ticket\b|\(\d+ tickets?\)|\b\d+ of \d+ tickets?\b"
        r"|\btransferred\b|\bresold\b|\bresale\b|\bpayout\b|\bstubhub\b|\bbartered\b|\brefund",
        re.I),
    "channel": re.compile(
        r"\bpresale\b|\bgift card\b|\bpurchased by\b|\bbought by\b|\bpaid (?:by|with)\b|\bvenmo\b"
        r"|\bper (?:the )?receipt\b",
        re.I),
    "money": re.compile(r"\$\s?\d"),
    "seat": re.compile(
        r"\btable\s+[A-Z]?\d+\b|\bseats?\s+[A-Z]?\d+"
        # Letter codes are matched case-sensitively, so "front row at" and
        # "a section of the crowd" pass while "Row K" and "Section ABC2" do not.
        r"|\bsection\s+(?-i:[A-Z0-9]*[A-Z0-9]\d[A-Z0-9]*|[A-Z]{2,}\d*)\b|\bsec\.?\s+(?-i:[A-Z0-9]{2,})\b"
        r"|\brow\s+(?-i:[A-Z]{1,2})\b|\brow\s+\d+\b|\bbox(?:es)?\s+\d+|\b\d(?:st|nd|rd|th) floor box"
        r"|\bGA Gold\b|\bADV GA\b|\bpremier seating\b",
        re.I),
}

EVERY = ("order", "block")

# file glob -> (key columns, status column or None, {column: rules for every row},
#               {column: extra rules for upcoming rows only})
SCOPES = [
    ("data/live_shows_current.tsv", ("Show Date", "Artist"), "Status",
     {"Notes / Memories": EVERY + ("tickets", "channel", "money"),
      "Ticket Access": EVERY + ("tickets", "money")},
     {"Notes / Memories": ("seat",), "Ticket Access": ("seat",)}),
    ("data/history/*.tsv", ("Show Date", "Artist"), None,
     {"Notes / Memories": EVERY + ("tickets", "money")}, {}),
    ("data/live_shows_potential.tsv", ("Artist", "Date"), None,
     {"Notes": EVERY, "Availability Notes": EVERY, "Watching For": EVERY}, {}),
    ("tools/research/follows/new_artist_research.tsv", ("Artist",), None,
     {"Signal": EVERY, "Overview & Niche": EVERY, "USA Touring": EVERY, "Source": EVERY}, {}),
]


def rules_hit(text, rule_names):
    """Names of the rules in `rule_names` that `text` trips, in RULES order."""
    return [name for name in RULES if name in rule_names and RULES[name].search(text or "")]


def load_allow():
    """{(file, key, rule)} from the allowlist; a missing file allows nothing."""
    allowed = set()
    if not ALLOW_TSV.is_file():
        return allowed
    with open(ALLOW_TSV, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            allowed.add(((row.get("File") or "").strip(), (row.get("Key") or "").strip(),
                         (row.get("Rule") or "").strip()))
    return allowed


def scan_file(rel, key_cols, status_col, every_row, upcoming_only, allowed):
    """Findings for one file as (rel, line number, key, column, rule)."""
    findings = []
    path = REPO_ROOT / rel
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE))
    if not rows:
        return findings
    header = rows[0]
    index = {name: i for i, name in enumerate(header)}
    for line_no, row in enumerate(rows[1:], start=2):
        def cell(name):
            i = index.get(name)
            return row[i] if i is not None and i < len(row) else ""
        key = " | ".join(cell(c) for c in key_cols)
        upcoming = status_col is not None and cell(status_col).strip().lower() == "upcoming"
        for column in sorted(set(every_row) | set(upcoming_only)):
            names = tuple(every_row.get(column, ()))
            if upcoming:
                names += tuple(upcoming_only.get(column, ()))
            for rule in rules_hit(cell(column), names):
                if (rel, key, rule) in allowed:
                    continue
                findings.append((rel, line_no, key, column, rule))
    return findings


def scan(only=None):
    allowed = load_allow()
    findings = []
    for pattern, key_cols, status_col, every_row, upcoming_only in SCOPES:
        for path in sorted(glob.glob(str(REPO_ROOT / pattern))):
            rel = str(Path(path).relative_to(REPO_ROOT))
            if only and rel not in only:
                continue
            findings.extend(scan_file(rel, key_cols, status_col, every_row, upcoming_only, allowed))
    return findings


WHY = {
    "order": "an order or confirmation reference",
    "block": "a calendar block's label, dates or reason (write 'calendar block' only)",
    "tickets": "a ticket count, transfer or resale detail",
    "channel": "a purchase-channel detail (presale, gift card, who paid)",
    "money": "a dollar amount",
    "seat": "a seat location or ticket tier on an upcoming show",
}


def self_test():
    cases = [
        ("Confirmation #9990001 (TestTix).", ("order",), ["order"]),
        ("Order zzTEST00SAMPLE1 (TestTix).", ("order",), ["order"]),
        ("only for pre-order on Bandcamp", ("order",), []),
        ("a lower-confidence curiosity pick", ("order",), []),
        ("Order ID TESTID1234 (TestTix)", ("order",), ["order"]),
        ("calendar conflict 2030-06-02 to 2030-06-04", ("block",), ["block"]),
        ("checked 2030-01-05 - Feb 3 2030 falls in a calendar block", ("block",), []),
        ("the Feb 3-9 2030 block", ("block",), ["block"]),
        ("the Jun 2 calendar block", ("block",), ["block"]),
        ("newsletters 2030-01-05 to 2030-01-07", ("block",), []),
        ("block starts the next day", ("block",), ["block"]),
        ("NO SHOWS calendar conflict", ("block",), ["block"]),
        ("Calendar block conflict", ("block",), []),
        ("the Jun 2-4 block ends the Saturday before", ("block",), ["block"]),
        ("outside a calendar block", ("block",), []),
        ("keyboard blocked the view", ("block",), []),
        ("4-ticket table order", ("tickets",), ["tickets"]),
        ("one ticket already transferred", ("tickets",), ["tickets"]),
        ("standard ticket", ("tickets",), []),
        ("venue presale", ("channel",), ["channel"]),
        ("$20 at the door", ("money",), ["money"]),
        ("Section ABC2, Row K, Seats 5-6", ("seat",), ["seat"]),
        ("Vantage: 3rd row stage right", ("seat",), []),
        ("front row at the club", ("seat",), []),
        ("ADV GA Gold Seated", ("seat",), ["seat"]),
    ]
    bad = [(t, want, rules_hit(t, names)) for t, names, want in cases if rules_hit(t, names) != want]
    for text, want, got in bad:
        print("self-test FAILED: %r wanted %s got %s" % (text, want, got))
    print("self-test: %d cases, %d failed." % (len(cases), len(bad)))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--strict", nargs="*", metavar="FILE", default=None,
                    help="exit 1 on any finding; with FILE arguments, judge only those files")
    ap.add_argument("--self-test", action="store_true", help="run the synthetic cases and exit")
    args = ap.parse_args()
    if args.self_test:
        sys.exit(self_test())

    only = set(args.strict) if args.strict else None
    findings = scan(only)
    level = "error" if args.strict is not None else "warning"
    for rel, line_no, key, column, rule in findings:
        print("::%s file=%s,line=%d::%s [%s] holds %s" % (level, rel, line_no, key, column, WHY[rule]))
    if findings:
        print("check_public_notes: %d finding(s). The matched text is not shown here on purpose - "
              "open the row. Move the detail to the private sidecar, or record a deliberate "
              "exception in %s." % (len(findings), ALLOW_TSV.relative_to(REPO_ROOT)))
        sys.exit(1 if args.strict is not None else 0)
    print("check_public_notes: clean.")


if __name__ == "__main__":
    main()
