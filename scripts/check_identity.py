#!/usr/bin/env python3
"""
check_identity.py - the artist-identity checks: data lint and synthetic self-tests
of the resolver in name_forms.py.

WHAT IT CHECKS
  lint       data/artist_relations.tsv and data/bill_annotations.tsv:
               - vocabulary (Kind, Role, Shape, Status) and required cells
               - every annotation joins a bill entry on its date: the headliner
                 cell or one support entry. A confirmed row must join a show that
                 happened; an assumed row may join an upcoming current row.
             Warnings (never fail the run):
               - an assumed row whose Review After date has passed
               - a hand-keyed map name (tools/map/pins.json, the builder's
                 HARBORMISTRESSES set) that is not the canonical name of its
                 identity. Those keys are matched raw, so they will stop
                 matching the day the map resolves names through the resolver.
  selftest   synthetic worlds built in memory, so the resolver's rules are pinned
             without restating live data (which would need upkeep every time the
             ledger grows): the derived default and its split after a solo
             appearance, ambiguity, trailing components, eponymous acts,
             annotation credits, member-of, not-an-artist, explicit targets.

Exit status: 1 if any lint error or self-test failure; else 0.

Run:  python3 scripts/check_identity.py [--root .]
"""

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import name_forms as nf  # noqa: E402  (sibling module in scripts/)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------- lint
def _bill_entries(bills):
    out = {}
    for date, head, sup in bills:
        for name in [head] + list(sup):
            out.setdefault(date, set()).add(nf.identity_key(name))
    return out


def lint(root, errors, warnings, today=None):
    today = today or dt.date.today().isoformat()
    rel_path = Path(root) / nf.RELATIONS_PATH
    ann_path = Path(root) / nf.ANNOTATIONS_PATH

    if rel_path.exists():
        for i, r in enumerate(nf.read_relations(root), start=2):
            where = "%s row %d (%s)" % (nf.RELATIONS_PATH, i, r["name"])
            if r["kind"] not in nf.RELATION_KINDS:
                errors.append("%s: Kind %r is not one of %s" % (where, r["kind"], ", ".join(nf.RELATION_KINDS)))
            if r["kind"] in ("same-as", "member-of") and not r["target"]:
                errors.append("%s: %s needs a Target" % (where, r["kind"]))
            if r["kind"] == "not-an-artist" and r["target"]:
                errors.append("%s: not-an-artist takes no Target (use '-')" % where)

    if not ann_path.exists():
        return
    happened = _bill_entries(nf.ledger_bills(root))
    upcoming = _bill_entries(nf.upcoming_bills(root))
    for i, a in enumerate(nf.read_annotations(root), start=2):
        where = "%s row %d (%s, %s)" % (nf.ANNOTATIONS_PATH, i, a["date"], a["act"])
        if not DATE_RE.match(a["date"]):
            errors.append("%s: Show Date must be YYYY-MM-DD" % where)
        if a["role"] not in nf.ANNOTATION_ROLES:
            errors.append("%s: Role %r is not one of %s" % (where, a["role"], ", ".join(nf.ANNOTATION_ROLES)))
        if a["shape"] not in nf.ANNOTATION_SHAPES:
            errors.append("%s: Shape %r is not one of %s" % (where, a["shape"], ", ".join(nf.ANNOTATION_SHAPES)))
        if a["role"] == "principal" and a["shape"] == "-":
            errors.append("%s: a principal row needs a Shape" % where)
        if a["status"] not in nf.ANNOTATION_STATUSES:
            errors.append("%s: Status %r is not one of %s" % (where, a["status"], ", ".join(nf.ANNOTATION_STATUSES)))
        if a["review_after"] and not DATE_RE.match(a["review_after"]):
            errors.append("%s: Review After must be YYYY-MM-DD or '-'" % where)
        bk = nf.identity_key(a["billing"])
        joined = bk in happened.get(a["date"], set())
        if not joined and a["status"] == "assumed":
            joined = bk in upcoming.get(a["date"], set())
        if not joined:
            errors.append("%s: Billing %r matches no headliner or support entry on that date"
                          % (where, a["billing"]))
        if a["status"] == "assumed" and a["review_after"] and a["review_after"] < today:
            warnings.append("%s: still assumed after its Review After date %s - confirm or correct it"
                            % (where, a["review_after"]))


def map_keys(root):
    """Hand-keyed settlement names in the map: pins.json keys and HARBORMISTRESSES."""
    root = Path(root)
    keys = []
    pins = root / "tools" / "map" / "pins.json"
    if pins.exists():
        keys += [("pins.json", k) for k in json.loads(pins.read_text(encoding="utf-8"))]
    builder = root / "tools" / "map" / "build_fantasy_map.py"
    if builder.exists():
        m = re.search(r"^HARBORMISTRESSES\s*=\s*\{(.*?)\}", builder.read_text(encoding="utf-8"), re.S | re.M)
        if m:
            keys += [("HARBORMISTRESSES", k) for k in re.findall(r'"([^"]+)"', m.group(1))]
    return keys


def lint_map_keys(root, resolver, warnings):
    for where, k in map_keys(root):
        c = resolver.canonical(k)
        if c and c != k:
            warnings.append("%s key %r is not canonical (resolves to %r); it is matched raw and will "
                            "orphan when the map resolves names through ArtistResolver" % (where, k, c))


# ------------------------------------------------------------------- helpers
def _credit_set(resolver, date, billing):
    return sorted("%s:%s" % (resolver.canonical(a["act"]) or a["act"], a["role"])
                  for a in resolver.credits(date, billing))


# ------------------------------------------------------------------ selftest
def selftest(failures):
    def world(**kw):
        base = dict(names=[], appearances=[], aliases=[], relations=[], annotations=[])
        base.update(kw)
        return nf.ArtistResolver(**base)

    def expect(label, got, want):
        if got != want:
            failures.append("selftest %s: expected %r, got %r" % (label, want, got))

    # derived default, then split back out by a solo appearance
    w = world(names=["Nick Lowe", "Nick Lowe & Los Straitjackets"],
              appearances=["Nick Lowe & Los Straitjackets"])
    expect("derived default folds", w.canonical("Nick Lowe"), "Nick Lowe & Los Straitjackets")
    w = world(names=["Nick Lowe", "Nick Lowe & Los Straitjackets"],
              appearances=["Nick Lowe & Los Straitjackets", "Nick Lowe"])
    expect("solo appearance splits", w.canonical("Nick Lowe"), "Nick Lowe")

    # two candidate acts: ambiguous, stays split
    w = world(names=["Kim Wilson", "Kim Wilson Blues Revue", "Kim Wilson & Friends"],
              appearances=["Kim Wilson Blues Revue", "Kim Wilson & Friends"])
    expect("ambiguous stays split", w.canonical("Kim Wilson"), "Kim Wilson")

    # a trailing component is never a leader
    w = world(names=["The Example Brothers", "Solo Example & The Example Brothers"],
              appearances=["Solo Example & The Example Brothers"])
    expect("trailing component stays", w.canonical("The Example Brothers"), "The Example Brothers")

    # eponymous act: plain name attested -> person's name; not attested -> band name
    w = world(names=["Ann Example Band", "Ann Example"], appearances=["Ann Example Band"] * 5)
    expect("eponymous with plain attested", w.canonical("Ann Example Band"), "Ann Example")
    w = world(names=["The Example Band"], appearances=["The Example Band"])
    expect("band name without a plain form", w.canonical("The Example Band"), "The Example Band")

    # an annotation principal has an appearance of its own, so it never folds into the billing
    ann = [{"date": "2099-01-01", "billing": "Ann Example & Bo Sample", "act": a, "role": "principal",
            "shape": "joint-set", "status": "confirmed", "review_after": "", "notes": ""}
           for a in ("Ann Example", "Bo Sample")]
    w = world(names=["Ann Example & Bo Sample", "Ann Example", "Bo Sample"],
              appearances=["Ann Example & Bo Sample"], annotations=ann)
    expect("annotated principal stays", w.canonical("Ann Example"), "Ann Example")
    expect("credits", _credit_set(w, "2099-01-01", "Ann Example & Bo Sample"),
           ["Ann Example:principal", "Bo Sample:principal"])

    # explicit targets win, and member-of folds like same-as
    rel = [{"name": "Mando Example", "kind": "member-of", "target": "Example Duo", "notes": ""},
           {"name": "Example Tribute Night", "kind": "not-an-artist", "target": "", "notes": ""}]
    w = world(names=["Mando Example", "Example Duo", "Example Tribute Night"],
              appearances=["Example Duo", "Mando Example"], relations=rel)
    expect("member-of", w.canonical("Mando Example"), "Example Duo")
    expect("not-an-artist", w.is_non_artist("Example Tribute Night"), True)

    # a derived fold into a group with an explicit target keeps that target
    w = world(names=["Lead Example", "Lead Example & Crew", "Crew Tour Name"],
              appearances=["Lead Example & Crew"],
              aliases=[("Lead Example & Crew", "Lead Example Crew")])
    expect("derived fold keeps alias target", w.canonical("Lead Example"), "Lead Example Crew")

    # a bill with no annotation credits nobody beyond the ledger's own reading
    counts = {}
    for d in ("2099-01-01", "2099-02-01"):
        for a in w.credits(d, "none"):
            counts[a["act"]] = counts.get(a["act"], 0) + 1
    expect("no credits for an unannotated bill", counts, {})


# ---------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=".")
    args = ap.parse_args()

    errors, warnings, failures = [], [], []
    lint(args.root, errors, warnings)
    resolver = nf.ArtistResolver.from_repo(args.root)
    lint_map_keys(args.root, resolver, warnings)
    selftest(failures)

    for w in warnings:
        print("warning: " + w)
    for e in errors:
        print("error: " + e)
    for f in failures:
        print("FAIL: " + f)
    print("identity: %d lint errors, %d self-test failures, %d warnings"
          % (len(errors), len(failures), len(warnings)))
    if resolver.derived:
        print("derived default folds: " + "; ".join(
            "%s -> %s" % (a, resolver.canonical(a)) for a, _t in resolver.derived))
    return 1 if (errors or failures) else 0


if __name__ == "__main__":
    sys.exit(main())
