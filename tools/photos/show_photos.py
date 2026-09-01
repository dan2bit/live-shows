#!/usr/bin/env python3
"""
show_photos.py — per-show tagging pass, and the tag-to-album sync

Stage 2 and stage 3 of the forward photo pipeline. Stage 1 is the phone:
upload from the Immich mobile app into the album matching the photo's kind.
Everything after that happens here.

  plan      Show what would be tagged for one show. No writes. Derives what
            it can and names every judgment it cannot make.

  edit      Serve a local page with one card per photo, carrying only the
            undecidable fields: which artist, and for memorabilia the show
            date and subtype. Everything derivable is pre-filled.

  tag       Apply the tags recorded by `edit` to Immich.

  sync      Materialise tags into albums: for each distinct show/ and
            artist/ tag, ensure the album exists, add missing assets, mint a
            share link if absent, and print the row for the data file.
            Idempotent — safe to re-run after every show.

WHY A SYNC STEP EXISTS AT ALL

  Tags are the source of truth, but they are not a public surface: Immich
  shared links accept only type ALBUM or INDIVIDUAL, and /api/tags is 401
  unauthenticated. So a public URL for "everything tagged artist/x" has to
  be a share token over an album, and tokens are random rather than
  derivable — they must be stored. Album links ARE stable across membership
  changes, so this is one durable row per album, not per photo.

  If a TAG shared-link type ever lands upstream, this stage collapses to
  nothing and the stored links become derivable.

WHAT DERIVES AND WHAT DOES NOT

  kind      from the upload album the photo landed in
  show      from capture date, matched against the show library
  venue     from the show row
  artist    proposed from named faces, confirmed by a human — a performance
            shot may be the support act, and that must never be assumed

  Memorabilia is the standing exception. A setlist photographed at home days
  later carries the photo-session date, so its show/ tag is assigned, never
  derived. Correct EXIF does not fix this; the batch import merely made it
  universal instead of occasional.

House rules: plain tab-joined TSV lines, LF endings, never the csv module.
Requires IMMICH_API_KEY, same as immich.py.
"""

import argparse
import collections
import datetime
import json
import os
import re
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", ".."))
sys.path.insert(0, _SCRIPT_DIR)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import immich  # noqa: E402
from name_forms import goal_norm  # noqa: E402

ARTIST_ALBUMS = os.path.join(_ROOT, "data", "show_goals", "artist-albums.tsv")

# Upload album -> kind tag. The mobile app can only sort into albums, so the
# album a photo lands in is the one classification made at capture time.
KIND_BY_ALBUM = {
    "guitar gods and goddesses": "with-artist",
    "player portraits": "performance",
    "concert memorabilia": "memorabilia",
    "preshow selfies": "selfie",
    "crowds i'm in": "crowd",
}

MEMORABILIA_KIND = "memorabilia"


def _slug(name):
    """Tag-path segment for an artist or venue name.

    Apostrophes are deleted rather than treated as separators: goal_norm
    turns "Gov't" into "gov t", which would slug to "gov-t-mule". Dropping
    them first gives "govt-mule" and keeps the segment stable against a
    name written with a curly quote in one place and a straight one in
    another. Diacritics are already folded by goal_norm, so "Whitney
    Mongé" and "Whitney Monge" reach the same tag."""
    cleaned = re.sub(r"['\u2019]", "", name or "")
    return re.sub(r"-+", "-",
                  re.sub(r"[^a-z0-9]+", "-", goal_norm(cleaned))).strip("-")


# ── show lookup ────────────────────────────────────────────────────────────

def _show_rows():
    rows = list(immich._read_tsv_rows("data/live_shows_current.tsv"))
    hist = os.path.join(_ROOT, "data", "history")
    if os.path.isdir(hist):
        for f in sorted(os.listdir(hist)):
            if f.endswith(".tsv"):
                rows.extend(immich._read_tsv_rows(f"data/history/{f}"))
    return rows


def find_show(date):
    """The show row for a date. Current wins over history, as elsewhere."""
    for row in _show_rows():
        if (row.get("Show Date") or "").strip() == date:
            return row
    return None


def show_venue(row):
    """Venue name, across both schemas. live_shows_current.tsv calls the
    column `Venue Name`; the history files call it `Venue`. Reading only one
    silently yields an empty venue/ tag path for every past show."""
    return ((row.get("Venue Name") or row.get("Venue") or "").strip())


def show_bill(row):
    """Everyone who played: headliner first, then support. Support may be a
    slash- or comma-separated list, and the column is named `Supporting
    Artist` in the current file but `Supporting Acts` in history."""
    out = [(row.get("Artist") or "").strip()]
    support = (row.get("Supporting Artist")
               or row.get("Supporting Acts") or "").strip()
    for part in re.split(r"\s*[/,]\s*", support):
        if part.strip():
            out.append(part.strip())
    return [a for a in out if a]


# ── asset gathering ────────────────────────────────────────────────────────

def _album_kinds():
    """album_id -> kind, for the upload albums we know how to classify."""
    out = {}
    for a in immich.albums():
        name = (a.get("albumName") or "").lower()
        for hint, kind in KIND_BY_ALBUM.items():
            if hint in name:
                out[a["id"]] = kind
    return out


def gather(date, window_days=1):
    """Assets that plausibly belong to this show.

    Two sources, unioned. Capture date catches anything shot that night,
    which is every kind except memorabilia. Upload-album membership catches
    memorabilia, whose capture date is the photo session rather than the
    show — those cannot be found by date and must be picked by a human, so
    they arrive here as unassigned candidates rather than proposals."""
    day = datetime.date.fromisoformat(date)
    lo = (day - datetime.timedelta(days=0)).isoformat()
    hi = (day + datetime.timedelta(days=window_days)).isoformat()
    by_date = {a["id"]: a for a in immich.search_metadata(
        taken_after=f"{lo}T00:00:00.000Z", taken_before=f"{hi}T23:59:59.999Z")}

    kinds = _album_kinds()
    in_album = {}
    for album_id, kind in kinds.items():
        for a in immich.search_metadata(album_id=album_id):
            in_album[a["id"]] = kind

    out = []
    for aid, a in by_date.items():
        out.append({"id": aid, "kind": in_album.get(aid),
                    "taken": str(a.get("fileCreatedAt") or "")[:10],
                    "by_date": True})
    return out, in_album


def existing_tags(asset_ids):
    """asset_id -> set of tag values already applied."""
    out = collections.defaultdict(set)
    for t in immich.tags():
        val = t.get("value") or t.get("name") or ""
        if not val:
            continue
        for a in immich.search_metadata(tag_id=t["id"]):
            if a["id"] in asset_ids:
                out[a["id"]].add(val)
    return out


# ── plan ───────────────────────────────────────────────────────────────────

def cmd_plan(args):
    row = find_show(args.show)
    if not row:
        raise SystemExit(f"No show row for {args.show}. Checked "
                         "live_shows_current.tsv and data/history/*.tsv.")
    bill = show_bill(row)
    venue = show_venue(row)
    assets, in_album = gather(args.show, args.window_days)

    print(f"show    : {args.show}  {bill[0]}")
    if len(bill) > 1:
        print(f"also on : {', '.join(bill[1:])}")
    print(f"venue   : {venue}")
    print(f"derives : show/{args.show}  "
          + (f"venue/{_slug(venue)}" if venue
             else "venue/??  <- NO VENUE on the show row"))
    print()
    if not assets:
        print("No assets found in the capture window. Upload from the phone "
              "first, or widen with --window-days.")
        return

    have = existing_tags({a["id"] for a in assets}) if not args.fast else {}
    unknown = [a for a in assets if not a["kind"]]
    print(f"{len(assets)} asset(s) in the window:\n")
    for a in sorted(assets, key=lambda x: (x["kind"] or "~", x["id"])):
        tags = sorted(have.get(a["id"], []))
        print(f"  {a['id'][:8]}  taken {a['taken']}  "
              f"kind={a['kind'] or 'UNKNOWN (not in an upload album)'}")
        if tags:
            print(f"            already tagged: {', '.join(tags)}")
    print()
    mem = [a for a in assets if a["kind"] == MEMORABILIA_KIND]
    print("Needs a human:")
    print(f"  - artist for each photo (bill: {', '.join(bill)})")
    if unknown:
        print(f"  - {len(unknown)} asset(s) are in no upload album, so kind "
              "cannot be derived")
    if mem:
        print(f"  - {len(mem)} memorabilia asset(s) landed in the window, so "
              "they were shot that night. CONFIRM the capture date is the "
              "show date rather than a later photo session before tagging.")
    else:
        print("  - no memorabilia in this window. Anything photographed after "
              "the show carries the photo-session date and has to be found "
              "and tagged by hand.")
    if not venue:
        print("  - venue is blank on the show row, so no venue/ tag can be "
              "derived")


# ── tag ────────────────────────────────────────────────────────────────────

def _apply(paths_by_asset, dry_run):
    """paths_by_asset: asset_id -> [tag paths]. Batched per tag path."""
    by_path = collections.defaultdict(list)
    for asset_id, paths in paths_by_asset.items():
        for p in paths:
            by_path[p].append(asset_id)
    for path, ids in sorted(by_path.items()):
        if dry_run:
            print(f"  [dry] {path}  <- {len(ids)} asset(s)")
            continue
        tag = immich.ensure_tag(path)
        immich.tag_assets([tag["id"]], ids)
        print(f"  {path}  <- {len(ids)} asset(s)")


def cmd_tag(args):
    """Apply tags from an assignments file written by `edit`, or derive the
    non-artist tags for everything in the window when run with --derived-only."""
    row = find_show(args.show)
    if not row:
        raise SystemExit(f"No show row for {args.show}.")
    venue = show_venue(row)
    assets, _ = gather(args.show, args.window_days)

    plan = {}
    if args.assignments:
        with open(args.assignments, encoding="utf-8") as f:
            data = json.load(f)
        for asset_id, fields in data.items():
            paths = []
            if fields.get("kind"):
                paths.append(f"kind/{fields['kind']}")
            if fields.get("artist"):
                paths.append(f"artist/{_slug(fields['artist'])}")
            # The taxonomy has three orthogonal axes, not one deep path: kind
            # is what the photo is, memorabilia/* is what object it shows, and
            # signed and detail are properties. A signed setlist carries
            # kind/memorabilia, memorabilia/setlist and signed - keeping them
            # separate means "everything about the hat" still matches a close
            # up of it, which a memorabilia/hat-detail subtype would not.
            if fields.get("subtype"):
                paths.append(f"memorabilia/{fields['subtype']}")
            for flag in ("signed", "detail"):
                if fields.get(flag):
                    paths.append(flag)
            # Memorabilia photographed after the show carries the photo
            # session date, so its show date is stated here rather than
            # derived from the capture window.
            show_date = fields.get("show") or args.show
            paths.append(f"show/{show_date}")
            if venue:
                paths.append(f"venue/{_slug(venue)}")
            plan[asset_id] = paths
    else:
        if not args.derived_only:
            raise SystemExit("Pass --assignments FILE, or --derived-only to "
                             "apply just kind/show/venue with no artist.")
        for a in assets:
            paths = [f"show/{args.show}"]
            if a["kind"]:
                paths.append(f"kind/{a['kind']}")
            if venue:
                paths.append(f"venue/{_slug(venue)}")
            plan[a["id"]] = paths

    if not plan:
        print("Nothing to tag.")
        return
    print(f"{len(plan)} asset(s):")
    _apply(plan, args.dry_run)
    if args.dry_run:
        print("\n[DRY RUN] nothing written. Re-run without --dry-run.")


# ── sync ───────────────────────────────────────────────────────────────────

def _album_by_name():
    return {(a.get("albumName") or "").strip(): a for a in immich.albums()}


def _read_artist_albums():
    rows = {}
    if os.path.exists(ARTIST_ALBUMS):
        for row in immich._read_tsv_rows("data/show_goals/artist-albums.tsv"):
            name = (row.get("Artist") or "").strip()
            if name:
                rows[name] = (row.get("Album URL") or "").strip()
    return rows


def cmd_sync(args):
    """Materialise show/ and artist/ tags into albums, minting a share link
    for any album that lacks one.

    Idempotent by construction: album lookup is by name, asset adds are a
    set difference, and a link is minted only when the album has none."""
    want = {}
    for t in immich.tags():
        val = t.get("value") or ""
        if val.startswith("show/") or val.startswith("artist/"):
            want[val] = t["id"]
    if not want:
        print("No show/ or artist/ tags on the server yet. Run `tag` first.")
        return

    albums = _album_by_name()
    known_links = _read_artist_albums()
    new_rows = []

    for path in sorted(want):
        kind, _, leaf = path.partition("/")
        asset_ids = [a["id"] for a in immich.search_metadata(tag_id=want[path])]
        if not asset_ids:
            continue
        album_name = (f"{leaf}" if kind == "show"
                      else leaf.replace("-", " ").title())
        album = albums.get(album_name)

        if album is None:
            if args.dry_run:
                print(f"  [dry] create album {album_name!r} "
                      f"with {len(asset_ids)} asset(s)")
                continue
            album = immich.create_album(album_name, asset_ids=asset_ids)
            albums[album_name] = album
            print(f"  created {album_name!r} with {len(asset_ids)} asset(s)")
        else:
            have = {a["id"] for a in
                    immich.search_metadata(album_id=album["id"])}
            missing = [i for i in asset_ids if i not in have]
            if missing:
                if args.dry_run:
                    print(f"  [dry] add {len(missing)} asset(s) to "
                          f"{album_name!r}")
                else:
                    immich.add_album_assets(album["id"], missing)
                    print(f"  {album_name!r} += {len(missing)} asset(s)")

        if kind == "artist" and album_name not in known_links:
            if args.dry_run:
                print(f"  [dry] mint share link for {album_name!r}")
            else:
                link = immich.create_link(album_id=album["id"],
                                          description=album_name)
                url = immich.link_url(link or {})
                new_rows.append((album_name, url))
                print(f"  minted {album_name!r} -> {url}")

    if new_rows:
        print("\nAppend to data/show_goals/artist-albums.tsv:")
        for name, url in new_rows:
            print(f"{name}\t{url}")
    if args.dry_run:
        print("\n[DRY RUN] nothing written.")


def cmd_scaffold(args):
    """Write an assignments file pre-filled with everything derivable.

    Copying twelve asset ids out of a plan listing by hand is the kind of
    step that produces a typo the tagger then applies silently. This emits
    them already keyed, with kind filled in and artist left blank so the
    only thing to do is type names."""
    row = find_show(args.show)
    if not row:
        raise SystemExit(f"No show row for {args.show}.")
    bill = show_bill(row)
    assets, _ = gather(args.show, args.window_days)
    if not assets:
        raise SystemExit("No assets in the window; nothing to scaffold.")

    out = {}
    for a in sorted(assets, key=lambda x: (x["kind"] or "~", x["id"])):
        entry = {"kind": a["kind"] or "", "artist": ""}
        if a["kind"] == MEMORABILIA_KIND:
            entry["subtype"] = ""
            entry["signed"] = False
            entry["show"] = args.show
        out[a["id"]] = entry

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    print(f"wrote {args.out} with {len(out)} asset(s)")
    print(f"bill: {', '.join(bill)}")
    print("Fill in artist for each. Memorabilia rows also carry subtype "
          "(one of the memorabilia/* leaves), signed, and an explicit show "
          "date to override the capture date.")


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(prog="show_photos.py",
                                 description=__doc__.splitlines()[1])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="what would be tagged for one show")
    p.add_argument("--show", required=True, metavar="DATE")
    p.add_argument("--window-days", type=int, default=1,
                   help="days after the show date to include (late-night "
                        "capture crosses midnight). Default: 1")
    p.add_argument("--fast", action="store_true",
                   help="skip the existing-tag lookup, which costs one "
                        "search per tag")

    p = sub.add_parser("tag", help="apply tags to Immich")
    p.add_argument("--show", required=True, metavar="DATE")
    p.add_argument("--window-days", type=int, default=1)
    p.add_argument("--assignments", metavar="FILE",
                   help="JSON of asset_id -> {kind, artist, show, subtype, "
                        "signed, detail}. Only asset_id is required; every "
                        "field is optional and omitted fields write no tag.")
    p.add_argument("--derived-only", action="store_true",
                   help="apply only kind/show/venue, no artist")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("scaffold", help="write a starter assignments file")
    p.add_argument("--show", required=True, metavar="DATE")
    p.add_argument("--window-days", type=int, default=1)
    p.add_argument("--out", metavar="FILE", required=True)

    p = sub.add_parser("sync", help="materialise tags into albums + links")
    p.add_argument("--dry-run", action="store_true")

    args = ap.parse_args()
    {"plan": cmd_plan, "tag": cmd_tag, "sync": cmd_sync,
     "scaffold": cmd_scaffold}[args.cmd](args)


if __name__ == "__main__":
    main()
