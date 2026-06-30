#!/usr/bin/env python3
"""
Internal photo tagger — a dependency-free local web app for reviewing/curating tags.

Run:   python3 scripts/photos/tagger.py        (opens http://localhost:8800)

What it does:
  - Lists photos (filter by shoot / city / reviewed state) with their thumbnails.
  - Per photo: verify neighborhood + click-toggle Land use / Architecture / Subject / Tone.
  - Collections control: toggle membership in existing collections, or create a new one inline.
  - AUTOSAVES every change to data/photos.json (and data/collections.json), and marks the
    photo reviewed=true so the tagging pipeline never overwrites your hand edits.

It reads/writes the same files the Hugo site + pipeline use, so changes flow straight to the site.
"""

import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "data" / "photos.json"
COLLECTIONS = REPO / "data" / "collections.json"
TAXONOMY = REPO / "data" / "taxonomy.json"
DERIV = REPO / ".photo-build" / "derivatives"
PORT = 8800

_lock = threading.Lock()


def slugify(s):
    out = "".join(c.lower() if c.isalnum() else "-" for c in s)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def load(path, default):
    if path.exists():
        return json.loads(path.read_text())
    return default


def atomic_write(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def save_manifest(m):
    # match pipeline ordering for clean diffs
    import re
    def key(k):
        nums = re.findall(r"\d+", k)
        return (k.rsplit("/", 1)[0], [int(n) for n in nums])
    atomic_write(MANIFEST, {k: m[k] for k in sorted(m.keys(), key=key)})


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Photo Tagger</title>
<style>
 *{box-sizing:border-box} body{font-family:-apple-system,sans-serif;margin:0;background:#f4f4f5;color:#18181b}
 header{position:sticky;top:0;z-index:5;background:#fff;border-bottom:1px solid #e4e4e7;padding:12px 20px;
   display:flex;gap:16px;align-items:center;flex-wrap:wrap}
 header h1{font-size:15px;margin:0;font-weight:700;letter-spacing:.02em}
 select,input{font:inherit;padding:6px 10px;border:1px solid #d4d4d8;border-radius:6px;background:#fff}
 .stat{font-size:13px;color:#71717a;margin-left:auto}
 .save-flash{font-size:12px;color:#16a34a;opacity:0;transition:opacity .3s}
 .save-flash.on{opacity:1}
 main{padding:16px;max-width:1100px;margin:0 auto}
 .row{display:grid;grid-template-columns:200px 1fr;gap:18px;background:#fff;border:1px solid #e4e4e7;
   border-radius:10px;padding:14px;margin-bottom:14px}
 .row.reviewed{border-color:#86efac;background:#f0fdf4}
 .thumb{width:100%;border-radius:6px;display:block;background:#e4e4e7}
 .imgmeta{font-size:11px;color:#a1a1aa;margin-top:6px;font-variant-numeric:tabular-nums}
 .imgmeta b{color:#52525b}
 .dim{margin-bottom:10px}
 .dim .label{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#a1a1aa;margin-bottom:5px}
 .chips{display:flex;flex-wrap:wrap;gap:6px}
 .chip{font-size:12.5px;padding:5px 11px;border:1px solid #d4d4d8;border-radius:999px;background:#fafafa;
   cursor:pointer;user-select:none;transition:all .12s}
 .chip:hover{border-color:#a1a1aa}
 .chip.on{background:#18181b;color:#fff;border-color:#18181b}
 .chip.coll.on{background:#7c3aed;border-color:#7c3aed}
 .nb{display:flex;gap:8px;align-items:center}
 .nb input{width:240px}
 .reviewbtn{font-size:12px;padding:5px 12px;border-radius:6px;border:1px solid #d4d4d8;background:#fff;cursor:pointer}
 .reviewbtn.on{background:#16a34a;color:#fff;border-color:#16a34a}
 .newcoll{display:flex;gap:6px;margin-top:6px}
 .newcoll input{width:230px}
 .newcoll button{font:inherit;font-size:12px;padding:5px 10px;border-radius:6px;border:1px solid #7c3aed;
   background:#7c3aed;color:#fff;cursor:pointer}
 .notes{font-size:12px;color:#71717a;font-style:italic;margin-top:4px}
</style></head><body>
<header>
 <h1>Photo Tagger</h1>
 <select id="shoot"></select>
 <select id="filter">
   <option value="all">All</option>
   <option value="unreviewed">Unreviewed only</option>
   <option value="reviewed">Reviewed only</option>
 </select>
 <span class="save-flash" id="flash">saved ✓</span>
 <span class="stat" id="stat"></span>
</header>
<main id="list"></main>
<script>
let PHOTOS={}, COLLS=[], SHOOTS=[], TAX=[];
const $=s=>document.querySelector(s);
const esc=s=>String(s).replace(/'/g,"\\'");
const arr=(key,dim)=>{const v=PHOTOS[key][dim];return Array.isArray(v)?v:(v?[v]:[]);};

async function boot(){
  const d = await (await fetch('/api/data')).json();
  PHOTOS=d.photos; COLLS=d.collections; SHOOTS=d.shoots; TAX=d.taxonomy||[];
  const ss=$('#shoot'); ss.innerHTML='<option value="">All shoots</option>'+
    SHOOTS.map(s=>`<option value="${s}">${s}</option>`).join('');
  ss.onchange=render; $('#filter').onchange=render;
  render();
}

function flash(){const f=$('#flash');f.classList.add('on');setTimeout(()=>f.classList.remove('on'),900);}

async function save(key, patch){
  PHOTOS[key]=Object.assign(PHOTOS[key], patch, {reviewed:true});
  await fetch('/api/save',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({key, patch})});
  flash(); updateStat();
  const el=document.querySelector(`[data-key="${CSS.escape(key)}"]`);
  if(el) el.classList.add('reviewed');
}

async function newCollection(title, key){
  const r=await (await fetch('/api/collection',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({title, place: PHOTOS[key].city})})).json();
  COLLS=r.collections;
  const cur=new Set(PHOTOS[key].collections||[]); cur.add(r.slug);
  await save(key,{collections:[...cur]});
  render();
}

function updateStat(){
  const list=visible();
  const rev=list.filter(k=>PHOTOS[k].reviewed).length;
  $('#stat').textContent=`${rev} / ${list.length} reviewed`;
}

function visible(){
  const shoot=$('#shoot').value, filt=$('#filter').value;
  return Object.keys(PHOTOS).filter(k=>{
    const p=PHOTOS[k];
    if(shoot && p.shoot!==shoot) return false;
    if(filt==='unreviewed' && p.reviewed) return false;
    if(filt==='reviewed' && !p.reviewed) return false;
    return true;
  }).sort((a,b)=>(PHOTOS[a].img_no-PHOTOS[b].img_no)||a.localeCompare(b));
}

// dim is a taxonomy object {key,label,values,multi}. Every dim here is multi-select.
function chipRow(key, dim){
  const cur=arr(key,dim.key);
  return `<div class="dim"><div class="label">${dim.label}</div><div class="chips">`+
    dim.values.map(v=>`<span class="chip ${cur.includes(v)?'on':''}" onclick="toggleDim('${esc(key)}','${dim.key}','${esc(v)}')">${v}</span>`).join('')+
    `</div></div>`;
}

function collRow(key){
  const p=PHOTOS[key], cur=new Set(p.collections||[]);
  const chips=COLLS.map(c=>`<span class="chip coll ${cur.has(c.slug)?'on':''}" onclick="toggleColl('${esc(key)}','${c.slug}')">${c.title}</span>`).join('');
  return `<div class="dim"><div class="label">Collections</div><div class="chips">${chips||'<span class="notes">none yet</span>'}</div>`+
    `<div class="newcoll"><input placeholder="New collection name…" id="nc-${cssid(key)}">`+
    `<button onclick="(function(){const i=document.getElementById('nc-${cssid(key)}');if(i.value.trim())newCollection(i.value.trim(),'${esc(key)}')})()">＋ create & add</button></div></div>`;
}
function cssid(k){return k.replace(/[^a-z0-9]/gi,'_');}

window.toggleDim=(key,dim,v)=>{
  const s=new Set(arr(key,dim)); s.has(v)?s.delete(v):s.add(v);
  PHOTOS[key][dim]=[...s]; save(key,{[dim]:[...s]}); paintDim(key,dim);
};
window.toggleColl=(key,slug)=>{const s=new Set(PHOTOS[key].collections||[]);
  s.has(slug)?s.delete(slug):s.add(slug); PHOTOS[key].collections=[...s];
  save(key,{collections:[...s]}); paintColl(key);};

function paintDim(key,dim){const row=document.querySelector(`[data-key="${CSS.escape(key)}"]`);
  if(!row)return; const d=TAX.find(x=>x.key===dim);
  row.querySelector(`[data-dim="${dim}"]`).outerHTML=`<div data-dim="${dim}">${chipRow(key,d)}</div>`;}
function paintColl(key){const row=document.querySelector(`[data-key="${CSS.escape(key)}"]`);
  if(!row)return; row.querySelector('[data-dim="collections"]').outerHTML=`<div data-dim="collections">${collRow(key)}</div>`;}

function render(){
  const list=visible();
  $('#list').innerHTML=list.map(key=>{
    const p=PHOTOS[key];
    const dims=TAX.map(d=>`<div data-dim="${d.key}">${chipRow(key,d)}</div>`).join('');
    return `<div class="row ${p.reviewed?'reviewed':''}" data-key="${key}">
      <div>
        <img class="thumb" loading="lazy" src="/img/${p.thumb}">
        <div class="imgmeta"><b>${p.file}</b> · ${p.city} · #${p.img_no}</div>
        ${p.tag_notes?`<div class="notes">“${p.tag_notes}”</div>`:''}
      </div>
      <div>
        <div class="dim"><div class="label">Neighborhood</div>
          <div class="nb"><input list="hoods" value="${(p.neighborhood||'').replace(/"/g,'&quot;')}"
            onchange="save('${esc(key)}',{neighborhood:this.value||null})"></div></div>
        ${dims}
        <div data-dim="collections">${collRow(key)}</div>
      </div>
    </div>`;
  }).join('') + `<datalist id="hoods">${[...new Set(Object.values(PHOTOS).map(p=>p.neighborhood).filter(Boolean))].map(h=>`<option value="${h}">`).join('')}</datalist>`;
  updateStat();
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
        if path == "/" or path == "/index.html":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if path == "/api/data":
            with _lock:
                m = load(MANIFEST, {})
                colls = load(COLLECTIONS, {"collections": []})["collections"]
                tax = load(TAXONOMY, {"dimensions": []})["dimensions"]
            shoots = sorted({p["shoot"] for p in m.values()})
            return self._send(200, {"photos": m, "collections": colls, "shoots": shoots, "taxonomy": tax})
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
