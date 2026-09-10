#!/usr/bin/env python3
"""
reconcile_photos.py

Offline lint of every photo link the show library carries: the Photo URL on
each show row (live_shows_current.tsv and data/history/*.tsv) and the Album
URL on each data/show_goals/artist-albums.tsv and kind-albums.tsv row.
Reports only — never auto-fixes, and needs no server access.

  OFF-HOST — a link that does not point at the image server (a retired
             Google Photos link that escaped the migration, or a typo in the
             host). The site would render it, but it is not part of the
             library any more.
  MALFORMED — an image-server URL with no /share/<key> token, or a key that
             is not the shape the server issues. A dead badge on the live
             site.
  DUPLICATE — two show rows carrying the same share key. Every show has its
             own album, so two rows on one link means one of them is wrong.

Anything that needs the server — whether a key resolves, whether a show
row's link is the show album rather than a per-photo link, whether every
artist/ tag has a row — is `tools/photos/show_photos.py audit`, which runs
with the automation key and is not a CI check.

Usage:
    python scripts/reconcile_photos.py [--strict]

Exit codes:
    0  — clean, or only OFF-HOST findings
    1  — any MALFORMED or DUPLICATE finding; or any finding under --strict

The issue history behind these designs is logged in docs/ISSUE_LOG.md.
"""

import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

CURRENT = Path("data/live_shows_current.tsv")
HISTORY_DIR = Path("data/history")
ALBUM_FILES = (Path("data/show_goals/artist-albums.tsv"),
               Path("data/show_goals/kind-albums.tsv"))

PHOTO_HOST = "photos.redhat-bootlegs.net"
SHARE_KEY_RE = re.compile(r"^/share/([A-Za-z0-9_-]{20,})$")
DATE_HEADERS = ("Show Date", "Date")
ARTIST_HEADERS = ("Artist", "Headliner")


def classify(url):
    """(status, key) where status is "ok", "off-host" or "malformed"."""
    parts = urlsplit(url)
    if parts.netloc.lower() != PHOTO_HOST:
        return "off-host", None
    m = SHARE_KEY_RE.match(parts.path)
    if not m:
        return "malformed", None
    return "ok", m.group(1)


def _col(header, names):
    for n in names:
        if n in header:
            return header.index(n)
    return None


def _rows(path, url_col, label_cols):
    """[(label, url)] for every row of a TSV with a non-empty url column."""
    out = []
    if not path.exists():
        return out
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not lines:
        return out
    header = lines[0].split("\t")
    if url_col not in header:
        return out
    ui = header.index(url_col)
    li = [_col(header, names) for names in label_cols]
    for ln in lines[1:]:
        c = ln.split("\t")
        if len(c) <= ui:
            continue
        url = c[ui].strip()
        if not url or url == "-":
            continue
        label = " ".join(c[i].strip() for i in li if i is not None and i < len(c))
        out.append((label, url))
    return out


def main():
    strict = "--strict" in sys.argv[1:]
    files = ([CURRENT] if CURRENT.exists() else []) + (
        sorted(HISTORY_DIR.glob("*.tsv")) if HISTORY_DIR.is_dir() else [])

    off_host, malformed, seen = [], [], {}
    for path in files:
        for label, url in _rows(path, "Photo URL", (DATE_HEADERS, ARTIST_HEADERS)):
            status, key = classify(url)
            if status == "off-host":
                off_host.append((path.name, label, url))
            elif status == "malformed":
                malformed.append((path.name, label, url))
            else:
                seen.setdefault(key, []).append((path.name, label))
    for path in ALBUM_FILES:
        for label, url in _rows(path, "Album URL", (("Artist", "Kind"),)):
            status, _ = classify(url)
            if status == "off-host":
                off_host.append((path.name, label, url))
            elif status == "malformed":
                malformed.append((path.name, label, url))

    duplicates = {k: v for k, v in seen.items() if len(v) > 1}

    for title, rows in (("MALFORMED - image-server URL with no usable share key:", malformed),
                        ("OFF-HOST - link is not on the image server:", off_host)):
        if rows:
            print(title)
            for src, label, url in rows:
                print(f"  [{src}] {label}  {url}")
    if duplicates:
        print("DUPLICATE - one share key on more than one show row:")
        for key, rows in duplicates.items():
            print(f"  {key}")
            for src, label in rows:
                print(f"      [{src}] {label}")
    if not (malformed or off_host or duplicates):
        print("OK - every photo link is a well-formed image-server share link.")

    hard = bool(malformed or duplicates)
    return 1 if hard or (strict and off_host) else 0


if __name__ == "__main__":
    sys.exit(main())
