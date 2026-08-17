#!/usr/bin/env python3
"""
yt_mcp.py — local MCP server for conversational channel audits and capped edits.

A thin, first-party stdio server the desktop app launches so a conversation
can inspect and (carefully) correct the @dan2bit YouTube channel. The trust
model is structural, not behavioral:

  READ tier    — TSV-first (youtube_videos.tsv / youtube_playlists.tsv), API
                 only where the cache cannot answer (statistics, comments).
                 Cannot write anything.
  PROPOSE tier — dry-run only. Produces a persisted change-set of OLD/NEW
                 pairs (or a playlist plan) for human review. Cannot write.
  APPLY tier   — the only writes. Replays a previously reviewed change-set,
                 under a server-enforced per-call cap, with a per-item mid-air
                 check (skip if the live value drifted since proposal).
                 There are NO delete tools. A change-set expires after a day.

So the model cannot write anything that was not first shown as a diff, and
never more items per call than the cap. The OAuth token (token.json, minted by
the upload pipeline) never leaves this machine; reads use the API key only.

Conventions (title/description templates, the "(bootleg)" parse anchor, blank
sentinels) come from youtube.yml via yt_config, shared with the emitters —
the auditor and the writer cannot drift apart. Text after the bootleg marker
in a title is operator-owned: parsers ignore it, and edit proposals built
from parsed titles carry it forward unchanged.

The description cache is stored full-length and whitespace-flattened by
youtube_fetch.py; this server treats that as its parsing contract. An audit
over truncated data would certify what it cannot see.

Register under mcpServers as:
    {"command": "python3", "args": ["/path/to/tools/youtube/yt_mcp.py"]}

Requires: YOUTUBE_API_KEY in tools/youtube/.env for reads; token.json (from
the upload pipeline's auth flow) only when applying.

The issue history behind these designs is logged in docs/ISSUE_LOG.md.
"""

import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

import yt_config

_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", ".."))
VIDEOS_TSV = os.path.join(_SCRIPT_DIR, "youtube_videos.tsv")
PLAYLISTS_TSV = os.path.join(_SCRIPT_DIR, "youtube_playlists.tsv")
VENUES_TSV = os.path.join(_ROOT, "data", "venues.tsv")
VENUE_ALIASES_TSV = os.path.join(_ROOT, "data", "venue_aliases.tsv")
ARTIST_ALIASES_TSV = os.path.join(_ROOT, "data", "recommend_aliases.tsv")
TOKEN_PATH = os.path.join(_SCRIPT_DIR, "token.json")

CFG = yt_config.load_config()
CHANGESET_DIR = os.path.join(_SCRIPT_DIR, CFG["mcp"]["changeset_dir"])
EXPIRY_SECONDS = int(CFG["mcp"]["changeset_expiry_hours"]) * 3600
APPLY_CAP_DEFAULT = int(CFG["mcp"]["apply_cap_default"])
# Any one of these grants the update/insert calls the apply tier makes. The
# upload pipeline mints its token with the first; the token's OWN scopes are
# authoritative — overriding them at load time poisons the refresh request.
WRITE_CAPABLE_SCOPES = {
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
}


# ── data access ────────────────────────────────────────────────────────────

def _read_tsv(path):
    """Plain tab-split rows as dicts; short rows padded. No csv module —
    default quoting corrupts fields that contain literal quotes."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
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


_CACHE = {}


def _videos():
    if "videos" not in _CACHE:
        _CACHE["videos"] = _read_tsv(VIDEOS_TSV)
    return _CACHE["videos"]


def _playlists():
    if "playlists" not in _CACHE:
        _CACHE["playlists"] = _read_tsv(PLAYLISTS_TSV)
    return _CACHE["playlists"]


def _artist_alias_map():
    """norm(alias) -> norm(canonical), from the shared manual alias file.
    Rows starting with a comment mark are skipped; the file is not
    in-page-editable so its comment block is expected."""
    if "aliases" in _CACHE:
        return _CACHE["aliases"]
    amap = {}
    if os.path.exists(ARTIST_ALIASES_TSV):
        with open(ARTIST_ALIASES_TSV, encoding="utf-8") as f:
            for ln in f:
                if ln.startswith("#") or not ln.strip():
                    continue
                parts = ln.rstrip("\n").split("\t")
                if len(parts) >= 2 and parts[0].strip() and parts[1].strip():
                    amap[yt_config.norm_name(parts[0])] = yt_config.norm_name(parts[1])
    _CACHE["aliases"] = amap
    return amap


def _canon_artist(name):
    n = yt_config.norm_name(name)
    return _artist_alias_map().get(n, n)


def _api_key_client():
    if "yt_read" in _CACHE:
        return _CACHE["yt_read"]
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))
    except ImportError:
        pass
    key = os.environ.get("YOUTUBE_API_KEY", "")
    if not key or key == "your_api_key_here":
        raise RuntimeError("YOUTUBE_API_KEY is not set (tools/youtube/.env)")
    from googleapiclient.discovery import build
    _CACHE["yt_read"] = build("youtube", "v3", developerKey=key)
    return _CACHE["yt_read"]


def _oauth_client():
    """Write-capable client from the upload pipeline's token.json. This server
    never runs a consent flow — mint or refresh the token with the upload
    script's auth mode, as the brand channel."""
    if "yt_write" in _CACHE:
        return _CACHE["yt_write"]
    if not os.path.exists(TOKEN_PATH):
        raise RuntimeError(
            "token.json not found - run the upload pipeline's --auth-only "
            "flow first (consent as the brand channel)")
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_file(TOKEN_PATH)
    if not (set(creds.scopes or []) & WRITE_CAPABLE_SCOPES):
        raise RuntimeError(
            "token.json lacks a write-capable scope - re-mint it via the "
            "upload pipeline's auth flow (consent as the brand channel)")
    if not creds.valid and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
    _CACHE["yt_write"] = build("youtube", "v3", credentials=creds)
    return _CACHE["yt_write"]


# ── change-set store ───────────────────────────────────────────────────────

def _save_changeset(payload):
    os.makedirs(CHANGESET_DIR, exist_ok=True)
    cs_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8]
    payload["change_set_id"] = cs_id
    payload["created"] = time.time()
    payload["applied_items"] = []
    with open(os.path.join(CHANGESET_DIR, cs_id + ".json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return cs_id


def _load_changeset(cs_id):
    if not re.fullmatch(r"[0-9]{14}-[0-9a-f]{8}", cs_id or ""):
        raise RuntimeError("malformed change_set_id")
    path = os.path.join(CHANGESET_DIR, cs_id + ".json")
    if not os.path.exists(path):
        raise RuntimeError("unknown change_set_id (never proposed, or cleaned up)")
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    if time.time() - payload.get("created", 0) > EXPIRY_SECONDS:
        raise RuntimeError("change-set expired - re-propose so the diff is fresh")
    return payload, path


def _update_changeset(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


# ── read tier ──────────────────────────────────────────────────────────────

def tool_catalog_search(artist=None, song=None, text=None, cover_only=False,
                        date_from=None, date_to=None, limit=50):
    want_artist = _canon_artist(artist) if artist else None
    want_song = yt_config.norm_name(song) if song else None
    want_text = (text or "").casefold() or None
    out = []
    for row in _videos():
        parsed = yt_config.parse_title(row.get("title", ""), CFG)
        pub = row.get("published", "")
        if date_from and pub < date_from:
            continue
        if date_to and pub > date_to:
            continue
        if want_artist and _canon_artist(parsed["artist"]) != want_artist:
            continue
        if want_song and want_song not in yt_config.norm_name(parsed["song"]):
            continue
        desc = row.get("description", "")
        if cover_only and "cover" not in desc.casefold():
            continue
        if want_text and want_text not in (row.get("title", "") + " " + desc).casefold():
            continue
        out.append({
            "video_id": row.get("video_id", ""),
            "title": row.get("title", ""),
            "artist": parsed["artist"],
            "song": parsed["song"],
            "trailer": parsed["trailer"],
            "published": pub,
            "duration": row.get("duration", ""),
            "url": row.get("url", ""),
            "description": desc,
        })
        if len(out) >= int(limit):
            break
    return {"matches": out, "count": len(out), "source": "youtube_videos.tsv"}


def tool_video_stats(video_ids):
    yt = _api_key_client()
    stats = {}
    ids = list(dict.fromkeys(video_ids))
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        resp = yt.videos().list(part="statistics,snippet", id=",".join(batch)).execute()
        for item in resp.get("items", []):
            st = item.get("statistics", {})
            stats[item["id"]] = {
                "title": item.get("snippet", {}).get("title", ""),
                "views": int(st.get("viewCount", 0)),
                "likes": int(st.get("likeCount", 0)),
                "comments": int(st.get("commentCount", 0)),
            }
    return {"stats": stats, "count": len(stats)}


def _iter_channel_text():
    for row in _videos():
        vid = row.get("video_id", "")
        yield ("video", vid, "title", row.get("title", ""))
        yield ("video", vid, "description", row.get("description", ""))
    for row in _playlists():
        pid = row.get("playlist_id", "")
        yield ("playlist", pid, "title", row.get("title", ""))
        yield ("playlist", pid, "description", row.get("description", ""))


def tool_audit_venues(venue=None):
    aliases = _read_tsv(VENUE_ALIASES_TSV)
    canon_filter = yt_config.norm_name(venue) if venue else None
    findings = {}
    for arow in aliases:
        alias = arow.get("Alias", "").strip()
        canonical = arow.get("Venue Name", "").strip()
        if not alias or not canonical:
            continue
        if canon_filter and yt_config.norm_name(canonical) != canon_filter:
            continue
        if yt_config.norm_name(alias) == yt_config.norm_name(canonical):
            continue
        pat = re.compile(re.escape(alias), re.IGNORECASE)
        for item_type, item_id, field, value in _iter_channel_text():
            if pat.search(value):
                findings.setdefault(canonical, []).append({
                    "item_type": item_type, "item_id": item_id, "field": field,
                    "found": alias, "text": value,
                })
    total = sum(len(v) for v in findings.values())
    return {"divergences_by_venue": findings, "total": total,
            "note": "each entry is paste-ready input for propose_edits"}


def tool_audit_text(pattern, scope="all", limit=200):
    try:
        pat = re.compile(pattern, re.IGNORECASE)
    except re.error as err:
        raise RuntimeError("bad pattern: " + str(err))
    scopes = {"all", "video_titles", "video_descriptions",
              "playlist_titles", "playlist_descriptions"}
    if scope not in scopes:
        raise RuntimeError("scope must be one of " + ", ".join(sorted(scopes)))
    matches = []
    for item_type, item_id, field, value in _iter_channel_text():
        key = item_type + "_" + field + "s"
        if scope != "all" and key != scope:
            continue
        m = pat.search(value)
        if m:
            matches.append({"item_type": item_type, "item_id": item_id,
                            "field": field, "match": m.group(0), "text": value})
            if len(matches) >= int(limit):
                break
    return {"matches": matches, "count": len(matches)}


def tool_comments_pending(filter="unknown_song", max_videos=10, since=None):
    yt = _api_key_client()
    targets = []
    for row in _videos():
        title = row.get("title", "")
        if filter == "unknown_song" and "Unknown Song" not in title:
            continue
        if since and row.get("published", "") < since:
            continue
        targets.append(row)
    targets = targets[: int(max_videos)]
    results = []
    for row in targets:
        vid = row.get("video_id", "")
        entry = {"video_id": vid, "title": row.get("title", ""), "comments": []}
        try:
            resp = yt.commentThreads().list(
                part="snippet", videoId=vid, maxResults=20,
                textFormat="plainText", order="relevance").execute()
            for item in resp.get("items", []):
                top = item["snippet"]["topLevelComment"]["snippet"]
                entry["comments"].append({
                    "author": top.get("authorDisplayName", ""),
                    "text": top.get("textDisplay", ""),
                    "published": top.get("publishedAt", "")[:10],
                    "likes": top.get("likeCount", 0),
                })
        except Exception as err:
            entry["error"] = str(err)[:200]
        results.append(entry)
    with_comments = sum(1 for r in results if r["comments"])
    return {"videos": results, "videos_checked": len(results),
            "videos_with_comments": with_comments}


# ── propose tier ───────────────────────────────────────────────────────────

def _live_snapshots(video_ids, playlist_ids):
    """Raw live title/description per id, via API-key reads (batched).

    Proposals anchor to the LIVE value, not the cache: the cache flattens
    newlines for searchability, so a description with real line breaks can
    never byte-match it and the apply tier's drift check would refuse every
    edit. The cache stays the discovery layer; the diff the human reviews and
    the value the drift check compares are both reality."""
    yt = _api_key_client()
    snaps = {}
    vids = list(dict.fromkeys(video_ids))
    for i in range(0, len(vids), 50):
        resp = yt.videos().list(part="snippet", id=",".join(vids[i:i + 50])).execute()
        for item in resp.get("items", []):
            sn = item.get("snippet", {})
            snaps[("video", item["id"])] = {
                "title": sn.get("title", ""),
                "description": sn.get("description", "")}
    for pid in dict.fromkeys(playlist_ids):
        resp = yt.playlists().list(part="snippet", id=pid).execute()
        for item in resp.get("items", []):
            sn = item.get("snippet", {})
            snaps[("playlist", item["id"])] = {
                "title": sn.get("title", ""),
                "description": sn.get("description", "")}
    return snaps


def tool_propose_edits(edits):
    if not edits:
        raise RuntimeError("no edits given")
    vids = {r.get("video_id"): r for r in _videos()}
    pls = {r.get("playlist_id"): r for r in _playlists()}
    for e in edits:
        it = e.get("item_type", "video")
        if it not in ("video", "playlist"):
            raise RuntimeError("item_type must be video or playlist")
        if (vids if it == "video" else pls).get(e.get("item_id", "")) is None:
            raise RuntimeError(it + " not in cache: " + str(e.get("item_id")) +
                               " (refresh the fetch TSVs first)")
    snaps = _live_snapshots(
        [e["item_id"] for e in edits if e.get("item_type", "video") == "video"],
        [e["item_id"] for e in edits if e.get("item_type") == "playlist"])
    items, diffs = [], []
    for e in edits:
        item_type = e.get("item_type", "video")
        item_id = e.get("item_id", "")
        field = e.get("field", "")
        new = e.get("new", "")
        if field not in ("title", "description"):
            raise RuntimeError("field must be title or description")
        snap = snaps.get((item_type, item_id))
        if snap is None:
            raise RuntimeError(item_type + " not found live: " + str(item_id))
        old = snap[field]
        if field == "title" and item_type == "video":
            parsed = yt_config.parse_title(old, CFG)
            new_parsed = yt_config.parse_title(new, CFG)
            if parsed["is_bootleg"] and parsed["trailer"] and not new_parsed["trailer"]:
                new = new.rstrip() + " " + parsed["trailer"]
        if old == new:
            continue
        items.append({"item_type": item_type, "item_id": item_id,
                      "field": field, "old": old, "new": new})
        diffs.append({"item": item_type + ":" + item_id + "/" + field,
                      "old": old, "new": new})
    if not items:
        return {"change_set_id": None,
                "note": "nothing to change - all live values already match"}
    cs_id = _save_changeset({"kind": "edits", "items": items})
    return {"change_set_id": cs_id, "diffs": diffs, "item_count": len(items),
            "note": "review the diffs, then apply_change_set to write"}


def tool_propose_playlist(title, video_ids, description=""):
    if not video_ids:
        raise RuntimeError("no video_ids given")
    vids = {r.get("video_id"): r for r in _videos()}
    missing = [v for v in video_ids if v not in vids]
    if missing:
        raise RuntimeError("not in the channel cache: " + ", ".join(missing))
    dupes = [r.get("title") for r in _playlists()
             if yt_config.norm_name(r.get("title", "")) == yt_config.norm_name(title)]
    preview = [{"position": i, "video_id": v, "title": vids[v].get("title", "")}
               for i, v in enumerate(video_ids)]
    cs_id = _save_changeset({"kind": "playlist", "title": title,
                             "description": description, "video_ids": list(video_ids)})
    return {"change_set_id": cs_id, "title": title, "description": description,
            "items": preview,
            "duplicate_title_warning": dupes[0] if dupes else None,
            "note": "review the plan, then apply_change_set to create"}


# ── apply tier ─────────────────────────────────────────────────────────────

def _apply_edits(payload, path, cap):
    yt = _oauth_client()
    done_keys = {tuple(d) for d in payload.get("applied_items", [])}
    results, written = [], 0
    for item in payload["items"]:
        key = (item["item_type"], item["item_id"], item["field"])
        if list(key) in payload.get("applied_items", []) or key in done_keys:
            results.append({"item": key, "status": "already-applied"})
            continue
        if written >= cap:
            results.append({"item": key, "status": "over-cap (re-run to continue)"})
            continue
        try:
            if item["item_type"] == "video":
                resp = yt.videos().list(part="snippet", id=item["item_id"]).execute()
                objs = resp.get("items", [])
                if not objs:
                    results.append({"item": key, "status": "missing on channel"})
                    continue
                snippet = objs[0]["snippet"]
                if snippet.get(item["field"], "") != item["old"]:
                    results.append({"item": key, "status": "drifted - live value "
                                    "changed since proposal; re-propose"})
                    continue
                snippet[item["field"]] = item["new"]
                yt.videos().update(part="snippet", body={
                    "id": item["item_id"], "snippet": snippet}).execute()
            else:
                resp = yt.playlists().list(part="snippet", id=item["item_id"]).execute()
                objs = resp.get("items", [])
                if not objs:
                    results.append({"item": key, "status": "missing on channel"})
                    continue
                snippet = objs[0]["snippet"]
                if snippet.get(item["field"], "") != item["old"]:
                    results.append({"item": key, "status": "drifted - live value "
                                    "changed since proposal; re-propose"})
                    continue
                snippet[item["field"]] = item["new"]
                yt.playlists().update(part="snippet", body={
                    "id": item["item_id"], "snippet": snippet}).execute()
            written += 1
            payload.setdefault("applied_items", []).append(list(key))
            _update_changeset(path, payload)
            results.append({"item": key, "status": "written"})
        except Exception as err:
            results.append({"item": key, "status": "error: " + str(err)[:200]})
    return {"results": [{"item": list(r["item"]) if isinstance(r["item"], tuple)
                         else r["item"], "status": r["status"]} for r in results],
            "written": written, "cap": cap,
            "note": "cache rows are now stale for written items - re-run the "
                    "fetch script with --force over their publish window"}


def _apply_playlist(payload, path, cap):
    yt = _oauth_client()
    if payload.get("created_playlist_id"):
        pl_id = payload["created_playlist_id"]
    else:
        resp = yt.playlists().insert(part="snippet,status", body={
            "snippet": {"title": payload["title"],
                        "description": payload.get("description", "")},
            "status": {"privacyStatus": "public"},
        }).execute()
        pl_id = resp["id"]
        payload["created_playlist_id"] = pl_id
        _update_changeset(path, payload)
    already = set(payload.get("applied_items", []))
    added = 0
    results = []
    for pos, vid in enumerate(payload["video_ids"]):
        if vid in already:
            results.append({"video_id": vid, "status": "already-added"})
            continue
        if added >= cap:
            results.append({"video_id": vid, "status": "over-cap (re-run to continue)"})
            continue
        try:
            yt.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": pl_id, "position": pos,
                "resourceId": {"kind": "youtube#video", "videoId": vid},
            }}).execute()
            added += 1
            payload.setdefault("applied_items", []).append(vid)
            _update_changeset(path, payload)
            results.append({"video_id": vid, "status": "added"})
            time.sleep(0.3)
        except Exception as err:
            results.append({"video_id": vid, "status": "error: " + str(err)[:200]})
    return {"playlist_id": pl_id,
            "playlist_url": "https://www.youtube.com/playlist?list=" + pl_id,
            "results": results, "added": added, "cap": cap}


def tool_apply_change_set(change_set_id, cap=None):
    cap = int(cap) if cap else APPLY_CAP_DEFAULT
    if cap < 1:
        raise RuntimeError("cap must be at least 1")
    payload, path = _load_changeset(change_set_id)
    if payload["kind"] == "edits":
        return _apply_edits(payload, path, cap)
    if payload["kind"] == "playlist":
        return _apply_playlist(payload, path, cap)
    raise RuntimeError("unknown change-set kind")


# ── MCP protocol plumbing ──────────────────────────────────────────────────

def _schema(props, required):
    return {"type": "object", "properties": props, "required": required}

_S = {"type": "string"}
_B = {"type": "boolean"}
_I = {"type": "integer"}
_SL = {"type": "array", "items": {"type": "string"}}

TOOLS = [
    ("catalog_search", "Search the channel's cached video catalog by artist "
     "(alias-aware), song, free text, cover flag, or date range. TSV-only, "
     "zero API quota.",
     _schema({"artist": _S, "song": _S, "text": _S, "cover_only": _B,
              "date_from": _S, "date_to": _S, "limit": _I}, []),
     tool_catalog_search),
    ("video_stats", "View/like/comment counts for specific videos (the one "
     "read the cache cannot answer). Batched 50 per API call.",
     _schema({"video_ids": _SL}, ["video_ids"]), tool_video_stats),
    ("audit_venues", "Sweep every cached title and description for venue-name "
     "forms that diverge from the canonical spellings in venues.tsv, using "
     "the shared venue alias map. Read-only.",
     _schema({"venue": _S}, []), tool_audit_venues),
    ("audit_text", "Regex sweep across cached video/playlist titles and "
     "descriptions - name drift, stale links, convention changes. Read-only.",
     _schema({"pattern": _S, "scope": _S, "limit": _I}, ["pattern"]),
     tool_audit_text),
    ("comments_pending", "Pull top comments for crowdsource-titled videos "
     "(filter unknown_song) or recent uploads - closes the loop the "
     "unknown-song titles open.",
     _schema({"filter": _S, "max_videos": _I, "since": _S}, []),
     tool_comments_pending),
    ("propose_edits", "Dry-run: build a reviewable change-set of title or "
     "description edits (old snapshotted from the LIVE channel; video-title "
     "proposals carry operator trailing text forward). Writes nothing.",
     _schema({"edits": {"type": "array", "items": _schema({
         "item_type": _S, "item_id": _S, "field": _S, "new": _S},
         ["item_id", "field", "new"])}}, ["edits"]),
     tool_propose_edits),
    ("propose_playlist", "Dry-run: plan a new playlist (title, ordered video "
     "ids, description); validates ids against the cache and warns on "
     "duplicate titles. Writes nothing.",
     _schema({"title": _S, "video_ids": _SL, "description": _S},
             ["title", "video_ids"]), tool_propose_playlist),
    ("apply_change_set", "The only write path: replay a previously proposed "
     "change-set under a per-call cap, skipping items whose live values "
     "drifted since proposal. Resumable; no delete capability exists.",
     _schema({"change_set_id": _S, "cap": _I}, ["change_set_id"]),
     tool_apply_change_set),
]


def _tools_payload():
    return {"tools": [{"name": n, "description": d, "inputSchema": s}
                      for n, d, s, _ in TOOLS]}


def _dispatch_tool(name, arguments):
    for n, _, _, func in TOOLS:
        if n == name:
            return func(**(arguments or {}))
    raise RuntimeError("unknown tool: " + str(name))


def _handle(msg):
    method = msg.get("method", "")
    msg_id = msg.get("id")
    if method == "initialize":
        proto = (msg.get("params") or {}).get("protocolVersion", "2024-11-05")
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": proto,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "yt-mcp", "version": "0.1.2"}}}
    if method.startswith("notifications/"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": _tools_payload()}
    if method == "tools/call":
        params = msg.get("params") or {}
        try:
            result = _dispatch_tool(params.get("name"), params.get("arguments"))
            content = [{"type": "text", "text": json.dumps(result, indent=2)}]
            return {"jsonrpc": "2.0", "id": msg_id,
                    "result": {"content": content, "isError": False}}
        except Exception as err:
            content = [{"type": "text", "text": "ERROR: " + str(err)}]
            return {"jsonrpc": "2.0", "id": msg_id,
                    "result": {"content": content, "isError": True}}
    if msg_id is not None:
        return {"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": "method not found: " + method}}
    return None


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        resp = _handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
