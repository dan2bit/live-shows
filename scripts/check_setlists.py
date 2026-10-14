#!/usr/bin/env python3
"""check_setlists.py -- hygiene for the setlist.fm links every show carries.

Four checks, four reports, four step-summary sections:

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
  attendance    ADVISORY permanently, and only with --api on a full run (no
                --changed). Pulls the setlist.fm user's attended list and
                reconciles it with the ledgers from ATTENDANCE_FROM on, both ways:
                a setlist attended there that no ledger row accounts for (a missed
                show, or an act on a bill whose own setlist is not linked - a
                MULTI candidate), a linked setlist the attended list does not have
                (a bill change, a link to the wrong night, or a show not yet
                ticked on setlist.fm), and the same show dated differently on the
                two sides. The whole list is pulled every time: it is newest
                first by event date, so an old show marked attended today lands
                deep in it, and a full pull is only a couple of dozen requests.
                The pull is kept in --cache under ATTENDED_CACHE_KEY, and a run
                whose pull fails falls back to it.

Usage:
    python scripts/check_setlists.py                     # advisory, offline
    python scripts/check_setlists.py --strict            # pairing findings exit 1
    python scripts/check_setlists.py --api --cache FILE  # also verify with setlist.fm
    python scripts/check_setlists.py --api --changed BEFORE HEAD
                                                         # verify only links added
                                                         # or changed between two commits
    python scripts/check_setlists.py --selftest          # the attendance rules on a
                                                         # synthetic ledger, no network

The setlist.fm user whose attended list is pulled is --attended-user, else
SETLISTFM_USER, else GITHUB_REPOSITORY_OWNER (set in every Actions run), so a
fork whose GitHub and setlist.fm names differ sets the SETLISTFM_USER variable.

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
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta

from hygiene_report import Report, scope_from_args
from name_forms import ArtistResolver, identity_keys, split_support

LEDGERS = sorted(glob.glob("data/history/*.tsv")) + ["data/live_shows_current.tsv"]
SIDECARS = sorted(glob.glob("data/setlists/*.json"))
URL_RE = re.compile(r"^https?://(?:www\.)?setlist\.fm/setlist/([^/]+)/(\d{4})/(.+)-([0-9a-f]+)\.html$")
URL_FIND_RE = re.compile(r"https?://(?:www\.)?setlist\.fm/setlist/[^\s\"'\t]+?\.html")
# Words that appear in many venue names and so prove nothing when two names share them.
STOPWORDS = {"the", "and", "usa", "for", "hall", "club", "center", "centre", "theatre",
             "theater", "live", "park", "arts", "national", "performing"}
API_BASE_DEFAULT = "https://api.setlist.fm/rest"
ATTENDANCE_FROM = "2021-01-01"       # the history ledgers' first year; earlier shows are hand-kept
ATTENDED_CACHE_KEY = "_attended"     # not a setlist id, so it never collides with verification facts
DRIFT_DAYS = 3                       # how far apart two dates can be and still be one show


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


def check_verification(report, targets, venues, args, summary_note, drifted=None):
    """True when verification actually ran; False when it was skipped. Ids whose
    setlist.fm date differs from the ledger's are added to drifted."""
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
            if drifted is not None:
                drifted.add(sid)
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


# ---- check 4: attendance against the setlist.fm attended list -----------------

def fetch_attended_page(user, page, key, base, pause):
    """(http status, json or None, note). Retries a 429 once."""
    url = f"{base}/1.0/user/{urllib.parse.quote(user)}/attended?p={page}"
    request = urllib.request.Request(url, headers={
        "x-api-key": key, "Accept": "application/json", "User-Agent": "live-shows-setlist-check"})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                return response.status, json.load(response), ""
        except urllib.error.HTTPError as err:
            if err.code == 429 and attempt == 1:
                try:
                    wait = min(int(err.headers.get("Retry-After", "2")), 120)
                except ValueError:
                    wait = 2
                time.sleep(wait)
                continue
            return err.code, None, f"HTTP {err.code}"
        except (urllib.error.URLError, TimeoutError, ValueError) as err:
            return 0, None, f"{type(err).__name__}: {err}"
        finally:
            time.sleep(pause)
    return 0, None, "gave up"


def pull_attended(user, key, base, pause, max_pages):
    """({id: {date, artist, venue, city, url}}, complete, note). note is set only on a failure."""
    found = {}
    for page in range(1, max_pages + 1):
        status, data, note = fetch_attended_page(user, page, key, base, pause)
        if status == 404 and page > 1:
            return found, True, ""            # past the last page
        if status != 200 or data is None:
            return found, False, note or f"HTTP {status}"
        items = data.get("setlist") or []
        for s in items:
            try:
                when = datetime.strptime(s.get("eventDate", ""), "%d-%m-%Y").date().isoformat()
            except ValueError:
                continue
            venue = s.get("venue") or {}
            found[s.get("id", "")] = {"date": when, "artist": (s.get("artist") or {}).get("name", ""),
                                      "venue": venue.get("name", ""),
                                      "city": (venue.get("city") or {}).get("name", ""),
                                      "url": s.get("url", "")}
        total, per = data.get("total") or 0, data.get("itemsPerPage") or 20
        if not items or page * per >= total:
            return found, True, ""
    return found, False, f"stopped at --attended-max-pages {max_pages}"


def ledger_shows():
    """Every attended show from ATTENDANCE_FROM on, with the setlists it links.

    [{path, line, date, headliner, support: [..], seen: [..], links: [(act, url, id)]}]
    A MULTI row's links come from its data/setlists entry. seen_with names count as
    on the bill: a sit-in or support slot recorded there can have a set of its own.
    """
    entries = {}
    for path in SIDECARS:
        with open(path, encoding="utf-8") as fh:
            entries.update(json.load(fh))
    seen = defaultdict(list)
    for _, row in read_tsv("data/seen_with.tsv"):
        name = (row.get("Seen With") or "").strip()
        if name and name != "-":
            seen[(row.get("Show Date") or "").strip()].append(name)
    shows = []
    for path in LEDGERS:
        current = path.endswith("live_shows_current.tsv")
        for line, row in read_tsv(path):
            when = (row.get("Show Date") or "").strip()
            if when < ATTENDANCE_FROM:
                continue
            if current and (row.get("Status") or "").strip().lower() != "attended":
                continue
            headliner = (row.get("Artist") or "").strip()
            cell = (row.get("Setlist.fm URL") or "").strip()
            links = []
            if cell.startswith("MULTI:"):
                entry = entries.get(cell[len("MULTI:"):].strip()) or {}
                for item in entry.get("setlists") or []:
                    parts = parse_url(item.get("url"))
                    if parts:
                        links.append((item.get("artist", ""), item["url"].strip(), parts["id"]))
            else:
                parts = parse_url(cell)
                if parts:
                    links.append((headliner, cell, parts["id"]))
            support = split_support(row.get("Supporting Acts") or row.get("Supporting Artist") or "")
            shows.append({"path": path, "line": line, "date": when, "headliner": headliner,
                          "support": support, "seen": seen.get(when, []), "links": links})
    return shows


def days_apart(a, b):
    try:
        return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)
    except ValueError:
        return 9999


def reconcile(shows, attended, same_act, through, complete=True, drifted=()):
    """The attendance findings as (kind, path, line, message), kinds being
    'unaccounted', 'multi', 'unlinked', 'not-attended' and 'drift'.

    attended  {id: {date, artist, venue, city, url}} from the setlist.fm list
    same_act  (a, b) -> bool, the name resolution
    through   the latest date to hold the ledger to (shows after it can't be attended yet)
    complete  False when the pull stopped early: a linked setlist older than the
              oldest one pulled is then not evidence of anything
    drifted   ids verification already reported dated differently
    """
    out = []
    linked = {}
    for show in shows:
        for act, url, sid in show["links"]:
            linked.setdefault(sid, (show, act, url))
    oldest = min((a["date"] for a in attended.values()), default="")

    for sid, a in sorted(attended.items(), key=lambda kv: (kv[1]["date"], kv[1]["artist"])):
        if a["date"] < ATTENDANCE_FROM:
            continue
        where = f"{a['venue']}, {a['city']}".strip(", ")
        if sid in linked:
            show, act, url = linked[sid]
            if show["date"] != a["date"] and sid not in drifted:
                out.append(("drift", show["path"], show["line"],
                            f"{act or show['headliner']}: the ledger dates setlist {sid} {show['date']}, "
                            f"setlist.fm dates it {a['date']} ({url})"))
            continue
        same_day = [s for s in shows if s["date"] == a["date"]]
        hit = None
        for s in same_day:
            if same_act(a["artist"], s["headliner"]):
                hit = ("unlinked", s, "headliner")
                break
            if any(same_act(a["artist"], x) for x in s["support"]):
                hit = ("multi", s, "on the bill")
                break
            if any(same_act(a["artist"], x) for x in s["seen"]):
                hit = ("multi", s, "in seen_with")
                break
        if hit:
            kind, s, how = hit
            if kind == "unlinked" and not s["links"]:
                msg = f"{a['artist']} on {a['date']}: the row has no setlist link; setlist.fm has {a['url']}"
            elif kind == "unlinked":
                msg = (f"{a['artist']} on {a['date']}: a second attended setlist for the headliner, not "
                       f"linked from the row ({a['url']})")
            else:
                msg = (f"{a['artist']} on {a['date']} is {how} of the {s['headliner']} row but its "
                       f"setlist is not linked: MULTI candidate ({a['url']})")
            out.append((kind, s["path"], s["line"], msg))
            continue
        near = [s for s in shows if 0 < days_apart(s["date"], a["date"]) <= DRIFT_DAYS
                and (same_act(a["artist"], s["headliner"]) or any(same_act(a["artist"], x) for x in s["support"]))]
        if near:
            s = min(near, key=lambda s: days_apart(s["date"], a["date"]))
            out.append(("drift", s["path"], s["line"],
                        f"{a['artist']}: setlist.fm dates the show {a['date']} at {where}, the ledger "
                        f"row is {s['date']} ({a['url']})"))
            continue
        tail = (f"; the {', '.join(s['headliner'] for s in same_day)} row that night names no such act"
                if same_day else "")
        out.append(("unaccounted", same_day[0]["path"] if same_day else None,
                    same_day[0]["line"] if same_day else None,
                    f"{a['artist']} on {a['date']} at {where}: attended on setlist.fm, not in any "
                    f"ledger{tail} ({a['url']})"))

    for show in shows:
        if show["date"] > through or (not complete and show["date"] < oldest):
            continue
        for act, url, sid in show["links"]:
            if sid not in attended:
                out.append(("not-attended", show["path"], show["line"],
                            f"{act or show['headliner']} on {show['date']}: setlist {sid} is linked but "
                            f"not on the attended list - not yet ticked on setlist.fm, a bill change, "
                            f"or a link to the wrong night ({url})"))
    return out


def check_attendance(report, args, summary_note, drifted):
    """True when the reconcile ran (from a fresh pull or the cached one)."""
    key = os.environ.get("SETLISTFM_API_KEY", "").strip()
    user = (args.attended_user or os.environ.get("SETLISTFM_USER", "")
            or os.environ.get("GITHUB_REPOSITORY_OWNER", "")).strip()
    if not key:
        summary_note("Setlist.fm attendance skipped: no SETLISTFM_API_KEY in this run.")
        return False
    if not user:
        summary_note("Setlist.fm attendance skipped: no setlist.fm user (--attended-user or SETLISTFM_USER).")
        return False
    base = os.environ.get("SETLISTFM_API_BASE", API_BASE_DEFAULT).rstrip("/")
    pause = float(os.environ.get("SETLISTFM_MIN_INTERVAL", "0.55"))
    cache = load_cache(args.cache) if args.cache else {}
    kept = cache.get(ATTENDED_CACHE_KEY) or {}
    if kept.get("user") != user:
        kept = {}
    today = date.today().isoformat()

    pulled, complete, failure = pull_attended(user, key, base, pause, args.attended_max_pages)
    if failure and not complete and not pulled and not kept:
        report.warn(f"setlist.fm would not list {user}'s attended shows ({failure}) and nothing is cached")
        summary_note(f"Setlist.fm attendance: no list for {user} ({failure}).")
        return True
    if failure and (not pulled or not complete) and kept.get("setlists"):
        report.warn(f"setlist.fm attended list for {user}: {failure}; reconciling against the copy "
                    f"pulled {kept.get('pulled', '?')}")
        attended, complete = kept["setlists"], kept.get("complete", False)
        fresh = []
    else:
        if failure:
            report.warn(f"setlist.fm attended list for {user}: {failure}; the pull is partial")
        before = kept.get("setlists") or {}
        attended = {sid: dict(a, first_seen=(before.get(sid) or {}).get("first_seen", today))
                    for sid, a in pulled.items()}
        fresh = sorted((a for sid, a in attended.items() if sid not in before and before),
                       key=lambda a: a["date"], reverse=True)
        if args.cache:
            cache[ATTENDED_CACHE_KEY] = {"user": user, "pulled": today, "complete": complete,
                                         "setlists": attended}
            save_cache(args.cache, cache)

    resolver = ArtistResolver.from_repo(".")

    def same_act(a, b):
        return artists_match(a, b) or bool(resolver.group(a) & resolver.group(b))

    findings = reconcile(ledger_shows(), attended, same_act, today, complete, drifted)
    order = ("unaccounted", "multi", "unlinked", "drift", "not-attended")
    for kind in order:
        for k, path, line, message in findings:
            if k == kind:
                report.warn(message, path, line)
    counts = {k: sum(1 for f in findings if f[0] == k) for k in order}
    note = (f"Setlist.fm attendance for {user}: {len(attended)} attended setlist(s)"
            + ("" if complete else " (partial list)")
            + (f", {len(fresh)} new since the last pull" if fresh else "")
            + f"; {counts['unaccounted']} not in a ledger, {counts['multi']} MULTI candidate(s), "
              f"{counts['unlinked']} headliner setlist(s) not linked, {counts['drift']} dated differently, "
              f"{counts['not-attended']} linked but not attended.")
    summary_note(note)
    if fresh:
        summary_note("New on the attended list: " + "; ".join(
            f"{a['date']} [{a['artist']}]({a['url']})" for a in fresh[:20])
            + (f"; and {len(fresh) - 20} more" if len(fresh) > 20 else "") + ".")
    return True


def selftest():
    """The reconcile rules on a synthetic ledger. Returns a list of failures."""
    def u(slug, sid):
        return f"https://www.setlist.fm/setlist/{slug}/2099/example-hall-{sid}.html"

    shows = [
        {"path": "L", "line": 2, "date": "2099-03-01", "headliner": "Example Mule",
         "support": ["Opener Example", "Yola (DJ)"], "seen": [], "links": [("Example Mule", u("m", "a1"), "a1")]},
        {"path": "L", "line": 3, "date": "2099-03-05", "headliner": "Example Duo",
         "support": [], "seen": ["Sit In Example"], "links": [("Example Duo", u("d", "b1"), "b1")]},
        {"path": "L", "line": 4, "date": "2099-03-09", "headliner": "No Link Example",
         "support": [], "seen": [], "links": []},
        {"path": "L", "line": 5, "date": "2099-03-12", "headliner": "Bill Change Example",
         "support": [], "seen": [], "links": [("Cancelled Opener", u("c", "c9"), "c9"),
                                              ("Bill Change Example", u("b", "c1"), "c1")]},
        {"path": "L", "line": 6, "date": "2099-03-20", "headliner": "Typo Date Example",
         "support": [], "seen": [], "links": []},
        {"path": "L", "line": 7, "date": "2099-03-25", "headliner": "Retagged Example",
         "support": [], "seen": [], "links": [("Retagged Example", u("r", "e1"), "e1")]},
        {"path": "L", "line": 8, "date": "2099-04-01", "headliner": "Example Mule",
         "support": [], "seen": [], "links": [("Example Mule", u("m", "f1"), "f1")]},
    ]

    def a(when, artist, sid):
        return {"date": when, "artist": artist, "venue": "Example Hall", "city": "Example", "url": u("x", sid)}

    attended = {
        "a1": a("2099-03-01", "Example Mule", "a1"),
        "a2": a("2099-03-01", "Opener Example", "a2"),        # support, unlinked -> multi
        "b1": a("2099-03-05", "Example Duo", "b1"),
        "b2": a("2099-03-05", "Sit In Example", "b2"),        # seen_with, unlinked -> multi
        "n1": a("2099-03-09", "The No Link Example", "n1"),   # headliner, row has no link
        "c1": a("2099-03-12", "Bill Change Example", "c1"),   # c9 linked, never attended
        "t1": a("2099-03-21", "Typo Date Example", "t1"),     # a day off -> drift
        "e1": a("2099-03-26", "Retagged Example", "e1"),      # same id, other date -> drift
        "z1": a("2099-03-30", "Missed Show Example", "z1"),   # no row at all
        "o1": a("1999-01-01", "Before The Ledgers", "o1"),    # out of scope
    }
    loose_match = lambda x, y: loose(x) == loose(y)
    got = sorted((k, line) for k, _, line, _ in reconcile(shows, attended, loose_match, "2099-03-31"))
    want = sorted([("multi", 2), ("multi", 3), ("unlinked", 4), ("not-attended", 5), ("drift", 6),
                   ("drift", 7), ("unaccounted", None)])
    failures = [] if got == want else [f"reconcile: expected {want}, got {got}"]
    # a show after `through` is not owed an attendance yet; f1 is 2099-04-01
    if any(k == "not-attended" and line == 8 for k, _, line, _ in
           reconcile(shows, attended, loose_match, "2099-03-31")):
        failures.append("reconcile: a show after the through date was held to the attended list")
    # verification already reported e1's date; attendance does not repeat it
    if any(line == 7 for k, _, line, _ in reconcile(shows, attended, loose_match, "2099-03-31", drifted={"e1"})):
        failures.append("reconcile: repeated a date drift verification already reported")
    # a partial pull says nothing about links older than its oldest setlist
    partial = {k: v for k, v in attended.items() if v["date"] >= "2099-03-20"}
    if any(k == "not-attended" for k, _, _, _ in
           reconcile(shows, partial, loose_match, "2099-03-31", complete=False)):
        failures.append("reconcile: a partial pull reported links older than its oldest setlist")
    return failures


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
    ap.add_argument("--attended-user", metavar="USER", help="setlist.fm user whose attended list to reconcile")
    ap.add_argument("--attended-max-pages", type=int, default=60, help="cap on attended-list pages (20 each)")
    ap.add_argument("--selftest", action="store_true", help="run the attendance rules on a synthetic ledger")
    args = ap.parse_args(argv)

    if args.selftest:
        failures = selftest()
        for failure in failures:
            print(f"::error::{failure}")
        print("Attendance selftest: " + ("clean." if not failures else f"{len(failures)} failure(s)."))
        return 1 if failures else 0

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
    drifted = set()
    verified = args.api and check_verification(verify, targets, venues, args, summary_note, drifted)
    # A push or PR (--changed) is about the links it touched; the attended list is a
    # whole-ledger question, so only the weekly run and a manual dispatch ask it.
    attendance = Report("Setlist.fm attendance")
    reconciled = args.api and not args.changed and check_attendance(attendance, args, summary_note, drifted)

    links.finish()
    if verified:
        verify.finish()
    if reconciled:
        attendance.finish()
    return pairing.finish(strict=args.strict is not None, scope=scope_from_args(args.strict))


if __name__ == "__main__":
    sys.exit(main())
