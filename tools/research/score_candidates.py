#!/usr/bin/env python3
"""score_candidates.py - order the untracked names in a web-src diff by fit.

Consumes the --json output of websrc_diff.py (the three untracked sections)
and renders every name into one of four buckets with its reasons. Scoring
ORDERS the list; it never drops a name. The bucket a human should read most
carefully is not "Strong fit" alone - "No signal" is where a local, brand-new
act lands, and that is exactly the kind of act the weekly HFTB pass exists to
surface.

Three independent signals, so an artist a genre map cannot place is still
caught by the other two:

  G  genre tags   Last.fm top tags (count-weighted) plus MusicBrainz genres,
                  scored against data/taste_genres.tsv. Range about -2 .. +2.
  T  taste graph  Last.fm similar artists (top 10) that are already tracked in
                  follows_master, fast_track or artists.tsv.
  R  context      repo-only: on a tracked label roster, or sharing a bill with
                  a tracked artist. No external call. (Core venue is the
                  admission test for the diff section itself, so it is not a
                  signal here - every candidate would carry it.)

Buckets (thresholds are constants below, not tuned per run):

  Strong fit    G >= STRONG_G or T >= STRONG_T
  Possible      G > 0 or T >= 1 or any R hit
  No signal     not found on Last.fm or MusicBrainz at all
  Off-profile   everything else

Enrichment is cached in data/candidate_cache.json, keyed by the display name,
separate from artist_spotify.json so never-adopted names do not pollute the
roster cache. Entries unseen for PRUNE_DAYS are dropped on write. Zero Spotify
calls: the Dev-mode app has no genres to give and no quota to spare.

Name matching goes through the repo normalizer (websrc_diff.keys_of for the
diff and bill joins, name_forms.identity_keys for the alias-aware taste-graph
join), never a raw compare.

    --diff PATH      websrc_diff.py --json output (required)
    --scrape PATH    the HFTB scrape TSV, for bill co-occurrence (optional)
    --offline        no network; score from the cache only, and report names
                     the cache lacks as "No signal (not enriched)"
    --no-write       do not update the cache file
    --json           machine-readable output instead of the report

Prints NOTHING and exits 0 when the diff holds no untracked names, so the
output can feed notify_email.py unconditionally.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts"))
from websrc_diff import acts, keys_of, load_tracking, read_rows  # noqa: E402
from name_forms import identity_keys, norm  # noqa: E402

GENRES_PATH = ROOT / "data" / "taste_genres.tsv"
CACHE_PATH = ROOT / "data" / "candidate_cache.json"

LASTFM_API = "https://ws.audioscrobbler.com/2.0/"
MB_API = "https://musicbrainz.org/ws/2/artist/"
UA = "live-shows-score-candidates/1.0 (+https://github.com/dan2bit/live-shows)"

TAGS_MAX = 8            # Last.fm top tags kept per artist
SIMILAR_MAX = 10        # Last.fm similar artists kept per artist
STRONG_G = 1.0          # bucket thresholds
STRONG_T = 2
COLLISION_LISTENERS = 500_000   # a "local act" with this many listeners is probably a name collision
CACHE_TTL_DAYS = 90     # re-enrich after this
PRUNE_DAYS = 90         # drop cache entries unseen for this long
MB_DELAY = 1.1          # MusicBrainz asks for <= 1 request/second
LASTFM_DELAY = 0.25

# Files that count for the taste-graph signal. artists.tsv is deliberately in:
# most seen-live artists are follows already, but it catches the strays.
T_FILES = {"follows", "fast_track", "artists"}

DECADE_TAG = re.compile(r"^(19|20)?\d0s$")

TODAY = date.today()


# ---- taste genres ----------------------------------------------------------

def tag_key(tag):
    """Fold case, hyphens, spaces and punctuation so blues-rock == blues rock == bluesrock."""
    return re.sub(r"[^a-z0-9]+", "", (tag or "").lower())


def load_genres(path=GENRES_PATH):
    """{tag_key: weight (float) or 'x'}, plus {tag_key: family}."""
    weights, families = {}, {}
    if not path.exists():
        return weights, families
    for r in read_rows(path):
        k = tag_key(r.get("Tag", ""))
        w = (r.get("Weight") or "").strip()
        if not k or not w:
            continue
        if w.lower() == "x":
            weights[k] = "x"
        else:
            try:
                weights[k] = float(w)
            except ValueError:
                continue
        families[k] = (r.get("Family") or "").strip()
    return weights, families


# ---- cache -----------------------------------------------------------------

def load_cache(path=CACHE_PATH):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def save_cache(cache, path=CACHE_PATH):
    keep = {}
    for name, e in cache.items():
        last = e.get("last_seen") or e.get("first_seen")
        try:
            if last and (TODAY - date.fromisoformat(last)).days > PRUNE_DAYS:
                continue
        except ValueError:
            pass
        keep[name] = e
    path.write_text(json.dumps(keep, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8")
    return len(cache) - len(keep)


def stale(iso):
    if not iso:
        return True
    try:
        return (TODAY - date.fromisoformat(iso)).days > CACHE_TTL_DAYS
    except ValueError:
        return True


# ---- network ---------------------------------------------------------------

def http_json(url, params=None, headers=None):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                time.sleep(2 * (attempt + 1))
                continue
            return None
        except (urllib.error.URLError, ValueError, TimeoutError):
            return None
    return None


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def lastfm(method, artist, api_key, **extra):
    data = http_json(LASTFM_API, {"method": method, "artist": artist, "autocorrect": "1",
                                  "api_key": api_key, "format": "json", **extra})
    if not data or "error" in data:
        return None
    return data


def enrich_lastfm(name, api_key):
    """-> lastfm block or None when Last.fm does not know the name."""
    info = lastfm("artist.getInfo", name, api_key)
    if not info or "artist" not in info:
        return None
    a = info["artist"]
    time.sleep(LASTFM_DELAY)
    tags_raw = lastfm("artist.getTopTags", name, api_key) or {}
    tags = [{"name": t.get("name", ""), "count": int(t.get("count", 0) or 0)}
            for t in _as_list((tags_raw.get("toptags") or {}).get("tag"))
            if isinstance(t, dict) and t.get("name")][:TAGS_MAX]
    time.sleep(LASTFM_DELAY)
    sim_raw = lastfm("artist.getSimilar", name, api_key, limit=str(SIMILAR_MAX)) or {}
    similar = [s.get("name", "") for s in _as_list((sim_raw.get("similarartists") or {}).get("artist"))
               if isinstance(s, dict) and s.get("name")][:SIMILAR_MAX]
    stats = a.get("stats") or {}
    try:
        listeners = int(stats.get("listeners") or 0)
    except ValueError:
        listeners = 0
    return {"matched": a.get("name", name), "mbid": a.get("mbid", "") or "",
            "url": a.get("url", "") or "", "listeners": listeners,
            "tags": tags, "similar": similar, "checked": TODAY.isoformat()}


def enrich_mb(mbid):
    """-> list of curated MusicBrainz genre names, or None on failure."""
    if not mbid:
        return []
    data = http_json(MB_API + urllib.parse.quote(mbid), {"inc": "genres", "fmt": "json"})
    if data is None:
        return None
    time.sleep(MB_DELAY)
    return [g.get("name", "") for g in data.get("genres") or [] if g.get("name")]


# ---- candidates ------------------------------------------------------------

def candidates_from_diff(diff):
    seen, out = set(), []
    for section in ("untracked_corroborated", "untracked_single_source_core_venue",
                    "label_roster_hits"):
        for e in diff.get(section, []):
            k = frozenset(keys_of(e["name"]))
            if not k or k in seen:
                continue
            seen.add(k)
            out.append({"name": e["name"], "sources": e.get("sources", []),
                        "shows": e.get("shows", []), "labels": e.get("labels", []),
                        "corroborated": section == "untracked_corroborated"})
    return out


def bill_mates(scrape_path, tracked_keys):
    """{candidate key -> [tracked names sharing a bill]} from the raw scrape."""
    out = {}
    if not scrape_path or not Path(scrape_path).exists():
        return out
    for r in read_rows(Path(scrape_path)):
        names = acts(r.get("Artist", ""))
        if len(names) < 2:
            continue
        tracked = [n for n in names if keys_of(n) & tracked_keys]
        if not tracked:
            continue
        for n in names:
            if n in tracked:
                continue
            for k in keys_of(n):
                out.setdefault(k, [])
                for t in tracked:
                    if t not in out[k]:
                        out[k].append(t)
    return out


# ---- scoring ---------------------------------------------------------------

def score_g(entry, weights):
    """(score or None, recognised tag names, unknown tag names)."""
    tags = list((entry.get("lastfm") or {}).get("tags") or [])
    mb = entry.get("mb_genres") or []
    top = max((t["count"] for t in tags), default=100) or 100
    tags = tags + [{"name": g, "count": top} for g in mb if g]
    num = den = 0.0
    used, unknown = [], []
    for t in tags:
        k = tag_key(t["name"])
        if not k or DECADE_TAG.match(k) or weights.get(k) == "x":
            continue
        w = weights.get(k)
        c = float(t["count"] or 1)
        if w is None:
            unknown.append(t["name"])
            den += c
            continue
        num += w * c
        den += c
        if t["name"].lower() not in (u.lower() for u in used):
            used.append(t["name"])
    if den == 0:
        return None, used, unknown
    return num / den, used, unknown


def ident(name):
    """Alias-aware identity keys, with "X and Y" folded onto "X Y" so an
    ampersand spelling and an "and" spelling meet (norm() drops the "&" but
    keeps the word)."""
    keys = set(identity_keys(name))
    return keys | {k.replace(" and ", " ") for k in keys}


def t_index_from(tracking):
    idx = {}
    for v in tracking.values():
        if not (v["files"] & T_FILES):
            continue
        for k in ident(v["name"]):
            idx.setdefault(k, v["name"])
    return idx


def score_t(entry, t_index):
    hits = []
    for s in (entry.get("lastfm") or {}).get("similar") or []:
        hit = next((t_index[k] for k in ident(s) if k in t_index), None)
        if hit and hit not in hits:
            hits.append(hit)
    return hits


def bucket(g, t, r_hits, found):
    if not found:
        return "No signal"
    if (g is not None and g >= STRONG_G) or len(t) >= STRONG_T:
        return "Strong fit"
    if (g is not None and g > 0) or t or r_hits:
        return "Possible"
    return "Off-profile"


def run(args):
    weights, families = load_genres()
    cache = load_cache()
    diff = json.loads(Path(args.diff).read_text(encoding="utf-8"))
    cands = candidates_from_diff(diff)
    if not cands:
        return None, cache

    tracking = load_tracking()
    t_index = t_index_from(tracking)
    tracked_keys = set(tracking)
    mates = bill_mates(args.scrape, tracked_keys)

    api_key = os.environ.get("LASTFM_API_KEY", "")
    offline = args.offline or not api_key
    if not api_key and not args.offline:
        print("::warning::LASTFM_API_KEY unset - scoring from the cache only.", file=sys.stderr)

    results, unknown_all, collisions = [], Counter(), 0
    for c in cands:
        name = c["name"]
        e = cache.get(name) or {"first_seen": TODAY.isoformat(), "weeks_seen": 0}
        e["last_seen"] = TODAY.isoformat()
        e["weeks_seen"] = int(e.get("weeks_seen", 0)) + 1
        enriched_now = False
        if not offline and ("lastfm" not in e or stale(e.get("checked"))):
            e["lastfm"] = enrich_lastfm(name, api_key)
            e["checked"] = TODAY.isoformat()
            enriched_now = True
            if e["lastfm"] and e["lastfm"].get("mbid"):
                mb = enrich_mb(e["lastfm"]["mbid"])
                if mb is not None:
                    e["mb_genres"] = mb
        cache[name] = e

        lf = e.get("lastfm")
        found = bool(lf)
        not_enriched = "lastfm" not in e
        g, used, unknown = score_g(e, weights) if found else (None, [], [])
        t = score_t(e, t_index) if found else []
        r = []
        if c["labels"]:
            r.append("roster: " + ", ".join(c["labels"]))
        mate = next((mates[k] for k in keys_of(name) if k in mates), None)
        if mate:
            r.append("bill: " + ", ".join(mate[:3]))
        if c["corroborated"]:
            r.append("both sources")
        collision = bool(lf and lf.get("listeners", 0) >= COLLISION_LISTENERS)
        if collision:
            collisions += 1
        b = bucket(g, t, r, found)
        if collision:
            b = "Possible" if r else "No signal"   # do not trust the enrichment
        if not found and not_enriched:
            b = "No signal (not enriched)"
        for u in unknown:
            unknown_all[u] += 1
        results.append({"name": name, "bucket": b, "g": g, "g_tags": used, "t": t, "r": r,
                        "collision": collision, "listeners": (lf or {}).get("listeners"),
                        "matched": (lf or {}).get("matched"), "shows": c["shows"][:2],
                        "enriched_now": enriched_now})
    return {"results": results, "unknown_tags": unknown_all, "collisions": collisions}, cache


ORDER = ["Strong fit", "Possible", "No signal", "No signal (not enriched)", "Off-profile"]


def render(out):
    res = out["results"]
    lines = ["Untracked names, scored (%d)" % len(res),
             "G = genre fit (-2..+2)  T = tracked artists among Last.fm similar  R = context",
             ""]
    for b in ORDER:
        group = [r for r in res if r["bucket"] == b]
        if not group:
            continue
        lines.append("%s (%d)" % (b, len(group)))
        lines.append("-" * 62)
        for r in sorted(group, key=lambda x: (-(x["g"] or -9), -len(x["t"]), x["name"].lower())):
            bits = []
            if r["g"] is not None:
                bits.append("G%+.1f (%s)" % (r["g"], ", ".join(r["g_tags"][:4]) or "no scored tags"))
            if r["t"]:
                bits.append("T%d (%s)" % (len(r["t"]), ", ".join(r["t"][:3])))
            bits.extend(r["r"])
            if r["collision"]:
                bits.append("collision? %s listeners as \"%s\"" % (
                    "{:,}".format(r["listeners"] or 0), r["matched"]))
            elif r["matched"] and norm(r["matched"]) != norm(r["name"]):
                bits.append("matched \"%s\"" % r["matched"])
            lines.append("  %-30s %s" % (r["name"], "  ".join(bits)))
            for s in r["shows"]:
                lines.append("      %s" % s)
        lines.append("")
    if out["unknown_tags"]:
        top = out["unknown_tags"].most_common(12)
        lines.append("Tags not in taste_genres.tsv (add or mark x): " +
                     ", ".join("%s(%d)" % kv for kv in top))
    if out["collisions"]:
        lines.append("%d name(s) flagged as possible Last.fm collisions - enrichment not trusted."
                     % out["collisions"])
    return "\n".join(lines).rstrip()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--diff", required=True)
    ap.add_argument("--scrape")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    out, cache = run(args)
    if not args.no_write and out is not None:
        pruned = save_cache(cache)
        if pruned:
            print("candidate cache: pruned %d stale entr%s" % (pruned, "y" if pruned == 1 else "ies"),
                  file=sys.stderr)
    if out is None:
        return 0
    if args.json:
        o = dict(out)
        o["unknown_tags"] = dict(out["unknown_tags"])
        print(json.dumps(o, indent=2, ensure_ascii=False))
        return 0
    print(render(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
