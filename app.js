// app.js — live-shows front-end logic
// See README for architecture notes.

// ── Configuration ────────────────────────────────────────────────────────
const REPO_OWNER = 'dan2bit';
const REPO_NAME  = 'live-shows';
const PRIVATE_REPO_NAME = 'live-shows-private';

// Feature flags
const FEATURES = {
  recommendations: true,
  privateData: true,
};

// ── Auth ───────────────────────────────────────────────────────────────────
const PAT_KEY = 'gh_pat';
function getPat(){ return localStorage.getItem(PAT_KEY)||''; }
function savePat(){ const v=document.getElementById('patInput').value.trim(); if(v){ localStorage.setItem(PAT_KEY,v); showToast('Token saved'); } closeAuthModal(); }
function clearPat(){ localStorage.removeItem(PAT_KEY); showToast('Token cleared'); closeAuthModal(); }

// ── GitHub API fetch ───────────────────────────────────────────────────────
async function ghFetch(path, repo=REPO_NAME){
  const url = `https://api.github.com/repos/${REPO_OWNER}/${repo}/contents/${path}`;
  const headers = { 'Accept': 'application/vnd.github.v3.raw' };
  const pat = getPat();
  if(pat) headers['Authorization'] = `token ${pat}`;
  const res = await fetch(url, { headers });
  if(!res.ok) throw new Error(`ghFetch ${path}: ${res.status}`);
  return res.text();
}

// ── TSV parser ─────────────────────────────────────────────────────────────
function parseTsv(text){
  const lines = text.trim().split('\n');
  if(!lines.length) return [];
  const headers = lines[0].split('\t');
  return lines.slice(1).map(line=>{
    const cols = line.split('\t');
    const row = {};
    headers.forEach((h,i)=>{ row[h] = (cols[i]||'').trim(); });
    return row;
  });
}

// ── Private data merge ─────────────────────────────────────────────────────
async function mergePrivateData(publicRows, privateFile, keyFn){
  if(!getPat()) return publicRows;
  try {
    const text = await ghFetch(privateFile, PRIVATE_REPO_NAME);
    const privateRows = parseTsv(text);
    const privateMap = {};
    privateRows.forEach(r=>{ privateMap[keyFn(r)] = r; });
    return publicRows.map(r=>{
      const priv = privateMap[keyFn(r)];
      return priv ? Object.assign({},r,priv) : r;
    });
  } catch(e) {
    console.warn('mergePrivateData failed:', e);
    return publicRows;
  }
}

// ── Date helpers ───────────────────────────────────────────────────────────
function today(){ return new Date().toISOString().slice(0,10); }
function parseDate(s){ return s ? new Date(s+'T12:00:00') : null; }
function fmtDate(s){
  const d = parseDate(s);
  if(!d) return s||'';
  return d.toLocaleDateString('en-US',{weekday:'short',month:'short',day:'numeric',year:'numeric'});
}
function isUpcoming(s){ return s >= today(); }
function isToday(s){ return s === today(); }

// ── On This Day ────────────────────────────────────────────────────────────
function renderOnThisDay(rows){
  const todayMD = today().slice(5); // MM-DD
  const matches = rows.filter(r=>r['Show Date']&&r['Show Date'].slice(5)===todayMD&&r['Status']==='attended');
  const el = document.getElementById('otdItems');
  if(!matches.length){ el.innerHTML='<span class="otd-none">&#8212;</span>'; return; }
  el.innerHTML = matches.map(r=>{
    const yr = r['Show Date'].slice(0,4);
    const artist = r['Artist']||'';
    return `<span class="otd-item"><span class="otd-year">${yr}</span> ${escHtml(artist)}</span>`;
  }).join('');
}

// ── Escape HTML ────────────────────────────────────────────────────────────
function escHtml(s){ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

// ── Toast ──────────────────────────────────────────────────────────────────
function showToast(msg, dur=2200){
  let t = document.getElementById('toast');
  if(!t){ t=document.createElement('div'); t.id='toast'; t.className='toast'; document.body.appendChild(t); }
  t.textContent=msg; t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'), dur);
}

// ── Tab switching ──────────────────────────────────────────────────────────
let activeTab = 'shows';
function switchTab(tab){
  document.querySelectorAll('.tab').forEach(el=>el.classList.toggle('active', el.dataset.tab===tab));
  document.querySelectorAll('.panel').forEach(el=>el.classList.toggle('active', el.id===`panel-${tab}`));
  activeTab = tab;
}

// ── Modal helpers ──────────────────────────────────────────────────────────
function openAboutModal(){ document.getElementById('aboutModal').classList.add('open'); }
function closeAboutModal(){ document.getElementById('aboutModal').classList.remove('open'); }
function openAuthModal(){ document.getElementById('authModal').classList.add('open'); }
function closeAuthModal(){ document.getElementById('authModal').classList.remove('open'); }
function closeForSaleModal(){ document.getElementById('forsaleModal').classList.remove('open'); }
function closeMultisetModal(){ document.getElementById('multisetModal').classList.remove('open'); }

// Close modals on backdrop click
document.addEventListener('click', e=>{
  ['aboutModal','authModal','forsaleModal','multisetModal','recommendModal'].forEach(id=>{
    const el = document.getElementById(id);
    if(el && e.target===el) el.classList.remove('open');
  });
});

// ── Badge helper ───────────────────────────────────────────────────────────
function setBadge(id, n){ const el=document.getElementById(id); if(el) el.textContent=n||'&#8212;'; }

// ── Venue display helper ───────────────────────────────────────────────────
function shortVenue(v){ return (v||'').split(',')[0].trim(); }

// ── Setlist / Playlist link helpers ───────────────────────────────────────
function setlistLink(url){
  if(!url||url==='-') return '';
  if(url.startsWith('MULTI:')) return `<span class="multi-trigger" onclick="openMultiset('${escHtml(url)}')">&#9835; setlists</span>`;
  return `<a href="${escHtml(url)}" target="_blank" class="icon-link">&#9835;</a>`;
}
function playlistLink(url){
  if(!url||url==='-') return '';
  if(url.startsWith('MULTI:')) return `<span class="multi-trigger" onclick="openMultiset('${escHtml(url)}')">&#9654; playlists</span>`;
  return `<a href="${escHtml(url)}" target="_blank" class="icon-link">&#9654;</a>`;
}
function photoLink(url){
  if(!url||url==='-') return '';
  return `<a href="${escHtml(url)}" target="_blank" class="icon-link">&#128247;</a>`;
}

// ── Multi-setlist modal ────────────────────────────────────────────────────
async function openMultiset(multiKey){
  document.getElementById('multisetModal').classList.add('open');
  document.getElementById('multisetModalBody').innerHTML = '<div class="multiset-loading">Loading&#8230;</div>';
  const dateKey = multiKey.replace('MULTI:','');
  try {
    const text = await ghFetch('data/setlists.json');
    const data = JSON.parse(text);
    const entries = data[dateKey];
    if(!entries||!entries.length){ document.getElementById('multisetModalBody').innerHTML='<p>No setlists found.</p>'; return; }
    document.getElementById('multisetModalBody').innerHTML = entries.map(e=>{
      const icon = e.type==='playlist' ? '&#9654;' : '&#9835;';
      return `<div class="multiset-item"><a href="${escHtml(e.url)}" target="_blank">${icon} ${escHtml(e.artist)}</a></div>`;
    }).join('');
  } catch(err){
    document.getElementById('multisetModalBody').innerHTML = `<p>Error: ${escHtml(err.message)}</p>`;
  }
}

// ── Interaction badge ──────────────────────────────────────────────────────
function interactionBadge(v){
  if(!v) return '';
  const map = { Photo:'&#128247;', Autograph:'&#9999;', Both:'&#128247;&#9999;' };
  return map[v] ? `<span class="badge badge-interaction" title="${escHtml(v)}">${map[v]}</span>` : '';
}

// ── Shows tab ──────────────────────────────────────────────────────────────
function renderShows(rows){
  const upcoming = rows.filter(r=>r['Status']==='upcoming').sort((a,b)=>a['Show Date'].localeCompare(b['Show Date']));
  const attended = rows.filter(r=>r['Status']==='attended').sort((a,b)=>b['Show Date'].localeCompare(a['Show Date']));
  setBadge('showsBadge', upcoming.length||attended.length);
  const allRows = [...upcoming, ...attended];
  if(!allRows.length){ document.getElementById('showsContent').innerHTML='<p class="empty">No shows.</p>'; return; }

  document.getElementById('showsContent').innerHTML = `
  <table class="shows-table">
    <thead><tr>
      <th>Date</th><th>Artist</th><th>Venue</th><th>Links</th>
    </tr></thead>
    <tbody>${allRows.map(r=>{
      const isUpcomingRow = r['Status']==='upcoming';
      const trClass = isUpcomingRow ? 'upcoming' : 'attended';
      const todayCls = isToday(r['Show Date']) ? ' today' : '';
      const vipBadge = r['VIP']==='Y' ? '<span class="badge badge-vip">VIP</span>' : '';
      const groupBadge = r['Group']==='Y' ? '<span class="badge badge-group">+</span>' : '';
      const support = r['Supporting Artist'] ? `<div class="support">w/ ${escHtml(r['Supporting Artist'])}</div>` : '';
      const interaction = interactionBadge(r['Artist Interaction']);
      const links = [setlistLink(r['Setlist.fm URL']), playlistLink(r['Playlist URL']), photoLink(r['Photo URL'])].filter(Boolean).join(' ');
      return `<tr class="${trClass}${todayCls}">
        <td class="date-cell">${escHtml(fmtDate(r['Show Date']))}</td>
        <td>${escHtml(r['Artist']||'')}${vipBadge}${groupBadge}${support}${interaction}</td>
        <td>${escHtml(shortVenue(r['Venue Name']||''))}</td>
        <td class="links-cell">${links}</td>
      </tr>`;
    }).join('')}</tbody>
  </table>`;
}

// ── History tab ────────────────────────────────────────────────────────────
function renderHistory(rows){
  const sorted = rows.slice().sort((a,b)=>b['Show Date'].localeCompare(a['Show Date']));
  setBadge('historyBadge', sorted.length||'&#8212;');
  if(!sorted.length){ document.getElementById('historyContent').innerHTML='<p class="empty">No history.</p>'; return; }

  document.getElementById('historyContent').innerHTML = `
  <table class="shows-table">
    <thead><tr>
      <th>Date</th><th>Artist</th><th>Venue</th><th>Links</th>
    </tr></thead>
    <tbody>${sorted.map(r=>{
      const support = r['Supporting Acts'] ? `<div class="support">w/ ${escHtml(r['Supporting Acts'])}</div>` : '';
      const links = [setlistLink(r['Setlist.fm URL']), playlistLink(r['Playlist URL']), photoLink(r['Photo URL'])].filter(Boolean).join(' ');
      return `<tr class="attended">
        <td class="date-cell">${escHtml(fmtDate(r['Show Date']))}</td>
        <td>${escHtml(r['Artist']||'')}${support}</td>
        <td>${escHtml(shortVenue(r['Venue']||''))}</td>
        <td class="links-cell">${links}</td>
      </tr>`;
    }).join('')}</tbody>
  </table>`;
}

// ── Potential tab ──────────────────────────────────────────────────────────
const DECISION_ORDER = { Buy:0, Choose:1, Sell:2, Pass:3 };

function renderPotential(rows, isAuthed){
  const sorted = rows.slice().sort((a,b)=>{
    const da = DECISION_ORDER[a['Decision']]??99;
    const db = DECISION_ORDER[b['Decision']]??99;
    if(da!==db) return da-db;
    return (a['Date']||'').localeCompare(b['Date']||'');
  });
  setBadge('potBadge', sorted.length||'&#8212;');
  if(!sorted.length){ document.getElementById('potContent').innerHTML='<p class="empty">No potentials.</p>'; return; }

  document.getElementById('potContent').innerHTML = `
  <table class="shows-table potential-table">
    <thead><tr>
      <th>Decision</th><th>Artist</th><th>Date</th><th>Venue</th><th>Notes</th>${isAuthed?'<th>Actions</th>':''}
    </tr></thead>
    <tbody>${sorted.map((r,i)=>{
      const dec = r['Decision']||'';
      const decClass = dec.toLowerCase();
      const watchFor = r['Watching For'] ? `<div class="watching">${escHtml(r['Watching For'])}</div>` : '';
      const notes = r['Notes'] ? `<div class="pot-notes">${escHtml(r['Notes'])}</div>` : '';
      const prev = r['Prev Show'] && r['Prev Show']!=='-' ? `<span class="bracket prev">${escHtml(r['Prev Show'])}</span>` : '';
      const next = r['Next Show'] && r['Next Show']!=='-' ? `<span class="bracket next">${escHtml(r['Next Show'])}</span>` : '';
      const brackets = (prev||next) ? `<div class="brackets">${prev}${next}</div>` : '';
      const actions = isAuthed ? `<td class="actions-cell">${renderDecisionActions(r, i)}</td>` : '';
      return `<tr class="pot-row pot-${decClass}" data-artist="${escHtml(r['Artist']||'')}" data-date="${escHtml(r['Date']||'')}">
        <td><span class="badge badge-${decClass}">${escHtml(dec)}</span></td>
        <td>${escHtml(r['Artist']||'')}${brackets}</td>
        <td class="date-cell">${escHtml(fmtDate(r['Date']))}</td>
        <td>${escHtml(shortVenue(r['Venue']||''))}</td>
        <td>${watchFor}${notes}</td>
        ${actions}
      </tr>`;
    }).join('')}</tbody>
  </table>`;
}

function renderDecisionActions(r, i){
  const decisions = ['Buy','Choose','Sell','Pass'];
  const current = r['Decision']||'';
  const select = `<select class="dec-select" onchange="handleDecisionChange(this,'${escHtml(r['Artist']||'')}','${escHtml(r['Date']||'')}')">`
    + decisions.map(d=>`<option${d===current?' selected':''}>${d}</option>`).join('')
    + '</select>';
  const revoke = `<button class="btn btn-sm" onclick="handleRevoke('${escHtml(r['Artist']||'')}','${escHtml(r['Date']||'')}')" title="Remove">&#10005;</button>`;
  return select + revoke;
}

async function handleDecisionChange(sel, artist, date){
  const newDec = sel.value;
  try {
    const text = await ghFetch('data/live_shows_potential.tsv');
    const rows = parseTsv(text);
    const idx = rows.findIndex(r=>r['Artist']===artist && r['Date']===date);
    if(idx===-1){ showToast('Row not found'); return; }
    rows[idx]['Decision'] = newDec;
    await commitPotential(rows, `decision: ${artist} → ${newDec}`);
    showToast(`${artist} → ${newDec}`);
    await loadData();
  } catch(e){ showToast('Error: '+e.message); }
}

async function handleRevoke(artist, date){
  if(!confirm(`Remove ${artist} from potentials?`)) return;
  try {
    const text = await ghFetch('data/live_shows_potential.tsv');
    const rows = parseTsv(text);
    const filtered = rows.filter(r=>!(r['Artist']===artist && r['Date']===date));
    await commitPotential(filtered, `revoke: ${artist}`);
    showToast(`Removed ${artist}`);
    await loadData();
  } catch(e){ showToast('Error: '+e.message); }
}

async function commitPotential(rows, msg){
  const headers = Object.keys(rows[0]||{});
  const tsv = [headers.join('\t'), ...rows.map(r=>headers.map(h=>r[h]||'').join('\t'))].join('\n')+'\n';
  const pat = getPat();
  if(!pat) throw new Error('Not authenticated');
  // Get current SHA
  const metaRes = await fetch(`https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/data/live_shows_potential.tsv`,
    { headers: { Authorization: `token ${pat}`, Accept: 'application/vnd.github.v3+json' } });
  const meta = await metaRes.json();
  const sha = meta.sha;
  const content = btoa(unescape(encodeURIComponent(tsv)));
  const putRes = await fetch(`https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/data/live_shows_potential.tsv`, {
    method: 'PUT',
    headers: { Authorization: `token ${pat}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: msg, content, sha })
  });
  if(!putRes.ok) throw new Error(`Commit failed: ${putRes.status}`);
}

// ── Waiting (fast_track) tab ───────────────────────────────────────────────
function renderTourHere(rows){
  const sorted = rows.slice().sort((a,b)=>(a['Artist']||'').localeCompare(b['Artist']||''));
  setBadge('tourhereBadge', sorted.length||'&#8212;');
  if(!sorted.length){ document.getElementById('tourhereContent').innerHTML='<p class="empty">No artists on watch.</p>'; return; }

  document.getElementById('tourhereContent').innerHTML = `
  <table class="shows-table">
    <thead><tr>
      <th>Artist</th><th>Tier</th><th>Notes</th>
    </tr></thead>
    <tbody>${sorted.map(r=>{
      return `<tr>
        <td>${escHtml(r['Artist']||'')}</td>
        <td><span class="badge">${escHtml(r['Tier']||'')}</span></td>
        <td>${escHtml(r['Notes']||'')}</td>
      </tr>`;
    }).join('')}</tbody>
  </table>`;
}

// ── For Sale modal ─────────────────────────────────────────────────────────
function openForSaleModal(rows){
  const sellRows = rows.filter(r=>r['Decision']==='Sell');
  const modal = document.getElementById('forsaleModal');
  const body = document.getElementById('forsaleModalBody');
  if(!sellRows.length){ body.innerHTML='<p>Nothing for sale.</p>'; modal.classList.add('open'); return; }
  body.innerHTML = sellRows.map(r=>{
    const notes = r['Notes'] ? `<div class="pot-notes">${escHtml(r['Notes'])}</div>` : '';
    return `<div class="forsale-item"><strong>${escHtml(r['Artist']||'')}</strong> — ${escHtml(fmtDate(r['Date']))} @ ${escHtml(shortVenue(r['Venue']||''))}${notes}</div>`;
  }).join('');
  modal.classList.add('open');
}

// ── Load and render ────────────────────────────────────────────────────────
let _currentRows = [];
let _historyRows = [];
let _potentialRows = [];
let _tourhereRows = [];

async function loadData(){
  document.getElementById('refreshBtn').disabled = true;
  try {
    const [currentText, historyTexts, potText, tourhereText] = await Promise.all([
      ghFetch('data/live_shows_current.tsv'),
      fetchHistoryFiles(),
      ghFetch('data/live_shows_potential.tsv'),
      ghFetch('data/fast_track.tsv'),
    ]);

    _currentRows = parseTsv(currentText);
    _historyRows = historyTexts.flatMap(t=>parseTsv(t));
    _potentialRows = parseTsv(potText);
    _tourhereRows = parseTsv(tourhereText);

    const pat = getPat();
    if(pat && FEATURES.privateData){
      _currentRows = await mergePrivateData(_currentRows, 'current_private.tsv', r=>`${r['Show Date']}|${r['Artist']}`);
      _potentialRows = await mergePrivateData(_potentialRows, 'potential_private.tsv', r=>`${r['Artist']}|${r['Date']}`);
    }

    renderOnThisDay([..._currentRows, ..._historyRows]);
    renderShows(_currentRows);
    renderHistory(_historyRows);
    renderPotential(_potentialRows, !!pat);
    renderTourHere(_tourhereRows);

    document.getElementById('fetchedAt').textContent = new Date().toLocaleTimeString();
  } catch(e){
    showToast('Load error: '+e.message);
    console.error(e);
  } finally {
    document.getElementById('refreshBtn').disabled = false;
  }
}

async function fetchHistoryFiles(){
  // List history/ directory and fetch each .tsv
  try {
    const pat = getPat();
    const headers = { Accept: 'application/vnd.github.v3+json' };
    if(pat) headers['Authorization'] = `token ${pat}`;
    const res = await fetch(`https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/data/history`, { headers });
    if(!res.ok) return [];
    const files = await res.json();
    const tsvFiles = files.filter(f=>f.name.endsWith('.tsv'));
    return Promise.all(tsvFiles.map(f=>ghFetch(`data/history/${f.name}`)));
  } catch(e){
    console.warn('fetchHistoryFiles failed:', e);
    return [];
  }
}

// ── Hat loading spinner ────────────────────────────────────────────────────
function hatLoadingHtml(){return'<div class="hat-loading"><img class="hat-loading-img" src="https://dan2bit.github.io/live-shows/static/brand-hat.png" alt=""><div class="loading loading-dots" style="animation:none">Loading</div></div>';}

// ── Init ───────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', ()=>{
  switchTab('shows');
  loadData();
});
