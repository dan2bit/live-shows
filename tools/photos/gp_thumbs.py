#!/usr/bin/env python3
"""
gp_thumbs.py — fill the `gp_thumb` column of gp_scrape.tsv

The winnowing page shows the Google Photos image beside the Immich
candidates, which turns each decision into a glance instead of a tab
switch. That needs a directly embeddable image URL per crosswalk row.
Google's share URLs are opaque and the API is dead, so the URLs are
harvested the same way the captions were.

Two classes of share link, harvested two different ways:

  album-level  (no `/photo/` segment - the item_log memorabilia shares)
      The share page carries an `og:image` meta tag readable with no
      cookies at all, so `album` mode fetches them directly. No browser,
      no session.

  photo-level  (a `/photo/<id>` deep link - the artist photos, all but
      one of them inside a single large shared album)
      No `og:image` at any authentication level. The image URL lives in
      the page payload, reachable only from an authenticated same-origin
      fetch, so `snippet` mode prints browser JS to run against an open
      photos.google.com tab and `merge` mode folds the result back in.

WHY THE SHORTEST TOKEN

  A photo page carries three `lh3.googleusercontent.com/pw/...` tokens
  for the same image: a ~148 char form, a ~185 char form, and a ~1051
  char signed form bound to the photo's `data-media-key`. All three
  render byte-identical output at the same size parameter, and sampling
  pages from three points in the album found no neighbouring photo's
  token on any of them. The shortest is taken because a shorter URL is
  the likelier durable form; if these ever start 404ing, re-run the
  harvest - the page falls back to the click-through link meanwhile.

  Account avatars also appear on the page under `/ogw/`, `/a/` and a
  legacy `/-X.../photo.jpg` form. Only `/pw/` is content.

The stored URL is bare. The size suffix is appended at render time, so
one harvested URL serves any thumbnail size the page asks for.

Exposure note: these URLs reach the same images as the share links the
crosswalk already carries in the public repo, so they widen nothing.
The crosswalk and this scrape file are both temporary, archived once
the rewrite PRs land.
"""

import argparse
import os
import re
import sys
import urllib.request

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", ".."))
sys.path.insert(0, _SCRIPT_DIR)

import immich  # noqa: E402

SCRAPE = os.path.join(_SCRIPT_DIR, "gp_scrape.tsv")
SCRAPE_HEADER = ["link_key", "caption", "gp_thumb"]

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_OG_IMAGE = re.compile(
    r'<meta[^>]*property="og:image"[^>]*content="([^"]+)"', re.I)
# A trailing size token (`=w600-h315-p-k`) is Google's, not ours - strip it
# so the page can ask for whatever size it wants.
_SIZE_TOKEN = re.compile(r"=[wshcpk\d\-]+$")


def _link_key(link):
    """The unique photo or share id a gp_scrape row is keyed by: the
    `/photo/<id>` segment when present, else the `/share/<id>` one."""
    m = re.search(r"/photo/([\w\-]+)", link)
    if m:
        return m.group(1)
    m = re.search(r"/share/([\w\-]+)", link)
    return m.group(1) if m else ""


def _crosswalk_links():
    """(link_key, google_link, is_photo_level) for every crosswalk row."""
    out, seen = [], set()
    for row in immich._read_tsv_rows("tools/photos/backfill_crosswalk.tsv"):
        link = (row.get("google_link") or "").strip()
        key = _link_key(link)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append((key, link, "/photo/" in link))
    return out


def _load_scrape():
    """link_key -> {caption, gp_thumb}, tolerating a file that predates
    the gp_thumb column."""
    out = {}
    for row in immich._read_tsv_rows("tools/photos/gp_scrape.tsv"):
        key = (row.get("link_key") or "").strip()
        if key:
            out[key] = {"caption": (row.get("caption") or "").strip(),
                        "gp_thumb": (row.get("gp_thumb") or "").strip()}
    return out


def _write_scrape(entries):
    with open(SCRAPE, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(SCRAPE_HEADER) + "\n")
        for key in sorted(entries):
            e = entries[key]
            f.write("\t".join([key, e.get("caption", ""),
                               e.get("gp_thumb", "")]) + "\n")


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def cmd_album(args):
    """Anonymous og:image harvest for the album-level shares."""
    entries = _load_scrape()
    targets = [(k, l) for k, l, is_photo in _crosswalk_links()
               if not is_photo and (args.refresh or
                                    not entries.get(k, {}).get("gp_thumb"))]
    if not targets:
        print("every album-level row already has a gp_thumb "
              "(--refresh to redo).")
        return

    got = missed = 0
    for key, link in targets:
        try:
            html = _fetch(link)
        except Exception as exc:
            print(f"  {key[:24]}... fetch failed: {exc}", file=sys.stderr)
            missed += 1
            continue
        m = _OG_IMAGE.search(html)
        if not m:
            print(f"  {key[:24]}... no og:image", file=sys.stderr)
            missed += 1
            continue
        url = _SIZE_TOKEN.sub("", m.group(1))
        entries.setdefault(key, {"caption": "", "gp_thumb": ""})
        entries[key]["gp_thumb"] = url
        got += 1
        if args.verbose:
            print(f"  {key[:24]}... {url[-24:]}")

    _write_scrape(entries)
    print(f"album-level: {got} harvested, {missed} missed, "
          f"{len(entries)} rows in {os.path.basename(SCRAPE)}")


_SNIPPET = """
// Run in the console of an open photos.google.com tab. Paste the printed
// TSV block back via:  python3 gp_thumbs.py merge <file>
const urls = %s;
const out = [];
for (const u of urls) {
  try {
    const h = await (await fetch(u, {credentials: 'include'})).text();
    const toks = [...new Set(h.match(/lh3\\.googleusercontent\\.com\\/pw\\/[\\w\\-]+/g) || [])]
                   .sort((a, b) => a.length - b.length);
    const key = u.match(/\\/photo\\/([\\w\\-]+)/)[1];
    out.push(key + '\\t' + (toks[0] ? 'https://' + toks[0] : ''));
  } catch (e) { out.push('ERROR\\t' + u + '\\t' + e.message); }
}
console.log(out.join('\\n'));
out.length + ' rows - copy the block logged above'
""".strip()


def cmd_snippet(args):
    """Print browser JS for the photo-level shares, in batches."""
    entries = _load_scrape()
    todo = [l for k, l, is_photo in _crosswalk_links()
            if is_photo and (args.refresh or
                             not entries.get(k, {}).get("gp_thumb"))]
    if not todo:
        print("every photo-level row already has a gp_thumb "
              "(--refresh to redo).")
        return
    batches = [todo[i:i + args.batch] for i in range(0, len(todo), args.batch)]
    print(f"// {len(todo)} link(s) to harvest, {len(batches)} batch(es) "
          f"of up to {args.batch}\n")
    for n, batch in enumerate(batches, 1):
        listing = "[\n" + ",\n".join(f"'{u}'" for u in batch) + "]"
        print(f"// ---- batch {n} of {len(batches)} ----")
        print(_SNIPPET % listing)
        print()


def cmd_merge(args):
    """Fold a harvested `link_key<TAB>url` block into gp_scrape.tsv."""
    entries = _load_scrape()
    added = skipped = 0
    with open(args.path, encoding="utf-8-sig") as f:
        for ln in f:
            parts = ln.rstrip("\n").split("\t")
            if len(parts) < 2 or parts[0] in ("ERROR", "link_key"):
                skipped += 1
                continue
            key, url = parts[0].strip(), parts[1].strip()
            if not key or not url.startswith("https://"):
                skipped += 1
                continue
            entries.setdefault(key, {"caption": "", "gp_thumb": ""})
            entries[key]["gp_thumb"] = _SIZE_TOKEN.sub("", url)
            added += 1
    _write_scrape(entries)
    print(f"merged {added} thumb(s), skipped {skipped}, "
          f"{len(entries)} rows in {os.path.basename(SCRAPE)}")


def cmd_status(args):
    entries = _load_scrape()
    links = _crosswalk_links()

    def tally(is_photo):
        rows = [k for k, _, p in links if p == is_photo]
        have = sum(1 for k in rows if entries.get(k, {}).get("gp_thumb"))
        cap = sum(1 for k in rows if entries.get(k, {}).get("caption"))
        return len(rows), have, cap

    for label, is_photo in (("photo-level", True), ("album-level", False)):
        total, have, cap = tally(is_photo)
        print(f"{label:12}  {total:>3} rows   {have:>3} with thumb   "
              f"{cap:>3} with caption")


def main():
    ap = argparse.ArgumentParser(prog="gp_thumbs.py",
                                 description=__doc__.splitlines()[1])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("album", help="anonymous og:image harvest")
    p.add_argument("--refresh", action="store_true",
                   help="re-harvest rows that already have a thumb")
    p.add_argument("--verbose", action="store_true")

    p = sub.add_parser("snippet", help="print browser JS for photo-level links")
    p.add_argument("--batch", type=int, default=15,
                   help="links per batch (default 15)")
    p.add_argument("--refresh", action="store_true")

    p = sub.add_parser("merge", help="fold a harvested block into gp_scrape")
    p.add_argument("path", help="file holding the pasted key<TAB>url lines")

    sub.add_parser("status", help="coverage by link class")

    args = ap.parse_args()
    {"album": cmd_album, "snippet": cmd_snippet,
     "merge": cmd_merge, "status": cmd_status}[args.cmd](args)


if __name__ == "__main__":
    main()
