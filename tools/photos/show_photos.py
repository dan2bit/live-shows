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

  add       One asset, end to end: tag it, put it in its show album, its
            kind album and (when an artist is named) the artist album, and
            report the links the library rows need. The issue-close
            workflow calls this; memorabilia and portraits use it by hand.

  sync      Materialise tags into albums for the whole server: show/,
            artist/ and kind/. Ensure each album, add missing assets, mint
            a share link only where none exists, and print (or with
            --write, apply) the library rows. Idempotent — safe to re-run
            after every show, and it is the one-time backfill too.

  audit     Read-only. Resolve every photo link the library holds back to
            its Immich object and report what does not line up: show rows
            still on a per-photo link, artist rows off-host, tags with no
            row, photos with no artist. Run it before and after sync.

  seed      The one-time bootstrap for a library whose photos were linked
            before any tag existed. Resolves every link the library holds
            (show rows, artist-photos.tsv) to its asset and tags it from
            the row: show/ and venue/ from the show row, kind/ from the
            upload album it sits in, artist/ from the caption matched
            against that night's bill and sidemen. Read the --dry-run
            report first: unmatched captions and dates are listed there.

ALBUM RULES

  show      one album per show date, named "<date> <headliner>", found by
            date prefix so a rename never forks a second album; every photo
            tagged show/<date> is a member. Always created, even for one
            photo: the show row then carries exactly one link, whatever
            happens later.
  artist    every photo from every show at which the artist was
            PHOTOGRAPHED — the artist/ tag decides eligibility, the show
            albums decide membership. A bandmate's solo shot from the same
            night is therefore in both albums, and an artist who played but
            was never in frame gets no album at all. Adding a photo to a
            night changes every artist album anchored on that night.
  kind      the five upload albums double as the standing type albums;
            kind/ tags are synced INTO them so a photo re-tagged after
            upload still lands in the right one.

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

ARTIST_ALBUMS = "data/show_goals/artist-albums.tsv"
ARTIST_PHOTOS = "data/show_goals/artist-photos.tsv"
SEEN_WITH = "data/seen_with.tsv"
ALIASES = "data/recommend_aliases.tsv"
KIND_ALBUMS = "data/show_goals/kind-albums.tsv"
VENUES = "data/venues.tsv"
VENUE_ALIASES = "data/venue_aliases.tsv"
CURRENT = "data/live_shows_current.tsv"
HISTORY_DIR = "data/history"

# Upload album -> kind tag. The mobile app can only sort into albums, so the
# album a photo lands in is the one classification made at capture time.
KIND_BY_ALBUM = {
    "guitar gods and goddesses": "with-artist",
    "player portraits": "performance",
    "concert memorabilia": "memorabilia",
    "preshow selfies": "selfie",
    "crowds i'm in": "crowd",
}

# kind tag -> the standing type album it is materialised into. These are the
# same five albums the phone uploads into; the display names here are what
# a fresh server gets if an album is missing, and lookup is by the hint in
# KIND_BY_ALBUM so a hand-renamed album still resolves.
KIND_ALBUM_NAMES = {
    "with-artist": "Guitar gods and goddesses",
    "performance": "Player portraits",
    "memorabilia": "Concert memorabilia",
    "selfie": "Preshow selfies",
    "crowd": "Crowds I'm in",
}

MEMORABILIA_KIND = "memorabilia"

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def show_album_name(date, headliner=""):
    """The one naming rule for show albums, shared by add, sync and the
    issue-close handler. The headliner is decoration for the Immich UI;
    the date is the key (see find_show_album)."""
    return f"{date} {headliner}".strip()


def find_show_album(albums_by_name, date):
    """The show album for a date: exact bare-date name, else the first album
    whose name starts with the date. Prefix lookup means an album created
    under the bare-date rule, or renamed by hand, is still the same album
    rather than the seed of a second one."""
    if date in albums_by_name:
        return albums_by_name[date]
    for name, album in sorted(albums_by_name.items()):
        if name.startswith(date + " "):
            return album
    return None


def artist_album_name(slug, hints):
    """Display name for an artist album. Prefer the name the library already
    uses for this slug (show rows, artist-albums.tsv, the caller); fall
    back to title-casing the slug, which loses diacritics and apostrophes
    but still canonicalises to the same artist through goal_norm."""
    return hints.get(slug) or slug.replace("-", " ").title()


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


# ── venue identity ─────────────────────────────────────────────────────────

_VENUE_CACHE = {}


def _venue_key(value):
    """Fold a venue name to its match key, the same way app.js and
    check_box_office.py do: no leading 'the', no punctuation."""
    key = re.sub(r"^the\s+", "", (value or "").strip().lower())
    key = re.sub(r"[^a-z0-9 ]+", " ", key)
    return re.sub(r"\s+", " ", key).strip()


def _venue_identity():
    """(aliases, display) keyed by folded name: aliases -> canonical Venue
    Name; display -> Short Name where venues.tsv has one, else the
    canonical Venue Name."""
    if not _VENUE_CACHE:
        aliases, display = {}, {}
        for row in immich._read_tsv_rows(VENUE_ALIASES):
            a, c = (row.get("Alias") or "").strip(), (row.get("Venue Name") or "").strip()
            if a and c:
                aliases[_venue_key(a)] = c
        for row in immich._read_tsv_rows(VENUES):
            name = (row.get("Venue Name") or "").strip()
            if name:
                display[_venue_key(name)] = (row.get("Short Name") or "").strip() or name
        _VENUE_CACHE["aliases"], _VENUE_CACHE["display"] = aliases, display
    return _VENUE_CACHE["aliases"], _VENUE_CACHE["display"]


def venue_slug(venue_str):
    """(slug, resolved) for whatever spelling a show row carries.

    History rows hold the setlist.fm long form ("Birchmere, Alexandria, VA,
    USA"); current rows hold the library name. Both must reach one tag, so
    the string is first-comma-truncated, folded, passed through
    venue_aliases.tsv, and looked up in venues.tsv; the tag is built from
    the Short Name (or the canonical name when there is none). An
    unrecognised venue slugs as given with resolved=False, so the caller
    can report it rather than silently minting a second identity."""
    raw = (venue_str or "").split(",")[0].strip()
    if not raw:
        return "", True
    aliases, display = _venue_identity()
    key = _venue_key(raw)
    if key in aliases:
        key = _venue_key(aliases[key])
    if key in display:
        return _slug(display[key]), True
    return _slug(raw), False


# ── show lookup ────────────────────────────────────────────────────────────

def _history_files():
    hist = os.path.join(_ROOT, HISTORY_DIR)
    if not os.path.isdir(hist):
        return []
    return [f"{HISTORY_DIR}/{f}" for f in sorted(os.listdir(hist))
            if f.endswith(".tsv")]


def _show_rows():
    rows = list(immich._read_tsv_rows(CURRENT))
    for relpath in _history_files():
        rows.extend(immich._read_tsv_rows(relpath))
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
          + (f"venue/{venue_slug(venue)[0]}" if venue
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
                paths.append(f"venue/{venue_slug(venue)[0]}")
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
                paths.append(f"venue/{venue_slug(venue)[0]}")
            plan[a["id"]] = paths

    if not plan:
        print("Nothing to tag.")
        return
    print(f"{len(plan)} asset(s):")
    _apply(plan, args.dry_run)
    if args.dry_run:
        print("\n[DRY RUN] nothing written. Re-run without --dry-run.")


# ── library rows ───────────────────────────────────────────────────────────

def _read_artist_albums():
    """[(artist, url)] in file order, so a rewrite keeps the rows where a
    human left them and only appends what is new."""
    out = []
    for row in immich._read_tsv_rows(ARTIST_ALBUMS):
        name = (row.get("Artist") or "").strip()
        if name:
            out.append((name, (row.get("Album URL") or "").strip()))
    return out


def _write_artist_albums(rows):
    path = os.path.join(_ROOT, ARTIST_ALBUMS)
    with open(path, "w", encoding="utf-8") as f:
        f.write("Artist\tAlbum URL\n")
        for name, url in rows:
            f.write(f"{name}\t{url}\n")


def _write_kind_albums(rows):
    path = os.path.join(_ROOT, KIND_ALBUMS)
    with open(path, "w", encoding="utf-8") as f:
        f.write("Kind\tAlbum\tAlbum URL\n")
        for kind, album, url in rows:
            f.write(f"{kind}\t{album}\t{url}\n")


def _name_hints():
    """slug -> display name, from every place the library already spells an
    artist: show bills (headliner and support) and artist-albums.tsv rows.
    The first spelling seen wins; artist-albums.tsv is read first because
    its spelling is the one already keyed by the site."""
    hints = {}
    for name, _ in _read_artist_albums():
        hints.setdefault(_slug(name), name)
    for row in _show_rows():
        for name in show_bill(row):
            hints.setdefault(_slug(name), name)
    for row in immich._read_tsv_rows(SEEN_WITH):
        name = (row.get("Seen With") or "").strip()
        if name:
            hints.setdefault(_slug(name), name)
    return hints


def _aliases():
    """Alias -> Canonical from recommend_aliases.tsv (# comment lines and
    the header skipped), both as given."""
    out = {}
    path = os.path.join(_ROOT, ALIASES)
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for ln in f:
            if not ln.strip() or ln.lstrip().startswith("#"):
                continue
            c = ln.rstrip("\n").split("\t")
            if len(c) >= 2 and c[0].strip() and c[0].strip() != "Alias" and c[1].strip():
                out[c[0].strip()] = c[1].strip()
    return out


def canonical_artist(name, aliases=None):
    """The library's spelling for a name via recommend_aliases.tsv; a name
    with no alias row comes back as given. Billing drift ("X & Y" vs "X and
    Y") resolves through a data row, never a code change."""
    aliases = _aliases() if aliases is None else aliases
    want = goal_norm(name)
    for alias, canon in aliases.items():
        if goal_norm(alias) == want:
            return canon
    return name


def set_show_photo_url(date, url, headliner=None):
    """Write `url` into the Photo URL column of the show row for `date`,
    across live_shows_current.tsv and every history file. Current is
    checked first, as everywhere. Short rows (trailing tabs stripped on the
    way through the API) are padded back to full width. Returns a status
    line; a row whose Photo URL already equals `url` is a no-op, which is
    the path that fires on the second and later photos of one show."""
    for relpath in [CURRENT] + _history_files():
        path = os.path.join(_ROOT, relpath)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        bom = "\ufeff" if raw.startswith("\ufeff") else ""
        lines = raw[len(bom):].split("\n")
        header = lines[0].split("\t")
        try:
            di = next(header.index(h) for h in ("Show Date", "Date")
                      if h in header)
            ai = next(header.index(h) for h in ("Artist", "Headliner")
                      if h in header)
            pi = header.index("Photo URL")
        except (StopIteration, ValueError):
            continue
        for i in range(1, len(lines)):
            if not lines[i].strip():
                continue
            cells = lines[i].split("\t")
            if len(cells) < len(header):
                cells += [""] * (len(header) - len(cells))
            if cells[di].strip() != date:
                continue
            if headliner and goal_norm(cells[ai]) != goal_norm(headliner):
                continue
            cur = cells[pi].strip()
            if cur == url:
                return f"Photo URL already set on the show row; no change. ({relpath})"
            cells[pi] = url
            lines[i] = "\t".join(cells)
            with open(path, "w", encoding="utf-8") as f:
                f.write(bom + "\n".join(lines))
            was = f" (was {cur})" if cur and cur != "-" else ""
            return f"Photo URL written to show row: {date} / {cells[ai]}{was} ({relpath})"
    return (f"WARN: no show row for {date}"
            + (f" / {headliner}" if headliner else "") + " - Photo URL not written")


def upsert_artist_album(name, url):
    """Add or update the artist-albums.tsv row for `name`, matched by slug
    so a spelling variant does not create a second row. Returns a status
    line; an unchanged row is a no-op."""
    rows = _read_artist_albums()
    want = _slug(name)
    for i, (have, cur) in enumerate(rows):
        if _slug(have) == want:
            if cur == url:
                return f"artist-albums.tsv row for {have} already carries this link; no change."
            rows[i] = (have, url)
            _write_artist_albums(rows)
            return f"artist-albums.tsv row updated: {have} (was {cur or '-'})"
    rows.append((name, url))
    _write_artist_albums(rows)
    return f"artist-albums.tsv row added: {name}"


# ── album resolution ───────────────────────────────────────────────────────

def _album_by_name():
    return {(a.get("albumName") or "").strip(): a for a in immich.albums()}


def _album_members(album):
    return {a["id"] for a in immich.search_metadata(album_id=album["id"])}


def resolve_asset(ref, links=None):
    """An asset id from what a human can paste: the id itself, or a
    per-photo share link. An album link is refused rather than guessed at -
    the caller is asking which photo, and an album does not say."""
    ref = (ref or "").strip()
    if _UUID_RE.match(ref):
        return ref
    key = immich.share_key(ref)
    if not key:
        raise SystemExit(f"not an asset id or a /share/ link: {ref!r}")
    link = immich.shared_link_by_key(key, links)
    if link is None:
        raise SystemExit(f"no shared link on the server has key {key}")
    if link.get("type") == "ALBUM":
        raise SystemExit("that is an album link; paste the photo's own share "
                         "link (Share -> Create link on the photo) or its asset id")
    assets = link.get("assets") or []
    if len(assets) != 1:
        raise SystemExit(f"that link covers {len(assets)} assets; need exactly one")
    return assets[0]["id"]


class _Albums:
    """Album, membership and link state for one run, fetched once and kept
    current as the run creates things. Every mutating call is guarded by
    dry_run and logs one line, so a --dry-run transcript reads as the plan
    the real run will execute."""

    def __init__(self, dry_run):
        self.dry = dry_run
        self.by_name = _album_by_name()
        self.links = immich.links_by_album()
        self.log = []

    def _say(self, msg):
        self.log.append(msg)
        print(("  [dry] " if self.dry else "  ") + msg)

    def ensure(self, album, name, asset_ids, description=""):
        """Create `name` with `asset_ids`, or add the missing ones to the
        existing `album`. Returns the album dict (a stub under dry run)."""
        asset_ids = set(asset_ids)
        if album is None:
            self._say(f"create album {name!r} with {len(asset_ids)} asset(s)")
            if self.dry:
                album = {"id": None, "albumName": name}
            else:
                album = immich.create_album(name, asset_ids=asset_ids,
                                            description=description)
            self.by_name[name] = album
            return album
        if album.get("id") is None:
            return album
        missing = asset_ids - _album_members(album)
        if missing:
            self._say(f"{album.get('albumName')!r} += {len(missing)} asset(s)")
            if not self.dry:
                immich.add_album_assets(album["id"], missing)
        return album

    def link(self, album, description):
        """The album's share URL, minting one only if none exists."""
        album_id = album.get("id")
        if album_id and album_id in self.links:
            return immich.link_url(self.links[album_id])
        self._say(f"mint share link for {album.get('albumName')!r}")
        if self.dry or not album_id:
            return f"<link for {album.get('albumName')}>"
        link = immich.create_link(album_id=album_id, description=description)
        self.links[album_id] = link
        return immich.link_url(link)

    def kind_album(self, kind):
        """The standing type album for a kind, by the hint in KIND_BY_ALBUM."""
        for name, album in self.by_name.items():
            for hint, k in KIND_BY_ALBUM.items():
                if k == kind and hint in name.lower():
                    return album
        return None


# ── sync ───────────────────────────────────────────────────────────────────

def _tag_index():
    """value -> tag id for every tag on the server."""
    return {(t.get("value") or ""): t["id"] for t in immich.tags()
            if t.get("value")}


def _assets_of(tag_id):
    return {a["id"] for a in immich.search_metadata(tag_id=tag_id)}


def sync_targets(dates=None, artists=None, kinds=None, dry_run=False,
                 name_hints=None):
    """Materialise tags into albums and links.

    dates / artists / kinds restrict which albums are touched (None = every
    tag of that axis on the server). Show membership is always loaded in
    full, because an artist album is the union of the artist's show
    albums and that union cannot be built from one show.

    Returns {"shows": {date: url}, "artists": {name: url},
             "kinds": {kind: (album name, url)}}."""
    hints = dict(_name_hints())
    hints.update(name_hints or {})
    tags = _tag_index()
    st = _Albums(dry_run)
    out = {"shows": {}, "artists": {}, "kinds": {}}

    # show/<date> -> member asset ids, for every show tag. This is the
    # membership source for both show and artist albums.
    show_assets = {}
    for val, tid in tags.items():
        if val.startswith("show/"):
            date = val[len("show/"):].split("/")[-1]
            ids = _assets_of(tid)
            if ids:
                show_assets[date] = ids

    for date in sorted(show_assets):
        if dates is not None and date not in dates:
            continue
        row = find_show(date)
        headliner = (row.get("Artist") or "").strip() if row else ""
        album = find_show_album(st.by_name, date)
        album = st.ensure(album, show_album_name(date, headliner),
                          show_assets[date], description=f"show/{date}")
        out["shows"][date] = st.link(album, show_album_name(date, headliner))

    # A scoped run must still touch every artist anchored on an affected
    # night: adding one photo to a show changes each of those albums, not
    # only the named artist's. So the scope is "named, or in frame at one
    # of these shows", and the second test needs the artist's own assets.
    affected = set()
    for d in (dates or ()):
        affected |= show_assets.get(d, set())

    for val, tid in sorted(tags.items()):
        if not val.startswith("artist/"):
            continue
        slug = val[len("artist/"):]
        if artists is not None and slug not in artists and not affected:
            continue
        own = _assets_of(tid)
        if not own:
            continue
        if artists is not None and slug not in artists and not (own & affected):
            continue
        nights = {d for d, ids in show_assets.items() if ids & own}
        members = set(own)
        for d in nights:
            members |= show_assets[d]
        name = artist_album_name(slug, hints)
        album = st.ensure(st.by_name.get(name), name, members,
                          description=f"artist/{slug}")
        out["artists"][name] = st.link(album, name)

    for kind, display in KIND_ALBUM_NAMES.items():
        if kinds is not None and kind not in kinds:
            continue
        tid = tags.get(f"kind/{kind}")
        ids = _assets_of(tid) if tid else set()
        album = st.kind_album(kind)
        if album is None and not ids:
            continue
        album = st.ensure(album, display, ids, description=f"kind/{kind}")
        out["kinds"][kind] = (album.get("albumName") or display,
                              st.link(album, album.get("albumName") or display))
    return out


def _print_rows(result):
    if result["shows"]:
        print("\nShow rows (Photo URL):")
        for date, url in sorted(result["shows"].items()):
            print(f"{date}\t{url}")
    if result["artists"]:
        print("\ndata/show_goals/artist-albums.tsv:")
        for name, url in sorted(result["artists"].items()):
            print(f"{name}\t{url}")
    if result["kinds"]:
        print("\ndata/show_goals/kind-albums.tsv:")
        for kind, (album, url) in sorted(result["kinds"].items()):
            print(f"{kind}\t{album}\t{url}")


def _apply_rows(result):
    """Write the sync result into the library: show rows, artist-albums.tsv,
    kind-albums.tsv. Each is an upsert; unchanged rows are left alone."""
    print()
    for date, url in sorted(result["shows"].items()):
        print(set_show_photo_url(date, url))
    for name, url in sorted(result["artists"].items()):
        print(upsert_artist_album(name, url))
    if result["kinds"]:
        rows = [(k, a, u) for k, (a, u) in sorted(result["kinds"].items())]
        _write_kind_albums(rows)
        print(f"kind-albums.tsv written: {len(rows)} row(s)")


def cmd_sync(args):
    result = sync_targets(dry_run=args.dry_run)
    _print_rows(result)
    if args.dry_run:
        print("\n[DRY RUN] nothing written.")
    elif args.write:
        _apply_rows(result)
    else:
        print("\nRows printed only. Re-run with --write to apply them.")


# ── add ────────────────────────────────────────────────────────────────────

def add_asset(asset_id, show, kind, artist=None, subtype=None, signed=False,
              detail=False, dry_run=False):
    """Tag one asset and place it in every album it belongs to.

    Returns {"asset_id", "show_link", "artist", "artist_link"}; the caller
    owns the library writes (the issue-close handler writes the show row
    and the artist-albums.tsv row from these). Nothing here reads EXIF:
    `show` is stated by the caller, which is what memorabilia needs."""
    row = find_show(show)
    if not row:
        raise SystemExit(f"No show row for {show}. Checked "
                         "live_shows_current.tsv and data/history/*.tsv.")
    if kind not in KIND_ALBUM_NAMES:
        raise SystemExit(f"kind must be one of {', '.join(KIND_ALBUM_NAMES)}")
    venue = show_venue(row)
    paths = [f"show/{show}", f"kind/{kind}"]
    slug = None
    if artist:
        slug = _slug(artist)
        paths.append(f"artist/{slug}")
    if subtype:
        paths.append(f"memorabilia/{subtype}")
    if signed:
        paths.append("signed")
    if detail:
        paths.append("detail")
    if venue:
        vslug, known = venue_slug(venue)
        if not known:
            print(f"WARN: venue {venue!r} is not in venues.tsv or venue_aliases.tsv; "
                  f"tagging venue/{vslug} as given")
        paths.append(f"venue/{vslug}")

    print(f"tags for {asset_id[:8]}:")
    _apply({asset_id: paths}, dry_run)
    print("albums:")
    result = sync_targets(dates={show}, artists={slug} if slug else set(),
                          kinds={kind}, dry_run=dry_run,
                          name_hints={slug: artist} if slug else None)
    if dry_run and show not in result["shows"]:
        # Under dry run the tag was not applied, so the show may have no
        # members yet on the server; report the album that would exist.
        result["shows"][show] = f"<link for {show_album_name(show, row.get('Artist', ''))}>"
    name = artist_album_name(slug, {slug: artist}) if slug else None
    return {
        "asset_id": asset_id,
        "show_link": result["shows"].get(show, ""),
        "artist": name,
        "artist_link": result["artists"].get(name, "") if name else "",
    }


def cmd_add(args):
    asset_id = resolve_asset(args.asset)
    res = add_asset(asset_id, args.show, args.kind, artist=args.artist,
                    subtype=args.subtype, signed=args.signed,
                    detail=args.detail, dry_run=args.dry_run)
    print()
    print(f"show row link  : {res['show_link']}")
    if res["artist"]:
        print(f"artist album   : {res['artist']}\t{res['artist_link']}")
    if args.dry_run:
        print("\n[DRY RUN] nothing written. Re-run without --dry-run.")
    elif args.write:
        print()
        print(set_show_photo_url(args.show, res["show_link"]))
        if res["artist"]:
            print(upsert_artist_album(res["artist"], res["artist_link"]))
    else:
        print("\nImmich updated; library rows printed only. Re-run with "
              "--write to apply them.")


# ── audit ──────────────────────────────────────────────────────────────────

def _show_row_links():
    """[(relpath, date, artist, url)] for every show row with a Photo URL."""
    out = []
    for relpath in [CURRENT] + _history_files():
        for row in immich._read_tsv_rows(relpath):
            url = (row.get("Photo URL") or "").strip()
            if url and url != "-":
                date = (row.get("Show Date") or row.get("Date") or "").strip()
                artist = (row.get("Artist") or row.get("Headliner") or "").strip()
                out.append((relpath, date, artist, url))
    return out


def cmd_audit(args):
    """Every finding is something a later sync or a human must do; nothing
    here writes. Sections are ordered from the show row outward."""
    links = immich.shared_links()
    by_key = {l.get("key"): l for l in links}
    albums = _album_by_name()
    tags = _tag_index()
    show_tags = {v[len("show/"):].split("/")[-1]: tid
                 for v, tid in tags.items() if v.startswith("show/")}
    findings = 0

    print("== Show rows")
    seen_dates = set()
    for relpath, date, artist, url in _show_row_links():
        seen_dates.add(date)
        link = by_key.get(immich.share_key(url))
        if not immich.on_photo_host(url):
            findings += 1
            print(f"  OFF-HOST   {date} {artist}  {url}  ({relpath})")
        elif link is None:
            findings += 1
            print(f"  DEAD KEY   {date} {artist}  {url}  ({relpath})")
        elif link.get("type") != "ALBUM":
            findings += 1
            n = len(link.get("assets") or [])
            print(f"  PER-PHOTO  {date} {artist}  {n} asset(s); needs the show album link")
        elif not find_show_album(albums, date):
            findings += 1
            print(f"  ALBUM-NAME {date} {artist}  row links album "
                  f"{(link.get('album') or {}).get('albumName')!r}, which does not "
                  f"follow the date-prefix rule")
    for date in sorted(show_tags):
        if date not in seen_dates and not args.fast:
            n = len(_assets_of(show_tags[date]))
            if n:
                findings += 1
                print(f"  NO LINK    {date}  {n} tagged asset(s) but no Photo URL on a show row")

    print("== Artist rows")
    artist_rows = _read_artist_albums()
    row_slugs = {_slug(n) for n, _ in artist_rows}
    for name, url in artist_rows:
        if not immich.on_photo_host(url):
            findings += 1
            print(f"  OFF-HOST   {name}  {url}")
        elif immich.share_key(url) not in by_key:
            findings += 1
            print(f"  DEAD KEY   {name}  {url}")
    for val in sorted(tags):
        if val.startswith("artist/") and val[len("artist/"):] not in row_slugs:
            findings += 1
            print(f"  NO ROW     {val}")

    if not args.fast:
        print("== Photos with no artist")
        artist_tagged = set()
        for val, tid in tags.items():
            if val.startswith("artist/"):
                artist_tagged |= _assets_of(tid)
        for date, tid in sorted(show_tags.items()):
            untagged = _assets_of(tid) - artist_tagged
            if untagged:
                findings += 1
                print(f"  {date}  {len(untagged)} asset(s) tagged show/ but no artist/")

        print("== Kind albums")
        st = _Albums(dry_run=True)
        for kind in KIND_ALBUM_NAMES:
            tid = tags.get(f"kind/{kind}")
            ids = _assets_of(tid) if tid else set()
            album = st.kind_album(kind)
            if album is None:
                if ids:
                    findings += 1
                    print(f"  NO ALBUM   kind/{kind}  {len(ids)} tagged asset(s)")
                continue
            missing = ids - _album_members(album)
            if missing:
                findings += 1
                print(f"  MISSING    kind/{kind}  {len(missing)} tagged asset(s) not in "
                      f"{album.get('albumName')!r}")

    print(f"\n{findings} finding(s)." if findings else "\nClean.")


# ── seed ───────────────────────────────────────────────────────────────────

_ROW_DATE_RE = re.compile(r"^([A-Z][a-z]{2}) (\d{1,2}), (\d{4})")
_CAP_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_CAP_US = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")


def _row_iso(text):
    """'Oct 16, 2021, 10:31:28 PM' or 'Dec 14, 2022' -> ISO date, or ""."""
    m = _ROW_DATE_RE.match((text or "").strip())
    if not m:
        return ""
    try:
        d = datetime.datetime.strptime(" ".join(m.groups()), "%b %d %Y").date()
    except ValueError:
        return ""
    return d.isoformat()


def _caption_iso(text):
    m = _CAP_ISO.search(text or "")
    if m:
        return m.group(1)
    m = _CAP_US.search(text or "")
    if m:
        mo, dy, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yr < 100:
            yr += 2000
        return f"{yr:04d}-{mo:02d}-{dy:02d}"
    return ""


def _name_in_text(name, text):
    """Word-bounded, punctuation-folded containment."""
    n, t = goal_norm(name), goal_norm(text)
    return bool(n) and re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", t) is not None


def _squash(text):
    return re.sub(r"[^a-z0-9]", "", goal_norm(text or ""))


def _act_in_text(name, text, aliases):
    """Does a caption name this act? Exact word-bounded containment of the
    name or any alias; else the punctuation-squashed form ("J. P. Soars" /
    "JP Soars", "All-Stars" / "Allstars"); else, for a name of three or
    more words, its first two ("Ally Venable Band" is "Ally Venable" in
    every caption that names her)."""
    forms = {name} | {a for a, c in aliases.items() if goal_norm(c) == goal_norm(name)}
    if any(_name_in_text(f, text) for f in forms):
        return True
    sq = _squash(text)
    if any(_squash(f) and _squash(f) in sq for f in forms):
        return True
    words = goal_norm(name).split()
    return len(words) >= 3 and _name_in_text(" ".join(words[:2]), text)


def _seen_with_for(date):
    return [(r.get("Seen With") or "").strip()
            for r in immich._read_tsv_rows(SEEN_WITH)
            if (r.get("Show Date") or "").strip() == date and (r.get("Seen With") or "").strip()]


_RUN = r"[A-Z][\w.'\u2019-]*(?:\s+[A-Z][\w.'\u2019-]*)+"
_PEOPLE_RE = re.compile(_RUN)
_OF_BAND_RE = re.compile(r"\s+(?:of|for|from)\s+(?P<band>.+?)(?=\s*[.@,(|]|\s+-\s|\s+and\s+|\s+w/|$)")


def _people_of_band(caption):
    """('Laura Rogers and Lydia Slagle of Secret Sisters', ...) ->
    (["Laura Rogers", "Lydia Slagle"], "Secret Sisters"), else None. The
    people are the capitalised runs of two or more words before the
    of/for/from; a role phrase ("Tikyra Jackson, drummer for ...") sits
    between and is skipped because it is lowercase."""
    m = _OF_BAND_RE.search(caption or "")
    if not m:
        return None
    prefix = caption[:m.start()]
    people = [re.sub(r"\s*\(again\)", "", r).strip() for r in _PEOPLE_RE.findall(prefix)]
    people = [p for p in people if p]
    if not people:
        return None
    return people, m.group("band").strip()


def _caption_artists(caption, date, aliases):
    """(names, anchored) - who a caption is about, from the names the
    library knows for that night. In order: a "PERSON of BAND" form whose
    band is on the bill names the person(s), not the band; sidemen from
    seen_with.tsv named in the caption; bill acts named in the caption
    (alias- and punctuation-tolerant). Those three anchor the caption to
    the night (anchored=True). Failing all of them, the capitalised run
    the caption opens with is taken as a person the library does not know
    yet (anchored=False). Library spellings where known."""
    row = find_show(date) if date else None
    if not row:
        return [], False
    bill = show_bill(row)
    sidemen = [n for n in _seen_with_for(date) if _name_in_text(n, caption)]
    ofb = _people_of_band(caption)
    if ofb:
        people, band = ofb
        if any(_act_in_text(b, band, aliases) for b in bill):
            names = list(people)
            for n in sidemen:
                if not any(goal_norm(n) == goal_norm(p) for p in names):
                    names.append(n)
            return names, True
    names = list(sidemen)
    for b in bill:
        if _act_in_text(b, caption, aliases) and not any(
                goal_norm(b) == goal_norm(n) for n in names):
            names.append(b)
    if names:
        return names, True
    m = _PEOPLE_RE.match(caption or "")
    if m:
        return [re.sub(r"\s*\(again\)", "", m.group(0)).strip()], False
    return [], False


def _resolve_night(row_iso, caption, aliases):
    """(date, names) for an artist-photos row. Candidate nights are the date
    written in the caption, then the row timestamp, then the day before it
    (post-midnight capture). The first candidate whose show row is named
    in the caption wins; failing that, the first candidate that is a show
    at all. A timestamp that lands on a different show therefore loses to
    the caption that names the right one."""
    cands = []
    day_before = ((datetime.date.fromisoformat(row_iso) - datetime.timedelta(days=1)).isoformat()
                  if row_iso else "")
    for c in (_caption_iso(caption), row_iso, day_before):
        if c and c not in cands:
            cands.append(c)
    fallback = ""
    for c in cands:
        if not find_show(c):
            continue
        names, anchored = _caption_artists(caption, c, aliases)
        if anchored:
            return c, names
        fallback = fallback or c
    if not fallback:
        return "", []
    return fallback, _caption_artists(caption, fallback, aliases)[0]


def _link_assets(link):
    """Asset ids behind a shared link: its own for INDIVIDUAL, the album's
    membership for ALBUM."""
    if link.get("type") == "ALBUM":
        album = link.get("album") or {}
        return _album_members(album) if album.get("id") else set()
    return {a["id"] for a in (link.get("assets") or [])}


def cmd_seed(args):
    links = immich.shared_links()
    by_key = {l.get("key"): l for l in links}
    aliases = _aliases()
    hints = _name_hints()
    plan = collections.defaultdict(set)
    off_host, dead, no_date, unmatched, unknown = [], [], [], [], {}
    unknown_venues = {}

    def show_tags(date):
        row = find_show(date)
        venue = show_venue(row) if row else ""
        tags = {f"show/{date}"}
        if venue:
            vslug, known = venue_slug(venue)
            if not known:
                unknown_venues[venue] = vslug
            tags.add(f"venue/{vslug}")
        return tags

    # 1. show rows: the linked asset(s) belong to that night.
    for relpath, date, artist, url in _show_row_links():
        if not immich.on_photo_host(url):
            off_host.append((date, artist, url, relpath))
            continue
        link = by_key.get(immich.share_key(url))
        if link is None:
            dead.append((date, artist, url))
            continue
        for aid in _link_assets(link):
            plan[aid] |= show_tags(date)

    # 2. artist-photos.tsv rows: with-artist by definition; the night from
    #    the row date (a post-midnight timestamp means the day before),
    #    else the date in the caption; the artist from the caption.
    for row in immich._read_tsv_rows(ARTIST_PHOTOS):
        url = (row.get("Share Link") or "").strip()
        caption = (row.get("Caption / Artist Info") or "").strip()
        if not immich.on_photo_host(url):
            off_host.append(("", caption[:40], url, ARTIST_PHOTOS))
            continue
        link = by_key.get(immich.share_key(url))
        if link is None:
            dead.append(("", caption[:40], url))
            continue
        iso = _row_iso(row.get("Date"))
        date, names = _resolve_night(iso, caption, aliases)
        assets = _link_assets(link)
        for aid in assets:
            plan[aid].add("kind/with-artist")
        if not date:
            no_date.append((iso or "?", caption[:60]))
            continue
        for aid in assets:
            plan[aid] |= show_tags(date)
        if not names and args.assume_headliner:
            names = [show_bill(find_show(date))[0]]
        if not names:
            unmatched.append((date, caption[:70]))
            continue
        for name in names:
            name = canonical_artist(name, aliases)
            slug = _slug(name)
            if slug not in hints:
                unknown[name] = slug
            for aid in assets:
                plan[aid].add(f"artist/{slug}")

    # 3. kind from upload-album membership, for everything on the server.
    for album_id, kind in _album_kinds().items():
        for a in immich.search_metadata(album_id=album_id):
            plan[a["id"]].add(f"kind/{kind}")

    n_tags = sum(len(v) for v in plan.values())
    print(f"{len(plan)} asset(s), {n_tags} tag(s):")
    _apply(plan, args.dry_run)

    if off_host:
        print(f"\nOFF-HOST ({len(off_host)}) - not on the image server; find the asset and run "
              "`add --asset <id> --show <date> --kind with-artist --artist <name>`:")
        for date, who, url, src in off_host:
            print(f"  {date} {who}  {url}  ({src})")
    if dead:
        print(f"\nDEAD KEY ({len(dead)}) - link on the host but no such shared link:")
        for date, who, url in dead:
            print(f"  {date} {who}  {url}")
    if no_date:
        print(f"\nNO SHOW DATE ({len(no_date)}) - row date, day-before and caption date match no show row; "
              "kind tagged, show/ and artist/ not:")
        for iso, cap in no_date:
            print(f"  {iso}  {cap}")
    if unmatched:
        print(f"\nUNMATCHED CAPTION ({len(unmatched)}) - no bill act or sideman named; show/ tagged, "
              "artist/ not (re-run with --assume-headliner, or add seen_with/alias rows):")
        for date, cap in unmatched:
            print(f"  {date}  {cap}")
    if unknown:
        print(f"\nNAME NOT IN LIBRARY ({len(unknown)}) - tagged as given; the album will take this spelling:")
        for name, slug in sorted(unknown.items()):
            print(f"  {name}  -> artist/{slug}")
    if unknown_venues:
        print(f"\nVENUE NOT IN LIBRARY ({len(unknown_venues)}) - no venues.tsv row or venue_aliases.tsv "
              "alias resolves this spelling; tagged as given (add an alias row and re-run):")
        for venue, slug in sorted(unknown_venues.items()):
            print(f"  {venue}  -> venue/{slug}")
    if args.dry_run:
        print("\n[DRY RUN] nothing written. Re-run without --dry-run to tag.")


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

    p = sub.add_parser("add", help="one asset: tag it and place it in its albums")
    p.add_argument("--asset", required=True, metavar="ID_OR_LINK",
                   help="asset id, or the photo's own /share/ link")
    p.add_argument("--show", required=True, metavar="DATE",
                   help="the show date - stated, never derived from EXIF")
    p.add_argument("--kind", required=True, choices=sorted(KIND_ALBUM_NAMES))
    p.add_argument("--artist", metavar="NAME",
                   help="who is in frame; omit for crowd/selfie/anonymous memorabilia")
    p.add_argument("--subtype", metavar="LEAF",
                   help="memorabilia/* leaf, e.g. pick or setlist")
    p.add_argument("--signed", action="store_true")
    p.add_argument("--detail", action="store_true")
    p.add_argument("--write", action="store_true",
                   help="also write the show row and artist-albums.tsv row")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("sync", help="materialise tags into albums + links")
    p.add_argument("--write", action="store_true",
                   help="apply the rows to the library TSVs (show rows, "
                        "artist-albums.tsv, kind-albums.tsv)")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("audit", help="read-only: what does not line up")
    p.add_argument("--fast", action="store_true",
                   help="skip the per-tag membership searches")

    p = sub.add_parser("seed", help="one-time: tag every library-linked asset from its rows")
    p.add_argument("--assume-headliner", action="store_true",
                   help="a caption naming nobody the library knows is the headliner")
    p.add_argument("--dry-run", action="store_true")

    args = ap.parse_args()
    {"plan": cmd_plan, "tag": cmd_tag, "sync": cmd_sync,
     "scaffold": cmd_scaffold, "add": cmd_add,
     "audit": cmd_audit, "seed": cmd_seed}[args.cmd](args)


if __name__ == "__main__":
    main()
