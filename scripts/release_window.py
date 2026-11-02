#!/usr/bin/env python3
"""
release_window.py - the month-end release window, computed in one place.

A "New Music <Month>" list picks releases dated inside that calendar month, up
through its last day. The list can only be built once every resolved artist in
data/artist_spotify.json has been checked late enough to see the month's last
releases, and Spotify's Dev-mode ceiling (about 100 calls a day for the whole
app) means a roster of 500+ needs several days of checks to get there. This
script says when that window is open, what --stale-days makes exactly the
not-yet-covered entries eligible, and, once the window completes, renders the
mail announcing that the month is ready to build.

Two workflows read it - the daily release sweep and the weekly new-artist
resolve - so the calendar maths lives here rather than in two copies of shell.

THE ANCHOR (the date every entry must be checked on or after)

    month ends Sat, Sun or Mon  ->  that month's last Friday
    month ends Tue .. Fri       ->  the last day of the month itself

Most releases land on a Friday and very few on a Saturday, Sunday or Monday, so
when the month ends one to three days after its last Friday, anchoring on the
Friday starts the window up to three days sooner and misses almost nothing. When
the month ends Tuesday to Thursday, four to six days have passed since the
Friday and the mid-week releases in between are worth catching, so the window
waits for the last day. A month ending on a Friday anchors on that Friday under
either reading.

THE WINDOW

Opens on the anchor and runs until nothing is pending, with a hard stop on the
WINDOW_END_DOM-th of the following month (an entry that keeps failing to stamp
would otherwise hold it open forever). Inside it, --stale-days is the number of
days since the anchor plus one, which leaves exactly the entries checked before
the anchor eligible.

PRIORITY AND SKIPS

The window checks artists in the order they are likely to have released, judged
from the two releases the cache keeps (latest_release, previous_release) as of
the anchor. Measured against four months of the cache's own history (July to
October 2026, 77 releases that only a window check found):

    tier 1  a single in the last 90 days           ~17% found something
    tier 2  a release in the last year              ~4%
    tier 3  last release one to two years ago       ~2%
    tier 4  last release two or more years ago      ~1.4%
    skip    an album already out this month          0 of 45
    skip    no release on Spotify at all             0 of 44

Tiers 1 and 2 hold about 84% of what the window finds, so checking them first
finds most of a month's late releases on the window's first days. Quiet artists
stay in, last: when they do release it is usually a full album with no single
ahead of it. The two skip groups are left out of the window and out of the
pending count; the daily trickle still reaches them, so a rare release from one
shows up within a few weeks rather than never.

USAGE

    release_window.py --env [--today YYYY-MM-DD]
        KEY=VALUE lines for `eval` in a workflow step:
        IN_WINDOW (true/false), MONTH (YYYY-MM of the month being closed),
        MONTH_NAME, ANCHOR, WINDOW_END, WINDOW_STALE_DAYS, WINDOW_LAST_DAY
        (true on the hard-stop day). MONTH and the rest describe the month
        whose window governs today even when IN_WINDOW is false.

    release_window.py --pending --month YYYY-MM
        Resolved entries still checked before that month's anchor, skip groups
        excluded, as a count. Local only; no API calls.

    release_window.py --plan --month YYYY-MM
        The same entries, one cache key per line, in priority order (tier, then
        oldest-checked first), for spotify_cache.py --names-from.

    release_window.py --report --month YYYY-MM
        The plain-text body of the "ready" mail: coverage, any entries still
        unchecked, and every cached release dated in the month (latest_release
        or previous_release), oldest first.

    release_window.py --self-test
        Synthetic checks of the calendar rules over two years of dates.
"""

import argparse
import calendar
import json
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE = REPO_ROOT / "data" / "artist_spotify.json"

WINDOW_END_DOM = 7          # hard stop: this day of the month after the one closing
FRIDAY = 4                  # date.weekday(): Monday=0 ... Sunday=6
FRIDAY_ANCHOR_EOM_DAYS = {5, 6, 0}   # month ends Sat, Sun, Mon -> anchor on Friday
SINGLE_RECENT_DAYS = 90     # tier 1: a single this recent
TIER_YEAR_DAYS = 365        # tier 2 bound
TIER_QUIET_DAYS = 730       # tier 3 bound; older is tier 4
SKIP_ALBUM = "album already out this month"
SKIP_NONE = "no release on Spotify"


def month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def last_friday(d: date) -> date:
    e = month_end(d)
    return e - timedelta(days=(e.weekday() - FRIDAY) % 7)


def anchor_for(d: date) -> date:
    """The date every entry must be checked on or after, for d's month."""
    e = month_end(d)
    return last_friday(d) if e.weekday() in FRIDAY_ANCHOR_EOM_DAYS else e


def window_end_for(d: date) -> date:
    e = month_end(d)
    return e + timedelta(days=WINDOW_END_DOM)


def governing_month(today: date) -> date:
    """First day of the month whose window applies today: the previous month
    through the WINDOW_END_DOM-th, the current month after that."""
    first = today.replace(day=1)
    if today.day <= WINDOW_END_DOM:
        return (first - timedelta(days=1)).replace(day=1)
    return first


def window(today: date) -> dict:
    m = governing_month(today)
    a = anchor_for(m)
    end = window_end_for(m)
    inside = a <= today <= end
    return {
        "IN_WINDOW": "true" if inside else "false",
        "MONTH": m.strftime("%Y-%m"),
        "MONTH_NAME": m.strftime("%B %Y"),
        "ANCHOR": a.isoformat(),
        "WINDOW_END": end.isoformat(),
        "WINDOW_STALE_DAYS": str((today - a).days + 1) if inside else "",
        "WINDOW_LAST_DAY": "true" if today == end else "false",
    }


def _month_start(spec: str) -> date:
    y, mo = spec.split("-")
    return date(int(y), int(mo), 1)


def _load_cache() -> dict:
    with open(CACHE, encoding="utf-8") as f:
        return json.load(f)


def _checked(entry: dict) -> date | None:
    c = entry.get("latest_release_checked")
    try:
        return date.fromisoformat(c[:10]) if c else None
    except ValueError:
        return None


def _rdate(r: dict) -> date | None:
    """A release's date, padded to the start of its period when partial."""
    parts = (r.get("date") or "").split("-")
    try:
        y = int(parts[0])
        mo = int(parts[1]) if len(parts) > 1 and parts[1] else 1
        dd = int(parts[2]) if len(parts) > 2 and parts[2] else 1
        return date(y, mo, dd)
    except (ValueError, IndexError):
        return None


def tier(entry: dict, m: date):
    """Priority tier 1-4 for month m's window, or a SKIP_* reason string."""
    a = anchor_for(m)
    rels = [r for r in (entry.get("latest_release"), entry.get("previous_release"))
            if isinstance(r, dict) and _rdate(r)]
    if not rels:
        return SKIP_NONE
    prefix = m.strftime("%Y-%m")
    if any((r.get("type") == "album") and (r.get("date") or "").startswith(prefix) for r in rels):
        return SKIP_ALBUM
    if any(r.get("type") == "single" and (a - _rdate(r)).days <= SINGLE_RECENT_DAYS for r in rels):
        return 1
    age = (a - max(_rdate(r) for r in rels)).days
    if age <= TIER_YEAR_DAYS:
        return 2
    if age <= TIER_QUIET_DAYS:
        return 3
    return 4


def _uncovered(cache: dict, m: date):
    """(name, entry) for resolved entries last checked before the anchor."""
    a = anchor_for(m)
    for name, e in cache.items():
        if not isinstance(e, dict) or not e.get("spotify_id"):
            continue
        c = _checked(e)
        if c is None or c < a:
            yield name, e


def pending(cache: dict, m: date) -> list:
    """Uncovered entries the window still owes a check, skip groups excluded."""
    return sorted(n for n, e in _uncovered(cache, m) if isinstance(tier(e, m), int))


def skipped(cache: dict, m: date) -> dict:
    """Uncovered entries the window leaves out, by skip reason."""
    out = {}
    for n, e in _uncovered(cache, m):
        t = tier(e, m)
        if not isinstance(t, int):
            out.setdefault(t, []).append(n)
    return {k: sorted(v) for k, v in out.items()}


def plan(cache: dict, m: date) -> list:
    """Pending names in check order: tier, then oldest-checked first, then name."""
    rows = [(tier(e, m), e.get("latest_release_checked") or "", n)
            for n, e in _uncovered(cache, m)]
    return [n for t, _, n in sorted(r for r in rows if isinstance(r[0], int))]


def releases_in(cache: dict, m: date) -> list:
    """(date, artist, release) for every cached release dated in month m.
    Month- or year-precision dates count only when they name this month."""
    prefix = m.strftime("%Y-%m")
    rows = []
    for name, e in cache.items():
        if not isinstance(e, dict):
            continue
        seen = set()
        for field in ("latest_release", "previous_release"):
            r = e.get(field)
            if not isinstance(r, dict):
                continue
            d = r.get("date") or ""
            if not d.startswith(prefix):
                continue
            key = r.get("spotify_id") or (d, r.get("name"))
            if key in seen:
                continue
            seen.add(key)
            rows.append((d, name, r))
    rows.sort(key=lambda t: (t[0], t[1].lower()))
    return rows


def report(cache: dict, m: date) -> str:
    a = anchor_for(m)
    e = month_end(m)
    resolved = sum(1 for v in cache.values() if isinstance(v, dict) and v.get("spotify_id"))
    unresolved = sum(1 for v in cache.values() if isinstance(v, dict) and not v.get("spotify_id"))
    left = pending(cache, m)
    lines = []
    month_name = m.strftime("%B %Y")
    if left:
        lines.append(f"The {month_name} window closed with {len(left)} of {resolved} "
                     f"resolved artists still unchecked since {a:%a %b %d}.")
        lines.append("Releases from these artists late in the month may be missing:")
        lines += [f"    {n}" for n in left]
    else:
        lines.append(f"All {resolved} resolved artists have been checked since "
                     f"{a:%a %b %d}, so the cache holds {month_name} through its last day.")
    if a < e:
        first = a + timedelta(days=1)
        span = f"{e:%b %d}" if first == e else f"{first:%b %d} to {e:%b %d}"
        lines.append(f"(Anchored on the last Friday: a release dated {span} is seen "
                     f"only for artists checked on or after its date.)")
    skips = skipped(cache, m)
    for reason, names in sorted(skips.items()):
        lines.append(f"{len(names)} artist(s) not re-checked ({reason}); "
                     f"the daily trickle still covers them.")
    if unresolved:
        lines.append(f"{unresolved} cache entries have no Spotify id and are not covered.")
    rel = releases_in(cache, m)
    lines.append("")
    lines.append(f"{len(rel)} release(s) dated in {month_name} "
                 f"(latest_release or previous_release):")
    for d, name, r in rel:
        kind = r.get("type") or "release"
        lines.append(f"  {d}  {name} - {r.get('name') or '?'} ({kind})")
        if r.get("url"):
            lines.append(f"              {r['url']}")
    return "\n".join(lines) + "\n"


def self_test() -> int:
    fails = 0
    d = date(2026, 1, 1)
    while d <= date(2027, 12, 31):
        w = window(d)
        m = _month_start(w["MONTH"])
        a = date.fromisoformat(w["ANCHOR"])
        e = month_end(m)
        # anchor is a Friday or the month's last day, and never later than it
        if not (a.weekday() == FRIDAY or a == e) or a > e or a.month != m.month:
            print("bad anchor", d, w); fails += 1
        # Friday anchor exactly when the month ends Sat/Sun/Mon (or on a Friday)
        want_fri = e.weekday() in FRIDAY_ANCHOR_EOM_DAYS or e.weekday() == FRIDAY
        if want_fri != (a == last_friday(m)):
            print("bad rule", d, w); fails += 1
        # stale-days leaves exactly the pre-anchor entries eligible
        if w["IN_WINDOW"] == "true":
            sd = int(w["WINDOW_STALE_DAYS"])
            if (d - a).days >= sd or (d - (a - timedelta(days=1))).days < sd:
                print("bad stale-days", d, w); fails += 1
        # the window covers anchor .. hard stop and nothing else
        inside = a <= d <= window_end_for(m)
        if inside != (w["IN_WINDOW"] == "true"):
            print("bad window", d, w); fails += 1
        d += timedelta(days=1)
    # a synthetic cache: pending and the month's releases
    m = date(2026, 10, 1)
    cache = {
        "Early": {"spotify_id": "a", "latest_release_checked": "2026-10-29",
                  "latest_release": {"date": "2026-10-09", "name": "X", "spotify_id": "1"}},
        "Late": {"spotify_id": "b", "latest_release_checked": "2026-11-02",
                 "latest_release": {"date": "2026-11-01", "name": "Y", "spotify_id": "2"},
                 "previous_release": {"date": "2026-10-30", "name": "Z", "spotify_id": "3"}},
        "Skeleton": {"spotify_id": None},
        "Quiet": {"spotify_id": "c", "latest_release_checked": "2026-10-01",
                  "latest_release": {"date": "2019", "type": "album", "spotify_id": "4"}},
        "Singling": {"spotify_id": "d", "latest_release_checked": "2026-10-20",
                     "latest_release": {"date": "2026-09-25", "type": "single", "spotify_id": "5"}},
        "AlbumOut": {"spotify_id": "e", "latest_release_checked": "2026-10-20",
                     "latest_release": {"date": "2026-10-16", "type": "album", "spotify_id": "6"}},
        "Nothing": {"spotify_id": "f", "latest_release_checked": "2026-10-20",
                    "latest_release": None},
    }
    if pending(cache, m) != ["Early", "Quiet", "Singling"]:
        print("bad pending", pending(cache, m)); fails += 1
    if plan(cache, m) != ["Singling", "Early", "Quiet"]:
        print("bad plan", plan(cache, m)); fails += 1
    if skipped(cache, m) != {SKIP_ALBUM: ["AlbumOut"], SKIP_NONE: ["Nothing"]}:
        print("bad skipped", skipped(cache, m)); fails += 1
    got = [(d_, n) for d_, n, _ in releases_in(cache, m)]
    if got != [("2026-10-09", "Early"), ("2026-10-16", "AlbumOut"), ("2026-10-30", "Late")]:
        print("bad releases", got); fails += 1
    print("self-test:", "ok" if not fails else f"{fails} failure(s)")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--env", action="store_true", help="KEY=VALUE window state for today")
    g.add_argument("--pending", action="store_true", help="count entries not yet covered")
    g.add_argument("--plan", action="store_true", help="pending names in check order")
    g.add_argument("--report", action="store_true", help="render the ready-mail body")
    g.add_argument("--self-test", action="store_true")
    ap.add_argument("--month", metavar="YYYY-MM", help="month for --pending/--plan/--report")
    ap.add_argument("--today", metavar="YYYY-MM-DD",
                    help="override today's date (UTC by default) for --env")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if args.env:
        today = date.fromisoformat(args.today) if args.today else _utc_today()
        for k, v in window(today).items():
            print(f"{k}={v!s}" if " " not in v else f"{k}='{v}'")
        return 0
    if not args.month:
        ap.error("--pending, --plan and --report need --month YYYY-MM")
    m = _month_start(args.month)
    cache = _load_cache()
    if args.pending:
        print(len(pending(cache, m)))
    elif args.plan:
        for n in plan(cache, m):
            print(n)
    else:
        sys.stdout.write(report(cache, m))
    return 0


def _utc_today() -> date:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).date()


if __name__ == "__main__":
    sys.exit(main())
