#!/usr/bin/env python3
"""
yt_edit.py — A local browser surface for the manifest correction pass

The correction pass happens with Studio open in the next tab: listen to a
clip there, name it here. This serves the lean manifest as a page on
localhost where each keeper clip gets a dropdown of its Set Artist's setlist
songs — and a song picked on one clip disappears from every other clip's
options, live. Duplicate titles become impossible by construction, which is
the same mistake class the CI linter exists to catch, eliminated at the
source instead.

Driven by youtube_upload_show.py --edit.

WHAT IT IS, AND IS NOT

  A view over the lean file. Saving rewrites ONLY the lean TSV's human
  columns — the machine sidecar is untouched, the TSV stays the source of
  truth, and nothing here talks to YouTube. Titles still go out through
  --apply, behind its publish guard. Close the tab, hit Done, or Ctrl-C;
  no state lives anywhere but the manifest.

WHERE THE SETLISTS COME FROM

  The same cache --identify writes next to the manifest. Run --identify
  first (even a --dry-run) and the dropdowns are populated offline; without
  a cached setlist an artist's rows degrade to free-text entry, exactly like
  the rest of the pipeline degrades.

THE SMALL PRINT ON SECURITY

  Binds 127.0.0.1 only. Every request must carry a per-run token (embedded
  in the URL the tool opens), and writes reject any cross-origin request —
  a random web page must not be able to POST at a localhost port and edit
  a manifest. No YouTube credential is loaded at any point.
"""

import html
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import yt_manifest


DEFAULT_PORT = 8765

# The only columns a save may touch. Clip is the join key, never edited.
EDITABLE_FIELDS = ("Decision", "Set Artist", "Song", "Cover", "Skip Reason")


# ── state assembly ─────────────────────────────────────────────────────

def build_state(rows: list[dict], setlists: dict, show: dict) -> dict:
    """Everything the page needs, JSON-serializable.

    Skip rows ride along (visible, toggleable back to got) but carry no
    dropdown. Artists offered for Set Artist are the union of the bill and
    whatever the manifest already says, so a hand-corrected co-bill is not
    fought over.
    """
    artists = []
    for name in ([show.get("artist", "")]
                 + [p.strip() for p in
                    (show.get("support", "") or "").replace("&", "/").split("/")]
                 + [(r.get("Set Artist") or "").strip() for r in rows]):
        name = name.strip()
        if name and name not in artists:
            artists.append(name)

    state_rows = []
    for row in sorted(rows, key=lambda r: _int(r.get("Capture Order"))):
        state_rows.append({
            "clip":       row.get("Clip", ""),
            "order":      row.get("Capture Order", ""),
            "duration":   row.get("Duration", ""),
            "capture":    row.get("Capture Start", ""),
            "decision":   (row.get("Decision") or "").strip() or "got",
            "setArtist":  (row.get("Set Artist") or "").strip(),
            "song":       (row.get("Song") or "").strip(),
            "cover":      (row.get("Cover") or "").strip(),
            "skipReason": (row.get("Skip Reason") or "").strip(),
            "candidates": (row.get("Candidates") or "").strip(),
            "lyricHint":  (row.get("Lyric Hint") or "").strip(),
            "videoId":    (row.get("Video ID") or "").strip(),
        })

    state_setlists = {}
    for artist, setlist in (setlists or {}).items():
        state_setlists[artist] = {
            "incomplete": bool(getattr(setlist, "incomplete", False)),
            "songs": [{
                "title":    s.title,
                "position": s.position,
                "cover":    s.cover_of,
                "section":  s.section,
                "unknown":  s.unknown,
            } for s in getattr(setlist, "songs", [])],
        }

    return {
        "show": {"artist": show.get("artist", ""),
                 "date": show.get("date", ""),
                 "venue": show.get("venue", "")},
        "artists": artists,
        "rows": state_rows,
        "setlists": state_setlists,
    }


def apply_edits(rows: list[dict], edits: list) -> tuple[int, list[str]]:
    """Fold posted row edits into the merged rows, human columns only.

    Returns (changed_row_count, errors). An edit naming a clip the manifest
    does not know is an error, not a new row — the editor is a correction
    surface, never a creator.
    """
    by_clip = {(r.get("Clip") or "").strip(): r for r in rows}
    changed = 0
    errors = []

    for edit in edits or []:
        if not isinstance(edit, dict):
            errors.append("malformed edit entry (not an object)")
            continue
        clip = (edit.get("clip") or "").strip()
        row = by_clip.get(clip)
        if row is None:
            errors.append(f"unknown clip: {clip!r}")
            continue

        mapping = {"Decision": "decision", "Set Artist": "setArtist",
                   "Song": "song", "Cover": "cover",
                   "Skip Reason": "skipReason"}
        touched = False
        for field, key in mapping.items():
            if key not in edit:
                continue
            value = str(edit[key] or "").strip()
            if field == "Decision" and value not in ("got", "skip"):
                errors.append(f"{clip}: Decision {value!r} is not got/skip")
                continue
            if value != (row.get(field) or "").strip():
                row[field] = value
                touched = True
        if touched:
            changed += 1

    return changed, errors


def _int(value) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


# ── page ────────────────────────────────────────────────────────────────────

def render_page(state: dict, token: str) -> str:
    """The whole editor: one page, inline CSS and JS, no external assets."""
    show = state["show"]
    title = html.escape(f"{show['artist']} — {show['date']} — manifest")
    payload = json.dumps({"state": state, "token": token},
                         ensure_ascii=False).replace("</", "<\\/")
    return PAGE_TEMPLATE.replace("__TITLE__", title) \
                        .replace("__PAYLOAD__", payload)


PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>__TITLE__</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 14px/1.45 -apple-system, system-ui, sans-serif; margin: 0;
         background: Canvas; color: CanvasText; }
  header { position: sticky; top: 0; background: Canvas; z-index: 2;
           padding: 10px 16px; border-bottom: 1px solid color-mix(in srgb, CanvasText 20%, transparent);
           display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 16px; margin: 0; flex: 1; }
  #status { font-size: 12px; opacity: .75; }
  button { font: inherit; padding: 5px 14px; border-radius: 6px;
           border: 1px solid color-mix(in srgb, CanvasText 30%, transparent);
           background: transparent; color: inherit; cursor: pointer; }
  button.primary { background: #2563eb; border-color: #2563eb; color: #fff; }
  button[disabled] { opacity: .4; cursor: default; }
  .artist-block { margin: 14px 16px; }
  .artist-block h2 { font-size: 14px; margin: 4px 0 2px; }
  .artist-note { font-size: 12px; opacity: .7; margin: 0 0 6px; }
  .row { display: flex; gap: 10px; align-items: center; padding: 7px 8px;
         border: 1px solid color-mix(in srgb, CanvasText 14%, transparent);
         border-radius: 8px; margin-bottom: 6px; }
  .row.skip { opacity: .5; }
  .thumb { width: 84px; height: 47px; object-fit: cover; border-radius: 4px;
           background: color-mix(in srgb, CanvasText 12%, transparent); flex: none; }
  .meta { flex: none; width: 118px; font-size: 12px; }
  .meta .dur { font-weight: 700; font-size: 14px; }
  .meta a { font-size: 11px; }
  .pick { flex: 1; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  select, input[type=text] { font: inherit; padding: 4px 6px; border-radius: 6px;
           border: 1px solid color-mix(in srgb, CanvasText 30%, transparent);
           background: Field; color: FieldText; }
  select.song { min-width: 240px; }
  input.cover { width: 130px; }
  .hint { font-size: 11px; opacity: .65; width: 100%; }
  .dirty { outline: 2px solid #2563eb55; }
</style></head><body>
<header>
  <h1>__TITLE__</h1>
  <span id="status"></span>
  <button id="save" class="primary" disabled>Save</button>
  <button id="done">Done</button>
</header>
<main id="main"></main>
<script>
const BOOT = __PAYLOAD__;
const S = BOOT.state, TOKEN = BOOT.token;
const rows = S.rows;
let dirty = false;

const UNKNOWN = "unknown";
const FREE = "…type a title";

function takenTitles(artist, exceptClip) {
  const t = new Set();
  for (const r of rows)
    if (r.setArtist === artist && r.clip !== exceptClip
        && r.decision === "got" && r.song
        && r.song.toLowerCase() !== UNKNOWN)
      t.add(r.song);
  return t;
}

function songOptions(artist, row) {
  const sl = S.setlists[artist];
  const taken = takenTitles(artist, row.clip);
  const opts = [{v: "", label: "— not yet identified —"}];
  if (sl) for (const s of sl.songs) {
    if (s.unknown) continue;
    let label = s.position + ". " + s.title;
    if (s.section) label += "  [" + s.section.replace(/:$/,"") + "]";
    if (s.cover) label += "  (" + s.cover + " cover)";
    opts.push({v: s.title, label, disabled: taken.has(s.title) && row.song !== s.title});
  }
  opts.push({v: UNKNOWN, label: "— unknown (crowdsource the title) —"});
  opts.push({v: FREE, label: "— " + FREE + "… —"});
  return opts;
}

function coverFor(artist, title) {
  const sl = S.setlists[artist];
  if (!sl) return "";
  const hit = sl.songs.find(s => s.title === title);
  return hit ? hit.cover : "";
}

function render() {
  const main = document.getElementById("main");
  main.innerHTML = "";
  const groups = new Map();
  for (const r of rows) {
    const key = r.setArtist || "(no artist)";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(r);
  }
  for (const [artist, group] of groups) {
    const block = document.createElement("div");
    block.className = "artist-block";
    const h = document.createElement("h2");
    h.textContent = artist + "  (" + group.filter(r=>r.decision==="got").length + " keepers)";
    block.appendChild(h);
    const sl = S.setlists[artist];
    const note = document.createElement("p");
    note.className = "artist-note";
    note.textContent = !sl ? "no cached setlist — free-text entry (run --identify to fetch)"
      : sl.incomplete ? "setlist.fm warns this setlist is incomplete/out of order — dropdown is a suggestion, not an ordering"
      : sl.songs.filter(s=>!s.unknown).length + " setlist songs";
    block.appendChild(note);
    for (const r of group) block.appendChild(renderRow(r));
    main.appendChild(block);
  }
}

function renderRow(r) {
  const div = document.createElement("div");
  div.className = "row" + (r.decision === "skip" ? " skip" : "");

  if (r.videoId) {
    const img = document.createElement("img");
    img.className = "thumb";
    img.src = "https://i.ytimg.com/vi/" + r.videoId + "/mqdefault.jpg";
    img.alt = "";
    div.appendChild(img);
  } else {
    const ph = document.createElement("div");
    ph.className = "thumb";
    div.appendChild(ph);
  }

  const meta = document.createElement("div");
  meta.className = "meta";
  const time = (r.capture || "").split(" ")[1] || "";
  meta.innerHTML = '<div class="dur"></div><div></div><div></div>';
  meta.children[0].textContent = r.duration || "?:??";
  meta.children[1].textContent = "#" + r.order + (time ? "  " + time.slice(0,5) : "");
  if (r.videoId) {
    const a = document.createElement("a");
    a.href = "https://studio.youtube.com/video/" + r.videoId + "/edit";
    a.target = "_blank"; a.rel = "noopener";
    a.textContent = "open in Studio";
    meta.children[2].appendChild(a);
  }
  div.appendChild(meta);

  const pick = document.createElement("div");
  pick.className = "pick";

  const dec = document.createElement("select");
  for (const v of ["got", "skip"]) {
    const o = document.createElement("option");
    o.value = v; o.textContent = v; o.selected = r.decision === v;
    dec.appendChild(o);
  }
  dec.onchange = () => { r.decision = dec.value; markDirty(); render(); };
  pick.appendChild(dec);

  const art = document.createElement("select");
  for (const v of S.artists) {
    const o = document.createElement("option");
    o.value = v; o.textContent = v; o.selected = r.setArtist === v;
    art.appendChild(o);
  }
  art.onchange = () => { r.setArtist = art.value; markDirty(); render(); };
  pick.appendChild(art);

  if (r.decision === "got") {
    const sel = document.createElement("select");
    sel.className = "song";
    const opts = songOptions(r.setArtist, r);
    const known = opts.some(o => o.v === r.song);
    for (const o of opts) {
      const el = document.createElement("option");
      el.value = o.v; el.textContent = o.label;
      el.disabled = !!o.disabled;
      el.selected = r.song === o.v;
      sel.appendChild(el);
    }
    if (r.song && !known) {   // off-setlist title already typed
      const el = document.createElement("option");
      el.value = r.song; el.textContent = r.song + "  (off-setlist)";
      el.selected = true;
      sel.insertBefore(el, sel.children[1]);
    }
    sel.onchange = () => {
      if (sel.value === FREE) {
        const typed = prompt("Song title:", "");
        r.song = (typed || "").trim();
      } else {
        r.song = sel.value;
      }
      if (r.song && r.song.toLowerCase() !== UNKNOWN && !r.cover)
        r.cover = coverFor(r.setArtist, r.song);
      markDirty(); render();
    };
    pick.appendChild(sel);

    const cov = document.createElement("input");
    cov.type = "text"; cov.className = "cover";
    cov.placeholder = "cover of…"; cov.value = r.cover;
    cov.onchange = () => { r.cover = cov.value.trim(); markDirty(); };
    pick.appendChild(cov);

    if (r.candidates || r.lyricHint) {
      const hint = document.createElement("div");
      hint.className = "hint";
      hint.textContent = [r.candidates && ("candidates: " + r.candidates),
                          r.lyricHint && ("lyric: " + r.lyricHint)]
                         .filter(Boolean).join("   ·   ");
      pick.appendChild(hint);
    }
  } else {
    const why = document.createElement("input");
    why.type = "text"; why.placeholder = "skip reason";
    why.value = r.skipReason;
    why.onchange = () => { r.skipReason = why.value.trim(); markDirty(); };
    pick.appendChild(why);
  }

  div.appendChild(pick);
  return div;
}

function markDirty() {
  dirty = true;
  document.getElementById("save").disabled = false;
  setStatus("unsaved changes");
}
function setStatus(t) { document.getElementById("status").textContent = t; }

async function post(path, body) {
  const resp = await fetch(path + "?t=" + TOKEN, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
  return resp.json();
}

document.getElementById("save").onclick = async () => {
  const out = await post("/save", {rows: rows.map(r => ({
    clip: r.clip, decision: r.decision, setArtist: r.setArtist,
    song: r.song, cover: r.cover, skipReason: r.skipReason}))});
  if (out.errors && out.errors.length) {
    setStatus("save had problems: " + out.errors.join("; "));
  } else {
    dirty = false;
    document.getElementById("save").disabled = true;
    setStatus("saved — " + out.changed + " row(s) updated");
  }
};

document.getElementById("done").onclick = async () => {
  if (dirty && !confirm("Unsaved changes — leave anyway?")) return;
  try { await post("/quit", {}); } catch (e) {}
  document.body.innerHTML = "<p style='margin:40px;font:16px system-ui'>" +
    "Editor closed. Next: <code>python3 youtube_upload_show.py --apply --dry-run</code></p>";
};

window.addEventListener("beforeunload", e => {
  if (dirty) { e.preventDefault(); e.returnValue = ""; }
});

render();
setStatus(rows.filter(r => r.decision === "got" && !r.song).length + " songs still to pick");
</script></body></html>
"""


# ── server ───────────────────────────────────────────────────────────────────

def serve(manifest_path: str, show: dict, setlists: dict,
          port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    """Serve the editor until Done or Ctrl-C. Blocks."""
    token = secrets.token_urlsafe(16)
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):          # quiet
            pass

        def _reject(self, code, msg):
            self.send_response(code)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(msg.encode())

        def _authorized(self) -> bool:
            query = parse_qs(urlparse(self.path).query)
            if query.get("t", [""])[0] != token:
                return False
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).hostname not in ("127.0.0.1",
                                                            "localhost"):
                return False
            return True

        def do_GET(self):
            if urlparse(self.path).path != "/" or not self._authorized():
                return self._reject(403, "forbidden")
            with lock:
                rows = yt_manifest.load(manifest_path)
                page = render_page(build_state(rows, setlists, show), token)
            body = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            path = urlparse(self.path).path
            if not self._authorized():
                return self._reject(403, "forbidden")

            if path == "/quit":
                self._json({"ok": True})
                threading.Thread(target=server.shutdown, daemon=True).start()
                return

            if path != "/save":
                return self._reject(404, "no such endpoint")

            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._reject(400, "bad json")

            with lock:
                rows = yt_manifest.load(manifest_path)
                changed, errors = apply_edits(rows, payload.get("rows"))
                if changed:
                    yt_manifest.save(manifest_path, rows)
            self._json({"ok": not errors, "changed": changed,
                        "errors": errors})

        def _json(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/?t={token}"
    print(f"\nManifest editor: {url}")
    print("  Save writes the lean TSV; the machine sidecar is never touched.")
    print("  Done (or Ctrl-C here) stops the server.\n")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print("Editor closed. Next:\n"
          "  python3 youtube_upload_show.py --apply --dry-run")
""".rstrip() if False else None
