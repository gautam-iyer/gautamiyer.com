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
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline as PIPE      # SHOOTS registry + the derive/rotate primitives

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "data" / "photos.json"
COLLECTIONS = REPO / "data" / "collections.json"
TAXONOMY = REPO / "data" / "taxonomy.json"
PLACES = REPO / "data" / "places.json"
DELETIONS = REPO / "deleted-photos.jsonl"  # append-only record of deletes
DUPES = REPO / "data" / "duplicates.json"  # near-duplicate groups (scripts/photos/dupes.py)
BREAKS = REPO / "data" / "neighborhood_breaks.json"   # per-shoot neighborhood breakpoints (Neighborhoods mode)
HINTS = REPO / "data" / "neighborhood_hints.json"     # evidence-backed suggestions, accept-or-ignore
DERIV = REPO / ".photo-build" / "derivatives"
PORT = 8800

_lock = threading.Lock()

# ---- rotation ---------------------------------------------------------------
# Rotation is stored as data (`rotate`, clockwise degrees) and re-applied on every
# derive, so the source library in ~/Documents is never touched. Re-deriving one
# photo is ~9s (a 6000px decode dominates), far too slow to block a click, so the
# request only writes the manifest and the pixels are rebuilt on this pool.
_ROT_POOL = ThreadPoolExecutor(max_workers=max(2, (os.cpu_count() or 4) - 2))
_rot_state = {}                       # key -> "pending" | "done" | "error: ..."
_rot_meta = threading.Lock()          # guards _rot_state and _rot_active
_rot_active = set()                   # keys with a full re-derive in flight
_SHOOT_BY_SLUG = {x["slug"]: x for x in PIPE.SHOOTS}


def _orient_of(rec):
    return (PIPE.norm_rotate(rec.get("rotate")), PIPE.norm_flip(rec.get("flip")))


def _rotate_job(key):
    """Rebuild all three tiers from source at the photo's CURRENT orientation.

    COALESCING: clicking ↻ four times must not queue four 9s derives. Only one job
    per key is ever in flight; when it finishes it re-reads the manifest, and if
    more clicks landed while it was encoding it goes round again. So N fast clicks
    cost one or two derives, not N.

    Deliberately does NOT hold `_lock` across the encode, and does NOT call
    pipeline's cmd_derive: that rewrites the WHOLE manifest from a stale in-memory
    copy on exit, which is how a past session lost a batch of tags."""
    try:
        while True:
            with _lock:
                rec = load(MANIFEST, {}).get(key)
                rec = dict(rec) if rec else None
            if rec is None:
                raise KeyError("photo is no longer in the manifest")
            shoot = _SHOOT_BY_SLUG.get(rec.get("shoot"))
            if shoot is None:
                raise KeyError(f"shoot {rec.get('shoot')!r} is not in pipeline.SHOOTS")
            want = _orient_of(rec)
            res = PIPE._derive_one(rec, shoot, force=True)
            if res is None:
                raise RuntimeError("source file missing")
            thumb, avif, webp, _present = res
            # Re-read under the lock: the record may have been edited (or deleted)
            # during the ~9s encode, so patch the LIVE record, never write back the
            # snapshot.
            with _lock:
                m = load(MANIFEST, {})
                live = m.get(key)
                still = _orient_of(live) if live is not None else want
                if live is not None:
                    PIPE._set_local_paths(live, thumb, avif, webp)
                    # The derivative keeps its filename, so the R2 object key is
                    # unchanged and nothing about the URL says it is stale. This
                    # flag is the only record that the live pixels are now wrong.
                    live["needs_upload"] = True
                    live["derived_at"] = int(time.time())
                    save_manifest(m)
            with _rot_meta:
                if still == want:          # nothing new arrived — we are current
                    _rot_state[key] = "done"
                    _rot_active.discard(key)
                    return
            # else: more clicks landed mid-encode, go again at the newer value
    except Exception as e:
        with _rot_meta:
            _rot_state[key] = f"error: {e}"
            _rot_active.discard(key)


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
 .dverdict{font-size:11.5px;padding:2px 8px;border-radius:9px}
 .vd-dupe{background:#fef3c7;color:#92400e} .vd-distinct{background:#dcfce7;color:#166534}
 .keepall:hover{border-color:#16a34a;color:#16a34a}
 .removing{opacity:0;transform:scale(.92);transition:opacity .25s,transform .25s}
 /* ---- Cull mode: mark-then-delete. Marking is reversible and does NOT
    affect the site; only "Delete marked" removes anything. ---- */
 .cullgrid{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-start}
 .cullcell{position:relative;border:2px solid #e4e4e7;border-radius:10px;overflow:hidden;cursor:pointer;background:#fff;flex:0 0 auto}
 :root{--cullh:230px}
 .cullcell img{height:var(--cullh);width:auto;display:block;background:#f4f4f5}
 /* Rotation controls: hover-only so they never compete with the cull mark, which
    is what this grid is actually for. */
 .rot{position:absolute;bottom:24px;right:5px;display:none;gap:4px;z-index:3}
 .cullcell:hover .rot,.row:hover .rot{display:flex}
 .rot button{width:25px;height:25px;padding:0;border-radius:6px;background:rgba(255,255,255,.94);
   border:1px solid #d4d4d8;font-size:14px;line-height:1;cursor:pointer}
 .rot button:hover{background:#fff;border-color:#71717a}
 /* The photo stays fully visible and clickable while the full-quality tiers
    rebuild — the thumbnail is already correct, so dimming it would only hide a
    finished picture and make the tool feel stuck. A corner dot says "still
    working" without taking the photo away. */
 .rotating .rotdot{display:block}
 .rotdot{display:none;position:absolute;top:6px;right:6px;width:9px;height:9px;border-radius:50%;
   background:#2563eb;box-shadow:0 0 0 2px #fff;z-index:5;animation:rotpulse 1s ease-in-out infinite}
 @keyframes rotpulse{0%,100%{opacity:1}50%{opacity:.25}}
 .roterr{outline:2px solid #dc2626;outline-offset:-2px}
 .row .rot{position:static;display:flex;margin-top:6px}
 .upbanner{background:#fef3c7;border:1px solid #fcd34d;color:#78350f;padding:9px 12px;
   border-radius:8px;font-size:12.5px;line-height:1.7;margin:0 0 12px}
 .upbanner code{background:#fffbeb;border:1px solid #fde68a;border-radius:4px;padding:1px 5px;
   font-size:11.5px;font-family:ui-monospace,monospace}
 /* width:0 + min-width:100% keeps a long caption from widening the card —
    the image alone decides the cell width, so shape stays truthful. */
 .cullcell .cap{font-size:11px;color:#52525b;padding:4px 7px;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;width:0;min-width:100%;box-sizing:border-box}
 .cullcell.marked{border-color:#dc2626}
 .cullcell.marked img{opacity:.45;filter:grayscale(.7)}
 .cullcell.cursor{outline:3px solid #2563eb;outline-offset:-3px}
 .cullcell .xmark{position:absolute;top:8px;right:8px;width:26px;height:26px;border-radius:50%;
   background:#dc2626;color:#fff;font-size:15px;font-weight:700;line-height:26px;text-align:center;display:none}
 .cullcell.marked .xmark{display:block}
 .cullbar{display:flex;gap:10px;align-items:center;margin-bottom:12px;flex-wrap:wrap}
 .danger{border:1px solid #dc2626;background:#fff;color:#dc2626;border-radius:6px;font-size:12px;padding:5px 12px;cursor:pointer;font-weight:600}
 .danger:hover{background:#dc2626;color:#fff}
 .danger[disabled]{opacity:.4;cursor:default}
 .danger[disabled]:hover{background:#fff;color:#dc2626}
 .cullnote{font-size:12px;color:#52525b;background:#fafafa;border:1px solid #e4e4e7;border-radius:8px;padding:8px 11px;margin-bottom:12px}
 /* ---- Neighborhoods mode: breakpoint runs over a shoot in IMG order ---- */
 .nbgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
 .nbcell{position:relative;border:1px solid #e4e4e7;border-radius:8px;overflow:hidden;background:#fff}
 .nbcell img{width:100%;height:110px;object-fit:cover;display:block}
 .nbcell .cap{font-size:10.5px;color:#52525b;padding:3px 6px;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .nbcell .cut{position:absolute;top:5px;left:5px;font-size:11px;line-height:1;padding:3px 6px;border-radius:6px;
   background:rgba(255,255,255,.93);border:1px solid #d4d4d8;color:#71717a;cursor:pointer}
 .nbcell .cut:hover{border-color:#2563eb;color:#2563eb}
 .nbcell.isbreak{border-color:#2563eb;border-width:2px}
 .nbcell.isbreak .cut{background:#2563eb;border-color:#2563eb;color:#fff}
 .nbcell.hashint{border-color:#b3872a}
 .runband{grid-column:1/-1;display:flex;gap:10px;align-items:center;margin:10px 0 2px;
   padding:6px 11px;border-radius:8px;background:#eff6ff;border:1px solid #bfdbfe;font-size:13px}
 .runband b{color:#1d4ed8}
 .runband .rm{margin-left:auto;border:0;background:none;color:#94a3b8;cursor:pointer;font-size:12px}
 .runband .rm:hover{color:#dc2626}
 .hintband{grid-column:1/-1;display:flex;gap:10px;align-items:center;margin:10px 0 2px;
   padding:6px 11px;border-radius:8px;background:#fffbeb;border:1px dashed #fcd34d;font-size:12.5px;color:#78350f}
 .hintband button{border:1px solid #b3872a;background:#fff;color:#92400e;border-radius:6px;font-size:11.5px;padding:3px 9px;cursor:pointer}
 .hintband button:hover{background:#b3872a;color:#fff}
 .nbbar{display:flex;gap:10px;align-items:center;margin-bottom:12px;flex-wrap:wrap}
 .apply{border:1px solid #16a34a;background:#fff;color:#16a34a;border-radius:6px;font-size:12px;padding:5px 12px;cursor:pointer;font-weight:600}
 .apply:hover{background:#16a34a;color:#fff}
 .apply[disabled]{opacity:.4;cursor:default} .apply[disabled]:hover{background:#fff;color:#16a34a}
 .bpedit{grid-column:1/-1;display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;margin:10px 0 2px;
   padding:10px 12px;border-radius:8px;background:#fff;border:2px solid #2563eb}
 .bpedit label{display:flex;flex-direction:column;gap:3px;font-size:11px;color:#71717a}
 .bpedit input{font-size:13px;padding:4px 7px;border:1px solid #d4d4d8;border-radius:6px}
 .bpedit .wide{width:190px} .bpedit .narrow{width:56px}
 .bpedit .go{border:1px solid #2563eb;background:#2563eb;color:#fff;border-radius:6px;font-size:12px;padding:6px 13px;cursor:pointer;font-weight:600}
 .bpedit .cancel{border:1px solid #d4d4d8;background:#fff;color:#52525b;border-radius:6px;font-size:12px;padding:6px 11px;cursor:pointer}
 .bpedit .del{border:1px solid #dc2626;background:#fff;color:#dc2626;border-radius:6px;font-size:12px;padding:6px 11px;cursor:pointer}
 .bpedit .hintline{flex-basis:100%;font-size:11.5px;color:#78350f;background:#fffbeb;border:1px dashed #fcd34d;border-radius:6px;padding:5px 8px}
 kbd{background:#f4f4f5;border:1px solid #d4d4d8;border-bottom-width:2px;border-radius:4px;padding:1px 5px;font-size:11px;font-family:ui-monospace,monospace}
</style></head><body>
<header>
 <h1>Photo Tagger</h1>
 <div class="seg" id="modeseg">
   <button data-mode="tag" class="on">Tag photos</button>
   <button data-mode="colls">Collections</button>
   <button data-mode="dupes">Duplicates</button>
   <button data-mode="cull">Cull</button>
   <button data-mode="nbhd">Neighborhoods</button>
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
let cullFilter={shoot:'',city:'',coll:'',show:'all'}, cullCursor=0;
let BREAKS={}, HINTS={}, nbShoot='', nbDirty=false;
let NEEDUP=0, ROTPOLL=null; const ROTSEEN=new Set();   // rotation -> R2 debt tracking
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
  BREAKS=d.breaks||{}; HINTS=d.hints||{};
  NEEDUP=Object.values(PHOTOS).filter(p=>p.needs_upload).length;
  startRotPoll();   // a reload mid-rotation should still pick up the finished pixels
  document.querySelectorAll('#modeseg button').forEach(b=>b.onclick=()=>{
    mode=b.dataset.mode; page=0; memberSlug=null;
    location.hash=mode;
    document.querySelectorAll('#modeseg button').forEach(x=>x.classList.toggle('on',x===b));
    render();
  });
  // The mode lives in the URL hash so a view is bookmarkable and survives reload
  // (#tag #colls #dupes #cull #nbhd).
  const want=(location.hash||'').replace('#','');
  if(want && [...document.querySelectorAll('#modeseg button')].some(b=>b.dataset.mode===want)){
    mode=want;
    document.querySelectorAll('#modeseg button').forEach(x=>x.classList.toggle('on',x.dataset.mode===want));
  }
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
/* ======================= ROTATION =======================
   `rotate` is a manifest field (clockwise degrees) re-applied on every derive —
   the source JPEG is never modified, so this is reversible and shows in a diff.
   The catch it must never hide: the rebuilt derivative keeps its filename, so the
   R2 object key is unchanged and the LIVE SITE keeps serving the old pixels until
   the file is re-uploaded and Cloudflare's edge cache is purged. That debt is what
   the amber banner counts.                                                     */
const cellsFor=key=>[...document.querySelectorAll(`[data-key="${CSS.escape(key)}"]`)];
// A re-oriented derivative keeps its FILENAME, so a plain /img/<path> would be
// served from the browser cache showing the old orientation — which looked like
// "the rotation didn't take" until you hard-refreshed. `derived_at` is persisted
// on the record, so the buster survives a reload and a re-render too.
const imgu=(p)=>'/img/'+p.thumb+(p.derived_at?('?v='+p.derived_at):'');
function rotBtns(key){
  const b=(t,fn)=>`<button title="${t}" onclick="event.stopPropagation();${fn}">`;
  return `<span class="rot">`+
    b('Rotate 90° counter-clockwise',`rotatePhoto('${jesc(key)}',-90)`)+`↺</button>`+
    b('Rotate 90° clockwise',`rotatePhoto('${jesc(key)}',90)`)+`↻</button>`+
    b('Flip left ⇄ right',`flipPhoto('${jesc(key)}','h')`)+`⇋</button>`+
    b('Flip top ⇅ bottom',`flipPhoto('${jesc(key)}','v')`)+`⇵</button></span>`;
}
// Click as many times as you like — each click is ~0.3s (the server re-orients the
// existing thumbnail) and the full-quality rebuild coalesces server-side, so four
// fast clicks cost one or two derives rather than four. Nothing blocks.
window.rotatePhoto=(key,delta)=>reorient(key,{delta});
window.flipPhoto=(key,axis)=>reorient(key,{flip:axis});
async function reorient(key,body){
  const els=cellsFor(key);
  els.forEach(e=>{e.classList.add('rotating');e.classList.remove('roterr');});
  let r,res;
  try{
    r=await fetch('/api/rotate',{method:'POST',headers:{'content-type':'application/json'},
      body:JSON.stringify(Object.assign({key},body))});
    res=await r.json();
  }catch(e){ els.forEach(x=>x.classList.remove('rotating')); alert('Failed: '+e); return; }
  if(!r.ok){els.forEach(x=>x.classList.remove('rotating'));alert('Failed: '+(res.error||r.status));return;}
  const p=PHOTOS[key];
  p.rotate=res.rotate; p.flip=res.flip; p.width=res.width; p.height=res.height;
  p.derived_at=res.derived_at;
  // The thumbnail on disk is ALREADY correct, so show it now rather than waiting
  // on the 9s full-quality pass.
  els.forEach(e=>{const img=e.querySelector('img');
    if(img){img.src=imgu(p); img.style.aspectRatio=`${p.width||3}/${p.height||2}`;}});
  ROTSEEN.delete(key); startRotPoll();
}
function startRotPoll(){
  if(ROTPOLL)return;
  ROTPOLL=setInterval(async()=>{
    let st; try{ st=await (await fetch('/api/rotate/status')).json(); }catch(e){ return; }
    let pending=0;
    Object.entries(st.state||{}).forEach(([k,v])=>{
      if(v==='pending'){pending++;return;}
      if(ROTSEEN.has(k))return;         // terminal states persist server-side; apply once
      ROTSEEN.add(k);
      const p=PHOTOS[k]; if(!p)return;
      cellsFor(k).forEach(e=>{
        e.classList.remove('rotating');
        if(v!=='done'){e.classList.add('roterr');e.title=v;return;}
        const img=e.querySelector('img');
        // Swap the quick thumbnail for the one rebuilt from source. Same filename,
        // new bytes — the version stamp is what defeats the cache.
        if(img){p.derived_at=Math.floor(Date.now()/1000);
                img.src=imgu(p);
                img.style.aspectRatio=`${p.width||3}/${p.height||2}`;}
      });
      if(v==='done'&&!p.needs_upload){p.needs_upload=true;NEEDUP++;paintBanner();}
    });
    if(!pending){clearInterval(ROTPOLL);ROTPOLL=null;}
  },1200);
}
function upBanner(){return `<div id="upb"${NEEDUP?' class="upbanner"':''}>${NEEDUP?upText():''}</div>`;}
function upText(){
  return `<b>${NEEDUP} photo${NEEDUP===1?'':'s'} rotated locally but not yet on R2</b> — `+
    `the live site still shows the old orientation. To publish:<br>`+
    `<code>python3 scripts/photos/pipeline.py upload-pending --out /tmp/pending.txt</code> · `+
    `<code>scripts/photos/upload_targeted.sh /tmp/pending.txt</code><br>`+
    `then purge those URLs in Cloudflare (same key, new bytes — the edge serves stale until TTL), `+
    `then <code>pipeline.py upload-pending --clear</code>.`;
}
function paintBanner(){const el=$('#upb'); if(!el)return;
  el.className=NEEDUP?'upbanner':''; el.innerHTML=NEEDUP?upText():'';}

function cellMenu(key){
  return `<button class="cmbtn" title="More…" onclick="event.stopPropagation();toggleMenu('${jesc(key)}')">⋯</button>
    <div class="cmenu" id="menu-${cssid(key)}" style="display:none" onclick="event.stopPropagation()">
      <select onchange="addToColl('${jesc(key)}',this.value);this.value=''"><option value="">+ Add to collection…</option>`+
      COLLS.slice().sort((a,b)=>a.title.localeCompare(b.title)).map(c=>`<option value="${esc(c.slug)}">${esc(c.title)}</option>`).join('')+
      `</select>`+
      `<button onclick="rotatePhoto('${jesc(key)}',-90)">↺ Rotate left</button>`+
      `<button onclick="rotatePhoto('${jesc(key)}',90)">↻ Rotate right</button>`+
      `<button onclick="flipPhoto('${jesc(key)}','h')">⇋ Flip left/right</button>`+
      `<button onclick="flipPhoto('${jesc(key)}','v')">⇵ Flip top/bottom</button>`+
      `<button class="del" onclick="deletePhoto('${jesc(key)}')">🗑 Delete photo</button></div>`;
}
function repaint(key,dim,html){const row=document.querySelector(`.row[data-key="${CSS.escape(key)}"]`);
  if(row){const el=row.querySelector(`[data-dim="${dim}"]`);if(el)el.outerHTML=html;}}

function renderList(){
  const all=tagVisible(), pages=Math.max(1,Math.ceil(all.length/PER));
  if(page>=pages)page=pages-1;
  const slice=all.slice(page*PER,page*PER+PER);
  const rev=all.filter(k=>PHOTOS[k].reviewed).length;
  $('#stat').textContent=`${rev}/${all.length} reviewed`;
  $('#main').innerHTML=upBanner()+slice.map(key=>{
    const p=PHOTOS[key];
    const dims=TAX.map(d=>chipRow(key,d)).join('');
    return `<div class="row ${p.reviewed?'reviewed':''}" data-key="${esc(key)}">
      <div><span class="rotdot"></span><img class="thumb" loading="lazy" src="${imgu(p)}">
        <div class="imgmeta"><b>${esc(p.file)}</b> · ${esc(p.shoot)} · #${p.img_no}${p.camera?` · <span class="cam ${p.camera==='EOS 7D'?'cam-old':''}">${esc(p.camera)}</span>`:''}</div>
        ${p.tag_notes?`<div class="notes">“${esc(p.tag_notes)}”</div>`:''}
        <button class="del small" onclick="deletePhoto('${jesc(key)}')">🗑 Delete photo</button>
        ${rotBtns(key)}</div>
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
        ${g.verdict?`<span class="dverdict ${g.verdict==='near-identical'?'vd-dupe':'vd-distinct'}">${esc(g.verdict)}${g.verdict_note?' — '+esc(g.verdict_note):''}</span>`:''}
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
     <td>${c.collage?`<input class="order" type="number" min="0" placeholder="—" value="${c.collage_rank||''}" onchange="updateColl('${esc(c.slug)}',{collage_rank:+this.value||0})" title="Home-collage priority: 1 = most likely to appear, 2 next, and so on — weighted, still random. Blank/0 = unranked (all unranked share the tier below the last ranked).">`:''}</td>
     <td><button class="linkbtn" onclick="editMembers('${esc(c.slug)}')">Edit members →</button>
         <button class="linkbtn arch" title="Remove from the site (membership kept; restore anytime from the Archived list below)" onclick="archiveColl('${esc(c.slug)}')">Archive</button></td>
   </tr>
   <tr class="caprow${c.featured?' feat':''}"><td colspan="8"><div class="caplabel">Caption${c.featured?' — shown on the home page':''}</div><textarea class="caption" placeholder="Write a 2–10 sentence caption…" onchange="updateColl('${esc(c.slug)}',{caption:this.value})">${esc(c.caption||'')}</textarea></td></tr>`).join('');
  const archRows=archived.slice().sort((a,b)=>a.title.localeCompare(b.title))
   .map(c=>`<tr class="archrow">
     <td class="ct">${esc(c.title)}</td>
     <td class="ct">${esc(collPlacesStr(c))}</td>
     <td class="ct">${collCount(c.slug)}</td>
     <td class="ct" colspan="4">archived — not on the site; membership preserved</td>
     <td><button class="linkbtn" onclick="restoreColl('${esc(c.slug)}')">Restore</button></td>
   </tr>`).join('');
  const archBlock=archived.length?`<tr><td colspan="8" class="archhead">Archived (${archived.length})</td></tr>${archRows}`:'';
  const cities=uniq(Object.values(PHOTOS).map(p=>p.city));
  // Two special "sets" browsable in the same grid: the home Hero rotation and
  // the per-place cover photos.
  const roleRows=`
   <tr class="role-row"><td><b>★ Hero</b> <span class="ct">— home hero rotation</span></td><td class="ct">any</td><td class="ct">${targetCount('__hero')}</td><td class="ct">—</td><td class="ct">—</td><td class="ct">—</td><td class="ct">—</td><td><button class="linkbtn" onclick="editMembers('__hero')">Edit set →</button></td></tr>
   <tr class="role-row"><td><b>⚑ Place cover</b> <span class="ct">— one per place</span></td><td class="ct">per city</td><td class="ct">${targetCount('__cover')}</td><td class="ct">—</td><td class="ct">—</td><td class="ct">—</td><td class="ct">—</td><td><button class="linkbtn" onclick="editMembers('__cover')">Edit set →</button></td></tr>`;
  $('#main').innerHTML=`<p class="hint">Rename via the title. <b>Place</b> is editable — type one or several <b>comma-separated</b> locations (e.g. “Newark, Brooklyn”) to span multiple; the site’s Collections filter then lists it under each. Tick <b>Featured</b> + set <b>Order</b> (1,2,3…) to choose the home-page 5 and their sequence. Tick <b>Collage</b> to make a collection eligible for the home collage walls — then curate WHICH photos show with the ▦ toggle inside “Edit members”: ONLY flagged photos appear (12–18 tiles gap-perfectly; a handful renders as a short wall of big cells, possibly with some crop). <b>Home rank</b> skews which collections the three walls draw: 1 = most likely, 2 next, etc — weighted but still random; blank = unranked. “Edit members / set” opens the add/remove grid — that includes the two special sets at the top: ★ Hero and ⚑ Place cover.</p>
   <table class="ctable"><thead><tr><th>Title</th><th>Place(s)</th><th>Photos</th><th>Featured</th><th>Order</th><th>Collage</th><th>Home rank</th><th></th></tr></thead><tbody>${roleRows}${rows}${archBlock}</tbody></table>
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
        <span class="badge">${inn?'in':'add'}</span>${cb}${cellMenu(key)}<span class="rotdot"></span><img loading="lazy" src="${imgu(p)}">
        <div class="cap">${esc(p.city||'')} · #${p.img_no}</div></div>`;}).join('')+`</div>`+pager(page,pages,all.length);
  $('#m-all').onchange=e=>{memberFilter.all=e.target.checked;page=0;render();};
  $('#m-city').onchange=e=>{memberFilter.city=e.target.value;page=0;render();};
  wirePager();
}
window.backToColls=()=>{mode='colls';memberSlug=null;document.querySelectorAll('#modeseg button').forEach(x=>x.classList.toggle('on',x.dataset.mode==='colls'));render();};

/* ============================ CULL MODE ============================
   A two-step cull: MARK photos (reversible, no effect on the site), review the
   marked set, then delete them in one batch. `photo.cull` is the mark. Deleting
   goes through the same path as the single-photo delete — manifest, R2, local
   cache, and an append to deleted-photos.jsonl so a re-scan can't resurrect it.
   Keyboard: arrows/hjkl move, X or Space marks, Enter opens the photo big. */
function cullList(){
  let keys=Object.keys(PHOTOS);
  if(cullFilter.shoot)keys=keys.filter(k=>PHOTOS[k].shoot===cullFilter.shoot);
  if(cullFilter.city)keys=keys.filter(k=>(PHOTOS[k].city||'')===cullFilter.city);
  if(cullFilter.coll)keys=keys.filter(k=>(PHOTOS[k].collections||[]).includes(cullFilter.coll));
  if(cullFilter.show==='marked')keys=keys.filter(k=>PHOTOS[k].cull);
  if(cullFilter.show==='unmarked')keys=keys.filter(k=>!PHOTOS[k].cull);
  return keys.sort((a,b)=>(PHOTOS[a].shoot||'').localeCompare(PHOTOS[b].shoot||'')||(PHOTOS[a].img_no-PHOTOS[b].img_no));
}
function cullCount(){return Object.values(PHOTOS).filter(p=>p.cull).length;}
window.toggleCull=(key)=>{const p=PHOTOS[key];p.cull=!p.cull;save(key,{cull:!!p.cull});
  const cell=document.querySelector(`.cullcell[data-key="${CSS.escape(key)}"]`);
  if(cell)cell.classList.toggle('marked',!!p.cull);
  cullStat();
  const b=$('#cull-del');if(b){const n=cullCount();b.disabled=!n;b.textContent=`Delete ${n} marked photo${n===1?'':'s'}…`;}};
function cullStat(){const n=cullCount();$('#stat').textContent=`${n} marked for culling`;}
window.setCullCursor=(i)=>{const cells=[...document.querySelectorAll('.cullcell')];
  if(!cells.length)return; cullCursor=Math.max(0,Math.min(i,cells.length-1));
  cells.forEach((c,j)=>c.classList.toggle('cursor',j===cullCursor));
  cells[cullCursor].scrollIntoView({block:'nearest'});};
function renderCull(){
  const shoots=uniq(Object.values(PHOTOS).map(p=>p.shoot));
  const cities=uniq(Object.values(PHOTOS).map(p=>p.city));
  const colls=COLLS.slice().sort((a,b)=>a.title.localeCompare(b.title));
  const all=cullList(), pages=Math.max(1,Math.ceil(all.length/GRIDPER));
  if(page>=pages)page=pages-1;
  const slice=all.slice(page*GRIDPER,page*GRIDPER+GRIDPER);
  const n=cullCount();
  cullStat();
  $('#main').innerHTML=upBanner()+`
    <div class="cullnote">Click a photo to mark it for culling — the mark is just a mark, it changes nothing on the site
      and you can unmark freely. When you're happy with the set, switch <b>Show</b> to <b>marked only</b>, look it over,
      and hit <b>Delete</b>. That step is permanent: the photo leaves the manifest and R2 and is written to
      <code>deleted-photos.jsonl</code> so a re-scan can't bring it back.
      &nbsp;·&nbsp; Keys: <kbd>←</kbd><kbd>→</kbd><kbd>↑</kbd><kbd>↓</kbd> move &nbsp; <kbd>X</kbd>/<kbd>space</kbd> mark &nbsp; <kbd>Enter</kbd> open full size
      &nbsp; <kbd>[</kbd><kbd>]</kbd> rotate &nbsp; <kbd>f</kbd> flip ⇋ &nbsp; <kbd>F</kbd> flip ⇵
      <br>Hover a photo for <b>↺ ↻ ⇋ ⇵</b>. Click as many times as you need — each one lands in about a third of a
      second and you never have to wait between them; the blue dot just means the full-size version is still
      rebuilding. It never touches your source file, so any of it can be undone.</div>
    <div class="cullbar">
      <select id="c-shoot"><option value="">All shoots</option>${shoots.map(x=>`<option value="${esc(x)}"${x===cullFilter.shoot?' selected':''}>${esc(x)}</option>`).join('')}</select>
      <select id="c-city"><option value="">All cities</option>${cities.map(x=>`<option value="${esc(x)}"${x===cullFilter.city?' selected':''}>${esc(x)}</option>`).join('')}</select>
      <select id="c-coll"><option value="">Any collection</option>${colls.map(c=>`<option value="${esc(c.slug)}"${c.slug===cullFilter.coll?' selected':''}>${esc(c.title)}</option>`).join('')}</select>
      <select id="c-show">
        <option value="all"${cullFilter.show==='all'?' selected':''}>Show: all</option>
        <option value="unmarked"${cullFilter.show==='unmarked'?' selected':''}>Show: unmarked only</option>
        <option value="marked"${cullFilter.show==='marked'?' selected':''}>Show: marked only</option>
      </select>
      <span class="spacer" style="flex:1"></span>
      <button class="keepall" onclick="clearCullMarks()" ${n?'':'disabled'}>Unmark all ${n?`(${n})`:''}</button>
      <button class="danger" id="cull-del" onclick="deleteCulled()" ${n?'':'disabled'}>Delete ${n} marked photo${n===1?'':'s'}…</button>
    </div>
    <div class="cullgrid">`+slice.map((key,i)=>{const p=PHOTOS[key];
      return `<div class="cullcell${p.cull?' marked':''}" data-key="${esc(key)}" onclick="toggleCull('${jesc(key)}')">
        <span class="xmark">✕</span><span class="rotdot"></span>
        <img loading="lazy" src="${imgu(p)}" style="aspect-ratio:${(p.width||3)}/${(p.height||2)}">
        ${rotBtns(key)}
        <div class="cap">${esc(p.city||'—')} · ${esc(p.neighborhood||'')} #${p.img_no}</div></div>`;}).join('')
    +`</div>`+pager(page,pages,all.length);
  $('#c-shoot').onchange=e=>{cullFilter.shoot=e.target.value;page=0;render();};
  $('#c-city').onchange=e=>{cullFilter.city=e.target.value;page=0;render();};
  $('#c-coll').onchange=e=>{cullFilter.coll=e.target.value;page=0;render();};
  $('#c-show').onchange=e=>{cullFilter.show=e.target.value;page=0;render();};
  wirePager(); setCullCursor(0);
}
window.clearCullMarks=async()=>{const keys=Object.keys(PHOTOS).filter(k=>PHOTOS[k].cull);
  if(!keys.length)return;
  if(!confirm(`Unmark all ${keys.length} photos? (Nothing is deleted — this just clears the marks.)`))return;
  keys.forEach(k=>PHOTOS[k].cull=false);
  await Promise.all(keys.map(k=>fetch('/api/save',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({key:k,patch:{cull:false}})})));
  render();};
window.deleteCulled=async()=>{
  const keys=Object.keys(PHOTOS).filter(k=>PHOTOS[k].cull);
  if(!keys.length)return;
  const byCity={};keys.forEach(k=>{const c=PHOTOS[k].city||'(no city)';byCity[c]=(byCity[c]||0)+1;});
  const breakdown=Object.entries(byCity).sort((a,b)=>b[1]-a[1]).map(([c,n])=>`  ${c}: ${n}`).join('\n');
  if(!confirm(`Permanently delete ${keys.length} photos?\n\n${breakdown}\n\nThis removes them from the manifest and R2 and logs them to deleted-photos.jsonl. It cannot be undone from here.`))return;
  if(!confirm(`Last check — really delete ${keys.length} photos?`))return;
  const r=await fetch('/api/cull/delete',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({keys})});
  const res=await r.json();
  if(!r.ok){alert('Delete failed: '+(res.error||r.status));return;}
  res.deleted.forEach(k=>{delete PHOTOS[k];});
  alert(`Deleted ${res.deleted.length} photos.${res.missing.length?` (${res.missing.length} were already gone.)`:''}`);
  page=0;render();};

/* ======================= NEIGHBOURHOODS MODE =======================
   Photos are shot in walking order, so a contiguous run of IMG numbers is a
   contiguous piece of ground. Rather than label 4,000 photos one by one, you
   walk a shoot in order and drop a breakpoint where the ground changes: "from
   here on, Allentown". Each breakpoint owns every frame until the next one.

   Vision HINTS are shown as dashed amber bands with the evidence that produced
   them (a landmark, a street sign). They are suggestions only — one click turns
   a hint into a real breakpoint, and ignoring them costs nothing. Nothing is
   written to a photo until you press Apply.                                  */
const NBPER=150;
function nbBreaks(){return (BREAKS[nbShoot]||[]).slice().sort((a,b)=>a.from_img-b.from_img);}
function nbHints(){return (HINTS[nbShoot]||[]).slice().sort((a,b)=>a.from_img-b.from_img);}
function nbKeys(){return Object.keys(PHOTOS).filter(k=>PHOTOS[k].shoot===nbShoot)
  .sort((a,b)=>(PHOTOS[a].img_no||0)-(PHOTOS[b].img_no||0));}
function nbKnownNames(){
  const fromPhotos=Object.values(PHOTOS).map(p=>p.neighborhood);
  const fromBreaks=Object.values(BREAKS).flat().map(b=>b.neighborhood);
  const fromHints=Object.values(HINTS).flat().map(h=>h.neighborhood);
  return uniq([...fromPhotos,...fromBreaks,...fromHints]);
}
function nbRunAt(img){let r=null;for(const b of nbBreaks()){if(img>=b.from_img)r=b;else break;}return r;}
function nbAt(img){const r=nbRunAt(img);return (r&&!r.end)?(r.neighborhood||null):null;}
function runLabel(b){
  if(b.end)return '— run ends —';
  // Show the run for what it actually sets. A town-level run reads as the town.
  const bits=[];
  if(b.neighborhood)bits.push(b.neighborhood);
  if(b.city)bits.push(b.city+(b.state?', '+b.state:''));
  return bits.join(' · ')||'(empty)';
}
async function nbSave(bps){
  BREAKS[nbShoot]=bps;
  await fetch('/api/neighborhood/breaks',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({shoot:nbShoot,breaks:bps})});
  nbDirty=true; flash();
}
/* Which levels a run sets is up to the run. A big city's districts get a
   neighborhood; a small town that has no districts just gets a city and leaves
   neighborhood empty — "Vicksburg" is a city, not a neighborhood of somewhere
   else, and putting it in the neighborhood field would render "Vicksburg,
   Mississippi Delta, MS" and deny it a place page. Blank fields are left alone,
   so a run can correct only the city without touching neighborhoods. */
let bpEditAt=null;
window.nbSetBreak=(img)=>{bpEditAt=(bpEditAt===img?null:img);render();
  const el=document.querySelector('.bpedit input'); if(el)el.focus();};
window.nbCancelEdit=()=>{bpEditAt=null;render();};
window.nbEndRun=async(img)=>{
  let bps=nbBreaks().filter(b=>b.from_img!==img);
  bps.push({from_img:img,end:true});
  bps.sort((a,b)=>a.from_img-b.from_img);
  bpEditAt=null; await nbSave(bps); render();
};
window.nbCommitBreak=async(img)=>{
  const g=id=>(document.getElementById(id)||{}).value||'';
  const city=g('bp-city').trim(), st=g('bp-state').trim().toUpperCase(), nb=g('bp-nbhd').trim();
  let bps=nbBreaks().filter(b=>b.from_img!==img);
  if(city||nb){
    const rec={from_img:img};
    if(city)rec.city=city;
    if(st)rec.state=st;
    if(nb)rec.neighborhood=nb;
    bps.push(rec);
  }
  bps.sort((a,b)=>a.from_img-b.from_img);
  bpEditAt=null; await nbSave(bps); render();
};
function bpEditor(img){
  const cur=nbBreaks().find(b=>b.from_img===img)||{};
  const keys=nbKeys(), here=keys.find(k=>PHOTOS[k].img_no===img);
  const p=here?PHOTOS[here]:{};
  const cities=uniq(Object.values(PHOTOS).map(x=>x.city));
  const hint=nbHints().find(h=>h.from_img===img);
  return `<div class="bpedit">
    ${hint?`<div class="hintline"><b>Suggested:</b> ${esc(hint.neighborhood)} — ${esc(hint.evidence||'')}</div>`:''}
    <label>City (leave blank to keep)
      <input id="bp-city" class="wide" list="dl-nbcity" value="${esc(cur.city||'')}" placeholder="${esc(p.city||'')}"></label>
    <label>State<input id="bp-state" class="narrow" value="${esc(cur.state||'')}" placeholder="${esc(p.state||'')}" maxlength="2"></label>
    <label>Neighborhood (blank = none)
      <input id="bp-nbhd" class="wide" list="dl-nbname" value="${esc(cur.neighborhood||(hint?hint.neighborhood:'')||'')}" placeholder="small towns: leave empty"></label>
    <button class="go" onclick="nbCommitBreak(${img})">Set run from IMG ${img}</button>
    <button class="cancel" onclick="nbEndRun(${img})" title="Everything from here has no run until the next breakpoint — use it where the shoot leaves the area">End run here</button>
    <button class="cancel" onclick="nbCancelEdit()">Cancel</button>
    ${(cur.city||cur.neighborhood)?`<button class="del" onclick="nbRemoveBreak(${img})">Remove</button>`:''}
    <datalist id="dl-nbcity">${cities.map(c=>`<option value="${esc(c)}">`).join('')}</datalist>
    <datalist id="dl-nbname">${nbKnownNames().map(c=>`<option value="${esc(c)}">`).join('')}</datalist>
  </div>`;
}
window.nbAcceptHint=async(i)=>{
  const h=nbHints()[i]; if(!h)return;
  const prev=nbBreaks().find(b=>b.from_img===h.from_img)||{};
  let bps=nbBreaks().filter(b=>b.from_img!==h.from_img);
  bps.push(Object.assign({},prev,{from_img:h.from_img,neighborhood:h.neighborhood}));
  bps.sort((a,b)=>a.from_img-b.from_img);
  await nbSave(bps); render();
};
window.nbRemoveBreak=async(img)=>{await nbSave(nbBreaks().filter(b=>b.from_img!==img));render();};
window.nbApply=async(overwrite)=>{
  const bps=nbBreaks();
  if(!bps.length){alert('No breakpoints set for this shoot yet.');return;}
  const keys=nbKeys(), covered=keys.filter(k=>nbAt(PHOTOS[k].img_no)!==null);
  const already=covered.filter(k=>PHOTOS[k].neighborhood);
  let msg=`Apply ${bps.length} run${bps.length===1?'':'s'} to ${covered.length} photos in this shoot?`;
  if(keys.length-covered.length)msg+=`\n\n${keys.length-covered.length} photos sit before the first breakpoint and stay untouched.`;
  if(already.length)msg+= overwrite
      ? `\n\n${already.length} already have a neighborhood and WILL BE OVERWRITTEN.`
      : `\n\n${already.length} already have a neighborhood and will be kept as they are.`;
  if(!confirm(msg))return;
  const r=await fetch('/api/neighborhood/apply',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({shoot:nbShoot,overwrite:!!overwrite})});
  const res=await r.json();
  if(!r.ok){alert('Apply failed: '+(res.error||r.status));return;}
  Object.entries(res.changed||{}).forEach(([k,v])=>{if(PHOTOS[k])PHOTOS[k].neighborhood=v;});
  nbDirty=false;
  alert(`Set the neighborhood on ${res.set} photos.${res.kept?` Kept ${res.kept} that already had one.`:''}`);
  render();
};
function renderNbhd(){
  const shoots=SHOOTS.slice();
  if(!nbShoot)nbShoot=shoots[0]||'';
  const keys=nbKeys(), bps=nbBreaks(), hints=nbHints();
  const pages=Math.max(1,Math.ceil(keys.length/NBPER));
  if(page>=pages)page=pages-1;
  const slice=keys.slice(page*NBPER,page*NBPER+NBPER);
  const done=keys.filter(k=>PHOTOS[k].neighborhood).length;
  const cityn=uniq(keys.map(k=>PHOTOS[k].city)).length;
  $('#stat').textContent=`${done}/${keys.length} have a neighborhood · ${cityn} cit${cityn===1?'y':'ies'} · ${bps.length} run${bps.length===1?'':'s'}`;
  const bpAt=new Map(bps.map(b=>[b.from_img,b]));
  const hintAt=new Map(); hints.forEach((h,i)=>hintAt.set(h.from_img,{h,i}));
  const cityOf=keys.length?(PHOTOS[keys[0]].city||''):'';

  let cells='', runShown=null;
  slice.forEach(key=>{
    const p=PHOTOS[key], img=p.img_no;
    const hb=hintAt.get(img);
    if(hb && !bpAt.has(img))
      cells+=`<div class="hintband">Suggested from IMG ${img}: <b>${esc(hb.h.neighborhood)}</b>
        — ${esc(hb.h.evidence||'')} <button onclick="nbAcceptHint(${hb.i})">Use this</button></div>`;
    const b=bpAt.get(img);
    if(b){ runShown=runLabel(b);
      cells+=`<div class="runband">From IMG ${img}: <b>${esc(runLabel(b))}</b>
        <button class="rm" onclick="nbRemoveBreak(${img})">remove</button></div>`;
    } else if(runShown===null){
      const cur=nbRunAt(img);
      if(cur&&!cur.end){runShown=runLabel(cur);
        cells+=`<div class="runband">…continuing: <b>${esc(runLabel(cur))}</b></div>`;}
    }
    if(bpEditAt===img)cells+=bpEditor(img);
    cells+=`<div class="nbcell${b?' isbreak':''}${hb&&!b?' hashint':''}" data-key="${esc(key)}">
      <span class="cut" title="Start a run here" onclick="nbSetBreak(${img})">${b?'▸':'✂'}</span>
      <img loading="lazy" src="/img/${p.thumb}">
      <div class="cap">#${img} · ${esc(p.neighborhood||p.city||'—')}</div></div>`;
  });

  $('#main').innerHTML=`
    <div class="cullnote">Walk the shoot in shooting order and drop a run (<b>✂</b>) wherever the ground changes.
      Each run owns every frame until the next, so a whole street — or a whole town — costs one click.
      A run can set the <b>city</b>, the <b>neighborhood</b>, or both: a big city's districts get a neighborhood,
      while a small town that has no districts just gets a city and leaves neighborhood empty.
      Blank fields are left alone, so you can correct a city without disturbing neighborhoods.
      Amber bands are <b>suggestions</b> with the evidence behind them — take them or ignore them.
      Nothing touches a photo until you press <b>Apply</b>, and values you already set are kept unless you say otherwise.</div>
    <div class="nbbar">
      <select id="nb-shoot">${shoots.map(x=>`<option value="${esc(x)}"${x===nbShoot?' selected':''}>${esc(x)}</option>`).join('')}</select>
      <span class="ct">${esc(cityOf)} · ${keys.length} photos</span>
      <span class="spacer" style="flex:1"></span>
      <button class="apply" onclick="nbApply(false)" ${bps.length?'':'disabled'}>Apply to unset photos</button>
      <button class="keepall" onclick="nbApply(true)" ${bps.length?'':'disabled'} title="Also replace neighborhoods that are already set">Apply, overwriting existing</button>
    </div>
    <div class="nbgrid">${cells}</div>`+pager(page,pages,keys.length);
  $('#nb-shoot').onchange=e=>{nbShoot=e.target.value;page=0;render();};
  wirePager();
}

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
    else if(mode==='cull')renderCull();
    else if(mode==='nbhd')renderNbhd();
    else renderMembers();}
}

/* Cull-mode keyboard: culling 4,000 photos by mouse alone is not realistic. */
document.addEventListener('keydown',e=>{
  if(mode!=='cull')return;
  if(/^(INPUT|SELECT|TEXTAREA)$/.test((e.target.tagName||'')))return;
  const cells=[...document.querySelectorAll('.cullcell')];
  if(!cells.length)return;
  // Cells are variable-width now, so a row isn't a fixed column count — group by
  // vertical position and step to the neighbour nearest the current x-centre.
  const box=c=>c.getBoundingClientRect();
  const rowOf=c=>Math.round(box(c).top);
  const rows=[...new Set(cells.map(rowOf))].sort((a,b)=>a-b);
  const vstep=(dir)=>{
    const cur=cells[cullCursor], r=rows.indexOf(rowOf(cur)), tgt=rows[r+dir];
    if(tgt===undefined)return cullCursor;
    const cx=box(cur).left+box(cur).width/2;
    let best=cullCursor, bd=Infinity;
    cells.forEach((c,j)=>{ if(rowOf(c)!==tgt)return;
      const d=Math.abs(box(c).left+box(c).width/2-cx);
      if(d<bd){bd=d;best=j;} });
    return best;
  };
  let i=cullCursor, handled=true;
  switch(e.key){
    case 'ArrowRight': case 'l': i++; break;
    case 'ArrowLeft':  case 'h': i--; break;
    case 'ArrowDown':  case 'j': i=vstep(1); break;
    case 'ArrowUp':    case 'k': i=vstep(-1); break;
    case 'x': case 'X': case ' ':
      toggleCull(cells[cullCursor].dataset.key); break;
    case 'Enter':
      window.open('/img/'+PHOTOS[cells[cullCursor].dataset.key].display_webp,'_blank'); break;
    case '[': rotatePhoto(cells[cullCursor].dataset.key,-90); break;
    case ']': rotatePhoto(cells[cullCursor].dataset.key,90); break;
    case 'f': flipPhoto(cells[cullCursor].dataset.key,'h'); break;
    case 'F': flipPhoto(cells[cullCursor].dataset.key,'v'); break;
    default: handled=false;
  }
  if(handled){e.preventDefault(); if(i!==cullCursor)setCullCursor(i);}
});
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
            breaks = load(BREAKS, {"shoots": {}})["shoots"]
            hints = load(HINTS, {"shoots": {}})["shoots"]
            return self._send(200, {"photos": m, "collections": colls, "taxonomy": tax,
                                    "shoots": shoots, "dupes": dupes,
                                    "breaks": breaks, "hints": hints})
        if path == "/api/rotate/status":
            # Cheap on purpose — polled every ~1.2s while a rotation is in flight.
            # Deliberately does NOT recount needs_upload: that would mean parsing
            # the 4.4MB manifest on every tick. The page tracks that count itself.
            with _rot_meta:
                return self._send(200, {"state": dict(_rot_state)})
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
        if path == "/api/rotate":
            # Permanently rotate a photo WITHOUT touching the source JPEG. The
            # manifest (rotate + w/h) updates synchronously so the grid can reflow
            # immediately; the pixels are rebuilt on the pool and the page polls
            # /api/rotate/status for the swap.
            key = data["key"]
            with _lock:
                m = load(MANIFEST, {})
                rec = m.get(key)
                if rec is None:
                    return self._send(404, {"error": "unknown key"})
                cur, curf = _orient_of(rec)
                axis = data.get("flip")
                to = data.get("to")
                if axis:
                    new, newf = cur, PIPE.toggle_flip(curf, axis)
                elif to is not None:
                    new, newf = PIPE.norm_rotate(to), curf
                else:
                    # On a mirrored photo a clockwise turn READS counter-clockwise
                    # (mirroring conjugates a rotation to its inverse), so the stored
                    # value moves the other way and the arrow keeps its promise.
                    d = int(data.get("delta") or 90)
                    new = PIPE.norm_rotate(cur - d if PIPE.is_mirrored(curf) else cur + d)
                    newf = curf
                rec["rotate"], rec["flip"] = new, newf
                shoot = _SHOOT_BY_SLUG.get(rec.get("shoot"))
                w = h = None
                if shoot:
                    w, h = PIPE.dims(PIPE.PHOTOS_ROOT / shoot["folder"] / rec["file"], new)
                if w and h:
                    rec["width"], rec["height"] = w, h
                elif (cur % 180) != (new % 180):
                    # Source unreadable — fall back to swapping what we already hold
                    # rather than leaving the aspect ratio lying about the photo.
                    rec["width"], rec["height"] = rec.get("height"), rec.get("width")
                # Re-orient the EXISTING thumbnail in place (~0.3s) so the grid is
                # right almost immediately. The background job then rebuilds all
                # three tiers from source and overwrites this one, so the extra
                # generation of WebP loss is only ever a few seconds old.
                thumb_rel = rec.get("thumb")
                if thumb_rel and (cur, curf) != (new, newf):
                    try:
                        PIPE.retransform_thumb(DERIV / thumb_rel, cur, curf, new, newf)
                    except Exception:
                        pass          # the full re-derive below is the real answer
                rec["reviewed"] = True
                rec["derived_at"] = int(time.time())
                save_manifest(m)
                out = {"ok": True, "rotate": new, "flip": newf,
                       "width": rec.get("width"), "height": rec.get("height"),
                       "derived_at": rec["derived_at"]}
            with _rot_meta:
                _rot_state[key] = "pending"
                fresh = key not in _rot_active      # one job per key; it re-loops
                if fresh:                           # if more clicks land mid-encode
                    _rot_active.add(key)
            if fresh:
                _ROT_POOL.submit(_rotate_job, key)
            return self._send(200, out)
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
        if path == "/api/cull/delete":
            # Batch delete for Cull mode. Same semantics as /api/delete but for
            # many keys under ONE manifest lock — deleting 400 photos as 400
            # separate read-modify-write cycles would be slow and would risk
            # interleaving with a concurrent tagger save.
            keys = data.get("keys") or []
            deleted, missing, tiers = [], [], []
            with _lock:
                m = load(MANIFEST, {})
                with open(DELETIONS, "a") as fh:
                    for key in keys:
                        rec = m.pop(key, None)
                        if rec is None:
                            missing.append(key)
                            continue
                        fh.write(json.dumps({
                            "key": key, "deleted_at": datetime.now(timezone.utc).isoformat(),
                            "city": rec.get("city"), "shoot": rec.get("shoot"),
                            "thumb": rec.get("thumb"), "tag_notes": rec.get("tag_notes"),
                            "culled": True,
                        }, ensure_ascii=False) + "\n")
                        deleted.append(key)
                        tiers += [rec.get(t) for t in ("thumb", "display_avif", "display_webp") if rec.get(t)]
                if deleted:
                    save_manifest(m)

            def _cleanup(paths):
                for rel in paths:
                    subprocess.run(["npx", "wrangler", "r2", "object", "delete",
                                    f"gautamiyer-photos/{rel}", "--remote"], capture_output=True)
                    try:
                        (DERIV / rel).unlink()
                    except FileNotFoundError:
                        pass
            if tiers:
                threading.Thread(target=_cleanup, args=(tiers,), daemon=True).start()
            return self._send(200, {"deleted": deleted, "missing": missing})
        if path == "/api/neighborhood/breaks":
            # Persist one shoot's breakpoint list. A breakpoint is
            # {"from_img": <img_no>, "neighborhood": "..."} and owns every photo
            # from that IMG number until the next breakpoint — photos shot in
            # walking order means contiguous IMG ranges are contiguous ground.
            shoot = data["shoot"]
            bps = sorted([b for b in data.get("breaks", [])
                           if b.get("neighborhood") or b.get("city") or b.get("end")],
                          key=lambda b: b["from_img"])
            with _lock:
                d = load(BREAKS, {"shoots": {}})
                if bps:
                    d["shoots"][shoot] = bps
                else:
                    d["shoots"].pop(shoot, None)
                atomic_write(BREAKS, d)
            return self._send(200, {"ok": True, "breaks": bps})
        if path == "/api/neighborhood/apply":
            # Write the shoot's breakpoint runs onto its photos. An existing
            # neighborhood is a human's answer and is kept unless overwrite is
            # explicitly asked for.
            shoot = data["shoot"]
            overwrite = bool(data.get("overwrite"))
            with _lock:
                d = load(BREAKS, {"shoots": {}})
                bps = sorted(d["shoots"].get(shoot, []), key=lambda b: b["from_img"])
                if not bps:
                    return self._send(400, {"error": "no breakpoints for this shoot"})
                m = load(MANIFEST, {})
                setn = kept = 0
                changed = {}
                for key, rec in m.items():
                    if rec.get("shoot") != shoot or rec.get("img_no") is None:
                        continue
                    run = None
                    for b in bps:
                        if rec["img_no"] >= b["from_img"]:
                            run = b
                        else:
                            break
                    if run is None:
                        continue            # before the first run: untouched
                    if run.get("end"):
                        # Past an explicit end marker. A run owns frames until the
                        # NEXT breakpoint, so without an end it runs off the end of
                        # the shoot and labels the next town with the last town's
                        # neighborhood. On overwrite the end marker also CLEARS a
                        # neighborhood in its region — that is the only way to undo
                        # an overrun. City is never cleared: a photo with no city is
                        # worse off than one with an imperfect city.
                        if overwrite and rec.get("neighborhood"):
                            rec["neighborhood"] = None
                            changed.setdefault(key, {})["neighborhood"] = None
                            setn += 1
                        continue
                    # A breakpoint carries whichever levels it was given. Small
                    # towns get a city and no neighborhood; a city district gets
                    # both. Only non-empty fields are written, so a run can
                    # correct the city without disturbing neighborhoods.
                    touched = False
                    for field in ("city", "state", "neighborhood"):
                        val = run.get(field)
                        if not val:
                            continue
                        if rec.get(field) and not overwrite:
                            continue
                        if rec.get(field) != val:
                            rec[field] = val
                            changed.setdefault(key, {})[field] = val
                            touched = True
                    if touched:
                        setn += 1
                    elif any(run.get(f) and rec.get(f) for f in ("city", "state", "neighborhood")):
                        kept += 1
                save_manifest(m)
            return self._send(200, {"set": setn, "kept": kept, "changed": changed})
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
                        for f in ("title", "featured", "order", "place", "places", "description", "caption", "collage", "collage_rank", "archived"):
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
