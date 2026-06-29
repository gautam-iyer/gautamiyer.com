#!/usr/bin/env python3
"""
gautamiyer.com photo pipeline.

Single brain for turning edited JPEGs into a web gallery:
  scan         discover new edited JPEGs, add stub records (city from folder, dims via sips)
  derive       generate thumbnail + display tiers (idempotent; skips existing outputs)
  neighborhoods apply neighborhood tags from an IMG-range map
  tag-apply    upsert vision tags from a JSON batch (never clobbers reviewed records)
  status       print coverage counts

Design invariants (see project memory):
  - Manifest keyed by RELATIVE PATH (shoot folder + filename), because IMG_#### repeats across shoots.
  - Idempotent / incremental: re-runs only touch NEW photos and never overwrite reviewed=true tags.
  - Originals (10-30MB) are never served or committed. Derivatives go to R2; manifest holds URLs.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PHOTOS_ROOT = Path.home() / "Documents" / "Key Personal Docs" / "Photos"
MANIFEST = REPO / "data" / "photos.json"
BUILD = REPO / ".photo-build"
DERIV = BUILD / "derivatives"          # <slug>/<name>.{webp,avif}
TMP = BUILD / "tmp"

# Image tiers
THUMB_EDGE = 1000       # grid thumbnail, longest edge px
DISPLAY_EDGE = 3500     # lightbox display, longest edge px
THUMB_WEBP_Q = 80
DISPLAY_WEBP_Q = 82
AVIF_ARGS = ["--min", "0", "--max", "28", "--speed", "6", "--jobs", "2"]

# Pilot shoots. Add entries here as more shoots get edited.
SHOOTS = [
    {
        "folder": "Pittsburgh 6:16:26/Edited",
        "slug": "pittsburgh-2026-06-16",
        "city": "Pittsburgh",
        "date": "2026-06-16",
        "title": "Pittsburgh",
    },
    {
        "folder": "Texas 6:14:26/Dump 1/Edited",
        "slug": "san-antonio-2026-06-14",
        "city": "San Antonio",
        "date": "2026-06-14",
        "title": "San Antonio",
    },
]

TAG_FIELDS = ["neighborhood", "land_use", "architecture", "subject", "medium", "tone", "tag_notes"]
# Dimensions stored as arrays (multi-select). Kept in sync with data/taxonomy.json.
MULTI_FIELDS = ["land_use", "architecture", "subject", "tone"]


# ---------- manifest io ----------

def load_manifest():
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {}


def save_manifest(m):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    # stable ordering by key for clean git diffs
    ordered = {k: m[k] for k in sorted(m.keys(), key=_sort_key)}
    MANIFEST.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n")


def _sort_key(key):
    # sort by shoot then by numeric IMG order
    nums = re.findall(r"\d+", key)
    return (key.rsplit("/", 1)[0], [int(n) for n in nums])


def name_slug(filename):
    """IMG_6430.jpg -> img_6430 ; IMG_6832-2.jpg -> img_6832-2"""
    stem = Path(filename).stem
    return stem.lower()


def img_number(filename):
    """Primary integer sequence number for range mapping. IMG_6832-2 -> 6832."""
    m = re.search(r"(\d+)", Path(filename).stem)
    return int(m.group(1)) if m else None


# ---------- sips helpers ----------

def dims(path):
    out = subprocess.run(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
        capture_output=True, text=True,
    ).stdout
    w = re.search(r"pixelWidth:\s*(\d+)", out)
    h = re.search(r"pixelHeight:\s*(\d+)", out)
    return (int(w.group(1)), int(h.group(1))) if w and h else (None, None)


def resize_to(src, dst, longest_edge):
    """High-quality downscale to longest_edge using sips. Never upscales (-Z caps the max dim)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["sips", "-s", "format", "png", "-Z", str(longest_edge), str(src), "--out", str(dst)],
        capture_output=True, text=True, check=True,
    )


# ---------- commands ----------

def cmd_scan(args):
    m = load_manifest()
    added = 0
    shoots = [s for s in SHOOTS if (not args.shoot or s["slug"] == args.shoot)]
    for shoot in shoots:
        folder = PHOTOS_ROOT / shoot["folder"]
        if not folder.exists():
            print(f"  ! missing shoot folder: {folder}", file=sys.stderr)
            continue
        for f in sorted(folder.glob("*.jpg")) + sorted(folder.glob("*.JPG")):
            key = f"{shoot['folder']}/{f.name}"
            if key in m:
                continue
            w, h = dims(f)
            m[key] = {
                "key": key,
                "file": f.name,
                "shoot": shoot["slug"],
                "city": shoot["city"],
                "date": shoot["date"],
                "img_no": img_number(f.name),
                "width": w,
                "height": h,
                # tag fields (filled by tag-apply / neighborhoods)
                "neighborhood": None,
                "land_use": [],
                "architecture": [],
                "subject": [],
                "medium": None,
                "tone": [],
                "tag_notes": None,
                "collections": [],
                # derivative urls (filled by derive + r2 upload)
                "thumb": None,
                "display_avif": None,
                "display_webp": None,
                # state flags
                "tagged": False,
                "reviewed": False,
            }
            added += 1
    save_manifest(m)
    print(f"scan: +{added} new, {len(m)} total")


def _derive_one(rec, shoot):
    """Generate the three tiers for one record. Returns (thumb, avif, webp) paths or None if skipped/missing."""
    src = PHOTOS_ROOT / shoot["folder"] / rec["file"]
    slug = name_slug(rec["file"])
    out_dir = DERIV / rec["shoot"]
    thumb = out_dir / f"{slug}.thumb.webp"
    d_avif = out_dir / f"{slug}.display.avif"
    d_webp = out_dir / f"{slug}.display.webp"
    if thumb.exists() and d_avif.exists() and d_webp.exists():
        return (thumb, d_avif, d_webp, True)
    if not src.exists():
        print(f"  ! missing source: {src}", file=sys.stderr)
        return None
    t_thumb = TMP / f"{slug}.thumb.png"
    t_disp = TMP / f"{slug}.disp.png"
    resize_to(src, t_thumb, THUMB_EDGE)
    resize_to(src, t_disp, DISPLAY_EDGE)
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cwebp", "-quiet", "-q", str(THUMB_WEBP_Q), str(t_thumb), "-o", str(thumb)], check=True)
    subprocess.run(["cwebp", "-quiet", "-q", str(DISPLAY_WEBP_Q), str(t_disp), "-o", str(d_webp)], check=True)
    subprocess.run(["avifenc", *AVIF_ARGS, str(t_disp), str(d_avif)], capture_output=True, check=True)
    t_thumb.unlink(missing_ok=True)
    t_disp.unlink(missing_ok=True)
    return (thumb, d_avif, d_webp, False)


def cmd_derive(args):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    m = load_manifest()
    shoot_by_slug = {s["slug"]: s for s in SHOOTS}
    TMP.mkdir(parents=True, exist_ok=True)
    items = list(m.values())
    if args.limit:
        items = items[: args.limit]
    workers = max(2, (os.cpu_count() or 4) - 2)
    done = skipped = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_derive_one, rec, shoot_by_slug[rec["shoot"]]): rec for rec in items}
        for fut in as_completed(futs):
            rec = futs[fut]
            res = fut.result()
            if res is None:
                continue
            thumb, d_avif, d_webp, was_present = res
            _set_local_paths(rec, thumb, d_avif, d_webp)
            if was_present:
                skipped += 1
            else:
                done += 1
            if (done + skipped) % 50 == 0:
                print(f"  processed {done + skipped}/{len(items)}...")
                save_manifest(m)
    save_manifest(m)
    print(f"derive: {done} generated, {skipped} already present ({workers} workers)")


def _set_local_paths(rec, thumb, d_avif, d_webp):
    # store paths RELATIVE TO THE DERIVATIVES ROOT (e.g. "pittsburgh-2026-06-16/img_6430.thumb.webp").
    # Templates prepend site param `photo_base` (a local path during dev, the R2 public URL in prod),
    # and R2 upload mirrors this same structure, so the manifest never needs rewriting.
    rec["thumb"] = str(thumb.relative_to(DERIV))
    rec["display_avif"] = str(d_avif.relative_to(DERIV))
    rec["display_webp"] = str(d_webp.relative_to(DERIV))


def cmd_neighborhoods(args):
    """
    Apply neighborhoods from a map file. Format (JSON): a list of breakpoints,
    each {"upto": <img_no>, "neighborhood": "..."}. A photo gets the FIRST
    breakpoint whose upto >= its img_no, scoped to the given shoot.
    """
    mapping = json.loads(Path(args.map).read_text())
    breaks = sorted(mapping["breakpoints"], key=lambda b: b["upto"])
    shoot = mapping["shoot"]
    m = load_manifest()
    n = 0
    for rec in m.values():
        if rec["shoot"] != shoot or rec["img_no"] is None:
            continue
        if rec["reviewed"]:
            continue
        for b in breaks:
            if rec["img_no"] <= b["upto"]:
                rec["neighborhood"] = b["neighborhood"]
                n += 1
                break
    save_manifest(m)
    print(f"neighborhoods: set on {n} records for {shoot}")


def cmd_tag_apply(args):
    """
    Upsert vision tags. Input JSON: {"<key>": {"land_use": ..., "architecture": ...,
    "subject": ..., "medium": ..., "tag_notes": ...}, ...}. Skips reviewed records.
    """
    batch = json.loads(Path(args.batch).read_text())
    m = load_manifest()
    applied = skipped = missing = 0
    for key, tags in batch.items():
        rec = m.get(key)
        if rec is None:
            missing += 1
            continue
        if rec["reviewed"]:
            skipped += 1
            continue
        for field in TAG_FIELDS:
            if field in tags and tags[field] is not None:
                val = tags[field]
                if field in MULTI_FIELDS and not isinstance(val, list):
                    val = [val]   # vision agents emit a single value; store as array
                rec[field] = val
        rec["tagged"] = True
        applied += 1
    save_manifest(m)
    print(f"tag-apply: {applied} applied, {skipped} reviewed-skipped, {missing} unknown-key")


def cmd_contact_sheet(args):
    """Write a scrollable HTML contact sheet (thumbnails labeled by IMG number) for neighborhood mapping."""
    m = load_manifest()
    recs = [r for r in m.values() if r["shoot"] == args.shoot and r["thumb"]]
    recs.sort(key=lambda r: (r["img_no"], r["file"]))
    cells = []
    for r in recs:
        abs_thumb = (DERIV / r["thumb"]).as_uri()
        hood = r.get("neighborhood") or ""
        cells.append(
            f'<figure><img loading="lazy" src="{abs_thumb}">'
            f'<figcaption>{r["img_no"]}{(" · " + hood) if hood else ""}</figcaption></figure>'
        )
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Contact sheet — {args.shoot}</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background:#111; color:#ccc; margin:0; padding:24px; }}
  h1 {{ font-size:15px; font-weight:600; letter-spacing:.04em; color:#fff; position:sticky; top:0;
        background:#111; padding:8px 0; margin:0 0 16px; z-index:1; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:10px; }}
  figure {{ margin:0; }}
  img {{ width:100%; aspect-ratio:2/3; object-fit:cover; display:block; background:#222; border-radius:3px; }}
  figcaption {{ font-size:12px; color:#9aa; padding:4px 2px; font-variant-numeric:tabular-nums; }}
</style></head><body>
<h1>{args.shoot} — {len(recs)} frames in capture order · note the IMG number where each neighborhood begins</h1>
<div class="grid">{''.join(cells)}</div>
</body></html>"""
    out = BUILD / f"contact-sheet-{args.shoot}.html"
    out.write_text(html)
    print(str(out))


def cmd_status(args):
    m = load_manifest()
    total = len(m)
    derived = sum(1 for r in m.values() if r["thumb"])
    tagged = sum(1 for r in m.values() if r["tagged"])
    hood = sum(1 for r in m.values() if r["neighborhood"])
    reviewed = sum(1 for r in m.values() if r["reviewed"])
    print(f"total:        {total}")
    print(f"derived:      {derived}")
    print(f"tagged:       {tagged}")
    print(f"neighborhood: {hood}")
    print(f"reviewed:     {reviewed}")


def cmd_prune(args):
    """Delete local DISPLAY tiers (.avif/.webp) whose objects are on R2, keeping thumbnails.
    Frees ~95% of local space; thumbs (~70KB) stay so the tagger works offline."""
    removed = freed = 0
    for f in DERIV.rglob("*.display.*"):
        freed += f.stat().st_size
        f.unlink()
        removed += 1
    print(f"prune: removed {removed} display files, freed {freed/1e6:.0f} MB (thumbnails kept)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--manifest", help="override manifest path (e.g. a staging file)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scan")
    sc.add_argument("--shoot", default=None)
    d = sub.add_parser("derive")
    d.add_argument("--limit", type=int, default=0)
    d.add_argument("--force", action="store_true")
    n = sub.add_parser("neighborhoods")
    n.add_argument("map")
    t = sub.add_parser("tag-apply")
    t.add_argument("batch")
    cs = sub.add_parser("contact-sheet")
    cs.add_argument("--shoot", default="pittsburgh-2026-06-16")
    sub.add_parser("prune")
    sub.add_parser("status")
    args = p.parse_args()
    if args.manifest:
        global MANIFEST
        MANIFEST = Path(args.manifest)
    {
        "scan": cmd_scan,
        "derive": cmd_derive,
        "neighborhoods": cmd_neighborhoods,
        "tag-apply": cmd_tag_apply,
        "contact-sheet": cmd_contact_sheet,
        "prune": cmd_prune,
        "status": cmd_status,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
