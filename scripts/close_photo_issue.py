#!/usr/bin/env python3
"""
close_photo_issue.py

Called by the photo-close GitHub Actions workflow
(.github/workflows/close-photo-issue.yml) when a `Photos:` issue receives a
comment that begins with a photo's own image-server share link.

Usage:
    python scripts/close_photo_issue.py <issue_title> <comment_body>
    python scripts/close_photo_issue.py --self-test

One issue per show; one comment per photo. The issue title names the show:

    Photos: [Headliner] — [YYYY-MM-DD] ([Venue short name]) — before [YYYY-MM-DD]
    Photos: [Headliner] — [YYYY-MM-DD] ([Venue short name])
    Photo:  [Artist]    — [YYYY-MM-DD] ([Venue short name])   (older, per-artist form)

Only the artist and the show date are read. Anything after the venue's
closing parenthesis - the filing-deadline suffix the issue template adds,
or a note typed onto the title later - is ignored.

--self-test parses a set of synthetic titles, then fills in the title line
of .github/ISSUE_TEMPLATE/photo.md and parses that too, so the template and
this parser cannot drift apart unnoticed. It needs no key and no network.

The comment's first line is the photo's per-photo share link, optionally
followed by tokens:

    https://photos.../share/KEY
    https://photos.../share/KEY artist="Steve Bell"
    https://photos.../share/KEY subtype=pick signed artist="Ghalia Volt"
    https://photos.../share/KEY item=73
    https://photos.../share/KEY close

    artist="..."   who is in frame. Defaults to the title's artist for a
                   with-artist photo; nobody otherwise. Quote it.
    subtype=LEAF   memorabilia only: setlist, cd, vinyl, poster, pick,
                   ticket, autograph-book, photo-print, hat, other
    signed         memorabilia carries a signature
    item=N         the photo is of item N in data/items.tsv. subtype, signed
                   and artist then default to what the ledger says, and the
                   link is stored on the item (tools/items/ledger.py)
    detail         a close-up of an item already filed
    close          this is the last photo; close the issue

The photo's kind is never typed: it is whichever of the five upload albums
the photo was put in from the phone. A photo in none of them is refused
with a message rather than guessed at.

Everything server-side is tools/photos/show_photos.py add_asset(): tags,
show / artist / kind albums, one share link per album minted only when
none exists. Two library rows are then upserted:

    live_shows_current.tsv (or the history file)  Photo URL  <- show-album link
    data/show_goals/artist-albums.tsv             Artist row <- artist-album link

Both are idempotent, so every photo after the first from one show is a
no-op on the show row and a membership add on the server. With item=N a
third write stores the photo's link on that item in the items ledger; without
it, recording the item itself stays a separate, human step.

The artist name is canonicalized through recommend_aliases.tsv before it
becomes a tag, so billing drift resolves via a data row, never a code change.

Outputs (GITHUB_OUTPUT): kind, show_link, artist, artist_link, close.

Exits:
    0  — filed
    1  — error (title unparseable, link unresolvable, no show row, unknown
         subtype, photo in no upload album, Immich refused a call)

Requires IMMICH_API_KEY in the environment: in CI that is the least-privilege
photo-close key held as a repository secret (see
tools/playbooks/IMAGE_SERVER.md); nothing here can upload, modify or delete
a photo.

The issue history behind these designs is logged in docs/ISSUE_LOG.md.
"""

import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "tools" / "photos"))

import show_photos  # noqa: E402

# Photo(s): [Artist] — [YYYY-MM-DD] ([Venue]) [anything]   (em dash or hyphen as
# the separator). The venue stops at the first closing parenthesis so that
# trailing text, which may hold parentheses of its own, is never read as venue.
TITLE_RE = re.compile(
    r"^Photo(?P<plural>s)?:\s*(?P<artist>.+?)\s*[—-]\s*(?P<date>\d{4}-\d{2}-\d{2})"
    r"\s*\((?P<venue>[^)]+)\)(?P<trailing>.*)$"
)
TEMPLATE = _HERE.parent / ".github" / "ISSUE_TEMPLATE" / "photo.md"
LINK_RE = re.compile(r"^\s*(?P<link>https://\S+/share/[A-Za-z0-9_-]+)(?P<rest>.*)$")
TOKEN_RE = re.compile(r"""(?P<key>[a-z]+)(?:=(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<bare>\S+)))?""")
FLAGS = {"signed", "detail", "close"}
VALUES = {"artist", "subtype", "item"}


def parse_title(title):
    """(artist, iso date) from an issue title, or None when it is not a photo
    issue title. The artist is returned as typed, not canonicalized."""
    m = TITLE_RE.match((title or "").strip())
    if not m:
        return None
    return m.group("artist").strip(), m.group("date")


def parse_comment(body):
    """(link, opts) from the first line of a comment. Unknown tokens are an
    error: a typo in `subtyp=pick` must not file a photo as untyped."""
    first = (body or "").strip().split("\n", 1)[0]
    m = LINK_RE.match(first)
    if not m:
        raise SystemExit("comment must begin with the photo's /share/ link")
    opts = {"signed": False, "detail": False, "close": False}
    for t in TOKEN_RE.finditer(m.group("rest")):
        key = t.group("key")
        val = t.group("dq") if t.group("dq") is not None else (
            t.group("sq") if t.group("sq") is not None else t.group("bare"))
        if key in FLAGS and val is None:
            opts[key] = True
        elif key in VALUES and val:
            opts[key] = val.strip()
        else:
            raise SystemExit(f"unrecognised token {t.group(0)!r}; allowed: "
                             "artist=\"...\", subtype=LEAF, item=N, signed, detail, close")
    return m.group("link"), opts


def _gh_output(**kv):
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if not gh_out:
        return
    with open(gh_out, "a", encoding="utf-8") as fh:
        for k, v in kv.items():
            fh.write(f"{k}={v}\n")


def template_title():
    """The title line of the photo issue template with every placeholder
    filled in, or None when the template has no title line."""
    for line in TEMPLATE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"""^title:\s*(["']?)(?P<title>.*)\1\s*$""", line)
        if m:
            fill = {"HEADLINER": "Sample Artist", "YYYY-MM-DD": "2030-06-02",
                    "VENUE_SHORT": "Sample Hall", "NEXT_SHOW_DATE": "2030-06-09"}
            return re.sub(r"\{\{([^}]+)\}\}",
                          lambda p: fill.get(p.group(1), "sample"), m.group("title"))
    return None


def self_test() -> int:
    want = ("Sample Artist", "2030-06-02")
    cases = [
        ("Photos: Sample Artist — 2030-06-02 (Sample Hall)", want),
        ("Photo: Sample Artist — 2030-06-02 (Sample Hall)", want),
        ("Photos: Sample Artist - 2030-06-02 (Sample Hall)", want),
        ("Photos: Sample Artist — 2030-06-02 (Sample Hall) — before 2030-06-09", want),
        ("Photos: Sample Artist — 2030-06-02 (Sample Hall) — before the next show", want),
        ("Photos: Sample Artist — 2030-06-02 (Sample Hall) (reshoot the poster)", want),
        ("Photos:   Sample Artist — 2030-06-02 (Sample Hall)   ", want),
        ("Photos: Sample-Artist Band — 2030-06-02 (Sample Hall)",
         ("Sample-Artist Band", "2030-06-02")),
        ("Photos: Sample Artist — 2030-06-02", None),
        ("Photos: Sample Artist (Sample Hall) — before 2030-06-09", None),
        ("Playlist: Sample Artist — 2030-06-02 (Sample Hall)", None),
    ]
    filled = template_title()
    if filled is None:
        print(f"self-test FAILED: no title line in {TEMPLATE.name}")
        return 1
    cases.append((filled, want))
    bad = 0
    for title, expect in cases:
        got = parse_title(title)
        if got != expect:
            bad += 1
            print(f"self-test FAILED: {title!r} wanted {expect} got {got}")
    print(f"self-test: {len(cases)} cases, {bad} failed.")
    return 1 if bad else 0


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        return self_test()
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <issue_title> <comment_body>", file=sys.stderr)
        return 1

    parsed = parse_title(sys.argv[1])
    if not parsed:
        print(f"ERROR: could not parse issue title: {sys.argv[1]!r}", file=sys.stderr)
        return 1
    iso = parsed[1]
    title_artist = show_photos.canonical_artist(parsed[0])

    link, opts = parse_comment(sys.argv[2])
    asset_id = show_photos.resolve_asset(link)
    print(f"asset {asset_id} <- {link}")

    kind = show_photos.asset_kind(asset_id)
    if kind is None:
        print("ERROR: this photo is in none of the five upload albums; move it into "
              "one in Immich and comment the link again", file=sys.stderr)
        return 1
    item = opts.get("item")
    if item:
        if not item.isdigit():
            print(f"ERROR: item= takes the item's number, got {item!r}", file=sys.stderr)
            return 1
        plan = show_photos.item_defaults(item, asset_id, kind)
        opts.setdefault("artist", plan["artist"])
        opts.setdefault("subtype", plan["subtype"])
        opts["signed"] = opts["signed"] or plan["signed"]
    artist = opts.get("artist")
    if artist:
        artist = show_photos.canonical_artist(artist)
    elif kind == "with-artist":
        artist = title_artist
    # selfie / crowd / performance / memorabilia: nobody unless stated - a
    # performance shot may be the support act, and that is never assumed.

    res = show_photos.add_asset(asset_id, iso, kind, artist=artist,
                                subtype=opts.get("subtype"),
                                signed=opts["signed"], detail=opts["detail"])

    print()
    print(show_photos.set_show_photo_url(iso, res["show_link"]))
    if res["artist"]:
        print(show_photos.upsert_artist_album(res["artist"], res["artist_link"]))
    if item:
        print(show_photos.record_item_photo(item, link))

    _gh_output(kind=res["kind"], show_link=res["show_link"],
               artist=res["artist"] or "", artist_link=res["artist_link"] or "",
               close="true" if opts["close"] else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
