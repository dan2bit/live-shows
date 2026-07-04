// ── Artist modal / #artist/{slug} view (issue #107, P1) ─────────────────────
// Isolated module (option a): lazy index load + render + overlay modal + a
// hash route, so ongoing fixes here don't churn app.js. Reads the prebuilt
// data/artist_modal_index.json (scripts/build_artist_index.py). One render path;
// CSS makes the modal full-bleed on narrow viewports (the "route view" of #107).
//
// Globals borrowed from app.js: esc, featureOn, SITE_CONFIG, _assetUrl,
// currentRows, potentialRows. Own name-normalizer so it never depends on
// recommend.js load order. Phase 1 wires no list triggers yet — verify via
// window.openArtistModal('vanessa collier') or #artist/vanessa-collier.

var AM_INDEX_PATH='data/artist_modal_index.json';
var amIndexCache=null,amSlugMap=null,amRouting=false;

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
  var res=await fetch(AM_INDEX_PATH);           // relative -> Pages CDN, no API rate limit
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
function amErr(msg){return'<div class="am-msg am-err">'+esc(msg)+'</div>'
  +'<div class="am-actions"><button class="btn" onclick="closeArtistModal()">Close</button></div>';}

async function openArtistModal(name){
  amShow();
  amBody('<div class="am-loading">'+amHatImg(false)+'<span>Loading\u2026</span></div>');
  var data;try{data=await amLoadIndex();}catch(e){amBody(amErr('Couldn\u2019t load artist data \u2014 please try again.'));return;}
  var key=amNorm(name),rec=(data.artists||{})[key]||null;
  amOpenRec(rec,name,key);
}
async function openArtistBySlug(slug){
  amShow();
  amBody('<div class="am-loading">'+amHatImg(false)+'<span>Loading\u2026</span></div>');
  var data;try{data=await amLoadIndex();}catch(e){amBody(amErr('Couldn\u2019t load artist data \u2014 please try again.'));return;}
  var key=(amSlugMap||{})[slug]||null,rec=key?data.artists[key]:null;
  amOpenRec(rec,rec?rec.name:slug.replace(/-/g,' '),key||slug);
}
function amOpenRec(rec,displayName,key){
  var slug=(rec&&rec.slug)||amSlugify(key);
  amBody(amRender(rec,displayName,key));
  amSetHash(slug);
  if(rec)amHydrateImage(rec);
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

// ── render ──
function amHatImg(signed){
  var bi=(SITE_CONFIG.site&&SITE_CONFIG.site.brand_icon)||'static/brand-hat.png';
  var url=(typeof _assetUrl==='function')?_assetUrl(bi):bi;
  return'<img class="am-hat'+(signed?' am-hat-signed':'')+'" src="'+esc(url)+'" alt="'+(signed?'hat signed':'')+'">';
}
function amRender(rec,displayName,key){
  if(!rec){
    return'<div class="am-head"><div class="am-avatar">'+amHatImg(false)+'</div>'
      +'<div class="am-id"><div class="am-name">'+esc(displayName||'Unknown')+'</div>'
      +'<div class="am-sub am-dim">No details on file yet.</div></div>'
      +'<button class="am-close" onclick="closeArtistModal()" aria-label="Close">\u2715</button></div>'
      +amUpcoming(key)
      +'<div class="am-actions"><a class="ext-link" href="https://open.spotify.com/search/'+encodeURIComponent(displayName||'')+'" target="_blank">Search Spotify</a></div>';
  }
  var spotify=featureOn('spotify');
  var name=esc(rec.name||displayName||''),hatSigned=(rec.badges&&rec.badges.hat)==='completed';
  var h='';
  // Header / identity
  h+='<div class="am-head">';
  h+='<div class="am-avatar" id="amArt">'+amHatImg(hatSigned)+'</div>';
  h+='<div class="am-id"><div class="am-name">'+name+'</div>';
  var chips=[];
  if(rec.tier&&rec.tier.label)chips.push(amTierDots(rec.tier));
  if(rec.listener&&rec.listener.tranche)chips.push('<span class="am-chip am-tranche" title="'+esc(String(rec.listener.raw||''))+' Last.fm listeners">'+esc(rec.listener.tranche)+'</span>');
  if(rec.fast_track&&(!rec.seen||!rec.seen.count))chips.push('<span class="am-chip am-fast">\u26a1 1st \u00b7 fast-track</span>');
  if(chips.length)h+='<div class="am-chiprow">'+chips.join('')+'</div>';
  if(spotify&&rec.genres&&rec.genres.length)
    h+='<div class="am-genres">'+rec.genres.map(function(g){return'<span class="am-chip am-genre">'+esc(g)+'</span>';}).join('')+'</div>';
  h+='</div>';                                   // .am-id
  h+='<button class="am-close" onclick="closeArtistModal()" aria-label="Close">\u2715</button>';
  h+='</div>';                                   // .am-head
  if(rec.affinity)h+=amAffinity(rec.affinity);
  h+=amHistory(rec);
  h+=amUpcoming(key);
  if(spotify)h+=amMusic(rec);
  if(spotify)h+=amSimilar(rec);
  h+=amLinks(rec,spotify);
  return h;
}

function amTierDots(t){
  var r=t.rank||0,dots='';
  for(var i=1;i<=4;i++)dots+='<span class="am-dot'+(i<=r?' on':'')+'"></span>';
  return'<span class="am-chip am-tier" title="follow tier: '+esc(t.label)+'">'+dots+'<span class="am-tier-lbl">'+esc(t.label)+'</span></span>';
}
function amAffinity(a){
  var pct=Math.round((a.score||0)*100);
  return'<div class="am-affinity am-band-'+esc(a.band||'low')+'">'
    +'<div class="am-affinity-track"><div class="am-affinity-fill" style="width:'+pct+'%"></div></div>'
    +'<span class="am-affinity-lbl">affinity \u00b7 '+esc(a.band||'')+'</span></div>';
}
function amBadgeChips(b){
  var out=[];
  if(b.hat==='completed')out.push('<span class="am-badge">\ud83c\udfa9 hat signed</span>');
  if(b.book==='completed')out.push('<span class="am-badge">\ud83d\udcd3 book signed</span>');
  else if(b.book==='not_yet')out.push('<span class="am-badge am-badge-dim">\ud83d\udcd3 in book</span>');
  if(b.vip>0)out.push('<span class="am-badge">VIP\u00d7'+b.vip+'</span>');
  if(b.photo>0)out.push('<span class="am-badge">\ud83d\udcf7 '+b.photo+'</span>');
  return out.join('');
}
function amHistory(rec){
  var s=rec.seen||{},b=rec.badges||{},n=s.count||0;
  if(!n){
    if(rec.fast_track)return'<div class="am-section"><div class="am-sec-h">Your history</div><p class="am-dim">Not seen yet \u2014 on the fast-track list; any DC/MD/VA date is an instant buy.</p></div>';
    return'';
  }
  var line='Seen '+n+'\u00d7';
  if(s.first)line+=' \u00b7 first '+esc(s.first);
  if(s.recent&&s.recent!==s.first)line+=' \u00b7 recent '+esc(s.recent);
  var badges=amBadgeChips(b);
  var log='';
  if(s.show_log&&s.show_log.length){
    log='<details class="am-log"><summary>show log ('+s.show_log.length+')</summary><ul>'
      +s.show_log.map(function(r){
        var v=r.venue?esc(r.venue):'';
        var via=r.via?' <span class="am-dim">(via '+esc(r.via)+')</span>':'';
        return'<li><span class="am-log-date">'+esc(r.date||'')+'</span> '+v+via+'</li>';
      }).join('')+'</ul></details>';
  }
  return'<div class="am-section"><div class="am-sec-h">Your history</div>'
    +'<div class="am-seen">'+line+'</div>'
    +(badges?'<div class="am-badges">'+badges+'</div>':'')
    +log+'</div>';
}
function amUpcoming(key){
  var up=null,con=null;
  try{
    (currentRows||[]).forEach(function(r){if((r['Status']||'')==='upcoming'&&amNorm(r['Artist']||'')===key)up={date:r['Show Date']||'',venue:r['Venue Name']||''};});
    (potentialRows||[]).forEach(function(r){if(amNorm(r['Artist']||'')===key)con={date:r['Date']||'',venue:r['Venue']||'',decision:r['Decision']||''};});
  }catch(e){}
  if(!up&&!con)return'';
  var h='<div class="am-section">';
  if(up){
    var d=Date.parse(up.date),days=isNaN(d)?null:Math.ceil((d-Date.now())/86400000);
    var cd=(days===null)?'':(days<=0?'today/soon':'in '+days+' day'+(days===1?'':'s'));
    h+='<div class="am-upcoming">\ud83c\udf9f <strong>Upcoming</strong> \u2014 '+esc(up.date)+(up.venue?' \u00b7 '+esc(up.venue):'')+(cd?' <span class="am-cd">'+cd+'</span>':'')+'</div>';
  }
  if(con)h+='<div class="am-considering">\ud83d\udc40 Considering \u2014 '+esc(con.date||'TBD')+(con.venue?' \u00b7 '+esc(con.venue):'')+(con.decision?' \u00b7 '+esc(con.decision):'')+'</div>';
  return h+'</div>';
}
function amMusic(rec){
  var lr=rec.latest_release,sp=rec.links&&rec.links.spotify;
  if(!lr&&!sp)return'';
  var h='<div class="am-section"><div class="am-sec-h">Music</div>';
  if(lr&&lr.name){
    h+='<div class="am-release">latest '+esc(lr.type||'release')+': <strong>'+esc(lr.name)+'</strong>'+(lr.date?' <span class="am-dim">('+esc(lr.date)+')</span>':'')
      +(lr.url?' \u2014 <a class="ext-link" href="'+esc(lr.url)+'" target="_blank">open</a>':'')+'</div>';
  }
  if(sp)h+='<div class="am-actions"><a class="ext-link am-cta" href="'+esc(sp)+'" target="_blank">\u25b6 Open in Spotify</a></div>';
  return h+'</div>';
}
function amSimilar(rec){
  var sim=rec.similar||[];if(!sim.length)return'';
  var chips=sim.slice(0,8).map(function(s){
    if(s.in_tracker&&s.slug)return'<button class="am-chip am-sim am-sim-link" onclick="openArtistBySlug(\''+esc(s.slug)+'\')">'+esc(s.name)+'</button>';
    return'<a class="am-chip am-sim" href="https://www.last.fm/search?q='+encodeURIComponent(s.name||'')+'" target="_blank">'+esc(s.name)+'</a>';
  }).join('');
  return'<div class="am-section"><div class="am-sec-h">Similar</div><div class="am-simrow">'+chips+'</div></div>';
}
function amLinks(rec,spotify){
  var L=rec.links||{},items=[];
  function add(url,label){if(url)items.push('<a class="ext-link" href="'+esc(url)+'" target="_blank">'+label+'</a>');}
  if(spotify)add(L.spotify,'Spotify');
  add(L.youtube,'YouTube');
  add(L.bandsintown,'Bandsintown');
  add(L.seated,'Seated');
  if(spotify){add(L.lastfm,'Last.fm');add(L.musicbrainz,'MusicBrainz');}
  add(L.setlistfm,'setlist.fm');
  if(!items.length)return'';
  return'<div class="am-section am-links">'+items.join('')+'</div>';
}

// Identity image via Spotify oEmbed (no cache, decision 1). Brand-hat stays on failure.
function amHydrateImage(rec){
  if(!featureOn('spotify'))return;
  var sp=rec.links&&rec.links.spotify;if(!sp)return;
  fetch('https://open.spotify.com/oembed?url='+encodeURIComponent(sp)).then(function(r){return r.ok?r.json():null;}).then(function(j){
    if(!j||!j.thumbnail_url)return;
    var box=document.getElementById('amArt');if(!box)return;
    var img=new Image();
    img.onload=function(){box.innerHTML='<img class="am-photo" src="'+esc(j.thumbnail_url)+'" alt="'+esc(rec.name||'')+'">';};
    img.src=j.thumbnail_url;
  }).catch(function(){});
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
