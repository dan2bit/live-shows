#!/usr/bin/env python3
"""Build data/artist_modal_index.json — the precomputed artist-modal payload (issue #107).

Contract & field sources are frozen in tools/playbooks/DATA_WRITE_PROTOCOLS.md
("artist_modal_index.json — frozen schema"). This script is the *builder* half of the
builder<->renderer interface; app.js renders from the emitted index.

All inputs are PUBLIC, so the affinity score and the whole index are public-safe. The
explicit favorite (issue #116) is never produced here — it merges client-side.

Run:  python3 scripts/build_artist_index.py [--root .] [--out data/artist_modal_index.json]
Regenerated in CI by .github/workflows/artist-modal-index.yml on any payload/score source change.
"""
import argparse
import csv
import json
import math
import os
import re
import unicodedata
from datetime import datetime, timezone

import yaml

SCHEMA_VERSION = 1

# Rank/label for the taste-tier dots + affinity T. follows_master uses "Lower"; the
# potentials file uses "Low" for the same tier -> aliased. Anything else (incl. "Legacy",
# blank, or not-in-follows) has no rank (no dots) and contributes 0 to affinity.
TIER_RANK = {"Strong": 4, "Medium-Strong": 3, "Medium": 2, "Lower": 1}
TIER_ALIASES = {"low": "Lower"}

# Listener tranche labels (5 bands for the 4 config cutoffs). Cosmetic + tunable.
TRANCHE_LABELS = ["niche", "emerging", "mid", "popular", "major"]
DEFAULT_TRANCHES = [5000, 50000, 250000, 1000000]

SUPPORT_SPLIT = re.compile(r"\s*[;/]\s*|\s+w/\s+")  # multi-support separators (not commas)


# ----------------------------------------------------------------------------- helpers
def norm(s):
    """Normalized lookup key — mirrors recStripDia() in recommend.js plus the de-inversion
    build_recommend_index.py applies, so the client and the index agree on keys."""
    if not s:
        return ""
    s = s.strip()
    m = re.match(r"^(.*),\s+(the|a|an)$", s, re.I)  # "Lone Bellow, The" -> "The Lone Bellow"
    if m:
        s = m.group(2) + " " + m.group(1)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"^\s*(the|a|an)\s+", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def slugify(name):
    n = norm(name)
    return n.replace(" ", "-") if n else None


def read_tsv(path, skip_comments=False):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    if skip_comments:
        lines = [ln for ln in lines if not ln.lstrip().startswith("#")]
    lines = [ln for ln in lines if ln != ""]
    if not lines:
        return []
    reader = csv.DictReader(lines, delimiter="\t")
    return list(reader)


def clean(v):
    """Empty / sentinel values -> None."""
    if v is None:
        return None
    v = v.strip()
    return None if v in ("", "-") else v


# ------------------------------------------------------------------------------- loaders
def load_config(root):
    with open(os.path.join(root, "config.yaml"), encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    badges = (cfg.get("badges") or {})
    aff = badges.get("affinity") or {}
    weights = aff.get("weights") or {"tier": 0.35, "seen": 0.40, "goals": 0.25}
    return {
        "weights": weights,
        "tier_points": aff.get("tier_points") or {},
        "fast_track_equiv_shows": aff.get("fast_track_equiv_shows", 1),
        "seen_scale": aff.get("seen_scale", 2.5),
        "goals_split": aff.get("goals_split") or {"hat": 0.6, "book": 0.4},
        "bands": aff.get("bands") or {"high": 0.60, "medium": 0.30},
        "tranches": badges.get("listener_tranches") or DEFAULT_TRANCHES,
    }


def load_aliases(root):
    """recommend_aliases.tsv: extra alias -> canonical mappings (normalized)."""
    out = {}
    for row in read_tsv(os.path.join(root, "data/recommend_aliases.tsv"), skip_comments=True):
        # DictReader keys off the first data row's header; be tolerant of the layout.
        cells = list(row.values())
        if len(cells) >= 2 and cells[0] and cells[1]:
            out[norm(cells[0])] = norm(cells[1])
    return out


# ------------------------------------------------------------------------------- sightings
def build_sightings(root, canon):
    """Return {artist_key: [ {date, venue, via, photo_url, role} ]} from the canonical
    ledger: history/*.tsv + current.tsv (attended) + seen_with.tsv. Keyed by the
    alias-aware canonical form so variant spellings attach to one artist. Combined-bill
    components are attributed via the artists.tsv Via column."""
    sight = {}

    def add(key, date, venue, via, photo, role):
        if not key or not date:
            return
        sight.setdefault(key, []).append(
            {"date": date, "venue": venue, "via": via, "photo_url": photo, "role": role}
        )

    def split_support(s):
        s = clean(s)
        return [p.strip() for p in SUPPORT_SPLIT.split(s) if p.strip()] if s else []

    # history/*.tsv
    hist_dir = os.path.join(root, "data/history")
    for fn in sorted(os.listdir(hist_dir)) if os.path.isdir(hist_dir) else []:
        if not fn.endswith(".tsv"):
            continue
        for r in read_tsv(os.path.join(hist_dir, fn)):
            date = clean(r.get("Show Date"))
            venue = clean(r.get("Venue"))
            photo = clean(r.get("Photo URL"))
            head = clean(r.get("Artist"))
            if head:
                add(canon(head), date, venue, None, photo, "headliner")
            for sup in split_support(r.get("Supporting Acts")):
                add(canon(sup), date, venue, head, photo, "support")

    # current.tsv — attended rows only (2026 shows live here, not in history/)
    for r in read_tsv(os.path.join(root, "data/live_shows_current.tsv")):
        if (r.get("Status") or "").strip().lower() != "attended":
            continue
        date = clean(r.get("Show Date"))
        venue = clean(r.get("Venue Name"))
        photo = clean(r.get("Photo URL"))
        head = clean(r.get("Artist"))
        if head:
            add(canon(head), date, venue, None, photo, "headliner")
        for sup in split_support(r.get("Supporting Artist")):
            add(canon(sup), date, venue, head, photo, "support")

    # seen_with.tsv — sidemen / component sightings (no venue/photo of their own)
    for r in read_tsv(os.path.join(root, "data/seen_with.tsv")):
        date = clean(r.get("Show Date"))
        head = clean(r.get("Headliner"))
        who = clean(r.get("Seen With"))
        if who:
            add(canon(who), date, None, head, None, "seen_with")

    return sight


def dedup_log(rows):
    """Collapse to one entry per date; prefer the richest (headliner > support > via >
    seen_with) and any row that carries a photo."""
    role_pri = {"headliner": 3, "support": 2, "seen_with": 1}
    by_date = {}
    for r in rows:
        d = r["date"]
        cur = by_date.get(d)
        if cur is None:
            by_date[d] = dict(r)
            continue
        # prefer a photo, then a higher-priority role
        better = (r["photo_url"] and not cur["photo_url"]) or (
            role_pri.get(r["role"], 0) > role_pri.get(cur["role"], 0)
        )
        if better:
            keep_photo = cur["photo_url"] or r["photo_url"]
            by_date[d] = dict(r)
            by_date[d]["photo_url"] = r["photo_url"] or keep_photo
        elif r["photo_url"] and not cur["photo_url"]:
            cur["photo_url"] = r["photo_url"]
    out = sorted(by_date.values(), key=lambda x: x["date"], reverse=True)
    return out


# ------------------------------------------------------------------------------- main build
def build(root):
    cfg = load_config(root)
    aliases = load_aliases(root)

    def canon(name):
        n = norm(name)
        return aliases.get(n, n)

    # --- source tables keyed by normalized/canonical name ---
    artists = {}
    for r in read_tsv(os.path.join(root, "data/artists.tsv")):
        k = canon(r.get("Artist", ""))
        if k:
            artists[k] = r
    follows = {canon(r["Artist"]): r.get("Tier", "").strip()
               for r in read_tsv(os.path.join(root, "tools/research/follows/follows_master.tsv"))
               if r.get("Artist")}
    pots = {}
    for r in read_tsv(os.path.join(root, "data/live_shows_potential.tsv")):
        if r.get("Artist"):
            pots.setdefault(canon(r["Artist"]), r)
    fast = {canon(r["Artist"]) for r in read_tsv(os.path.join(root, "data/fast_track.tsv")) if r.get("Artist")}
    books = {canon(r["Artist"]): r
             for r in read_tsv(os.path.join(root, "data/show_goals/autograph_books_combined.tsv"))
             if r.get("Artist")}
    hat_elig = {canon(r["Artist"]): ((r.get("Hat Eligible") or "").strip().lower() == "yes")
                for r in read_tsv(os.path.join(root, "data/show_goals/hat_eligibility.tsv"))
                if r.get("Artist")}
    # Hat completion from canonical signatures (#115): a signature credits the signer,
    # unless attributed "of <band>" (band member) -> the band gets the completed state.
    hat_completed = set()
    for r in read_tsv(os.path.join(root, "data/show_goals/hat_signatures.tsv")):
        signer = (r.get("signer") or "").strip()
        if not signer:
            continue
        attr = (r.get("attribution") or "").strip()
        target = attr[3:].strip() if attr.lower().startswith("of ") else signer
        hat_completed.add(canon(target))

    with open(os.path.join(root, "data/artist_spotify.json"), encoding="utf-8") as fh:
        spotify_raw = json.load(fh)
    spotify = {canon(name): entry for name, entry in spotify_raw.items()}

    sightings = build_sightings(root, canon)

    # --- display-name resolution + universe ---
    display = {}

    def see(name):
        k = canon(name)
        if k and k not in display and clean(name):
            display[k] = name.strip()
        return k

    for r in read_tsv(os.path.join(root, "data/artists.tsv")):
        see(r.get("Artist", ""))
    for name in spotify_raw:
        see(name)
    for k in list(follows) + list(pots) + list(fast) + list(books):
        display.setdefault(k, k)  # fall back to the key if no nicer form seen
    for r in read_tsv(os.path.join(root, "data/live_shows_current.tsv")):
        see(r.get("Artist", ""))
        for s in SUPPORT_SPLIT.split(clean(r.get("Supporting Artist")) or ""):
            if s.strip():
                see(s)
    for r in read_tsv(os.path.join(root, "data/live_shows_potential.tsv")):
        see(r.get("Artist", ""))
    for r in read_tsv(os.path.join(root, "data/seen_with.tsv")):
        see(r.get("Seen With", ""))

    universe = set(display)

    def tier_for(k):
        raw = follows.get(k) or (pots.get(k, {}).get("Tier") if k in pots else None)
        raw = (raw or "").strip()
        if not raw:
            return None
        return TIER_ALIASES.get(raw.lower(), raw)

    def listener_for(entry):
        lf = (entry or {}).get("lastfm") or {}
        n = lf.get("listeners")
        if not isinstance(n, int):
            return None
        cuts = cfg["tranches"]
        idx = sum(1 for c in cuts if n >= c)
        label = TRANCHE_LABELS[min(idx, len(TRANCHE_LABELS) - 1)]
        return {"tranche": label, "raw": n}

    # --- collect per-artist sightings incl. Via bill-borrow, then compute ---
    index = {}
    for k in sorted(universe):
        a = artists.get(k, {})
        sp = spotify.get(k, {})
        lf = (sp.get("lastfm") or {})
        bk = books.get(k, {})
        disp = display.get(k, k)

        # sightings (own) + Via bill-borrow (component artists inherit the bill's sightings)
        rows = list(sightings.get(k, []))
        via_bill = clean(a.get("Via"))
        if via_bill:
            for s in sightings.get(canon(via_bill), []):
                rows.append({**s, "via": via_bill, "role": "via"})
        log = dedup_log(rows)
        count = len(log)
        first = min((r["date"] for r in log), default=None)
        recent = max((r["date"] for r in log), default=None)
        if count <= 1:
            recent = None

        # goals (signings)
        hat_signed = k in hat_completed          # #115: sourced from hat_signatures.tsv
        hat_eligible = hat_elig.get(k)           # True / False / None (absent -> not-yet suppressed)
        in_aps = (bk.get("In APS") or "").strip().lower() == "yes"
        in_rhbs = (bk.get("In RHBS") or "").strip().lower() == "yes"
        aps_signed = (bk.get("APS Signed") or "").strip().lower() == "yes"
        rhbs_signed = (bk.get("RHBS Signed") or "").strip().lower() == "yes"
        book_signed = aps_signed or rhbs_signed
        in_book = in_aps or in_rhbs

        # tier
        tlabel = tier_for(k)
        trank = TIER_RANK.get(tlabel) if tlabel else None
        tier_obj = {"label": tlabel, "rank": trank} if tlabel else None

        # affinity
        is_fast = k in fast
        w = cfg["weights"]
        gs = cfg["goals_split"]
        T = float(cfg["tier_points"].get(tlabel, 0.0)) if tlabel else 0.0
        S = 1 - math.exp(-count / cfg["seen_scale"]) if count > 0 else 0.0
        floor = 1 - math.exp(-cfg["fast_track_equiv_shows"] / cfg["seen_scale"]) if is_fast else 0.0
        Seff = max(S, floor)
        G = gs["hat"] * (1 if hat_signed else 0) + gs["book"] * (1 if book_signed else 0)
        gate = (tlabel is not None) or count > 0 or hat_signed or book_signed or is_fast
        if gate:
            score = max(0.0, min(1.0, w["tier"] * T + w["seen"] * Seff + w["goals"] * G))
            band = "high" if score >= cfg["bands"]["high"] else ("medium" if score >= cfg["bands"]["medium"] else "low")
            affinity = {"score": round(score, 3), "band": band}
        else:
            affinity = None

        # badges
        if hat_signed:
            hat_badge = "completed"          # completion wins (hat_signatures.tsv)
        elif hat_eligible:
            hat_badge = "not_yet"            # eligible (hat_eligibility.tsv), unsigned
        else:
            hat_badge = "absent"             # ineligible or eligibility unknown
        if not in_book:
            book_badge = "absent"
        else:
            book_badge = "completed" if book_signed else "not_yet"
        try:
            vip = int((a.get("VIP Count") or "0").strip() or 0)
        except ValueError:
            vip = 0
        photo_count = sum(1 for r in log if r["photo_url"])

        # latest release
        lr = sp.get("latest_release")
        latest_release = None
        if lr and lr.get("name"):
            latest_release = {
                "name": lr.get("name"),
                "type": lr.get("type"),
                "date": lr.get("date"),
                "url": lr.get("url"),
                "image_url": None,  # album art resolved at build time later (P2 with spotify_cache image_url)
            }

        # links
        mbid = clean(lf.get("mbid"))
        spotify_url = clean(sp.get("spotify_url")) or clean(a.get("Spotify URL"))
        yt = clean(a.get("YouTube Channel"))
        links = {
            "spotify": spotify_url,
            "youtube": yt,
            "lastfm": clean(lf.get("url")),
            "musicbrainz": f"https://musicbrainz.org/artist/{mbid}" if mbid else None,
            "bandsintown": f"https://www.bandsintown.com/search?query={disp.replace(' ', '+')}",
            "seated": None,
            "setlistfm": f"https://www.setlist.fm/search?query={disp.replace(' ', '+')}",
        }

        index[k] = {
            "name": disp,
            "slug": slugify(disp),
            "spotify_id": clean(sp.get("spotify_id")),
            "mbid": mbid,
            "image_url": None,     # build-time resolved later (spotify_cache image_url); null in P1
            "banner_url": None,    # P2
            "genres": [t.lower() for t in (lf.get("tags") or [])[:3]],
            "listener": listener_for(sp),
            "tier": tier_obj,
            "seen": {
                "count": count,
                "first": first,
                "recent": recent,
                "show_log": [
                    {"date": r["date"], "venue": r["venue"], "via": r["via"], "photo_url": r["photo_url"]}
                    for r in log
                ],
            },
            "fast_track": is_fast,
            "affinity": affinity,
            "badges": {
                "hat": hat_badge,
                "book": book_badge,
                "book_detail": {
                    "aps": {"in": in_aps, "signed": aps_signed, "page": clean(bk.get("APS Page"))},
                    "rhbs": {"in": in_rhbs, "signed": rhbs_signed},
                },
                "vip": vip,
                "photo": photo_count,
            },
            "latest_release": latest_release,
            "_similar_names": (lf.get("similar") or [])[:8],  # resolved in pass 2, then removed
            "links": links,
        }

    # pass 2 — resolve "similar" in_tracker against the finished universe
    keys = set(index)
    for k, obj in index.items():
        sims = []
        for nm in obj.pop("_similar_names"):
            sk = canon(nm)
            here = sk in keys
            sims.append({"name": nm, "in_tracker": here, "slug": slugify(nm) if here else None})
        obj["similar"] = sims

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artists": index,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="data/artist_modal_index.json")
    args = ap.parse_args()
    out = build(args.root)
    path = os.path.join(args.root, args.out)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=0, separators=(",", ":"))
        fh.write("\n")
    print(f"wrote {path}: {len(out['artists'])} artists")


if __name__ == "__main__":
    main()
