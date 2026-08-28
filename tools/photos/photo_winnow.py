#!/usr/bin/env python3
"""
photo_winnow.py — A local browser surface for the crosswalk winnowing pass

Machine enrichment gets a crosswalk row as far as "these assets agree with
two signals". Turning that into a confirmed match needs eyes on both
images, and doing that across a hundred-odd rows by hand is the slow part
of the backfill. This serves the crosswalk as a page on localhost where
each row shows the Google Photos image beside its Immich candidates, so a
decision is a glance and a click.

Driven by backfill.py winnow.

WHAT IT IS, AND IS NOT

  A view over the crosswalk. Saving rewrites ONLY the crosswalk's decision
  columns - match_id, confidence, notes, and the candidate list when you
  reject one. Library TSVs are untouched; those change only through
  `rewrite`, and only from confidence-3 rows. Nothing here mints a shared
  link either: confirming records WHICH asset, and `mint` turns confirmed
  rows into share links afterwards. So a mis-click is one cell to undo
  rather than an orphaned link on the server.

WHERE THE TWO IMAGES COME FROM

  Immich thumbnails proxy through this server, which holds the API key
  and streams the bytes back, so the key never reaches the page. They are
  cached under .thumb_cache/ (gitignored) - the corpus is stable, and
  re-fetching on every pass would be waste. Google thumbnails come from
  gp_scrape.tsv and are loaded directly by the browser: those URLs need no
  credential and their responses carry a permissive cross-origin resource
  policy. A row with no harvested thumb degrades to its caption plus a
  click-through to the share link, exactly as the pass worked before.

  Run gp_thumbs.py first for the side-by-side. Without it the page still
  works, just with more tab switching.

ORDERING

  Not file order. Rows are queued by how cheap the decision is: strong
  single-candidate rows first (a yes/no glance), then strong multi, then
  weak, then unmatched. Within a bucket, by show date, so consecutive
  cards share visual context.

THE SMALL PRINT ON SECURITY

  Binds 127.0.0.1 only. Every request carries a per-run token embedded in
  the URL the tool opens, and writes reject cross-origin requests - a
  random web page must not be able to POST at a localhost port and edit
  the crosswalk. The Immich key is read from the same environment
  immich.py uses and is never serialized into the page.
"""

import html
import json
import os
import re
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

import immich  # noqa: E402

DEFAULT_PORT = 8766          # yt_edit owns 8765; both may be open at once
THUMB_CACHE = os.path.join(_SCRIPT_DIR, ".thumb_cache")

# The only crosswalk columns a save may touch. source_row and google_link
# are the join keys and are never edited here.
EDITABLE_FIELDS = ("match_id", "immich_candidates", "confidence", "notes")

_UUID_RE = re.compile(r"^[0-9a-fA-F-]{32,40}$")


# ── state assembly ─────────────────────────────────────────────────────────

def _scrape_index():
    """link_key -> (caption, gp_thumb) from the harvested scrape file."""
    out = {}
    for row in immich._read_tsv_rows("tools/photos/gp_scrape.tsv"):
        key = (row.get("link_key") or "").strip()
        if key:
            out[key] = ((row.get("caption") or "").strip(),
                        (row.get("gp_thumb") or "").strip())
    return out


def _scrape_for(link, index):
    for key, value in index.items():
        if key in link:
            return value
    return ("", "")


def _row_dates(row):
    return sorted(set(re.findall(r"\d{4}-\d{2}-\d{2}",
                                 row.get("source_row", "") + " " +
                                 row.get("signals", ""))))


def _queue_rank(row):
    """Cheapest decision first: strong-single, strong-multi, weak, unmatched.
    Confirmed rows sink to the bottom and render read-only."""
    conf = (row.get("confidence") or "0").strip()
    n = len([c for c in (row.get("immich_candidates") or "").split(";") if c])
    if conf == "3":
        return 9
    if conf == "2":
        return 0 if n == 1 else 1
    if conf == "1":
        return 2 if n else 3
    return 4 if n else 5


def build_state(rows):
    """Everything the page needs, JSON-serializable. Index is the row's
    position in the file, which is what a save addresses - the queue only
    reorders the cards."""
    index = _scrape_index()
    claimed = {}
    for n, row in enumerate(rows):
        mid = (row.get("match_id") or "").strip()
        if mid:
            claimed.setdefault(mid, []).append(n)

    cards = []
    for n, row in enumerate(rows):
        caption, thumb = _scrape_for(row.get("google_link", ""), index)
        cards.append({
            "i": n,
            "source": row.get("source_row", ""),
            "link": row.get("google_link", ""),
            "desc": row.get("google_desc", ""),
            "caption": caption,
            "gpThumb": thumb,
            "candidates": [c for c in
                           (row.get("immich_candidates") or "").split(";") if c],
            "matchId": (row.get("match_id") or "").strip(),
            "conf": (row.get("confidence") or "0").strip(),
            "signals": [s for s in (row.get("signals") or "").split("|") if s],
            "notes": row.get("notes", ""),
            "dates": _row_dates(row),
            "rank": _queue_rank(row),
        })
    cards.sort(key=lambda c: (c["rank"], c["dates"], c["i"]))

    counts = {}
    for c in cards:
        counts[c["conf"]] = counts.get(c["conf"], 0) + 1
    return {"cards": cards, "counts": counts, "total": len(cards),
            "claimed": {k: v for k, v in claimed.items() if len(v) > 1}}


def apply_edit(rows, edit):
    """Write one decision into one row. Returns (ok, message)."""
    try:
        i = int(edit.get("i", -1))
    except (TypeError, ValueError):
        return False, "bad row index"
    if not 0 <= i < len(rows):
        return False, f"row {i} out of range"
    row = rows[i]

    action = edit.get("action")
    if action == "confirm":
        asset_id = (edit.get("matchId") or "").strip()
        if not _UUID_RE.match(asset_id):
            return False, "confirm needs an asset id"
        row["match_id"] = asset_id
        row["immich_candidates"] = asset_id
        row["confidence"] = "3"
    elif action == "reject":
        # Back to unmatched WITH the candidates cleared, which is what lets
        # a later enrich re-propose: its discovery only runs on a row that
        # has none. Leaving a rejected candidate in place would freeze the
        # row forever.
        row["match_id"] = ""
        row["immich_candidates"] = ""
        row["confidence"] = "0"
    elif action == "absent":
        row["match_id"] = ""
        row["immich_candidates"] = ""
        row["confidence"] = "0"
        row["notes"] = _note(row, "no immich equivalent")
    elif action == "note":
        pass
    else:
        return False, f"unknown action {action!r}"

    if "notes" in edit and action != "absent":
        row["notes"] = (edit.get("notes") or "").strip()
    return True, "ok"


def _note(row, text):
    existing = (row.get("notes") or "").strip()
    if text in existing:
        return existing
    return f"{existing}; {text}".strip("; ")


def write_crosswalk(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(immich.CROSSWALK_HEADER) + "\n")
        for row in rows:
            f.write("\t".join(row.get(c, "")
                              for c in immich.CROSSWALK_HEADER) + "\n")


# ── thumbnails ─────────────────────────────────────────────────────────────

def _cached_thumb(asset_id, size="thumbnail"):
    """Immich thumbnail bytes, memoized on disk. The key stays server-side;
    the page only ever sees this server's own /thumb URL."""
    os.makedirs(THUMB_CACHE, exist_ok=True)
    path = os.path.join(THUMB_CACHE, f"{asset_id}.{size}.jpg")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "rb") as f:
            return f.read()
    data = immich.thumbnail(asset_id, size=size)
    if isinstance(data, str):
        data = data.encode("latin-1", "ignore")
    if data:
        with open(path, "wb") as f:
            f.write(data)
    return data or b""


def _widen_by_date(dates):
    """Assets captured on the row's date(s). The enricher discards
    alternates when the face signal narrows a candidate list, so this is
    how a card gets them back without a full re-run.

    Only works where the asset kept its capture date. The batch import
    stripped EXIF from much of the library, leaving those assets stamped
    with the upload time instead, so for a large share of rows this
    correctly returns nothing and the artist lookup below is the way in."""
    out = []
    for date in dates[:2]:
        for hit in immich.search_metadata(
                taken_after=f"{date}T00:00:00.000Z",
                taken_before=f"{date}T23:59:59.999Z"):
            if hit["id"] not in out:
                out.append(hit["id"])
    return out[:24]


_ARTIST_INDEX = {}


def _person_index():
    """Name key -> Immich person id(s), built once per run.

    Keyed two ways on purpose. Canonical artist names come through
    backfill's resolver, so a person spelled differently from the
    artists.tsv row still matches, exactly as enrich does. But only a
    minority of named people ARE artists - most are sidemen with no
    artists.tsv row, and they are precisely who the descriptive captions
    name ("Ori Naftaly of Southern Avenue"). So the person's own name is
    indexed too, or those rows have no way in."""
    if _ARTIST_INDEX:
        return _ARTIST_INDEX
    import backfill
    canon = backfill._canonical_artists()
    aliases = backfill._alias_map()
    for person in immich.people(named_only=True):
        name = (person.get("name") or "").strip()
        if not name or backfill.PLACEHOLDER_RE.match(name):
            continue
        _ARTIST_INDEX.setdefault(backfill.goal_norm(name), []).append(
            person["id"])
        resolved, _ = backfill._resolve_artist(name, canon, aliases)
        if resolved:
            key = backfill.goal_norm(resolved)
            ids = _ARTIST_INDEX.setdefault(key, [])
            if person["id"] not in ids:
                ids.append(person["id"])
    return _ARTIST_INDEX


def _widen_by_artist(row):
    """Assets showing anyone the row names, with no date filter at all.

    This is the answer for the imported half of the library: the capture
    date is gone but the face is not, and a person typically has only a
    handful of assets, which is a small enough set to judge by eye.
    Returns (ids, tried) so a row whose names have no person can say so
    rather than looking like an empty result."""
    import backfill
    canon = backfill._canonical_artists()
    aliases = backfill._alias_map()
    index = _person_index()

    out, tried = [], []
    for name in backfill._row_artists(row, backfill._item_log_index()):
        pids = index.get(backfill.goal_norm(name), [])
        if not pids:
            resolved, _ = backfill._resolve_artist(name, canon, aliases)
            if resolved:
                pids = index.get(backfill.goal_norm(resolved), [])
        if not pids:
            tried.append(f"{name} (no Immich person)")
            continue
        tried.append(name)
        for pid in pids:
            for hit in immich.search_metadata(person_id=pid):
                if hit["id"] not in out:
                    out.append(hit["id"])
    return out[:24], tried


# ── page ───────────────────────────────────────────────────────────────────

_PAGE = """<!doctype html>
<meta charset="utf-8"><title>crosswalk winnowing</title>
<style>
 :root { color-scheme: light dark; }
 body { font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        margin: 0; padding: 16px 20px 120px; }
 h1 { font-size: 16px; margin: 0 0 4px; }
 .counts { color: #666; margin-bottom: 18px; }
 .counts b { color: inherit; }
 .card { border: 1px solid #8883; border-radius: 8px; padding: 12px;
         margin-bottom: 14px; display: grid;
         grid-template-columns: 260px 1fr; gap: 14px; }
 .card[data-done="1"] { opacity: .5; }
 .gp img { width: 250px; border-radius: 6px; display: block; }
 .gp .noimg { width: 250px; height: 160px; border: 1px dashed #8886;
              border-radius: 6px; display: grid; place-items: center;
              color: #888; font-size: 12px; text-align: center; padding: 8px; }
 .src { font-size: 12px; color: #888; word-break: break-all; }
 .cap { margin: 6px 0; }
 .sig { font-size: 12px; color: #888; }
 .cands { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
 .cand { border: 2px solid transparent; border-radius: 6px; padding: 2px;
         cursor: pointer; position: relative; }
 .cand img { width: 132px; height: 132px; object-fit: cover;
             border-radius: 4px; display: block; background: #8882; }
 .cand.sel { border-color: #2b7; }
 .brokenthumb { width: 132px; height: 132px; border: 1px dashed #c66;
                border-radius: 4px; display: grid; place-items: center;
                color: #c66; font-size: 11px; text-align: center; padding: 6px; }
 .cand .dupe { position: absolute; left: 2px; right: 2px; bottom: 2px;
               background: #c60d; color: #fff; font-size: 10px;
               text-align: center; border-radius: 0 0 4px 4px; }
 button { font: inherit; padding: 5px 11px; border-radius: 6px;
          border: 1px solid #8886; background: #8881; cursor: pointer; }
 button.go { border-color: #2b7; }
 button:disabled { opacity: .4; cursor: default; }
 .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
 .msg { margin-left: 8px; color: #2b7; font-size: 12px; }
 .bar { position: fixed; left: 0; right: 0; bottom: 0; padding: 10px 20px;
        background: Canvas; border-top: 1px solid #8883; }
</style>
<h1>Crosswalk winnowing</h1>
<div class="counts" id="counts"></div>
<div id="cards"></div>
<div class="bar"><button onclick="quit()">Done</button>
  <span class="msg" id="bar"></span></div>
<script>
const S = STATE_JSON, T = "TOKEN";
const el = document.getElementById('cards');

function counts() {
  const c = {}; S.cards.forEach(x => c[x.conf] = (c[x.conf]||0)+1);
  document.getElementById('counts').innerHTML =
    S.total + ' rows &middot; ' + [0,1,2,3].map(n =>
      'conf ' + n + ': <b>' + (c[n]||0) + '</b>').join(' &middot; ');
}

function card(c) {
  const gp = c.gpThumb
    ? '<img loading="lazy" referrerpolicy="no-referrer" src="' + c.gpThumb +
      '=w250" onerror="this.outerHTML=\\'<div class=noimg>thumb unavailable<br>' +
      'open the share link</div>\\'">'
    : '<div class="noimg">no harvested thumb<br>open the share link</div>';
  const cands = c.candidates.map(id =>
    '<div class="cand' + (id === c.matchId ? ' sel' : '') + '" data-id="' + id +
    '" onclick="pick(' + c.i + ',\\'' + id + '\\')">' +
    '<img loading="lazy" src="/thumb/' + id + '?t=' + T + '" onerror="thumbFail(this)">' +
    (S.claimed[id] ? '<div class="dupe">also on another row</div>' : '') +
    '</div>').join('');
  return '<div class="card" id="c' + c.i + '" data-done="' +
    (c.conf === '3' ? 1 : 0) + '">' +
    '<div class="gp"><a href="' + c.link + '" target="_blank" rel="noreferrer">' +
      gp + '</a></div>' +
    '<div><div class="src">' + esc(c.source) + '</div>' +
    '<div class="cap">' + esc(c.caption || c.desc || '(no caption)') + '</div>' +
    '<div class="sig">conf ' + c.conf + ' &middot; ' +
      (c.signals.join(' &middot; ') || 'no signals') + '</div>' +
    '<div class="cands">' + (cands || '<i>no candidates</i>') + '</div>' +
    '<div class="row">' +
      '<button class="go" onclick="act(' + c.i + ',\\'confirm\\')">Confirm</button>' +
      '<button onclick="act(' + c.i + ',\\'reject\\')">Reject all</button>' +
      '<button onclick="act(' + c.i + ',\\'absent\\')">Not in Immich</button>' +
      '<button onclick="widen(' + c.i + ',\\'date\\')">Widen by date</button>' +
      '<button onclick="widen(' + c.i + ',\\'artist\\')">Widen by artist</button>' +
      '<span class="msg" id="m' + c.i + '"></span>' +
    '</div></div></div>';
}

function esc(s) { const d = document.createElement('div');
  d.textContent = s || ''; return d.innerHTML; }
function byIndex(i) { return S.cards.find(c => c.i === i); }

// A failed /thumb fetch otherwise renders as a browser broken-image icon,
// which reads exactly like "this is the wrong photo" when it actually means
// the asset could not be fetched. Say which it is.
function thumbFail(img) {
  const d = document.createElement('div');
  d.className = 'brokenthumb';
  d.textContent = 'thumbnail failed';
  img.replaceWith(d);
}

// With one candidate the click carries no information - there is nothing
// else to choose - so preselect it and let the row be a straight confirm or
// reject. Multi-candidate rows still require an explicit pick, which is
// where the ambiguity actually lives. This only sets the page's selection;
// nothing reaches the crosswalk until Confirm is pressed.
function preselect() {
  S.cards.forEach(c => {
    if (!c.matchId && c.conf !== '3' && c.candidates.length === 1) {
      c.matchId = c.candidates[0];
    }
  });
}

function render() { preselect(); counts(); el.innerHTML = S.cards.map(card).join(''); }

function pick(i, id) {
  const c = byIndex(i); c.matchId = (c.matchId === id ? '' : id);
  document.querySelectorAll('#c' + i + ' .cand').forEach(n =>
    n.classList.toggle('sel', n.dataset.id === c.matchId));
}

async function post(path, body) {
  const r = await fetch(path + '?t=' + T, { method: 'POST',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
  return r.json();
}

async function act(i, action) {
  const c = byIndex(i);
  if (action === 'confirm' && !c.matchId) {
    document.getElementById('m' + i).textContent = 'pick a candidate first';
    return;
  }
  const res = await post('/save', { i: i, action: action, matchId: c.matchId });
  if (!res.ok) { document.getElementById('m' + i).textContent = res.msg; return; }
  c.conf = res.conf; c.matchId = res.matchId; c.candidates = res.candidates;
  document.getElementById('c' + i).dataset.done = (c.conf === '3' ? 1 : 0);
  document.getElementById('m' + i).textContent = 'saved';
  counts();
}

async function widen(i, mode) {
  const m = document.getElementById('m' + i);
  m.textContent = 'searching...';
  const res = await post('/widen', { i: i, mode: mode });
  if (!res.ok) { m.textContent = res.msg; return; }
  const c = byIndex(i);
  c.candidates = res.candidates;
  c.matchId = (res.candidates.length === 1 ? res.candidates[0] : '');
  document.getElementById('c' + i).outerHTML = card(c);
  document.getElementById('m' + i).textContent =
    res.candidates.length + ' candidate(s) via ' + mode +
    (res.note ? ' - ' + res.note : '');
}

async function quit() {
  await post('/quit', {});
  document.getElementById('bar').textContent = 'closed - you can shut this tab';
}
render();
</script>
"""


def render_page(state, token):
    return (_PAGE
            .replace("STATE_JSON", json.dumps(state))
            .replace("TOKEN", html.escape(token)))


# ── server ─────────────────────────────────────────────────────────────────

def serve(crosswalk_path, port=DEFAULT_PORT, open_browser=True):
    """Serve the winnowing page until Done or Ctrl-C. Blocks."""
    token = secrets.token_urlsafe(16)
    lock = threading.Lock()
    rel = os.path.relpath(crosswalk_path, immich._ROOT)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _authorized(self):
            if parse_qs(urlparse(self.path).query).get("t", [""])[0] != token:
                return False
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).hostname not in ("127.0.0.1",
                                                            "localhost"):
                return False
            return True

        def _send(self, code, ctype, body):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj):
            self._send(200, "application/json",
                       json.dumps(obj).encode("utf-8"))

        def do_GET(self):
            parsed = urlparse(self.path)
            if not self._authorized():
                return self._send(403, "text/plain", b"forbidden")
            if parsed.path == "/":
                with lock:
                    rows = immich._read_tsv_rows(rel)
                    page = render_page(build_state(rows), token)
                return self._send(200, "text/html; charset=utf-8",
                                  page.encode("utf-8"))
            m = re.match(r"^/thumb/([0-9a-fA-F-]{32,40})$", parsed.path)
            if m:
                try:
                    return self._send(200, "image/jpeg",
                                      _cached_thumb(m.group(1)))
                except Exception:
                    return self._send(404, "text/plain", b"no thumbnail")
            return self._send(404, "text/plain", b"not found")

        def do_POST(self):
            path = urlparse(self.path).path
            if not self._authorized():
                return self._send(403, "text/plain", b"forbidden")
            if path == "/quit":
                self._json({"ok": True})
                threading.Thread(target=server.shutdown, daemon=True).start()
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._send(400, "text/plain", b"bad json")

            if path == "/save":
                with lock:
                    rows = immich._read_tsv_rows(rel)
                    ok, msg = apply_edit(rows, payload)
                    if ok:
                        write_crosswalk(crosswalk_path, rows)
                        row = rows[int(payload["i"])]
                        return self._json({
                            "ok": True, "conf": row.get("confidence", "0"),
                            "matchId": row.get("match_id", ""),
                            "candidates": [c for c in row.get(
                                "immich_candidates", "").split(";") if c]})
                    return self._json({"ok": False, "msg": msg})

            if path == "/widen":
                with lock:
                    rows = immich._read_tsv_rows(rel)
                    i = int(payload.get("i", -1))
                    if not 0 <= i < len(rows):
                        return self._json({"ok": False, "msg": "bad row"})
                    mode = payload.get("mode", "date")
                    if mode == "artist":
                        found, tried = _widen_by_artist(rows[i])
                        note = ", ".join(tried) or "no artist on this row"
                    else:
                        dates = _row_dates(rows[i])
                        if not dates:
                            return self._json({"ok": False,
                                               "msg": "row has no date"})
                        found, note = _widen_by_date(dates), ", ".join(dates)
                    if not found:
                        return self._json({"ok": False,
                                           "msg": f"nothing found ({note})"})
                    rows[i]["immich_candidates"] = ";".join(found)
                    write_crosswalk(crosswalk_path, rows)
                    return self._json({"ok": True, "candidates": found,
                                       "note": note})

            return self._send(404, "text/plain", b"no such endpoint")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/?t={token}"
    print(f"winnowing at {url}\n(Done in the page, or Ctrl-C here)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print("closed.")
