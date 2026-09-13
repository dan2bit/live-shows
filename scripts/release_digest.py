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

The same goes for the tier / DMV-date join: `follows_master.tsv`,
`fast_track.tsv`, `artists.tsv` and the two show files are all committed files
already read by other scripts. A release from a followed artist is the strongest
leading indicator of a tour announcement this project has, and treating it as a
prompt rather than as news costs nothing.

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
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from name_forms import identity_keys  # noqa: E402  (path set above)

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "artist_spotify.json"

FOLLOWS = ROOT / "tools" / "research" / "follows" / "follows_master.tsv"
FAST_TRACK = ROOT / "data" / "fast_track.tsv"
ARTISTS = ROOT / "data" / "artists.tsv"
CURRENT = ROOT / "data" / "live_shows_current.tsv"
POTENTIAL = ROOT / "data" / "live_shows_potential.tsv"

# Sort order and the actionable test. fast-track outranks Strong: a fast-track
# artist is on the list precisely because their shows do not reliably surface in
# time, so a release from one is the most time-sensitive thing here.
TIER_RANK = {"fast-track": 0, "Strong": 1, "Medium-Strong": 2,
             "Medium": 3, "Lower": 4, "Low": 4}
ACTIONABLE_TIERS = {"fast-track", "Strong", "Medium-Strong"}


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


def read_tsv(path):
    """Header-keyed rows. Absent file yields none - a fork may lack any of these."""
    if not path.exists():
        return []
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return []
    header = [h.strip() for h in lines[0].split("\t")]
    out = []
    for ln in lines[1:]:
        cells = ln.split("\t")
        out.append({h: (cells[i].strip() if i < len(cells) else "")
                    for i, h in enumerate(header)})
    return out


def load_context():
    """(tier, dmv, tour) keyed on every identity form of each artist.

    Every lookup below goes through identity_keys(), never a raw string compare.
    Skipping the alias table makes long-tracked artists report as untracked - a
    wrong answer that reads like a finding rather than a bug.
    """
    tier, tour, dmv = {}, {}, {}

    for r in read_tsv(ARTISTS):
        seen = (r.get("Times Seen") or "").strip()
        if not r.get("Artist"):
            continue
        label = ("seen %s times, no follow row" % seen) if seen else "seen before, no follow row"
        for k in identity_keys(r["Artist"]):
            tier.setdefault(k, label)

    # follows_master then fast_track, each overriding the weaker statement above.
    for r in read_tsv(FOLLOWS):
        t = (r.get("Tier") or "").strip()
        if r.get("Artist") and t:
            for k in identity_keys(r["Artist"]):
                tier[k] = t

    for r in read_tsv(FAST_TRACK):
        if not r.get("Artist"):
            continue
        for k in identity_keys(r["Artist"]):
            tier[k] = "fast-track"
            if (r.get("Tour URL") or "").strip():
                tour[k] = r["Tour URL"].strip()

    today = date.today().isoformat()

    def note(keys, when, text):
        for k in keys:
            cur = dmv.get(k)
            if cur is None or when < cur[0]:
                dmv[k] = (when, text)

    for r in read_tsv(CURRENT):
        d = (r.get("Show Date") or "").strip()
        if r.get("Artist") and d >= today:
            note(identity_keys(r["Artist"]), d,
                 "%s at %s (purchased)" % (d, (r.get("Venue Name") or "?").strip()))

    # Pass and Sell rows are deliberately excluded: a passed show is not a date
    # you would act on, so reporting it as "the next DMV date" would suppress the
    # actionable flag on exactly the artist worth checking.
    for r in read_tsv(POTENTIAL):
        d = (r.get("Date") or "").strip()[:10]
        dec = (r.get("Decision") or "?").strip()
        if r.get("Artist") and d >= today and dec not in ("Pass", "Sell"):
            note(identity_keys(r["Artist"]), d,
                 "%s at %s (%s)" % (d, (r.get("Venue") or "?").strip(), dec))

    return tier, dmv, tour


def annotate(name, ctx):
    """-> dict of join context for one artist. Never raises on a miss.

    One artist can match SEVERAL keys with different values - "Lone Bellow, The"
    normalizes to both `lone bellow` (Strong, from follows_master) and
    `lone bellow the` (an artists.tsv sighting). Picking the first match off a set
    would make the answer depend on set iteration order, so every lookup here
    resolves deterministically: the strongest tier, the earliest date, and the
    first tour URL by sorted key.
    """
    tier_map, dmv_map, tour_map = ctx
    keys = identity_keys(name)

    tiers = [tier_map[k] for k in sorted(keys) if k in tier_map]
    t = min(tiers, key=lambda x: (TIER_RANK.get(x, 9), x)) if tiers else "untracked"

    dates = [dmv_map[k] for k in sorted(keys) if k in dmv_map]
    d = min(dates) if dates else None

    u = next((tour_map[k] for k in sorted(keys) if k in tour_map), None)
    return {
        "tier": t,
        "dmv": d[1] if d else None,
        "tour_url": u,
        "actionable": t in ACTIONABLE_TIERS and d is None,
        "_rank": (TIER_RANK.get(t, 9), (d[0] if d else "9999"), name.lower()),
    }


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


def render(hits, counts, ctx=None):
    out = []
    if not hits:
        out.append("No new releases.")
    else:
        n_act = sum(1 for n, _, _ in hits
                    if ctx and annotate(n, ctx)["actionable"]) if ctx else 0
        head = "NEW RELEASES (%d)" % len(hits)
        if n_act:
            head += " - %d worth a tour-page check" % n_act
        out.append(head)
        out.append("=" * 62)
        for name, old_date, r in hits:
            kind = r.get("type") or "release"
            title = r.get("name") or "(untitled)"
            out.append("")
            out.append('%s - %s - "%s"' % (name, kind, title))
            out.append("  %s -> %s" % (old_date or "first seen", r.get("date")))
            if r.get("url"):
                out.append("  %s" % r["url"])
            if ctx:
                a = annotate(name, ctx)
                out.append("  tier: %s - %s" % (a["tier"], a["dmv"] or "no DMV date on file"))
                if a["tour_url"]:
                    out.append("  tour: %s" % a["tour_url"])
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
    ap.add_argument("--no-join", action="store_true",
                    help="skip the tier / DMV-date join and report the raw diff")
    args = ap.parse_args()

    after = load(args.after) if args.after else load(CACHE)
    before = load(args.before) if args.before else load_head(
        str(CACHE.relative_to(ROOT)))

    hits, counts = diff(before, after, args.include_first)

    ctx = None if args.no_join else load_context()
    if ctx:
        # fast-track and Strong first, then by nearest DMV date, then by name.
        hits.sort(key=lambda h: annotate(h[0], ctx)["_rank"])

    if args.json:
        rels = []
        for n, o, r in hits:
            row = {"artist": n, "previous": o, **r}
            if ctx:
                a = annotate(n, ctx)
                row.update({k: a[k] for k in ("tier", "dmv", "tour_url", "actionable")})
            rels.append(row)
        print(json.dumps({
            "count": len(hits),
            "actionable": sum(1 for r in rels if r.get("actionable")),
            "counts": counts,
            "releases": rels,
        }, indent=2, ensure_ascii=False))
    else:
        print(render(hits, counts, ctx))
    return 0


if __name__ == "__main__":
    sys.exit(main())
