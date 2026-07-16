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
  • Duplicates   — reviews near-duplicate groups found by scripts/photos/dupes.py
                   (data/duplicates.json): keep-only-one, delete individual frames,
                   or dismiss a group as not-duplicates. Deletes use the same
                   full-removal path as everywhere else (manifest+R2+deny-list).

AUTOSAVES every change to data/photos.json / data/collections.json and marks
edited photos reviewed=true so the pipeline never overwrites hand edits.
"""

import json
import os
import re
import subprocess
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "data" / "photos.json"
COLLECTIONS = REPO / "data" / "collections.json"
TAXONOMY = REPO / "data" / "taxonomy.json"
PLACES = REPO / "data" / "places.json"
DELETIONS = REPO / "deleted-photos.jsonl"  # append-only record of deletes
DUPES = REPO / "data" / "duplicates.json"  # near-duplicate groups (scripts/photos/dupes.py)
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
 .cam{color:#71717a} .cam-old{color:#b45309;font-weight:600}
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
 .chip.role.on{background:#d97706;border-color:#d97706;color:#fff}
 .chip.med.on{background:#0891b2;border-color:#0891b2;color:#fff}
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
 .ctable tr.role-row{background:#fff7ed}
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
 .cell .cbadge{position:absolute;top:32px;left:6px;font-size:12px;line-height:1;padding:4px 6px;border-radius:6px;background:#fff;border:1px solid #d4d4d8;color:#a1a1aa;cursor:pointer;z-index:2}
 .cell .cbadge.on{background:#16a34a;border-color:#16a34a;color:#fff}
 .cell .cbadge:hover{border-color:#16a34a}
 .linkbtn.arch{color:#a1a1aa} .linkbtn.arch:hover{color:#dc2626}
 .archhead{padding:14px 8px 6px;font-size:12px;font-weight:700;color:#a1a1aa;text-transform:uppercase;letter-spacing:.04em;border-top:2px solid #e4e4e7}
 .archrow td{color:#a1a1aa;background:#fafafa}
 .cell.out:hover{opacity:.85}
 .cell .cmbtn{position:absolute;top:6px;left:6px;z-index:2;width:22px;height:22px;padding:0;border-radius:6px;background:rgba(255,255,255,.92);border:1px solid #d4d4d8;font-size:13px;line-height:1;cursor:pointer}
 .cell .cmenu{position:absolute;top:30px;left:6px;z-index:4;background:#fff;border:1px solid #d4d4d8;border-radius:8px;padding:6px;box-shadow:0 4px 14px rgba(0,0,0,.18);display:flex;flex-direction:column;gap:6px;width:180px}
 .cell .cmenu select{width:100%;font-size:12px}
 .del{border:1px solid #ef4444;color:#ef4444;background:#fff;border-radius:6px;font-size:12px;padding:5px 8px;cursor:pointer}
 .del:hover{background:#ef4444;color:#fff}
 .del.small{margin-top:8px;padding:3px 8px}
 .ctable textarea.caption{width:100%;min-height:52px;font:inherit;font-size:12.5px;padding:6px 9px;border:1px solid #d4d4d8;border-radius:6px;resize:vertical}
 .ctable tr.caprow td{padding-top:0;border-bottom:1px solid #f0f0f1}
 .caplabel{font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:#a1a1aa;margin-bottom:3px}
 .deleting{opacity:.4;pointer-events:none;transition:opacity .15s}
 .dgroup{background:#fff;border:1px solid #e4e4e7;border-radius:10px;margin:14px 18px;padding:12px 14px}
 .dhead{font-size:13px;color:#52525b;margin-bottom:10px;display:flex;align-items:center;gap:14px}
 .drow{display:flex;gap:12px;flex-wrap:wrap}
 .dcard{width:270px} .dcard img{width:270px;height:270px;object-fit:contain;background:#18181b;border-radius:8px;display:block}
 .dmeta{font-size:11px;color:#71717a;margin:6px 0;line-height:1.5}
 .dbtns{display:flex;gap:8px;align-items:center}
 .keep{border:1px solid #16a34a;color:#16a34a;background:#fff;border-radius:6px;font-size:12px;padding:5px 10px;cursor:pointer}
 .keep:hover{background:#16a34a;color:#fff}
 .keepall{border:1px solid #d4d4d8;background:#fff;border-radius:6px;font-size:12px;padding:4px 10px;cursor:pointer;color:#52525b}
 .keepall:hover{border-color:#16a34a;color:#16a34a}
 .removing{opacity:0;transform:scale(.92);transition:opacity .25s,transform .25s}
</style></head><body>
<header>
 <h1>Photo Tagger</h1>
 <div class="seg" id="modeseg">
   <button data-mode="tag" class="on">Tag photos</button>
   <button data-mode="colls">Collections</button>
   <button data-mode="dupes">Duplicates</button>
 </div>
 <span id="filters"></span>
 <span class="spacer"></span>
 <span class="save-flash" id="flash">saved ✓</span>
 <span class="stat" id="stat"></span>
</header>
<main id="main"></main>
<script>
let PHOTOS={}, COLLS=[], TAX=[], SHOOTS=[], DUPES=[];
let mode='tag', page=0, memberSlug=null;
const PER=48, GRIDPER=60;                     // list page size / grid page size
const $=s=>document.querySelector(s);
const esc=s=>String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;');
// For a value placed inside an onclick JS single-quoted string: backslash-escape
// \ and ' (keys like "Buffalo '26/..." contain apostrophes), then HTML-escape.
const jesc=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;').replace(/\\/g,'\\\\').replace(/'/g,"\\'");
const arr=(k,d)=>{const v=PHOTOS[k][d];return Array.isArray(v)?v:(v?[v]:[]);};
const uniq=a=>[...new Set(a.filter(Boolean))].sort();

async function boot(){
  const d=await (await fetch('/api/data')).json();
  PHOTOS=d.photos; COLLS=d.collections; TAX=d.taxonomy||[]; SHOOTS=d.shoots||[]; DUPES=d.dupes||[];
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
const tagFilters={shoot:'',city:'',state:'',coll:'',medium:'',camera:'',review:'',q:''};
function tagVisible(){
  const f=tagFilters;
  return Object.keys(PHOTOS).filter(k=>{
    const p=PHOTOS[k];
    if(f.shoot&&p.shoot!==f.shoot)return false;
    if(f.city&&p.city!==f.city)return false;
    if(f.state&&p.state!==f.state)return false;
    if(f.coll&&!(p.collections||[]).includes(f.coll))return false;
    if(f.medium&&(p.medium||'')!==f.medium)return false;
    if(f.camera&&(p.camera||'')!==f.camera)return false;
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
  <select id="f-medium"><option value="">Any medium</option><option value="Digital"${tagFilters.medium==='Digital'?' selected':''}>Digital</option><option value="Film"${tagFilters.medium==='Film'?' selected':''}>Film</option></select>
  <select id="f-camera"><option value="">Any camera</option>${opt(uniq(Object.values(PHOTOS).map(p=>p.camera)).map(c=>({v:c,t:c})),tagFilters.camera)}</select>
  <select id="f-review"><option value="">All</option><option value="un"${tagFilters.review==='un'?' selected':''}>Unreviewed</option><option value="rev"${tagFilters.review==='rev'?' selected':''}>Reviewed</option></select>
  <input class="search" id="f-q" placeholder="search…" value="${esc(tagFilters.q)}">`;
}
function wireTagFilters(){
  const bind=(id,key,ev)=>{const el=$(id);if(!el)return;el.addEventListener(ev,()=>{tagFilters[key]=el.value;page=0;render();});};
  bind('#f-shoot','shoot','change');bind('#f-city','city','change');bind('#f-state','state','change');
  bind('#f-coll','coll','change');bind('#f-medium','medium','change');bind('#f-camera','camera','change');bind('#f-review','review','change');
  const q=$('#f-q');if(q){q.addEventListener('input',()=>{tagFilters.q=q.value;page=0;renderList();});q.focus();q.setSelectionRange(q.value.length,q.value.length);}
}
function geoRow(key){
  const p=PHOTOS[key];
  const inp=(f,label)=>`<div><label>${label}</label><input list="dl-${f}" value="${esc(p[f]||'')}"
     onchange="save('${jesc(key)}',{${f}:this.value||null})"></div>`;
  return `<div class="geo">${inp('sub_neighborhood','Sub-nbhd')}${inp('neighborhood','Neighborhood')}${inp('city','City')}${inp('state','State')}</div>`;
}
function chipRow(key,dim){
  const cur=arr(key,dim.key);
  return `<div class="dim" data-dim="${dim.key}"><div class="label">${dim.label}</div><div class="chips">`+
    dim.values.map(v=>`<span class="chip ${cur.includes(v)?'on':''}" onclick="toggleDim('${jesc(key)}','${dim.key}','${jesc(v)}')">${esc(v)}</span>`).join('')+`</div></div>`;
}
function collRow(key){
  const cur=new Set(PHOTOS[key].collections||[]);
  const chips=COLLS.slice().sort((a,b)=>a.title.localeCompare(b.title))
    .map(c=>`<span class="chip coll ${cur.has(c.slug)?'on':''}" onclick="toggleColl('${jesc(key)}','${c.slug}')">${esc(c.title)}</span>`).join('');
  return `<div class="dim" data-dim="collections"><div class="label">Collections</div><div class="chips">${chips||'<span class="notes">none</span>'}</div>
    <div class="newcoll"><input placeholder="New collection…" id="nc-${cssid(key)}">
    <button onclick="(()=>{const i=document.getElementById('nc-${cssid(key)}');if(i.value.trim())newCollection(i.value.trim(),'${jesc(key)}')})()">＋ create & add</button></div></div>`;
}
const cssid=k=>k.replace(/[^a-z0-9]/gi,'_');
// Special roles: Hero (in the home-page hero rotation) + Place cover (this
// photo represents its place on /places). One cover per city.
function rolesRow(key){
  const p=PHOTOS[key];
  return `<div class="dim" data-dim="roles"><div class="label">Roles</div><div class="chips">`+
    `<span class="chip role ${p.hero?'on':''}" onclick="toggleHero('${jesc(key)}')">★ Hero</span>`+
    `<span class="chip role ${p.place_cover?'on':''}" onclick="toggleCover('${jesc(key)}')">⚑ Place cover</span>`+
    `</div></div>`;
}
// Medium: single-select Film vs Digital (the `medium` field).
function mediumRow(key){
  const cur=PHOTOS[key].medium||'';
  const chip=v=>`<span class="chip med ${cur===v?'on':''}" onclick="setMedium('${jesc(key)}','${v}')">${v}</span>`;
  return `<div class="dim" data-dim="medium"><div class="label">Medium</div><div class="chips">${chip('Digital')}${chip('Film')}</div></div>`;
}
window.setMedium=(key,v)=>{PHOTOS[key].medium=v;save(key,{medium:v});repaint(key,'medium',mediumRow(key));};
window.toggleHero=(key)=>{const v=!PHOTOS[key].hero;PHOTOS[key].hero=v;save(key,{hero:v});repaint(key,'roles',rolesRow(key));};
window.toggleCover=(key)=>{const v=!PHOTOS[key].place_cover;
  if(v){const city=PHOTOS[key].city;Object.keys(PHOTOS).forEach(k=>{
    if(k!==key&&PHOTOS[k].city===city&&PHOTOS[k].place_cover){PHOTOS[k].place_cover=false;save(k,{place_cover:false});
      const c=document.querySelector(`.row[data-key="${CSS.escape(k)}"] [data-dim="roles"]`);if(c)c.outerHTML=rolesRow(k);}});}
  PHOTOS[key].place_cover=v;save(key,{place_cover:v});repaint(key,'roles',rolesRow(key));};
window.toggleDim=(key,dim,v)=>{const s=new Set(arr(key,dim));s.has(v)?s.delete(v):s.add(v);
  PHOTOS[key][dim]=[...s];save(key,{[dim]:[...s]});repaint(key,dim,chipRow(key,TAX.find(x=>x.key===dim)));};
window.toggleColl=(key,slug)=>{const s=new Set(PHOTOS[key].collections||[]);s.has(slug)?s.delete(slug):s.add(slug);
  PHOTOS[key].collections=[...s];save(key,{collections:[...s]});repaint(key,'collections',collRow(key));};
// Cell "⋯" actions: add to another collection, or delete the photo everywhere.
window.toggleMenu=(key)=>{const el=document.getElementById('menu-'+cssid(key));if(el)el.style.display=(el.style.display==='none'?'block':'none');};
window.addToColl=(key,slug)=>{if(!slug)return;const s=new Set(PHOTOS[key].collections||[]);s.add(slug);PHOTOS[key].collections=[...s];save(key,{collections:[...s]});};
window.deletePhoto=async(key)=>{
  if(!confirm('Delete this photo from the site + R2 for good? (Recorded in deleted-photos.jsonl.)'))return;
  const els=[...document.querySelectorAll(`[data-key="${CSS.escape(key)}"]`)];
  els.forEach(e=>e.classList.add('deleting'));           // instant feedback
  let r=null; try{r=await fetch('/api/delete',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({key})});}catch(e){}
  if(!r||!r.ok){els.forEach(e=>e.classList.remove('deleting'));alert('Delete failed — nothing was removed.');return;}
  delete PHOTOS[key];
  els.forEach(e=>{e.classList.add('removing');setTimeout(()=>e.remove(),260);});  // fade out
  flash();
  if(mode==='members')setTimeout(()=>{$('#stat').textContent=`${targetCount(memberSlug)} in set`;},280);
};
function cellMenu(key){
  return `<button class="cmbtn" title="More…" onclick="event.stopPropagation();toggleMenu('${jesc(key)}')">⋯</button>
    <div class="cmenu" id="menu-${cssid(key)}" style="display:none" onclick="event.stopPropagation()">
      <select onchange="addToColl('${jesc(key)}',this.value);this.value=''"><option value="">+ Add to collection…</option>`+
      COLLS.slice().sort((a,b)=>a.title.localeCompare(b.title)).map(c=>`<option value="${esc(c.slug)}">${esc(c.title)}</option>`).join('')+
      `</select><button class="del" onclick="deletePhoto('${jesc(key)}')">🗑 Delete photo</button></div>`;
}
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
        <div class="imgmeta"><b>${esc(p.file)}</b> · ${esc(p.shoot)} · #${p.img_no}${p.camera?` · <span class="cam ${p.camera==='EOS 7D'?'cam-old':''}">${esc(p.camera)}</span>`:''}</div>
        ${p.tag_notes?`<div class="notes">“${esc(p.tag_notes)}”</div>`:''}
        <button class="del small" onclick="deletePhoto('${jesc(key)}')">🗑 Delete photo</button></div>
      <div>${geoRow(key)}${rolesRow(key)}${mediumRow(key)}${dims}${collRow(key)}</div></div>`;
  }).join('')+pager(page,pages,all.length)+datalists();
  wirePager();
}

/* ================= DUPLICATES MODE ================= */
// Groups come from scripts/photos/dupes.py -> data/duplicates.json.
// Review actions: "Keep only this" deletes the rest of the group; per-photo 🗑;
// "Not duplicates" dismisses the group. Group status persists via /api/dupes.
async function setDupeStatus(id,status){
  const g=DUPES.find(x=>x.id===id); if(g)g.status=status;
  await fetch('/api/dupes',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({id,status})});
  flash();
}
window.dupeKeepAll=async(id)=>{await setDupeStatus(id,'kept');renderDupes();};
window.dupeDelete=async(id,key)=>{
  const g=DUPES.find(x=>x.id===id); if(!g)return;
  if(!confirm('Delete '+key.split('/').pop()+' from the site + R2 for good?'))return;
  let r=null; try{r=await fetch('/api/delete',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({key})});}catch(e){}
  if(!r||!r.ok){alert('Delete failed — nothing was removed.');return;}
  delete PHOTOS[key];
  g.keys=g.keys.filter(k=>k!==key);
  if(g.keys.length<2)await setDupeStatus(id,'resolved');
  flash();renderDupes();
};
window.dupeKeepOnly=async(id,key)=>{
  const g=DUPES.find(x=>x.id===id); if(!g)return;
  const losers=g.keys.filter(k=>k!==key);
  if(!confirm('Keep only '+key.split('/').pop()+' and DELETE the other '+losers.length+' from the site + R2 for good?'))return;
  for(const k of losers){
    let r=null; try{r=await fetch('/api/delete',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({key:k})});}catch(e){}
    if(r&&r.ok)delete PHOTOS[k];
  }
  g.keys=[key];
  await setDupeStatus(id,'resolved');
  renderDupes();
};
function renderDupes(){
  const open=DUPES.filter(g=>g.status==='open'&&g.keys.filter(k=>PHOTOS[k]).length>1);
  const done=DUPES.length-open.length;
  $('#stat').textContent=`${open.length} open group${open.length===1?'':'s'} · ${done} resolved/kept`;
  if(!open.length){$('#main').innerHTML='<div class="dgroup"><em>No open duplicate groups. Re-run scripts/photos/dupes.py after new ingests.</em></div>';return;}
  $('#main').innerHTML=open.map(g=>{
    const cards=g.keys.filter(k=>PHOTOS[k]).map(k=>{
      const p=PHOTOS[k];
      return `<div class="dcard" data-key="${esc(k)}">
        <img loading="lazy" src="/img/${p.thumb}">
        <div class="dmeta"><b>${esc(p.file)}</b><br>#${p.img_no} · ${p.width}×${p.height}${p.camera?' · '+esc(p.camera):''}${p.reviewed?' · ✓reviewed':''}<br>${esc(p.shoot)}</div>
        <div class="dbtns">
          <button class="keep" onclick="dupeKeepOnly(${g.id},'${jesc(k)}')">Keep only this</button>
          <button class="del small" onclick="dupeDelete(${g.id},'${jesc(k)}')">🗑</button>
        </div></div>`;
    }).join('');
    return `<div class="dgroup" id="dg-${g.id}">
      <div class="dhead">Group ${g.id} · ${g.keys.length} photos
        <button class="keepall" onclick="dupeKeepAll(${g.id})">✓ Not duplicates — keep all</button></div>
      <div class="drow">${cards}</div></div>`;
  }).join('');
  window.scrollTo(0,0);
}

/* ================= COLLECTIONS MODE ================= */
function collCount(slug){return Object.values(PHOTOS).filter(p=>(p.collections||[]).includes(slug)).length;}
function collPlacesStr(c){const a=(c.places&&c.places.length)?c.places:(c.place?[c.place]:[]);return a.join(', ');}
window.savePlaces=(slug,val)=>{const a=val.split(',').map(s=>s.trim()).filter(Boolean);updateColl(slug,{places:a,place:a[0]||''});};
function renderColls(){
  const active=COLLS.filter(c=>!c.archived), archived=COLLS.filter(c=>c.archived);
  $('#stat').textContent=`${active.length} collections${archived.length?` · ${archived.length} archived`:''}`;
  const rows=active.slice().sort((a,b)=>(a.featured===b.featured)?(a.order-b.order)||a.title.localeCompare(b.title):(a.featured?-1:1))
   .map(c=>`<tr class="${c.featured?'feat':''}">
     <td><input class="title" value="${esc(c.title)}" onchange="updateColl('${esc(c.slug)}',{title:this.value})"></td>
     <td><input class="place" list="dl-place" value="${esc(collPlacesStr(c))}" placeholder="e.g. Newark, Brooklyn" onchange="savePlaces('${esc(c.slug)}',this.value)"></td>
     <td class="ct">${collCount(c.slug)}</td>
     <td><input type="checkbox" ${c.featured?'checked':''} onchange="updateColl('${esc(c.slug)}',{featured:this.checked})"></td>
     <td><input class="order" type="number" min="0" value="${c.order||0}" onchange="updateColl('${esc(c.slug)}',{order:+this.value})"></td>
     <td title="Eligible for the home-page collage hero. Curate which members show via the ▦ toggle in Edit members."><input type="checkbox" ${c.collage?'checked':''} onchange="updateColl('${esc(c.slug)}',{collage:this.checked})"> <span class="ct">${c.collage?collageCount(c.slug)+' ▦':''}</span></td>
     <td><button class="linkbtn" onclick="editMembers('${esc(c.slug)}')">Edit members →</button>
         <button class="linkbtn arch" title="Remove from the site (membership kept; restore anytime from the Archived list below)" onclick="archiveColl('${esc(c.slug)}')">Archive</button></td>
   </tr>
   <tr class="caprow${c.featured?' feat':''}"><td colspan="7"><div class="caplabel">Caption${c.featured?' — shown on the home page':''}</div><textarea class="caption" placeholder="Write a 2–10 sentence caption…" onchange="updateColl('${esc(c.slug)}',{caption:this.value})">${esc(c.caption||'')}</textarea></td></tr>`).join('');
  const archRows=archived.slice().sort((a,b)=>a.title.localeCompare(b.title))
   .map(c=>`<tr class="archrow">
     <td class="ct">${esc(c.title)}</td>
     <td class="ct">${esc(collPlacesStr(c))}</td>
     <td class="ct">${collCount(c.slug)}</td>
     <td class="ct" colspan="3">archived — not on the site; membership preserved</td>
     <td><button class="linkbtn" onclick="restoreColl('${esc(c.slug)}')">Restore</button></td>
   </tr>`).join('');
  const archBlock=archived.length?`<tr><td colspan="7" class="archhead">Archived (${archived.length})</td></tr>${archRows}`:'';
  const cities=uniq(Object.values(PHOTOS).map(p=>p.city));
  // Two special "sets" browsable in the same grid: the home Hero rotation and
  // the per-place cover photos.
  const roleRows=`
   <tr class="role-row"><td><b>★ Hero</b> <span class="ct">— home hero rotation</span></td><td class="ct">any</td><td class="ct">${targetCount('__hero')}</td><td class="ct">—</td><td class="ct">—</td><td class="ct">—</td><td><button class="linkbtn" onclick="editMembers('__hero')">Edit set →</button></td></tr>
   <tr class="role-row"><td><b>⚑ Place cover</b> <span class="ct">— one per place</span></td><td class="ct">per city</td><td class="ct">${targetCount('__cover')}</td><td class="ct">—</td><td class="ct">—</td><td class="ct">—</td><td><button class="linkbtn" onclick="editMembers('__cover')">Edit set →</button></td></tr>`;
  $('#main').innerHTML=`<p class="hint">Rename via the title. <b>Place</b> is editable — type one or several <b>comma-separated</b> locations (e.g. “Newark, Brooklyn”) to span multiple; the site’s Collections filter then lists it under each. Tick <b>Featured</b> + set <b>Order</b> (1,2,3…) to choose the home-page 5 and their sequence. Tick <b>Collage</b> to make a collection eligible for the home-page collage hero — then curate WHICH photos show with the ▦ toggle inside “Edit members” (aim for 12–18; fewer than 8 gets topped up automatically). “Edit members / set” opens the add/remove grid — that includes the two special sets at the top: ★ Hero and ⚑ Place cover.</p>
   <table class="ctable"><thead><tr><th>Title</th><th>Place(s)</th><th>Photos</th><th>Featured</th><th>Order</th><th>Collage</th><th></th></tr></thead><tbody>${roleRows}${rows}${archBlock}</tbody></table>
   <datalist id="dl-place">${cities.map(c=>`<option value="${esc(c)}">`).join('')}</datalist>`;
}
function collageCount(slug){return Object.keys(PHOTOS).filter(k=>(PHOTOS[k].collections||[]).includes(slug)&&PHOTOS[k].collage).length;}
window.archiveColl=async(slug)=>{const c=COLLS.find(x=>x.slug===slug);if(!c)return;
  let msg=`Archive “${c.title}”? It disappears from the site (collections page, place pages${c.featured?', AND the home page — it is currently FEATURED':''}${c.collage?', and the collage pool':''}). Membership is kept; restore anytime.`;
  if(!confirm(msg))return;
  await updateColl(slug,{archived:true});render();};
window.restoreColl=async(slug)=>{await updateColl(slug,{archived:false});render();};
window.editMembers=(slug)=>{mode='members';memberSlug=slug;page=0;memberFilter.city='';memberFilter.all=false;emptiedKeys=null;render();};
/* After "Empty collection", the former members stay in the grid (as one-click
   re-adds) — rebuilding from zero without wading through all photos. Session-
   scoped; cleared when switching collections. */
let emptiedKeys=null;

/* ============ EDIT-MEMBERS GRID (collections + Hero / Place-cover) ============
   memberSlug is a collection slug, or the pseudo-targets "__hero" / "__cover"
   (per-photo flags). isIn/setIn branch on which; the rest is shared. */
const memberFilter={city:'',all:false};
function targetLabel(t){return t==='__hero'?'★ Hero':t==='__cover'?'⚑ Place cover':((COLLS.find(x=>x.slug===t)||{}).title||t);}
function isIn(key,t){const p=PHOTOS[key];return t==='__hero'?!!p.hero:t==='__cover'?!!p.place_cover:(p.collections||[]).includes(t);}
function targetCount(t){return Object.keys(PHOTOS).filter(k=>isIn(k,t)).length;}
function setIn(key,t,on){const p=PHOTOS[key];
  if(t==='__hero'){p.hero=on;save(key,{hero:on});}
  else if(t==='__cover'){
    if(on){const city=p.city;Object.keys(PHOTOS).forEach(k=>{if(k!==key&&PHOTOS[k].city===city&&PHOTOS[k].place_cover){PHOTOS[k].place_cover=false;save(k,{place_cover:false});}});}
    p.place_cover=on;save(key,{place_cover:on});}
  else{const s=new Set(p.collections||[]);on?s.add(t):s.delete(t);p.collections=[...s];save(key,{collections:[...s]});}}
function memberList(){
  const t=memberSlug;
  let keys=memberFilter.all?Object.keys(PHOTOS):Object.keys(PHOTOS).filter(k=>isIn(k,t)||(emptiedKeys&&emptiedKeys.has(k)));
  if(memberFilter.city)keys=keys.filter(k=>PHOTOS[k].city===memberFilter.city);
  return keys.sort((a,b)=>(PHOTOS[a].shoot||'').localeCompare(PHOTOS[b].shoot||'')||(PHOTOS[a].img_no-PHOTOS[b].img_no));
}
window.toggleMember=(key)=>{const t=memberSlug;const on=!isIn(key,t);setIn(key,t,on);
  if(t==='__cover'){render();return;}   // one-per-city may clear another cover → full refresh
  const cell=document.querySelector(`.cell[data-key="${CSS.escape(key)}"]`);
  if(cell){cell.classList.toggle('out',!on);cell.querySelector('.badge').textContent=on?'in':'add';}
  $('#stat').textContent=`${targetCount(t)} in set`;};
/* Per-photo collage inclusion (photo.collage). Only shown for collage-enabled
   collections. NOTE: the flag is per-PHOTO — a photo in two collage-enabled
   collections shows in both pools. */
function collActive(){const c=COLLS.find(x=>x.slug===memberSlug);return !!(c&&c.collage);}
window.toggleCollage=(ev,key)=>{ev.stopPropagation();
  const p=PHOTOS[key];p.collage=!p.collage;save(key,{collage:p.collage});
  const b=document.querySelector(`.cell[data-key="${CSS.escape(key)}"] .cbadge`);
  if(b)b.classList.toggle('on',p.collage);
  memberStat();};
/* Empty a collection's MEMBERSHIP (not collage flags): remove every photo from
   this collection so it can be rebuilt one-by-one via "show all photos".
   Regular collections only — not the ★/⚑ pseudo-sets. */
window.emptyCollection=async()=>{const t=memberSlug;
  if(t==='__hero'||t==='__cover')return;
  const keys=Object.keys(PHOTOS).filter(k=>(PHOTOS[k].collections||[]).includes(t));
  if(!keys.length)return;
  const c=COLLS.find(x=>x.slug===t);
  if(!confirm(`Remove ALL ${keys.length} photos from “${(c&&c.title)||t}”?\n\nPhotos are NOT deleted — they STAY in this grid so you can click your keepers straight back in.`))return;
  await Promise.all(keys.map(k=>{const s=(PHOTOS[k].collections||[]).filter(x=>x!==t);PHOTOS[k].collections=s;
    return fetch('/api/save',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({key:k,patch:{collections:s}})});}));
  emptiedKeys=new Set(keys);
  render();};
window.deselectAllCollage=async()=>{const t=memberSlug;
  const keys=Object.keys(PHOTOS).filter(k=>(PHOTOS[k].collections||[]).includes(t)&&PHOTOS[k].collage);
  if(!keys.length)return;
  if(!confirm(`Clear the ▦ collage flag on ${keys.length} photo${keys.length===1?'':'s'} in this collection?`))return;
  await Promise.all(keys.map(k=>{PHOTOS[k].collage=false;
    return fetch('/api/save',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({key:k,patch:{collage:false}})});}));
  render();};
function memberStat(){const t=memberSlug;let s=`${targetCount(t)} in set`;
  if(collActive())s+=` · ${collageCount(t)} ▦ in collage`;
  $('#stat').textContent=s;}
function renderMembers(){
  const t=memberSlug;
  const cities=uniq(Object.values(PHOTOS).map(p=>p.city));
  const all=memberList(), pages=Math.max(1,Math.ceil(all.length/GRIDPER));
  if(page>=pages)page=pages-1;
  const slice=all.slice(page*GRIDPER,page*GRIDPER+GRIDPER);
  memberStat();
  const showCollage=collActive();
  $('#main').innerHTML=`<p class="hint"><button class="linkbtn" onclick="backToColls()">← Collections</button> &nbsp; Editing <b>${esc(targetLabel(t))}</b>.
     Click a photo to ${memberFilter.all?'add/remove':'remove'} it. Autosaves.${showCollage?' &nbsp;·&nbsp; <b>▦</b> = include in the home-page collage (click the corner chip).':''}</p>
    <div style="display:flex;gap:10px;align-items:center;margin-bottom:12px">
      <label style="font-size:13px"><input type="checkbox" id="m-all" ${memberFilter.all?'checked':''}> show all photos (to add)</label>
      <select id="m-city"><option value="">All cities</option>${cities.map(c=>`<option value="${esc(c)}"${c===memberFilter.city?' selected':''}>${esc(c)}</option>`).join('')}</select>
      ${showCollage?`<button class="keepall" onclick="deselectAllCollage()" title="Clear every ▦ collage flag in this collection">✕ Deselect all ▦</button>`:''}
      ${(t!=='__hero'&&t!=='__cover')?`<button class="keepall" onclick="emptyCollection()" title="Remove every photo from this collection (membership only — nothing is deleted) so you can rebuild it one by one">⊘ Empty collection…</button>`:''}
    </div>
    <div class="grid">`+slice.map(key=>{const p=PHOTOS[key];const inn=isIn(key,t);
      const cb=showCollage&&inn?`<span class="cbadge${p.collage?' on':''}" title="Include in home-page collage" onclick="toggleCollage(event,'${jesc(key)}')">▦</span>`:'';
      return `<div class="cell ${inn?'':'out'}" data-key="${esc(key)}" onclick="toggleMember('${jesc(key)}')">
        <span class="badge">${inn?'in':'add'}</span>${cb}${cellMenu(key)}<img loading="lazy" src="/img/${p.thumb}">
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
    else if(mode==='dupes')renderDupes();
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
            dupes = load(DUPES, {"groups": []})["groups"]
            return self._send(200, {"photos": m, "collections": colls, "taxonomy": tax, "shoots": shoots, "dupes": dupes})
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
        if path == "/api/delete":
            # Remove a photo everywhere: manifest, R2 (all tiers), local cache,
            # and append it to deleted-photos.jsonl (deny-list + record).
            key = data["key"]
            with _lock:
                m = load(MANIFEST, {})
                rec = m.pop(key, None)
                if rec is None:
                    return self._send(404, {"error": "unknown key"})
                entry = {"key": key, "deleted_at": datetime.now(timezone.utc).isoformat(),
                         "city": rec.get("city"), "shoot": rec.get("shoot"),
                         "thumb": rec.get("thumb"), "tag_notes": rec.get("tag_notes")}
                with open(DELETIONS, "a") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
                save_manifest(m)
            # R2 + local-cache cleanup runs in the background so the response is
            # instant (3 wrangler calls would otherwise block ~5s). The manifest
            # removal + log above are the source-of-truth deletion.
            tiers = [rec.get(t) for t in ("thumb", "display_avif", "display_webp") if rec.get(t)]
            def _cleanup(paths):
                for rel in paths:
                    subprocess.run(["npx", "wrangler", "r2", "object", "delete",
                                    f"gautamiyer-photos/{rel}", "--remote"], capture_output=True)
                    try:
                        (DERIV / rel).unlink()
                    except FileNotFoundError:
                        pass
            threading.Thread(target=_cleanup, args=(tiers,), daemon=True).start()
            return self._send(200, {"ok": True})
        if path == "/api/dupes":
            # Persist a duplicate group's review status (open | kept | resolved).
            with _lock:
                d = load(DUPES, {"groups": []})
                for g in d["groups"]:
                    if g["id"] == data["id"]:
                        g["status"] = data["status"]
                        break
                atomic_write(DUPES, d)
            return self._send(200, {"ok": True})
        if path == "/api/collection/update":
            slug = data["slug"]
            with _lock:
                reg = load(COLLECTIONS, {"collections": []})
                for c in reg["collections"]:
                    if c["slug"] == slug:
                        for f in ("title", "featured", "order", "place", "places", "description", "caption", "collage", "archived"):
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
