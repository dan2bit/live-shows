let OWNER='dan2bit',REPO='live-shows';
const CURRENT_PATH='data/live_shows_current.tsv',POTENTIAL_PATH='data/live_shows_potential.tsv';
let OWNER_PRIVATE='dan2bit',REPO_PRIVATE='live-shows-private';const CURRENT_PRIVATE_PATH='current_private.tsv',POTENTIAL_PRIVATE_PATH='potential_private.tsv';
const CUR_PRIVATE_FIELDS=['Seat Info / GA','Ticket Quantity','Face Value (per ticket)','Fees','Total Cost','Purchase Date','Food & Bev','Parking','Merch','Private Notes'];
const HISTORY_YEARS=[2021,2022,2023,2024,2025],PAT_KEY='ghpat_liveshows';
let currentRows=[],potentialRows=[],authed=false;
var historyData={};
HISTORY_YEARS.forEach(function(yr){historyData[yr]=null;});
var _now=new Date();
var _todayMmDd=String(_now.getMonth()+1).padStart(2,'0')+'-'+String(_now.getDate()).padStart(2,'0');
var _srchTimer=null;
var _allYearsLoaded=false;

// ── Config (#69) ───────────────────────────
// Per-fork personalization loaded from config.yaml at boot. Any missing key falls
// back to DEFAULT_CONFIG, so a failed/absent/invalid config never breaks the site.
const DEFAULT_CONFIG={site:{title:'live-shows',owner:'dan2bit',repo:'live-shows',private_owner:'dan2bit',private_repo:'live-shows-private'}};
var SITE_CONFIG=DEFAULT_CONFIG;
function _cfgMerge(base,over){
  var out=Object.assign({},base);
  for(var k in over){
    if(over[k]&&typeof over[k]==='object'&&!Array.isArray(over[k]))out[k]=_cfgMerge(base[k]||{},over[k]);
    else if(over[k]!==undefined&&over[k]!==null)out[k]=over[k];
  }
  return out;
}
async function loadConfig(){
  try{
    var res=await fetch('config.yaml?t='+Date.now(),{cache:'no-store'});
    if(!res.ok)throw new Error('config.yaml '+res.status);
    var parsed=(typeof jsyaml!=='undefined')?jsyaml.load(await res.text()):null;
    SITE_CONFIG=_cfgMerge(DEFAULT_CONFIG,parsed||{});
  }catch(e){console.warn('config load failed, using defaults:',e);SITE_CONFIG=DEFAULT_CONFIG;}
  window.SITE_CONFIG=SITE_CONFIG;
  return SITE_CONFIG;
}
// Resolve a config asset path to an absolute URL. Module-level (not closed over applyConfig)
// so loading interstitials can derive the brand image from site.brand_icon too. Relative
// paths expand to https://<owner>.github.io/<repo>/<path>; absolute paths pass through.
function _assetUrl(p,site){
  if(!p)return p;
  if(/^https?:\/\//.test(p))return p;
  site=site||(SITE_CONFIG&&SITE_CONFIG.site)||{};
  var base=(site.pages_base||('https://'+OWNER+'.github.io/'+REPO)).replace(/\/+$/,'');
  return base+'/'+String(p).replace(/^\/+/,'');
}
function applyConfig(cfg){
  cfg=cfg||SITE_CONFIG;
  var s=cfg.site||{};
  if(s.title){
    document.title=s.title;
    var st=document.querySelector('.site-title');
    if(st)st.textContent=s.title;
  }
  if(s.owner)OWNER=s.owner;
  if(s.repo)REPO=s.repo;
  if(s.private_owner)OWNER_PRIVATE=s.private_owner;
  if(s.private_repo)REPO_PRIVATE=s.private_repo;
  // Branding/identity (#69 phase 3). Relative asset paths are expanded to absolute
  // https://<owner>.github.io/<repo>/<path> URLs because relative asset URLs 404 on
  // this project-pages setup; s.pages_base overrides the derived base for custom domains.
  function _asset(p){return _assetUrl(p,s);}
  function _txt(sel,v){if(v==null)return;var el=document.querySelector(sel);if(el)el.textContent=v;}
  function _attr(sel,a,v){if(v==null)return;var el=document.querySelector(sel);if(el)el.setAttribute(a,v);}
  if(s.favicon){var fav=_asset(s.favicon);document.querySelectorAll('link[rel~="icon"]').forEach(function(l){l.setAttribute('href',fav);});}
  if(s.brand_icon)_attr('.hat-btn img','src',_asset(s.brand_icon));
  if(s.about_handle){_txt('.about-hero-handle',s.about_handle);_attr('.hat-btn','title','About '+s.about_handle);}
  if(s.about_tagline)_txt('.about-hero-tagline',s.about_tagline);
  if(s.about_text)_txt('#aboutModal .about-body p',s.about_text);
  if(s.about_hero_image)_attr('.about-hero-img','src',_asset(s.about_hero_image));
  if(s.about_hero_alt)_attr('.about-hero-img','alt',s.about_hero_alt);
  if(s.about_footer)_txt('#aboutModal .modal-actions span',s.about_footer);
  // about_links: list of {url,label} objects (#82). Rebuilt dynamically so a fork can add
  // or remove links by editing config alone. The static anchors in index.html are the
  // pre-JS fallback shown if config.yaml is absent or about_links is not a list.
  var al=cfg.about_links;
  if(Array.isArray(al)&&al.length){
    var box=document.querySelector('#aboutModal .about-links');
    if(box){
      box.innerHTML='';
      al.forEach(function(lnk){
        if(!lnk||!lnk.url)return;
        var a=document.createElement('a');
        a.className='about-link';a.href=lnk.url;a.target='_blank';
        a.textContent=lnk.label||lnk.url;
        var li=document.createElement('li');li.appendChild(a);box.appendChild(li);
      });
    }
  }
  // Tab labels (#82). Keys are data-tab IDs; replace the label text node, keep the badge span.
  var _tabs=cfg.tabs;
  if(_tabs&&typeof _tabs==='object'){
    Object.keys(_tabs).forEach(function(k){
      var el=document.querySelector('.tab[data-tab="'+k+'"]');
      if(el&&el.firstChild&&el.firstChild.nodeType===3)el.firstChild.nodeValue=_tabs[k]+' ';
    });
  }
  // Waiting / Fast-Track tab show-hide (features.fast_track, #82).
  if(!featureOn('fast_track')){
    var _wt=document.querySelector('.tab[data-tab="tourhere"]');if(_wt)_wt.style.display='none';
    var _wp=document.getElementById('panel-tourhere');if(_wp)_wp.style.display='none';
  }
}
// Feature flags (#82). A flag is ON unless config explicitly sets it to false, so a
// fork that omits the features block — or any single key — keeps full behavior.
function featureOn(name){var f=SITE_CONFIG.features;return !f||f[name]!==false;}
function dataBranch(){return(SITE_CONFIG.site&&SITE_CONFIG.site.data_branch)||'main';}
// #89 read-side preview override: ?dataref=<branch> (URL) > site.preview_data_branch
// (config) > '' = default branch. READS ONLY — write PUT bodies stay on dataBranch()
// (the staging pipeline); the two must never be conflated. Public repo only — the
// private sidecar always resolves from its own default branch.
function _dataRef(){
  try{var q=new URLSearchParams(location.search).get('dataref');if(q)return q.trim();}catch(e){}
  return(SITE_CONFIG.site&&SITE_CONFIG.site.preview_data_branch)||'';
}
// Merch badge threshold (#82): Face Value at/above which the MERCH badge shows.
function merchEventCap(){var m=SITE_CONFIG.merch;return m&&m.event_cap!=null?m.event_cap:100;}
// #87 — Group/Solo upcoming badge (bystander) + ticket-count (authed) visibility, per config.
// Group = the public `Group=Y` flag; Solo = its absence. `which` is 'badge' or 'count',
// `kind` is 'solo' or 'group'. Missing config defaults to group shown, solo hidden.
function displayOn(which,kind){var d=SITE_CONFIG.display,v=d&&d[which]&&d[which][kind];if(v==null)return kind==='group';return v===true||(''+v).trim().toLowerCase()==='yes';}
// Decision-stage display (#82). Stage KEYS are fixed in code (sort order, dropdown, CSS);
// only the display copy is configurable, and stage colors live in the theme block. Falls
// back to the built-in copy so a config without a stages block renders identically.
function stageHeader(key){
  var def={buy:{icon:'🟩',label:'Buy',tagline:'not purchased but probably going',sep:' — '},
           choose:{icon:'🟡',label:'Choose',tagline:'shows I am considering',sep:' — '},
           pass:{icon:'◯',label:'Pass',tagline:'considered, but not going',sep:' - '}}[key]||{sep:' — '};
  var d=(SITE_CONFIG.stages||{})[key]||{};
  var icon=d.icon!=null?d.icon:def.icon,label=d.label!=null?d.label:def.label,tagline=d.tagline!=null?d.tagline:def.tagline;
  return esc(icon)+' '+esc(label)+def.sep+esc(tagline);
}
// ── Theme (#71) ───────────────────────────
// HSL helpers for deriving _dim and _bg variants from a base color.
// A forker only needs to set the 5 base colors; triads are computed automatically.
// Explicit overrides (e.g. color_accent_dim) always win over computed values.
function _hexToHsl(hex){
  var r=parseInt(hex.slice(1,3),16)/255,g=parseInt(hex.slice(3,5),16)/255,b=parseInt(hex.slice(5,7),16)/255;
  var max=Math.max(r,g,b),min=Math.min(r,g,b),h,s,l=(max+min)/2;
  if(max===min){h=s=0;}else{var d=max-min;s=l>0.5?d/(2-max-min):d/(max+min);
    switch(max){case r:h=(g-b)/d+(g<b?6:0);break;case g:h=(b-r)/d+2;break;case b:h=(r-g)/d+4;break;}h/=6;}
  return[h*360,s*100,l*100];
}
function _hslToHex(h,s,l){
  h/=360;s/=100;l/=100;
  var r,g,b;
  if(s===0){r=g=b=l;}else{
    function hue2rgb(p,q,t){if(t<0)t+=1;if(t>1)t-=1;if(t<1/6)return p+(q-p)*6*t;if(t<1/2)return q;if(t<2/3)return p+(q-p)*(2/3-t)*6;return p;}
    var q=l<0.5?l*(1+s):l+s-l*s,p=2*l-q;
    r=hue2rgb(p,q,h+1/3);g=hue2rgb(p,q,h);b=hue2rgb(p,q,h-1/3);
  }
  return'#'+[r,g,b].map(function(x){return Math.round(x*255).toString(16).padStart(2,'0');}).join('');
}
function _deriveTriad(hex){
  var hsl=_hexToHsl(hex),h=hsl[0],s=hsl[1],l=hsl[2];
  var dim=_hslToHex(h,s,Math.max(l*0.48,8));
  var bg=_hslToHex(h,s*0.85,Math.max(l*0.16,5));
  return{base:hex,dim:dim,bg:bg};
}
function applyTheme(cfg){
  cfg=cfg||SITE_CONFIG;
  var t=cfg.theme;if(!t||typeof t!=='object'||!Object.keys(t).length)return;
  var root=document.documentElement.style;
  function set(v,k){if(v)root.setProperty(k,v);}
  // Chrome neutrals — explicit values only, no derivation
  set(t.color_bg,'--bg');set(t.color_surface,'--surface');set(t.color_surface_bright,'--surface-bright');
  set(t.color_border,'--border');set(t.color_border_bright,'--border-bright');
  set(t.color_text,'--text');set(t.color_text_muted,'--text-muted');set(t.color_text_dim,'--text-dim');
  // Semantic color triads — derive dim/bg if not explicitly overridden
  var pairs=[['color_accent','--amber'],['color_buy','--green'],['color_choose','--yellow'],
             ['color_sell','--sell'],['color_pass','--gray']];
  pairs.forEach(function(p){
    var base=t[p[0]];if(!base)return;
    var triad=_deriveTriad(base);
    set(base,p[1]);
    set(t[p[0]+'_dim']||triad.dim,p[1]+'-dim');
    set(t[p[0]+'_bg']||triad.bg,p[1]+'-bg');
  });
  // Show goal badge colors — iterate cfg.show_goals (#85 S3) and emit --<key> /
  // --<key>-dim / --<key>-bg CSS var triads. Auto-derived from goal.color via HSL
  // darkening (same _deriveTriad used for semantic colors above); a fork may also
  // provide explicit goal.color_dim / goal.color_bg overrides if the auto-derived
  // shades need tuning. A fork may add, remove, or edit any goal without CSS work.
  var goals=(cfg.show_goals&&cfg.show_goals.length)?cfg.show_goals:[];
  goals.forEach(function(g){
    if(!g||!g.key||!g.color)return;
    var triad=_deriveTriad(g.color);
    set(g.color,'--'+g.key);
    set(g.color_dim||triad.dim,'--'+g.key+'-dim');
    set(g.color_bg||triad.bg,'--'+g.key+'-bg');
  });
  // Status rows
  set(t.color_today_bg,'--today-bg');set(t.color_soon_bg,'--soon-bg');
  set(t.color_otd_bg,'--otd-bg');set(t.color_otd_border,'--otd-border');
  // Fonts — inject a <link> if config specifies a different font stack
  if(t.font_mono||t.font_sans){
    set(t.font_mono,'--mono');set(t.font_sans,'--sans');
    // If either font name differs from the IBM Plex defaults, swap the Google Fonts import
    var monoName=(t.font_mono||'').replace(/'/g,'').split(',')[0].trim();
    var sansName=(t.font_sans||'').replace(/'/g,'').split(',')[0].trim();
    var ibmMono='IBM Plex Mono',ibmSans='IBM Plex Sans';
    if(monoName&&monoName!==ibmMono||sansName&&sansName!==ibmSans){
      var families=[];
      if(monoName&&monoName!==ibmMono)families.push('family='+encodeURIComponent(monoName)+':wght@400;500');
      if(sansName&&sansName!==ibmSans)families.push('family='+encodeURIComponent(sansName)+':wght@400;500');
      if(families.length){
        var link=document.createElement('link');
        link.rel='stylesheet';
        link.href='https://fonts.googleapis.com/css2?'+families.join('&')+'&display=swap';
        document.head.appendChild(link);
      }
    }
  }
}

async function ghFetch(path,opts,owner,repo){
  opts=opts||{};
  var pat=localStorage.getItem(PAT_KEY);
  var headers={'Accept':'application/vnd.github.v3+json'};
  if(pat)headers['Authorization']='token '+pat;
  var url='https://api.github.com/repos/'+(owner||OWNER)+'/'+(repo||REPO)+'/contents/'+path;
  var _ref=_dataRef();   // #89: reads may target a preview branch (public repo only)
  if(_ref&&(owner||OWNER)===OWNER&&(repo||REPO)===REPO)url+='?ref='+encodeURIComponent(_ref);
  var res=await fetch(url,Object.assign({cache:'no-store'},opts,{headers:Object.assign(headers,opts.headers||{})}));
  if(!res.ok){
    var _em='GitHub API '+res.status+': '+res.statusText;
    try{var _eb=await res.json();if(_eb&&_eb.message&&_eb.message!=='Not Found')_em+=' — '+_eb.message;}catch(e){}
    if(_ref)_em+=' (dataref='+_ref+')';
    throw new Error(_em);
  }
  return res.json();
}
function _decodeB64(c){return decodeURIComponent(escape(atob(c.replace(/\n/g,''))));
}
async function mergePrivateData(){
  if(!authed||!featureOn('private_data'))return;
  // Sidecar joins normalize the Artist half of the key via _goalNorm (house identity
  // doctrine), so diacritic/case/encoding variants join anyway; any private row that
  // still matches nothing gets a console.warn — billing-name or date drift (the
  // Taj Mahal / Sierra Hull class, 2026-07-16) can't be bridged by normalization and
  // must be fixed in the sidecar. See EMAIL_WORKFLOWS Routine 1 verbatim-key rule.
  var _pk=function(a,d){return _goalNorm(a||'')+'␟'+(d||'').trim();};
  try{
    var cp=await ghFetch(CURRENT_PRIVATE_PATH,{},OWNER_PRIVATE,REPO_PRIVATE),cmap={},cseen={};
    parseTsv(_decodeB64(cp.content)).forEach(function(r){cmap[_pk(r['Artist'],r['Show Date'])]=r;});
    currentRows.forEach(function(r){var k=_pk(r['Artist'],r['Show Date']),p=cmap[k];if(p){cseen[k]=1;CUR_PRIVATE_FIELDS.forEach(function(f){if(p[f]!==undefined)r[f]=p[f];});}});
    Object.keys(cmap).forEach(function(k){if(!cseen[k])console.warn('current_private row matched no public show:',cmap[k]['Artist'],cmap[k]['Show Date']);});
  }catch(e){console.warn('private current merge skipped:',e.message);}
  try{
    var pp=await ghFetch(POTENTIAL_PRIVATE_PATH,{},OWNER_PRIVATE,REPO_PRIVATE),pmap={},pseen={};
    parseTsv(_decodeB64(pp.content)).forEach(function(r){pmap[_pk(r['Artist'],r['Date'])]=r;});
    potentialRows.forEach(function(r){var k=_pk(r['Artist'],r['Date']),p=pmap[k];if(p){pseen[k]=1;if(p['Private Notes']!==undefined)r['Private Notes']=p['Private Notes'];}});
    Object.keys(pmap).forEach(function(k){if(!pseen[k])console.warn('potential_private row matched no potential:',pmap[k]['Artist'],pmap[k]['Date']);});
  }catch(e){console.warn('private potential merge skipped:',e.message);}
}
async function _savePrivateSidecar(path,keyFields,keyVals,field,newVal){
  var pat=localStorage.getItem(PAT_KEY);if(!pat)throw new Error('no auth');
  var fd=await ghFetch(path,{},OWNER_PRIVATE,REPO_PRIVATE);
  var raw=_decodeB64(fd.content);
  var headers=raw.split('\n')[0].split('\t').map(function(h){return h.trim();});
  var rows=parseTsv(raw);
  var fi=rows.findIndex(function(r){return keyFields.every(function(k){var a=(r[k]||''),b=(keyVals[k]||'');return k==='Artist'?_goalNorm(a)===_goalNorm(b):a.trim()===b.trim();});});
  if(fi<0){var nr={};headers.forEach(function(h){nr[h]='';});keyFields.forEach(function(k){nr[k]=keyVals[k]||'';});nr[field]=newVal;rows.push(nr);}else{rows[fi][field]=newVal;}
  var res=await fetch('https://api.github.com/repos/'+OWNER_PRIVATE+'/'+REPO_PRIVATE+'/contents/'+path,{method:'PUT',headers:{'Accept':'application/vnd.github.v3+json','Authorization':'token '+pat,'Content-Type':'application/json'},body:JSON.stringify({message:path+': update '+(keyVals['Artist']||'')+' '+field,content:btoa(unescape(encodeURIComponent(serializeTsv(rows,headers)))),sha:fd.sha})});
  if(!res.ok)throw new Error(await res.text());
}
function parseTsv(text){
  var lines=text.trim().replace(/\r\n/g,'\n').replace(/\r/g,'\n').split('\n');
  var headers=lines[0].split('\t').map(function(h){return h.trim();});
  return lines.slice(1).map(function(line){
    var vals=line.split('\t');
    while(vals.length<headers.length)vals.push('');
    var obj={};
    headers.forEach(function(h,i){obj[h]=(vals[i]||'').trim();});
    return obj;
  });
}
function serializeTsv(rows,headers){
  return[headers.join('\t')].concat(rows.map(function(r){return headers.map(function(h){return r[h]||'';}).join('\t');})).join('\n')+'\n';
}
var DAYS=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
var MONTHS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function parseISODate(s){var m=(s||'').match(/^(\d{4})-(\d{2})-(\d{2})/);return m?new Date(+m[1],+m[2]-1,+m[3]):null;}
function _dateFmt(){return(SITE_CONFIG.display&&SITE_CONFIG.display.date_format)||'mon_day';}
function formatShowDate(s){var d=parseISODate(s);if(!d)return s;var mo=d.getMonth(),dy=d.getDate(),f=_dateFmt();if(f==='day_mon')return dy+' '+MONTHS[mo];if(f==='m_d')return(mo+1)+'/'+dy;if(f==='d_m')return dy+'/'+(mo+1);return MONTHS[mo]+' '+dy;}
function formatShowDateYear(s){var d=parseISODate(s);if(!d)return s;var mo=d.getMonth(),dy=d.getDate(),yr=d.getFullYear(),f=_dateFmt();if(f==='day_mon')return dy+' '+MONTHS[mo]+' '+yr;if(f==='m_d')return(mo+1)+'/'+dy+'/'+yr;if(f==='d_m')return dy+'/'+(mo+1)+'/'+yr;return MONTHS[mo]+' '+dy+', '+yr;}
function dayOfWeek(s){var d=parseISODate(s);return d?DAYS[d.getDay()]:'';
}
function daysFromNow(s){var d=parseISODate(s);if(!d)return 999;var now=new Date();now.setHours(0,0,0,0);return Math.floor((d-now)/86400000);}
function isOtdMatch(s){var m=(s||'').match(/^\d{4}-(\d{2}-\d{2})/);return m?m[1]===_todayMmDd:false;}
function gcalUrl(artist){var now=new Date(),pad=function(n){return String(n).padStart(2,'0');};return'https://calendar.google.com/calendar/r/search?q='+encodeURIComponent(artist)+'&start='+now.getFullYear()+pad(now.getMonth()+1)+pad(now.getDate())+'&end='+(now.getFullYear()+1)+pad(now.getMonth()+1)+pad(now.getDate());}
function esc(s){return(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
// ── Venue identity (#189) ─────────────────────────────
// Shared resolution over data/venue_aliases.tsv (true renames only — case /
// leading-"The" / punctuation variants fold in _venueKey) and data/venues.tsv
// (canonical names + Short Name display column; blank Short Name = identity).
// Chain everywhere: first-comma-truncate -> _venueKey -> alias -> canonical.
// Loaded once per loadData; missing files degrade to plain truncation.
// Python twins: scripts/check_box_office.py and
// tools/youtube/youtube_create_playlists.py — keep the three in step.
var VENUE_ALIASES={},VENUE_SHORT_NAMES={};
async function loadVenueIdentity(){
  VENUE_ALIASES={};VENUE_SHORT_NAMES={};
  try{
    var ar=await ghFetch('data/venue_aliases.tsv');
    parseTsv(_decodeB64(ar.content)).forEach(function(r){
      var a=_venueKey((r['Alias']||'').split(',')[0]),c=(r['Venue Name']||'').trim();
      if(a&&c)VENUE_ALIASES[a]=c;
    });
  }catch(e){/* no alias file -> key-fold only */}
  try{
    var vr=await ghFetch('data/venues.tsv');
    parseTsv(_decodeB64(vr.content)).forEach(function(r){
      var c=_venueKey(r['Venue Name']),s=(r['Short Name']||'').trim();
      if(c&&s)VENUE_SHORT_NAMES[c]=s;
    });
  }catch(e){/* no venues file -> no short names */}
}
function _venueCanonical(v){var t=String(v||'').split(',')[0].trim();return VENUE_ALIASES[_venueKey(t)]||t;}
function _venueCanonKey(v){return _venueKey(_venueCanonical(v));}
function shortVenueName(full){var c=_venueCanonical(full);return VENUE_SHORT_NAMES[_venueKey(c)]||c;}

// ── On This Day ──────────────────────────────
// Renders the On-This-Day strip from already-loaded historyData (no fetch); reveals the
// strip, which starts hidden (index.html) until History is first opened. Called by loadAllHistory.
// #148 — "On This Day" carousel: show one match at a time (newest first), with a trailing
// ‹ dots › control when >1 show shares today's month/day. The total goes in the label; the
// visible row's ♫/▶ links render exactly as before. State + helpers below.
var _otdMatches=[],_otdIndex=0;
function _otdItemHtml(r){
  var year=(r['Show Date']||'').slice(0,4),artist=esc(r['Artist']||''),venue=esc((r['Venue']||'').split(',')[0].trim());
  var setlist=r['Setlist.fm URL']||'',playlist=r['Playlist URL']||'';
  var links=(setlist?'<a class="icon-link" href="'+esc(setlist)+'" target="_blank" title="Setlist.fm">♫</a>':'')+(playlist?'<a class="icon-link" href="'+esc(playlist)+'" target="_blank" title="YouTube playlist">▶</a>':'');
  return'<span class="otd-item"><span class="otd-year">'+year+'</span><span class="otd-artist">'+artist+'</span><span class="otd-sep">&middot;</span><span class="otd-venue">'+venue+'</span>'+(links?'<span class="otd-links">'+links+'</span>':'')+'</span>';
}
function _renderOtdItem(){
  var el=document.getElementById('otdItems');if(!el||!_otdMatches.length)return;
  var n=_otdMatches.length;if(_otdIndex<0||_otdIndex>=n)_otdIndex=0;
  var nav='';
  if(n>1){
    var dots='';for(var i=0;i<n;i++)dots+='<span class="otd-dot'+(i===_otdIndex?' active':'')+'"></span>';
    nav='<span class="otd-nav"><button type="button" class="otd-nav-btn" onclick="otdStep(-1)" aria-label="Previous show" title="Previous">&#8249;</button><span class="otd-dots">'+dots+'</span><button type="button" class="otd-nav-btn" onclick="otdStep(1)" aria-label="Next show" title="Next">&#8250;</button></span>';
  }
  el.innerHTML=_otdItemHtml(_otdMatches[_otdIndex])+nav;
}
function otdStep(delta){var n=_otdMatches.length;if(!n)return;_otdIndex=(_otdIndex+delta+n)%n;_renderOtdItem();}
function renderOnThisDay(){
  var el=document.getElementById('otdItems');if(!el)return;
  var matches=[];
  HISTORY_YEARS.forEach(function(yr){(historyData[yr]||[]).forEach(function(r){if((r['Show Date']||'').trim().endsWith(_todayMmDd))matches.push(r);});});
  matches.sort(function(a,b){return(b['Show Date']||'').localeCompare(a['Show Date']||'');});
  var strip=document.querySelector('.on-this-day');if(strip)strip.style.display='';
  var cnt=document.getElementById('otdCount');if(cnt)cnt.textContent=matches.length>1?' ('+matches.length+')':'';
  _otdMatches=matches;_otdIndex=0;
  if(!matches.length){el.innerHTML='<span class="otd-none">no shows on this day</span>';return;}
  _renderOtdItem();
}

// ── Badges ──────────────────────────────────────────────
function ticketLabel(access){
  var a=(access||'').toLowerCase();
  if(a.includes('axs'))return['AXS',false];if(a.includes('ticketmaster'))return['TM',false];
  if(a.includes('opendate'))return['Opendate',false];if(a.includes('eventbrite'))return['Eventbrite',false];
  if(a.includes('eventim')||a.includes('see tickets'))return['Eventim',false];
  if(a.includes('paper'))return['PAPER',true];if(a.includes('freshtix'))return['Freshtix',false];
  return access?[access.split(' ')[0],false]:[null,false];
}
// #186 — 🏣 badge is driven by the explicit Box Office flag on Buy/Choose potentials
// plus a venue match against the upcoming row, not by guessing at note phrasing.
// Venue keys fold case, a leading "The", and punctuation ("Birchmere" == "The
// Birchmere"); differently-worded venue names won't match — keep names consistent.
function _venueKey(v){return String(v||'').toLowerCase().replace(/^the\s+/,'').replace(/[^a-z0-9 ]+/g,' ').replace(/\s+/g,' ').trim();}
function _boxOfficeVenueKeys(){
  var s={};
  potentialRows.forEach(function(r){
    if((r['Box Office']||'').trim().toUpperCase()!=='Y')return;
    var dec=(r['Decision']||'').toLowerCase();
    if(!(dec.indexOf('buy')===0||dec.indexOf('choose')===0))return;
    var k=_venueCanonKey(r['Venue']);if(k)s[k]=1;
  });
  return s;
}
function buildBadges(row){
  if(!row['Ticket Access']&&!row['Face Value (per ticket)'])return'';
  var notes=(row['Notes / Memories']||'').toLowerCase(),pvt=(row['Private Notes']||'').toLowerCase(),seat=(row['Seat Info / GA']||'').toLowerCase(),access=(row['Ticket Access']||'').toLowerCase(),all=notes+' '+pvt+' '+seat+' '+access;
  var isVip=(row['VIP']||'').trim().toUpperCase()==='Y',isWT=(row['Venue Name']||'').includes('Wolf Trap Filene');
  var fv=parseFloat((row['Face Value (per ticket)']||'').replace(/[^0-9.]/g,''))||0;
  var badges=[],tl=ticketLabel(row['Ticket Access']||''),label=tl[0],isPaper=tl[1];
  if(label)badges.push('<span class="badge '+(isPaper?'badge-paper':'badge-ticket')+'">'+esc(label)+'</span>');
  if(isVip)badges.push('<span class="badge badge-vip">⭐ VIP</span>');
  if(!isVip&&!isWT&&fv>=merchEventCap())badges.push('<span class="badge badge-merch">💸 MERCH</span>');
  if(_boxOfficeVenueKeys()[_venueCanonKey(row['Venue Name'])])badges.push('<span class="badge badge-boxoffice" title="A flagged potential at this venue — buy at the box office while you\'re there">🏣 BOX OFFICE</span>');
  return badges.length?'<div class="badges">'+badges.join('')+'</div>':'';
}
function seatTypeBadge(seatType){var s=(seatType||'').toLowerCase();if(!s)return'';return'<span class="badge badge-seat">'+(s.indexOf('ga')>-1?'GA':'Seated')+'</span>';}
function publicBadges(row){var b=[];if((row['VIP']||'').trim().toUpperCase()==='Y')b.push('<span class="badge badge-vip">⭐ VIP</span>');var isGroup=(row['Group']||'').trim().toUpperCase()==='Y';if(isGroup){if(displayOn('badge','group'))b.push('<span class="badge badge-group">👥 Group</span>');}else if(displayOn('badge','solo'))b.push('<span class="badge badge-solo">🧍 Solo</span>');return b.length?'<div class="badges">'+b.join('')+'</div>':'';}

// ── Show-goal badges (#140 / #85 S4) ─────────────────────
// Config-driven goal badges. Iterates SITE_CONFIG.show_goals; event_log goals join
// client-side against the small data/show_goals/*.tsv signature + eligibility files
// loaded by loadGoalData(). Replicates build_artist_index.py credit_targets()+norm()
// so client and builder agree. Degrades to nothing when show_goals is empty or the
// goal folder is absent (#85 exit criterion). No styles.css needed — colors come from
// the --<key>/-dim/-bg CSS vars emitted by applyTheme().
var GOAL_DATA=null;
function _goalNorm(s){
  if(!s)return'';
  s=String(s).trim();
  var m=s.match(/^(.*),\s+(the|a|an)$/i);if(m)s=m[2]+' '+m[1];
  s=s.normalize('NFKD').replace(/[̀-ͯ]/g,'').toLowerCase();
  s=s.replace(/^\s*(the|a|an)\s+/,'').replace(/[^a-z0-9 ]+/g,' ').replace(/\s+/g,' ').trim();
  return s;
}
function _goalCreditTargets(signer,attribution){
  var a=(attribution||'').trim(),al=a.toLowerCase(),targets=signer?[signer]:[];
  if(al.indexOf('of ')===0){var band=a.slice(3).trim();if(band)targets.push(band);}
  else if(al.slice(-6)===' entry'){var alias=a.slice(0,a.length-6).trim();if(alias)targets.push(alias);}
  return targets;
}
// #150 — bill-name decomposition for the goal join. A row is often billed under a compound
// or variant name ("Victor Wooten & The Wooten Brothers", "Maggie Rose Band") while the
// eligibility/signature files are keyed on the tracked entity ("The Wooten Brothers",
// "Maggie Rose"). Returns the exact key first, then component fallbacks — exact always wins.
// Separators are explicit; no fuzzy matching (#150 non-goal). The trailing-" Band" drop
// mirrors surface_forms() in scripts/build_recommend_index.py, the house rule for that same
// variant. Python twin: bill_keys() in scripts/audit_goal_badges.py — keep the two in step.
var _GOAL_BILL_SEP=/\s+(?:&|and his|and her|and|w\/|feat\.?|featuring|with)\s+|\s*,\s*/i;
function _goalBillKeys(name){
  var base=_goalNorm(name),keys=base?[base]:[];
  if(!name)return keys;
  String(name).split(_GOAL_BILL_SEP).forEach(function(p){
    p=(p||'').trim();if(!p)return;
    [p,p.replace(/\s+band$/i,'').trim()].forEach(function(v){
      var k=_goalNorm(v);if(k&&keys.indexOf(k)<0)keys.push(k);
    });
  });
  return keys;
}
function _goalEventList(){var g=SITE_CONFIG.show_goals;return(g&&g.length?g:[]).filter(function(x){return x&&x.key&&/^event_log:/.test(x.source||'');});}
async function loadGoalData(){
  GOAL_DATA={};
  var goals=_goalEventList();if(!goals.length)return;
  await Promise.all(goals.map(async function(g){
    // #154 — `signed` is per-artist (any date); `completed` stays per-artist+date. Forward-looking
    // rows use `signed` to suppress a goal that's already been obtained.
    var d={completed:{},eligible:{},signed:{}},file=(g.source||'').replace(/^event_log:/,'').trim();
    try{
      var res=await ghFetch('data/show_goals/'+file+'.tsv');
      parseTsv(_decodeB64(res.content)).forEach(function(r){
        var signer=(r['signer']||'').trim(),date=(r['show_date']||'').trim();
        if(!signer||!date)return;
        _goalCreditTargets(signer,r['attribution']).forEach(function(t){var k=_goalNorm(t);if(!k)return;d.completed[k+'␟'+date]=1;d.signed[k]=1;});
      });
    }catch(e){/* missing signatures -> no completions */}
    if(g.eligibility){
      try{
        var er=await ghFetch('data/show_goals/'+g.eligibility+'.tsv');
        parseTsv(_decodeB64(er.content)).forEach(function(r){
          var k=_goalNorm(r['Artist']);if(!k)return;
          var v=(r['Eligible']||r['Hat Eligible']||'').trim().toLowerCase();if(v==='yes')d.eligible[k]=1;
        });
      }catch(e){/* missing eligibility -> no planned */}
    }
    GOAL_DATA[g.key]=d;
  }));
}
function _goalBadgeSpans(artist,showDate,isUpcoming){
  if(!GOAL_DATA)return'';
  var goals=_goalEventList();if(!goals.length)return'';
  var keys=_goalBillKeys(artist),sd=showDate||'',out='';
  goals.forEach(function(g){
    var d=GOAL_DATA[g.key];if(!d)return;
    var completed=keys.some(function(k){return !!d.completed[k+'␟'+sd];});
    // #154 — eligibility answers "meets the criteria", not "still needed". Once the autograph
    // exists for this goal (from any past show), don't advertise it as planned on a future row;
    // that badge belongs only on the row where it was obtained. Per-goal, so a signed hat never
    // hides an unsigned book.
    var signed=keys.some(function(k){return !!d.signed[k];});
    var state=completed?'completed':(isUpcoming&&!signed&&keys.some(function(k){return !!d.eligible[k];})?'planned':'');
    if(!state)return;
    var key=g.key,label=esc(g.label||g.key),icon=g.icon||'';
    var style=state==='completed'
      ?'background:var(--'+key+'-bg);color:var(--'+key+');border:1px solid var(--'+key+'-dim)'
      :'background:transparent;color:var(--'+key+'-dim);border:1px dashed var(--'+key+'-dim);opacity:.85';
    out+='<span class="badge goal-'+key+' goal-'+state+'" style="'+style+'" title="'+label+(state==='planned'?' — planned':'')+'">'+icon+' '+label+'</span>';
  });
  return out;
}
function rowGoalBadges(artist,showDate,isUpcoming){var s=_goalBadgeSpans(artist,showDate,isUpcoming);return s?'<div class="badges">'+s+'</div>':'';}

// ── Artist-name modal triggers (#107 P2) ─────────────────
// Any artist name in a list becomes a keyboard-accessible button that opens the
// artist modal (openArtistModal, artist-modal.js) via the delegated handler below.
// Names not in the index render a graceful minimal card. Multi-artist support /
// seen-with strings (" / "-separated, optional " + more") wrap each name.
function artistLink(name){name=(name||'').trim();if(!name)return'';return'<button type="button" class="artist-link" data-artist="'+esc(name)+'">'+esc(name)+'</button>';}
function artistNames(str){
  str=(str||'').trim();if(!str)return'';
  var more='';var m=str.match(/\s*\+\s*more\s*$/i);if(m){more='<span class="cell-support-more"> + more</span>';str=str.slice(0,m.index);}
  return str.split(' / ').map(function(p){return artistLink(p);}).filter(Boolean).join(' / ')+more;
}

// #150 — support acts carry their own goal badges, rendered inline beside each name rather
// than merged into the headliner's badge cluster, so it stays clear whose badge it is.
// Same " / " split and "+ more" handling as artistNames.
function supportGoalNames(str,showDate,isUpcoming){
  str=(str||'').trim();if(!str)return'';
  var more='';var m=str.match(/\s*\+\s*more\s*$/i);if(m){more='<span class="cell-support-more"> + more</span>';str=str.slice(0,m.index);}
  return str.split(' / ').map(function(p){
    p=(p||'').trim();if(!p)return'';
    var b=_goalBadgeSpans(p,showDate,isUpcoming);
    return artistLink(p)+(b?' '+b:'');
  }).filter(Boolean).join(' / ')+more;
}

// ── setlistIconHtml helper ──────────────────────
function setlistIconHtml(s){
  if(!s||s==='-')return'';
  if(s.startsWith('MULTI:')){var key=s.slice(6);return'<button class="icon-link" style="background:none;border:none;cursor:pointer;padding:0;font-family:inherit;font-size:14px;" onclick="openMultisetModal(\''+key+'\')" title="Setlists">♫</button>';}
  return'<a class="icon-link" href="'+esc(s)+'" target="_blank" title="Setlist.fm">♫</a>';
}

// ── Schema normalization ───────────────────────
function normalizeRow(row){
  function cleanUrl(v){var s=(v||'').trim();return(s===''||s==='-')?'':s;}
  return{
    artist:row['Artist']||'',
    support:row['Supporting Artist']||row['Supporting Acts']||'',
    venueName:row['Venue Name']||(row['Venue']||'').split(',')[0].trim(),
    showDate:row['Show Date']||'',
    notes:row['Notes / Memories']||'',
    pvtNotes:row['Private Notes']||'',
    setlist:cleanUrl(row['Setlist.fm URL']),
    playlist:cleanUrl(row['Playlist URL']),
    photo:cleanUrl(row['Photo URL']),
    totalCost:row['Total Cost']||'',
  };
}

// ── Total spend helper ───────────────────────────
function totalSpend(row){
  var fields=['Total Cost','Food & Bev','Parking','Merch'];
  var sum=fields.reduce(function(acc,f){
    var v=parseFloat((row[f]||'').replace(/[^0-9.]/g,''));
    return acc+(isNaN(v)?0:v);
  },0);
  return sum>0?'$'+sum.toFixed(2):'';
}

// ── Inline notes editing ──────────────────────
function makeEditBtn(cellId,fileKey,rowIdx,field,label){
  return'<button class="notes-edit-btn" title="Edit '+label+'" onclick="startEdit(\''+cellId+'\',\''+fileKey+'\','+rowIdx+',\''+field+'\')">&#9998;</button>';
}
function _fieldAlternate(fileKey,field){
  if(fileKey==='current'){
    if(field==='Notes / Memories')return'Private Notes';
    if(field==='Private Notes')return'Notes / Memories';
  }
  if(fileKey==='potential'){
    if(field==='Notes')return'Private Notes';
    if(field==='Private Notes')return'Notes';
  }
  return null;
}
function _fieldLabel(field){
  if(field==='Notes / Memories')return'Public';
  if(field==='Private Notes')return'Private';
  if(field==='Notes')return'Public';
  return field;
}
function switchEditField(cellId,fileKey,rowIdx,field){
  var ta=document.getElementById('ta-'+cellId);if(!ta)return;
  var alt=_fieldAlternate(fileKey,field);if(!alt)return;
  var altVal='';
  if(fileKey==='current')altVal=(currentRows[rowIdx]||{})[alt]||'';
  else if(fileKey==='potential')altVal=(potentialRows[rowIdx]||{})[alt]||'';
  ta.value=altVal;
  ta.focus();ta.setSelectionRange(ta.value.length,ta.value.length);
  var saveBtn=document.getElementById('savebtn-'+cellId);
  var switchBtn=document.getElementById('switchbtn-'+cellId);
  var lbl=document.getElementById('fieldlbl-'+cellId);
  if(saveBtn)saveBtn.setAttribute('onclick','saveEdit(\''+cellId+'\',\''+fileKey+'\','+rowIdx+',\''+alt+'\')');
  if(switchBtn)switchBtn.setAttribute('onclick','switchEditField(\''+cellId+'\',\''+fileKey+'\','+rowIdx+',\''+alt+'\')');
  if(switchBtn)switchBtn.textContent='→ '+_fieldLabel(field);
  if(lbl)lbl.textContent=_fieldLabel(alt);
}
function startEdit(cellId,fileKey,rowIdx,field){
  var cell=document.getElementById(cellId);if(!cell)return;
  var current='';
  if(fileKey==='current'){current=(currentRows[rowIdx]||{})[field]||'';}
  else if(fileKey==='potential'){current=(potentialRows[rowIdx]||{})[field]||'';}
  else if(fileKey==='fasttrack'){current=(fastTrackRows[rowIdx]||{})[field]||'';}
  else if(fileKey.startsWith('history:')){var yr=parseInt(fileKey.split(':')[1]);current=((historyData[yr]||[])[rowIdx]||{})[field]||'';}
  var ind='ind-'+cellId;
  var alt=_fieldAlternate(fileKey,field);
  var switchHtml=alt?'<button class="notes-switch-btn" id="switchbtn-'+cellId+'" onclick="switchEditField(\''+cellId+'\',\''+fileKey+'\','+rowIdx+',\''+field+'\')">'+'→ '+_fieldLabel(alt)+'</button>':'';
  var labelHtml=alt?'<span class="notes-field-label" id="fieldlbl-'+cellId+'">'+_fieldLabel(field)+'</span>':'';
  cell.innerHTML='<div class="notes-edit-wrap">'
    +labelHtml
    +'<textarea class="notes-textarea" id="ta-'+cellId+'" rows="3">'+esc(current)+'</textarea>'
    +'<div class="notes-edit-actions">'
    +'<button class="notes-save-btn" id="savebtn-'+cellId+'" onclick="saveEdit(\''+cellId+'\',\''+fileKey+'\','+rowIdx+',\''+field+'\')">Save</button>'
    +'<button class="notes-cancel-btn" onclick="cancelEdit(\''+cellId+'\',\''+fileKey+'\','+rowIdx+',\''+field+'\')">Cancel</button>'
    +'<span class="notes-save-ind save-indicator" id="'+ind+'"></span>'
    +switchHtml
    +'</div></div>';
  var ta=document.getElementById('ta-'+cellId);
  if(ta){ta.focus();ta.setSelectionRange(ta.value.length,ta.value.length);}
}
function cancelEdit(cellId,fileKey,rowIdx,field){
  if(fileKey==='current'){renderShows();}
  else if(fileKey==='potential'){renderPotential();}
  else if(fileKey==='fasttrack'){renderTourHere();}
  else if(fileKey.startsWith('history:')){
    var yr=parseInt(fileKey.split(':')[1]);
    var panel=document.getElementById('inner-hist-'+yr);
    if(panel){panel.innerHTML=renderHistoryYear(yr);requestAnimationFrame(revealToggles);}
  }
}
async function saveEdit(cellId,fileKey,rowIdx,field){
  var ta=document.getElementById('ta-'+cellId);if(!ta)return;
  var newVal=ta.value;
  var ind=document.getElementById('ind-'+cellId);
  if(ind){ind.textContent='…';ind.className='notes-save-ind save-indicator';}
  var pat=localStorage.getItem(PAT_KEY);if(!pat){if(ind){ind.textContent='✗ no auth';ind.className='notes-save-ind save-err';}return;}
  try{
    if(fileKey==='current'&&field==='Private Notes'){
      await _savePrivateSidecar(CURRENT_PRIVATE_PATH,['Show Date','Artist'],{'Show Date':currentRows[rowIdx]['Show Date'],'Artist':currentRows[rowIdx]['Artist']},field,newVal);
      currentRows[rowIdx][field]=newVal;
    } else if(fileKey==='current'){
      var fd=await ghFetch(CURRENT_PATH);
      var raw=decodeURIComponent(escape(atob(fd.content.replace(/\n/g,''))));
      var headers=raw.split('\n')[0].split('\t').map(function(h){return h.trim();});
      var rows=parseTsv(raw);
      rows[rowIdx][field]=newVal;currentRows[rowIdx][field]=newVal;
      var msgArtist=rows[rowIdx]['Artist']||'show';
      var res=await fetch('https://api.github.com/repos/'+OWNER+'/'+REPO+'/contents/'+CURRENT_PATH,{method:'PUT',headers:{'Accept':'application/vnd.github.v3+json','Authorization':'token '+pat,'Content-Type':'application/json'},body:JSON.stringify({message:'current: update '+msgArtist+' '+field,content:btoa(unescape(encodeURIComponent(serializeTsv(rows,headers)))),sha:fd.sha,branch:dataBranch()})});
      if(!res.ok)throw new Error(await res.text());
    } else if(fileKey==='potential'&&field==='Private Notes'){
      await _savePrivateSidecar(POTENTIAL_PRIVATE_PATH,['Artist','Date'],{'Artist':potentialRows[rowIdx]['Artist'],'Date':potentialRows[rowIdx]['Date']},field,newVal);
      potentialRows[rowIdx][field]=newVal;
    } else if(fileKey==='potential'){
      var fd=await ghFetch(POTENTIAL_PATH);
      var raw=decodeURIComponent(escape(atob(fd.content.replace(/\n/g,''))));
      var headers=raw.split('\n')[0].split('\t').map(function(h){return h.trim();});
      var rows=parseTsv(raw);
      var _pt=potentialRows[rowIdx],_pfi=rows.findIndex(function(r){return r['Artist']===_pt['Artist']&&r['Date']===_pt['Date'];});
      if(_pfi<0)throw new Error('Potential row not found: '+(_pt['Artist']||''));
      rows[_pfi][field]=newVal;potentialRows[rowIdx][field]=newVal;
      var msgArtist=rows[_pfi]['Artist']||'show';
      var res=await fetch('https://api.github.com/repos/'+OWNER+'/'+REPO+'/contents/'+POTENTIAL_PATH,{method:'PUT',headers:{'Accept':'application/vnd.github.v3+json','Authorization':'token '+pat,'Content-Type':'application/json'},body:JSON.stringify({message:'potential: update '+msgArtist+' '+field,content:btoa(unescape(encodeURIComponent(serializeTsv(rows,headers)))),sha:fd.sha,branch:dataBranch()})});
      if(!res.ok)throw new Error(await res.text());
    } else if(fileKey==='fasttrack'){
      var fd=await ghFetch(FAST_TRACK_PATH);
      var raw=decodeURIComponent(escape(atob(fd.content.replace(/\n/g,''))));
      var headers=raw.split('\n')[0].split('\t').map(function(h){return h.trim();});
      var rows=parseFastTrack(raw);
      rows[rowIdx][field]=newVal;fastTrackRows[rowIdx][field]=newVal;
      var msgArtist=rows[rowIdx]['Artist']||'artist';
      var res=await fetch('https://api.github.com/repos/'+OWNER+'/'+REPO+'/contents/'+FAST_TRACK_PATH,{method:'PUT',headers:{'Accept':'application/vnd.github.v3+json','Authorization':'token '+pat,'Content-Type':'application/json'},body:JSON.stringify({message:'fast_track: update '+msgArtist+' '+field,content:btoa(unescape(encodeURIComponent(serializeFastTrack(rows,headers)))),sha:fd.sha,branch:dataBranch()})});
      if(!res.ok)throw new Error(await res.text());
    } else if(fileKey.startsWith('history:')){
      var yr=parseInt(fileKey.split(':')[1]);
      var histPath='data/history/'+yr+'.tsv';
      var fd=await ghFetch(histPath);
      var raw=decodeURIComponent(escape(atob(fd.content.replace(/\n/g,''))));
      var headers=raw.split('\n')[0].split('\t').map(function(h){return h.trim();});
      var rows=parseTsv(raw);
      rows[rowIdx][field]=newVal;historyData[yr][rowIdx][field]=newVal;
      var msgArtist=rows[rowIdx]['Artist']||'show';
      var res=await fetch('https://api.github.com/repos/'+OWNER+'/'+REPO+'/contents/'+histPath,{method:'PUT',headers:{'Accept':'application/vnd.github.v3+json','Authorization':'token '+pat,'Content-Type':'application/json'},body:JSON.stringify({message:'history: update '+msgArtist+' '+yr+' '+field,content:btoa(unescape(encodeURIComponent(serializeTsv(rows,headers)))),sha:fd.sha,branch:dataBranch()})});
      if(!res.ok)throw new Error(await res.text());
    }
    if(ind){ind.textContent='✓';ind.className='notes-save-ind save-ok';}
    setTimeout(function(){cancelEdit(cellId,fileKey,rowIdx,field);},600);
  }catch(e){
    console.error(e);
    if(ind){ind.textContent='✗ '+e.message.slice(0,40);ind.className='notes-save-ind save-err';}
  }
}

// ── Upcoming rows ──────────────────────────────────
function renderUpcomingRowBystander(row,idx){
  var days=daysFromNow(row['Show Date']),cls=days<=1?'row-today':days<=7?'row-soon':'';
  var pn=esc(row['Notes / Memories']||'');
  var vh=row['Venue Event URL']?'<a href="'+esc(row['Venue Event URL'])+'" target="_blank">'+esc(row['Venue Name'])+'</a>':esc(row['Venue Name']);
  var sb=seatTypeBadge(row['Seat Type']||'');
  var mv=row['Venue Name']?'<div class="cell-venue-mobile">'+esc(shortVenueName(row['Venue Name']))+(sb?' '+sb:'')+'</div>':'';
  return'<tr class="'+cls+'"><td class="cell-date"><span class="date-text">'+formatShowDate(row['Show Date'])+'</span><span class="day-of-week">'+dayOfWeek(row['Show Date'])+'</span></td>'
    +'<td><div class="cell-artist">'+artistLink(row['Artist'])+'</div>'+(row['Supporting Artist']?'<div class="cell-support">w/ '+supportGoalNames(row['Supporting Artist'],row['Show Date'],true)+'</div>':'')+mv+publicBadges(row)+rowGoalBadges(row['Artist'],row['Show Date'],true)+'</td>'
    +'<td class="cell-venue col-support">'+vh+'</td><td class="cell-seat col-seat">'+sb+'</td>'
    +'<td class="cell-notes">'+(pn?'<div class="notes-text">'+pn+'</div>':'')+'</td></tr>';
}
function renderUpcomingRowAuthed(row,idx,origIdx){
  var days=daysFromNow(row['Show Date']),cls=days<=1?'row-today':days<=7?'row-soon':'';
  var pn=row['Notes / Memories']||'',pvt=row['Private Notes']||'';
  var fn=pvt?pn+(pn?' · ':'')+pvt:pn,fne=esc(fn);
  var vh=row['Venue Event URL']?'<a href="'+esc(row['Venue Event URL'])+'" target="_blank">'+esc(row['Venue Name'])+'</a>':esc(row['Venue Name']);
  var seat=esc(row['Seat Info / GA']||'');
  var isGroup=(row['Group']||'').trim().toUpperCase()==='Y',showCount=displayOn('count',isGroup?'group':'solo');
  var cal=featureOn('calendar_integration')?'<a class="icon-link" href="'+gcalUrl(row['Artist'])+'" target="_blank" title="Google Calendar"> 📅</a>':'';
  var mv=row['Venue Name']?'<div class="cell-venue-mobile">'+esc(shortVenueName(row['Venue Name']))+(seat?' · '+seat:'')+'</div>':'';
  var cellId='cell-up-'+idx;
  var nh=fne?'<div class="notes-text collapsible" id="n-up-'+idx+'" onclick="toggleNote(this,\'nt-up-'+idx+'\')">'+''+fne+'</div><span class="notes-toggle" id="nt-up-'+idx+'" onclick="toggleNote(document.getElementById(\'n-up-'+idx+'\'),this)">more</span>':'';
  var editBtn=makeEditBtn(cellId,'current',(origIdx!==undefined?origIdx:idx),'Notes / Memories','notes');
  return'<tr class="'+cls+'"><td class="cell-date"><span class="date-text">'+formatShowDate(row['Show Date'])+'</span><span class="day-of-week">'+dayOfWeek(row['Show Date'])+'</span></td>'
    +'<td><div class="cell-artist">'+artistLink(row['Artist'])+(showCount?' <span style="font-size:11px;color:var(--text-dim);font-family:var(--mono)">('+row['Ticket Quantity']+')</span>':'')+cal+'</div>'
    +(row['Supporting Artist']?'<div class="cell-support">w/ '+supportGoalNames(row['Supporting Artist'],row['Show Date'],true)+'</div>':'')+mv+buildBadges(row)+rowGoalBadges(row['Artist'],row['Show Date'],true)+'</td>'
    +'<td class="cell-venue col-support">'+vh+'</td><td class="cell-seat col-seat">'+seat+'</td>'
    +'<td class="cell-notes" id="'+cellId+'">'+editBtn+nh+'</td></tr>';
}

// ── Attended rows ──────────────────────────────────
function renderAttendedRowBystander(row,idx){
  var n=normalizeRow(row),isOtd=isOtdMatch(n.showDate);
  var otdB=isOtd?' <span class="badge badge-otd">📅 On this day</span>':'';
  var ne=esc(n.notes);
  var nh=ne?'<div class="notes-text collapsible" id="n-at-'+idx+'" onclick="toggleNote(this,\'nt-at-'+idx+'\')">'+''+ne+'</div><span class="notes-toggle" id="nt-at-'+idx+'" onclick="toggleNote(document.getElementById(\'n-at-'+idx+'\'),this)">more</span>':'';
  return'<tr class="'+(isOtd?'row-otd':'')+'"><td class="cell-date">'+formatShowDate(n.showDate)+otdB+'</td>'
    +'<td><div class="cell-artist">'+artistLink(n.artist)+'</div>'+rowGoalBadges(n.artist,n.showDate,false)+(n.support?'<div class="cell-support">w/ '+supportGoalNames(n.support,n.showDate,false)+'</div>':'')
    +'<div class="cell-venue-mobile">'+esc(shortVenueName(n.venueName))+'</div></td>'
    +'<td class="cell-venue">'+esc(shortVenueName(n.venueName))+'</td>'
    +'<td style="white-space:nowrap">'+(n.setlist?setlistIconHtml(n.setlist):'')
    +(n.playlist?'<a class="icon-link" href="'+esc(n.playlist)+'" target="_blank" title="YouTube playlist">▶</a>':'')
    +(n.photo?'<a class="icon-link" href="'+esc(n.photo)+'" target="_blank" title="Artist photo">📷</a>':'')+'</td>'
    +'<td class="cell-notes">'+nh+'</td></tr>';
}
function renderAttendedRowSearch(row,idx){
  var n=normalizeRow(row);
  var ne=esc(n.notes);
  var sw=_seenWithFor(n);
  var nh=ne?'<div class="notes-text collapsible" id="n-sr-'+idx+'" onclick="toggleNote(this,\'nt-sr-'+idx+'\')">'+ne+'</div><span class="notes-toggle" id="nt-sr-'+idx+'" onclick="toggleNote(document.getElementById(\'n-sr-'+idx+'\'),this)">more</span>':'';
  return'<tr><td class="cell-date">'+formatShowDateYear(n.showDate)+'</td>'
    +'<td><div class="cell-artist">'+artistLink(n.artist)+'</div>'+rowGoalBadges(n.artist,n.showDate,false)+(n.support?'<div class="cell-support">w/ '+supportGoalNames(n.support,n.showDate,false)+'</div>':'')+(sw.length?'<div class="cell-support">incl. '+sw.map(function(x){return artistLink(x);}).join(', ')+'</div>':'')
    +'<div class="cell-venue-mobile">'+esc(shortVenueName(n.venueName))+'</div></td>'
    +'<td class="cell-venue">'+esc(shortVenueName(n.venueName))+'</td>'
    +'<td style="white-space:nowrap">'+(n.setlist?setlistIconHtml(n.setlist):'')
    +(n.playlist?'<a class="icon-link" href="'+esc(n.playlist)+'" target="_blank" title="YouTube playlist">▶</a>':'')
    +(n.photo?'<a class="icon-link" href="'+esc(n.photo)+'" target="_blank" title="Artist photo">📷</a>':'')+'</td>'
    +'<td class="cell-notes">'+nh+'</td></tr>';
}
function renderAttendedRowAuthed(row,idx,origIdx){
  var n=normalizeRow(row),isOtd=isOtdMatch(n.showDate);
  var otdB=isOtd?' <span class="badge badge-otd">📅 On this day</span>':'';
  var fn=n.pvtNotes&&n.pvtNotes!=='-'?n.notes+(n.notes?' · ':'')+n.pvtNotes:n.notes,fne=esc(fn);
  var cellId='cell-at-'+idx;
  var nh=fne?'<div class="notes-text collapsible" id="n-at-'+idx+'" onclick="toggleNote(this,\'nt-at-'+idx+'\')">'+''+fne+'</div><span class="notes-toggle" id="nt-at-'+idx+'" onclick="toggleNote(document.getElementById(\'n-at-'+idx+'\'),this)">more</span>':'';
  var editBtn=makeEditBtn(cellId,'current',(origIdx!==undefined?origIdx:idx),'Notes / Memories','notes');
  var cost=totalSpend(row);
  return'<tr class="'+(isOtd?'row-otd':'')+'"><td class="cell-date">'+formatShowDate(n.showDate)+otdB+'</td>'
    +'<td><div class="cell-artist">'+artistLink(n.artist)+'</div>'+rowGoalBadges(n.artist,n.showDate,false)+(n.support?'<div class="cell-support">w/ '+supportGoalNames(n.support,n.showDate,false)+'</div>':'')
    +'<div class="cell-venue-mobile">'+esc(shortVenueName(n.venueName))+'</div></td>'
    +'<td class="cell-venue">'+esc(shortVenueName(n.venueName))+'</td>'
    +'<td style="white-space:nowrap">'+(n.setlist?setlistIconHtml(n.setlist):'')
    +(n.playlist?'<a class="icon-link" href="'+esc(n.playlist)+'" target="_blank" title="YouTube playlist">▶</a>':'')
    +(n.photo?'<a class="icon-link" href="'+esc(n.photo)+'" target="_blank" title="Artist photo">📷</a>':'')+'</td>'
    +'<td class="cell-cost col-cost">'+esc(cost)+'</td>'
    +'<td class="cell-notes" id="'+cellId+'">'+editBtn+nh+'</td></tr>';
}

// ── History panel ──────────────────────────────────
function renderHistoryYear(yr){
  var rows=historyData[yr];if(!rows)return'<div class="loading">Loading</div>';
  var sorted=rows.slice().sort(function(a,b){return(b['Show Date']||'').localeCompare(a['Show Date']||'');});
  var origIdx=sorted.map(function(r){return rows.indexOf(r);});
  var tbody=sorted.map(function(r,i){
    var oi=origIdx[i];
    var cellId='cell-hist-'+yr+'-'+i;
    var n=normalizeRow(r),isOtd=isOtdMatch(n.showDate);
    var otdB=isOtd?' <span class="badge badge-otd">📅 On this day</span>':'';
    var ne=esc(n.notes);
    var editBtn=authed?makeEditBtn(cellId,'history:'+yr,oi,'Notes / Memories','notes'):'';
    var nh=ne?'<div class="notes-text collapsible" id="n-hist-'+yr+'-'+i+'" onclick="toggleNote(this,\'nt-hist-'+yr+'-'+i+'\')">'+ne+'</div><span class="notes-toggle" id="nt-hist-'+yr+'-'+i+'" onclick="toggleNote(document.getElementById(\'n-hist-'+yr+'-'+i+'\'),this)">more</span>':'';
    return'<tr class="'+(isOtd?'row-otd':'')+'"><td class="cell-date">'+formatShowDate(n.showDate)+otdB+'</td>'
      +'<td><div class="cell-artist">'+artistLink(n.artist)+'</div>'+rowGoalBadges(n.artist,n.showDate,false)+(n.support?'<div class="cell-support">w/ '+supportGoalNames(n.support,n.showDate,false)+'</div>':'')
      +'<div class="cell-venue-mobile">'+esc(shortVenueName(n.venueName))+'</div></td>'
      +'<td class="cell-venue">'+esc(shortVenueName(n.venueName))+'</td>'
      +'<td style="white-space:nowrap">'+(n.setlist?setlistIconHtml(n.setlist):'')
      +(n.playlist?'<a class="icon-link" href="'+esc(n.playlist)+'" target="_blank" title="YouTube playlist">▶</a>':'')
      +(n.photo?'<a class="icon-link" href="'+esc(n.photo)+'" target="_blank" title="Artist photo">📷</a>':'')+'</td>'
      +'<td class="cell-notes" id="'+cellId+'">'+editBtn+nh+'</td></tr>';
  }).join('');
  return'<div class="history-year-header"><span class="history-year-label">'+yr+'</span><span class="history-year-count">'+sorted.length+' show'+(sorted.length!==1?'s':'')+'</span></div>'
    +'<div class="attended-table"><table class="shows-table"><thead><tr><th style="width:64px">Date</th><th style="width:260px">Artist</th><th style="width:200px">Venue</th><th style="width:40px">Links</th><th>Notes</th></tr></thead>'
    +'<tbody>'+tbody+'</tbody></table></div>';
}
function hatLoadingHtml(){var _bi=(SITE_CONFIG.site&&SITE_CONFIG.site.brand_icon)||'static/brand-hat.png';return'<div class="hat-loading"><img class="hat-loading-img" src="'+_assetUrl(_bi)+'" alt=""><div class="loading loading-dots" style="animation:none">Loading</div></div>';}
// Error twin of hatLoadingHtml — same centered layout, static hat (no pulse), red message.
function hatErrorHtml(msg){var _bi=(SITE_CONFIG.site&&SITE_CONFIG.site.brand_icon)||'static/brand-hat.png';return'<div class="hat-loading"><img class="hat-loading-img hat-static" src="'+_assetUrl(_bi)+'" alt=""><div class="error-msg" style="padding:0;text-align:center">'+esc(msg)+'</div></div>';}
async function loadHistoryYear(yr){
  if(historyData[yr]!==null)return;
  try{
    var results=await Promise.all([ghFetch('data/history/'+yr+'.tsv'),new Promise(function(r){setTimeout(r,2400);})]);
    historyData[yr]=parseTsv(decodeURIComponent(escape(atob(results[0].content.replace(/\n/g,'')))));
  }catch(e){historyData[yr]=[];console.error('Failed to load data/history/'+yr+'.tsv:',e);}
}
// One-shot loader for every history year — the same files the On-This-Day strip needs.
// In-flight-deduped so History-open and Search-open both await one fetch, never two.
// Failed years stay null (retryable) so the next History open can retry them; only sets
// _allYearsLoaded=true if every year succeeded, preventing permanently-empty year tabs.
// Also primes _setlistsCache for all years discovered in data/setlists/ in parallel,
// independently of HISTORY_YEARS — so 2026.json is warmed even before rollover adds 2026
// to the history TSV set.
var _historyLoad=null;
// #102 — seen_with lookup: "Show Date|Headliner" -> [session/sit-in/supergroup names].
// Loaded once with the history years so those names are searchable and annotated in results.
var _seenWith={};
function _buildSeenWithLookup(rows){
  _seenWith={};
  rows.forEach(function(r){
    var d=(r['Show Date']||'').trim(),h=(r['Headliner']||'').trim(),nm=(r['Seen With']||'').trim();
    if(!d||!h||!nm)return;
    var k=d+'|'+h;(_seenWith[k]||(_seenWith[k]=[])).push(nm);
  });
}
function _seenWithFor(n){return _seenWith[(n.showDate||'')+'|'+(n.artist||'')]||[];}
function loadAllHistory(){
  if(_allYearsLoaded)return Promise.resolve();
  if(_historyLoad)return _historyLoad;
  _historyLoad=(async function(){
    var unloaded=HISTORY_YEARS.filter(function(yr){return historyData[yr]===null;});
    var _anyFailed=false;
    // Prime setlists cache in parallel: discover years by listing data/setlists/, then
    // fetch each JSON. Runs independently of HISTORY_YEARS so 2026.json is always primed
    // even before rollover.
    var setlistPrime=(async function(){
      try{
        var dir=await ghFetch('data/setlists');
        var years=dir.filter(function(f){return/^\d{4}\.json$/.test(f.name);}).map(function(f){return parseInt(f.name);});
        await Promise.allSettled(years.map(function(yr){return _loadSetlistsForYear(yr);}));
      }catch(e){console.warn('setlists prime failed:',e.message);}
    })();
    // #102 — load seen_with.tsv once (supplementary; a failure just leaves the lookup empty).
    var seenWithPrime=(async function(){
      try{var res=await ghFetch('data/seen_with.tsv');_buildSeenWithLookup(parseTsv(_decodeB64(res.content)));}
      catch(e){console.warn('seen_with load failed:',e.message);}
    })();
    if(unloaded.length){
      var results=await Promise.allSettled(unloaded.map(function(yr){return ghFetch('data/history/'+yr+'.tsv');}));
      results.forEach(function(res,i){
        var yr=unloaded[i];
        if(res.status==='fulfilled'){try{historyData[yr]=parseTsv(_decodeB64(res.value.content));}catch(e){historyData[yr]=null;_anyFailed=true;console.error('parse data/history/'+yr+'.tsv:',e);}}
        else{historyData[yr]=null;_anyFailed=true;console.error('load data/history/'+yr+'.tsv:',res.reason);}
      });
      // If any year failed, reset the in-flight promise so the next History open retries.
      if(_anyFailed)_historyLoad=null;
    }
    await Promise.all([setlistPrime,seenWithPrime]);
    if(!_anyFailed)_allYearsLoaded=true;
  })();
  return _historyLoad;
}
// DOM refresh once all years are cached: true per-year + total History badges, search
// datalists, and the On-This-Day strip. Idempotent; safe from either entry point.
function _historyLoadedDom(){
  HISTORY_YEARS.forEach(function(yr){var b=document.getElementById('histBadge-'+yr);if(b&&historyData[yr])b.textContent=historyData[yr].length;});
  var total=HISTORY_YEARS.reduce(function(s,yr){return s+(historyData[yr]?historyData[yr].length:0);},0);
  var hb=document.getElementById('historyBadge');if(hb)hb.textContent=total||'—';
  populateSearchDatalists();
  renderOnThisDay();
  // #146 — history lazy-loads after the search panel already baked its empty state, so refresh
  // #srchResults here (the single load-complete chokepoint) to swap the "Type to search"
  // fallback for the stat boxes. Idle inputs only, so an active search isn't clobbered.
  var _sr=document.getElementById('srchResults'),_sa=document.getElementById('srchArtist'),_sv=document.getElementById('srchVenue');
  if(_sr&&(!_sa||!_sa.value)&&(!_sv||!_sv.value))_sr.innerHTML=buildSearchEmptyState();
}
function allAttendedRows(){
  var rows=[];
  HISTORY_YEARS.forEach(function(yr){if(historyData[yr])rows=rows.concat(historyData[yr]);});
  currentRows.filter(function(r){return r['Status']==='attended';}).forEach(function(r){rows.push(r);});
  rows.sort(function(a,b){
    var da=a['Show Date']||a['Date']||'',db=b['Show Date']||b['Date']||'';
    return db.localeCompare(da);
  });
  return rows;
}
function populateSearchDatalists(){
  var rows=allAttendedRows();
  var artists=new Set(),venues=new Set();
  rows.forEach(function(r){
    var n=normalizeRow(r);
    if(n.artist)artists.add(n.artist);
    if(n.support)n.support.split(/[/,]/).forEach(function(s){var t=s.trim();if(t)artists.add(t);});
    if(n.venueName)venues.add(shortVenueName(n.venueName));
  });
  function artSort(s){return s.replace(/^(The|A|An)\s+/i,'').toLowerCase();}
  Object.keys(_seenWith).forEach(function(k){_seenWith[k].forEach(function(nm){if(nm)artists.add(nm);});});
  var al=document.getElementById('srchArtistList'),vl=document.getElementById('srchVenueList');
  if(al)al.innerHTML=Array.from(artists).sort(function(a,b){return artSort(a).localeCompare(artSort(b));}).map(function(a){return'<option value="'+esc(a)+'">';}).join('');
  if(vl)vl.innerHTML=Array.from(venues).sort(function(a,b){return artSort(a).localeCompare(artSort(b));}).map(function(v){return'<option value="'+esc(v)+'">';}).join('');
}
function runSearch(){
  var qa=(document.getElementById('srchArtist')||{}).value||'';
  var qv=(document.getElementById('srchVenue')||{}).value||'';
  var resultsEl=document.getElementById('srchResults');
  if(!resultsEl)return;
  if(!qa&&!qv){resultsEl.innerHTML=buildSearchEmptyState();return;}
  var la=qa.toLowerCase(),lv=qv.toLowerCase();
  var rows=allAttendedRows().filter(function(r){
    var n=normalizeRow(r);
    var artistOk=!la||(n.artist.toLowerCase().includes(la)||n.support.toLowerCase().includes(la)||_seenWithFor(n).some(function(nm){return nm.toLowerCase().includes(la);}));
    var venueOk=!lv||(n.venueName.toLowerCase().includes(lv)||shortVenueName(n.venueName).toLowerCase().includes(lv));
    return artistOk&&venueOk;
  });
  if(!rows.length){resultsEl.innerHTML='<div class="search-empty">No matches</div>';return;}
  var tbody=rows.map(function(r,i){return renderAttendedRowSearch(r,i);}).join('');
  resultsEl.innerHTML='<div class="search-count">'+rows.length+' match'+(rows.length!==1?'es':'')+'</div>'
    +'<div class="attended-table"><table class="shows-table"><thead><tr>'
    +'<th style="width:80px">Date</th><th style="width:260px">Artist</th><th style="width:200px">Venue</th><th style="width:40px">Links</th><th>Notes</th>'
    +'</tr></thead><tbody>'+tbody+'</tbody></table></div>';
  requestAnimationFrame(revealToggles);
}
function debounceSearch(){clearTimeout(_srchTimer);_srchTimer=setTimeout(runSearch,250);}
function clearSearch(){
  var a=document.getElementById('srchArtist'),v=document.getElementById('srchVenue'),r=document.getElementById('srchResults');
  if(a)a.value='';if(v)v.value='';
  if(r)r.innerHTML=buildSearchEmptyState();
  if(a)a.focus();
}
function buildSearchEmptyState(){
  var rows=allAttendedRows();
  var artists=new Set(),venues=new Set();
  rows.forEach(function(r){
    var n=normalizeRow(r);
    if(n.artist)artists.add(n.artist);
    if(n.support)n.support.split(/[/,]/).forEach(function(s){var t=s.trim();if(t)artists.add(t);});
    if(n.venueName)venues.add(shortVenueName(n.venueName));
  });
  var firstDate=new Date(2021,6,11);
  var now=new Date();now.setHours(0,0,0,0);
  var days=Math.floor((now-firstDate)/86400000);
  var sc=rows.length,ac=artists.size,vc=venues.size;
  if(!sc)return'<div class="search-empty">Type to search across all shows</div>';
  return'<div style="padding:28px 0 20px;text-align:center">'
    +'<div style="display:flex;justify-content:center;gap:0;margin-bottom:18px">'
    +'<div style="padding:12px 22px;border:1px solid var(--border);border-radius:3px 0 0 3px"><div style="font-family:var(--mono);font-size:20px;font-weight:500;color:var(--amber);line-height:1;margin-bottom:3px">'+sc+'</div><div style="font-family:var(--mono);font-size:10px;letter-spacing:.07em;text-transform:uppercase;color:var(--text-dim)">Shows</div></div>'
    +'<div style="padding:12px 22px;border:1px solid var(--border);border-left:none"><div style="font-family:var(--mono);font-size:20px;font-weight:500;color:var(--amber);line-height:1;margin-bottom:3px">'+ac+'</div><div style="font-family:var(--mono);font-size:10px;letter-spacing:.07em;text-transform:uppercase;color:var(--text-dim)">Artists</div></div>'
    +'<div style="padding:12px 22px;border:1px solid var(--border);border-left:none"><div style="font-family:var(--mono);font-size:20px;font-weight:500;color:var(--amber);line-height:1;margin-bottom:3px">'+vc+'</div><div style="font-family:var(--mono);font-size:10px;letter-spacing:.07em;text-transform:uppercase;color:var(--text-dim)">Venues</div></div>'
    +'<div style="padding:12px 22px;border:1px solid var(--border);border-left:none;border-radius:0 3px 3px 0"><div style="font-family:var(--mono);font-size:20px;font-weight:500;color:var(--amber);line-height:1;margin-bottom:3px">'+days.toLocaleString()+'</div><div style="font-family:var(--mono);font-size:10px;letter-spacing:.07em;text-transform:uppercase;color:var(--text-dim)">Days</div></div>'
    +'</div>'
    +'<div style="font-family:var(--mono);font-size:11px;color:var(--text-dim)">first post-pandemic show <span style="color:var(--text-muted)">Jul 11, 2021 · Oliver Wood · Patio Stage at Strathmore</span></div>'
    +'<img src="'+_assetUrl((SITE_CONFIG.site&&SITE_CONFIG.site.brand_icon)||'static/brand-hat.png')+'" alt="" style="width:120px;height:120px;object-fit:contain;display:block;margin:44px auto 0;opacity:.9">'
    +'</div>';
}
function renderHistoryPanel(){
  var mr=HISTORY_YEARS[HISTORY_YEARS.length-1];
  var searchPanel='<div class="inner-panel" id="inner-hist-search"><div class="search-bar"><input class="search-input" id="srchArtist" placeholder="Artist…" list="srchArtistList" oninput="debounceSearch()" autocomplete="off"><datalist id="srchArtistList"></datalist><input class="search-input" id="srchVenue" placeholder="Venue…" list="srchVenueList" oninput="debounceSearch()" autocomplete="off"><datalist id="srchVenueList"></datalist><button class="btn" onclick="clearSearch()" title="Clear filters" style="flex-shrink:0">&#10005; clear</button></div><div id="srchResults">'+buildSearchEmptyState()+'</div></div>';
  var itr='<div class="inner-tab-row">'+HISTORY_YEARS.slice().reverse().map(function(yr){var cnt=historyData[yr]?historyData[yr].length:'&#8212;';return'<div class="inner-tab'+(yr===mr?' active':'')+'" data-inner="hist-'+yr+'" onclick="switchHistoryTab('+yr+')">'+yr+' <span class="tab-badge" id="histBadge-'+yr+'">'+cnt+'</span></div>';}).join('')+'<div class="inner-tab" data-inner="hist-search" onclick="switchHistorySearch()" style="margin-left:auto">&#128269; Search</div></div>';
  var ip=searchPanel+HISTORY_YEARS.slice().reverse().map(function(yr){return'<div class="inner-panel'+(yr===mr?' active':'')+'" id="inner-hist-'+yr+'">'+renderHistoryYear(yr)+'</div>';}).join('');
  var total=HISTORY_YEARS.reduce(function(s,yr){return s+(historyData[yr]?historyData[yr].length:0);},0);
  document.getElementById('historyBadge').textContent=total||'—';
  document.getElementById('historyContent').innerHTML=itr+ip;
  requestAnimationFrame(revealToggles);
}
async function switchHistorySearch(){
  document.querySelectorAll('.inner-tab[data-inner^="hist-"]').forEach(function(t){t.classList.toggle('active',t.dataset.inner==='hist-search');});
  document.querySelectorAll('[id^="inner-hist-"]').forEach(function(p){p.classList.toggle('active',p.id==='inner-hist-search');});
  if(!_allYearsLoaded){var srchEl=document.getElementById('srchResults');if(srchEl)srchEl.innerHTML=hatLoadingHtml();await loadAllHistory();_historyLoadedDom();runSearch();}else{var inp=document.getElementById('srchArtist');if(inp&&!inp.value)inp.focus();else runSearch();}
}
async function switchHistoryTab(yr){
  document.querySelectorAll('.inner-tab[data-inner^="hist-"]').forEach(function(t){t.classList.toggle('active',t.dataset.inner==='hist-'+yr);});
  document.querySelectorAll('[id^="inner-hist-"]').forEach(function(p){p.classList.toggle('active',p.id==='inner-hist-'+yr);});
  var panel=document.getElementById('inner-hist-'+yr);
  if(historyData[yr]===null){if(panel)panel.innerHTML=hatLoadingHtml();await loadHistoryYear(yr);}
  if(historyData[yr]!==null){
    var badge=document.getElementById('histBadge-'+yr);
    if(badge)badge.textContent=historyData[yr].length;
    if(panel){panel.innerHTML=renderHistoryYear(yr);requestAnimationFrame(revealToggles);}
    var total=HISTORY_YEARS.reduce(function(s,y){return s+(historyData[y]?historyData[y].length:0);},0);
    document.getElementById('historyBadge').textContent=total||'—';
  }else{requestAnimationFrame(revealToggles);}
}

// ── In-page purchase flow (#152) ─────────────────────
// The 🎟 bought button on authed Buy/Choose potentials rows records a purchase
// with FOUR simple client writes: (1) append the public current row (staging
// via dataBranch() → guard → auto-promote), (2) append the private cost row
// (private repo main), folding in any potential_private notes already merged
// in memory, (3) delete the potential_private row, (4) delete the
// fast_track_caps row if present. ALL derived public state — potentials
// removal, re-sort, Prev/Next brackets, fast_track prune — belongs to the CI
// reconciler (scripts/reconcile_purchases.py via potentials-maintenance.yml),
// never the client. Between step 1 and the reconciler's commit the show exists
// in both lists; the row renders "purchased — reconciling…" locally meanwhile.
// Private deletes are LINE-preserving: fast_track_caps.tsv carries a # comment
// block that parse-and-rewrite would destroy.
// With features.private_data false, only step 1 exists — the public move and
// the reconciler tidy-up are independent of the cost sidecar, so the modal
// hides the cost fields and never constructs a private-repo request.
var _purchasePending={};   // {Artist␟Date: 1} — local render state only, until next data refresh
var _purchaseSteps={};     // {Artist␟Date: {1..4: true}} — lets Confirm resume after a partial failure
function refreshAfterPurchase(){
  _purchasePending={};
  loadData();
}

function openPurchaseModal(idx){
  var r=potentialRows[idx];if(!r)return;
  var priv=featureOn('private_data');   // cost fields only exist when there is a sidecar to hold them
  var fm=(r['Face Price']||'').match(/\$?(\d+(?:\.\d{1,2})?)/);
  var fees=/all-?in|no fee/i.test(r['Fees Notes']||'')?'0':'';
  var seated=/seat/i.test(r['Face Price']||'')&&!/\bGA\b/i.test(r['Face Price']||'');
  var today=new Date().toISOString().slice(0,10);
  var html='<div class="fs-artist">'+esc(r['Artist']||'')+'</div>'
    +'<div class="fs-detail">'+formatShowDate(r['Date'])+' '+dayOfWeek(r['Date'])+' &middot; '+esc(r['Venue']||'')+' &middot; '+esc(r['Venue City']||'')+'</div>'
    +'<div class="pm-row" style="margin-top:12px"><span class="pm-label">Ticket access</span><input class="pm-input" id="pm-access" value="'+esc(r['Ticket Service']||'')+'" placeholder="AXS Mobile, Eventim…"></div>'
    +'<div class="pm-row"><span class="pm-label">Paper ticket</span><label class="pm-radio"><input type="checkbox" id="pm-paper"'+(/paper/i.test(r['Ticket Service']||'')?' checked':'')+'> Paper ticket</label></div>'
    +'<div class="pm-row"><span class="pm-label">Seat type</span><label class="pm-radio"><input type="radio" name="pm-seattype" value="GA"'+(seated?'':' checked')+'> GA</label><label class="pm-radio"><input type="radio" name="pm-seattype" value="Seated"'+(seated?' checked':'')+'> Seated</label></div>'
    +(priv?'<div class="pm-row"><span class="pm-label">Face value ($)</span><input class="pm-input" id="pm-face" type="number" step="0.01" min="0" value="'+(fm?fm[1]:'')+'"></div>'
      +'<div class="pm-row"><span class="pm-label">Fees total ($)</span><input class="pm-input" id="pm-fees" type="number" step="0.01" min="0" value="'+fees+'"></div>'
      +'<div class="pm-row"><span class="pm-label">Quantity</span><input class="pm-input" id="pm-qty" type="number" step="1" min="1" value="1"></div>'
      +'<div class="pm-row"><span class="pm-label">Seat info</span><input class="pm-input" id="pm-seatinfo" placeholder="optional — table/row/seat"></div>'
      +'<div class="pm-row"><span class="pm-label">Purchase date</span><input class="pm-input" id="pm-pdate" type="date" value="'+today+'"></div>'
      +'<div class="pm-row"><span class="pm-label">Private notes</span><textarea class="notes-textarea" id="pm-notes" rows="3">'+((r['Private Notes']&&r['Private Notes']!=='-')?esc(r['Private Notes']):'')+'</textarea></div>':'')
    +'<div class="pm-row"><span class="pm-label">Flags</span><label class="pm-radio"><input type="checkbox" id="pm-vip"> VIP</label><label class="pm-radio"><input type="checkbox" id="pm-group"> Group</label></div>'
    +'<div class="pm-steps" id="pm-steps"></div>'
    +'<div class="modal-actions"><button class="btn" onclick="closePurchaseModal()">Cancel</button><button class="btn btn-save" id="pm-confirm" onclick="confirmPurchase('+idx+')">Confirm purchase</button></div>';
  document.getElementById('purchaseModalBody').innerHTML=html;
  document.getElementById('purchaseModal').classList.add('open');
}
function closePurchaseModal(){document.getElementById('purchaseModal').classList.remove('open');}
function _pmStep(n,msg,cls){var el=document.getElementById('pm-steps');if(!el)return;var d=document.getElementById('pm-s'+n);if(!d){d=document.createElement('div');d.id='pm-s'+n;el.appendChild(d);}d.textContent=msg;d.className=cls||'';}

// Step 1 — append the public current row (19-col schema, '-' sentinels), in
// chronological position, committed to staging via dataBranch().
async function _purchaseAppendPublic(r,form,iso){
  var pat=localStorage.getItem(PAT_KEY);if(!pat)throw new Error('no auth');
  var fd=await ghFetch(CURRENT_PATH);
  var raw=_decodeB64(fd.content),headers=raw.split('\n')[0].split('\t').map(function(h){return h.trim();});
  var rows=parseTsv(raw);
  var nr={};headers.forEach(function(h){nr[h]='-';});
  nr['Show ID']=iso;nr['Artist']=r['Artist']||'';nr['Supporting Artist']=r['Support']||'';
  nr['Show Date']=iso;nr['Venue Name']=r['Venue']||'';nr['Venue Address']=r['Venue City']||'-';
  nr['Venue Event URL']=r['Event URL']||r['Purchase URL']||'-';
  nr['Seat Type']=form.seatType;nr['VIP']=form.vip?'Y':'';nr['Group']=form.group?'Y':'';
  var access=form.access||'';
  if(form.paper){access=/paper/i.test(access)?access:(access?access+' (Paper)':'Paper');}
  nr['Ticket Access']=access||'-';nr['Status']='upcoming';
  var at=rows.findIndex(function(x){return (x['Show Date']||'')>iso;});
  if(at<0)rows.push(nr);else rows.splice(at,0,nr);
  var res=await fetch('https://api.github.com/repos/'+OWNER+'/'+REPO+'/contents/'+CURRENT_PATH,{method:'PUT',headers:{'Accept':'application/vnd.github.v3+json','Authorization':'token '+pat,'Content-Type':'application/json'},body:JSON.stringify({message:'purchase: add '+(r['Artist']||'')+' '+iso+' (in-page)',content:btoa(unescape(encodeURIComponent(serializeTsv(rows,headers)))),sha:fd.sha,branch:dataBranch()})});
  if(!res.ok)throw new Error(await res.text());
}

// Step 2 — append the private cost row. Show Date + Artist are copied VERBATIM
// from the same values the public row was written with (the join keys — see
// the EMAIL_WORKFLOWS Routine 1 verbatim-key rule). Any potential_private
// notes already merged in memory are folded in, plus the 'in-page purchase'
// provenance marker Routine 1 uses to switch to verify-and-enrich mode.
// PRIVATE write: private repo main only — never a path in the public repo.
async function _purchaseAppendPrivate(r,form,iso){
  var pat=localStorage.getItem(PAT_KEY);if(!pat)throw new Error('no auth');
  var fd=await ghFetch(CURRENT_PRIVATE_PATH,{},OWNER_PRIVATE,REPO_PRIVATE);
  var raw=_decodeB64(fd.content),headers=raw.split('\n')[0].split('\t').map(function(h){return h.trim();});
  var rows=parseTsv(raw);
  var pvt=form.notes?form.notes+' · ':'';
  var total=form.face*form.qty+form.fees;
  var nr={};headers.forEach(function(h){nr[h]='-';});
  nr['Show Date']=iso;nr['Artist']=r['Artist']||'';
  nr['Seat Info / GA']=form.seatInfo||form.seatType;
  nr['Ticket Quantity']=String(form.qty);
  nr['Face Value (per ticket)']='$'+form.face.toFixed(2);
  nr['Fees']='$'+form.fees.toFixed(2);
  nr['Total Cost']='$'+total.toFixed(2);
  nr['Purchase Date']=form.pdate;
  nr['Private Notes']=pvt+'in-page purchase '+new Date().toISOString().slice(0,10);
  var at=rows.findIndex(function(x){return (x['Show Date']||'')>iso;});
  if(at<0)rows.push(nr);else rows.splice(at,0,nr);
  var res=await fetch('https://api.github.com/repos/'+OWNER_PRIVATE+'/'+REPO_PRIVATE+'/contents/'+CURRENT_PRIVATE_PATH,{method:'PUT',headers:{'Accept':'application/vnd.github.v3+json','Authorization':'token '+pat,'Content-Type':'application/json'},body:JSON.stringify({message:'purchase: add '+(r['Artist']||'')+' '+iso+' (in-page)',content:btoa(unescape(encodeURIComponent(serializeTsv(rows,headers)))),sha:fd.sha})});
  if(!res.ok)throw new Error(await res.text());
}

// Steps 3+4 — keyed deletes in the private repo, LINE-preserving so leading
// # comment blocks (fast_track_caps.tsv) survive verbatim. A missing row is a
// no-op (false), never an error. PRIVATE repo main only.
async function _purchaseDeletePrivateLine(path,match,label){
  var pat=localStorage.getItem(PAT_KEY);if(!pat)throw new Error('no auth');
  var fd=await ghFetch(path,{},OWNER_PRIVATE,REPO_PRIVATE);
  var raw=_decodeB64(fd.content),lines=raw.split('\n'),out=[],removed=false,headerSeen=false;
  lines.forEach(function(ln){
    if(!headerSeen){out.push(ln);if(ln&&ln.charAt(0)!=='#')headerSeen=true;return;}
    if(!removed&&ln&&match(ln.split('\t'))){removed=true;return;}
    out.push(ln);
  });
  if(!removed)return false;
  var res=await fetch('https://api.github.com/repos/'+OWNER_PRIVATE+'/'+REPO_PRIVATE+'/contents/'+path,{method:'PUT',headers:{'Accept':'application/vnd.github.v3+json','Authorization':'token '+pat,'Content-Type':'application/json'},body:JSON.stringify({message:path+': remove '+label+' (purchased)',content:btoa(unescape(encodeURIComponent(out.join('\n')))),sha:fd.sha})});
  if(!res.ok)throw new Error(await res.text());
  return true;
}

async function confirmPurchase(idx){
  var r=potentialRows[idx];if(!r)return;
  var priv=featureOn('private_data'),sfx='/'+(priv?4:1)+' ';
  var form={face:0,fees:0,qty:1,
    seatType:((document.querySelector('input[name="pm-seattype"]:checked')||{}).value)||'GA',
    seatInfo:((document.getElementById('pm-seatinfo')||{}).value||'').trim(),
    access:((document.getElementById('pm-access')||{}).value||'').trim(),
    pdate:((document.getElementById('pm-pdate')||{}).value)||new Date().toISOString().slice(0,10),
    vip:!!(document.getElementById('pm-vip')||{}).checked,
    group:!!(document.getElementById('pm-group')||{}).checked,
    paper:!!(document.getElementById('pm-paper')||{}).checked,
    notes:(function(){var el=document.getElementById('pm-notes');return el?el.value.trim():'';})()};
  if(priv){
    form.face=parseFloat((document.getElementById('pm-face')||{}).value);
    form.fees=parseFloat((document.getElementById('pm-fees')||{}).value||'0');
    form.qty=parseInt((document.getElementById('pm-qty')||{}).value||'1',10);
    if(isNaN(form.face)||form.face<0||isNaN(form.qty)||form.qty<1){alert('Enter a face value and quantity.');return;}
    if(isNaN(form.fees)||form.fees<0)form.fees=0;
  }
  var key=(r['Artist']||'')+'␟'+(r['Date']||''),done=_purchaseSteps[key]=_purchaseSteps[key]||{};
  var iso=(r['Date']||'').slice(0,10);
  var btn=document.getElementById('pm-confirm');if(btn)btn.disabled=true;
  try{
    if(!done[1]){_pmStep(1,'1'+sfx+'public show row…');await _purchaseAppendPublic(r,form,iso);done[1]=true;}
    _pmStep(1,'1'+sfx+'public show row ✓','pm-step-ok');
    if(priv){
      if(!done[2]){_pmStep(2,'2'+sfx+'private cost row…');await _purchaseAppendPrivate(r,form,iso);done[2]=true;}
      _pmStep(2,'2'+sfx+'private cost row ✓','pm-step-ok');
      if(!done[3]){_pmStep(3,'3'+sfx+'potentials sidecar…');await _purchaseDeletePrivateLine(POTENTIAL_PRIVATE_PATH,function(c){return c[0]===(r['Artist']||'')&&c[1]===(r['Date']||'');},(r['Artist']||'')+' potential note');done[3]=true;}
      _pmStep(3,'3'+sfx+'potentials sidecar ✓','pm-step-ok');
      if(!done[4]){_pmStep(4,'4'+sfx+'fast-track caps…');await _purchaseDeletePrivateLine('fast_track_caps.tsv',function(c){return c[0]===(r['Artist']||'');},(r['Artist']||'')+' caps');done[4]=true;}
      _pmStep(4,'4'+sfx+'fast-track caps ✓ — reconciler will tidy potentials','pm-step-ok');
    }else{
      _pmStep(1,'1'+sfx+'public show row ✓ — reconciler will tidy potentials','pm-step-ok');
    }
    _purchasePending[key]=1;
    setTimeout(function(){closePurchaseModal();renderPotential();},900);
  }catch(e){
    console.error(e);
    var n=!done[1]?1:!done[2]?2:!done[3]?3:4;
    _pmStep(n,n+sfx+'failed — '+String(e.message||'error').slice(0,140)+' — Confirm retries the remaining steps','pm-step-err');
    if(btn)btn.disabled=false;
  }
}

// ── For Sale modal ───────────────────────────────────
function openForSaleModal(idx){
  var r=potentialRows[idx];if(!r)return;
  var m=(r['Watching For']||'').match(/(\d+)/),qty=m?parseInt(m[1],10):1;
  var html='<div class="fs-artist">'+esc(r['Artist']||'')+'</div>'
    +'<div class="fs-detail">'+formatShowDate(r['Date'])+' '+dayOfWeek(r['Date'])+' &middot; '+esc(r['Venue']||'')+' &middot; '+esc(r['Venue City']||'')+'</div>'
    +(r['Availability Notes']&&r['Availability Notes']!=='-'?'<div class="fs-detail" style="margin-top:4px"><strong>Seat:</strong> '+esc(r['Availability Notes'])+'</div>':'')
    +(r['Ticket Service']?'<div class="fs-detail"><strong>Platform:</strong> '+esc(r['Ticket Service'])+'</div>':'')
    +'<div class="fs-price">'+esc(r['Face Price']||'')+' / ticket &middot; '+qty+' ticket'+(qty!==1?'s':'')+' available</div>'
    +(r['Notes']?'<div class="fs-notes">'+esc(r['Notes'])+'</div>':'')
    +(r['Purchase URL']?'<a class="fs-buy-btn" href="'+esc(r['Purchase URL'])+'" target="_blank">Buy tickets &#8594;</a>':'');
  document.getElementById('forsaleModalBody').innerHTML=html;
  document.getElementById('forsaleModal').classList.add('open');
}
function closeForSaleModal(){document.getElementById('forsaleModal').classList.remove('open');}

// ── Potential rows ───────────────────────────────────
function tierHtml(tier){var t=(tier||'').toLowerCase(),cls=t.includes('strong')&&t.includes('medium')?'tier-medium-strong':t==='strong'?'tier-strong':t==='low'?'tier-low':'tier-medium',dots=t==='strong'?'●●●':t.includes('strong')&&t.includes('medium')?'●●':t==='medium'?'●':t==='low'?'◦':'';return'<span class="cell-tier '+cls+'">'+(dots?'<span class="tier-dots">'+dots+'</span> ':'')+esc(tier)+'</span>';}
function renderPotentialRowBystander(r,gi){
  var pn=esc(r['Notes']||''),vu=r['Event URL']||r['Purchase URL']||'',vs=shortVenueName(r['Venue']||'');
  var vh=vu?'<a href="'+esc(vu)+'" target="_blank" style="color:var(--text-muted);text-decoration:none">'+esc(vs)+'</a>':esc(vs);
  var dec=r['Decision']||'',cls=dec.toLowerCase().startsWith('buy')?'buy':dec.toLowerCase()==='choose'?'choose':dec.toLowerCase()==='sell'?'sell':'pass';
  var isSell=dec.toLowerCase()==='sell',ph=esc(r['Face Price']||'');
  if(isSell&&r['Purchase URL'])ph+=' <a class="icon-link" href="'+esc(r['Purchase URL'])+'" target="_blank" title="View listing">🎟</a>';
  var ctx=[esc(r['Prev Show (2026)']||''),esc(r['Next Show (2026)']||'')].filter(Boolean).map(function(s){return'<div>'+s+'</div>';}).join('');
  var an=artistLink(r['Artist']);
  return'<tr class="row-'+cls+'"><td style="white-space:nowrap"><span class="cell-decision-ro '+cls+'">'+esc(dec)+'</span></td>'
    +'<td class="cell-date"><span class="date-text">'+formatShowDate(r['Date'])+'</span><span class="day-of-week">'+dayOfWeek(r['Date'])+'</span></td>'
    +'<td><div class="cell-artist">'+an+_goalBadgeSpans(r['Artist'],r['Date'],true)+'</div>'+(r['Support']?'<div class="cell-support">w/ '+supportGoalNames(r['Support'],r['Date'],true)+'</div>':'')+'</td>'
    +'<td>'+vh+'<div style="font-size:11px;color:var(--text-dim);margin-top:2px">'+esc(r['Venue City']||'')+'</div></td>'
    +'<td class="col-tier">'+tierHtml(r['Tier']||'')+'</td><td class="col-price cell-price">'+ph+'</td>'
    +'<td class="col-watching">'+(r['Watching For']?'<span class="cell-watching"><span class="watch-icon">&#9888;</span> '+esc(r['Watching For'])+'</span>':'')+'</td>'
    +'<td class="col-context cell-context">'+ctx+'</td><td class="cell-pot-notes">'+(pn?'<div>'+pn+'</div>':'')+'</td></tr>';
}
function renderPotentialRowAuthed(r,gi){
  var pn=r['Notes']||'',pvt=r['Private Notes']||'',s=pvt==='-';
  var fn=!s&&pvt?pn+(pn?' · ':'')+pvt:pn,fne=esc(fn);
  var vu=r['Event URL']||r['Purchase URL']||'',vs=shortVenueName(r['Venue']||'');
  var vh=vu?'<a href="'+esc(vu)+'" target="_blank" style="color:var(--text-muted);text-decoration:none">'+esc(vs)+'</a>':esc(vs);
  var dec=r['Decision']||'',isSell=dec.toLowerCase()==='sell';
  var ctx=[esc(r['Prev Show (2026)']||''),esc(r['Next Show (2026)']||'')].filter(Boolean).map(function(s){return'<div>'+s+'</div>';}).join('');
  var potCellId='cell-pot-'+gi;
  var potEditBtn=makeEditBtn(potCellId,'potential',gi,'Notes','notes');
  var nh=fne?'<div class="cell-pot-notes" style="cursor:pointer;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden" onclick="this.style.display=\'block\';this.style.cursor=\'default\'">'+fne+'</div>':'';
  var dh;
  if(_purchasePending[(r['Artist']||'')+'␟'+(r['Date']||'')]){dh='<a href="#" class="pot-reconciling" onclick="event.preventDefault();refreshAfterPurchase();">🎟 purchased — reconciling… (tap to refresh)</a>';}
  else if(isSell){dh='<span class="cell-decision-ro sell">'+esc(dec)+'</span><button class="revoke-btn" onclick="handleRevoke('+gi+')" title="Remove listing">&#10005; revoke</button>';}
  else{var opts=['Buy','Choose','Pass'].map(function(v){return'<option value="'+v+'"'+(dec.toLowerCase().startsWith(v.toLowerCase())?' selected':'')+'>'+v+'</option>';}).join('');dh='<select class="decision-select" data-row="'+gi+'" onchange="handleDecisionChange(this)">'+opts+'</select><span class="save-indicator" id="save-'+gi+'"></span>';if(featureOn('in_page_purchase'))dh+='<button class="bought-btn" onclick="openPurchaseModal('+gi+')" title="Record a ticket purchase">🎟 bought</button>';}
  var pu=r['Purchase URL']||'',sl=isSell?pu:((dec.toLowerCase().startsWith('buy')||dec.toLowerCase()==='choose')&&pu),ph=esc(r['Face Price']||'');
  if(sl)ph+=' <a class="icon-link" href="'+esc(pu)+'" target="_blank" title="'+(isSell?'View listing':'Buy tickets')+'">🎟</a>';
  if((r['Box Office']||'').trim().toUpperCase()==='Y')ph+=' <span title="Buy at the box office — not online (#186)">🏣</span>';
  var an=artistLink(r['Artist']);
  return'<tr class="row-'+dec.toLowerCase()+'"><td style="white-space:nowrap">'+dh+'</td>'
    +'<td class="cell-date"><span class="date-text">'+formatShowDate(r['Date'])+'</span><span class="day-of-week">'+dayOfWeek(r['Date'])+'</span></td>'
    +'<td><div class="cell-artist">'+an+_goalBadgeSpans(r['Artist'],r['Date'],true)+'</div>'+(r['Support']?'<div class="cell-support">w/ '+supportGoalNames(r['Support'],r['Date'],true)+'</div>':'')+'</td>'
    +'<td>'+vh+'<div style="font-size:11px;color:var(--text-dim);margin-top:2px">'+esc(r['Venue City']||'')+'</div></td>'
    +'<td class="col-tier">'+tierHtml(r['Tier']||'')+'</td><td class="col-price cell-price">'+ph+'</td>'
    +'<td class="col-watching">'+(r['Watching For']?'<span class="cell-watching"><span class="watch-icon">&#9888;</span> '+esc(r['Watching For'])+'</span>':'')+'</td>'
    +'<td class="col-context cell-context">'+ctx+'</td><td class="cell-pot-notes" id="'+potCellId+'">'+potEditBtn+nh+'</td></tr>';
}

// ── Recommend CTA ────────────────────────────────
function recommendCtaHtml(label){
  if(!featureOn('recommendations'))return'';
  label=label||'+ Suggest a show';
  var enabled=authed||(typeof RECOMMEND_DEBUG==='undefined'||!RECOMMEND_DEBUG);
  return enabled
    ?'<button class="recommend-cta-header active" title="Suggest an artist or show" onclick="openRecommendModal()">'+label+'</button>'
    :'<button class="recommend-cta-header" title="Suggestions are coming soon" aria-disabled="true" disabled>'+label+'</button>';
}

// ── Shows rendering ───────────────────────────────────
function renderShows(){
  var upcoming=currentRows.filter(function(r){return r['Status']==='upcoming';}).sort(function(a,b){return(a['Show Date']||'').localeCompare(b['Show Date']||'');});
  var attended=currentRows.filter(function(r){return r['Status']==='attended';}).sort(function(a,b){return(b['Show Date']||'').localeCompare(a['Show Date']||'');});
  var sellRows=featureOn('for_sale')?potentialRows.filter(function(r){return(r['Decision']||'').toLowerCase()==='sell';}):[];
  var bannerCta=sellRows.length
    ?'<button class="forsale-cta" onclick="openForSaleModal('+potentialRows.indexOf(sellRows[0])+')"><span style="opacity:.7;font-size:10px;letter-spacing:.06em;text-transform:uppercase;margin-right:6px">For Sale</span>&#127991; '+esc(sellRows[0]['Artist']||'')+(sellRows.length>1?' + '+(sellRows.length-1)+' more':'')+'</button>'
    :recommendCtaHtml();
  var banner=!authed?'<div class="bystander-banner"><span>&#128075; Welcome! &#8212; Feel free to browse my upcoming shows and history.</span>'+bannerCta+'</div>':'';
  document.getElementById('showsBadge').textContent=attended.length+'+'+upcoming.length;
  var upOrigIdx=upcoming.map(function(r){return currentRows.indexOf(r);});
  var atOrigIdx=attended.map(function(r){return currentRows.indexOf(r);});
  var uTbody=authed?upcoming.map(function(r,i){return renderUpcomingRowAuthed(r,i,upOrigIdx[i]);}).join(''):upcoming.map(function(r,i){return renderUpcomingRowBystander(r,i);}).join('');
  var aTbody=authed?attended.map(function(r,i){return renderAttendedRowAuthed(r,i,atOrigIdx[i]);}).join(''):attended.map(function(r,i){return renderAttendedRowBystander(r,i);}).join('');
  var uTable='<table class="shows-table"><thead><tr><th>Date</th><th>Artist</th><th class="col-support">Venue</th><th class="col-seat">Seat / GA</th><th>Notes</th></tr></thead><tbody>'+uTbody+'</tbody></table>';
  var aTableHead=authed?'<thead><tr><th>Date</th><th>Artist</th><th>Venue</th><th>Links</th><th class="col-cost">Cost</th><th>Notes</th></tr></thead>':'<thead><tr><th>Date</th><th>Artist</th><th>Venue</th><th>Links</th><th>Notes</th></tr></thead>';
  var aTable='<div class="attended-table"><table class="shows-table">'+aTableHead+'<tbody>'+aTbody+'</tbody></table></div>';
  var di=authed?'upcoming':'attended';
  var itr='<div class="inner-tab-row"><div class="inner-tab'+(di==='attended'?' active':'')+'" data-inner="attended" onclick="switchInnerTab(\'attended\')" tabindex="0" onkeydown="if(event.key===\'Enter\'||event.key===\' \')switchInnerTab(\'attended\')">Attended (2026)<span class="tab-badge">'+attended.length+'</span></div><div class="inner-tab'+(di==='upcoming'?' active':'')+'" data-inner="upcoming" onclick="switchInnerTab(\'upcoming\')" tabindex="0" onkeydown="if(event.key===\'Enter\'||event.key===\' \')switchInnerTab(\'upcoming\')">Upcoming <span class="tab-badge">'+upcoming.length+'</span></div><div style="margin-left:auto;padding:6px 4px 6px 12px">'+recommendCtaHtml()+'</div></div>';
  var ip='<div class="inner-panel'+(di==='attended'?' active':'')+'" id="inner-attended">'+aTable+'</div><div class="inner-panel'+(di==='upcoming'?' active':'')+'" id="inner-upcoming">'+uTable+'</div>';
  document.getElementById('showsContent').innerHTML=banner+itr+ip;
  requestAnimationFrame(revealToggles);
  if(fastTrackRows.length)renderTourHere();
}

// ── Potential rendering ──────────────────────────────
function renderPotentialGroup(rows,groupKey,label){
  if(!rows.length)return'';
  var tbody=authed?rows.map(function(r){return renderPotentialRowAuthed(r,potentialRows.indexOf(r));}).join(''):rows.map(function(r){return renderPotentialRowBystander(r,potentialRows.indexOf(r));}).join('');
  var table='<table class="pot-table"><thead><tr><th></th><th>Date</th><th>Artist</th><th>Venue</th><th class="col-tier">Tier</th><th class="col-price">Face</th><th class="col-watching">Watching For</th><th class="col-context">Prev / Next</th><th>Notes</th></tr></thead><tbody>'+tbody+'</tbody></table>';
  if(groupKey==='pass')return'<div class="potential-group"><details class="pass-details"><summary>'+label+' <span class="group-count">('+rows.length+')</span></summary><div class="group-table-wrap group-table-pass">'+table+'</div></details></div>';
  return'<div class="potential-group"><div class="group-header group-header-'+groupKey+'">'+label+' <span class="group-count">('+rows.length+')</span></div><div class="group-table-wrap group-table-'+groupKey+'">'+table+'</div></div>';
}
function renderPotential(){
  var s=potentialRows.slice().sort(function(a,b){return(a['Date']||'').localeCompare(b['Date']||'');});
  var buy=s.filter(function(r){return(r['Decision']||'').toLowerCase().startsWith('buy');});
  var choose=s.filter(function(r){return(r['Decision']||'').toLowerCase()==='choose';});
  var sell=s.filter(function(r){return(r['Decision']||'').toLowerCase()==='sell';});
  var pass=s.filter(function(r){return(r['Decision']||'').toLowerCase()==='pass';});
  document.getElementById('potBadge').textContent=buy.length+'+'+choose.length;
  document.getElementById('potContent').innerHTML=renderPotentialGroup(buy,'buy',stageHeader('buy'))+renderPotentialGroup(choose,'choose',stageHeader('choose'))+(featureOn('for_sale')?renderPotentialGroup(sell,'sell','&#127991; For Sale &#8212; buy my tickets'):'')+renderPotentialGroup(pass,'pass',stageHeader('pass'))||'<p class="loading" style="animation:none">No data</p>';
  if(fastTrackRows.length)renderTourHere();
}

// ── Decision editing ──────────────────────────────────
async function handleRevoke(idx){
  if(!confirm('Remove this Sell row from potentials? This cannot be undone.'))return;
  try{
    var fd=await ghFetch(POTENTIAL_PATH),raw=decodeURIComponent(escape(atob(fd.content.replace(/\n/g,''))));
    var headers=raw.split('\n')[0].split('\t').map(function(h){return h.trim();}),rows=parseTsv(raw);
    var _target=potentialRows[idx];
    var _fi=rows.findIndex(function(r){return r['Artist']===_target['Artist']&&r['Date']===_target['Date'];});
    if(_fi<0)throw new Error('Row not found in file: '+(_target['Artist']||''));
    var artist=rows[_fi]['Artist']||'show';rows.splice(_fi,1);potentialRows.splice(idx,1);
    var pat=localStorage.getItem(PAT_KEY);
    var res=await fetch('https://api.github.com/repos/'+OWNER+'/'+REPO+'/contents/'+POTENTIAL_PATH,{method:'PUT',headers:{'Accept':'application/vnd.github.v3+json','Authorization':'token '+pat,'Content-Type':'application/json'},body:JSON.stringify({message:'potential: remove '+artist+' Sell row (revoked)',content:btoa(unescape(encodeURIComponent(serializeTsv(rows,headers)))),sha:fd.sha,branch:dataBranch()})});
    if(!res.ok)throw new Error(await res.text());
    potentialRows=rows;setTimeout(function(){renderPotential();renderShows();},400);
  }catch(e){console.error(e);alert('Error removing row: '+e.message);}
}
async function handleDecisionChange(select){
  var idx=parseInt(select.dataset.row),newVal=select.value,ind=document.getElementById('save-'+idx);
  ind.textContent='…';ind.className='save-indicator';
  try{
    var fd=await ghFetch(POTENTIAL_PATH),raw=decodeURIComponent(escape(atob(fd.content.replace(/\n/g,''))));
    var headers=raw.split('\n')[0].split('\t').map(function(h){return h.trim();}),rows=parseTsv(raw);
    var _target=potentialRows[idx];
    var _fi=rows.findIndex(function(r){return r['Artist']===_target['Artist']&&r['Date']===_target['Date'];});
    if(_fi<0)throw new Error('Row not found in file: '+(_target['Artist']||''));
    rows[_fi]['Decision']=newVal;potentialRows[idx]['Decision']=newVal;
    rows.sort(function(a,b){var rank=function(r){var d=(r['Decision']||'').toLowerCase();return d.startsWith('buy')?0:d==='choose'?1:d==='sell'?2:3;};return rank(a)-rank(b)||(a['Date']||'').localeCompare(b['Date']||'');});
    var pat=localStorage.getItem(PAT_KEY);
    var res=await fetch('https://api.github.com/repos/'+OWNER+'/'+REPO+'/contents/'+POTENTIAL_PATH,{method:'PUT',headers:{'Accept':'application/vnd.github.v3+json','Authorization':'token '+pat,'Content-Type':'application/json'},body:JSON.stringify({message:'potential: update '+(potentialRows[idx]['Artist']||'')+' decision',content:btoa(unescape(encodeURIComponent(serializeTsv(rows,headers)))),sha:fd.sha,branch:dataBranch()})});
    if(!res.ok)throw new Error(await res.text());
    potentialRows=rows;ind.textContent='✓';ind.className='save-indicator save-ok';
    setTimeout(function(){renderPotential();renderShows();},600);
  }catch(e){console.error(e);ind.textContent='✗';ind.className='save-indicator save-err';}
}

// ── Please Tour Here ────────────────────────────────
var fastTrackRows=[];
var FAST_TRACK_PATH='data/fast_track.tsv';
var _fastTrackComments='';
function parseFastTrack(text){
  var lines=text.trim().replace(/\r\n/g,'\n').replace(/\r/g,'\n').split('\n');
  var commentLines=[];
  var dataLines=lines.filter(function(l){
    if(l.trim().startsWith('#')){commentLines.push(l);return false;}
    return l.trim();
  });
  _fastTrackComments=commentLines.join('\n');
  var headers=dataLines[0].split('\t').map(function(h){return h.trim();});
  return dataLines.slice(1).map(function(line){
    var vals=line.split('\t');
    while(vals.length<headers.length)vals.push('');
    var obj={};
    headers.forEach(function(h,i){obj[h]=(vals[i]||'').trim();});
    return obj;
  });
}
function serializeFastTrack(rows,headers){
  var data=serializeTsv(rows,headers);
  return _fastTrackComments?_fastTrackComments+'\n'+data:data;
}
function renderTourHere(){
  if(!fastTrackRows.length){document.getElementById('tourhereContent').innerHTML='<div class="loading" style="animation:none">No data</div>';return;}
  var banner='<div class="bystander-banner"><span>Artists I have never caught live yet &#8212; any DC/MD/VA date would be a strong buy.</span>'+recommendCtaHtml('+ Suggest an artist')+'</div>';
  var thead='<thead><tr><th style="width:170px">Artist</th><th style="width:110px">Links</th><th style="width:80px">Tier</th><th>Why</th></tr></thead>';
  var tbody=fastTrackRows.map(function(r,ri){
    var tier=r['Tier']||'';
    var isHat=!!(GOAL_DATA.hat&&GOAL_DATA.hat.eligible[_goalNorm(r['Artist'])]);
    var isFirst=(r['First Tour']||'').trim().toUpperCase()==='Y';
    var tourUrl=r['Tour URL']||r['BIT URL']||'';
    var spotUrl=featureOn('spotify_integration')?(r['Spotify URL']||''):'';  
    return'<tr><td><div class="ft-artist">'+artistLink(r['Artist']||'')+(isHat?' <span class="badge badge-hat">🎩 HAT</span>':'')+(isFirst?' <span class="badge badge-first">1st</span>':'')+'</div></td>'
      +'<td><div class="ft-links">'+(tourUrl?'<a class="ft-link ft-link-tour" href="'+esc(tourUrl)+'" target="_blank">Tour &#8599;</a>':'')+(spotUrl?'<a class="ft-link ft-link-sp" href="'+esc(spotUrl)+'" target="_blank">Spotify</a>':'')+'</div></td>'
      +'<td>'+tierHtml(tier)+'</td>'
      +'<td><div class="ft-why" id="cell-ft-why-'+ri+'">'+makeEditBtn('cell-ft-why-'+ri,'fasttrack',ri,'Why Fast Track','Why')+esc(r['Why Fast Track']||'')+'</div></td>'
      +'</tr>';
  }).join('');
  document.getElementById('tourhereBadge').textContent=fastTrackRows.length;
  document.getElementById('tourhereContent').innerHTML=banner+'<table class="ft-table">'+thead+'<tbody>'+tbody+'</tbody></table>';
}
async function loadTourHere(){
  if(!featureOn('fast_track'))return;
  if(fastTrackRows.length){renderTourHere();return;}
  document.getElementById('tourhereContent').innerHTML=hatLoadingHtml();
  try{
    var fd=await ghFetch(FAST_TRACK_PATH);
    var raw=decodeURIComponent(escape(atob(fd.content.replace(/\n/g,''))));
    fastTrackRows=parseFastTrack(raw);
    renderTourHere();
  }catch(e){
    document.getElementById('tourhereContent').innerHTML=hatErrorHtml('Error loading fast_track.tsv: '+e.message);
  }
}

// ── Utilities ────────────────────────────────────────────
function toggleNote(el,tog){if(!el)return;var ex=el.classList.toggle('expanded');if(typeof tog==='string')tog=document.getElementById(tog);if(tog)tog.textContent=ex?'less':'more';}
function revealToggles(){
  document.querySelectorAll('.notes-text.collapsible').forEach(function(el){
    var togId=el.id?el.id.replace(/^n-/,'nt-'):null;
    var tog=togId?document.getElementById(togId):null;
    if(!tog)return;
    tog.style.display=el.scrollHeight>el.clientHeight+2?'inline-block':'none';
  });
}
function switchInnerTab(name){
  document.querySelectorAll('.inner-tab:not([data-inner^="hist-"])').forEach(function(t){t.classList.toggle('active',t.dataset.inner===name);});
  document.querySelectorAll('#inner-attended,#inner-upcoming').forEach(function(p){p.classList.toggle('active',p.id==='inner-'+name);});
  requestAnimationFrame(revealToggles);
}
async function openHistory(){
  if(_allYearsLoaded){requestAnimationFrame(revealToggles);return;}
  var mr=HISTORY_YEARS[HISTORY_YEARS.length-1];
  var panel=document.getElementById('inner-hist-'+mr);
  if(panel)panel.innerHTML=hatLoadingHtml();
  // load every year (also what OTD needs); keep a ~2.4s floor so the hat animation reads,
  // matching the old per-year loader's feel.
  await Promise.all([loadAllHistory(),new Promise(function(r){setTimeout(r,2400);})]);
  _historyLoadedDom();
  HISTORY_YEARS.forEach(function(yr){var p=document.getElementById('inner-hist-'+yr);if(p&&historyData[yr])p.innerHTML=renderHistoryYear(yr);});
  requestAnimationFrame(revealToggles);
}
function switchTab(name){
  document.querySelectorAll('.tab').forEach(function(t){t.classList.toggle('active',t.dataset.tab===name);});
  document.querySelectorAll('.panel').forEach(function(p){p.classList.toggle('active',p.id==='panel-'+name);});
  if(name==='history')openHistory();
  if(name==='tourhere')loadTourHere();
}
function openAboutModal(){document.getElementById('aboutModal').classList.add('open');}
function closeAboutModal(){document.getElementById('aboutModal').classList.remove('open');}
function openAuthModal(){document.getElementById('patInput').value='';document.getElementById('authModal').classList.add('open');}
function closeAuthModal(){document.getElementById('authModal').classList.remove('open');}
async function savePat(){var v=document.getElementById('patInput').value.trim();if(!v)return;localStorage.setItem(PAT_KEY,v);authed=true;document.getElementById('authBtn').classList.add('authed');_gearVisible();closeAuthModal();await mergePrivateData();renderShows();renderPotential();if(fastTrackRows.length)renderTourHere();}
function clearPat(){localStorage.removeItem(PAT_KEY);authed=false;document.getElementById('authBtn').classList.remove('authed');_gearVisible();closeAuthModal();loadData();if(fastTrackRows.length)renderTourHere();}

document.addEventListener('DOMContentLoaded',function(){
  document.getElementById('aboutModal').addEventListener('click',function(e){if(e.target===e.currentTarget)closeAboutModal();});
  document.getElementById('authModal').addEventListener('click',function(e){if(e.target===e.currentTarget)closeAuthModal();});
  document.getElementById('forsaleModal').addEventListener('click',function(e){if(e.target===e.currentTarget)closeForSaleModal();});
  var _pm152=document.getElementById('purchaseModal');if(_pm152)_pm152.addEventListener('click',function(e){if(e.target===e.currentTarget)closePurchaseModal();});
  document.getElementById('multisetModal').addEventListener('click',function(e){if(e.target===e.currentTarget)closeMultisetModal();});
  document.getElementById('recommendModal').addEventListener('click',function(e){if(e.target===e.currentTarget)closeRecommendModal();});
});

// ── Multi-setlist modal ───────────────────────────────
var _setlistsCache={};
async function _loadSetlistsForYear(year){
  if(_setlistsCache[year]!==undefined)return _setlistsCache[year];
  try{
    var fd=await ghFetch('data/setlists/'+year+'.json');
    _setlistsCache[year]=JSON.parse(decodeURIComponent(escape(atob(fd.content.replace(/\n/g,'')))));
  }catch(e){_setlistsCache[year]=null;}
  return _setlistsCache[year];
}
function openMultisetModal(dateKey){
  var body=document.getElementById('multisetModalBody');
  body.innerHTML='<div class="multiset-loading">Loading&#8230;</div>';
  document.getElementById('multisetModal').classList.add('open');
  _loadSetlistsForYear(dateKey.slice(0,4)).then(function(data){
    var entry=data&&data[dateKey];
    if(!entry){body.innerHTML='<div class="multiset-loading">No setlist data found.</div>';return;}
    var items=entry.setlists.map(function(s,i){
      return'<div class="multiset-item"><span class="multiset-order">'+(i+1)+'.</span>'
        +'<span class="multiset-artist">'+esc(s.artist)+'</span>'
        +'<a class="ext-link" href="'+esc(s.url)+'" target="_blank">setlist.fm</a></div>';
    }).join('');
    body.innerHTML='<div class="multiset-event">'+esc(entry.event)+'</div><div class="multiset-list">'+items+'</div>';
  }).catch(function(e){body.innerHTML='<div class="multiset-loading">Error: '+esc(e.message)+'</div>';});
}
function closeMultisetModal(){document.getElementById('multisetModal').classList.remove('open');}

// -- Config editor (#77) --
var _cfgDraft=null;  // unsaved working copy of config.yaml, preserved across modal open/close
function _gearVisible(){
  // #180 — authed-only artist-graph link rides the same auth-visibility hook as the gear
  var gl=document.getElementById('graphLink');if(gl)gl.style.display=authed?'':'none';
  var gear=document.getElementById('configGearBtn');if(!gear)return;
  var webEdit=!SITE_CONFIG.features||SITE_CONFIG.features.web_edit!==false;
  gear.style.display=(authed&&webEdit)?'':'none';
}
async function openConfigEditor(){
  var ta=document.getElementById('configEditorText'),st=document.getElementById('configEditorStatus');
  document.getElementById('configModal').classList.add('open');
  if(_cfgDraft!==null){ta.value=_cfgDraft;st.textContent='restored your unsaved edits - Reset from repo to discard';return;}
  st.textContent='loading...';
  try{
    var res=await fetch('config.yaml?t='+Date.now(),{cache:'no-store'});
    if(!res.ok)throw new Error('config.yaml '+res.status);
    ta.value=await res.text();
    st.textContent='loaded from repo';
  }catch(e){ta.value='';st.textContent='load failed: '+e.message;}
}
function closeConfigEditor(){_cfgDraft=document.getElementById('configEditorText').value;document.getElementById('configModal').classList.remove('open');}
async function revertConfigToRepo(){
  _cfgDraft=null;
  var ta=document.getElementById('configEditorText'),st=document.getElementById('configEditorStatus');
  st.textContent='loading...';
  try{
    var res=await fetch('config.yaml?t='+Date.now(),{cache:'no-store'});
    if(!res.ok)throw new Error('config.yaml '+res.status);
    ta.value=await res.text();
    st.textContent='loaded from repo';
  }catch(e){ta.value='';st.textContent='load failed: '+e.message;}
}
function reloadConfigPreview(){
  var ta=document.getElementById('configEditorText'),st=document.getElementById('configEditorStatus');
  try{
    var parsed=jsyaml.load(ta.value);
    SITE_CONFIG=_cfgMerge(DEFAULT_CONFIG,parsed||{});
    window.SITE_CONFIG=SITE_CONFIG;
    applyConfig(SITE_CONFIG);
    applyTheme(SITE_CONFIG);
    _gearVisible();
    st.textContent='preview applied to this session (not committed)';
  }catch(e){st.textContent='YAML error: '+e.message;}
}
async function commitConfig(){
  var ta=document.getElementById('configEditorText'),st=document.getElementById('configEditorStatus');
  var pat=localStorage.getItem(PAT_KEY);if(!pat){st.textContent='not authed - cannot commit';return;}
  try{jsyaml.load(ta.value);}catch(e){st.textContent='YAML error (not committed): '+e.message;return;}
  st.textContent='committing...';
  try{
    var fd=await ghFetch('config.yaml');
    var res=await fetch('https://api.github.com/repos/'+OWNER+'/'+REPO+'/contents/config.yaml',{method:'PUT',headers:{'Accept':'application/vnd.github.v3+json','Authorization':'token '+pat,'Content-Type':'application/json'},body:JSON.stringify({message:'config: edit via in-page editor',content:btoa(unescape(encodeURIComponent(ta.value))),sha:fd.sha,branch:dataBranch()})});
    if(!res.ok)throw new Error(await res.text());
    st.textContent='committed - live ~1 min after Pages redeploys';_cfgDraft=null;
  }catch(e){st.textContent='commit failed: '+e.message;}
}
// ── Boot ───────────────────────────────────────────────
async function loadData(){
  _purchasePending={};
  document.getElementById('showsContent').innerHTML=hatLoadingHtml();
  document.getElementById('potContent').innerHTML=hatLoadingHtml();
  try{
    var results=await Promise.all([ghFetch(CURRENT_PATH),ghFetch(POTENTIAL_PATH)]);
    currentRows=parseTsv(_decodeB64(results[0].content));
    potentialRows=parseTsv(_decodeB64(results[1].content));
    await mergePrivateData();
    await loadGoalData();
    await loadVenueIdentity();
    renderShows();renderPotential();
    document.getElementById('fetchedAt').textContent='data fetched as of '+new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
  }catch(e){var msg=hatErrorHtml('Error: '+e.message);document.getElementById('showsContent').innerHTML=msg;document.getElementById('potContent').innerHTML=msg;}
}
if(localStorage.getItem(PAT_KEY)){authed=true;document.getElementById('authBtn').classList.add('authed');}
var defaultTab='shows';
document.querySelectorAll('.tab').forEach(function(t){t.classList.toggle('active',t.dataset.tab===defaultTab);});
document.querySelectorAll('.panel').forEach(function(p){p.classList.toggle('active',p.id==='panel-'+defaultTab);});
// #107 P2 — delegated artist-name click -> artist modal (survives re-renders)
document.addEventListener('click',function(e){var t=e.target;var b=t&&t.closest?t.closest('.artist-link'):null;if(b&&b.dataset.artist&&typeof openArtistModal==='function')openArtistModal(b.dataset.artist);});
(async function boot(){
  await loadConfig();
  applyConfig(SITE_CONFIG);
  applyTheme(SITE_CONFIG);
  _gearVisible();
  // History (incl. the On-This-Day strip) is lazy now: its 5 files load on first History
  // open, not at boot. Build the empty panel structure; the badge reads — until opened.
  renderHistoryPanel();
})();
loadData();
