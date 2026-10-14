#!/usr/bin/env python3
"""probe_setlistfm_attended.py -- can the setlist.fm API list a user's attended shows?

A one-off probe that answers the questions the attendance reconcile in
check_setlists.py has to be designed around, before any of it is built:

  reach       Does /1.0/user/{user}/attended answer with this API key? (The
              endpoint is documented but has been flaky for other keys.) The
              user record is asked first, so a missing user and a gated
              endpoint are told apart.
  shape       total, itemsPerPage, how many pages a full pull costs at the
              configured pause.
  ordering    Is the list ordered by event date, newest first? If it is, a show
              attended last week is on page 1, but an old show marked attended
              last week sits deep in the list - and "fetch page 1 until nothing
              new appears" would never see it.
  additions   Every setlist on the API list that is not in the archive export the
              history was built from (tools/archive/setlist_attendances_*.tsv) has
              been marked since that export. For each: its event date and the page
              it came back on. Those pages are the evidence for the paging rule.
  early stop  Simulates the cheap rule (walk from page 1, stop at the first page
              whose setlists are all already known) against the full pull and
              reports every addition that rule would have missed.
  ledgers     A preview of the reconcile itself: attended setlists from 2021 on
              whose URL appears nowhere under data/ (the likely missed show
              notes), newest first. Only a count and a short list - the real
              check matches names and dates, this matches ids.
  fallback    Only when asked, or when the attended endpoint fails: whether
              /1.0/search/setlists honours an attendee parameter, by comparing
              its total with and without the parameter for one year. Equal
              totals mean the parameter is ignored and the fallback is the web
              page, not the API.

Usage (repo root):
    SETLISTFM_API_KEY=... python3 scripts/probe_setlistfm_attended.py
    python3 scripts/probe_setlistfm_attended.py --user dan2bit --max-pages 40 \\
        --try-search --json probe.json

Writes a markdown report to $GITHUB_STEP_SUMMARY when set, else to stdout.
Always exits 0 when it ran; the findings are the output. The API base and the
pause between requests come from SETLISTFM_API_BASE and SETLISTFM_MIN_INTERVAL,
as in check_setlists.py.
"""

import argparse
import csv
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API_BASE_DEFAULT = "https://api.setlist.fm/rest"
ARCHIVE_GLOB = "tools/archive/setlist_attendances_*.tsv"
ID_RE = re.compile(r"setlist\.fm/setlist/[^\s\"'\t]+?-([0-9a-f]+)\.html")
LEDGER_FROM_YEAR = 2021


class Api:
    def __init__(self, key, base, pause):
        self.key, self.base, self.pause, self.calls = key, base.rstrip("/"), pause, 0

    def get(self, path, params=None):
        """-> (http_status, json_or_None, note). Retries a 429 once."""
        url = f"{self.base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={
            "x-api-key": self.key, "Accept": "application/json",
            "User-Agent": "live-shows-setlist-probe"})
        for attempt in (1, 2):
            self.calls += 1
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
                body = ""
                try:
                    body = err.read().decode("utf-8", "replace")[:200]
                except Exception:
                    pass
                return err.code, None, body
            except (urllib.error.URLError, TimeoutError, ValueError) as err:
                return 0, None, f"{type(err).__name__}: {err}"
            finally:
                time.sleep(self.pause)
        return 0, None, "gave up"


def iso(ddmmyyyy):
    try:
        return datetime.strptime(ddmmyyyy, "%d-%m-%Y").date().isoformat()
    except (TypeError, ValueError):
        return ""


def slim(s):
    venue = s.get("venue") or {}
    return {"id": s.get("id", ""), "date": iso(s.get("eventDate")),
            "artist": (s.get("artist") or {}).get("name", ""),
            "venue": venue.get("name", ""), "city": (venue.get("city") or {}).get("name", ""),
            "url": s.get("url", ""), "lastUpdated": s.get("lastUpdated", "")}


def read_archive():
    paths = sorted(glob.glob(ARCHIVE_GLOB))
    if not paths:
        return None, {}
    rows = {}
    with open(paths[-1], newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            m = ID_RE.search(r.get("URL") or "")
            if m:
                rows[m.group(1)] = r
    return paths[-1], rows


def ledger_ids():
    """Every setlist id that appears anywhere under data/ (TSV and JSON alike)."""
    ids = set()
    for path in glob.glob("data/**/*.tsv", recursive=True) + glob.glob("data/**/*.json", recursive=True):
        try:
            with open(path, encoding="utf-8") as fh:
                ids.update(ID_RE.findall(fh.read()))
        except (OSError, UnicodeDecodeError):
            continue
    return ids


def pull_attended(api, user, max_pages):
    pages, first = [], None
    for p in range(1, max_pages + 1):
        status, data, note = api.get(f"/1.0/user/{urllib.parse.quote(user)}/attended", {"p": p})
        if status != 200 or data is None:
            if p == 1:
                first = (status, note)
            elif status == 404:
                break      # the API answers 404 past the last page
            else:
                pages.append({"page": p, "status": status, "note": note, "items": []})
            break
        if p == 1:
            first = (status, "")
            meta = {k: data.get(k) for k in ("total", "itemsPerPage", "page")}
        items = [slim(s) for s in data.get("setlist") or []]
        pages.append({"page": p, "status": status, "items": items})
        total, per = data.get("total") or 0, data.get("itemsPerPage") or 20
        if not items or p * per >= total:
            break
    return first, (meta if pages else {}), pages


def ordering(pages):
    seq = [it["date"] for pg in pages for it in pg["items"] if it["date"]]
    inversions = sum(1 for a, b in zip(seq, seq[1:]) if b > a)
    return {"checked": len(seq), "newest_first": inversions == 0 and len(seq) > 1,
            "inversions": inversions, "first": seq[0] if seq else "", "last": seq[-1] if seq else ""}


def early_stop(pages, known):
    """Walk from page 1; stop after the first page whose ids are all known."""
    walked = set()
    stop_at = None
    for pg in pages:
        ids = {it["id"] for it in pg["items"]}
        walked |= ids
        if ids and ids <= known:
            stop_at = pg["page"]
            break
    every = {it["id"] for pg in pages for it in pg["items"]}
    missed = sorted(every - known - walked)
    return stop_at, missed


def search_fallback(api, user, year):
    with_user = api.get("/1.0/search/setlists", {"attendee": user, "year": year, "p": 1})
    without = api.get("/1.0/search/setlists", {"year": year, "p": 1})
    total = lambda r: (r[1] or {}).get("total") if r[0] == 200 else None
    a, b = total(with_user), total(without)
    if a is None:
        verdict = f"search with attendee answered HTTP {with_user[0]}"
    elif b is not None and a == b:
        verdict = "attendee is ignored (same total with and without it)"
    else:
        verdict = "attendee narrows the search"
    return {"year": year, "total_with_attendee": a, "total_without": b,
            "status_with": with_user[0], "status_without": without[0], "verdict": verdict}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--user", default="dan2bit")
    ap.add_argument("--max-pages", type=int, default=40, help="hard cap on attended pages pulled")
    ap.add_argument("--try-search", action="store_true", help="also probe the search fallback")
    ap.add_argument("--json", metavar="PATH", help="write the full result here")
    args = ap.parse_args(argv)

    out = []
    w = out.append
    key = os.environ.get("SETLISTFM_API_KEY", "").strip()
    w(f"## setlist.fm attended probe - `{args.user}`\n")
    if not key:
        w("No `SETLISTFM_API_KEY` in this run; nothing was asked.")
        emit(out)
        return 0
    api = Api(key, os.environ.get("SETLISTFM_API_BASE", API_BASE_DEFAULT),
              float(os.environ.get("SETLISTFM_MIN_INTERVAL", "0.55")))
    result = {"user": args.user, "probed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    # reach
    st, user_doc, note = api.get(f"/1.0/user/{urllib.parse.quote(args.user)}")
    result["user_lookup"] = {"status": st, "note": note}
    first, meta, pages = pull_attended(api, args.user, args.max_pages)
    result["attended_first_page"] = {"status": first[0] if first else None, "note": first[1] if first else ""}
    result["meta"], result["pages"] = meta, pages
    ok = bool(pages) and pages[0]["status"] == 200
    w(f"**reach** - user record: HTTP {st}" + (f" ({note})" if note else "")
      + f"; attended page 1: HTTP {first[0] if first else '-'}"
      + (f" ({first[1]})" if first and first[1] else "") + "\n")

    if ok:
        items = [it for pg in pages for it in pg["items"]]
        total, per = meta.get("total") or 0, meta.get("itemsPerPage") or 20
        full = -(-total // per) if per else 0
        pause = api.pause
        w(f"**shape** - total {total}, {per} per page: a full pull is {full} requests, "
          f"about {full * pause:.0f}s at {pause}s apart. Pulled {len(pages)} page(s), "
          f"{len(items)} setlists" + (" (stopped at --max-pages)" if len(pages) >= args.max_pages else "") + ".\n")
        o = ordering(pages)
        result["ordering"] = o
        w(f"**ordering** - {'newest event first' if o['newest_first'] else 'NOT strictly newest first'}"
          f" ({o['inversions']} inversion(s) over {o['checked']} dates, {o['first']} -> {o['last']}).\n")

        arch_path, archive = read_archive()
        known = set(archive)
        page_of = {it["id"]: pg["page"] for pg in pages for it in pg["items"]}
        added = sorted((it for it in items if it["id"] not in known), key=lambda it: it["date"], reverse=True)
        gone = sorted(set(archive) - set(page_of))
        result["archive"] = arch_path
        result["added_since_archive"] = [dict(it, page=page_of[it["id"]]) for it in added]
        result["in_archive_not_on_api"] = gone
        w(f"**additions** - {len(added)} setlist(s) on the API list are not in `{arch_path}` "
          f"({len(archive)} rows); {len(gone)} archive row(s) are no longer on the API list.\n")
        if added:
            deep = [it for it in added if page_of[it["id"]] > 1]
            w(f"{len(added) - len(deep)} of them on page 1, {len(deep)} deeper:\n")
            w("| page | date | artist | venue |")
            w("|---|---|---|---|")
            for it in added[:40]:
                w(f"| {page_of[it['id']]} | {it['date']} | [{it['artist']}]({it['url']}) | {it['venue']}, {it['city']} |")
            if len(added) > 40:
                w(f"| | | ... {len(added) - 40} more in the JSON | |")
            w("")
        stop_at, missed = early_stop(pages, known)
        result["early_stop"] = {"stops_at_page": stop_at, "missed": missed}
        w(f"**early stop** - walking from page 1 and stopping at the first all-known page stops at "
          f"page {stop_at if stop_at else '- (never; every page had something new)'} and would miss "
          f"{len(missed)} addition(s)" + (": the paging rule needs a full pull, or a periodic one." if missed
                                           else ": page-1-first with early stop is safe on this data.") + "\n")

        ledger = ledger_ids()
        recent = [it for it in items if it["date"][:4].isdigit() and int(it["date"][:4]) >= LEDGER_FROM_YEAR]
        unlinked = sorted((it for it in recent if it["id"] not in ledger), key=lambda it: it["date"], reverse=True)
        result["attended_not_in_ledgers_by_id"] = unlinked
        w(f"**ledgers (preview, ids only)** - {len(unlinked)} of {len(recent)} attended setlists from "
          f"{LEDGER_FROM_YEAR} on carry an id that appears nowhere under `data/`. Some will be bills "
          f"credited to a headliner's setlist; the real check also matches artist and date.\n")
        for it in unlinked[:15]:
            w(f"- {it['date']} [{it['artist']}]({it['url']}) - {it['venue']}")
        if len(unlinked) > 15:
            w(f"- ... {len(unlinked) - 15} more in the JSON")
        w("")

    if args.try_search or not ok:
        sf = search_fallback(api, args.user, datetime.now(timezone.utc).year)
        result["search_fallback"] = sf
        w(f"**fallback** - /1.0/search/setlists for {sf['year']}: total {sf['total_with_attendee']} with "
          f"attendee, {sf['total_without']} without -> {sf['verdict']}.\n")

    w(f"_{api.calls} API request(s)._")
    result["api_calls"] = api.calls
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    emit(out)
    return 0


def emit(lines):
    text = "\n".join(lines) + "\n"
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text)
    sys.stdout.write(text)


if __name__ == "__main__":
    sys.exit(main())
