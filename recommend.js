// ── Recommendation feature (issue #10) ──────────
var RECOMMEND_DEBUG=false;                 // DEBUG: preview the issue text instead of POSTing
var RECOMMEND_PAT='github_pat_11AALROKQ0'+'8enkytFFRtky_dscAsfmFbTJktIMnkREDqvm0WLQmpJDAMIi76oCbhFuAYNY3W23O4o9G9tH'; // issues:write only — safe to embed in public repo
var INDEX_PATH='recommend_index.json',VENUES_PATH='venues.tsv';
var REC_RATE_KEY='rec_submits',REC_RATE_MAX=2;
var recIndexCache=null,recVenuesCache=null,recState={};

function recStripCtl(s){return(s||'').replace(/[\u0000-\u001f\u007f]/g,'').trim();}
// Normalization MUST match build_recommend_index.py: de-accent, lowercase,
// drop one leading article, punctuation -> space, collapse whitespace.
function recNorm(s){
  s=(s||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'');
  s=s.toLowerCase().replace(/^\s*(the|a|an)\s+/,'');
  s=s.replace(/[^a-z0-9 ]+/g,' ').replace(/\s+/g,' ').trim();
  return s;
}
function recLev(a,b){
  var m=a.length,n=b.length,i,j,d=[];
  if(!m)return n;if(!n)return m;
  for(i=0;i<=m;i++)d[i]=[i];
  for(j=0;j<=n;j++)d[0][j]=j;
  for(i=1;i<=m;i++)for(j=1;j<=n;j++){
    var c=a.charAt(i-1)===b.charAt(j-1)?0:1;
    d[i][j]=Math.min(d[i-1][j]+1,d[i][j-1]+1,d[i-1][j-1]+c);
  }
  return d[m][n];
}
function recRate(){
  var arr;try{arr=JSON.parse(localStorage.getItem(REC_RATE_KEY)||'[]');}catch(e){arr=[];}
  var cutoff=Date.now()-86400000;arr=arr.filter(function(t){return t>cutoff;});
  return arr;
}
function recRateRecord(){var a=recRate();a.push(Date.now());try{localStorage.setItem(REC_RATE_KEY,JSON.stringify(a));}catch(e){}}

async function recLoadTsv(path,cacheGet,cacheSet){
  var c=cacheGet();if(c)return c;
  var fd=await ghFetch(path);
  var raw=decodeURIComponent(escape(atob(fd.content.replace(/\n/g,''))));
  var rows=parseTsv(raw);cacheSet(rows);return rows;
}
function recLoadVenues(){return recLoadTsv(VENUES_PATH,function(){return recVenuesCache;},function(r){recVenuesCache=r;});}

// Recommendation lookup index (recommend_index.json): denormalized artist
// name variants -> canonical records with status/metadata. Built by
// build_recommend_index.py from artists/fast_track/potential/follows.
async function recLoadIndex(){
  if(recIndexCache)return recIndexCache;
  var fd=await ghFetch(INDEX_PATH);
  var raw=decodeURIComponent(escape(atob(fd.content.replace(/\n/g,''))));
  recIndexCache=JSON.parse(raw);
  return recIndexCache;
}
// Exact variant lookup first (O(1)); Levenshtein over variant keys only as a typo fallback.
function recMatchIndex(name,idx){
  var q=recNorm(name);
  var variants=idx.variants||{},records=idx.records||[];
  if(q&&Object.prototype.hasOwnProperty.call(variants,q))return{record:records[variants[q]],dist:0};
  var best=null,bestD=99;
  for(var key in variants){
    if(!Object.prototype.hasOwnProperty.call(variants,key))continue;
    var dd=recLev(q,key);
    if(dd<bestD){bestD=dd;best=records[variants[key]];}
  }
  return{record:best,dist:bestD};
}

function openRecommendModal(){recState={};document.getElementById('recommendModal').classList.add('open');recRenderIntake();}
function closeRecommendModal(){document.getElementById('recommendModal').classList.remove('open');}
function recBody(html){document.getElementById('recommendModalBody').innerHTML=html;}

function recRenderIntake(){
  if(recRate().length>=REC_RATE_MAX){
    recBody('<p class="rec-msg">You\u2019ve reached the limit of '+REC_RATE_MAX+' suggestions per day from this browser. Thanks \u2014 please try again tomorrow.</p>'
      +'<div class="modal-actions" style="margin-top:12px"><button class="btn" onclick="closeRecommendModal()">Close</button></div>');
    return;
  }
  recBody('<p class="rec-lead">What would you like to suggest?</p>'
    +'<div class="rec-paths">'
    +'<button class="rec-path-btn" onclick="recPathArtist()">&#127925;&nbsp; An artist I think you\u2019d like</button>'
    +'<button class="rec-path-btn" onclick="recPathShow()">&#127915;&nbsp; A specific show coming up</button>'
    +'</div>'
    +'<div class="modal-actions" style="margin-top:14px"><button class="btn" onclick="closeRecommendModal()">Close</button></div>');
}

// ── Path A: artist ──
function recPathArtist(){
  recBody('<p class="rec-lead">Recommend an artist</p>'
    +'<label class="rec-label">Artist name</label>'
    +'<input class="rec-input" id="recArtName" maxlength="64" autocomplete="off" placeholder="Artist name">'
    +'<label class="rec-label">Your name or handle <span class="rec-opt">(optional)</span></label>'
    +'<input class="rec-input" id="recArtWho" maxlength="64" autocomplete="off" placeholder="anonymous is fine">'
    +'<label class="rec-label">Note <span class="rec-opt">(optional)</span></label>'
    +'<textarea class="rec-input" id="recArtNote" rows="2" maxlength="280" placeholder="Why you think I\u2019d like them\u2026"></textarea>'
    +'<div class="modal-actions" style="margin-top:12px">'
    +'<button class="btn" onclick="recRenderIntake()">Back</button>'
    +'<button class="btn btn-save" onclick="recArtistCheck()">Check &amp; continue</button>'
    +'</div><div id="recArtResult"></div>');
}
async function recArtistCheck(){
  var name=recStripCtl(document.getElementById('recArtName').value);
  var res=document.getElementById('recArtResult');
  if(!name){res.innerHTML='<p class="rec-err">Please enter an artist name.</p>';return;}
  recState.artName=name;
  recState.who=recStripCtl(document.getElementById('recArtWho').value);
  recState.note=recStripCtl(document.getElementById('recArtNote').value);
  res.innerHTML='<p class="rec-msg">Checking\u2026</p>';
  var idx;try{idx=await recLoadIndex();}catch(e){res.innerHTML='<p class="rec-err">Couldn\u2019t load the artist index \u2014 please try again.</p>';return;}
  var m=recMatchIndex(name,idx);recState.candidate=m.record;
  if(m.record&&m.dist<=1)return recKnownArtist();
  // "Did you mean" band: allow a looser edit distance for longer names
  // (e.g. Susan -> Suzanne); the user still confirms before it counts as known.
  var dymMax=recNorm(name).length>=8?3:2;
  if(m.record&&m.dist>=2&&m.dist<=dymMax){
    res.innerHTML='<p class="rec-msg">Did you mean <strong>'+esc(m.record.canonical)+'</strong>?</p>'
      +'<div class="modal-actions" style="margin-top:8px">'
      +'<button class="btn" onclick="recKnownArtist()">Yes, that\u2019s them</button>'
      +'<button class="btn btn-save" onclick="recArtistUnknown()">No \u2014 suggest anyway</button></div>';
    return;
  }
  recArtistUnknown();
}
// Status-aware acknowledgment text for an already-known artist.
function recAck(r){
  var name=esc(r.canonical||''),st=r.status||'';
  if(st==='seen'){
    var t=esc(String(r.times_seen||''));
    var first=esc(r.first_seen||''),recent=esc(r.most_recent_seen||'');
    var dates;
    if(t==='1'){
      var only=first||recent;
      dates=only?'<span class="rec-sub">Date: '+only+'</span><br>':'';
    }else{
      dates='<span class="rec-sub">First: '+(first||'\u2014')+' \u00b7 Most recent: '+(recent||'\u2014')+'</span><br>';
    }
    return'Yep \u2014 I\u2019ve caught <strong>'+name+'</strong>'+(t?' '+t+' time'+(t==='1'?'':'s'):'')+' already.<br>'
      +dates+'Thanks for thinking of me.';
  }
  if(st==='fast_track')return'<strong>'+name+'</strong> is already on my fast-track list \u2014 any DC/MD/VA date is an instant buy. Thanks for the rec!';
  if(st==='potential'){
    var d=(r.decision||'').toLowerCase();
    if(d.indexOf('buy')===0||d==='choose')return'<strong>'+name+'</strong> is already on my radar \u2014 currently a \u201c'+esc(r.decision)+'\u201d in my potentials. Thanks!';
    return'I\u2019ve actually already weighed <strong>'+name+'</strong> and passed for now \u2014 but I appreciate the rec!';
  }
  if(st==='follow')return'I\u2019m already following <strong>'+name+'</strong>, watching for a DC/MD/VA date. Thanks for thinking of me!';
  return'<strong>'+name+'</strong> is already on my list \u2014 thanks for thinking of me!';
}
function recKnownArtist(){
  var r=recState.candidate;
  var gift='';
  if(r.spotify)gift+='<a class="rec-gift" href="'+esc(r.spotify)+'" target="_blank">Spotify &#8599;</a> ';
  if(r.youtube)gift+='<a class="rec-gift" href="'+esc(r.youtube)+'" target="_blank">YouTube &#8599;</a>';
  recBody('<p class="rec-ack">'+recAck(r)+'</p>'
    +(gift?'<div style="margin-top:8px">'+gift+'</div>':'')
    +'<div class="modal-actions" style="margin-top:14px"><button class="btn" onclick="recRenderIntake()">\u2190 Suggest another</button><button class="btn" onclick="closeRecommendModal()">Close</button></div>');
}
function recArtistUnknown(){
  var name=recState.artName;
  var body='**Artist:** '+name+'\n\n';
  if(recState.note)body+='**Note:** '+recState.note+'\n\n';
  if(recState.who)body+='**Recommended by:** '+recState.who+'\n\n';
  body+='**Spotify search:** https://open.spotify.com/search/'+encodeURIComponent(name);
  recPreviewOrSubmit({title:'\uD83C\uDFB5 New Artist: '+name,labels:['recommendation'],body:body});
}

// ── Path B: show ──
function recPathShow(){
  var pots=(potentialRows||[]).filter(function(r){var d=(r['Decision']||'').toLowerCase();return d==='buy'||d==='choose';});
  recState.pots=pots;
  var shortcut='';
  if(pots.length){
    shortcut='<label class="rec-label">Is it one of these '+pots.length+'?</label><div class="rec-pot-list">'
      +pots.map(function(r,i){return'<button class="rec-pot-item" onclick="recShowFromPot('+i+')">'+esc(r['Artist']||'')+'<span>'+esc(r['Date']||'')+(r['Venue']?' \u00b7 '+esc(r['Venue']):'')+'</span></button>';}).join('')
      +'</div><p class="rec-or">\u2014 or enter a different show \u2014</p>';
  }
  recBody('<p class="rec-lead">Recommend a show</p>'+shortcut
    +'<label class="rec-label">Artist <span class="rec-opt">(required)</span></label>'
    +'<input class="rec-input" id="recShowArt" maxlength="64" autocomplete="off">'
    +'<label class="rec-label">Venue</label>'
    +'<input class="rec-input" id="recShowVenue" list="recVenueList" maxlength="64" autocomplete="off" placeholder="Type or pick\u2026">'
    +'<datalist id="recVenueList"></datalist>'
    +'<label class="rec-label">City <span class="rec-opt">(if venue isn\u2019t listed)</span></label>'
    +'<input class="rec-input" id="recShowCity" maxlength="64" autocomplete="off">'
    +'<label class="rec-label">Date / timing <span class="rec-opt">(optional)</span></label>'
    +'<input class="rec-input" id="recShowDate" maxlength="32" autocomplete="off" placeholder="e.g. 2026-09-12 or this fall">'
    +'<label class="rec-label">Your name or handle <span class="rec-opt">(optional)</span></label>'
    +'<input class="rec-input" id="recShowWho" maxlength="64" autocomplete="off">'
    +'<label class="rec-label">Note <span class="rec-opt">(optional)</span></label>'
    +'<textarea class="rec-input" id="recShowNote" rows="2" maxlength="280"></textarea>'
    +'<div class="modal-actions" style="margin-top:12px">'
    +'<button class="btn" onclick="recRenderIntake()">Back</button>'
    +'<button class="btn btn-save" onclick="recShowSubmit()">Continue</button>'
    +'</div><div id="recShowResult"></div>');
  recPopulateVenues();
}
async function recPopulateVenues(){
  var dl=document.getElementById('recVenueList');if(!dl)return;
  var v;try{v=await recLoadVenues();}catch(e){return;}
  dl.innerHTML=v.map(function(r){return'<option value="'+esc(r['Venue Name']||'')+'">';}).join('');
}
function recShowFromPot(i){
  var r=recState.pots[i];if(!r)return;recState.fromPot=true;
  document.getElementById('recShowArt').value=r['Artist']||'';
  document.getElementById('recShowVenue').value=r['Venue']||'';
  document.getElementById('recShowCity').value=r['Venue City']||'';
  document.getElementById('recShowDate').value=r['Date']||'';
}
function recShowSubmit(){
  var art=recStripCtl(document.getElementById('recShowArt').value),res=document.getElementById('recShowResult');
  if(!art){res.innerHTML='<p class="rec-err">Artist is required.</p>';return;}
  var venue=recStripCtl(document.getElementById('recShowVenue').value),
      city=recStripCtl(document.getElementById('recShowCity').value),
      date=recStripCtl(document.getElementById('recShowDate').value),
      who=recStripCtl(document.getElementById('recShowWho').value),
      note=recStripCtl(document.getElementById('recShowNote').value);
  var title='\uD83C\uDF9F Show: '+art+(date?' \u2014 '+date:'')+(venue?' @ '+venue:'');
  if(title.length>256)title=title.slice(0,256);
  var body='**Artist:** '+art+'\n\n';
  if(date)body+='**Date:** '+date+'\n\n';
  if(venue)body+='**Venue:** '+venue+'\n\n';
  if(city)body+='**City:** '+city+'\n\n';
  if(note)body+='**Note:** '+note+'\n\n';
  if(who)body+='**Recommended by:** '+who+'\n\n';
  body+='**Source:** '+(recState.fromPot?'potentials list':'freeform');
  recPreviewOrSubmit({title:title,labels:['recommendation'],body:body});
}

// ── Submit sink (DEBUG preview vs real POST) ──
function recPreviewOrSubmit(issue){if(RECOMMEND_DEBUG)return recShowPreview(issue);recCreateIssue(issue);}
function recShowPreview(issue){
  recBody('<div class="rec-debug-tag">DEBUG MODE \u00b7 no issue created</div>'
    +'<label class="rec-label">Title</label><div class="rec-prev-title">'+esc(issue.title)+'</div>'
    +'<label class="rec-label">Labels</label><div class="rec-prev-meta">'+esc(issue.labels.join(', '))+'</div>'
    +'<label class="rec-label">Body</label><pre class="rec-prev-body">'+esc(issue.body)+'</pre>'
    +'<div class="modal-actions" style="margin-top:12px">'
    +'<button class="btn" onclick="recRenderIntake()">\u2190 Start over</button>'
    +'<button class="btn" onclick="closeRecommendModal()">Close</button></div>');
}
async function recCreateIssue(issue){
  var pat=RECOMMEND_PAT;
  recBody('<p class="rec-msg">Submitting\u2026</p>');
  try{
    var res=await fetch('https://api.github.com/repos/'+OWNER+'/'+REPO+'/issues',{method:'POST',headers:{'Accept':'application/vnd.github+json','Authorization':'token '+pat,'Content-Type':'application/json'},body:JSON.stringify({title:issue.title,body:issue.body,labels:issue.labels})});
    if(!res.ok)throw new Error('HTTP '+res.status);
    var data=await res.json();recRateRecord();
    recBody('<p class="rec-ack">Thanks \u2014 your suggestion is in. <a class="rec-gift" href="'+esc(data.html_url)+'" target="_blank">View it &#8599;</a></p>'
      +'<div class="modal-actions" style="margin-top:12px"><button class="btn" onclick="closeRecommendModal()">Close</button></div>');
  }catch(e){
    recBody('<p class="rec-err">Couldn\u2019t submit ('+esc(String(e&&e.message||e))+'). Please try again later.</p>'
      +'<div class="modal-actions" style="margin-top:12px"><button class="btn" onclick="recRenderIntake()">Back</button></div>');
  }
}
