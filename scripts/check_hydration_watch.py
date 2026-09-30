#!/usr/bin/env python3
"""
check_hydration_watch.py - report watched artists whose Spotify entry has resolved.

data/hydration_watch.tsv lists artists that have no Spotify presence yet and says,
per row, what to do once they do (add them to a playlist, check a tour page).
new-artist-weekly.yml retries every cache entry with no spotify_id, so a watched
artist resolves on its own the week after they appear on Spotify - silently. This
script is the notice.

    python3 scripts/check_hydration_watch.py              # report, empty when nothing hydrated
    python3 scripts/check_hydration_watch.py --json
    python3 scripts/check_hydration_watch.py --selftest   # synthetic checks, no repo data

MATCHING. Each watched name resolves through ArtistResolver (scripts/name_forms.py),
so the watchlist and the cache can spell an artist differently ("X Band" / "X",
"Lone Bellow, The" / "The Lone Bellow") and still meet. A watched name that matches
NO cache entry at all is an error, not a quiet miss: the row would otherwise sit in
the file forever without ever being able to fire. Fix the spelling, or wait for the
weekly seed step to create the entry (it seeds names from the tracking files).

FIRES UNTIL REMOVED. A hit is reported on every run while its row stays in the
watchlist. Removing the row once the action is done is the acknowledgement; nothing
writes to the file automatically.

CHECK THE MATCH. The resolve step searches Spotify by name, so a new artist can
resolve to someone else with the same name. The cache stores no Spotify display
name, so the report shows the link plus the cached latest release and Last.fm
listener count - the fastest way to see a wrong match - and says to confirm before
acting.

Output: nothing when no watched artist has hydrated (so the report can be piped
into notify_email.py, which sends nothing for an empty body). Exit status: 0, or 2
when any watched name matches no cache entry.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import name_forms as nf  # noqa: E402  (sibling module in scripts/)

WATCHLIST = "data/hydration_watch.tsv"
CACHE = "data/artist_spotify.json"


def read_watchlist(root):
    rows = []
    for r in nf._read_rows(Path(root) / WATCHLIST):
        name = nf._cell(r.get("Artist"))
        if name:
            rows.append({"artist": name, "action": nf._cell(r.get("Action")),
                         "date_noted": nf._cell(r.get("Date Noted")),
                         "notes": nf._cell(r.get("Notes"))})
    return rows


def _identity(resolver, name):
    """Every key the watched name's identity is spelled under."""
    keys = resolver.group(name) if resolver is not None else set()
    return keys or nf._surface_keys(name) | {nf.identity_key(name)}


def check(watch, cache, resolver=None):
    """-> (hits, missing). A hit: the row plus every matching cache entry that now
    has a spotify_id. missing: rows whose name matches no cache entry at all."""
    hits, missing = [], []
    for row in watch:
        ident = _identity(resolver, row["artist"])
        matched = [k for k in sorted(cache) if nf.identity_key(k) in ident
                   or nf._surface_keys(k) & ident]
        if not matched:
            missing.append(row)
            continue
        resolved = []
        for k in matched:
            e = cache[k] or {}
            if not e.get("spotify_id"):
                continue
            rel = e.get("latest_release") or {}
            lf = e.get("lastfm") or {}
            resolved.append({"cache_key": k, "spotify_url": e.get("spotify_url"),
                             "latest_release": rel.get("name"),
                             "latest_release_date": rel.get("date"),
                             "lastfm_listeners": lf.get("listeners")})
        if resolved:
            hits.append({**row, "entries": resolved})
    return hits, missing


def render(hits):
    if not hits:
        return ""
    out = ["HYDRATION WATCH (%d) - watched artist(s) now on Spotify" % len(hits), ""]
    for h in hits:
        out.append(h["artist"])
        if h["action"]:
            out.append("  Action:  " + h["action"])
        for e in h["entries"]:
            out.append("  Spotify: %s  (cache entry \"%s\")" % (e["spotify_url"] or "-", e["cache_key"]))
            rel = e["latest_release"]
            if rel:
                out.append("  Latest:  %s%s" % (rel, " (%s)" % e["latest_release_date"]
                                                  if e["latest_release_date"] else ""))
            if e["lastfm_listeners"] is not None:
                out.append("  Last.fm listeners: %s" % e["lastfm_listeners"])
        if h["date_noted"]:
            out.append("  Watched since %s" % h["date_noted"])
        out.append("")
    out.append("The resolve step matches by name, so confirm each link is the right artist "
               "before acting. Remove the row from %s once the action is done; until then it "
               "is reported every week." % WATCHLIST)
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ selftest
def selftest():
    failures = []

    def expect(label, got, want):
        if got != want:
            failures.append("selftest %s: expected %r, got %r" % (label, want, got))

    watch = [{"artist": "Ann Example", "action": "Add to the example playlist",
              "date_noted": "2099-01-01", "notes": ""}]
    unresolved = {"Ann Example": {"spotify_id": None, "spotify_url": None}}
    resolved = {"Ann Example": {"spotify_id": "x1", "spotify_url": "https://open.spotify.com/artist/x1",
                                "latest_release": {"name": "First Single", "date": "2099-02-01"},
                                "lastfm": {"listeners": 12}}}

    hits, missing = check(watch, unresolved)
    expect("still null: no hit", (len(hits), len(missing)), (0, 0))
    expect("still null: silent report", render(hits), "")

    hits, missing = check(watch, resolved)
    expect("null -> real: one hit", (len(hits), len(missing)), (1, 0))
    expect("hit carries the url", hits[0]["entries"][0]["spotify_url"], "https://open.spotify.com/artist/x1")
    report = render(hits)
    expect("report names the action", "Add to the example playlist" in report, True)
    expect("report shows identity cues", "First Single" in report and "12" in report, True)

    typo = [dict(watch[0], artist="Ann Exampel")]
    hits, missing = check(typo, resolved)
    expect("typo is missing, never a quiet miss", (len(hits), [m["artist"] for m in missing]),
           (0, ["Ann Exampel"]))

    # a spelling difference the resolver bridges: watch the band name, cache the person
    r = nf.ArtistResolver(names=["Ann Example", "Ann Example Band"], appearances=["Ann Example Band"])
    band = [dict(watch[0], artist="Ann Example Band")]
    hits, missing = check(band, resolved, r)
    expect("resolver bridges X Band / X", (len(hits), len(missing)), (1, 0))

    # inverted article in the cache key
    inv = {"Example Band, The": dict(resolved["Ann Example"])}
    hits, missing = check([dict(watch[0], artist="The Example Band")], inv)
    expect("inverted article matches", (len(hits), len(missing)), (1, 0))

    for f in failures:
        print("FAIL: " + f)
    print("hydration watch selftest: %d failure(s)" % len(failures))
    return 1 if failures else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--selftest", action="store_true", help="run synthetic checks and exit")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    watch = read_watchlist(args.root)
    cache = json.loads((Path(args.root) / CACHE).read_text(encoding="utf-8"))
    resolver = nf.ArtistResolver.from_repo(args.root)
    hits, missing = check(watch, cache, resolver)

    for m in missing:
        print("error: %s: %r matches no entry in %s - fix the spelling, or wait for the weekly "
              "seed step to create it" % (WATCHLIST, m["artist"], CACHE), file=sys.stderr)

    if args.json:
        print(json.dumps({"count": len(hits), "missing": [m["artist"] for m in missing],
                          "hits": hits}, indent=2, ensure_ascii=False))
    else:
        sys.stdout.write(render(hits))
    return 2 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
