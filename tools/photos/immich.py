#!/usr/bin/env python3
"""
immich.py — REST wrapper + CLI for the image server (Immich on PikaPods).

The still-photo counterpart of the tools/youtube pipeline: everything the
show library needs from Immich runs through this one module, so the join
between photos and the library TSVs lives in the repo, not in a chat tool.

Capabilities (each a subcommand; see --help):
  verify           server version + reachability + key smoke-test
  search           metadata search: filename / taken date range / album / person / tag
  thumb            fetch an asset thumbnail to a local file (visual identification)
  ocr              recognized text for one asset
  ocr-search       find assets whose recognized text contains a string
  people           list (named) face clusters
  albums           list albums; --create NAME [--assets ...]; --add ALBUM_ID ...
  tags             list tags; --ensure path/one path/two; --bootstrap taxonomy
  tag              attach a hierarchical tag to assets
  links            list existing shared links
  link             mint a shared link over assets (--assets) or an album (--album)
  seed-crosswalk   enumerate every Google Photos link in the show library into
                   the backfill crosswalk TSV, prefilling Immich candidates

Config: IMMICH_API_KEY (required; never committed) and IMMICH_URL (defaults to
the canonical public host) from the environment or tools/photos/.env. The key
is the least-privilege automation key described in
tools/playbooks/IMAGE_SERVER.md — it cannot upload, modify, or delete photos.

Public shared links default to allowDownload=true and showMetadata=false:
viewers can save a photo, but capture time/device/location EXIF stays private,
matching what the old Google Photos share links exposed.

House TSV rules apply throughout: plain tab-joined lines, LF endings, never
the csv module (default quoting corrupts fields containing literal quotes).
"""

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", ".."))

DEFAULT_URL = "https://photos.redhat-bootlegs.net"

LINK_DEFAULTS = {"allowDownload": True, "showMetadata": False, "allowUpload": False}

# Tag taxonomy bootstrap. kind/ mirrors the curated Google Photos albums the
# import recreated; hat detail is a memorabilia subtype rather than a kind.
KIND_TAGS = [
    "kind/with-artist",
    "kind/performance",
    "kind/memorabilia",
    "kind/selfie",
    "kind/crowd",
]
MEMORABILIA_TAGS = [
    "memorabilia/setlist",
    "memorabilia/cd",
    "memorabilia/vinyl",
    "memorabilia/poster",
    "memorabilia/pick",
    "memorabilia/ticket",
    "memorabilia/autograph-book",
    "memorabilia/photo-print",
    "memorabilia/hat",
    "memorabilia/other",
]
FLAT_TAGS = ["signed"]


# ── config ─────────────────────────────────────────────────────────────────

def _load_env_file():
    """Tiny KEY=VALUE reader for tools/photos/.env (gitignored). No dependency
    on python-dotenv; values already in the environment win. Returns the
    file's values so callers can detect shadowing."""
    path = os.path.join(_SCRIPT_DIR, ".env")
    file_vals = {}
    if not os.path.exists(path):
        return file_vals
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            key, _, val = ln.partition("=")
            key, val = key.strip(), val.strip().strip("'\"")
            file_vals[key] = val
            os.environ.setdefault(key, val)
    return file_vals


KEY_SOURCE = "unset"


def _config():
    global KEY_SOURCE
    from_shell = bool(os.environ.get("IMMICH_API_KEY"))
    file_vals = _load_env_file()
    url = os.environ.get("IMMICH_URL", DEFAULT_URL).rstrip("/")
    key = os.environ.get("IMMICH_API_KEY", "")
    if not key:
        raise SystemExit(
            "IMMICH_API_KEY is not set (environment or tools/photos/.env). "
            "The key lives in the password manager; see "
            "tools/playbooks/IMAGE_SERVER.md")
    if from_shell:
        KEY_SOURCE = "shell environment"
        file_key = file_vals.get("IMMICH_API_KEY", "")
        if file_key and file_key != key:
            KEY_SOURCE += " (SHADOWING a different key in tools/photos/.env - unset IMMICH_API_KEY to use the file)"
    else:
        KEY_SOURCE = "tools/photos/.env"
    return url, key


# ── HTTP ───────────────────────────────────────────────────────────────────

def _ssl_context():
    """macOS pythons often lack a system CA store for urllib; prefer certifi's
    bundle when it is importable (it rides in with the youtube tooling's
    dependencies), else fall back to the platform default."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_SSL_CTX = None


def _req(method, path, body=None, raw=False, query=None):
    global _SSL_CTX
    if _SSL_CTX is None:
        _SSL_CTX = _ssl_context()
    url_base, key = _config()
    url = url_base + "/api" + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = None
    headers = {"x-api-key": key, "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:400]
        raise SystemExit(
            f"HTTP {err.code} on {method} {path}: {detail}\n"
            "(403 usually means the automation key lacks a permission - "
            "see the scope list in tools/playbooks/IMAGE_SERVER.md)")
    except urllib.error.URLError as err:
        hint = ""
        if "CERTIFICATE_VERIFY_FAILED" in str(err.reason):
            hint = ("\n(no usable CA store - pip install certifi into this "
                    "environment, or export SSL_CERT_FILE=$(python3 -m certifi))")
        raise SystemExit(f"cannot reach the image server at {url_base}: {err.reason}{hint}")
    if raw:
        return payload
    if not payload:
        return None
    return json.loads(payload)


# ── API surface ────────────────────────────────────────────────────────────

def about():
    return _req("GET", "/server/about")


def search_metadata(filename=None, taken_after=None, taken_before=None,
                    album_id=None, person_id=None, tag_id=None, page_size=250):
    """Paged metadata search; returns a flat list of asset dicts."""
    out, page = [], 1
    while True:
        body = {"page": page, "size": page_size, "withExif": False}
        if filename:
            body["originalFileName"] = filename
        if taken_after:
            body["takenAfter"] = taken_after
        if taken_before:
            body["takenBefore"] = taken_before
        if album_id:
            body["albumIds"] = [album_id]
        if person_id:
            body["personIds"] = [person_id]
        if tag_id:
            body["tagIds"] = [tag_id]
        resp = _req("POST", "/search/metadata", body) or {}
        assets = (resp.get("assets") or {})
        items = assets.get("items", [])
        out.extend(items)
        if not assets.get("nextPage"):
            break
        page += 1
    return out


def asset(asset_id):
    return _req("GET", f"/assets/{asset_id}")


def thumbnail(asset_id, size="preview"):
    return _req("GET", f"/assets/{asset_id}/thumbnail", raw=True,
                query={"size": size})


def ocr(asset_id):
    return _req("GET", f"/assets/{asset_id}/ocr")


def ocr_search(text, page_size=100):
    """OCR text search. Endpoint name follows the server's search family; if
    this 404s on an older server, fall back to per-asset ocr() sweeps."""
    resp = _req("POST", "/search/ocr", {"query": text, "size": page_size}) or {}
    assets = resp.get("assets") or resp
    if isinstance(assets, dict):
        return assets.get("items", [])
    return assets


def albums():
    return _req("GET", "/albums") or []


def album(album_id):
    return _req("GET", f"/albums/{album_id}")


def create_album(name, asset_ids=None, description=""):
    body = {"albumName": name, "description": description}
    if asset_ids:
        body["assetIds"] = list(asset_ids)
    return _req("POST", "/albums", body)


def add_album_assets(album_id, asset_ids):
    return _req("PUT", f"/albums/{album_id}/assets", {"ids": list(asset_ids)})


def tags():
    return _req("GET", "/tags") or []


def ensure_tag(path):
    """Walk a hierarchical tag path (a/b/c), creating missing levels.
    Returns the leaf tag dict."""
    existing = {t.get("value", t.get("name", "")): t for t in tags()}
    parent_id, walked = None, []
    for part in path.strip("/").split("/"):
        walked.append(part)
        value = "/".join(walked)
        if value in existing:
            parent_id = existing[value]["id"]
            continue
        body = {"name": part}
        if parent_id:
            body["parentId"] = parent_id
        created = _req("POST", "/tags", body)
        existing[value] = created
        parent_id = created["id"]
    return existing["/".join(walked)]


def tag_assets(tag_ids, asset_ids):
    return _req("PUT", "/tags/assets",
                {"tagIds": list(tag_ids), "assetIds": list(asset_ids)})


def people(named_only=True):
    resp = _req("GET", "/people") or {}
    everyone = resp.get("people", resp if isinstance(resp, list) else [])
    if named_only:
        return [p for p in everyone if p.get("name")]
    return everyone


def shared_links():
    return _req("GET", "/shared-links") or []


def create_link(asset_ids=None, album_id=None, description=""):
    body = dict(LINK_DEFAULTS)
    body["description"] = description
    if album_id:
        body.update({"type": "ALBUM", "albumId": album_id})
    elif asset_ids:
        body.update({"type": "INDIVIDUAL", "assetIds": list(asset_ids)})
    else:
        raise SystemExit("link needs --assets or --album")
    return _req("POST", "/shared-links", body)


def link_url(link):
    key = link.get("key", "")
    url_base = os.environ.get("IMMICH_URL", DEFAULT_URL).rstrip("/")
    return f"{url_base}/share/{key}"


# ── crosswalk seeding ──────────────────────────────────────────────────────

CROSSWALK_HEADER = ["source_row", "google_link", "google_desc",
                    "immich_candidates", "immich_desc", "match_id",
                    "immich_link", "confidence", "signals", "notes"]

_GP_PREFIX = "https://photos.google.com/"


def _read_tsv_rows(relpath):
    path = os.path.join(_ROOT, relpath)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        lines = [ln.rstrip("\n").rstrip("\r") for ln in f if ln.strip()]
    if not lines:
        return []
    header = lines[0].split("\t")
    rows = []
    for ln in lines[1:]:
        vals = ln.split("\t")
        vals += [""] * (len(header) - len(vals))
        rows.append(dict(zip(header, vals)))
    return rows


def _gather_sources():
    """Yield (source_row, google_link, google_desc, show_date) for every
    Google Photos link in the show library."""
    for row in _read_tsv_rows("data/show_goals/artist-photos.tsv"):
        link = row.get("Share Link", "")
        if link.startswith(_GP_PREFIX):
            yield (f"artist-photos.tsv:{row.get('Caption / Artist Info', '')[:40]}",
                   link, row.get("Caption / Artist Info", ""), "")
    for row in _read_tsv_rows("data/live_shows_current.tsv"):
        link = row.get("Photo URL", "")
        if link.startswith(_GP_PREFIX):
            yield (f"current:{row.get('Show Date', '')} {row.get('Artist', '')}",
                   link,
                   f"{row.get('Artist', '')} at {row.get('Venue Name', '')}",
                   row.get("Show Date", ""))
    hist_dir = os.path.join(_ROOT, "data", "history")
    if os.path.isdir(hist_dir):
        for fname in sorted(os.listdir(hist_dir)):
            if not fname.endswith(".tsv"):
                continue
            for row in _read_tsv_rows(f"data/history/{fname}"):
                link = row.get("Photo URL", "")
                if link.startswith(_GP_PREFIX):
                    yield (f"history/{fname}:{row.get('Show Date', '')} "
                           f"{row.get('Artist', '')}",
                           link,
                           f"{row.get('Artist', '')} at {row.get('Venue', '')}",
                           row.get("Show Date", ""))
    for row in _read_tsv_rows("data/show_goals/item_log.tsv"):
        link = row.get("photo_ref", "")
        if link.startswith(_GP_PREFIX):
            yield (f"item_log.tsv:{row.get('seq', '')}",
                   link,
                   f"{row.get('signer', '')} {row.get('item', '')}",
                   row.get("show_date", ""))


def seed_crosswalk(out_path, use_immich=True):
    """One crosswalk row per distinct Google link; multiple library rows
    sharing a link (e.g. a multi-signer poster) merge into one row with
    joined sources. Existing crosswalk rows are preserved untouched so
    confirmed matches are never re-litigated."""
    existing = {}
    if os.path.exists(out_path):
        for row in _read_tsv_rows(os.path.relpath(out_path, _ROOT)):
            existing[row.get("google_link", "")] = row

    grouped = {}
    for source, link, desc, date in _gather_sources():
        entry = grouped.setdefault(link, {"sources": [], "descs": [], "dates": set()})
        entry["sources"].append(source)
        if desc and desc not in entry["descs"]:
            entry["descs"].append(desc)
        if date:
            entry["dates"].add(date)

    out_rows, seeded, kept = [], 0, 0
    for link, entry in grouped.items():
        if link in existing:
            out_rows.append([existing[link].get(c, "") for c in CROSSWALK_HEADER])
            kept += 1
            continue
        candidates, signals, confidence = "", "", "0"
        dates = sorted(entry["dates"])
        if use_immich and len(dates) == 1:
            date = dates[0]
            hits = search_metadata(taken_after=f"{date}T00:00:00.000Z",
                                   taken_before=f"{date}T23:59:59.999Z")
            if hits:
                candidates = ";".join(h["id"] for h in hits[:12])
                signals = f"date:{date}"
                confidence = "1"
        out_rows.append([" ; ".join(entry["sources"]), link,
                         " / ".join(entry["descs"]), candidates, "", "", "",
                         confidence, signals, ""])
        seeded += 1

    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(CROSSWALK_HEADER) + "\n")
        for row in out_rows:
            f.write("\t".join(row) + "\n")
    return {"links": len(grouped), "seeded": seeded, "kept_existing": kept,
            "out": out_path}


# ── CLI ────────────────────────────────────────────────────────────────────

def _print(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1],
                                 prog="immich.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("verify", help="server version + key smoke-test")

    p = sub.add_parser("search", help="metadata search")
    p.add_argument("--filename")
    p.add_argument("--taken-after")
    p.add_argument("--taken-before")
    p.add_argument("--album")
    p.add_argument("--person")
    p.add_argument("--tag")

    p = sub.add_parser("thumb", help="fetch a thumbnail")
    p.add_argument("asset_id")
    p.add_argument("--out", required=True)
    p.add_argument("--size", default="preview", choices=["thumbnail", "preview"])

    p = sub.add_parser("ocr", help="recognized text for one asset")
    p.add_argument("asset_id")

    p = sub.add_parser("ocr-search", help="search recognized text")
    p.add_argument("text")

    p = sub.add_parser("people", help="face clusters")
    p.add_argument("--all", action="store_true", help="include unnamed clusters")

    p = sub.add_parser("albums", help="list / create / extend albums")
    p.add_argument("--create", metavar="NAME")
    p.add_argument("--description", default="")
    p.add_argument("--add", metavar="ALBUM_ID")
    p.add_argument("assets", nargs="*", help="asset ids for --create/--add")

    p = sub.add_parser("tags", help="list tags / ensure paths / bootstrap taxonomy")
    p.add_argument("--ensure", nargs="*", metavar="PATH", default=None)
    p.add_argument("--bootstrap", action="store_true",
                   help="create the standard kind/memorabilia/signed taxonomy")

    p = sub.add_parser("tag", help="attach a hierarchical tag to assets")
    p.add_argument("path", help="e.g. artist/sue-foley or show/2026/2026-03-11")
    p.add_argument("assets", nargs="+")

    sub.add_parser("links", help="list existing shared links")

    p = sub.add_parser("link", help="mint a shared link (downloads on, EXIF hidden)")
    p.add_argument("--assets", nargs="*", default=None)
    p.add_argument("--album")
    p.add_argument("--description", default="")

    p = sub.add_parser("seed-crosswalk", help="seed the backfill crosswalk TSV")
    p.add_argument("--out", default=os.path.join(_SCRIPT_DIR, "backfill_crosswalk.tsv"))
    p.add_argument("--no-immich", action="store_true",
                   help="enumerate sources only; skip candidate prefill")

    args = ap.parse_args()

    if args.cmd == "verify":
        info = about()
        named = people()
        _print({"server": info.get("version", info),
                "reachable": True,
                "key_source": KEY_SOURCE,
                "named_people": len(named),
                "albums": len(albums()),
                "tags": len(tags())})
    elif args.cmd == "search":
        hits = search_metadata(filename=args.filename,
                               taken_after=args.taken_after,
                               taken_before=args.taken_before,
                               album_id=args.album, person_id=args.person,
                               tag_id=args.tag)
        _print([{"id": h.get("id"),
                 "file": h.get("originalFileName"),
                 "taken": (h.get("fileCreatedAt") or "")[:10]} for h in hits])
    elif args.cmd == "thumb":
        data = thumbnail(args.asset_id, args.size)
        with open(args.out, "wb") as f:
            f.write(data)
        print(f"{len(data)} bytes -> {args.out}")
    elif args.cmd == "ocr":
        _print(ocr(args.asset_id))
    elif args.cmd == "ocr-search":
        hits = ocr_search(args.text)
        _print([{"id": h.get("id"), "file": h.get("originalFileName")} for h in hits])
    elif args.cmd == "people":
        _print([{"id": p_.get("id"), "name": p_.get("name", "")}
                for p_ in people(named_only=not args.all)])
    elif args.cmd == "albums":
        if args.create:
            _print(create_album(args.create, args.assets, args.description))
        elif args.add:
            _print(add_album_assets(args.add, args.assets))
        else:
            _print([{"id": a.get("id"), "name": a.get("albumName"),
                     "assets": a.get("assetCount")} for a in albums()])
    elif args.cmd == "tags":
        if args.bootstrap:
            for path in KIND_TAGS + MEMORABILIA_TAGS + FLAT_TAGS:
                ensure_tag(path)
                print("ensured", path)
        elif args.ensure:
            for path in args.ensure:
                t = ensure_tag(path)
                print("ensured", path, t.get("id"))
        else:
            _print([{"id": t.get("id"), "value": t.get("value", t.get("name"))}
                    for t in tags()])
    elif args.cmd == "tag":
        t = ensure_tag(args.path)
        tag_assets([t["id"]], args.assets)
        print(f"tagged {len(args.assets)} asset(s) with {args.path}")
    elif args.cmd == "links":
        _print([{"id": l.get("id"), "type": l.get("type"),
                 "description": l.get("description", ""),
                 "url": link_url(l)} for l in shared_links()])
    elif args.cmd == "link":
        link = create_link(asset_ids=args.assets, album_id=args.album,
                           description=args.description)
        print(link_url(link))
    elif args.cmd == "seed-crosswalk":
        result = seed_crosswalk(args.out, use_immich=not args.no_immich)
        _print(result)


if __name__ == "__main__":
    main()
