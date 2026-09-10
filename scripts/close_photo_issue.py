#!/usr/bin/env python3
"""
close_photo_issue.py

Called by the photo-close GitHub Actions workflow
(.github/workflows/close-photo-issue.yml) when a `Photos:` issue receives a
comment that begins with a photo's own image-server share link.

Usage:
    python scripts/close_photo_issue.py <issue_title> <comment_body>

One issue per show; one comment per photo. The issue title names the show:

    Photos: [Headliner] — [YYYY-MM-DD] ([Venue short name])
    Photo:  [Artist]    — [YYYY-MM-DD] ([Venue short name])   (older, per-artist form)

The comment's first line is the photo's per-photo share link, optionally
followed by tokens:

    https://photos.../share/KEY
    https://photos.../share/KEY artist="Steve Bell"
    https://photos.../share/KEY subtype=pick signed artist="Ghalia Volt"
    https://photos.../share/KEY close

    artist="..."   who is in frame. Defaults to the title's artist for a
                   with-artist photo; nobody otherwise. Quote it.
    subtype=LEAF   memorabilia only: setlist, cd, vinyl, poster, pick,
                   ticket, autograph-book, photo-print, hat, other
    signed         memorabilia carries a signature
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
no-op on the show row and a membership add on the server. Memorabilia also
belongs in item_log.tsv; that is a separate, human step.

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

# Photo(s): [Artist] — [YYYY-MM-DD] ([Venue])   (em dash or hyphen as the separator)
TITLE_RE = re.compile(
    r"^Photo(?P<plural>s)?:\s*(?P<artist>.+?)\s*[—-]\s*(?P<date>\d{4}-\d{2}-\d{2})\s*\((?P<venue>.+)\)\s*$"
)
LINK_RE = re.compile(r"^\s*(?P<link>https://\S+/share/[A-Za-z0-9_-]+)(?P<rest>.*)$")
TOKEN_RE = re.compile(r"""(?P<key>[a-z]+)(?:=(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<bare>\S+)))?""")
FLAGS = {"signed", "detail", "close"}
VALUES = {"artist", "subtype"}


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
                             "artist=\"...\", subtype=LEAF, signed, detail, close")
    return m.group("link"), opts


def _gh_output(**kv):
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if not gh_out:
        return
    with open(gh_out, "a", encoding="utf-8") as fh:
        for k, v in kv.items():
            fh.write(f"{k}={v}\n")


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <issue_title> <comment_body>", file=sys.stderr)
        return 1

    m = TITLE_RE.match(sys.argv[1].strip())
    if not m:
        print(f"ERROR: could not parse issue title: {sys.argv[1]!r}", file=sys.stderr)
        return 1
    iso = m.group("date")
    title_artist = show_photos.canonical_artist(m.group("artist").strip())

    link, opts = parse_comment(sys.argv[2])
    asset_id = show_photos.resolve_asset(link)
    print(f"asset {asset_id} <- {link}")

    kind = show_photos.asset_kind(asset_id)
    if kind is None:
        print("ERROR: this photo is in none of the five upload albums; move it into "
              "one in Immich and comment the link again", file=sys.stderr)
        return 1
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

    _gh_output(kind=res["kind"], show_link=res["show_link"],
               artist=res["artist"] or "", artist_link=res["artist_link"] or "",
               close="true" if opts["close"] else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
