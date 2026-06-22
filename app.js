
let OWNER='dan2bit',REPO='live-shows';
const CURRENT_PATH='data/live_shows_current.tsv',POTENTIAL_PATH='data/live_shows_potential.tsv';
const OWNER_PRIVATE='dan2bit',REPO_PRIVATE='live-shows-private',CURRENT_PRIVATE_PATH='current_private.tsv',POTENTIAL_PRIVATE_PATH='potential_private.tsv';
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
  function _asset(p){
    if(!p)return p;
    if(/^https?:\/\//.test(p))return p;
    var base=(s.pages_base||('https://'+OWNER+'.github.io/'+REPO)).replace(/\/+$/,'');
    return base+'/'+String(p).replace(/^\/+/,'');
  }
  function _txt(sel,v){if(v==null)return;var el=document.querySelector(sel);if(el)el.textContent=v;}
  function _attr(sel,a,v){if(v==null)return;var el=document.querySelector(sel);if(el)el.setAttribute(a,v);}
  if(s.favicon){var fav=_asset(s.favicon);document.querySelectorAll('link[rel~="icon"]').forEach(function(l){l.setAttribute('href',fav);});}
  if(s.brand_icon)_attr('.hat-btn img','src',_asset(s.brand_icon));
  if(s.about_handle){_txt('.about-hero-handle',s.about_handle);_attr('.hat-btn','title','About '+s.about_handle);}
  if(s.about_tagline)_txt('.about-hero-tagline',s.about_tagline);
  if(s.about_text)_txt('#aboutModal .about-body p',s.about_text);
  if(s.about_hero_image)_attr('.about-hero-img','src',_asset(s.about_hero_image));
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
        box.appendChild(a);
      });
    }
  }
}
// Feature flags (#82). A flag is ON unless config explicitly sets it to false, so a
// fork that omits the features block — or any single key — keeps full behavior.
function featureOn(name){var f=SITE_CONFIG.features;return !f||f[name]!==false;}
// Merch badge threshold (#82): Face Value at/above which the MERCH badge shows.
function merchEventCap(){var m=SITE_CONFIG.merch;return m&&m.event_cap!=null?m.event_cap:100;}
// Normal Ticket Number (#82 / #87): the owner's usual party size. The authed (X) count
// shows when a show's qty differs from this; the bystander Group/Solo badge is derived
// from a public flag at data-entry time (quantity is private). Default 1 = usually solo.
function normalTicketNumber(){var b=SITE_CONFIG.badges;return b&&b.normal_ticket_number!=null?b.normal_ticket_number:1;}
// Decision-stage display (#82). Stage KEYS are fixed in code (sort order, dropdown, CSS);
// only the display copy is configurable, and stage colors live in the theme block. Falls
// back to the built-in copy so a config without a stages block renders identically.
function stageHeader(key){
  var def={buy:{icon:'\uD83D\uDFE9',label:'Buy',tagline:'not purchased but probably going',sep:' \u2014 '},
           choose:{icon:'\uD83D\uDFE1',label:'Choose',tagline:'shows I am considering',sep:' \u2014 '},
           pass:{icon:'\u25EF',label:'Pass',tagline:'considered, but not going',sep:' - '}}[key]||{sep:' \u2014 '};
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
             ['color_sell','--sell'],['color_pass','--gray'],
             ['color_hat','--hat'],['color_book','--book']];
  pairs.forEach(function(p){
    var base=t[p[0]];if(!base)return;
    var triad=_deriveTriad(base);
    set(base,p[1]);
    set(t[p[0]+'_dim']||triad.dim,p[1]+'-dim');
    set(t[p[0]+'_bg']||triad.bg,p[1]+'-bg');
  });
  // Hat and book badge colors are handled by the pairs loop above (their explicit
  // _dim/_bg in config override the computed triad).
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
  var res=await fetch(url,Object.assign({cache:'no-store'},opts,{headers:Object.assign(headers,opts.headers||{})}));
  if(!res.ok)throw new Error('GitHub API '+res.status+': '+res.statusText);
  return res.json();
}
function _decodeB64(c){return decodeURIComponent(escape(atob(c.replace(/\n/g,''))));
}
async function mergePrivateData(){
  if(!authed||!featureOn('private_data'))return;
  try{
    var cp=await ghFetch(CURRENT_PRIVATE_PATH,{},OWNER_PRIVATE,REPO_PRIVATE),cmap={};
    parseTsv(_decodeB64(cp.content)).forEach(function(r){cmap[(r['Artist']||'')+'\u241F'+(r['Show Date']||'')]=r;});
    currentRows.forEach(function(r){var p=cmap[(r['Artist']||'')+'\u241F'+(r['Show Date']||'')];if(p)CUR_PRIVATE_FIELDS.forEach(function(f){if(p[f]!==undefined)r[f]=p[f];});});
  }catch(e){console.warn('private current merge skipped:',e.message);}
  try{
    var pp=await ghFetch(POTENTIAL_PRIVATE_PATH,{},OWNER_PRIVATE,REPO_PRIVATE),pmap={};
    parseTsv(_decodeB64(pp.content)).forEach(function(r){pmap[(r['Artist']||'')+'\u241F'+(r['Date']||'')]=r;});
    potentialRows.forEach(function(r){var p=pmap[(r['Artist']||'')+'\u241F'+(r['Date']||'')];if(p&&p['Private Notes']!==undefined)r['Private Notes']=p['Private Notes'];});
  }catch(e){console.warn('private potential merge skipped:',e.message);}
}
async function _savePrivateSidecar(path,keyFields,keyVals,field,newVal){
  var pat=localStorage.getItem(PAT_KEY);if(!pat)throw new Error('no auth');
  var fd=await ghFetch(path,{},OWNER_PRIVATE,REPO_PRIVATE);
  var raw=_decodeB64(fd.content);
  var headers=raw.split('\n')[0].split('\t').map(function(h){return h.trim();});
  var rows=parseTsv(raw);
  var fi=rows.findIndex(function(r){return keyFields.every(function(k){return (r[k]||'')===(keyVals[k]||'');});});
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
function formatShowDate(s){var d=parseISODate(s);return d?MONTHS[d.getMonth()]+' '+d.getDate():s;}
function formatShowDateYear(s){var d=parseISODate(s);return d?MONTHS[d.getMonth()]+' '+d.getDate()+', '+d.getFullYear():s;}
function dayOfWeek(s){var d=parseISODate(s);return d?DAYS[d.getDay()]:'';
}
function daysFromNow(s){var d=parseISODate(s);if(!d)return 999;var now=new Date();now.setHours(0,0,0,0);return Math.floor((d-now)/86400000);}
function isOtdMatch(s){var m=(s||'').match(/^\d{4}-(\d{2}-\d{2})/);return m?m[1]===_todayMmDd:false;}
function gcalUrl(artist){var now=new Date(),pad=function(n){return String(n).padStart(2,'0');};return'https://calendar.google.com/calendar/r/search?q='+encodeURIComponent(artist)+'&start='+now.getFullYear()+pad(now.getMonth()+1)+pad(now.getDate())+'&end='+(now.getFullYear()+1)+pad(now.getMonth()+1)+pad(now.getDate());}
function esc(s){return(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
var VENUE_SHORT={'Wolf Trap Filene Center':'Wolf Trap','Rams Head On Stage':'Rams Head','Barns at Wolf Trap':'Barns','Wolf Trap Farm Park (The Barns)':'Barns','Wolf Trap Farm Park (Filene Center)':'Wolf Trap','The State Theatre':'State Theatre','The Birchmere':'Birchmere','Live at Hub City Vinyl':'Hub City','The Anthem':'Anthem'};
function shortVenueName(full){var name=(full||'').split(',')[0].trim();return VENUE_SHORT[name]||name;}

// ── On This Day ──────────────────────────────
async function loadOnThisDay(){
  var now=new Date(),mmdd=String(now.getMonth()+1).padStart(2,'0')+'-'+String(now.getDate()).padStart(2,'0');
  var results=await Promise.allSettled(HISTORY_YEARS.map(function(yr){return ghFetch('data/history/'+yr+'.tsv');}));
  var matches=[];
  results.forEach(function(res){
    if(res.status!=='fulfilled')return;
    var rows=parseTsv(decodeURIComponent(escape(atob(res.value.content.replace(/\n/g,'')))));
    rows.forEach(function(r){if((r['Show Date']||'').trim().endsWith(mmdd))matches.push(r);});
  });
  matches.sort(function(a,b){return(a['Show Date']||'').localeCompare(b['Show Date']||'');});
  var el=document.getElementById('otdItems');
  if(!matches.length){el.innerHTML='<span class="otd-none">no shows on this day</span>';return;}
  el.innerHTML=matches.map(function(r){
    var year=(r['Show Date']||'').slice(0,4),artist=esc(r['Artist']||''),venue=esc((r['Venue']||'').split(',')[0].trim());
    var setlist=r['Setlist.fm URL']||'',playlist=r['Playlist URL']||'';
    var links=(setlist?'<a class="icon-link" href="'+esc(setlist)+'" target="_blank" title="Setlist.fm">♫</a>':'')+(playlist?'<a class="icon-link" href="'+esc(playlist)+'" target="_blank" title="YouTube playlist">▶</a>':'');
    return'<span class="otd-item"><span class="otd-year">'+year+'</span><span class="otd-artist">'+artist+'</span><span class="otd-sep">&middot;</span><span class="otd-venue">'+venue+'</span>'+(links?'<span class="otd-links">'+links+'</span>':'')+'</span>';
  }).join('<span class="otd-sep" style="margin:0 4px">|</span>');
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
function buildBadges(row){
  if(!row['Ticket Access']&&!row['Face Value (per ticket)'])return'';
  var notes=(row['Notes / Memories']||'').toLowerCase(),pvt=(row['Private Notes']||'').toLowerCase(),seat=(row['Seat Info / GA']||'').toLowerCase(),access=(row['Ticket Access']||'').toLowerCase(),all=notes+' '+pvt+' '+seat+' '+access;
  var isVip=(row['VIP']||'').trim().toUpperCase()==='Y',isWT=(row['Venue Name']||'').includes('Wolf Trap Filene');
  var fv=parseFloat((row['Face Value (per ticket)']||'').replace(/[^0-9.]/g,''))||0;
  var badges=[],tl=ticketLabel(row['Ticket Access']||''),label=tl[0],isPaper=tl[1];
  if(label)badges.push('<span class="badge '+(isPaper?'badge-paper':'badge-ticket')+'">'+esc(label)+'</span>');
  if(isVip)badges.push('<span class="badge badge-vip">⭐ VIP</span>');
  if((row['Notes / Memories']||'').includes('HAT:'))badges.push('<span class="badge badge-hat">🎩 HAT</span>');
  if((row['Notes / Memories']||'').includes('BRING RHBS')||(row['Notes / Memories']||'').includes('BRING APS'))badges.push('<span class="badge badge-book">📚 BOOK</span>');
  if(!isVip&&!isWT&&fv>=merchEventCap())badges.push('<span class="badge badge-merch">💸 MERCH</span>');
  if(((row['Notes / Memories']||'')+(row['Private Notes']||'')).toLowerCase().includes('box office'))badges.push('<span class="badge badge-boxoffice">🏣 BOX OFFICE</span>');
  return badges.length?'<div class="badges">'+badges.join('')+'</div>':'';
}
function seatTypeBadge(seatType){var s=(seatType||'').toLowerCase();if(!s)return'';return'<span class="badge badge-seat">'+(s.indexOf('ga')>-1?'GA':'Seated')+'</span>';}
function publicBadges(row){var b=[];if((row['VIP']||'').trim().toUpperCase()==='Y')b.push('<span class="badge badge-vip">⭐ VIP</span>');if((row['Group']||'').trim().toUpperCase()==='Y')b.push('<span class="badge badge-group">👥 Group</span>');return b.length?'<div class="badges">'+b.join('')+'</div>':'';}

// ── setlistIconHtml helper ──────────────────────
function setlistIconHtml(s){
  if(!s||s==='-')return'';
  if(s.startsWith('MULTI:')){var key=s.slice(6);return'<button class="icon-link" style="background:none;border:none;cursor:pointer;padding:0;font-size:13px;" onclick="openMultisetModal(\''+key+'\')" title="Setlists">♫</button>';}
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
  if(switchBtn)switchBtn.textContent='\u2192 '+_fieldLabel(field);
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
      var res=await fetch('https://api.github.com/repos/'+OWNER+'/'+REPO+'/contents/'+CURRENT_PATH,{method:'PUT',headers:{'Accept':'application/vnd.github.v3+json','Authorization':'token '+pat,'Content-Type':'application/json'},body:JSON.stringify({message:'current: update '+msgArtist+' '+field,content:btoa(unescape(encodeURIComponent(serializeTsv(rows,headers)))),sha:fd.sha})});
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
      var res=await fetch('https://api.github.com/repos/'+OWNER+'/'+REPO+'/contents/'+POTENTIAL_PATH,{method:'PUT',headers:{'Accept':'application/vnd.github.v3+json','Authorization':'token '+pat,'Content-Type':'application/json'},body:JSON.stringify({message:'potential: update '+msgArtist+' '+field,content:btoa(unescape(encodeURIComponent(serializeTsv(rows,headers)))),sha:fd.sha})});
      if(!res.ok)throw new Error(await res.text());
    } else if(fileKey==='fasttrack'){
      var fd=await ghFetch(FAST_TRACK_PATH);
      var raw=decodeURIComponent(escape(atob(fd.content.replace(/\n/g,''))));
      var headers=raw.split('\n')[0].split('\t').map(function(h){return h.trim();});
      var rows=parseFastTrack(raw);
      rows[rowIdx][field]=newVal;fastTrackRows[rowIdx][field]=newVal;
      var msgArtist=rows[rowIdx]['Artist']||'artist';
      var res=await fetch('https://api.github.com/repos/'+OWNER+'/'+REPO+'/contents/'+FAST_TRACK_PATH,{method:'PUT',headers:{'Accept':'application/vnd.github.v3+json','Authorization':'token '+pat,'Content-Type':'application/json'},body:JSON.stringify({message:'fast_track: update '+msgArtist+' '+field,content:btoa(unescape(encodeURIComponent(serializeFastTrack(rows,headers)))),sha:fd.sha})});
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
      var res=await fetch('https://api.github.com/repos/'+OWNER+'/'+REPO+'/contents/'+histPath,{method:'PUT',headers:{'Accept':'application/vnd.github.v3+json','Authorization':'token '+pat,'Content-Type':'application/json'},body:JSON.stringify({message:'history: update '+msgArtist+' '+yr+' '+field,content:btoa(unescape(encodeURIComponent(serializeTsv(rows,headers)))),sha:fd.sha})});
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
    +'<td><div class="cell-artist">'+esc(row['Artist'])+'</div>'+(row['Supporting Artist']?'<div class="cell-support">w/ '+esc(row['Supporting Artist'])+'</div>':'')+mv+publicBadges(row)+'</td>'
    +'<td class="cell-venue col-support">'+vh+'</td><td class="cell-seat col-seat">'+sb+'</td>'
    +'<td class="cell-notes">'+(pn?'<div class="notes-text">'+pn+'</div>':'')+'</td></tr>';
}
function renderUpcomingRowAuthed(row,idx,origIdx){
  var days=daysFromNow(row['Show Date']),cls=days<=1?'row-today':days<=7?'row-soon':'';
  var pn=row['Notes / Memories']||'',pvt=row['Private Notes']||'';
  var fn=pvt?pn+(pn?' · ':'')+pvt:pn,fne=esc(fn);
  var vh=row['Venue Event URL']?'<a href="'+esc(row['Venue Event URL'])+'" target="_blank">'+esc(row['Venue Name'])+'</a>':esc(row['Venue Name']);
  var seat=esc(row['Seat Info / GA']||''),qty=parseInt(row['Ticket Quantity']||'1',10);
  var cal=featureOn('calendar_integration')?'<a class="icon-link" href="'+gcalUrl(row['Artist'])+'" target="_blank" title="Google Calendar">📅</a>':'';
  var mv=row['Venue Name']?'<div class="cell-venue-mobile">'+esc(shortVenueName(row['Venue Name']))+(seat?' · '+seat:'')+'</div>':'';
  var cellId='cell-up-'+idx;
  var nh=fne?'<div class="notes-text collapsible" id="n-up-'+idx+'" onclick="toggleNote(this,\'nt-up-'+idx+'\')">'+''+fne+'</div><span class="notes-toggle" id="nt-up-'+idx+'" onclick="toggleNote(document.getElementById(\'n-up-'+idx+'\'),this)">more</span>':'';
  var editBtn=makeEditBtn(cellId,'current',(origIdx!==undefined?origIdx:idx),'Notes / Memories','notes');
  return'<tr class="'+cls+'"><td class="cell-date"><span class="date-text">'+formatShowDate(row['Show Date'])+'</span><span class="day-of-week">'+dayOfWeek(row['Show Date'])+'</span></td>'
    +'<td><div class="cell-artist">'+esc(row['Artist'])+(qty!=normalTicketNumber()?' <span style="font-size:11px;color:var(--text-dim);font-family:var(--mono)">('+row['Ticket Quantity']+')</span>':'')+cal+'</div>'
    +(row['Supporting Artist']?'<div class="cell-support">w/ '+esc(row['Supporting Artist'])+'</div>':'')+mv+buildBadges(row)+'</td>'
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
    +'<td><div class="cell-artist">'+esc(n.artist)+'</div>'+(n.support?'<div class="cell-support">w/ '+esc(n.support)+'</div>':'')
    +'<div class="cell-venue-mobile">'+esc(shortVenueName(n.venueName))+'</div></td>'
    +'<td style="white-space:nowrap">'+(n.setlist?setlistIconHtml(n.setlist):'')
    +(n.playlist?'<a class="icon-link" href="'+esc(n.playlist)+'" target="_blank" title="YouTube playlist">▶</a>':'')
    +(n.photo?'<a class="icon-link" href="'+esc(n.photo)+'" target="_blank" title="Artist photo">📷</a>':'')+'</td>'
    +'<td class="cell-notes">'+nh+'</td></tr>';
}
function renderAttendedRowSearch(row,idx){
  var n=normalizeRow(row);
  var ne=esc(n.notes);
  var nh=ne?'<div class="notes-text collapsible" id="n-sr-'+idx+'" onclick="toggleNote(this,\'nt-sr-'+idx+'\'">'+ne+'</div><span class="notes-toggle" id="nt-sr-'+idx+'" onclick="toggleNote(document.getElementById(\'n-sr-'+idx+'\'),this)">more</span>':'';
  return'<tr><td class="cell-date">'+formatShowDateYear(n.showDate)+'</td>'
    +'<td><div class="cell-artist">'+esc(n.artist)+'</div>'+(n.support?'<div class="cell-support">w/ '+esc(n.support)+'</div>':'')
    +'<div class="cell-venue-mobile">'+esc(shortVenueName(n.venueName))+'</div></td>'
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
    +'<td><div class="cell-artist">'+esc(n.artist)+'</div>'+(n.support?'<div class="cell-support">w/ '+esc(n.support)+'</div>':'')
    +'<div class="cell-venue-mobile">'+esc(shortVenueName(n.venueName))+'</div></td>'
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
      +'<td><div class="cell-artist">'+esc(n.artist)+'</div>'+(n.support?'<div class="cell-support">w/ '+esc(n.support)+'</div>':'')
      +'<div class="cell-venue-mobile">'+esc(shortVenueName(n.venueName))+'</div></td>'
      +'<td style="white-space:nowrap">'+(n.setlist?setlistIconHtml(n.setlist):'')
      +(n.playlist?'<a class="icon-link" href="'+esc(n.playlist)+'" target="_blank" title="YouTube playlist">▶</a>':'')
      +(n.photo?'<a class="icon-link" href="'+esc(n.photo)+'" target="_blank" title="Artist photo">📷</a>':'')+'</td>'
      +'<td class="cell-notes" id="'+cellId+'">'+editBtn+nh+'</td></tr>';
  }).join('');
  return'<div class="history-year-header"><span class="history-year-label">'+yr+'</span><span class="history-year-count">'+sorted.length+' show'+(sorted.length!==1?'s':'')+'</span></div>'
    +'<div class="attended-table"><table class="shows-table"><thead><tr><th style="width:64px">Date</th><th style="width:160px">Artist</th><th style="width:40px">Links</th><th>Notes</th></tr></thead>'
    +'<tbody>'+tbody+'</tbody></table></div>';
}
function hatLoadingHtml(){return'<div class="hat-loading"><img class="hat-loading-img" src="static/brand-hat.png" alt=""><div class="loading loading-dots" style="animation:none">Loading</div></div>';}
async function loadHistoryYear(yr){
  if(historyData[yr]!==null)return;
  try{
    var results=await Promise.all([ghFetch('data/history/'+yr+'.tsv'),new Promise(function(r){setTimeout(r,2400);})]);
    historyData[yr]=parseTsv(decodeURIComponent(escape(atob(results[0].content.replace(/\n/g,'')))));
  }catch(e){historyData[yr]=[];console.error('Failed to load data/history/'+yr+'.tsv:',e);}
}
async function ensureAllYearsLoaded(){
  if(_allYearsLoaded)return;
  var unloaded=HISTORY_YEARS.filter(function(yr){return historyData[yr]===null;});
  if(unloaded.length){
    await Promise.allSettled(unloaded.map(function(yr){return loadHistoryYear(yr);}));
    HISTORY_YEARS.forEach(function(yr){
      var b=document.getElementById('histBadge-'+yr);
      if(b&&historyData[yr])b.textContent=historyData[yr].length;
    });
    var total=HISTORY_YEARS.reduce(function(s,yr){return s+(historyData[yr]?historyData[yr].length:0);},0);
    document.getElementById('historyBadge').textContent=total||'—';
  }
  _allYearsLoaded=true;
  populateSearchDatalists();
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
    var artistOk=!la||(n.artist.toLowerCase().includes(la)||n.support.toLowerCase().includes(la));
    var venueOk=!lv||(n.venueName.toLowerCase().includes(lv)||shortVenueName(n.venueName).toLowerCase().includes(lv));
    return artistOk&&venueOk;
  });
  if(!rows.length){resultsEl.innerHTML='<div class="search-empty">No matches</div>';return;}
  var tbody=rows.map(function(r,i){return renderAttendedRowSearch(r,i);}).join('');
  resultsEl.innerHTML='<div class="search-count">'+rows.length+' match'+(rows.length!==1?'es':'')+'</div>'
    +'<div class="attended-table"><table class="shows-table"><thead><tr>'
    +'<th style="width:80px">Date</th><th>Artist</th><th style="width:40px">Links</th><th>Notes</th>'
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
  if(!_allYearsLoaded){var srchEl=document.getElementById('srchResults');if(srchEl)srchEl.innerHTML=hatLoadingHtml();await ensureAllYearsLoaded();runSearch();}else{var inp=document.getElementById('srchArtist');if(inp&&!inp.value)inp.focus();else runSearch();}
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
  var an=r['BIT URL']&&r['BIT URL']!=='-'?'<a href="'+esc(r['BIT URL'])+'" target="_blank" style="color:inherit;text-decoration:none">'+esc(r['Artist'])+'</a>':esc(r['Artist']);
  return'<tr class="row-'+cls+'"><td style="white-space:nowrap"><span class="cell-decision-ro '+cls+'">'+esc(dec)+'</span></td>'
    +'<td class="cell-date"><span class="date-text">'+formatShowDate(r['Date'])+'</span><span class="day-of-week">'+dayOfWeek(r['Date'])+'</span></td>'
    +'<td><div class="cell-artist">'+an+((r['Notes']||'').includes('HAT:')?'<span class="badge badge-hat" style="margin-left:6px">🎩 HAT</span>':'')+'</div>'+(r['Support']?'<div class="cell-support">w/ '+esc(r['Support'])+'</div>':'')+'</td>'
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
  if(isSell){dh='<span class="cell-decision-ro sell">'+esc(dec)+'</span><button class="revoke-btn" onclick="handleRevoke('+gi+')" title="Remove listing">&#10005; revoke</button>';}
  else{var opts=['Buy','Choose','Pass'].map(function(v){return'<option value="'+v+'"'+(dec.toLowerCase().startsWith(v.toLowerCase())?' selected':'')+'>'+v+'</option>';}).join('');dh='<select class="decision-select" data-row="'+gi+'" onchange="handleDecisionChange(this)">'+opts+'</select><span class="save-indicator" id="save-'+gi+'"></span>';}
  var pu=r['Purchase URL']||'',sl=isSell?pu:((dec.toLowerCase().startsWith('buy')||dec.toLowerCase()==='choose')&&pu),ph=esc(r['Face Price']||'');
  if(sl)ph+=' <a class="icon-link" href="'+esc(pu)+'" target="_blank" title="'+(isSell?'View listing':'Buy tickets')+'">🎟</a>';
  var an=r['BIT URL']&&r['BIT URL']!=='-'?'<a href="'+esc(r['BIT URL'])+'" target="_blank" style="color:inherit;text-decoration:none">'+esc(r['Artist'])+'</a>':esc(r['Artist']);
  return'<tr class="row-'+dec.toLowerCase()+'"><td style="white-space:nowrap">'+dh+'</td>'
    +'<td class="cell-date"><span class="date-text">'+formatShowDate(r['Date'])+'</span><span class="day-of-week">'+dayOfWeek(r['Date'])+'</span></td>'
    +'<td><div class="cell-artist">'+an+((r['Notes']||'').includes('HAT:')?'<span class="badge badge-hat" style="margin-left:6px">🎩 HAT</span>':'')+'</div>'+(r['Support']?'<div class="cell-support">w/ '+esc(r['Support'])+'</div>':'')+'</td>'
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
  var aTableHead=authed?'<thead><tr><th>Date</th><th>Artist</th><th>Links</th><th class="col-cost">Cost</th><th>Notes</th></tr></thead>':'<thead><tr><th>Date</th><th>Artist</th><th>Links</th><th>Notes</th></tr></thead>';
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
    var res=await fetch('https://api.github.com/repos/'+OWNER+'/'+REPO+'/contents/'+POTENTIAL_PATH,{method:'PUT',headers:{'Accept':'application/vnd.github.v3+json','Authorization':'token '+pat,'Content-Type':'application/json'},body:JSON.stringify({message:'potential: remove '+artist+' Sell row (revoked)',content:btoa(unescape(encodeURIComponent(serializeTsv(rows,headers)))),sha:fd.sha})});
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
    var res=await fetch('https://api.github.com/repos/'+OWNER+'/'+REPO+'/contents/'+POTENTIAL_PATH,{method:'PUT',headers:{'Accept':'application/vnd.github.v3+json','Authorization':'token '+pat,'Content-Type':'application/json'},body:JSON.stringify({message:'potential: update '+(potentialRows[idx]['Artist']||'')+' decision',content:btoa(unescape(encodeURIComponent(serializeTsv(rows,headers)))),sha:fd.sha})});
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
  var thead='<thead><tr><th style="width:170px">Artist</th><th style="width:80px">Tier</th><th>Why</th><th style="width:110px">Links</th></tr></thead>';
  var tbody=fastTrackRows.map(function(r,ri){
    var tier=r['Tier']||'',tierCls=tier.toLowerCase().includes('strong')&&tier.toLowerCase().includes('medium')?'tier-medium-strong':tier==='Strong'?'tier-strong':'tier-medium';
    var isHat=(r['Notes']||'').toLowerCase().includes('female artist');
    var isFirst=(r['First Tour']||'').trim().toUpperCase()==='Y';
    var tourUrl=r['Tour URL']||r['BIT URL']||'';
    var spotUrl=r['Spotify URL']||'';
    return'<tr><td><div class="ft-artist">'+esc(r['Artist']||'')+(isHat?' <span class="badge badge-hat">🎩 HAT</span>':'')+(isFirst?' <span class="badge badge-first">1st</span>':'')+'</div></td>'
      +'<td><span class="cell-tier '+tierCls+'">'+esc(tier)+'</span></td>'
      +'<td><div class="ft-why" id="cell-ft-why-'+ri+'">'+makeEditBtn('cell-ft-why-'+ri,'fasttrack',ri,'Why Fast Track','Why')+esc(r['Why Fast Track']||'')+'</div></td>'
      +'<td><div class="ft-links">'+(tourUrl?'<a class="ft-link ft-link-tour" href="'+esc(tourUrl)+'" target="_blank">Tour &#8599;</a>':'')+(spotUrl?'<a class="ft-link ft-link-sp" href="'+esc(spotUrl)+'" target="_blank">Spotify</a>':'')+'</div></td>'
      +'</tr>';
  }).join('');
  document.getElementById('tourhereBadge').textContent=fastTrackRows.length;
  document.getElementById('tourhereContent').innerHTML=banner+'<table class="ft-table">'+thead+'<tbody>'+tbody+'</tbody></table>';
}
async function loadTourHere(){
  if(fastTrackRows.length){renderTourHere();return;}
  try{
    var fd=await ghFetch(FAST_TRACK_PATH);
    var raw=decodeURIComponent(escape(atob(fd.content.replace(/\n/g,''))));
    fastTrackRows=parseFastTrack(raw);
    renderTourHere();
  }catch(e){
    document.getElementById('tourhereContent').innerHTML='<div class="error-msg">Error loading fast_track.tsv: '+esc(e.message)+'</div>';
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
function switchTab(name){
  document.querySelectorAll('.tab').forEach(function(t){t.classList.toggle('active',t.dataset.tab===name);});
  document.querySelectorAll('.panel').forEach(function(p){p.classList.toggle('active',p.id==='panel-'+name);});
  if(name==='history'){var mr=HISTORY_YEARS[HISTORY_YEARS.length-1];if(historyData[mr]===null){switchHistoryTab(mr);}else{requestAnimationFrame(revealToggles);}}
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
    var res=await fetch('https://api.github.com/repos/'+OWNER+'/'+REPO+'/contents/config.yaml',{method:'PUT',headers:{'Accept':'application/vnd.github.v3+json','Authorization':'token '+pat,'Content-Type':'application/json'},body:JSON.stringify({message:'config: edit via in-page editor',content:btoa(unescape(encodeURIComponent(ta.value))),sha:fd.sha})});
    if(!res.ok)throw new Error(await res.text());
    st.textContent='committed - live ~1 min after Pages redeploys';_cfgDraft=null;
  }catch(e){st.textContent='commit failed: '+e.message;}
}
// ── Boot ───────────────────────────────────────────────
async function loadData(){
  document.getElementById('showsContent').innerHTML='<div class="loading">Loading</div>';
  document.getElementById('potContent').innerHTML='<div class="loading">Loading</div>';
  try{
    var results=await Promise.all([ghFetch(CURRENT_PATH),ghFetch(POTENTIAL_PATH)]);
    currentRows=parseTsv(_decodeB64(results[0].content));
    potentialRows=parseTsv(_decodeB64(results[1].content));
    await mergePrivateData();
    renderShows();renderPotential();
    document.getElementById('fetchedAt').textContent='fetched '+new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
  }catch(e){var msg='<div class="error-msg">Error: '+esc(e.message)+'</div>';document.getElementById('showsContent').innerHTML=msg;document.getElementById('potContent').innerHTML=msg;}
}
if(localStorage.getItem(PAT_KEY)){authed=true;document.getElementById('authBtn').classList.add('authed');}
var defaultTab='shows';
document.querySelectorAll('.tab').forEach(function(t){t.classList.toggle('active',t.dataset.tab===defaultTab);});
document.querySelectorAll('.panel').forEach(function(p){p.classList.toggle('active',p.id==='panel-'+defaultTab);});
(async function boot(){
  await loadConfig();
  applyConfig(SITE_CONFIG);
  applyTheme(SITE_CONFIG);
  _gearVisible();
  var mr=HISTORY_YEARS[HISTORY_YEARS.length-1];
  if(!authed)await loadHistoryYear(mr);
  renderHistoryPanel();
  if(!authed)requestAnimationFrame(revealToggles);
  if(authed&&historyData[mr]!==null){var _panel=document.getElementById('inner-hist-'+mr);if(_panel){_panel.innerHTML=renderHistoryYear(mr);requestAnimationFrame(revealToggles);}}
})();
loadData();
loadOnThisDay();
