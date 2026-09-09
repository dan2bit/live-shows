#!/usr/bin/env python3
"""
close_photo_issue.py

Called by the photo-close GitHub Actions workflow
(.github/workflows/close-photo-issue.yml) when a `Photo:` issue receives a
comment that begins with the photo's own image-server share link.

Usage:
    python scripts/close_photo_issue.py <issue_title> <share_link>

Parses the artist, show date, and venue from the issue title
    Photo: [Artist] — [YYYY-MM-DD] ([Venue short name])
resolves the pasted per-photo link to its Immich asset, and hands that one
asset to tools/photos/show_photos.py add_asset(), which owns everything on
the server side: tags (kind/with-artist, artist/<slug>, show/<date>,
venue/<slug>), the show album, the artist album, the kind album, and one
share link per album, minted only when none exists.

Two library rows are then upserted from the links add_asset() reports:

    live_shows_current.tsv (or the history file)  Photo URL  <- show-album link
    data/show_goals/artist-albums.tsv             Artist row <- artist-album link

Both are idempotent on the same link, so the second and later photos from
one show, and the second and later shows with one artist, are no-ops on
the rows and membership adds on the server. There is no per-photo ledger:
the show album is the record of the night, the artist album the record of
the artist, and the tags on the asset the record of what the photo is.

The artist name is canonicalized through recommend_aliases.tsv before it
becomes a tag, so billing drift ("X & Y" title vs "X and Y" row) resolves
via a data row, never a code change.

Exits:
    0  — rows written, or already correct
    1  — error (title unparseable, link unresolvable, no show row, Immich
         refused a call)

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

# Photo: [Artist] — [YYYY-MM-DD] ([Venue])   (em dash or hyphen as the separator)
TITLE_RE = re.compile(
    r"^Photo:\s*(?P<artist>.+?)\s*[—-]\s*(?P<date>\d{4}-\d{2}-\d{2})\s*\((?P<venue>.+)\)\s*$"
)


def _gh_output(**kv):
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if not gh_out:
        return
    with open(gh_out, "a", encoding="utf-8") as fh:
        for k, v in kv.items():
            fh.write(f"{k}={v}\n")


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <issue_title> <share_link>", file=sys.stderr)
        return 1

    title = sys.argv[1].strip()
    link = sys.argv[2].strip()

    m = TITLE_RE.match(title)
    if not m:
        print(f"ERROR: could not parse issue title: {title!r}", file=sys.stderr)
        return 1
    artist = show_photos.canonical_artist(m.group("artist").strip())
    iso = m.group("date")

    asset_id = show_photos.resolve_asset(link)
    print(f"asset {asset_id} <- {link}")

    res = show_photos.add_asset(asset_id, iso, "with-artist", artist=artist)

    print()
    print(show_photos.set_show_photo_url(iso, res["show_link"]))
    print(show_photos.upsert_artist_album(res["artist"], res["artist_link"]))

    _gh_output(show_link=res["show_link"], artist=res["artist"],
               artist_link=res["artist_link"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
