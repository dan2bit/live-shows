#!/usr/bin/env python3
"""
photo_queue.py — the untagged queue: one local page to drain the photo backlog

    python3 tools/photos/show_photos.py queue            # serve and open the page
    python3 tools/photos/photo_queue.py --port 8781      # the same, directly

The queue is every photo sitting in one of the five upload albums (Guitar
gods / Player portraits / Concert memorabilia / Preshow selfies / Crowds) that
carries no show/ tag yet - which is to say, everything the phone has uploaded
that the pipeline has not filed. The page shows them as cards grouped by the
show they appear to belong to, each card carrying only what a human has to
decide: which show (pre-filled from the capture time, or from a `show
YYYY-MM-DD` description), who is in frame (the bill and that night's sidemen
offered first), and for memorabilia the subtype and whether it is signed.
One Apply files every ticked card through the same `add` path the
issue-close workflow uses - tags, show album, kind album, artist album,
share links, the show row's Photo URL and the artist-albums.tsv row.

The page also shows, per show, what the open `Photos:` issue expected
against what is filed, so the memorabilia still to be photographed is a
list rather than a memory. Expected items come from the issue bodies on
GitHub (public API, no token); filed items from the show's tags.

Nothing here writes until Apply, and Apply writes only what was ticked. The
cards are filed one at a time and each result streams back to the page as it
lands; the server is read once per batch, not once per photo. Library row
changes land in the repo at --root (default: the checkout this script runs
from) for a normal commit; the page says which files moved. Run it from a
worktree with --root pointing at the real clone so the rows do not land in a
stale tree. Requires IMMICH_API_KEY, same as immich.py.
"""

import argparse
import datetime
import html
import http.server
import json
import os
import re
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

import immich  # noqa: E402
import show_photos as sp  # noqa: E402

ISSUES_URL = ("https://api.github.com/repos/dan2bit/live-shows/issues"
              "?labels=photo&state=open&per_page=50")
# a show whose photos arrive after midnight: before this hour, the night
# before is the first guess
MIDNIGHT_SLOP_HOURS = 6
# default lower bound on capture date for the cards shown (the picker and the
# derivation always see every show row); --since widens or narrows it
DEFAULT_SINCE_DAYS = 90

# words in an issue's memorabilia line -> the subtype it will be filed under
_SUBTYPE_WORDS = [
    ("setlist", "setlist"), ("set list", "setlist"), ("poster", "poster"),
    ("vinyl", "vinyl"), ("cd", "cd"), ("pick", "pick"), ("ticket", "ticket"),
    ("autograph book", "autograph-book"), ("book", "autograph-book"),
    ("print", "photo-print"), ("hat", "hat"),
]


# ── the queue ──────────────────────────────────────────────────────────────

def _local_dt(asset):
    """Capture time as a naive local datetime (Immich's localDateTime is the
    camera's wall clock; fileCreatedAt is UTC and only a fallback)."""
    s = asset.get("localDateTime") or asset.get("fileCreatedAt") or ""
    s = str(s)[:19]
    try:
        return datetime.datetime.fromisoformat(s)
    except ValueError:
        return None


def _show_options():
    """Every show already played, for the picker and the derivation: [(date,
    label, row)], newest first. A photo cannot belong to a show that has not
    happened, so upcoming rows are left out. Current wins over history where
    a date repeats. The label leads with the act - a picker is scanned by
    name, the date is confirmation."""
    today = datetime.date.today().isoformat()
    out = {}
    for row in sp._show_rows():
        date = (row.get("Show Date") or "").strip()
        if len(date) != 10 or date > today or date in out:
            continue
        if (row.get("Status") or "").strip().lower() == "upcoming":
            continue
        venue = sp.show_venue(row)
        label = f"{(row.get('Artist') or '').strip()}  {date}" + (f"  ({venue})" if venue else "")
        out[date] = (label, row)
    return [(d, out[d][0], out[d][1]) for d in sorted(out, reverse=True)]


def derive_show(dt, shows):
    """The show a capture time most plausibly belongs to: the night before
    when the clock is small and that night had a show, else the same day
    when it did. None otherwise - memorabilia and strays stay unassigned."""
    if dt is None:
        return None
    same = dt.date().isoformat()
    before = (dt.date() - datetime.timedelta(days=1)).isoformat()
    if dt.hour < MIDNIGHT_SLOP_HOURS and before in shows:
        return before
    if same in shows:
        return same
    return None


def build_queue(since=None):
    """Everything in an upload album with no show/ tag and a capture date
    on or after `since` (None = everything), with what the page can derive
    for each."""
    kinds = sp._album_kinds()
    members = {}
    for album_id, kind in kinds.items():
        for a in immich.search_metadata(album_id=album_id, with_exif=True):
            members.setdefault(a["id"], (kind, a))
    tagged = set()
    for val, tid in sp._tag_index().items():
        if val.startswith("show/"):
            tagged |= sp._assets_of(tid)
    shows = _show_options()
    by_date = {d: row for d, _, row in shows}

    cards = []
    for aid, (kind, a) in members.items():
        if aid in tagged:
            continue
        dt = _local_dt(a)
        if since and dt and dt.date().isoformat() < since:
            continue
        hint = sp.parse_hint(((a.get("exifInfo") or {}).get("description") or ""))
        show = hint.get("show") or (derive_show(dt, by_date) if kind != sp.MEMORABILIA_KIND else None)
        cards.append({
            "id": aid,
            "kind": hint.get("kind") or kind,
            "taken": dt.strftime("%Y-%m-%d %H:%M") if dt else "",
            "hint": hint,
            "show": show,
            "derived": bool(show and not hint.get("show")),
            "file": a.get("originalFileName") or "",
        })
    cards.sort(key=lambda c: (c["show"] or "~", c["taken"]), reverse=True)
    return cards, shows


def choices_for(date, row):
    """Artist choices for a show: the bill, then that night's sidemen."""
    out = []
    for n in sp.show_bill(row) + sp._seen_with_for(date):
        if n and n not in out:
            out.append(n)
    return out


# ── expected vs filed ──────────────────────────────────────────────────────

def _issue_expectations():
    """{date: {"number", "with": [names], "memorabilia": [texts]}} from the
    open Photos: issues. Public endpoint; an outage just leaves the panel
    empty."""
    try:
        req = urllib.request.Request(ISSUES_URL, headers={"Accept": "application/vnd.github+json",
                                                          "User-Agent": "live-shows photo_queue"})
        with urllib.request.urlopen(req, timeout=15, context=immich._ssl_context()) as r:
            issues = json.load(r)
    except Exception as e:  # noqa: BLE001
        print(f"WARN: could not read the open Photos: issues ({e})", file=sys.stderr)
        return {}
    out = {}
    for iss in issues:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", iss.get("title") or "")
        if not m:
            continue
        exp = {"number": iss["number"], "with": [], "memorabilia": []}
        for line in (iss.get("body") or "").splitlines():
            lm = re.match(r"\s*-\s*\[[ xX]\]\s*(with-artist|memorabilia):\s*(.+?)\s*$", line)
            if not lm:
                continue
            text = re.sub(r"\s*\(.*?\)\s*$", "", lm.group(2)).strip()
            (exp["with"] if lm.group(1) == "with-artist" else exp["memorabilia"]).append(text)
        out[m.group(1)] = exp
    return out


def _filed_for(date, tag_index):
    """What the show's tagged photos say: artist slugs, memorabilia
    (subtype, signed) pairs, and a kind count."""
    tid = tag_index.get(f"show/{date}")
    out = {"artists": set(), "memorabilia": [], "kinds": {}}
    if not tid:
        return out
    for aid in sp._assets_of(tid):
        full = immich.asset(aid) or {}
        vals = {t.get("value") or "" for t in (full.get("tags") or [])}
        kind = next((v.split("/", 1)[1] for v in vals if v.startswith("kind/")), "")
        out["kinds"][kind] = out["kinds"].get(kind, 0) + 1
        out["artists"] |= {v.split("/", 1)[1] for v in vals if v.startswith("artist/")}
        subs = [v.split("/", 1)[1] for v in vals if v.startswith("memorabilia/")]
        for s in subs:
            out["memorabilia"].append((s, "signed" in vals))
    return out


def _subtype_guess(text):
    low = text.lower()
    for word, sub in _SUBTYPE_WORDS:
        if word in low:
            return sub
    return "other"


def gaps_for(shows):
    """[{date, label, issue, with: [(name, filed)], memorabilia: [(text, filed)]}]
    for every show that has an open Photos: issue."""
    exp = _issue_expectations()
    if not exp:
        return []
    tag_index = sp._tag_index()
    labels = {d: lab for d, lab, _ in shows}
    out = []
    for date in sorted(exp, reverse=True):
        e = exp[date]
        filed = _filed_for(date, tag_index)
        used = []
        mem = []
        for text in e["memorabilia"]:
            want = _subtype_guess(text)
            signed = "signed" in text.lower() or "signature" in text.lower()
            hit = next((i for i, (s, sg) in enumerate(filed["memorabilia"])
                        if i not in used and s == want and (sg or not signed)), None)
            if hit is not None:
                used.append(hit)
            mem.append((text, hit is not None))
        out.append({
            "date": date, "label": labels.get(date, date), "issue": e["number"],
            "with": [(n, sp._slug(n) in filed["artists"]) for n in e["with"]],
            "memorabilia": mem,
            "filed": filed["kinds"],
        })
    return out


# ── apply ──────────────────────────────────────────────────────────────────

def apply_items(items):
    """File each ticked card through add_asset and the row writers, yielding
    one result dict per card as it lands, then a final {"done": ...}. The
    album/link state and the tag membership cache are built once for the
    batch (sync_state) and threaded through every add_asset. A failure on
    one card is reported on that card and does not stop the rest."""
    touched = set()
    state = None
    for it in items:
        aid = it.get("id", "")
        try:
            if state is None:
                state = sp.sync_state()
            res = sp.add_asset(aid, it["show"], it.get("kind") or None,
                               artist=it.get("artist") or None,
                               subtype=it.get("subtype") or None,
                               signed=bool(it.get("signed")), dry_run=False,
                               state=state)
            lines = [sp.set_show_photo_url(it["show"], res["show_link"])]
            touched.add("the show row")
            if res["artist"]:
                lines.append(sp.upsert_artist_album(res["artist"], res["artist_link"]))
                touched.add("data/show_goals/artist-albums.tsv")
            yield {"id": aid, "ok": True, "show_link": res["show_link"],
                   "artist": res["artist"], "artist_link": res["artist_link"],
                   "rows": lines}
        except SystemExit as e:
            yield {"id": aid, "ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001
            yield {"id": aid, "ok": False, "error": f"{type(e).__name__}: {e}"}
    yield {"done": True, "touched": sorted(touched), "root": sp._ROOT}


# ── the page ───────────────────────────────────────────────────────────────

PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>photo queue</title>
<style>
 body{font:14px/1.4 -apple-system,Helvetica,Arial,sans-serif;margin:0;background:#f4f2ee;color:#222}
 header{position:sticky;top:0;background:#fff;border-bottom:1px solid #ddd;padding:10px 16px;display:flex;gap:16px;align-items:center;z-index:2}
 header h1{font-size:16px;margin:0;flex:1}
 button{font:inherit;padding:6px 14px;border-radius:6px;border:1px solid #888;background:#fff;cursor:pointer}
 button.primary{background:#1d4ed8;color:#fff;border-color:#1d4ed8}
 button:disabled{opacity:.5;cursor:default}
 main{padding:12px 16px;max-width:1400px}
 .group{margin:18px 0}
 .group h2{font-size:15px;margin:0 0 6px;display:inline-flex;gap:10px;align-items:baseline}
 .group summary{cursor:pointer}
 .group h2 small{color:#666;font-weight:normal}
 .gaps{background:#fff;border:1px solid #e3e0d8;border-radius:8px;padding:8px 12px;margin:6px 0 10px;font-size:13px}
 .gaps b{font-weight:600}
 .gaps .ok{color:#15803d}.gaps .miss{color:#b45309}
 .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:12px}
 .card{background:#fff;border:1px solid #e3e0d8;border-radius:8px;padding:10px;display:grid;grid-template-columns:120px 1fr;gap:10px}
 .card.done{opacity:.55}
 .card img{width:120px;height:120px;object-fit:cover;border-radius:6px;background:#ddd}
 .card .meta{font-size:12px;color:#666;margin-bottom:4px}
 .card label{display:block;font-size:12px;color:#444;margin-top:4px}
 .card select,.card input[type=text]{width:100%;font:inherit;padding:3px 4px;box-sizing:border-box}
 .card .kind{display:inline-block;font-size:11px;padding:1px 6px;border-radius:10px;background:#eee;margin-right:6px}
 .card .hint{font-size:12px;color:#1d4ed8}
 .card .res{font-size:12px;margin-top:6px}
 .card .res.ok{color:#15803d}.card .res.err{color:#b91c1c}
 .tick{display:flex;align-items:center;gap:6px;font-size:12px;margin-top:6px}
 #status{font-size:13px;color:#555}
 .empty{color:#666;padding:30px 0}
</style></head>
<body>
<header><h1>photo queue <small id="count"></small></h1><span id="status"></span>
<label style="font-size:12px">since <input type="date" id="since" style="font:inherit"></label>
<button id="all">all</button>
<button id="reload">reload</button><button id="apply" class="primary">apply ticked</button></header>
<main id="main"><div class="empty">loading…</div></main>
<script>
const KINDS=["with-artist","performance","memorabilia","selfie","crowd"];
const SUBTYPES=%SUBTYPES%;
let DATA=null;
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function choicesFor(date){const s=DATA.shows.find(x=>x.date===date);return s?s.choices:[];}
function showSelect(c){
  let o=`<option value="">— choose show —</option>`;
  for(const s of DATA.shows)o+=`<option value="${s.date}"${s.date===c.show?" selected":""}>${esc(s.label)}</option>`;
  return `<select name="show">${o}</select>`;
}
function billOf(date){const s=DATA.shows.find(x=>x.date===date);return s?s.bill:[];}
function artistField(c){
  const ch=choicesFor(c.show);
  const list=ch.map(n=>`<option value="${esc(n)}">`).join("");
  // a one-act bill answers "who" for a with-artist or stage shot by itself
  const bill=billOf(c.show);
  const v=c.hint.artist||((c.kind==="with-artist"||c.kind==="performance")&&bill.length===1?bill[0]:"");
  return `<input type="text" name="artist" list="al-${c.id}" placeholder="${c.kind==="selfie"||c.kind==="crowd"?"(none)":"who is in frame"}" value="${esc(v)}"><datalist id="al-${c.id}">${list}</datalist>`;
}
function card(c){
  const mem=c.kind==="memorabilia";
  const kindSel=`<select name="kind">${KINDS.map(k=>`<option${k===c.kind?" selected":""}>${k}</option>`).join("")}</select>`;
  const sub=mem?`<label>subtype <select name="subtype"><option value="">—</option>${SUBTYPES.map(s=>`<option${s===c.hint.subtype?" selected":""}>${s}</option>`).join("")}</select></label>
     <label><input type="checkbox" name="signed"${c.hint.signed?" checked":""}> signed</label>`:"";
  const hint=Object.keys(c.hint).length?`<div class="hint">description says: ${esc(Object.entries(c.hint).map(([k,v])=>k+"="+v).join(", "))}</div>`:"";
  const bill0=billOf(c.show);
  const tick=!!c.show&&(c.kind==="selfie"||c.kind==="crowd"||!!c.hint.artist||((c.kind==="with-artist"||c.kind==="performance")&&bill0.length===1));
  return `<div class="card" data-id="${c.id}">
    <a href="${DATA.base}/photos/${c.id}" target="_blank" title="open in Immich"><img src="/thumb/${c.id}" loading="lazy"></a>
    <div>
      <div class="meta"><span class="kind">${esc(c.kind)}</span>${esc(c.taken)}${c.derived?" · show derived from the time":""}</div>
      ${hint}
      <label>show ${showSelect(c)}</label>
      <label>kind ${kindSel}</label>
      <label>artist ${artistField(c)}</label>
      ${sub}
      <div class="tick"><input type="checkbox" name="file"${tick?" checked":""}> file this one</div>
      <div class="res"></div>
    </div></div>`;
}
function gapsPanel(g){
  const w=g.with.map(([n,ok])=>`<span class="${ok?"ok":"miss"}">${ok?"✓":"✗"} ${esc(n)}</span>`).join(" · ");
  const m=g.memorabilia.map(([t,ok])=>`<span class="${ok?"ok":"miss"}">${ok?"✓":"✗"} ${esc(t)}</span>`).join("<br>");
  const k=Object.entries(g.filed).map(([a,b])=>`${b} ${a}`).join(", ")||"nothing filed yet";
  return `<div class="gaps"><b>#${g.issue}</b> expects — with-artist: ${w||"—"}<br>memorabilia:<br>${m||"—"}<br><small>filed so far: ${k}</small></div>`;
}
function render(){
  const main=document.getElementById("main");
  document.getElementById("count").textContent=`${DATA.cards.length} untagged · rows → ${DATA.root}`;
  if(!DATA.cards.length&&!DATA.gaps.length){main.innerHTML='<div class="empty">queue is empty</div>';return;}
  const groups=new Map();
  for(const c of DATA.cards){const k=c.show||"";if(!groups.has(k))groups.set(k,[]);groups.get(k).push(c);}
  const gapsBy=new Map(DATA.gaps.map(g=>[g.date,g]));
  let h="";
  // shows with open issues but no queued photos still get their gaps panel
  for(const g of DATA.gaps)if(!groups.has(g.date))groups.set(g.date,[]);
  const keys=[...groups.keys()].sort().reverse();
  for(const k of keys){
    const s=DATA.shows.find(x=>x.date===k);
    const title=k?esc(s?`${k}  ${s.label.replace("  "+k,"")}`:k):"unassigned";
    const cs=groups.get(k)||[];
    h+=`<details class="group" open><summary><h2>${title} <small>${cs.length} queued</small></h2></summary>`;
    if(gapsBy.has(k))h+=gapsPanel(gapsBy.get(k));
    if(cs.length)h+=`<div class="cards">${cs.map(card).join("")}</div>`;
    h+=`</details>`;
  }
  main.innerHTML=h;
  main.querySelectorAll('select[name=show]').forEach(sel=>sel.addEventListener('change',e=>{
    const cardEl=e.target.closest('.card');const c=DATA.cards.find(x=>x.id===cardEl.dataset.id);
    c.show=e.target.value;cardEl.querySelector('input[name=artist]').setAttribute('list','');
    const dl=cardEl.querySelector('datalist');dl.innerHTML=choicesFor(c.show).map(n=>`<option value="${esc(n)}">`).join("");
    cardEl.querySelector('input[name=artist]').setAttribute('list',dl.id);
  }));
}
let ALL=false;
async function load(){
  document.getElementById("status").textContent="reading the server…";
  const since=document.getElementById("since").value;
  const url=ALL?"/queue?since=":(since?"/queue?since="+since:"/queue");
  const r=await fetch(url);DATA=await r.json();
  if(DATA.since&&!since&&!ALL)document.getElementById("since").value=DATA.since;
  render();
  document.getElementById("status").textContent="";
}
async function apply(){
  const items=[];
  for(const el of document.querySelectorAll('.card:not(.done)')){
    if(!el.querySelector('input[name=file]').checked)continue;
    const g=n=>el.querySelector(`[name=${n}]`);
    const it={id:el.dataset.id,show:g("show").value,kind:g("kind").value,artist:g("artist").value.trim()};
    if(g("subtype")){it.subtype=g("subtype").value;it.signed=g("signed").checked;}
    if(!it.show){el.querySelector('.res').textContent="pick a show";el.querySelector('.res').className="res err";continue;}
    items.push(it);
  }
  if(!items.length)return;
  const btn=document.getElementById("apply");btn.disabled=true;
  const status=document.getElementById("status");
  for(const it of items){const el=document.querySelector(`.card[data-id="${it.id}"]`);el.querySelector('.res').className="res";el.querySelector('.res').textContent="queued…";}
  status.textContent=`filing 0/${items.length}…`;
  let n=0,done=0,touched=[],root="";
  const r=await fetch("/apply",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(items)});
  const reader=r.body.getReader();const dec=new TextDecoder();let buf="";
  while(true){
    const {value,done:eof}=await reader.read();
    if(value)buf+=dec.decode(value,{stream:true});
    let nl;
    while((nl=buf.indexOf("\n"))>=0){
      const line=buf.slice(0,nl);buf=buf.slice(nl+1);if(!line.trim())continue;
      const res=JSON.parse(line);
      if(res.done){touched=res.touched;root=res.root;continue;}
      done++;
      const el=document.querySelector(`.card[data-id="${res.id}"]`);if(!el)continue;
      const box=el.querySelector('.res');
      if(res.ok){n++;el.classList.add("done");box.className="res ok";
        box.innerHTML=`filed · <a href="${res.show_link}" target="_blank">show album</a>`+(res.artist?` · <a href="${res.artist_link}" target="_blank">${esc(res.artist)}</a>`:"");}
      else{box.className="res err";box.textContent=res.error;}
      status.textContent=`filing ${done}/${items.length}…`;
    }
    if(eof)break;
  }
  status.textContent=`${n}/${items.length} filed`+(touched.length?` · changed in ${root}: ${touched.join(", ")} (commit when done)`:"");
  btn.disabled=false;
}
document.getElementById("reload").onclick=load;
document.getElementById("all").onclick=()=>{ALL=true;document.getElementById("since").value="";load();};
document.getElementById("since").onchange=()=>{ALL=false;load();};
document.getElementById("apply").onclick=apply;
load();
</script></body></html>
"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            page = PAGE.replace("%SUBTYPES%", json.dumps(list(sp.MEMORABILIA_SUBTYPES)))
            return self._send(200, page, "text/html; charset=utf-8")
        if self.path.startswith("/thumb/"):
            aid = self.path[len("/thumb/"):]
            if not sp._UUID_RE.match(aid):
                return self._send(404, b"", "text/plain")
            try:
                return self._send(200, immich.thumbnail(aid, size="thumbnail"), "image/webp")
            except (Exception, SystemExit) as e:  # immich._req exits on an HTTP error
                return self._send(502, str(e), "text/plain")
        if self.path.startswith("/queue"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query, keep_blank_values=True)
            since = (q.get("since") or [self.server.since])[0] or None
            try:
                cards, shows = build_queue(since)
            except (Exception, SystemExit) as e:
                return self._send(502, json.dumps({"error": str(e)}))
            base, _ = immich._config()
            payload = {
                "base": base,
                "root": sp._ROOT,
                "since": since or "",
                "cards": cards,
                "shows": [{"date": d, "label": lab, "choices": choices_for(d, row),
                           "bill": sp.show_bill(row)}
                          for d, lab, row in shows],
                "gaps": gaps_for(shows),
            }
            return self._send(200, json.dumps(payload))
        return self._send(404, b"", "text/plain")

    def do_POST(self):
        if self.path != "/apply":
            return self._send(404, b"", "text/plain")
        n = int(self.headers.get("Content-Length") or 0)
        items = json.loads(self.rfile.read(n) or b"[]")
        # one JSON object per line, flushed as each card lands; no
        # Content-Length, so the body ends when the connection closes
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        for res in apply_items(items):
            self.wfile.write((json.dumps(res) + "\n").encode("utf-8"))
            self.wfile.flush()


def serve(port, since, open_browser=True):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    srv.since = since
    url = f"http://127.0.0.1:{port}/"
    print(f"photo queue at {url}  (Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--port", type=int, default=8781)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--list", action="store_true",
                    help="print the queue and the gaps as text instead of serving")
    ap.add_argument("--since", metavar="DATE",
                    help=f"only photos captured on/after DATE (default: {DEFAULT_SINCE_DAYS} "
                         "days ago; 'all' for the whole library)")
    ap.add_argument("--root", metavar="DIR",
                    help="the repo checkout whose data/ the rows are read from and written "
                         "to (default: the one this script lives in). Point a worktree run "
                         "at the real clone.")
    args = ap.parse_args(argv)
    if args.root:
        root = os.path.abspath(os.path.expanduser(args.root))
        if not os.path.isdir(os.path.join(root, "data")):
            raise SystemExit(f"--root {root} has no data/ directory")
        sp._ROOT = immich._ROOT = root
    print(f"library rows: {sp._ROOT}")
    since = args.since or (datetime.date.today()
                           - datetime.timedelta(days=DEFAULT_SINCE_DAYS)).isoformat()
    if since == "all":
        since = None
    if args.list:
        cards, shows = build_queue(since)
        labels = {d: lab for d, lab, _ in shows}
        print(f"{len(cards)} untagged photo(s) in the upload albums\n")
        cur = object()
        for c in cards:
            if c["show"] != cur:
                cur = c["show"]
                print(f"== {labels.get(cur, cur) if cur else 'unassigned'}")
            said = ", ".join(f"{k}={v}" for k, v in c["hint"].items())
            print(f"  {c['id'][:8]}  {c['taken']}  {c['kind']:12s}"
                  + (f"  says: {said}" if said else ""))
        print()
        for g in gaps_for(shows):
            print(f"== {g['label']}  (#{g['issue']})")
            for n, ok in g["with"]:
                print(f"  {'ok  ' if ok else 'GAP '} with-artist: {n}")
            for t, ok in g["memorabilia"]:
                print(f"  {'ok  ' if ok else 'GAP '} memorabilia: {t}")
            filed = ", ".join(f"{v} {k}" for k, v in g["filed"].items()) or "nothing"
            print(f"       filed: {filed}")
        return
    serve(args.port, since, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
