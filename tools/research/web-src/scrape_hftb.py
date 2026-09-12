#!/usr/bin/env python3
"""
scrape_hftb.py - headless HereForTheBands scrape.

Replaces the browser-session scrape for HFTB. Writes the same TSV the Claude
in Chrome flow produced, so websrc_diff.py and the monthly archive convention
are unchanged.

    python3 tools/research/web-src/scrape_hftb.py
    python3 tools/research/web-src/scrape_hftb.py --days 7 --out /tmp/probe.tsv
    python3 tools/research/web-src/scrape_hftb.py --region 1

WHY THIS CAN BE HEADLESS

The shows page ships no event markup; it builds the table client-side from one
call per calendar day:

    https://www.hereforthebands.com/jc.php?region=3&page=ALL&date=YYYY-MM-DD

Nothing about that is personalised and the site has no account, so a plain HTTP
client with an ordinary User-Agent gets identical JSON (verified 2026-09-11).
That is what makes a scheduled run possible at all.

The Bandsintown recommends view is the opposite case and deliberately not
handled here: it is personalised to the rhbl follow graph, so without the
session it returns a generic listing that looks plausible and is not ours. BIT
stays on the monthly browser pass.

REGION IS A BITMASK

dc=1, bal=2, wd=4, phi=8 - so region=3 is DC + Baltimore, which is the default
here. Every scrape through 2026-09 used region=1, so Baltimore rooms that appear
in our own potentials and history (The 8x10, Ottobar, Baltimore Soundstage) were
never in the HFTB half of the diff.

Consequence worth knowing before the first run: a region=3 file diffed against a
region=1 predecessor reports every Baltimore act as new. That is a coverage
change, not a week of announcements. Use --baseline for that run.

HTML ENTITIES

jc.php returns entities raw (`&ndash;`, `&amp;`). The browser scrape decoded them
incidentally via the DOM; nothing here does that for free, so this unescapes
explicitly. Left raw, `&amp;` breaks artist matching and `&ndash;` is not a
character at all, just a literal seven-byte string in the middle of a title.

Note what decoding produces: `&ndash;` becomes a real en-dash. That is correct
here. web-src files are scrape artifacts recording what the site said, and
check_ascii_punctuation.py deliberately scans only data/ TSVs and
data/setlists/*.json - the 2026-09 file already carries 100 such characters
(47 en-dashes, plus curly quotes). Folding them would make the file a worse
record of the source, and websrc_diff normalizes punctuation at join time.

The rule does apply the moment a value is promoted out of web-src into a
curated data/ file - a potentials row, a notes field - because that is where a
curly character silently orphans a sidecar key or a goal-badge match. Fold
there, not here.
"""

import argparse
import html
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

# Default output lives beside this script. Computed defensively so the module
# stays importable from anywhere - the parsing functions are worth testing
# without a repo checkout around them.
WEBSRC = Path(__file__).resolve().parent

ENDPOINT = "https://www.hereforthebands.com/jc.php?region={region}&page=ALL&date={day}"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

HEADER = ["Artist", "Venue", "Date", "Venue URL"]

# Stop after this many consecutive empty days. The calendar thins out ~10 months
# ahead and then stops; a single empty day is normal (Mondays especially), a long
# run of them is the end of the data.
EMPTY_RUN_STOP = 45
MAX_DAYS = 420


def fetch_day(day, region, retries=3):
    url = ENDPOINT.format(region=region, day=day.isoformat())
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json, text/plain, */*"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode("utf-8", "replace")
            return json.loads(raw) if raw.strip() else {}
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt == retries - 1:
                raise SystemExit(f"FATAL: {day} failed after {retries} attempts: {e}")
            time.sleep(2 * (attempt + 1))


def fmt_date(d):
    """"Tuesday, September 1, 2026" - matches every existing HFTB file.

    Built by hand rather than with strftime("%-d"): the no-pad flag is a glibc
    extension and is not portable, and a zero-padded day would silently change
    the format of every row.
    """
    return "%s, %s %d, %d" % (d.strftime("%A"), d.strftime("%B"), d.day, d.year)


def clean(s):
    """Unescape entities, normalize whitespace, strip tabs.

    Tabs are stripped rather than escaped: this is a TSV and a tab inside a value
    would shift every column to its right, which is the silent-corruption class
    validate_potential.py exists to catch on the other files.
    """
    s = html.unescape(s or "")
    s = unicodedata.normalize("NFC", s)
    return re.sub(r"\s+", " ", s.replace("\t", " ")).strip()


def rows_for_day(payload, day):
    """payload is keyed by date, then venue. Unwrap both layers."""
    out = []
    # The endpoint echoes the requested date as the top-level key, but take
    # whatever key came back rather than assuming - a mismatch would silently
    # yield nothing.
    for _date_key, venues in (payload or {}).items():
        if not isinstance(venues, dict):
            continue
        for venue, info in venues.items():
            info = info or {}
            url = clean(info.get("venue_url", ""))
            for show in (info.get("shows") or []):
                artist = clean(show if isinstance(show, str) else show.get("name", ""))
                if not artist:
                    continue
                out.append([artist, clean(venue), fmt_date(day), url])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--region", type=int, default=3,
                    help="bitmask: dc=1 bal=2 wd=4 phi=8 (default 3 = DC+Baltimore)")
    ap.add_argument("--days", type=int, default=MAX_DAYS,
                    help="max calendar days to walk (default %d)" % MAX_DAYS)
    ap.add_argument("--start", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--out", help="output path (default: web-src/rhbl-hereforthebands-dc-YYYY-MM.tsv)")
    ap.add_argument("--sleep", type=float, default=0.25,
                    help="seconds between requests (default 0.25)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    start = date.fromisoformat(args.start) if args.start else date.today()
    out = Path(args.out) if args.out else WEBSRC / (
        "rhbl-hereforthebands-dc-%s.tsv" % start.strftime("%Y-%m"))

    rows, empty_run, days_hit = [], 0, 0
    for i in range(args.days):
        day = start + timedelta(days=i)
        got = rows_for_day(fetch_day(day, args.region), day)
        days_hit += 1
        if got:
            rows.extend(got)
            empty_run = 0
        else:
            empty_run += 1
            if empty_run >= EMPTY_RUN_STOP:
                if not args.quiet:
                    print("  %d consecutive empty days - stopping at %s" % (empty_run, day))
                break
        if not args.quiet and days_hit % 30 == 0:
            print("  %s ... %d rows so far" % (day, len(rows)))
        time.sleep(args.sleep)

    # Dedupe. A show occasionally appears under two venue spellings on the same
    # day; keep first occurrence so ordering stays stable run to run.
    seen, uniq = set(), []
    for r in rows:
        k = tuple(r)
        if k not in seen:
            seen.add(k)
            uniq.append(r)

    if not uniq:
        raise SystemExit("FATAL: zero rows scraped. The endpoint shape or region "
                         "may have changed - refusing to write an empty file over "
                         "a good one.")

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        f.write("\t".join(HEADER) + "\n")
        for r in uniq:
            f.write("\t".join(r) + "\n")

    venues = len({r[1] for r in uniq})
    print("wrote %s" % out)
    print("  %d rows, %d distinct venues, %d calendar days walked, region=%d"
          % (len(uniq), venues, days_hit, args.region))
    # Sanity gate, scaled to the walk. A flat row-count floor is meaningless on a
    # short probe - shows cluster in the near term, so the first days are dense
    # (~60/day at region=3) while the far tail is thin, and the monthly average
    # lands near 8/day. Only a full walk can be judged on total rows.
    if days_hit >= 90 and len(uniq) < 500:
        print("  WARNING: %d rows over %d days is far below the ~1500 seen in "
              "2026-09. Check the endpoint before trusting this file."
              % (len(uniq), days_hit), file=sys.stderr)
    elif days_hit < 90:
        print("  (short walk - not a full scrape; %.0f rows/day)"
              % (len(uniq) / max(days_hit, 1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
