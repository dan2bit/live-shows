#!/usr/bin/env python3
"""
watch_diff.py - daily page-watch engine.

Replaces the changedetection.io pod (history in docs/ISSUE_LOG.md) for any page
that is plain-HTTP-fetchable - confirmed per site before it is ever added to the
registry, never assumed. Nothing here uses a browser or Playwright; a page that
needs one to render is explicitly out of scope for this file and stays on the
existing monthly interactive-Chrome pass instead.

    python3 tools/watch/watch_diff.py
    python3 tools/watch/watch_diff.py --force blues-alley
    python3 tools/watch/watch_diff.py --dry-run

WHAT "DUE" MEANS

The workflow runs daily; the registry (tools/watch/watches.tsv) decides which
rows actually get fetched that day. A row is due when today - last_checked >=
check_every_days, or last_checked is "-" (never checked). --force <slug> checks
one row regardless of its cadence and skips every other row - an off-cycle
check, not a full run.

TWO WATCH KINDS

  artist  a single-subject page (an artist's own tour page). Whole-page
          cleaned-text diff. Any change is relevant by construction - the page
          IS the subject, so a change always mails.

  venue   a multi-act listings page. Needs an extractor in extractors.py that
          turns the page into {date, title} event records, so the diff is a
          set difference on real bookings rather than a line diff. That is
          what keeps boilerplate (nav text, "Get Tickets", a bare status flip)
          from ever becoming a diffed record - it was never extracted as an
          event to begin with.

RELEVANCE (venue kind only - the taste-profile analysis the old pod never had)

Every added/removed event title is checked, cheapest signal first:
  1. exact/alias match against the six tracking files, via the same
     load_tracking() / keys_of() the weekly HFTB diff uses - always relevant,
     no network call.
  2. the extractor's own "offprofile" function, if it defines one - a fast,
     free negative signal from the source's own labeling.
  3. otherwise, score_candidates.py - the exact scoring engine HFTB uses
     (Last.fm + MusicBrainz, cached in data/candidate_cache.json), invoked by
     building a small diff JSON in the shape it already expects and calling it
     as a subprocess. One scoring implementation in the repo, not two.

A site mails only when at least one added/removed event scored relevant.
Every add/remove still lands in the job summary regardless of the mail
decision - scoring decides what reaches the inbox, never what a human can see
by looking.

NO-OP IF UNCHANGED

Fetch, extract/clean, compare to the committed snapshot. Identical -> update
last_checked only; no mail, no snapshot rewrite, no scoring call at all.
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "research"))
from websrc_diff import load_tracking, keys_of, read_rows  # noqa: E402

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "watches.tsv"
SNAPSHOTS = HERE / "snapshots"
SCORE_SCRIPT = ROOT / "tools" / "research" / "score_candidates.py"
MANIFEST_PATH = Path("/tmp/watch_mail_manifest.json")
MAIL_BODY_DIR = Path("/tmp/watch-mail")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

HEADER = ["slug", "name", "url", "kind", "check_every_days", "last_checked",
          "ignore_contains", "extractor", "active", "notes"]

EVENT_FLOOR = 3  # fewer than this from a venue-kind page reads as extractor drift, not a quiet calendar

TODAY = date.today()


def fetch(url, retries=3):
    # Accept both: an HTML tour page (Blues Alley) and a raw JSON API response
    # (a Seated widget's own cdn.seated.com/api/... endpoint, discovered by
    # inspecting network requests rather than fetching the wrapper page - see
    # tools/playbooks/skills/watch-manager/SKILL.md). Servers of either kind
    # generally ignore Accept and return their native format regardless, but
    # there is no reason to bias the header toward HTML only.
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json, text/html;q=0.9,*/*;q=0.8"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def write_registry(rows):
    with REGISTRY.open("w", encoding="utf-8") as f:
        f.write("\t".join(HEADER) + "\n")
        for r in rows:
            f.write("\t".join((r.get(h) or "-") for h in HEADER) + "\n")


def is_due(row, force_slug):
    if force_slug:
        return row["slug"] == force_slug
    if row.get("active", "Y") != "Y":
        return False
    lc = row.get("last_checked", "-")
    if lc in ("", "-"):
        return True
    try:
        days = int(row.get("check_every_days") or "1")
    except ValueError:
        days = 1
    try:
        return (TODAY - date.fromisoformat(lc)).days >= days
    except ValueError:
        return True  # unparseable last_checked reads as "never checked"


# ---- artist-kind: whole-page text diff -------------------------------------

def clean_lines(html_text, ignore_contains, extractor_name=None):
    """Default: visible_lines(). If the row names an extractor with a "lines"
    entry, use that instead - for an artist-kind site whose real signal is
    which image is referenced rather than any visible text (see
    extractors.image_urls). Unset/"-" (every row so far except one) is
    unaffected - this is purely additive."""
    if extractor_name and extractor_name != "-":
        from extractors import EXTRACTORS
        spec = EXTRACTORS.get(extractor_name)
        if spec and "lines" in spec:
            lines = spec["lines"](html_text)
        else:
            print("::warning::artist-kind row names extractor '%s' with no 'lines' entry - "
                  "falling back to visible_lines" % extractor_name)
            from extractors import visible_lines
            lines = visible_lines(html_text)
    else:
        from extractors import visible_lines
        lines = visible_lines(html_text)
    if ignore_contains and ignore_contains != "-":
        bad = [s.strip().lower() for s in ignore_contains.split("|") if s.strip()]
        lines = [ln for ln in lines if not any(b in ln.lower() for b in bad)]
    return lines


def process_artist(row):
    html_text = fetch(row["url"])
    new_lines = clean_lines(html_text, row.get("ignore_contains", "-"), row.get("extractor"))
    snap_path = SNAPSHOTS / ("%s.txt" % row["slug"])
    summary = ["%s: %d visible lines" % (row["name"], len(new_lines))]

    if not snap_path.exists():
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        summary.append("  no prior snapshot - baseline seeded, nothing to diff yet")
        return summary, None

    old_lines = snap_path.read_text(encoding="utf-8").splitlines()
    old_set, new_set = set(old_lines), set(new_lines)
    added = [ln for ln in new_lines if ln not in old_set]
    removed = [ln for ln in old_lines if ln not in new_set]
    if not added and not removed:
        summary.append("  unchanged")
        return summary, None

    body = []
    if added:
        body.append("ADDED")
        body.extend("  + " + ln for ln in added)
        body.append("")
    if removed:
        body.append("REMOVED")
        body.extend("  - " + ln for ln in removed)
        body.append("")
    summary.extend(body)

    snap_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return summary, {"subject": "[watch] %s" % row["name"],
                      "body": "\n".join(body).rstrip() + "\n"}


# ---- venue-kind: structured event diff -------------------------------------

def diff_events(old_events, new_events):
    def ekey(e):
        return (e["date"], e["title"].strip().lower())
    old_idx = {ekey(e): e for e in old_events}
    new_idx = {ekey(e): e for e in new_events}
    added = [e for k, e in new_idx.items() if k not in old_idx]
    removed = [e for k, e in old_idx.items() if k not in new_idx]
    return added, removed


def check_relevance(title, tracking, offprofile_fn):
    """-> (relevant: bool|None, reason: str). None means 'needs scoring'.

    A hit is relevant regardless of hit["files"] - that set can legitimately
    come back empty for a name with more than one surface-form key (e.g. a
    "... Band" suffix), a real nondeterminism in the shared
    websrc_diff.load_tracking() keyed to Python's per-process string hash
    seed. It does not change whether the artist is tracked, only whether the
    file-list annotation below can be shown - worth a fix upstream, not
    something to route around here.
    """
    hit_key = next((k for k in keys_of(title) if k in tracking), None)
    if hit_key:
        hit = tracking[hit_key]
        tag = ("[%s]" % ",".join(sorted(hit["files"]))) if hit["files"] else ""
        return True, ("tracked: %s %s" % (hit["name"], tag)).strip()
    if offprofile_fn and offprofile_fn(title):
        return False, "off-profile marker"
    return None, None


def score_titles(titles):
    """-> {title: (bucket, reason)} by reusing score_candidates.py as-is."""
    if not titles:
        return {}
    diff_obj = {"untracked_single_source_core_venue": [
        {"name": t, "sources": ["watch"], "shows": [], "labels": []} for t in titles
    ]}
    MAIL_BODY_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = MAIL_BODY_DIR / "score_input.json"
    tmp_path.write_text(json.dumps(diff_obj), encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(SCORE_SCRIPT), "--diff", str(tmp_path), "--json"],
            capture_output=True, text=True, timeout=180)
        # score_candidates.py's own warnings (e.g. LASTFM_API_KEY unset) print to
        # stderr on an otherwise-successful run - surface them either way, not
        # just on failure, or a degraded-but-"working" scoring pass goes unnoticed.
        if proc.stderr.strip():
            for line in proc.stderr.strip().splitlines():
                print(line)
        if proc.returncode != 0:
            print("::warning::score_candidates.py failed (rc=%d)" % proc.returncode)
            return {}
        out = json.loads(proc.stdout)
    except Exception as e:  # noqa: BLE001 - any failure here degrades to "unscored", never crashes the run
        print("::warning::scoring unavailable (%s) - treating as unscored" % e)
        return {}
    return {r["name"]: (r["bucket"], "score: %s" % r["bucket"]) for r in out.get("results", [])}


def process_venue(row, tracking):
    from extractors import EXTRACTORS
    spec = EXTRACTORS.get(row["extractor"])
    if not spec:
        print("::warning::%s: unknown extractor '%s' - skipping" % (row["slug"], row["extractor"]))
        return ["%s: SKIPPED - unknown extractor '%s'" % (row["name"], row["extractor"])], None

    html_text = fetch(row["url"])
    events = spec["extract"](html_text)
    summary = ["%s: parsed %d events" % (row["name"], len(events))]
    if len(events) < EVENT_FLOOR:
        print("::warning::%s: only %d events parsed - possible extractor drift, verify against the live page"
              % (row["slug"], len(events)))
        summary.append("  WARNING: suspiciously few events parsed - check the extractor")

    snap_path = SNAPSHOTS / ("%s.json" % row["slug"])
    if not snap_path.exists():
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text(json.dumps(events, indent=1, ensure_ascii=False), encoding="utf-8")
        summary.append("  no prior snapshot - baseline seeded, nothing to diff yet")
        return summary, None

    old_events = json.loads(snap_path.read_text(encoding="utf-8"))
    added, removed = diff_events(old_events, events)
    if not added and not removed:
        summary.append("  unchanged")
        return summary, None

    offprofile_fn = spec.get("offprofile")
    decisions = {}
    to_score = []
    for e in added + removed:
        rel, reason = check_relevance(e["title"], tracking, offprofile_fn)
        decisions[e["title"]] = [rel, reason]
        if rel is None:
            to_score.append(e["title"])

    for title, (bucket, reason) in score_titles(to_score).items():
        decisions[title] = [bucket in ("Strong fit", "Possible"), reason]

    body, any_relevant = [], False
    for label, group in (("ADDED", added), ("REMOVED", removed)):
        if not group:
            continue
        body.append(label)
        for e in group:
            rel, reason = decisions.get(e["title"], (False, "unscored"))
            any_relevant = any_relevant or bool(rel)
            line = "  %s %s - %s%s  (%s)" % (
                "[RELEVANT]" if rel else "[filtered]", e["date"], e["title"],
                (" [%s]" % e["status"]) if e.get("status") else "", reason)
            body.append(line)
            summary.append(line)
        body.append("")

    snap_path.write_text(json.dumps(events, indent=1, ensure_ascii=False), encoding="utf-8")

    if not any_relevant:
        summary.append("  changes found, none relevant - not mailed")
        return summary, None
    return summary, {"subject": "[watch] %s" % row["name"], "body": "\n".join(body).rstrip() + "\n"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--force", help="check this slug regardless of cadence; skip every other row")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would happen; write no registry/snapshot changes, "
                         "send no mail manifest")
    args = ap.parse_args()

    if not REGISTRY.exists():
        raise SystemExit("FATAL: %s not found" % REGISTRY)
    rows = read_rows(REGISTRY)
    if not rows:
        raise SystemExit("FATAL: %s has no rows" % REGISTRY)

    tracking = load_tracking()
    manifest = []
    report = ["## Daily page watch - %s" % TODAY.isoformat(), ""]
    any_due = False

    for row in rows:
        if not is_due(row, args.force):
            continue
        any_due = True
        try:
            if row["kind"] == "venue":
                lines, mail = process_venue(row, tracking)
            elif row["kind"] == "artist":
                lines, mail = process_artist(row)
            else:
                print("::warning::%s: unknown kind '%s' - skipping" % (row["slug"], row["kind"]))
                continue
        except Exception as e:  # noqa: BLE001 - one site's failure must not sink the run
            print("::warning::%s: check failed (%s) - last_checked left unchanged, retries next run"
                  % (row["slug"], e))
            report.append("%s: FAILED - %s" % (row["name"], e))
            report.append("")
            continue

        report.extend(lines)
        report.append("")

        if not args.dry_run:
            row["last_checked"] = TODAY.isoformat()

        if mail:
            if args.dry_run:
                report.append("  (dry-run: would mail '%s')" % mail["subject"])
            else:
                MAIL_BODY_DIR.mkdir(parents=True, exist_ok=True)
                body_path = MAIL_BODY_DIR / ("%s.txt" % row["slug"])
                body_path.write_text(mail["body"], encoding="utf-8")
                manifest.append({"slug": row["slug"], "subject": mail["subject"],
                                 "body_file": str(body_path)})

    if not any_due:
        report.append("no sites due today." if not args.force
                      else "'%s' not found in the registry." % args.force)

    print("\n".join(report))

    if not args.dry_run:
        write_registry(rows)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
