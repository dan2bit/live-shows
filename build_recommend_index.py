#!/usr/bin/env python3
"""
build_recommend_index.py — generate recommend_index.json for the live-shows
recommendation lookup.

Denormalizes artist names from four sources into a flat variant->record index so
the web app can resolve any surface form of a known artist (inverted "X, The",
accented, apostrophe'd, "... Band" suffixes, etc.) with an O(1) exact lookup,
falling back to fuzzy matching only for genuine typos.

Sources (status precedence high -> low):
  1. artists.tsv                -> "seen"        (attended history; times/dates/spotify/youtube)
  2. fast_track.tsv             -> "fast_track"  (pre-authorized buys; tier/spotify)
  3. live_shows_potential.tsv   -> "potential"   (Buy/Choose/Sell/Pass; +support acts)
  4. follows/follows_master.tsv -> "follow"      (follow list; tier)

Run from the repo root:
    python3 build_recommend_index.py

Writes recommend_index.json and prints a build + collision summary to stderr.
No third-party dependencies (stdlib only).
"""
import csv
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent

ARTISTS   = ROOT / "artists.tsv"
FASTTRACK = ROOT / "fast_track.tsv"
POTENTIAL = ROOT / "live_shows_potential.tsv"
FOLLOWS   = ROOT / "follows" / "follows_master.tsv"
ALIASES   = ROOT / "recommend_aliases.tsv"
OUTPUT    = ROOT / "recommend_index.json"

# Metadata precedence (which source wins a field when several have it).
STATUS_ORDER = ["seen", "fast_track", "potential", "follow"]
TIER_ORDER   = ["fast_track", "follow", "potential", "seen"]

# Also index support acts listed on potential rows (festival/opener lineups).
HARVEST_POTENTIAL_SUPPORT = True
# Potential rows whose Artist is an event, not a performer -> don't make a record
# for the Artist cell (support acts are still harvested).
SKIP_POTENTIAL_AGGREGATE = re.compile(r"festival|blues summit", re.I)


# ── normalization ─────────────────────────────────────────────────
def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def norm(s):
    """Lowercase, de-accent, drop one leading article, strip punctuation."""
    s = strip_accents(s or "").lower()
    s = re.sub(r"^\s*(the|a|an)\s+", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def surface_forms(raw):
    """All legitimate spellings of a name, pre-normalization."""
    raw = (raw or "").strip()
    if not raw:
        return set()
    forms = {raw}
    # de-invert "X, The" / "X, A" / "X, An" -> "The X" and bare "X"
    m = re.match(r"^(.*),\s*(the|a|an)$", raw, re.I)
    if m:
        forms.add("%s %s" % (m.group(2), m.group(1)))
        forms.add(m.group(1))
    # drop a trailing " Band" (Ally Venable Band -> Ally Venable)
    for f in list(forms):
        m2 = re.match(r"^(.*\S)\s+band$", f, re.I)
        if m2:
            forms.add(m2.group(1))
    return forms


def variant_keys(raw):
    keys = set()
    for f in surface_forms(raw):
        k = norm(f)
        if k:
            keys.add(k)
    return keys


def display_name(raw):
    """Prefer natural 'The X' order for the canonical display name."""
    raw = (raw or "").strip()
    m = re.match(r"^(.*),\s*(the|a|an)$", raw, re.I)
    if m:
        return "%s %s" % (m.group(2).capitalize(), m.group(1))
    return raw


# ── TSV reading ───────────────────────────────────────────────
def read_tsv(path, skip_hash=False):
    if not path.exists():
        print("WARN: missing source %s" % path, file=sys.stderr)
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    if skip_hash:
        lines = [ln for ln in lines if not ln.lstrip().startswith("#")]
    rows = []
    for row in csv.DictReader(lines, delimiter="\t"):
        rows.append({(k or "").strip(): (v or "").strip()
                     for k, v in row.items() if k})
    return rows


def yt_url(v):
    v = (v or "").strip()
    if not v or v in ("-", "N/A", "n/a"):
        return ""
    if v.startswith("http"):
        return v
    if v.startswith("@"):
        return "https://www.youtube.com/" + v
    return v


# ── load sources ─────────────────────────────────────────────
def blank_rec(name, status, **kw):
    rec = dict(name=name, status=status, decision="", tier="",
               times_seen="", first_seen="", most_recent_seen="",
               spotify="", youtube="")
    rec.update(kw)
    return rec


def load_records():
    recs = []

    for r in read_tsv(ARTISTS):
        name = r.get("Artist", "")
        if name:
            recs.append(blank_rec(name, "seen",
                times_seen=r.get("Times Seen", ""),
                first_seen=r.get("First Seen", ""),
                most_recent_seen=r.get("Most Recent Seen", ""),
                spotify=r.get("Spotify URL", ""),
                youtube=yt_url(r.get("YouTube Channel", ""))))

    for r in read_tsv(FASTTRACK, skip_hash=True):
        name = r.get("Artist", "")
        if name:
            recs.append(blank_rec(name, "fast_track",
                tier=r.get("Tier", ""), spotify=r.get("Spotify URL", "")))

    for r in read_tsv(POTENTIAL):
        name = r.get("Artist", "")
        decision = r.get("Decision", "")
        if name and not SKIP_POTENTIAL_AGGREGATE.search(name):
            recs.append(blank_rec(name, "potential",
                decision=decision, tier=r.get("Tier", "")))
        if HARVEST_POTENTIAL_SUPPORT:
            for tok in r.get("Support", "").split("/"):
                tok = re.sub(r"\s*\+\s*\d*\s*more$", "", tok.strip(), flags=re.I).strip()
                if len(tok) > 2 and not re.fullmatch(r"more", tok, re.I):
                    recs.append(blank_rec(tok, "potential", decision=decision))

    for r in read_tsv(FOLLOWS):
        name = r.get("Artist", "")
        if name:
            recs.append(blank_rec(name, "follow", tier=r.get("Tier", "")))

    return recs


# ── merge by shared variant key (union-find) ──────────────────────────
def merge(recs):
    parent = list(range(len(recs)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    rec_keys = []
    first_seen_key = {}
    for i, rec in enumerate(recs):
        keys = variant_keys(rec["name"])
        rec_keys.append(keys)
        for k in keys:
            if k in first_seen_key:
                union(first_seen_key[k], i)
            else:
                first_seen_key[k] = i

    clusters = {}
    for i in range(len(recs)):
        clusters.setdefault(find(i), []).append(i)
    return list(clusters.values()), rec_keys


# ── cluster -> canonical record ───────────────────────────────────
def rank_of(rec):
    s = rec["status"]
    if s == "seen":
        return 0
    if s == "fast_track":
        return 1
    if s == "potential":
        d = (rec.get("decision", "") or "").lower()
        return 2 if (d.startswith("buy") or d == "choose") else 4
    if s == "follow":
        return 3
    return 5


def pick(members, field, order=STATUS_ORDER):
    for status in order:
        for r in members:
            if r["status"] == status and r.get(field):
                return r[field]
    return ""


def pick_decision(members):
    pots = [m for m in members if m["status"] == "potential" and m.get("decision")]
    if not pots:
        return ""
    pots.sort(key=lambda m: 0 if (m["decision"].lower().startswith("buy")
                                  or m["decision"].lower() == "choose") else 1)
    return pots[0]["decision"]


def build():
    recs = load_records()
    clusters, rec_keys = merge(recs)

    # Deterministic output: order clusters by normalized canonical name.
    prepared = []
    for idx_list in clusters:
        members = [recs[i] for i in idx_list]
        lead = min(members, key=rank_of)
        prepared.append((display_name(lead["name"]), idx_list))
    prepared.sort(key=lambda t: norm(t[0]))

    records = []
    variants = {}
    collisions = []

    for new_id, (cname, idx_list) in enumerate(prepared):
        members = [recs[i] for i in idx_list]
        status = min(members, key=rank_of)["status"]
        rec = {"id": new_id, "canonical": cname, "status": status}
        decision = pick_decision(members)
        tier = pick(members, "tier", TIER_ORDER)
        ts = pick(members, "times_seen")
        fs = pick(members, "first_seen")
        ms = pick(members, "most_recent_seen")
        sp = pick(members, "spotify")
        yt = pick(members, "youtube")
        if decision:
            rec["decision"] = decision
        if tier:
            rec["tier"] = tier
        if ts:
            rec["times_seen"] = ts
        if fs:
            rec["first_seen"] = fs
        if ms:
            rec["most_recent_seen"] = ms
        if sp:
            rec["spotify"] = sp
        if yt:
            rec["youtube"] = yt
        rec["sources"] = sorted({m["status"] for m in members},
                                key=STATUS_ORDER.index)
        records.append(rec)

        for i in idx_list:
            for k in rec_keys[i]:
                if k in variants and variants[k] != new_id:
                    collisions.append((k, records[variants[k]]["canonical"], cname))
                else:
                    variants[k] = new_id

    # Manual aliases (irregular surface forms the rules can't derive).
    if ALIASES.exists():
        for row in read_tsv(ALIASES):
            alias = row.get("Alias", "")
            canon = row.get("Canonical", "")
            if not alias or not canon:
                continue
            target = variants.get(norm(canon))
            if target is None:
                print("WARN alias: canonical not found: '%s' (alias '%s')"
                      % (canon, alias), file=sys.stderr)
                continue
            akey = norm(alias)
            if akey in variants and variants[akey] != target:
                collisions.append((akey, records[variants[akey]]["canonical"],
                                   records[target]["canonical"]))
            variants[akey] = target

    out = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "counts": {"records": len(records), "variants": len(variants)},
        "records": records,
        "variants": dict(sorted(variants.items())),
    }
    OUTPUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")

    print("wrote %s: %d records, %d variants"
          % (OUTPUT.name, len(records), len(variants)), file=sys.stderr)
    if collisions:
        print("\n%d variant collision(s) — review (wrong merge or alias clash):"
              % len(collisions), file=sys.stderr)
        for k, a, b in collisions:
            print("  '%s': %s  <->  %s" % (k, a, b), file=sys.stderr)


if __name__ == "__main__":
    build()
