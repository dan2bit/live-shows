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


def credit_targets(signer, attribution):
    """Return the list of artist-name inputs credited by an event_log signature row,
    per the vocabulary in docs/GOALS_SPEC.md § Source binding syntax.

    The signer is always credited; the attribution controls whether a second artist
    is also credited:
      empty / "self"      -> signer only
      "of <band>"         -> signer AND <band>       (signer is a band member)
      "<name> entry"      -> signer AND <name>       (book prints signer under an alias)
      "w/ <band>"         -> signer only              (signer signed at band's show)
      "co-bill w/ <band>" -> signer only              (signer signed at co-billed event)
      any other freeform  -> signer only              (default)
    """
    a = (attribution or "").strip()
    targets = [signer] if signer else []
    al = a.lower()
    if al.startswith("of "):
        band = a[3:].strip()
        if band:
            targets.append(band)
    elif al.endswith(" entry"):
        alias = a[:-len(" entry")].strip()
        if alias:
            targets.append(alias)
    return targets


def validate_goals_config(cfg):
    """#165: the flat G-term has one knob — badges.affinity.goals_decay — instead of
    per-goal weights. Validate it lies strictly between 0 and 1 (fails the build
    otherwise), and warn loudly about obsolete show_goals weight fields: they are
    IGNORED since #165, so leaving them in config.yaml is harmless but misleading."""
    d = cfg["goals_decay"]
    if not (0.0 < d < 1.0):
        raise ValueError(
            f"config.yaml: badges.affinity.goals_decay must be strictly between 0 and 1, "
            f"got {d}. See docs/GOALS_SPEC.md § Affinity contribution."
        )
    stale = [g.get("key", "?") for g in (cfg.get("show_goals") or [])
             if isinstance(g, dict) and "weight" in g]
    if stale:
        print(f"WARNING: show_goals 'weight' fields are obsolete since #165 and ignored "
              f"({', '.join(stale)}) — remove them from config.yaml.")


# ------------------------------------------------------------------------------- loaders
def load_config(root):
    with open(os.path.join(root, "config.yaml"), encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    badges = (cfg.get("badges") or {})
    aff = badges.get("affinity") or {}
    weights = aff.get("weights") or {"tier": 0.35, "seen": 0.40, "goals": 0.25}

    # #165: the G-term is a flat diminishing series over completion events (G = 1 − d^n).
    # Its only knob is goals_decay (first completion = 1−d ≈ the old hat weight at
    # d=0.4; the k-th adds d^(k−1) − d^k). Per-goal weights — the old goals_split dict
    # and show_goals[].weight — are obsolete and ignored; see validate_goals_config.
    return {
        "weights": weights,
        "tier_points": aff.get("tier_points") or {},
        "fast_track_equiv_shows": aff.get("fast_track_equiv_shows", 1),
        "seen_scale": aff.get("seen_scale", 2.5),
        "goals_decay": float(aff.get("goals_decay", 0.4)),
        "show_goals": cfg.get("show_goals") or [],
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
    validate_goals_config(cfg)
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
    # Book eligibility (#85 S2): what artists are printed in either book + per-book
    # In/Page. Signed columns moved out to book_signatures.tsv (event log).
    books = {canon(r["Artist"]): r
             for r in read_tsv(os.path.join(root, "data/show_goals/autograph_books_eligibility.tsv"))
             if r.get("Artist")}

    # Google Photos albums (#117): Artist -> shareable album URL. Keyed via canon() so
    # the join runs against the built universe (which includes seen_with-only names,
    # e.g. Brandon Miller) — never against artists.tsv. Album URL is deliberately NOT
    # unique across rows: a shared band album (Brandon Miller / Danielle Nicole) is
    # legitimate, so no uniqueness validation here or anywhere.
    albums = {}
    for r in read_tsv(os.path.join(root, "data/show_goals/artist-albums.tsv")):
        art, aurl = clean(r.get("Artist")), clean(r.get("Album URL"))
        if art and aurl:
            albums[canon(art)] = aurl

    # Hat eligibility (#115). Header column is "Eligible" post-#85 (uniform across goals).
    # Compat: also accept legacy "Hat Eligible" column name during any transition window.
    hat_elig = {}
    for r in read_tsv(os.path.join(root, "data/show_goals/hat_eligibility.tsv")):
        if not r.get("Artist"):
            continue
        raw = (r.get("Eligible") or r.get("Hat Eligible") or "").strip().lower()
        hat_elig[canon(r["Artist"])] = (raw == "yes")

    # Hat + book completion from canonical event logs (#115, #85). Attribution vocabulary
    # per docs/GOALS_SPEC.md § Source binding syntax; parsed uniformly via credit_targets.
    hat_completed = set()
    for r in read_tsv(os.path.join(root, "data/show_goals/hat_signatures.tsv")):
        signer = (r.get("signer") or "").strip()
        if not signer:
            continue
        for tgt in credit_targets(signer, r.get("attribution")):
            k = canon(tgt)
            if k:
                hat_completed.add(k)

    # Book completion, tracked per-book (APS/RHBS) so book_detail can carry accurate
    # signed states downstream. book_signed (aggregate) is derived per-artist below.
    book_completed = {}  # {canon_key: {"APS": bool, "RHBS": bool}}
    for r in read_tsv(os.path.join(root, "data/show_goals/book_signatures.tsv")):
        signer = (r.get("signer") or "").strip()
        which = (r.get("book") or "").strip().upper()
        if not signer or which not in ("APS", "RHBS"):
            continue
        for tgt in credit_targets(signer, r.get("attribution")):
            k = canon(tgt)
            if not k:
                continue
            entry = book_completed.setdefault(k, {"APS": False, "RHBS": False})
            entry[which] = True

    # #165: flat G-term completion-event counts, driven by the config show_goals list
    # (generic — a fork adding an event_log goal gets affinity contribution with no
    # code change here). Every event_log row crediting an artist is ONE completion
    # event: Book ×2 (APS + RHBS rows) is two events, and two band members signing
    # "of <band>" credits the band twice — each signature is an event. column:Photo URL
    # resolves later from the artist's deduped show_log (distinct photographed shows);
    # other column:/interaction: sources contribute 0 to G for now (per-artist event
    # counts for them aren't derived — noted in GOALS_SPEC § Affinity contribution).
    goal_event_counts = {}  # {canon_key: int} — event_log events only
    for g in cfg["show_goals"]:
        src = (g.get("source") or "") if isinstance(g, dict) else ""
        if not src.startswith("event_log:"):
            continue
        ev_name = src.split(":", 1)[1].strip() + ".tsv"
        for r in read_tsv(os.path.join(root, "data/show_goals", ev_name)):
            signer = (r.get("signer") or "").strip()
            if not signer:
                continue
            for tgt in credit_targets(signer, r.get("attribution")):
                kk = canon(tgt)
                if kk:
                    goal_event_counts[kk] = goal_event_counts.get(kk, 0) + 1

    # Per-artist per-date completed-goal keys, for baking into show_log entries so
    # S4 (app.js row badges) can join client-side without extra fetches. Only event_log
    # sources contribute here; column/interaction goals are per-row and handled at render.
    signature_events = {}  # {canon_key: {date: set(goal_key)}}
    for goal_key, ev_file in (("hat", "hat_signatures.tsv"),
                              ("book", "book_signatures.tsv")):
        for r in read_tsv(os.path.join(root, "data/show_goals", ev_file)):
            signer = (r.get("signer") or "").strip()
            date = (r.get("show_date") or "").strip()
            if not signer or not date:
                continue
            for tgt in credit_targets(signer, r.get("attribution")):
                k = canon(tgt)
                if k:
                    signature_events.setdefault(k, {}).setdefault(date, set()).add(goal_key)

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
        _book_state = book_completed.get(k, {})  # #85 S3: sourced from book_signatures.tsv
        aps_signed = _book_state.get("APS", False)
        rhbs_signed = _book_state.get("RHBS", False)
        book_signed = aps_signed or rhbs_signed
        in_book = in_aps or in_rhbs

        # tier
        tlabel = tier_for(k)
        trank = TIER_RANK.get(tlabel) if tlabel else None
        tier_obj = {"label": tlabel, "rank": trank} if tlabel else None

        # photo completions = distinct photographed shows in the deduped log — the
        # #117 badge metric, never times_seen. Needed by both affinity and badges.
        photo_count = sum(1 for r in log if r["photo_url"])

        # affinity — #165 flat G-term: ONE diminishing series over all goal completion
        # events (signature events + photographed shows), order- and type-independent.
        # First completion = 1−d, k-th adds d^(k−1) − d^k; asymptotic below 1.0 so the
        # earned-max vs #116-starred distinction is preserved.
        is_fast = k in fast
        w = cfg["weights"]
        T = float(cfg["tier_points"].get(tlabel, 0.0)) if tlabel else 0.0
        S = 1 - math.exp(-count / cfg["seen_scale"]) if count > 0 else 0.0
        floor = 1 - math.exp(-cfg["fast_track_equiv_shows"] / cfg["seen_scale"]) if is_fast else 0.0
        Seff = max(S, floor)
        n_goal = goal_event_counts.get(k, 0) + photo_count
        G = 1 - cfg["goals_decay"] ** n_goal if n_goal > 0 else 0.0
        gate = (tlabel is not None) or count > 0 or n_goal > 0 or is_fast
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

        # latest release
        lr = sp.get("latest_release")
        latest_release = None
        if lr and lr.get("name"):
            latest_release = {
                "name": lr.get("name"),
                "type": lr.get("type"),
                "date": lr.get("date"),
                "url": lr.get("url"),
                "image_url": lr.get("image_url"),  # album cover from spotify_cache (#125)
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
            "image_url": clean(sp.get("image_url")),  # artist portrait from spotify_cache (#125)
            "banner_url": None,    # P2
            "genres": [t.lower() for t in (lf.get("tags") or [])[:3]],
            "listener": listener_for(sp),
            "tier": tier_obj,
            "seen": {
                "count": count,
                "first": first,
                "recent": recent,
                "show_log": [
                    {
                        "date": r["date"], "venue": r["venue"], "via": r["via"],
                        "photo_url": r["photo_url"],
                        # #85 S3: event_log goal completions at this show for this artist,
                        # baked so app.js row badges can join without extra fetches.
                        # Column/interaction goals stay per-row (not baked here).
                        "goals": sorted(signature_events.get(k, {}).get(r["date"], set())),
                    }
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
                # #117: Google Photos album link for the photo badge. Nullable; present
                # only when artist-albums.tsv has a row. Additive to the frozen schema.
                "photo_album": albums.get(k),
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
