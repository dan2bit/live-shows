#!/usr/bin/env python3
"""
audit_goal_badges.py

Enumerates every show row whose goal badges (#140) depend on bill-name decomposition or on
the support column, i.e. every row where the *exact* normalized join against the eligibility
files fails but a bill component or a support act matches.

Why this exists (#150): row badges join the row's `Artist` string against the goal
eligibility/signature files. Rows billed under a compound or variant name ("Victor Wooten &
The Wooten Brothers", "Maggie Rose Band") don't match the tracked entity they're keyed on
("The Wooten Brothers", "Maggie Rose"), and support acts were never joined at all. app.js
now falls back to bill components (`_goalBillKeys`) and badges support acts
(`supportGoalNames`); this script is the fixture that enumerates what that fallback is
carrying, so a new compound booking can be eyeballed for a wrong credit instead of being
found by accident.

Third check (#154): a forward-looking row (potential / upcoming) must not advertise a goal
that has already been obtained. The eligibility files answer "does this artist meet the
criteria?", not "do I still need this autograph?", so eligible-and-already-signed is the
regression to watch — those rows must render no `planned` badge.

bill_keys() below is the Python twin of `_goalBillKeys` in app.js — keep the two in step.
The trailing-" Band" drop mirrors surface_forms() in build_recommend_index.py.

Exit status:
  default   0 always (report mode; every finding is a row the fallback legitimately rescues)
  --strict  1 if there are any findings (for wiring into CI once the current set is reviewed)
"""

import argparse
import csv
import glob
import os
import re
import sys
import unicodedata

ROOT = "."
GOAL_FILES = [
    # (label, eligibility file, eligible-column candidates)
    ("BOOK", "data/show_goals/autograph_books_eligibility.tsv", ("Eligible", "Book Eligible")),
    ("HAT", "data/show_goals/hat_eligibility.tsv", ("Eligible", "Hat Eligible")),
]

# Explicit separators only — no fuzzy matching (#150 non-goal). Mirrors _GOAL_BILL_SEP in app.js.
BILL_SEP = re.compile(r"\s+(?:&|and his|and her|and|w/|feat\.?|featuring|with)\s+|\s*,\s*", re.I)
TRAILING_BAND = re.compile(r"\s+band$", re.I)
PLUS_MORE = re.compile(r"\s*\+\s*\d*\s*more\s*$", re.I)


def norm(s):
    """Twin of _goalNorm() in app.js: de-invert "X, The", de-accent, drop a leading article,
    strip punctuation, collapse whitespace."""
    if not s:
        return ""
    s = str(s).strip()
    m = re.match(r"^(.*),\s+(the|a|an)$", s, re.I)
    if m:
        s = m.group(2) + " " + m.group(1)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"^\s*(the|a|an)\s+", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def bill_keys(name):
    """Twin of _goalBillKeys() in app.js. Exact key first, then component fallbacks."""
    base = norm(name)
    keys = [base] if base else []
    if not name:
        return keys
    for part in BILL_SEP.split(str(name)):
        part = (part or "").strip()
        if not part:
            continue
        for variant in (part, TRAILING_BAND.sub("", part).strip()):
            k = norm(variant)
            if k and k not in keys:
                keys.append(k)
    return keys


def support_names(raw):
    """Support column: " / "-separated, optional trailing "+ more" (as artistNames does)."""
    raw = PLUS_MORE.sub("", (raw or "").strip())
    return [p.strip() for p in raw.split(" / ") if p.strip()]


def read_tsv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def load_eligibility():
    """{goal_label: {norm_key: display_name}} for artists marked eligible."""
    out = {}
    for label, path, cols in GOAL_FILES:
        table = {}
        for r in read_tsv(os.path.join(ROOT, path)):
            artist = (r.get("Artist") or "").strip()
            if not artist:
                continue
            val = ""
            for c in cols:
                if r.get(c):
                    val = r[c]
                    break
            if val.strip().lower() == "yes":
                table[norm(artist)] = artist
        out[label] = table
    return out


def load_signed():
    """{goal_label: {norm_key: [dates]}} — every artist with a signature, any date.
    Mirrors _goalCreditTargets in app.js: the signer, plus the band named in an "of X"
    attribution."""
    out = {}
    for label, _, _ in GOAL_FILES:
        table = {}
        fname = "hat_signatures.tsv" if label == "HAT" else "book_signatures.tsv"
        for r in read_tsv(os.path.join(ROOT, "data/show_goals", fname)):
            signer = (r.get("signer") or "").strip()
            attr = (r.get("attribution") or "").strip()
            date = (r.get("show_date") or "").strip()
            targets = [signer] if signer else []
            m = re.match(r"^of\s+(.*)$", attr, re.I)
            if m:
                targets.append(m.group(1).strip())
            for t in targets:
                k = norm(t)
                if k:
                    table.setdefault(k, []).append(date)
        out[label] = table
    return out


def load_rows():
    """(source, artist, support, date) across potentials + current + history."""
    rows = []
    for r in read_tsv(os.path.join(ROOT, "data/live_shows_potential.tsv")):
        rows.append(("potential", r.get("Artist", ""), r.get("Support", ""), r.get("Date", "")))
    for r in read_tsv(os.path.join(ROOT, "data/live_shows_current.tsv")):
        src = "upcoming" if (r.get("Status") or "").strip().lower() == "upcoming" else "current"
        rows.append((src, r.get("Artist", ""), r.get("Supporting Artist", ""), r.get("Show Date", "")))
    for path in sorted(glob.glob(os.path.join(ROOT, "data/history/*.tsv"))):
        for r in read_tsv(path):
            rows.append((os.path.basename(path), r.get("Artist", ""), r.get("Support", ""), r.get("Show Date", "")))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true", help="exit 1 if there are any findings")
    args = ap.parse_args()

    elig = load_eligibility()
    signed = load_signed()
    rows = load_rows()

    bill_findings = []
    support_findings = []
    signed_findings = []
    FORWARD = ("potential", "upcoming")

    for src, artist, support, date in rows:
        if artist:
            keys = bill_keys(artist)
            exact, comps = keys[0] if keys else "", keys[1:]
            for label, table in elig.items():
                if table.get(exact):
                    continue  # exact join already badges this row
                for c in comps:
                    if table.get(c):
                        bill_findings.append((src, artist, date, label, table[c]))
                        break  # first component wins per goal

        for name in support_names(support):
            hits = [label for label, table in elig.items()
                    if any(table.get(k) for k in bill_keys(name))]
            if hits:
                support_findings.append((src, artist, date, name, "+".join(sorted(hits))))

        # #154 — a forward-looking row must not advertise a goal already obtained. Eligibility
        # means "meets the criteria", not "still needed", so eligible-and-already-signed is the
        # regression to watch: these must render no `planned` badge.
        if src in FORWARD:
            for name in ([artist] if artist else []) + support_names(support):
                keys = bill_keys(name)
                for label, table in elig.items():
                    if not any(table.get(k) for k in keys):
                        continue
                    hit = next((k for k in keys if signed[label].get(k)), None)
                    if hit:
                        dates = sorted(set(d for d in signed[label][hit] if d))
                        signed_findings.append((src, artist, date, name, label, dates))

    print(f"Goal-badge join audit — {len(rows)} rows scanned\n")

    print(f"Bill-name rows rescued by component fallback: {len(bill_findings)}")
    for src, artist, date, label, via in bill_findings:
        print(f"  [{src}] {artist} ({date})")
        print(f"      +{label} via component -> eligibility row {via!r}")

    print(f"\nSupport acts carrying goal badges: {len(support_findings)}")
    for src, artist, date, name, labels in support_findings:
        print(f"  [{src}] {artist} ({date}) -> {name}: {labels}")

    print(f"\nForward-looking rows eligible for an ALREADY-OBTAINED goal "
          f"(must render no 'planned' badge — #154): {len(signed_findings)}")
    for src, artist, date, name, label, dates in signed_findings:
        print(f"  [{src}] {artist} ({date}) -> {name}: {label} already signed {', '.join(dates)}")

    total = len(bill_findings) + len(support_findings)
    print(f"\n{total} finding(s). Review each: a component match should always be an artist who "
          f"genuinely fronts or belongs to that bill.")

    if args.strict and total:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
