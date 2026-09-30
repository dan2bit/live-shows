#!/usr/bin/env python3
"""
check_identity.py - the artist-identity checks: data lint, the shared fixture, and
synthetic self-tests of the resolver in name_forms.py.

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
  fixture    scripts/fixtures/identity.tsv against the resolver, and against
             every consumer that has moved onto it (today: the artist modal
             index). Rows:
               canonical  Input resolves to Expect
               distinct   Input and Expect are different identities
               credit     "date|billing" credits exactly Expect ("act:role;...",
                          "-" for none)
  selftest   synthetic worlds built in memory, for the behaviour that live data
             cannot pin down without going stale (counts, the derived default
             splitting back out after a solo appearance).

Exit status: 1 if any lint error, fixture failure or self-test failure; else 0.

Run:  python3 scripts/check_identity.py [--root .] [--skip-consumers]
"""

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import name_forms as nf  # noqa: E402  (sibling module in scripts/)

FIXTURE = "scripts/fixtures/identity.tsv"
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


# ------------------------------------------------------------------- fixture
def read_fixture(root):
    return [r for r in nf._read_rows(Path(root) / FIXTURE) if r.get("Check")]


def _credit_set(resolver, date, billing):
    return sorted("%s:%s" % (resolver.canonical(a["act"]) or a["act"], a["role"])
                  for a in resolver.credits(date, billing))


def _expect_set(expect):
    return [] if expect in ("", "-") else sorted(p.strip() for p in expect.split(";") if p.strip())


def run_fixture_resolver(rows, resolver, failures):
    for r in rows:
        chk, inp, exp = r["Check"], r["Input"], r["Expect"]
        if chk == "canonical":
            got = resolver.canonical(inp)
            if got != exp:
                failures.append("resolver canonical %r: expected %r, got %r" % (inp, exp, got))
        elif chk == "distinct":
            if resolver.group(inp) & resolver.group(exp):
                failures.append("resolver distinct: %r and %r share an identity" % (inp, exp))
        elif chk == "credit":
            date, billing = inp.split("|", 1)
            got, want = _credit_set(resolver, date, billing), _expect_set(exp)
            if got != want:
                failures.append("resolver credit %s: expected %s, got %s" % (inp, want, got))
        else:
            failures.append("fixture: unknown Check %r" % chk)


def run_fixture_modal(rows, root, failures):
    """The artist modal index as a consumer: a name reaches the record for its identity."""
    import build_artist_index as bai
    idx = bai.build(root)
    artists, aliases = idx["artists"], idx["aliases"]

    def record(name):
        k = bai.norm(name)
        return artists.get(k) or artists.get(aliases.get(k, ""))

    for r in rows:
        chk, inp, exp = r["Check"], r["Input"], r["Expect"]
        if chk == "canonical":
            rec = record(inp)
            if rec is None:
                # a name with no record anywhere is fine; one whose identity HAS a record is not
                if record(exp) is not None:
                    failures.append("modal canonical %r: no record reached (expected %r)" % (inp, exp))
            elif rec["name"] != exp:
                failures.append("modal canonical %r: reached %r, expected %r" % (inp, rec["name"], exp))
        elif chk == "distinct":
            a, b = record(inp), record(exp)
            if a is not None and a is b:
                failures.append("modal distinct: %r and %r reach the same record" % (inp, exp))
        elif chk == "credit":
            date, _billing = inp.split("|", 1)
            for pair in _expect_set(exp):
                act, role = pair.rsplit(":", 1)
                rec = record(act)
                roles = {s.get("role") for s in (rec or {}).get("seen", {}).get("show_log", [])
                         if s["date"] == date}
                if role not in roles:
                    failures.append("modal credit %s: %r has no %s entry that day (roles %s)"
                                    % (date, act, role, sorted(r_ for r_ in roles if r_)))
    # a retired slug still reaches its record through the emitted aliases
    for r in rows:
        if r["Check"] == "canonical" and r["Input"] != r["Expect"]:
            target = record(r["Expect"])
            old = bai.slugify(r["Input"])
            if target and old and old != target["slug"]:
                if aliases.get(old.replace("-", " ")) != bai.norm(target["name"]):
                    failures.append("modal slug %r (from %r) does not redirect to %r"
                                    % (old, r["Input"], target["slug"]))


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
    ap.add_argument("--skip-consumers", action="store_true",
                    help="run the fixture against the resolver only")
    args = ap.parse_args()

    errors, warnings, failures = [], [], []
    lint(args.root, errors, warnings)
    resolver = nf.ArtistResolver.from_repo(args.root)
    lint_map_keys(args.root, resolver, warnings)
    rows = read_fixture(args.root)
    run_fixture_resolver(rows, resolver, failures)
    if not args.skip_consumers:
        run_fixture_modal(rows, args.root, failures)
    selftest(failures)

    for w in warnings:
        print("warning: " + w)
    for e in errors:
        print("error: " + e)
    for f in failures:
        print("FAIL: " + f)
    print("identity: %d fixture rows, %d lint errors, %d failures, %d warnings"
          % (len(rows), len(errors), len(failures), len(warnings)))
    if resolver.derived:
        print("derived default folds: " + "; ".join(
            "%s -> %s" % (a, resolver.canonical(a)) for a, _t in resolver.derived))
    return 1 if (errors or failures) else 0


if __name__ == "__main__":
    sys.exit(main())
