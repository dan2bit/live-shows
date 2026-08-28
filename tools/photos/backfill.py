#!/usr/bin/env python3
"""
backfill.py — Phase-1 machinery for the Google Photos → Immich backfill.

Companion to immich.py (the REST wrapper); this file holds the backfill
workflow itself, in three subcommands run in this order:

  drift     Sanity-check Immich person names against the show library's
            canonical artist names before the face signal is trusted.
            Buckets: exact canonical match, alias-resolvable, placeholder
            (`played with <frontman> (role)` — intentional, never drift),
            sideman roster (real people with no artists.tsv row — expected),
            and true drift (near-miss spellings needing a rename or alias).

  enrich    Lift crosswalk rows from confidence 0/1 toward 2 by gathering
            agreeing signals per candidate asset: capture date, face match
            (named person resolved through the same rules as drift), landed
            album, caption text, and — for memorabilia — OCR text matched
            against the bootleg catalog's song titles to recover a show date
            the EXIF can't supply. Confirmed rows (confidence >= 2) are never
            touched, so nothing is re-litigated.

  winnow    Serve the crosswalk as a local page where each row shows the
            Google Photos image beside its Immich candidates, and a click
            confirms the match to level 3. Writes only the decision
            columns; see photo_winnow.py.

  mint      Turn confirmed rows into Immich share links: every confidence-3
            row with a match_id and no immich_link gets one. Separate from
            the confirming pass on purpose - a mis-click stays a one-cell
            undo instead of an orphaned link on the server. Dry-run by
            default; --apply mints.

  rewrite   Apply confirmed (confidence 3) rows to the library TSVs by
            replacing each Google Photos link with its Immich share link.
            The replacement is a raw text substitution on the file — headers,
            BOMs, comment blocks, and column padding all pass through
            byte-identical. Idempotent: once rewritten, the Google link no
            longer exists to match. Dry-run by default; --apply writes.

Confidence scale (crosswalk `confidence` column):
  0 unmatched · 1 weak (single signal) · 2 strong (>= 2 agreeing signals,
  machine) · 3 confirmed (human-verified, Immich link minted). Only level-3
  rows are ever written to the library TSVs, and only by `rewrite`.

Face-signal conventions honored here (see docs and the private runbook):
  - `played with <frontman> (role)` people are placeholders: never artist
    matches, never drift — but they DO carry show-locator value, so enrich
    may use them as a date/show signal for the frontman's shows.
  - Hidden people never appear in the named-people listing; nothing here
    consumes them.

House TSV rules apply: plain tab-joined lines, LF endings, never the csv
module. Requires the same environment as immich.py (IMMICH_API_KEY) for the
server-facing paths; `drift --people-json` and `rewrite` run offline.
"""

import argparse
import difflib
import json
import os
import re
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", ".."))
sys.path.insert(0, _SCRIPT_DIR)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import immich  # noqa: E402  (sibling module; provides the REST surface)
from name_forms import goal_norm, variant_keys  # noqa: E402

CROSSWALK = os.path.join(_SCRIPT_DIR, "backfill_crosswalk.tsv")

PLACEHOLDER_RE = re.compile(r"^played with\s+.+\(.+\)\s*$", re.I)

# The library files that carry Google Photos links, with the column that
# holds them. `rewrite` uses this only for reporting — the substitution
# itself is textual — and `enrich` uses the source prefix to classify rows.
LINK_SOURCES = [
    ("data/show_goals/artist-photos.tsv", "Share Link"),
    ("data/live_shows_current.tsv", "Photo URL"),
    ("data/show_goals/item_log.tsv", "photo_ref"),
]
HISTORY_DIR = "data/history"


# ── shared loaders ─────────────────────────────────────────────────────────

def _read_rows(relpath):
    return immich._read_tsv_rows(relpath)


def _canonical_artists():
    """Canonical artist names from artists.tsv, keyed by every automatic
    spelling variant — not just the literal row spelling. The variant rules
    (drop trailing " Band", de-invert "X, The") only expand a name they see,
    so a person named "Ally Venable" can never generate "Ally Venable Band";
    the expansion has to happen on the canonical side too, or the resolver
    only works in one direction. Primary keys win on collision so a variant
    of one artist can never shadow another artist's own spelling."""
    rows = [(row.get("Artist") or "").strip()
            for row in _read_rows("data/artists.tsv")]
    primary = {goal_norm(name): name for name in rows if name}
    out = dict(primary)
    for name in rows:
        if not name:
            continue
        for vk in variant_keys(name):
            if vk not in primary:
                out.setdefault(vk, name)
    return out


def _alias_map():
    """recommend_aliases.tsv alias -> canonical, keyed by goal_norm(alias)."""
    out = {}
    path = os.path.join(_ROOT, "data", "recommend_aliases.tsv")
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8-sig") as f:
        lines = [ln.rstrip("\n") for ln in f
                 if ln.strip() and not ln.startswith("#")]
    for ln in lines[1:]:
        parts = ln.split("\t")
        if len(parts) >= 2 and parts[0].strip() and parts[1].strip():
            out[goal_norm(parts[0])] = parts[1].strip()
    return out


def _resolve_artist(name, canon, aliases):
    """Resolve a free-form artist string to a canonical artists.tsv name,
    via exact match, alias row, or automatic spelling variants. Returns
    (canonical_name, how) or (None, None)."""
    key = goal_norm(name)
    if key in canon:
        resolved = canon[key]
        how = "exact" if goal_norm(resolved) == key else "variant"
        return resolved, how
    if key in aliases:
        target = goal_norm(aliases[key])
        if target in canon:
            return canon[target], "alias"
    for vk in variant_keys(name):
        if vk in canon:
            return canon[vk], "variant"
        if vk in aliases:
            target = goal_norm(aliases[vk])
            if target in canon:
                return canon[target], "alias"
    return None, None


# ── drift ──────────────────────────────────────────────────────────────────

def cmd_drift(args):
    if args.people_json:
        with open(args.people_json, encoding="utf-8") as f:
            payload = json.load(f)
        everyone = payload.get("people", payload if isinstance(payload, list) else [])
        named = [p for p in everyone if p.get("name")]
    else:
        named = immich.people(named_only=True)

    canon = _canonical_artists()
    aliases = _alias_map()

    buckets = {"exact": [], "alias": [], "variant": [],
               "placeholder": [], "sideman": [], "drift": []}

    for person in sorted(named, key=lambda p: (p.get("name") or "").lower()):
        name = (person.get("name") or "").strip()
        if PLACEHOLDER_RE.match(name):
            buckets["placeholder"].append({"person": name})
            continue
        resolved, how = _resolve_artist(name, canon, aliases)
        if resolved:
            entry = {"person": name, "canonical": resolved}
            buckets[how].append(entry)
            if how != "exact" or resolved != name:
                # spelled differently from the canonical row — flag near-miss
                if resolved != name:
                    entry["note"] = "resolves, but spelling differs from artists.tsv"
            continue
        near = difflib.get_close_matches(name, canon.values(), n=2, cutoff=0.82)
        if near:
            buckets["drift"].append({"person": name, "near": near})
        else:
            buckets["sideman"].append({"person": name})

    report = {k: v for k, v in buckets.items() if v}
    report["summary"] = {k: len(v) for k, v in buckets.items()}
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if buckets["drift"]:
        print(f"\n{len(buckets['drift'])} name(s) look like drift - rename the "
              "Immich person or add a recommend_aliases.tsv row.",
              file=sys.stderr)
        return 1
    print("\nno drift: every named person is canonical, alias-resolvable, "
          "a placeholder, or an expected sideman.", file=sys.stderr)
    return 0


# ── enrich ─────────────────────────────────────────────────────────────────

# Channel video-title grammar: `<Artist> LIVE - <Song> (bootleg)[ trailer]`
# (legacy `(bootleg - qualifier)` variants share the same anchor). The catalog
# TSV has no artist column - both artist and song live inside the title.
_CATALOG_TITLE_RE = re.compile(
    r"^(?P<artist>.+?)\s+LIVE\s*-\s*(?P<song>.+?)\s*\(bootleg", re.I)
_DESC_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_DESC_US_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b")


def _catalog_songs_by_artist():
    """(song, show_date) pairs from the bootleg catalog TSV, keyed by
    normalized artist. Artist and song are parsed from the video title per
    the channel grammar; the show date comes from the description slug
    (ISO or M/D/YY), falling back to blank - never the upload date, which
    can trail the show by days."""
    rows = _read_rows("tools/youtube/youtube_videos.tsv")
    out, unparsed = {}, 0
    for row in rows:
        m = _CATALOG_TITLE_RE.match(row.get("title") or "")
        if not m:
            unparsed += 1
            continue
        desc = row.get("description") or ""
        date = ""
        iso = _DESC_ISO_DATE_RE.search(desc)
        if iso:
            date = iso.group(1)
        else:
            us = _DESC_US_DATE_RE.search(desc)
            if us:
                mo, dy, yr = (int(us.group(1)), int(us.group(2)),
                              2000 + int(us.group(3)))
                date = f"{yr:04d}-{mo:02d}-{dy:02d}"
        out.setdefault(goal_norm(m.group("artist")), []).append(
            (m.group("song").strip(), date))
    if rows and not out:
        print("warning: no youtube_videos.tsv title matched the channel "
              "grammar - OCR song matching disabled", file=sys.stderr)
    elif unparsed:
        print(f"note: {unparsed} catalog title(s) did not match the channel "
              "grammar (legacy or non-song uploads) - skipped", file=sys.stderr)
    return out


def _norm_text(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())).strip()


def _name_in_text(term, text):
    """Whole-word containment of a normalized name in normalized OCR text.
    A bare substring test lets a short surname match inside a longer word -
    "Fish" inside "Kingfish" - which silently attaches one artist's
    memorabilia to another artist's row. Both sides are already lowercase,
    alphanumeric and single-spaced, so padding with spaces is a sufficient
    boundary test, and it treats a multi-word name as one phrase."""
    if not term or not text:
        return False
    return f" {term} " in f" {text} "


def _ocr_text(asset_id):
    try:
        payload = immich.ocr(asset_id)
    except SystemExit:
        return ""
    if isinstance(payload, dict):
        parts = payload.get("blocks") or payload.get("results") or []
        if isinstance(parts, list):
            texts = [p.get("text", "") if isinstance(p, dict) else str(p)
                     for p in parts]
            return " ".join(t for t in texts if t)
        return str(payload.get("text", ""))
    if isinstance(payload, list):
        return " ".join(p.get("text", "") if isinstance(p, dict) else str(p)
                        for p in payload)
    return str(payload or "")


# The server has no OCR search endpoint (POST /search/ocr 404s on this
# version), so memorabilia candidate discovery sweeps the landed album(s)
# with per-asset ocr() calls instead. The sweep result is cached locally -
# the corpus is stable (the batch import is done) and re-fetching a hundred
# OCR payloads per run would be pure waste. Delete the cache file to force
# a re-sweep after new uploads or an OCR job re-run.
_OCR_CACHE = os.path.join(_SCRIPT_DIR, ".ocr_cache.json")
_MEMORABILIA_ALBUM_HINTS = ("memorabilia", "hat detail")


def _memorabilia_ocr_corpus():
    """asset_id -> normalized OCR text for every asset in the memorabilia
    landed album(s), cached in .ocr_cache.json (gitignored)."""
    cache = {}
    if os.path.exists(_OCR_CACHE):
        with open(_OCR_CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    album_ids = [a["id"] for a in immich.albums()
                 if any(h in (a.get("albumName") or "").lower()
                        for h in _MEMORABILIA_ALBUM_HINTS)]
    if not album_ids:
        print("warning: no memorabilia album found on the server - "
              "OCR candidate discovery disabled", file=sys.stderr)
        return cache
    fetched = 0
    for aid in album_ids:
        for asset in immich.search_metadata(album_id=aid):
            asset_id = asset["id"]
            if asset_id in cache:
                continue
            cache[asset_id] = _norm_text(_ocr_text(asset_id))
            fetched += 1
    if fetched:
        with open(_OCR_CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        print(f"note: OCR'd {fetched} memorabilia asset(s) into the local "
              "cache", file=sys.stderr)
    return cache


# Browser-harvested Google Photos captions (gp_scrape.tsv). The GP API is
# dead and share URLs are opaque, but the share pages still server-render
# the caption - and the captions carry the show identity (artist, venue,
# date) in prose. Harvested via authenticated same-origin fetch in the
# browser; the key is the unique photo/share id substring of the link.
_CAP_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_CAP_US = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
_CAP_ARTIST = re.compile(r"^(.{3,60}?)\s+(?:@|at)\s+", re.I)
# Google Photos renders a tagged-person mention as a literal "(tagged)" in
# the harvested caption, so the leading phrase is sometimes a placeholder
# rather than a name. Those rows take their artist from the crosswalk
# source context instead of from the caption.
_CAP_TAGGED = re.compile(r"\(tagged\)", re.I)


def _gp_scrape():
    """link_key -> caption from the harvested scrape file."""
    out = {}
    for row in _read_rows("tools/photos/gp_scrape.tsv"):
        key = (row.get("link_key") or "").strip()
        caption = (row.get("caption") or "").strip()
        if key and caption:
            out[key] = caption
    return out


def _caption_for(link, scrape):
    for key, caption in scrape.items():
        if key in link:
            return caption
    return None


def _caption_date(caption):
    m = _CAP_ISO.search(caption)
    if m:
        return m.group(1)
    m = _CAP_US.search(caption)
    if m:
        mo, dy, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yr < 100:
            yr += 2000
        return f"{yr:04d}-{mo:02d}-{dy:02d}"
    return None


def _item_log_index():
    """seq -> (signer, show_date) from the item log, so an item_log crosswalk
    row (whose source carries only the seq) still yields artist and date."""
    out = {}
    for row in _read_rows("data/show_goals/item_log.tsv"):
        seq = (row.get("seq") or "").strip()
        if seq:
            out[seq] = ((row.get("signer") or "").strip(),
                        (row.get("show_date") or "").strip())
    return out


# Caption shapes seen in artist-photos.tsv. Most are "<name> @ <venue> <date>"
# or the same with "at"; the rest lead with the name and then qualify it
# ("Ori Naftaly of Southern Avenue", "Tikyra Jackson, drummer for ...",
# "Sonny Landreth - Hamilton Live"). The qualifier form usually names a
# sideman rather than the billed artist, which is still worth extracting -
# sidemen have faces in the photo library even without an artists.tsv row.
_LEAD_AT = re.compile(r"^(.{3,60}?)\s+(?:@|at)\s+", re.I)
_LEAD_NAME = re.compile(
    r"^([A-Z][\w.'\u2019-]+(?:\s+[A-Z][\w.'\u2019-]+){0,3})\s*(?:,|\s-\s|\sof\s)")


def _lead_artist(text):
    """The person a caption leads with, or None."""
    text = (text or "").strip()
    m = _LEAD_AT.match(text)
    if m:
        return m.group(1).strip()
    m = _LEAD_NAME.match(text)
    if m:
        return m.group(1).strip()
    return None


def _row_artists(row, item_index=None):
    """Best-effort artist strings from a crosswalk row's sources + descs."""
    names = []
    for source in (row.get("source_row") or "").split(" ; "):
        source = source.strip()
        m = re.match(r"(?:current|history/[^:]+):\d{4}-\d{2}-\d{2}\s+(..*)$", source)
        if m:
            names.append(m.group(1).strip())
        m = re.match(r"item_log\.tsv:(\d+)$", source)
        if m and item_index:
            signer, _ = item_index.get(m.group(1), ("", ""))
            if signer:
                names.append(signer)
        m = re.match(r"artist-photos\.tsv:(.+)$", source)
        if m:
            lead = _lead_artist(m.group(1))
            if lead:
                names.append(lead)
    for desc in (row.get("google_desc") or "").split(" / "):
        lead = _lead_artist(desc)
        if lead:
            names.append(lead)
    seen, out = set(), []
    for n in names:
        k = goal_norm(n)
        if n and k and k not in seen:
            seen.add(k)
            out.append(n)
    return out


def cmd_enrich(args):
    rows = _read_rows(os.path.relpath(args.crosswalk, _ROOT))
    if not rows:
        raise SystemExit(f"no crosswalk rows at {args.crosswalk} - run "
                         "immich.py seed-crosswalk first")

    canon = _canonical_artists()
    aliases = _alias_map()

    named = immich.people(named_only=True)
    person_by_artist = {}
    placeholder_by_frontman = {}
    for person in named:
        name = (person.get("name") or "").strip()
        m = re.match(r"^played with\s+(.+?)\s*\(.+\)\s*$", name, re.I)
        if m:
            resolved, _ = _resolve_artist(m.group(1), canon, aliases)
            if resolved:
                placeholder_by_frontman.setdefault(
                    goal_norm(resolved), []).append(person["id"])
            continue
        resolved, _ = _resolve_artist(name, canon, aliases)
        if resolved:
            person_by_artist.setdefault(goal_norm(resolved), []).append(person["id"])

    songs = {} if args.no_ocr else _catalog_songs_by_artist()
    item_index = _item_log_index()
    scrape = _gp_scrape()
    corpus = None  # built lazily on the first candidate-less item row

    lifted = kept = 0
    for row in rows:
        conf = (row.get("confidence") or "0").strip()
        if conf in ("2", "3"):
            kept += 1
            continue

        signals = [s for s in (row.get("signals") or "").split("|") if s]
        candidates = [c for c in (row.get("immich_candidates") or "").split(";") if c]
        dates = set(re.findall(r"\d{4}-\d{2}-\d{2}", row.get("source_row", "")))
        is_item = (row.get("source_row") or "").startswith("item_log")
        if is_item:
            for source in (row.get("source_row") or "").split(" ; "):
                m = re.match(r"item_log\.tsv:(\d+)$", source.strip())
                if m:
                    _, show_date = item_index.get(m.group(1), ("", ""))
                    if show_date:
                        dates.add(show_date)
        dates = sorted(dates)
        artists = _row_artists(row, item_index)

        # caption signal: the harvested GP caption names the show directly.
        # Its date joins the date set (driving the face window below) and,
        # for a row with no candidates yet, a capture-date search proposes
        # them - for artist photos the capture date IS the show date.
        caption = _caption_for(row.get("google_link", ""), scrape)
        if caption:
            m = _CAP_ARTIST.match(caption)
            cap_artist = m.group(1).strip() if m else ""
            if (cap_artist and not _CAP_TAGGED.search(cap_artist)
                    and goal_norm(cap_artist) not in {goal_norm(a) for a in artists}):
                artists.append(cap_artist)
            cdate = _caption_date(caption)
            if cdate:
                if cdate not in dates:
                    dates = sorted(set(dates) | {cdate})
                sig = f"caption:{cdate}"
                if sig not in signals:
                    signals.append(sig)
                if not candidates:
                    hits = immich.search_metadata(
                        taken_after=f"{cdate}T00:00:00.000Z",
                        taken_before=f"{cdate}T23:59:59.999Z")
                    candidates = [h["id"] for h in hits[:12]]

        # face signal: person hits intersected with the date window
        face_hits = set()
        for artist in artists:
            resolved, _ = _resolve_artist(artist, canon, aliases)
            if not resolved:
                continue
            key = goal_norm(resolved)
            pids = person_by_artist.get(key, []) + placeholder_by_frontman.get(key, [])
            for pid in pids:
                kwargs = {"person_id": pid}
                if len(dates) == 1:
                    kwargs["taken_after"] = f"{dates[0]}T00:00:00.000Z"
                    kwargs["taken_before"] = f"{dates[0]}T23:59:59.999Z"
                for hit in immich.search_metadata(**kwargs):
                    face_hits.add(hit["id"])
        if face_hits:
            narrowed = [c for c in candidates if c in face_hits] or sorted(face_hits)
            if narrowed != candidates:
                candidates = narrowed[:12]
            tag = "face" + (":date" if len(dates) == 1 else "")
            if tag not in signals:
                signals.append(tag)

        # OCR candidate discovery (memorabilia): a row with no candidates has
        # nothing to examine - the batch-import EXIF blocked date seeding and
        # object photos carry no faces, so no other signal can propose assets.
        # The signer's name is usually printed or signed on the item itself,
        # so scan the memorabilia OCR corpus for it; the song-title match
        # below then confirms and dates the proposal.
        if is_item and not candidates and not args.no_ocr and artists:
            if corpus is None:
                corpus = _memorabilia_ocr_corpus()
            terms = []
            for artist in artists:
                terms.append(_norm_text(artist))
                surname = artist.split()[-1]
                if len(surname) > 3 and surname != artist:
                    terms.append(_norm_text(surname))
            hits = [aid for aid, text in (corpus or {}).items()
                    if any(_name_in_text(t, text) for t in terms)]
            if hits:
                candidates = hits[:12]
                if "ocr-name" not in signals:
                    signals.append("ocr-name")

        # OCR signal (memorabilia): song titles recover the show
        if is_item and candidates and songs and not args.no_ocr:
            for cand in candidates[:4]:
                if corpus and cand in corpus:
                    text = corpus[cand]
                else:
                    text = _norm_text(_ocr_text(cand))
                if len(text) < 12:
                    continue
                for artist in artists:
                    resolved, _ = _resolve_artist(artist, canon, aliases)
                    if not resolved:
                        continue
                    matched = [(s, d) for s, d in songs.get(goal_norm(resolved), [])
                               if len(s) > 6 and _norm_text(s) in text]
                    if len(matched) >= args.ocr_min_songs:
                        show_dates = sorted({d for _, d in matched if d})
                        sig = "ocr:" + (show_dates[0] if len(show_dates) == 1
                                        else f"{len(matched)}songs")
                        if sig not in signals:
                            signals.append(sig)
                        if cand != candidates[0]:
                            candidates.remove(cand)
                            candidates.insert(0, cand)
                        break

        strong = len({s.split(":")[0] for s in signals}) >= 2
        new_conf = "2" if strong and len(candidates) == 1 else \
                   ("2" if strong and conf != "2" and len(candidates) <= 3 else
                    ("1" if signals else conf))
        if new_conf != conf or ";".join(candidates) != row.get("immich_candidates", ""):
            lifted += 1
        row["immich_candidates"] = ";".join(candidates)
        row["signals"] = "|".join(signals)
        row["confidence"] = new_conf

    with open(args.crosswalk, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(immich.CROSSWALK_HEADER) + "\n")
        for row in rows:
            f.write("\t".join(row.get(c, "") for c in immich.CROSSWALK_HEADER) + "\n")
    print(json.dumps({"rows": len(rows), "updated": lifted,
                      "confirmed_untouched": kept}, indent=2))


# ── winnow ─────────────────────────────────────────────────────────────────

def _write_crosswalk(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(immich.CROSSWALK_HEADER) + "\n")
        for row in rows:
            f.write("\t".join(row.get(c, "")
                              for c in immich.CROSSWALK_HEADER) + "\n")


def cmd_winnow(args):
    """Hand the crosswalk to the local review page. Imported here rather
    than at module scope so the other subcommands never pay for the HTTP
    server machinery."""
    import photo_winnow
    photo_winnow.serve(args.crosswalk, port=args.port,
                       open_browser=not args.no_browser)


def cmd_mint(args):
    rows = _read_rows(os.path.relpath(args.crosswalk, _ROOT))
    todo = [r for r in rows
            if (r.get("confidence") or "").strip() == "3"
            and (r.get("match_id") or "").strip()
            and not (r.get("immich_link") or "").strip()]
    if not todo:
        print("no confirmed rows awaiting a share link.")
        return
    if not args.apply:
        print(json.dumps({"mode": "DRY RUN - rerun with --apply to mint",
                          "rows_awaiting_link": len(todo)}, indent=2))
        return

    minted = failed = 0
    for row in todo:
        asset_id = row["match_id"].strip()
        link = immich.create_link(asset_ids=[asset_id],
                                  description=(row.get("source_row") or "")[:120])
        url = immich.link_url(link or {})
        if not link or url.rstrip("/").endswith("/share"):
            print(f"warning: no share key returned for {asset_id[:8]}... - "
                  "left unlinked", file=sys.stderr)
            failed += 1
            continue
        row["immich_link"] = url
        minted += 1

    _write_crosswalk(args.crosswalk, rows)
    print(json.dumps({"minted": minted, "failed": failed}, indent=2))


# ── rewrite ────────────────────────────────────────────────────────────────

def _rewrite_targets():
    targets = [rel for rel, _ in LINK_SOURCES]
    hist = os.path.join(_ROOT, HISTORY_DIR)
    if os.path.isdir(hist):
        targets.extend(f"{HISTORY_DIR}/{f}" for f in sorted(os.listdir(hist))
                       if f.endswith(".tsv"))
    return targets


def cmd_rewrite(args):
    rows = _read_rows(os.path.relpath(args.crosswalk, _ROOT))
    ready, skipped = [], 0
    for row in rows:
        if (row.get("confidence") or "").strip() != "3":
            continue
        link = (row.get("immich_link") or "").strip()
        gp = (row.get("google_link") or "").strip()
        if link and gp:
            ready.append((gp, link))
        else:
            skipped += 1

    if skipped:
        print(f"warning: {skipped} confidence-3 row(s) missing google_link or "
              "immich_link - not applied", file=sys.stderr)
    if not ready:
        print("no confidence-3 rows with links to apply.")
        return

    report = []
    for rel in _rewrite_targets():
        path = os.path.join(_ROOT, rel)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8", newline="") as f:
            text = f.read()
        replaced = []
        for gp, link in ready:
            if gp in text:
                text = text.replace(gp, link)
                replaced.append(gp)
        if replaced:
            report.append({"file": rel, "links_replaced": len(replaced)})
            if args.apply:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(text)

    mode = "APPLIED" if args.apply else "DRY RUN - rerun with --apply to write"
    print(json.dumps({"mode": mode, "confirmed_rows": len(ready),
                      "files": report}, indent=2, ensure_ascii=False))
    if not report:
        print("(no target file contains any of the confirmed Google links - "
              "already rewritten?)", file=sys.stderr)


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(prog="backfill.py",
                                 description=__doc__.splitlines()[1])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("drift", help="person-name drift check")
    p.add_argument("--people-json", help="offline: a saved GET /people payload")

    p = sub.add_parser("enrich", help="lift crosswalk confidence via signals")
    p.add_argument("--crosswalk", default=CROSSWALK)
    p.add_argument("--no-ocr", action="store_true",
                   help="skip the per-asset OCR fetches (faster)")
    p.add_argument("--ocr-min-songs", type=int, default=2,
                   help="song-title matches required for the OCR signal")

    p = sub.add_parser("winnow", help="local page to confirm matches")
    p.add_argument("--crosswalk", default=CROSSWALK)
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--no-browser", action="store_true",
                   help="print the URL instead of opening a tab")

    p = sub.add_parser("mint", help="share links for confirmed rows")
    p.add_argument("--crosswalk", default=CROSSWALK)
    p.add_argument("--apply", action="store_true",
                   help="mint the links (default is a dry run)")

    p = sub.add_parser("rewrite", help="apply confidence-3 rows to the TSVs")
    p.add_argument("--crosswalk", default=CROSSWALK)
    p.add_argument("--apply", action="store_true",
                   help="write the files (default is a dry run)")

    args = ap.parse_args()
    if args.cmd == "drift":
        sys.exit(cmd_drift(args))
    elif args.cmd == "enrich":
        cmd_enrich(args)
    elif args.cmd == "winnow":
        cmd_winnow(args)
    elif args.cmd == "mint":
        cmd_mint(args)
    elif args.cmd == "rewrite":
        cmd_rewrite(args)


if __name__ == "__main__":
    main()
