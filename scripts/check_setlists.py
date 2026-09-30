#!/usr/bin/env python3
"""check_setlists.py -- hygiene for the setlist.fm links every show carries.

Three checks, three reports, three step-summary sections:

  pairing       MECHANICAL. Every `MULTI:<date>` marker in a ledger row has an
                entry under that date in data/setlists/<year>.json, and every
                entry has a marker. A marker's date is its own row's Show Date.
                Every entry lists at least one act, each with a name and a URL.
                --strict makes these findings blocking.
  link sanity   HEURISTIC, advisory permanently. A URL's year matches the show's
                year; its venue slug shares a distinctive word with the show's
                venue (or one of that venue's aliases); one setlist is not filed
                under two shows; a MULTI entry lists more than one setlist.
  verification  ADVISORY permanently, and only with --api. Asks the setlist.fm
                API for the date, venue and artist behind each link and compares
                them with the ledger. Needs SETLISTFM_API_KEY and skips, without
                failing, when it is absent. Facts are kept in --cache so a
                repeat run asks only about links it has not seen recently.

Usage:
    python scripts/check_setlists.py                     # advisory, offline
    python scripts/check_setlists.py --strict            # pairing findings exit 1
    python scripts/check_setlists.py --api --cache FILE  # also verify with setlist.fm
    python scripts/check_setlists.py --api --changed BEFORE HEAD
                                                         # verify only links added
                                                         # or changed between two commits

Run from the repo root. The API base can be redirected with SETLISTFM_API_BASE
and the pause between requests with SETLISTFM_MIN_INTERVAL (seconds).
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta

from hygiene_report import Report, scope_from_args
from name_forms import identity_keys

LEDGERS = sorted(glob.glob("data/history/*.tsv")) + ["data/live_shows_current.tsv"]
SIDECARS = sorted(glob.glob("data/setlists/*.json"))
URL_RE = re.compile(r"^https?://(?:www\.)?setlist\.fm/setlist/([^/]+)/(\d{4})/(.+)-([0-9a-f]+)\.html$")
URL_FIND_RE = re.compile(r"https?://(?:www\.)?setlist\.fm/setlist/[^\s\"'\t]+?\.html")
# Words that appear in many venue names and so prove nothing when two names share them.
STOPWORDS = {"the", "and", "usa", "for", "hall", "club", "center", "centre", "theatre",
             "theater", "live", "park", "arts", "national", "performing"}
API_BASE_DEFAULT = "https://api.setlist.fm/rest"


# ---- reading -----------------------------------------------------------------

def read_tsv(path):
    """Yield (line number, row dict). Tolerates rows with trailing empty cells removed."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8", newline="") as fh:
        lines = fh.read().split("\n")
    header = lines[0].split("\t")
    for number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        cells = line.split("\t")
        cells += [""] * (len(header) - len(cells))
        yield number, dict(zip(header, cells))


def key_line(path, key):
    """Line number of a top-level JSON key, for annotations."""
    with open(path, encoding="utf-8") as fh:
        for number, line in enumerate(fh, start=1):
            if line.lstrip().startswith(f'"{key}"'):
                return number
    return None


def ascii_fold(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def tokens(text):
    """Distinctive lowercase words: '9:30 Club' gives {'930'}, 'Hamilton Live' gives {'hamilton'}."""
    text = re.sub(r"(?<=\d):(?=\d)", "", ascii_fold(text).lower())
    return {t for t in re.split(r"[^a-z0-9]+", text) if len(t) > 2 and t not in STOPWORDS}


def loose(name):
    """'The War & Treaty' and 'War and Treaty' collapse to the same string."""
    text = ascii_fold(name).lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]", "", re.sub(r"^\s*the\s+", "", text))


def artists_match(a, b):
    """The same act under any of its usual spellings. identity_keys covers aliases and
    accents; the loose form covers '&' against 'and', a leading 'The', and spacing."""
    if identity_keys(a) & identity_keys(b):
        return True
    la, lb = loose(a), loose(b)
    return bool(la and lb and (la == lb or (min(len(la), len(lb)) >= 8 and (la in lb or lb in la))))


class Venues:
    """A venue's name plus its short name and every alias, so any spelling matches."""

    def __init__(self):
        forms = defaultdict(set)
        for _, row in read_tsv("data/venues.tsv"):
            name = (row.get("Venue Name") or "").strip()
            if name:
                forms[name.lower()] |= {name, (row.get("Short Name") or "").strip()} - {""}
        for _, row in read_tsv("data/venue_aliases.tsv"):
            alias = (row.get("Alias") or "").strip()
            canon = (row.get("Venue Name") or "").strip()
            if alias and canon:
                forms[canon.lower()] |= {canon, alias}
        self.forms = forms
        self.index = {form.lower(): canon for canon, fs in forms.items() for form in fs}

    def tokens(self, text):
        canon = self.index.get((text or "").strip().lower())
        names = self.forms.get(canon, set()) | {text or ""}
        return set().union(*(tokens(n) for n in names))


def parse_url(url):
    m = URL_RE.match((url or "").strip())
    return None if not m else {"artist_slug": m.group(1), "year": m.group(2),
                               "venue_slug": m.group(3), "id": m.group(4)}


# ---- gathering ---------------------------------------------------------------

def gather():
    """Everything the checks need, read once."""
    markers = defaultdict(list)   # key -> [(path, line, row date, venue)]
    directs = []                  # (path, line, row date, venue, artist, url)
    for path in LEDGERS:
        for line, row in read_tsv(path):
            cell = (row.get("Setlist.fm URL") or "").strip()
            when = (row.get("Show Date") or "").strip()
            venue = (row.get("Venue") or row.get("Venue Name") or "").strip()
            if cell.startswith("MULTI:"):
                markers[cell[len("MULTI:"):].strip()].append((path, line, when, venue))
            elif cell.startswith("http"):
                directs.append((path, line, when, venue, (row.get("Artist") or "").strip(), cell))
    entries = {}                  # key -> (path, line, entry)
    for path in SIDECARS:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        for key, entry in data.items():
            entries[key] = (path, key_line(path, key), entry)
    return markers, directs, entries


# ---- check 1: pairing --------------------------------------------------------

def check_pairing(report, markers, entries):
    for key, places in sorted(markers.items()):
        if len(places) > 1:
            path, line, _, _ = places[1]
            report.warn(f"marker MULTI:{key} appears on {len(places)} ledger rows; a date key "
                        f"must belong to one show", path, line)
        for path, line, when, _ in places:
            if when and key != when:
                report.warn(f"marker MULTI:{key} does not match its row's Show Date {when}", path, line)
        want = f"data/setlists/{key[:4]}.json"
        if key not in entries:
            path, line, _, _ = places[0]
            report.warn(f"marker MULTI:{key} has no entry in {want}", path, line)
        elif os.path.normpath(entries[key][0]) != os.path.normpath(want):
            report.warn(f"entry {key} is filed in {entries[key][0]}, not {want}", entries[key][0], entries[key][1])
    for key, (path, line, entry) in sorted(entries.items()):
        if key not in markers:
            report.warn(f"entry {key} has no MULTI:{key} marker in any ledger row", path, line)
        acts = entry.get("setlists") if isinstance(entry, dict) else None
        if not acts:
            report.warn(f"entry {key} lists no setlists", path, line)
            continue
        for item in acts:
            if not (item.get("artist") or "").strip() or not (item.get("url") or "").strip():
                report.warn(f"entry {key} has a setlist with a blank artist or url", path, line)


# ---- check 2: link sanity ----------------------------------------------------

def sanity_targets(markers, directs, entries):
    """(path, line, show date, venue, act, url) for every setlist link, in the ledger or the sidecar."""
    targets = list(directs)
    for key, (path, line, entry) in entries.items():
        if key not in markers:
            continue
        _, _, when, venue = markers[key][0]
        for item in entry.get("setlists") or []:
            if (item.get("url") or "").strip():
                targets.append((path, line, when or key, venue, item.get("artist", ""), item["url"].strip()))
    return targets


def check_links(report, targets, entries, venues):
    seen_ids = defaultdict(set)
    for path, line, when, venue, act, url in targets:
        parts = parse_url(url)
        if not parts:
            report.warn(f"not a setlist.fm setlist URL: {url}", path, line)
            continue
        seen_ids[parts["id"]].add((when, act))
        if when and parts["year"] != when[:4]:
            report.warn(f"{act or 'link'} on {when}: the URL is for {parts['year']} ({url})", path, line)
        want = venues.tokens(venue)
        if want and not (want & tokens(parts["venue_slug"].replace("-", " "))):
            report.warn(f"{act or 'link'} on {when}: venue slug '{parts['venue_slug']}' shares no word "
                        f"with the show's venue '{venue}' ({url})", path, line)
    for sid, uses in seen_ids.items():
        shows = {when for when, _ in uses}
        if len(shows) > 1:
            report.warn(f"setlist {sid} is filed under {len(shows)} different shows: {', '.join(sorted(shows))}")
    for key, (path, line, entry) in entries.items():
        if len(entry.get("setlists") or []) == 1:
            report.warn(f"entry {key} lists one setlist; a show with a single link takes the URL "
                        f"directly in the ledger instead of a MULTI marker", path, line)


# ---- check 3: verification against setlist.fm --------------------------------

def load_cache(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(path, cache):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=1, sort_keys=True)


def added_ids(before, head):
    """Setlist IDs in URLs added between two commits, or None when git cannot say."""
    try:
        out = subprocess.run(["git", "diff", "-U0", before, head, "--", "data/history",
                              "data/live_shows_current.tsv", "data/setlists"],
                             capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    ids = set()
    for line in out.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            for url in URL_FIND_RE.findall(line):
                parts = parse_url(url)
                if parts:
                    ids.add(parts["id"])
    return ids


def fetch_facts(sid, key, base, pause):
    """('ok', facts) | ('missing', None) | ('auth', None) | ('rate', None) | ('error', why)."""
    request = urllib.request.Request(f"{base}/1.0/setlist/{sid}", headers={
        "x-api-key": key, "Accept": "application/json", "User-Agent": "live-shows-setlist-check"})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.load(response)
            when = datetime.strptime(data["eventDate"], "%d-%m-%Y").date().isoformat()
            venue = data.get("venue") or {}
            return "ok", {"date": when, "artist": (data.get("artist") or {}).get("name", ""),
                          "venue": venue.get("name", ""), "city": (venue.get("city") or {}).get("name", "")}
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return "missing", None
            if err.code in (401, 403):
                return "auth", None
            if err.code == 429 and attempt == 1:
                try:
                    wait = min(int(err.headers.get("Retry-After", "2")), 120)
                except ValueError:
                    wait = 2
                time.sleep(wait)
                continue
            return ("rate", None) if err.code == 429 else ("error", f"HTTP {err.code}")
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as err:
            return "error", f"{type(err).__name__}: {err}"
        finally:
            time.sleep(pause)
    return "error", "gave up"


def check_verification(report, targets, venues, args, summary_note):
    """True when verification actually ran; False when it was skipped."""
    key = os.environ.get("SETLISTFM_API_KEY", "").strip()
    if not key:
        summary_note("Setlist.fm verification skipped: no SETLISTFM_API_KEY in this run.")
        return False
    base = os.environ.get("SETLISTFM_API_BASE", API_BASE_DEFAULT).rstrip("/")
    pause = float(os.environ.get("SETLISTFM_MIN_INTERVAL", "0.55"))
    cache = load_cache(args.cache) if args.cache else {}
    today = date.today()
    stale_before = (today - timedelta(days=args.max_age_days)).isoformat()

    wanted = None
    if args.changed:
        wanted = added_ids(*args.changed)
        if wanted is None:
            summary_note("Setlist.fm verification skipped: could not diff the changed range.")
            return False
    scoped = [t for t in targets if parse_url(t[5]) and (wanted is None or parse_url(t[5])["id"] in wanted)]
    ids = sorted({parse_url(t[5])["id"] for t in scoped})
    todo = [i for i in ids if i not in cache or cache[i].get("fetched", "") < stale_before]
    requests_made = stopped = errors_in_a_row = 0
    problems = {}
    last_error = ""
    for sid in todo:
        if requests_made >= args.max_requests:
            stopped = len(todo) - todo.index(sid)
            break
        status, facts = fetch_facts(sid, key, base, pause)
        requests_made += 1
        errors_in_a_row = errors_in_a_row + 1 if status == "error" else 0
        if status == "ok":
            cache[sid] = dict(facts, fetched=today.isoformat())
        elif status == "auth":
            report.warn("setlist.fm rejected the API key; verification stopped")
            stopped = len(todo) - todo.index(sid)
            break
        elif status == "rate":
            report.warn("setlist.fm rate limit reached; verification stopped and will resume next run")
            stopped = len(todo) - todo.index(sid)
            break
        else:
            problems[sid] = status if status == "missing" else facts
            last_error = facts if status == "error" else last_error
            if errors_in_a_row >= 3:
                report.warn(f"setlist.fm gave three errors in a row (last: {last_error}); verification stopped")
                stopped = len(todo) - todo.index(sid)
                break
    if args.cache:
        save_cache(args.cache, cache)

    for path, line, when, venue, act, url in scoped:
        sid = parse_url(url)["id"]
        if problems.get(sid) == "missing":
            report.warn(f"{act or 'link'} on {when}: setlist.fm has no setlist {sid} ({url})", path, line)
            continue
        facts = cache.get(sid)
        if not facts:
            continue
        if when and facts["date"] != when:
            report.warn(f"{act or 'link'} on {when}: setlist.fm dates setlist {sid} {facts['date']} ({url})", path, line)
        want = venues.tokens(venue)
        have = tokens(f"{facts['venue']} {facts['city']}")
        if want and have and not (want & have):
            report.warn(f"{act or 'link'} on {when}: setlist.fm places setlist {sid} at "
                        f"'{facts['venue']}, {facts['city']}', not '{venue}' ({url})", path, line)
        if act and facts["artist"] and not artists_match(act, facts["artist"]):
            report.warn(f"{act} on {when}: setlist.fm files setlist {sid} under '{facts['artist']}' ({url})", path, line)
    cached = len(ids) - len(todo)
    note = (f"Setlist.fm verification: {len(ids)} link(s) in scope, {requests_made} request(s) made, "
            f"{cached} answered from the cache")
    if stopped:
        note += f", {stopped} left for the next run"
    unreachable = sum(1 for why in problems.values() if why != "missing")
    if unreachable:
        note += f"; {unreachable} could not be checked"
    summary_note(note + ".")
    return True


# ---- entry point --------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--strict", nargs="*", metavar="FILE", default=None,
                    help="exit 1 on pairing findings; with FILEs, only those files block")
    ap.add_argument("--api", action="store_true", help="also verify links with the setlist.fm API")
    ap.add_argument("--cache", metavar="PATH", help="JSON file of API facts reused between runs")
    ap.add_argument("--changed", nargs=2, metavar=("BEFORE", "HEAD"),
                    help="with --api, verify only links added between two commits")
    ap.add_argument("--max-requests", type=int, default=900, help="API request budget for one run")
    ap.add_argument("--max-age-days", type=int, default=45, help="re-ask about a link after this long")
    args = ap.parse_args(argv)

    def summary_note(text):
        print(text)
        dest = os.environ.get("GITHUB_STEP_SUMMARY")
        if dest:
            with open(dest, "a", encoding="utf-8") as fh:
                fh.write(text + "\n\n")

    markers, directs, entries = gather()
    venues = Venues()
    targets = sanity_targets(markers, directs, entries)

    pairing = Report("Setlist pairing")
    check_pairing(pairing, markers, entries)
    links = Report("Setlist link sanity")
    check_links(links, targets, entries, venues)
    verify = Report("Setlist.fm verification")
    verified = args.api and check_verification(verify, targets, venues, args, summary_note)

    links.finish()
    if verified:
        verify.finish()
    return pairing.finish(strict=args.strict is not None, scope=scope_from_args(args.strict))


if __name__ == "__main__":
    sys.exit(main())
