// ── Artist modal / #artist/{slug} view ─────────────────────────
// Isolated module (option a): lazy index load + render + overlay modal + a hash
// route. Reads the prebuilt data/artist_modal_index.json (build_artist_index.py).
// Render implements the approved "v3 unified" design: identity header → Artist
// group (listener meter, latest release + play, similar, links) → bezelled
// "@owner & this artist" footer (taste-tier meter, history/considering, brand-hat
// favorite gauge). This phase uses a square oEmbed avatar beside the name in
// place of the full-bleed banner.
//
// Globals from app.js: esc, featureOn, SITE_CONFIG, _assetUrl, currentRows,
// potentialRows. Own name-normalizer so it never depends on recommend.js.
// The issue history behind these designs is logged in docs/ISSUE_LOG.md.
var AM_INDEX_PATH='data/artist_modal_index.json';
var amIndexCache=null,amSlugMap=null,amRouting=false;
// Explicit favorite — PUBLIC data (data/artist_favorites.tsv in this repo; a
// deliberate privacy reversal — see docs/ISSUE_LOG.md). The pinned gauge + star
// are visible to ALL viewers, bystanders included; only the promote/remove CONTROL
// is authed. Reads ride the Pages CDN; writes follow the standard public-TSV
// pattern (fresh sha, PUT with branch:dataBranch() -> staging -> auto-promote).
var AM_FAV_PATH='data/artist_favorites.tsv';
var amFavCache=null;   // {amNorm(Artist): row} - loaded for all viewers when features.favorite is on
// Artist status — PUBLIC, curated, and entirely optional (data/artist_status.tsv).
// Sparse by design: a row exists only for an artist who is no longer active, so
// absence means active, and a missing or header-only file is a silent no-op. The
// modal renders one muted line under the name; nothing else in the site reads it.
var AM_STATUS_PATH='data/artist_status.tsv';
var amStatusCache=null;   // {amNorm(Artist): row}
// Kinship cross-links — PUBLIC, hand-maintained (data/related_acts.tsv).
// One row per membership/kinship relation co-listening data can't see (fronts,
// member-of, successor-of, sibling...). Read at render time like status/favorites;
// resolved against the already-loaded index, so a row whose endpoint isn't a tracked
// artist is silently skipped. This is a DISPLAY layer over act-level data — it never
// merges rows or alters any times_seen count (person-level view, act-level storage).
var AM_RELATED_PATH='data/related_acts.tsv';
var amRelatedCache=null;   // {amNorm(Artist): [{other:amNorm, rel, selfIsA}]} - bidirectional adjacency
// Mirrors build_artist_index.py norm(): de-invert "Lone Bellow, The", de-accent,
// drop one leading article, punctuation -> space, collapse whitespace.
function amNorm(s){
  s=(s||'').trim();
  var m=s.match(/^(.*),\s+(the|a|an)$/i);
  if(m)s=m[2]+' '+m[1];
  s=s.normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  s=s.replace(/^\s*(the|a|an)\s+/,'');
  s=s.replace(/[^a-z0-9 ]+/g,' ').replace(/\s+/g,' ').trim();
  return s;
}
function amSlugify(k){return amNorm(k).replace(/ /g,'-');}
async function amLoadIndex(){
  if(amIndexCache)return amIndexCache;
  var res=await fetch(AM_INDEX_PATH+'?t='+Date.now(),{cache:'no-store'});   // relative -> Pages CDN, no API rate limit; cache-busted
  if(!res.ok)throw new Error('HTTP '+res.status);
  var data=await res.json();
  amIndexCache=data;
  amSlugMap={};
  var arts=data.artists||{},k;
  for(k in arts){if(Object.prototype.hasOwnProperty.call(arts,k)){var sl=arts[k]&&arts[k].slug;if(sl)amSlugMap[sl]=k;}}
  return data;
}
// ── open / close / route ──
function amBody(html){var b=document.getElementById('artistModalBody');if(b)b.innerHTML=html;}
function amShow(){document.getElementById('artistModal').classList.add('open');}
function amHide(){document.getElementById('artistModal').classList.remove('open');}
function amErr(msg){return'<div class="am-loose"><p class="am-err">'+esc(msg)+'</p>'
  +'<div class="am-actions"><button class="btn" onclick="closeArtistModal()">Close</button></div></div>';}
async function openArtistModal(name){
  amShow();
  amBody('<div class="am-loose am-loading">'+amHatImg('am-hat-mini')+'<span>Loading\u2026</span></div>');
  var data;try{data=await amLoadIndex();}catch(e){amBody(amErr('Couldn\u2019t load artist data \u2014 please try again.'));return;}
  await amLoadFavorites();
  await amLoadStatus();
  await amLoadRelated();
  var key=amNorm(name),rec=(data.artists||{})[key]||null;
  if(!rec&&data.aliases&&data.aliases[key]){key=data.aliases[key];rec=(data.artists||{})[key]||null;}
  amOpenRec(rec,name,key);
}
async function openArtistBySlug(slug){
  amShow();
  amBody('<div class="am-loose am-loading">'+amHatImg('am-hat-mini')+'<span>Loading\u2026</span></div>');
  var data;try{data=await amLoadIndex();}catch(e){amBody(amErr('Couldn\u2019t load artist data \u2014 please try again.'));return;}
  await amLoadFavorites();
  await amLoadStatus();
  await amLoadRelated();
  var key=(amSlugMap||{})[slug]||null,rec=key?data.artists[key]:null;
  amOpenRec(rec,rec?rec.name:slug.replace(/-/g,' '),key||slug);
}
function amOpenRec(rec,displayName,key){
  var slug=(rec&&rec.slug)||amSlugify(key);
  amBody(amRender(rec,displayName,key));
  amSetHash(slug);
}
function amSetHash(slug){
  var want='#artist/'+slug;
  if((location.hash||'')===want)return;
  amRouting=true;
  try{location.hash=want;}finally{setTimeout(function(){amRouting=false;},0);}
}
function closeArtistModal(){
  amHide();
  if(/^#artist\//.test(location.hash||'')){
    try{history.replaceState(null,'',location.pathname+location.search);}catch(e){amRouting=true;location.hash='';setTimeout(function(){amRouting=false;},0);}
  }
}
function amOnHashChange(){
  if(amRouting)return;
  var m=(location.hash||'').match(/^#artist\/(.+)$/);
  if(m)openArtistBySlug(decodeURIComponent(m[1]));
  else if(document.getElementById('artistModal').classList.contains('open'))amHide();
}
// ── helpers ──
function amHatImg(cls){
  var bi=(SITE_CONFIG.site&&SITE_CONFIG.site.brand_icon)||'static/brand-hat.png';
  var url=(typeof _assetUrl==='function')?_assetUrl(bi):bi;
  return'<img class="'+(cls||'')+'" src="'+esc(url)+'" alt="">';
}
function amHatUrl(){
  var bi=(SITE_CONFIG.site&&SITE_CONFIG.site.brand_icon)||'static/brand-hat.png';
  return(typeof _assetUrl==='function')?_assetUrl(bi):bi;
}
function amDays(date){var d=Date.parse(date);if(isNaN(d))return null;return Math.ceil((d-Date.now())/86400000);}
function amYear(d){var m=(d||'').match(/(\d{4})/);return m?m[1]:'';}
function amCap(s){s=s||'';return s.charAt(0).toUpperCase()+s.slice(1);}
// Delegate to app.js's shared venue resolution (aliases + Short Name);
// fall back to plain truncation if app.js isn't loaded.
function amVenueShort(v){return typeof shortVenueName==='function'?shortVenueName(v):String(v||'').split(',')[0].trim();}
// Row-local context from the already-loaded show arrays.
function amRowContext(key){
  var up=null,con=null;
  try{
    (currentRows||[]).forEach(function(r){if((r['Status']||'')==='upcoming'&&amNorm(r['Artist']||'')===key)up={date:r['Show Date']||'',venue:r['Venue Name']||''};});
    (potentialRows||[]).forEach(function(r){if(!con&&amNorm(r['Artist']||'')===key)con={date:r['Date']||'',venue:r['Venue']||'',decision:r['Decision']||''};});
  }catch(e){}
  return{upcoming:up,considering:con};
}
// ── Explicit favorite (gauge is the CTA; floor = the affinity gate) ──
// Design intent: no hard band floor —
// the control rides the gauge, which only renders when affinity is non-null, so
// zero-relationship artists never see it. One-click promote at/above
// favorite.confirm_below_band (default high); an evidence-quoting confirm below.
function amFavCfg(){
  var f=SITE_CONFIG.favorite||{};
  return{enabled:featureOn('favorite'),pin:f.pin_to_full!==false,confirmBelow:f.confirm_below_band||'high'};
}
async function amLoadFavorites(){
  if(amFavCache)return amFavCache;
  amFavCache={};
  if(!amFavCfg().enabled)return amFavCache;
  try{
    var res=await fetch(AM_FAV_PATH+'?t='+Date.now(),{cache:'no-store'});   // Pages CDN - no API, no auth, all viewers
    if(res.ok)parseTsv(await res.text()).forEach(function(r){var k=amNorm(r['Artist']||'');if(k)amFavCache[k]=r;});
  }catch(e){console.warn('favorites load skipped:',e.message);}
  return amFavCache;
}
// Read-only, low-churn, no auth: a plain relative fetch off the Pages CDN. Any
// failure (absent file included) leaves the map empty and the modal unchanged.
async function amLoadStatus(){
  if(amStatusCache)return amStatusCache;
  amStatusCache={};
  try{
    var res=await fetch(AM_STATUS_PATH+'?t='+Date.now(),{cache:'no-store'});
    if(res.ok)parseTsv(await res.text()).forEach(function(r){var k=amNorm(r['Artist']||'');if(k)amStatusCache[k]=r;});
  }catch(e){console.warn('artist status load skipped:',e.message);}
  return amStatusCache;
}
// Read-only, low-churn, no auth: a plain relative fetch off the Pages CDN, same
// shape as amLoadStatus. Builds a bidirectional adjacency keyed by amNorm(name),
// recording for each edge which side of the A|B pair this endpoint is (selfIsA),
// so the render phrasing can stay directional. Any failure leaves the map empty
// and the modal unchanged.
async function amLoadRelated(){
  if(amRelatedCache)return amRelatedCache;
  amRelatedCache={};
  try{
    var res=await fetch(AM_RELATED_PATH+'?t='+Date.now(),{cache:'no-store'});
    if(res.ok){
      parseTsv(await res.text()).forEach(function(r){
        var a=amNorm(r['Artist A']||''),b=amNorm(r['Artist B']||''),rel=(r['Relation']||'').trim();
        if(!a||!b||!rel)return;
        (amRelatedCache[a]=amRelatedCache[a]||[]).push({other:b,rel:rel,selfIsA:true});
        (amRelatedCache[b]=amRelatedCache[b]||[]).push({other:a,rel:rel,selfIsA:false});
      });
    }
  }catch(e){console.warn('related acts load skipped:',e.message);}
  return amRelatedCache;
}
// Directional relation phrasing. For a row "A <rel> B": the individual is A, the
// band/successor is B. On A's panel we phrase from A's side; on B's panel, the
// reverse. sibling is symmetric. Unknown relations fall back to a neutral form.
var AM_REL_PHRASE={
  'fronts':        ['fronts',            'fronted by'],
  'member-of':     ['member of',         'features'],
  'former-member': ['former member of',  'formerly featured'],
  'successor-of':  ['successor to',      'succeeded by'],
  'sibling':       ['sibling of',        'sibling of']
};
function amRelPhrase(rel,selfIsA){
  var p=AM_REL_PHRASE[rel];
  if(!p)return'related to';
  return selfIsA?p[0]:p[1];
}
// Resolve this artist's related-act edges to tracked records only (skip rule:
// an endpoint absent from the index is dropped). Returns display-ready entries.
function amRelatedFor(key){
  var edges=(amRelatedCache&&amRelatedCache[key])||[];
  if(!edges.length||!amIndexCache)return[];
  var arts=amIndexCache.artists||{},out=[],seenSlugs={};
  edges.forEach(function(e){
    var other=arts[e.other];
    if(!other||!other.slug)return;                 // endpoint not tracked -> skip
    if(seenSlugs[other.slug])return;               // de-dupe (e.g. two rows to same act)
    seenSlugs[other.slug]=1;
    out.push({
      name:other.name||'',
      slug:other.slug,
      phrase:amRelPhrase(e.rel,e.selfIsA),
      seen:(other.seen&&other.seen.count)||0
    });
  });
  return out;
}
function amIsFav(key){return !!(amFavCache&&amFavCache[key]);}
// Gauge click: toggle favorite, with confirm friction below the configured band and on remove.
async function amFavClick(key){
  var cfg=amFavCfg();
  if(!cfg.enabled||!authed)return;
  await amLoadFavorites();
  var data=await amLoadIndex(),rec=(data.artists||{})[key];
  if(!rec||!rec.affinity)return;   // gauge floor: no scored relationship, no favorite
  var name=rec.name||key;
  try{
    if(amIsFav(key)){
      if(!confirm('Remove '+name+' from favorites?\nThe gauge returns to its earned value ('+(rec.affinity.score||0)+').'))return;
      delete amFavCache[key];
      await amFavSave('favorites: remove '+name);
    }else{
      var rank={low:0,medium:1,high:2},a=rec.affinity;
      var cut=rank[cfg.confirmBelow]!==undefined?rank[cfg.confirmBelow]:2;
      if((rank[a.band]||0)<cut){
        var seen=(rec.seen&&rec.seen.count)||0,nfav=Object.keys(amFavCache).length;
        if(!confirm('Pin '+name+' to full favorite?\n\nSeen '+seen+'\u00d7 \u00b7 affinity '+a.score+' ('+a.band+')\nThis would be favorite #'+(nfav+1)+'.'))return;
      }
      amFavCache[key]={'Artist':name,'Since':new Date().toISOString().slice(0,10)};
      await amFavSave('favorites: add '+name);
    }
    amOpenRec(rec,name,key);   // re-render with the new state
  }catch(e){console.error(e);}
}
async function amFavSave(message){
  // PUBLIC write: the standard in-page TSV pattern — fresh sha via the API, full-file
  // PUT with branch:dataBranch() so the commit rides staging -> guard -> auto-promote
  // (same flow as decision changes / notes edits; see DATA_WRITE_PROTOCOLS.md).
  var pat=localStorage.getItem(PAT_KEY);if(!pat)throw new Error('no auth');
  var sha=null;
  try{var fd=await ghFetch(AM_FAV_PATH,{},OWNER,REPO);sha=fd.sha;}catch(e){}
  var rows=Object.keys(amFavCache).sort().map(function(k){return amFavCache[k];});
  var body={message:message,content:btoa(unescape(encodeURIComponent(serializeTsv(rows,['Artist','Since'])))),branch:dataBranch()};
  if(sha)body.sha=sha;
  var res=await fetch('https://api.github.com/repos/'+OWNER+'/'+REPO+'/contents/'+AM_FAV_PATH,
    {method:'PUT',headers:{'Accept':'application/vnd.github.v3+json','Authorization':'token '+pat,'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!res.ok){var t=await res.text();alert('Favorite save failed: '+t);throw new Error(t);}
}
// ── render ──
function amRender(rec,displayName,key){
  if(!rec)return amUnknown(displayName,key);
  var spotify=featureOn('spotify');
  var h='<div class="am-card">';
  h+='<button class="am-close" onclick="closeArtistModal()" aria-label="Close">\u2715</button>';
  // Identity header (square-avatar fallback for the banner)
  h+='<div class="am-head">';
  h+=rec.image_url
    ?'<div class="am-avatar am-avatar-photo"><img class="am-photo" src="'+esc(rec.image_url)+'" alt="'+esc(rec.name||'')+'" referrerpolicy="no-referrer"></div>'
    :'<div class="am-avatar">'+amHatImg('am-hat-fallback')+'</div>';
  h+='<div class="am-id"><div class="am-name">'+esc(rec.name||displayName||'')+'</div>';
  h+=amStatusLine(rec.name||displayName||'');
  if(rec.genres&&rec.genres.length)
    h+='<div class="am-genres">'+rec.genres.slice(0,4).map(function(g){return'<span class="am-genre">'+esc(g)+'</span>';}).join('')+'</div>';
  h+='</div></div>';
  // Artist group band (label + rule + listener meter)
  h+='<div class="am-band"><span class="am-band-lbl">Artist</span><span class="am-rule"></span>'+amListenerMeter(rec.listener)+'</div>';
  if(spotify)h+=amRelease(rec.latest_release);
  if(spotify)h+=amSimilar(rec.similar);
  h+=amRelated(key);
  h+=amLinks(rec.links,spotify);
  h+=amYou(rec,key);
  return h+'</div>';
}
function amUnknown(displayName,key){
  return'<div class="am-card"><button class="am-close" onclick="closeArtistModal()" aria-label="Close">\u2715</button>'
    +'<div class="am-head"><div class="am-avatar">'+amHatImg('am-hat-fallback')+'</div>'
    +'<div class="am-id"><div class="am-name">'+esc(displayName||'Unknown')+'</div>'
    +amStatusLine(displayName||'')
    +'<div class="am-none">No details on file yet.</div></div></div>'
    +amRowOnly(key)
    +'<div class="am-links"><a class="am-link" href="https://open.spotify.com/search/'+encodeURIComponent(displayName||'')+'" target="_blank">Search Spotify</a></div></div>';
}
function amRowOnly(key){
  var r=amRowContext(key);if(!r.upcoming&&!r.considering)return'';
  var h='<div class="am-sec">';
  if(r.upcoming)h+='<div class="am-next-inline">\ud83c\udf9f Upcoming \u2014 '+esc(r.upcoming.date)+(r.upcoming.venue?' \u00b7 '+esc(amVenueShort(r.upcoming.venue)):'')+'</div>';
  if(r.considering)h+='<div class="am-next-inline">\ud83d\udc40 Considering \u2014 '+esc(r.considering.date||'TBD')+(r.considering.venue?' \u00b7 '+esc(r.considering.venue):'')+'</div>';
  return h+'</div>';
}
// One muted line under the artist name for an artist who is no longer active:
// "d." plus the year for deceased, "disbanded"/"retired" plus the year for an act
// that has stopped. Deliberately not a badge — the wording alone separates the
// states, so no color coding is needed at this size. An optional Note rides along
// as the tooltip. Status Date is the year source, with the closing year of Years
// as the fallback so a row carrying only a lifespan still renders.
function amStatusLine(name){
  var r=amStatusCache&&amStatusCache[amNorm(name||'')];
  if(!r)return'';
  var st=(r['Status']||'').toLowerCase();if(!st)return'';
  var yrs=(r['Years']||'').trim(),when=amYear(r['Status Date']||''),txt='';
  if(st==='deceased'){var dy=when||amYear(yrs.split('-').pop()||'');txt=dy?'d. '+dy:'';}
  else if(st==='defunct')txt='disbanded'+(when?' '+when:'');
  else if(st==='retired')txt='retired'+(when?' '+when:'');
  if(!txt)return'';
  var note=(r['Note']||'').trim();
  return'<div class="am-status am-status-'+esc(st)+'"'+(note?' title="'+esc(note)+'"':'')+'>'+esc(txt)+'</div>';
}
// 5-bar listener meter (emerging<niche<mid<popular<major). Null -> omit.
var AM_TRANCHES=['emerging','niche','mid','popular','major'];
function amListenerMeter(l){
  if(!l||!l.tranche)return'';
  var idx=AM_TRANCHES.indexOf(l.tranche),lvl=idx<0?0:idx+1,bars='';
  for(var i=1;i<=5;i++)bars+='<span class="am-bar'+(i<=lvl?' on':'')+'"></span>';
  var raw=l.raw?Number(l.raw).toLocaleString():'';
  return'<span class="am-meter" title="'+esc(raw)+' Last.fm listeners">'
    +'<span class="am-bars">'+bars+'</span>'
    +'<span class="am-meter-lbl">'+esc(l.tranche)+'</span></span>';
}
// 4-bar taste-tier meter (rank 1-4). No rank -> omit.
function amTierMeter(t){
  if(!t||!t.rank)return'';
  var bars='';for(var i=1;i<=4;i++)bars+='<span class="am-bar'+(i<=t.rank?' on':'')+'"></span>';
  return'<span class="am-meter" title="Your taste tier \u2014 how much you like them, independent of popularity">'
    +'<span class="am-meter-k">tier</span>'
    +'<span class="am-bars">'+bars+'</span>'
    +'<span class="am-meter-lbl">'+esc(t.label||'')+'</span></span>';
}
function amRelease(lr){
  if(!lr||!lr.name)return'';
  var art=lr.image_url
    ?'<img class="am-rel-art" src="'+esc(lr.image_url)+'" alt="" referrerpolicy="no-referrer">'
    :'<div class="am-rel-art am-rel-art-ph"><span>album<br>art</span></div>';
  var play=lr.url?'<a class="am-play" href="'+esc(lr.url)+'" target="_blank" title="Play on Spotify" aria-label="Play on Spotify">\u25b6</a>':'';
  var meta=amCap(lr.type||'release')+(amYear(lr.date)?' \u00b7 '+amYear(lr.date):'');
  return'<div class="am-sec"><div class="am-sec-h">Latest release</div>'
    +'<div class="am-release">'+art
    +'<div class="am-rel-body"><div class="am-rel-name">'+esc(lr.name)+'</div>'
    +'<div class="am-rel-meta"><span>'+esc(meta)+'</span>'+play+'</div></div></div></div>';
}
function amSimilar(sim){
  sim=sim||[];if(!sim.length)return'';
  var chips=sim.slice(0,8).map(function(s){
    if(s.in_tracker&&s.slug)return'<button class="am-sim am-sim-in" title="tracked artist \u2014 open artist" onclick="openArtistBySlug(\''+esc(s.slug)+'\')"><span class="am-sim-dot"></span>'+esc(s.name)+'</button>';
    return'<a class="am-sim" title="Last.fm" href="https://www.last.fm/search?q='+encodeURIComponent(s.name||'')+'" target="_blank">&#x1F517; '+esc(s.name)+'</a>';
  }).join('');
  return'<div class="am-sec"><div class="am-sec-h">Similar</div><div class="am-simrow">'+chips+'</div></div>';  return'<div class="am-sec"><div class="am-sec-h">Similar <span class="am-sec-note">\u00b7 \u25cf tracked artist</span></div><div class="am-simrow">'+chips+'</div></div>';
}
// Related acts (kinship from related_acts.tsv). Sits beside "Similar" as an
// identity fact about the act — NOT in the personal footer, since kinship isn't
// about @owner's relationship to them. Each chip opens the related act; when that
// act is itself in the seen history, its own count rides along ("seen 3x"). Counts
// are never summed across the edge — that would double-count siblings and misread
// lineage as identity. Directional phrasing via amRelPhrase.
function amRelated(key){
  var rel=amRelatedFor(key);
  if(!rel.length)return'';
  var chips=rel.map(function(r){
    var seen=r.seen>0?'<span class="am-rel-seen">seen '+r.seen+'\u00d7</span>':'';
    return'<button class="am-sim am-sim-in am-rel-chip" title="kinship \u2014 open artist" onclick="openArtistBySlug(\''+esc(r.slug)+'\')">'
      +'<span class="am-rel-dot"></span>'
      +'<span class="am-rel-verb">'+esc(r.phrase)+'</span> '+esc(r.name)+seen+'</button>';
  }).join('');
  return'<div class="am-sec"><div class="am-sec-h">Related acts</div><div class="am-simrow">'+chips+'</div></div>';
}
function amLinks(L,spotify){
  L=L||{};var items=[];
  function add(url,label){if(url)items.push('<a class="am-link" href="'+esc(url)+'" target="_blank">'+label+'</a>');}
  if(spotify)add(L.spotify,'Spotify');
  add(L.bandsintown,'Bandsintown');
  add(L.seated,'Seated');
  add(L.qobuz,'Qobuz');
  if(spotify){add(L.lastfm,'Last.fm');}
  add(L.setlistfm,'setlist.fm');
  if(L.youtube)items.push('<a class="am-link" href="'+esc(amYouTubeUrl(L.youtube))+'" target="_blank">YouTube</a>');
  if(spotify)add(L.musicbrainz,'MusicBrainz');
  if(!items.length)return'';
  return'<div class="am-sec"><div class="am-sec-h">Artist links</div><div class="am-links">'+items.join('')+'</div></div>';
}
function amYouTubeUrl(y){return/^https?:/.test(y)?y:('https://www.youtube.com/'+(y.charAt(0)==='@'?y:('@'+y)));}
// ── "@owner & this artist" bezelled footer ──
function amYou(rec,key){
  var b=rec.badges||{},s=rec.seen||{},n=s.count||0;
  var hatEligible=b.hat!=='absent';
  var rows=amRowContext(key),considering=rows.considering;
  if(!(n>0||considering||hatEligible||rec.affinity)){
    // 1e edge case: hat-ineligible, never seen, not considering -> no personal panel
    return'<div class="am-minimal">Never seen \u2014 no personal panel yet.</div>';
  }
  var head='<div class="am-you-head"><span class="am-you-dot"></span>'
    +'<span class="am-you-lbl">'+esc('@'+OWNER)+' &amp; this artist</span><span class="am-rule"></span>'
    +amTierMeter(rec.tier)+'</div>';
  var main='<div class="am-you-main">'+amYouBadges(rec,rows,hatEligible)+amYouHistory(rec,rows)+'</div>';
  var gauge=rec.affinity?amGauge(rec.affinity,rec,key):'';
  return'<div class="am-you">'+head+'<div class="am-you-body">'+main+gauge+'</div></div>';
}
// Personal-footer badge strip: seen count, hat/book/VIP/photo, next-show countdown, fast-track.
function amYouBadges(rec,rows,hatEligible){
  var b=rec.badges||{},s=rec.seen||{},n=s.count||0,out=[];
  var viaOnly=n>0&&(s.show_log||[]).every(function(x){return x.via;});
  if(n>0&&!viaOnly)out.push('<span class="am-seen">Seen <b>'+n+'\u00d7</b></span>');
  if(hatEligible){
    if(b.hat==='completed')out.push('<span class="am-b-hat am-b-hat-yes"><img src="'+esc(amHatUrl())+'" alt="hat">signed \u2713</span>');
    else out.push('<span class="am-b-hat am-b-hat-no"><img src="'+esc(amHatUrl())+'" alt="hat">hat \u2014 not signed yet</span>');
  }
  if(b.book==='completed')out.push('<span class="am-b-book"><span class="am-book-dot"></span>book signed</span>');
  else if(b.book==='not_yet')out.push('<span class="am-b-book"><span class="am-book-dot"></span>book</span>');
  if(b.vip>0)out.push('<span class="am-b-vip">VIP\u00d7'+b.vip+'</span>');
  // Photo badge -> Google Photos link. Album URL (baked from artist-albums.tsv)
  // wins; a single photographed show falls back to that photo's own share link; 2+
  // photos with no album yet renders unlinked (reconcile_photos.py flags the gap).
  if(b.photo>0){
    var pHref=b.photo_album||null;
    if(!pHref&&b.photo===1)(s.show_log||[]).some(function(x){if(x.photo_url){pHref=x.photo_url;return true;}return false;});
    var pTxt='\ud83d\udcf7'+(b.photo>1?'\u00d7'+b.photo:'');
    if(pHref)out.push('<a class="am-b-book am-b-photo" href="'+esc(pHref)+'" target="_blank" rel="noopener" title="'+(b.photo_album?'Google Photos album':'Show photo')+'">'+pTxt+'</a>');
    else out.push('<span class="am-b-book am-b-photo" title="'+b.photo+' show photos \u2014 album pending">'+pTxt+'</span>');
  }
  if(rows.upcoming){var d=amDays(rows.upcoming.date);out.push('<span class="am-b-next">next: '+(d!=null&&d>=0?('in '+d+' day'+(d===1?'':'s')):'upcoming')+'</span>');}
  if(rec.fast_track&&n===0)out.push('<span class="am-b-fast">\u2605 fast-track \u00b7 1st show</span>');
  else if(rec.fast_track&&viaOnly)out.push('<span class="am-b-fast">\u2605 fast-track</span>');
  if(n===0&&!rec.fast_track&&!rows.considering)out.push('<span class="am-never">never seen</span>');
  return'<div class="am-you-badges">'+out.join('')+'</div>';
}
// History block — renders one of: combined-bill note, considering card, or the seen timeline.
function amYouHistory(rec,rows){
  var s=rec.seen||{},n=s.count||0,log=s.show_log||[];
  var headline=log.filter(function(x){return !x.via;}),via=log.filter(function(x){return x.via;});
  // Combined-bill only (e.g. Joe Satriani via SatchVai Band)
  if(n>0&&headline.length===0&&via.length){
    var v=via[0];
    return'<div class="am-subh">History</div>'
      +'<div class="am-combined"><span class="am-combined-tag">combined bill</span>'
      +'<div class="am-combined-body">Seen with <b>'+esc(v.via)+'</b> <span class="am-dot-sep">\u00b7</span> <span class="am-combined-date">'+esc(v.date||'')+'</span>'
      +'<br><span class="am-combined-note">Never seen headlining under this name.</span></div></div>';
  }
  // Considering (never-seen potential)
  if(n===0&&rows.considering){
    var c=rows.considering,dec=(c.decision||'').toLowerCase();
    var btn=dec?'<span class="am-dec am-dec-'+esc(dec)+'">'+esc(c.decision)+'</span>':'';
    return'<div class="am-subh">Considering</div>'
      +'<div class="am-consider"><div class="am-consider-body"><div class="am-consider-date">'+esc(c.date||'TBD')+'</div>'
      +'<div class="am-consider-venue">'+esc(c.venue||'')+'</div></div>'+btn+'</div>';
  }
  // Seen timeline — full chronology, ALL roles. Previously
  // headline shows first, then support/via, which made "+ N earlier" misleading
  // for mixed-role artists (e.g. Larkin Poe: headline + festival + support slots
  // interleave in time). log is already reverse-chron from the builder's
  // dedup_log, so slicing it directly keeps the label chronologically true.
  // Support/via sightings carry a "w/ <headliner>" hint on the venue line.
  if(headline.length){
    var shown=log.slice(0,3),extra=n-shown.length;
    var items=shown.map(function(x,i){
      var recent=(i===0);
      var venue=esc(amVenueShort(x.venue)||'\u2014');
      if(x.via)venue+=' \u00b7 w/ '+esc(x.via);
      return'<div class="am-tl-item"><span class="am-tl-dot'+(recent?' on':'')+'"></span>'
        +'<div class="am-tl-date">'+esc(x.date||'')+'</div>'
        +'<div class="am-tl-venue">'+venue+'</div></div>';
    }).join('');
    var more=extra>0?'<div class="am-tl-item"><span class="am-tl-dot"></span><div class="am-tl-more">+ '+extra+' earlier show'+(extra===1?'':'s')+'</div></div>':'';
    return'<div class="am-tl">'+items+more+'</div>';
  }
  return'';
}
// Brand-hat favorite gauge — conic fill by affinity.score.
// An explicit favorite pins the fill to 1.0 (favorite.pin_to_full) with a
// star marker, so earned-max (~0.98) and starred (1.0) stay visually distinct;
// when authed and favorite.enabled the gauge itself is the promote/remove control.
function amGauge(a,rec,key){
  var cfg=amFavCfg(),fav=amIsFav(key);
  var score=Math.max(0,Math.min(1,a.score||0));
  if(fav&&cfg.pin)score=1;
  var glow=fav?0.34:({high:0.28,medium:0.16,low:0.07}[a.band]||0.10);
  var tip=fav
    ?'Favorite \u2605 \u2014 pinned to full (earned '+(a.score||0)+')'
    :'Favorite affinity: '+(a.band||'')+' \u2014 composite of tier, times seen, and goal completions';
  var canClick=cfg.enabled&&authed;
  if(canClick)tip+=fav?'. Click to remove.':'. Click to favorite.';
  var hat=esc(amHatUrl());
  return'<div class="am-gauge'+(fav?' am-gauge-fav':'')+(canClick?' am-gauge-btn':'')+'" style="--aff:'+score.toFixed(3)+';--glow:'+glow+'" title="'+esc(tip)+'"'
    +(canClick?' role="button" tabindex="0" onclick="amFavClick(\''+esc(key)+'\')" onkeydown="if(event.key===\'Enter\')amFavClick(\''+esc(key)+'\')"':'')+'>'
    +'<div class="am-gauge-glow"></div>'
    +'<img class="am-gauge-base" src="'+hat+'" alt="">'
    +'<img class="am-gauge-fill" src="'+hat+'" alt="">'
    +(fav?'<span class="am-gauge-star">\u2605</span>':'')+'</div>';
}
// ── init ──
function amInit(){
  var bd=document.getElementById('artistModal');
  if(bd&&!bd._amWired){bd._amWired=true;bd.addEventListener('click',function(e){if(e.target===bd)closeArtistModal();});}
  document.addEventListener('keydown',function(e){if(e.key==='Escape'){var m=document.getElementById('artistModal');if(m&&m.classList.contains('open'))closeArtistModal();}});
  window.addEventListener('hashchange',amOnHashChange);
  if(/^#artist\//.test(location.hash||''))amOnHashChange();     // honor a deep link on load
}
if(document.readyState!=='loading')amInit();else document.addEventListener('DOMContentLoaded',amInit);
