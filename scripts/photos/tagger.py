#!/usr/bin/env python3
"""
Internal photo tagger — a dependency-free local web app for reviewing/curating
tags and collections. Built to stay usable across 1k+ photos.

Run:   python3 scripts/photos/tagger.py        (opens http://localhost:8800)

Three modes (top-left switch):
  • Tag photos   — paginated list; filter by shoot / city / state / collection /
                   reviewed-state / free-text search. Per photo: the geo
                   hierarchy (Sub-neighborhood → Neighborhood → City → State),
                   Land use / Architecture / Subject / Tone chips, collection
                   membership, and the vision tag note.
  • Collections  — manage every collection: rename (title), set Featured + Order
                   (pick the 5 for the home page and their order), see counts,
                   jump to "Edit members".
  • Edit members — a grid for one collection: shows its photos (click to REMOVE);
                   flip "show all matching" + a place filter to ADD photos.

AUTOSAVES every change to data/photos.json / data/collections.json and marks
edited photos reviewed=true so the pipeline never overwrites hand edits.
"""

import json
import os
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "data" / "photos.json"
COLLECTIONS = REPO / "data" / "collections.json"
TAXONOMY = REPO / "data" / "taxonomy.json"
PLACES = REPO / "data" / "places.json"
DERIV = REPO / ".photo-build" / "derivatives"
PORT = 8800

_lock = threading.Lock()


def slugify(s):
    out = "".join(c.lower() if c.isalnum() else "-" for c in s)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def load(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def atomic_write(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def save_manifest(m):
    def key(k):
        nums = re.findall(r"\d+", k)
        return (k.rsplit("/", 1)[0], [int(n) for n in nums])
    atomic_write(MANIFEST, {k: m[k] for k in sorted(m.keys(), key=key)})


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Photo Tagger</title>
<style>
 *{box-sizing:border-box} body{font-family:-apple-system,system-ui,sans-serif;margin:0;background:#f4f4f5;color:#18181b}
 header{position:sticky;top:0;z-index:10;background:#fff;border-bottom:1px solid #e4e4e7;padding:10px 18px;
   display:flex;gap:10px;align-items:center;flex-wrap:wrap}
 header h1{font-size:14px;margin:0 8px 0 0;font-weight:700;letter-spacing:.02em}
 select,input,button{font:inherit;font-size:13px;padding:6px 9px;border:1px solid #d4d4d8;border-radius:6px;background:#fff;color:#18181b}
 button{cursor:pointer}
 .seg{display:flex;border:1px solid #d4d4d8;border-radius:7px;overflow:hidden}
 .seg button{border:0;border-radius:0;background:#fff;padding:6px 12px;font-weight:600;color:#71717a}
 .seg button.on{background:#18181b;color:#fff}
 .spacer{flex:1}
 .stat{font-size:12px;color:#71717a}
 .save-flash{font-size:12px;color:#16a34a;opacity:0;transition:opacity .3s} .save-flash.on{opacity:1}
 input.search{width:180px}
 main{padding:16px;max-width:1180px;margin:0 auto}
 .pager{display:flex;gap:12px;align-items:center;justify-content:center;margin:16px 0}
 .pager button:disabled{opacity:.4;cursor:default}
 .hint{font-size:13px;color:#71717a;margin:0 0 12px}

 /* Tag list */
 .row{display:grid;grid-template-columns:210px 1fr;gap:18px;background:#fff;border:1px solid #e4e4e7;
   border-radius:10px;padding:14px;margin-bottom:12px}
 .row.reviewed{border-color:#86efac;background:#f0fdf4}
 .thumb{width:100%;border-radius:6px;display:block;background:#e4e4e7}
 .imgmeta{font-size:11px;color:#a1a1aa;margin-top:6px;font-variant-numeric:tabular-nums}
 .imgmeta b{color:#52525b}
 .notes{font-size:12px;color:#71717a;font-style:italic;margin-top:6px}
 .dim{margin-bottom:9px}
 .dim .label{font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:#a1a1aa;margin-bottom:4px}
 .chips{display:flex;flex-wrap:wrap;gap:6px}
 .chip{font-size:12px;padding:4px 10px;border:1px solid #d4d4d8;border-radius:999px;background:#fafafa;
   cursor:pointer;user-select:none;transition:all .1s}
 .chip:hover{border-color:#a1a1aa}
 .chip.on{background:#18181b;color:#fff;border-color:#18181b}
 .chip.coll.on{background:#7c3aed;border-color:#7c3aed}
 .geo{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:10px}
 .geo label{display:block;font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:#a1a1aa;margin-bottom:3px}
 .geo input{width:100%}
 .newcoll{display:flex;gap:6px;margin-top:6px}
 .newcoll input{width:220px}
 .newcoll button{border-color:#7c3aed;background:#7c3aed;color:#fff}

 /* Collections manager */
 .ctable{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e4e4e7;border-radius:10px;overflow:hidden}
 .ctable th,.ctable td{padding:9px 12px;border-bottom:1px solid #f0f0f1;text-align:left;font-size:13px}
 .ctable th{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#a1a1aa;background:#fafafa}
 .ctable tr.feat{background:#faf5ff}
 .ctable input.title{width:100%;max-width:280px}
 .ctable input.place{width:100%;max-width:220px}
 .ctable input.order{width:52px;text-align:center}
 .ctable td.ct{color:#71717a;font-variant-numeric:tabular-nums}
 .linkbtn{border:0;background:none;color:#7c3aed;padding:0;text-decoration:underline;cursor:pointer;font-size:13px}

 /* Members grid */
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px}
 .cell{position:relative;border:2px solid #7c3aed;border-radius:8px;overflow:hidden;cursor:pointer;background:#fff;transition:all .1s}
 .cell img{width:100%;display:block;aspect-ratio:1;object-fit:cover;background:#e4e4e7}
 .cell .cap{font-size:11px;color:#52525b;padding:4px 7px;font-variant-numeric:tabular-nums}
 .cell .badge{position:absolute;top:6px;right:6px;font-size:10.5px;font-weight:700;padding:3px 8px;border-radius:999px;background:#7c3aed;color:#fff}
 .cell.out{border-color:#e4e4e7;opacity:.5} .cell.out .badge{background:#94a3b8}
 .cell.out:hover{opacity:.85}
</style></head><body>
<header>
 <h1>Photo Tagger</h1>
 <div class="seg" id="modeseg">
   <button data-mode="tag" class="on">Tag photos</button>
   <button data-mode="colls">Collections</button>
 </div>
 <span id="filters"></span>
 <span class="spacer"></span>
 <span class="save-flash" id="flash">saved ✓</span>
 <span class="stat" id="stat"></span>
</header>
<main id="main"></main>
<script>
let PHOTOS={}, COLLS=[], TAX=[], SHOOTS=[];
let mode='tag', page=0, memberSlug=null;
const PER=48, GRIDPER=60;                     // list page size / grid page size
const $=s=>document.querySelector(s);
const esc=s=>String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;');
const arr=(k,d)=>{const v=PHOTOS[k][d];return Array.isArray(v)?v:(v?[v]:[]);};
const uniq=a=>[...new Set(a.filter(Boolean))].sort();

async function boot(){
  const d=await (await fetch('/api/data')).json();
  PHOTOS=d.photos; COLLS=d.collections; TAX=d.taxonomy||[]; SHOOTS=d.shoots||[];
  document.querySelectorAll('#modeseg button').forEach(b=>b.onclick=()=>{
    mode=b.dataset.mode; page=0; memberSlug=null;
    document.querySelectorAll('#modeseg button').forEach(x=>x.classList.toggle('on',x===b));
    render();
  });
  render();
}
function flash(){const f=$('#flash');f.classList.add('on');setTimeout(()=>f.classList.remove('on'),800);}

async function save(key,patch){
  PHOTOS[key]=Object.assign(PHOTOS[key],patch,{reviewed:true});
  await fetch('/api/save',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({key,patch})});
  flash();
}
async function updateColl(slug,patch){
  const r=await (await fetch('/api/collection/update',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify(Object.assign({slug},patch))})).json();
  COLLS=r.collections; flash();
}
async function newCollection(title,key){
  const r=await (await fetch('/api/collection',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({title,place:PHOTOS[key]?PHOTOS[key].city:''})})).json();
  COLLS=r.collections;
  if(key){const s=new Set(PHOTOS[key].collections||[]);s.add(r.slug);await save(key,{collections:[...s]});}
  render();
}

/* ---------- shared datalists ---------- */
function datalists(){
  const vals=k=>uniq(Object.values(PHOTOS).map(p=>p[k]));
  return `<datalist id="dl-sub_neighborhood">${vals('sub_neighborhood').map(v=>`<option value="${esc(v)}">`).join('')}</datalist>
  <datalist id="dl-neighborhood">${vals('neighborhood').map(v=>`<option value="${esc(v)}">`).join('')}</datalist>
  <datalist id="dl-city">${vals('city').map(v=>`<option value="${esc(v)}">`).join('')}</datalist>
  <datalist id="dl-state">${vals('state').map(v=>`<option value="${esc(v)}">`).join('')}</datalist>`;
}

/* ================= TAG MODE ================= */
const tagFilters={shoot:'',city:'',state:'',coll:'',review:'',q:''};
function tagVisible(){
  const f=tagFilters;
  return Object.keys(PHOTOS).filter(k=>{
    const p=PHOTOS[k];
    if(f.shoot&&p.shoot!==f.shoot)return false;
    if(f.city&&p.city!==f.city)return false;
    if(f.state&&p.state!==f.state)return false;
    if(f.coll&&!(p.collections||[]).includes(f.coll))return false;
    if(f.review==='un'&&p.reviewed)return false;
    if(f.review==='rev'&&!p.reviewed)return false;
    if(f.q){const q=f.q.toLowerCase();
      const hay=[p.file,p.neighborhood,p.sub_neighborhood,p.city,p.tag_notes].filter(Boolean).join(' ').toLowerCase();
      if(!hay.includes(q))return false;}
    return true;
  }).sort((a,b)=>(PHOTOS[a].shoot||'').localeCompare(PHOTOS[b].shoot||'')||(PHOTOS[a].img_no-PHOTOS[b].img_no));
}
function tagFilterBar(){
  const opt=(sel,cur)=>sel.map(v=>`<option value="${esc(v.v)}"${v.v===cur?' selected':''}>${esc(v.t)}</option>`).join('');
  const cities=uniq(Object.values(PHOTOS).map(p=>p.city));
  const states=uniq(Object.values(PHOTOS).map(p=>p.state));
  return `
  <select id="f-shoot"><option value="">All shoots</option>${opt(SHOOTS.map(s=>({v:s,t:s})),tagFilters.shoot)}</select>
  <select id="f-city"><option value="">All cities</option>${opt(cities.map(c=>({v:c,t:c})),tagFilters.city)}</select>
  <select id="f-state"><option value="">State</option>${opt(states.map(s=>({v:s,t:s})),tagFilters.state)}</select>
  <select id="f-coll"><option value="">Any collection</option>${opt(COLLS.slice().sort((a,b)=>a.title.localeCompare(b.title)).map(c=>({v:c.slug,t:c.title})),tagFilters.coll)}</select>
  <select id="f-review"><option value="">All</option><option value="un"${tagFilters.review==='un'?' selected':''}>Unreviewed</option><option value="rev"${tagFilters.review==='rev'?' selected':''}>Reviewed</option></select>
  <input class="search" id="f-q" placeholder="search…" value="${esc(tagFilters.q)}">`;
}
function wireTagFilters(){
  const bind=(id,key,ev)=>{const el=$(id);if(!el)return;el.addEventListener(ev,()=>{tagFilters[key]=el.value;page=0;render();});};
  bind('#f-shoot','shoot','change');bind('#f-city','city','change');bind('#f-state','state','change');
  bind('#f-coll','coll','change');bind('#f-review','review','change');
  const q=$('#f-q');if(q){q.addEventListener('input',()=>{tagFilters.q=q.value;page=0;renderList();});q.focus();q.setSelectionRange(q.value.length,q.value.length);}
}
function geoRow(key){
  const p=PHOTOS[key];
  const inp=(f,label)=>`<div><label>${label}</label><input list="dl-${f}" value="${esc(p[f]||'')}"
     onchange="save('${esc(key)}',{${f}:this.value||null})"></div>`;
  return `<div class="geo">${inp('sub_neighborhood','Sub-nbhd')}${inp('neighborhood','Neighborhood')}${inp('city','City')}${inp('state','State')}</div>`;
}
function chipRow(key,dim){
  const cur=arr(key,dim.key);
  return `<div class="dim" data-dim="${dim.key}"><div class="label">${dim.label}</div><div class="chips">`+
    dim.values.map(v=>`<span class="chip ${cur.includes(v)?'on':''}" onclick="toggleDim('${esc(key)}','${dim.key}','${esc(v)}')">${esc(v)}</span>`).join('')+`</div></div>`;
}
function collRow(key){
  const cur=new Set(PHOTOS[key].collections||[]);
  const chips=COLLS.slice().sort((a,b)=>a.title.localeCompare(b.title))
    .map(c=>`<span class="chip coll ${cur.has(c.slug)?'on':''}" onclick="toggleColl('${esc(key)}','${c.slug}')">${esc(c.title)}</span>`).join('');
  return `<div class="dim" data-dim="collections"><div class="label">Collections</div><div class="chips">${chips||'<span class="notes">none</span>'}</div>
    <div class="newcoll"><input placeholder="New collection…" id="nc-${cssid(key)}">
    <button onclick="(()=>{const i=document.getElementById('nc-${cssid(key)}');if(i.value.trim())newCollection(i.value.trim(),'${esc(key)}')})()">＋ create & add</button></div></div>`;
}
const cssid=k=>k.replace(/[^a-z0-9]/gi,'_');
window.toggleDim=(key,dim,v)=>{const s=new Set(arr(key,dim));s.has(v)?s.delete(v):s.add(v);
  PHOTOS[key][dim]=[...s];save(key,{[dim]:[...s]});repaint(key,dim,chipRow(key,TAX.find(x=>x.key===dim)));};
window.toggleColl=(key,slug)=>{const s=new Set(PHOTOS[key].collections||[]);s.has(slug)?s.delete(slug):s.add(slug);
  PHOTOS[key].collections=[...s];save(key,{collections:[...s]});repaint(key,'collections',collRow(key));};
function repaint(key,dim,html){const row=document.querySelector(`.row[data-key="${CSS.escape(key)}"]`);
  if(row){const el=row.querySelector(`[data-dim="${dim}"]`);if(el)el.outerHTML=html;}}

function renderList(){
  const all=tagVisible(), pages=Math.max(1,Math.ceil(all.length/PER));
  if(page>=pages)page=pages-1;
  const slice=all.slice(page*PER,page*PER+PER);
  const rev=all.filter(k=>PHOTOS[k].reviewed).length;
  $('#stat').textContent=`${rev}/${all.length} reviewed`;
  $('#main').innerHTML=slice.map(key=>{
    const p=PHOTOS[key];
    const dims=TAX.map(d=>chipRow(key,d)).join('');
    return `<div class="row ${p.reviewed?'reviewed':''}" data-key="${esc(key)}">
      <div><img class="thumb" loading="lazy" src="/img/${p.thumb}">
        <div class="imgmeta"><b>${esc(p.file)}</b> · ${esc(p.shoot)} · #${p.img_no}</div>
        ${p.tag_notes?`<div class="notes">“${esc(p.tag_notes)}”</div>`:''}</div>
      <div>${geoRow(key)}${dims}${collRow(key)}</div></div>`;
  }).join('')+pager(page,pages,all.length)+datalists();
  wirePager();
}

/* ================= COLLECTIONS MODE ================= */
function collCount(slug){return Object.values(PHOTOS).filter(p=>(p.collections||[]).includes(slug)).length;}
function collPlacesStr(c){const a=(c.places&&c.places.length)?c.places:(c.place?[c.place]:[]);return a.join(', ');}
window.savePlaces=(slug,val)=>{const a=val.split(',').map(s=>s.trim()).filter(Boolean);updateColl(slug,{places:a,place:a[0]||''});};
function renderColls(){
  $('#stat').textContent=`${COLLS.length} collections`;
  const rows=COLLS.slice().sort((a,b)=>(a.featured===b.featured)?(a.order-b.order)||a.title.localeCompare(b.title):(a.featured?-1:1))
   .map(c=>`<tr class="${c.featured?'feat':''}">
     <td><input class="title" value="${esc(c.title)}" onchange="updateColl('${esc(c.slug)}',{title:this.value})"></td>
     <td><input class="place" list="dl-place" value="${esc(collPlacesStr(c))}" placeholder="e.g. Newark, Brooklyn" onchange="savePlaces('${esc(c.slug)}',this.value)"></td>
     <td class="ct">${collCount(c.slug)}</td>
     <td><input type="checkbox" ${c.featured?'checked':''} onchange="updateColl('${esc(c.slug)}',{featured:this.checked})"></td>
     <td><input class="order" type="number" min="0" value="${c.order||0}" onchange="updateColl('${esc(c.slug)}',{order:+this.value})"></td>
     <td><button class="linkbtn" onclick="editMembers('${esc(c.slug)}')">Edit members →</button></td>
   </tr>`).join('');
  const cities=uniq(Object.values(PHOTOS).map(p=>p.city));
  $('#main').innerHTML=`<p class="hint">Rename via the title. <b>Place</b> is editable — type one or several <b>comma-separated</b> locations (e.g. “Newark, Brooklyn”) to span multiple; the site’s Collections filter then lists it under each. Tick <b>Featured</b> + set <b>Order</b> (1,2,3…) to choose the home-page 5 and their sequence. “Edit members” opens the add/remove grid.</p>
   <table class="ctable"><thead><tr><th>Title</th><th>Place(s)</th><th>Photos</th><th>Featured</th><th>Order</th><th></th></tr></thead><tbody>${rows}</tbody></table>
   <datalist id="dl-place">${cities.map(c=>`<option value="${esc(c)}">`).join('')}</datalist>`;
}
window.editMembers=(slug)=>{mode='members';memberSlug=slug;page=0;memberFilter.city='';memberFilter.all=false;render();};

/* ================= EDIT-MEMBERS GRID ================= */
const memberFilter={city:'',all:false};
function memberList(){
  const slug=memberSlug;
  let keys;
  if(memberFilter.all){
    keys=Object.keys(PHOTOS).filter(k=>!memberFilter.city||PHOTOS[k].city===memberFilter.city);
  }else{
    keys=Object.keys(PHOTOS).filter(k=>(PHOTOS[k].collections||[]).includes(slug));
    if(memberFilter.city)keys=keys.filter(k=>PHOTOS[k].city===memberFilter.city);
  }
  return keys.sort((a,b)=>(PHOTOS[a].shoot||'').localeCompare(PHOTOS[b].shoot||'')||(PHOTOS[a].img_no-PHOTOS[b].img_no));
}
window.toggleMember=(key)=>{const slug=memberSlug;const s=new Set(PHOTOS[key].collections||[]);
  const inn=!s.has(slug); inn?s.add(slug):s.delete(slug); PHOTOS[key].collections=[...s]; save(key,{collections:[...s]});
  const cell=document.querySelector(`.cell[data-key="${CSS.escape(key)}"]`);
  if(cell){cell.classList.toggle('out',!inn);cell.querySelector('.badge').textContent=inn?'in':'add';}
  $('#stat').textContent=`${collCount(slug)} in collection`;};
function renderMembers(){
  const c=COLLS.find(x=>x.slug===memberSlug);
  const cities=uniq(Object.values(PHOTOS).map(p=>p.city));
  const all=memberList(), pages=Math.max(1,Math.ceil(all.length/GRIDPER));
  if(page>=pages)page=pages-1;
  const slice=all.slice(page*GRIDPER,page*GRIDPER+GRIDPER);
  $('#stat').textContent=`${collCount(memberSlug)} in collection`;
  $('#main').innerHTML=`<p class="hint"><button class="linkbtn" onclick="backToColls()">← Collections</button> &nbsp; Editing <b>${esc(c?c.title:memberSlug)}</b>.
     Click a photo to ${memberFilter.all?'add/remove':'remove'} it. Autosaves.</p>
    <div style="display:flex;gap:10px;align-items:center;margin-bottom:12px">
      <label style="font-size:13px"><input type="checkbox" id="m-all" ${memberFilter.all?'checked':''}> show all photos (to add)</label>
      <select id="m-city"><option value="">All cities</option>${cities.map(c=>`<option value="${esc(c)}"${c===memberFilter.city?' selected':''}>${esc(c)}</option>`).join('')}</select>
    </div>
    <div class="grid">`+slice.map(key=>{const p=PHOTOS[key];const inn=(p.collections||[]).includes(memberSlug);
      return `<div class="cell ${inn?'':'out'}" data-key="${esc(key)}" onclick="toggleMember('${esc(key)}')">
        <span class="badge">${inn?'in':'add'}</span><img loading="lazy" src="/img/${p.thumb}">
        <div class="cap">${esc(p.city||'')} · #${p.img_no}</div></div>`;}).join('')+`</div>`+pager(page,pages,all.length);
  $('#m-all').onchange=e=>{memberFilter.all=e.target.checked;page=0;render();};
  $('#m-city').onchange=e=>{memberFilter.city=e.target.value;page=0;render();};
  wirePager();
}
window.backToColls=()=>{mode='colls';memberSlug=null;document.querySelectorAll('#modeseg button').forEach(x=>x.classList.toggle('on',x.dataset.mode==='colls'));render();};

/* ---------- pager ---------- */
function pager(pg,pages,total){
  if(pages<=1)return `<div class="pager"><span class="stat">${total} items</span></div>`;
  return `<div class="pager"><button id="pg-prev" ${pg===0?'disabled':''}>← Prev</button>
    <span class="stat">page ${pg+1}/${pages} · ${total} items</span>
    <button id="pg-next" ${pg>=pages-1?'disabled':''}>Next →</button></div>`;
}
function wirePager(){const p=$('#pg-prev'),n=$('#pg-next');
  if(p)p.onclick=()=>{page--;render();window.scrollTo(0,0);};
  if(n)n.onclick=()=>{page++;render();window.scrollTo(0,0);};}

/* ---------- top-level render ---------- */
function render(){
  const fbar=$('#filters');
  if(mode==='tag'){fbar.innerHTML=tagFilterBar();wireTagFilters();renderList();}
  else{fbar.innerHTML='';
    if(mode==='colls')renderColls();
    else renderMembers();}
}
boot();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if path == "/api/data":
            with _lock:
                m = load(MANIFEST, {})
                colls = load(COLLECTIONS, {"collections": []})["collections"]
                tax = load(TAXONOMY, {"dimensions": []})["dimensions"]
            shoots = sorted({p["shoot"] for p in m.values()})
            return self._send(200, {"photos": m, "collections": colls, "taxonomy": tax, "shoots": shoots})
        if path.startswith("/img/"):
            rel = unquote(path[len("/img/"):])
            f = (DERIV / rel).resolve()
            if DERIV.resolve() in f.parents and f.exists():
                ct = "image/avif" if f.suffix == ".avif" else "image/webp"
                return self._send(200, f.read_bytes(), ct)
            return self._send(404, b"not found", "text/plain")
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) or b"{}")
        if path == "/api/save":
            with _lock:
                m = load(MANIFEST, {})
                rec = m.get(data["key"])
                if rec is None:
                    return self._send(404, {"error": "unknown key"})
                rec.update(data["patch"])
                rec["reviewed"] = True
                save_manifest(m)
            return self._send(200, {"ok": True})
        if path == "/api/collection":
            title = data["title"].strip()
            slug = slugify(title)
            place = (data.get("place") or "").strip()
            with _lock:
                reg = load(COLLECTIONS, {"collections": []})
                if not any(c["slug"] == slug for c in reg["collections"]):
                    reg["collections"].append({
                        "slug": slug, "title": title, "description": "",
                        "featured": False, "cover": None, "order": 0,
                        "type": "curated", "place": place,
                    })
                    atomic_write(COLLECTIONS, reg)
            return self._send(200, {"slug": slug, "collections": reg["collections"]})
        if path == "/api/collection/update":
            slug = data["slug"]
            with _lock:
                reg = load(COLLECTIONS, {"collections": []})
                for c in reg["collections"]:
                    if c["slug"] == slug:
                        for f in ("title", "featured", "order", "place", "places", "description"):
                            if f in data:
                                c[f] = data[f]
                        break
                atomic_write(COLLECTIONS, reg)
            return self._send(200, {"collections": reg["collections"]})
        return self._send(404, {"error": "not found"})


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Photo tagger running at {url}  (Ctrl-C to stop)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    srv.serve_forever()


if __name__ == "__main__":
    main()
