#!/usr/bin/env python3
"""
release_digest.py - report what the release sweep actually found.

`spotify_cache.py --refresh-releases` already detects new releases. It just
prints them as one line among hundreds:

    [51/325] D.K. Harrell  -> 2025-09-15 (unchanged)
    [52/325] Dale Ann Bradley  -> 2023-06-23 (unchanged)
    [53/325] Daniel Donato  -> 2026-06-26  (was 2026-05-15)
    [54/325] Danielle Nicole  -> 2026-05-22 (unchanged)

There is no end-of-run summary, so a sweep that finds three new records looks
identical to one that finds none. This renders the difference.

    python3 scripts/release_digest.py
    python3 scripts/release_digest.py --before old.json --after new.json
    python3 scripts/release_digest.py --json

With no arguments it compares the working copy of the cache against the version
committed at HEAD, which is exactly the state a CI sweep leaves behind: the
script has flushed, nothing is committed yet.

NO EXTRA API CALLS. Every field reported here - title, type, Spotify link - is
already pulled and cached by `latest_release()` on every run and then discarded
at display time. This is rendering, not collection, which matters against a
Dev-mode app that is already rate-limit constrained.

WHAT COUNTS AS A HIT

The sweep produces several kinds of line and only one is interesting:

  old -> new, new is later    a genuine new release. This is the hit.
  (unchanged)                 the overwhelming majority. Silent.
  null -> date                first-ever population. Suppressed by default:
                              genuine on a settled cache, pure noise during
                              backfill. --include-first turns it on.
  date -> null                null pull. The sweep keeps the old value and does
                              not re-check. Not a hit.
  date regressed              already warned on stderr by the sweep. A data
                              quality signal, not a release announcement.
  no spotify_id, skipped      not a hit, but worth counting.

A hit cannot be reported twice: the comparison is cached-vs-pulled and the
cache is written on the same pass, so the next run sees `unchanged`. Each
release announces itself exactly once.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "artist_spotify.json"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_head(rel):
    """The committed version of a file, without touching the working tree."""
    try:
        out = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=ROOT,
                             capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise SystemExit(
            f"FATAL: could not read HEAD:{rel} ({e}). Pass --before explicitly "
            f"if this is not a git checkout.")
    return json.loads(out.stdout)


def rel_of(entry):
    return (entry or {}).get("latest_release") or {}


def diff(before, after, include_first=False):
    hits, counts = [], {
        "checked": 0, "unchanged": 0, "no_spotify_id": 0,
        "regressed": 0, "null_pull": 0, "first_seen_suppressed": 0,
    }

    for name, new in sorted(after.items(), key=lambda kv: kv[0].lower()):
        old = before.get(name, {})
        if not new.get("spotify_id"):
            counts["no_spotify_id"] += 1
            continue

        # "Checked this run" is derivable: the sweep stamps the date whenever it
        # actually pulls. Without this, a run that skipped most of the cache
        # under --stale-days looks the same as one that walked all of it.
        if new.get("latest_release_checked") != old.get("latest_release_checked"):
            counts["checked"] += 1

        nr, orr = rel_of(new), rel_of(old)
        nd, od = nr.get("date"), orr.get("date")

        if not nd:
            counts["null_pull"] += 1
            continue
        if not od:
            if include_first and name in before:
                hits.append((name, None, nr))
            else:
                counts["first_seen_suppressed"] += 1
            continue
        if nd == od:
            counts["unchanged"] += 1
            continue
        if nd < od:
            counts["regressed"] += 1
            continue
        hits.append((name, od, nr))

    return hits, counts


def render(hits, counts):
    out = []
    if not hits:
        out.append("No new releases.")
    else:
        out.append("NEW RELEASES (%d)" % len(hits))
        out.append("=" * 62)
        for name, old_date, r in hits:
            kind = r.get("type") or "release"
            title = r.get("name") or "(untitled)"
            out.append("")
            out.append('%s - %s - "%s"' % (name, kind, title))
            out.append("  %s -> %s" % (old_date or "first seen", r.get("date")))
            if r.get("url"):
                out.append("  %s" % r["url"])
    out.append("")
    out.append("--")
    out.append("%d checked this run - %d unchanged - %d no spotify_id"
               % (counts["checked"], counts["unchanged"], counts["no_spotify_id"]))
    extra = []
    if counts["first_seen_suppressed"]:
        extra.append("%d first-seen suppressed" % counts["first_seen_suppressed"])
    if counts["regressed"]:
        extra.append("%d regressed" % counts["regressed"])
    if counts["null_pull"]:
        extra.append("%d null pull" % counts["null_pull"])
    if extra:
        out.append(" - ".join(extra))
    return "\n".join(out)


def main():
    # Piped to head or less like any report; a broken pipe is the normal way
    # that ends, not an error worth a traceback.
    try:
        import signal
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (ImportError, AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--before", help="cache JSON to compare against "
                                     "(default: the version committed at HEAD)")
    ap.add_argument("--after", help="cache JSON to report on "
                                    "(default: data/artist_spotify.json)")
    ap.add_argument("--include-first", action="store_true",
                    help="also report entries whose latest_release went from "
                         "null to a date (noisy during backfill)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    after = load(args.after) if args.after else load(CACHE)
    before = load(args.before) if args.before else load_head(
        str(CACHE.relative_to(ROOT)))

    hits, counts = diff(before, after, args.include_first)

    if args.json:
        print(json.dumps({
            "count": len(hits),
            "counts": counts,
            "releases": [{"artist": n, "previous": o, **r} for n, o, r in hits],
        }, indent=2, ensure_ascii=False))
    else:
        print(render(hits, counts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
