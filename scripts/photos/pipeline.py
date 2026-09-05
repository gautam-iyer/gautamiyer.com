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
import time
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
        "folder": "Buffalo '26/Drop 1",
        "slug": "buffalo-2026-drop1",
        "city": "Buffalo",
        "date": "2026-01-01",
        "title": "Buffalo",
    },
    {
        "folder": "Buffalo '26/Drop 2",
        "slug": "buffalo-2026-drop2",
        "city": "Buffalo",
        "date": "2026-01-01",
        "title": "Buffalo",
    },
    {
        "folder": "Buffalo '26/Film Drop 1",
        "slug": "buffalo-2026-film1",
        "city": "Buffalo",
        "date": "2026-01-01",
        "title": "Buffalo",
    },
    {
        "folder": "Buffalo '26/Film Drop 2",
        "slug": "buffalo-2026-film2",
        "city": "Buffalo",
        "date": "2026-01-01",
        "title": "Buffalo",
    },
    {
        "folder": "Buffalo '26/Film Drop 3",
        "slug": "buffalo-2026-film3",
        "city": "Buffalo",
        "date": "2026-01-01",
        "title": "Buffalo",
    },
    # NYC shoots (ingest the curated "Edited" subfolders; folder cities are
    # defaults — mixed-borough folders get fixed per-record during tagging).
    {
        "folder": "BK + Broad Channel Feb '26/Edited",
        "slug": "bk-broad-channel-2026",
        "city": "Brooklyn",
        "date": "2026-02-01",
        "title": "Brooklyn",
    },
    {
        "folder": "Flatbush 3:23:26/Edited",
        "slug": "flatbush-2026",
        "city": "Brooklyn",
        "date": "2026-03-23",
        "title": "Brooklyn",
    },
    {
        "folder": "Hells Kitchen + LES 3:31:26/Edited",
        "slug": "hells-kitchen-les-2026",
        "city": "New York",
        "date": "2026-03-31",
        "title": "New York",
    },
    {
        "folder": "Queens 3:9:26/Edited",
        "slug": "queens-2026",
        "city": "Queens",
        "date": "2026-03-09",
        "title": "Queens",
    },
    {
        "folder": "Rockaways 4:12:26/Edited",
        "slug": "rockaways-2026",
        "city": "Queens",
        "date": "2026-04-12",
        "title": "Queens",
    },
    {
        "folder": "SoBro + Riverside 4:18:26/Edited",
        "slug": "sobro-riverside-2026",
        "city": "Bronx",
        "date": "2026-04-18",
        "title": "Bronx",
    },
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
    {
        "folder": "Newark 5:14:26/Final JPEGs",
        "slug": "newark-2026-05-14",
        "city": "Newark",
        "date": "2026-05-14",
        "title": "Newark",
    },
    {
        "folder": "Durham 4:24:26/Edited",
        "slug": "durham-2026-04-24",
        "city": "Durham",
        "date": "2026-04-24",
        "title": "Durham",
    },
    {
        "folder": "South BK 4:6:26/Edited/JPEGs",
        "slug": "south-brooklyn-2026-04-06",
        "city": "Brooklyn",
        "date": "2026-04-06",
        "title": "South Brooklyn",
    },
    {
        "folder": "FiDi 4:20:26/Edited",
        "slug": "fidi-2026-04-20",
        "city": "New York",
        "date": "2026-04-20",
        "title": "FiDi",
    },
    # November '25 Road Trip — multi-city (Utica/Syracuse/Troy/+); city defaults
    # below are placeholders, vision tagging assigns the real city per record.
    {
        "folder": "November '25 Road Trip/Edited",
        "slug": "road-trip-2025-11",
        "city": "Utica",
        "date": "2025-11-17",
        "title": "November Road Trip",
    },
    {
        "folder": "November '25 Road Trip/Film/K200 - Utica",
        "slug": "road-trip-2025-11-film-k200-utica",
        "city": "Utica",
        "date": "2025-11-17",
        "title": "November Road Trip (Film)",
        "medium": "Film",
        "camera": None,
    },
    {
        "folder": "November '25 Road Trip/Film/K200 - ST",
        "slug": "road-trip-2025-11-film-k200-st",
        "city": "Utica",
        "date": "2025-11-18",
        "title": "November Road Trip (Film)",
        "medium": "Film",
        "camera": None,
    },
    {
        "folder": "November '25 Road Trip/Film/K400 - Utica + Cuse + ST",
        "slug": "road-trip-2025-11-film-k400-mixed",
        "city": "Utica",
        "date": "2025-11-19",
        "title": "November Road Trip (Film)",
        "medium": "Film",
        "camera": None,
    },
    {
        "folder": "November '25 Road Trip/Film/K400 - Troy",
        "slug": "road-trip-2025-11-film-k400-troy",
        "city": "Troy",
        "date": "2025-11-20",
        "title": "November Road Trip (Film)",
        "medium": "Film",
        "camera": None,
    },
    {
        "folder": "June '26 Film/Edited",
        "slug": "june-2026-film",
        "city": "New York",
        "date": "2026-06-01",
        "title": "June Film",
        "medium": "Film",
        "camera": None,
    },
    # Funky South — city defaults per Gautam's map; refined per record after
    # tagging (Drop 1 splits at IMG_0812; Drops 2/3 have Helena/Clarksdale/
    # Jackson/Baton Rouge carve-outs; Drop 4 last 2 are Baton Rouge).
    {
        "folder": "Funky South '26/Drop 1",
        "slug": "funky-south-2026-drop1",
        "city": "Memphis",
        "date": "2026-01-02",
        "title": "Funky South",
    },
    {
        "folder": "Funky South '26/Drop 2",
        "slug": "funky-south-2026-drop2",
        "city": "Lower Miss. Delta",
        "date": "2026-01-03",
        "title": "Funky South",
    },
    {
        "folder": "Funky South '26/Drop 3",
        "slug": "funky-south-2026-drop3",
        "city": "Lower Miss. Delta",
        "date": "2026-01-04",
        "title": "Funky South",
    },
    {
        "folder": "Funky South '26/Drop 4",
        "slug": "funky-south-2026-drop4",
        "city": "New Orleans",
        "date": "2026-01-05",
        "title": "Funky South",
    },
    {
        "folder": "Portugal Dec '25/Lisbon 1",
        "slug": "portugal-2025-12-lisbon1",
        "city": "Lisbon",
        "date": "2025-12-01",
        "title": "Lisbon",
    },
    {
        "folder": "Portugal Dec '25/Lisbon 2",
        "slug": "portugal-2025-12-lisbon2",
        "city": "Lisbon",
        "date": "2025-12-01",
        "title": "Lisbon",
    },
    {
        "folder": "Portugal Dec '25/Porto 1",
        "slug": "portugal-2025-12-porto1",
        "city": "Porto",
        "date": "2025-12-05",
        "title": "Porto",
    },
    {
        "folder": "Portugal Dec '25/Porto 2",
        "slug": "portugal-2025-12-porto2",
        "city": "Porto",
        "date": "2025-12-05",
        "title": "Porto",
    },
    {
        # Multi-city New England trip — city is resolved PER PHOTO at tagging
        # time, so the shoot default is left unset.
        "folder": "New England 8:23:26/Edited",
        "slug": "new-england-2026-08-23",
        "city": None,
        "date": "2026-08-23",
        "title": "New England",
    },
]

TAG_FIELDS = ["neighborhood", "land_use", "architecture", "subject", "medium", "tone", "tag_notes"]
# Dimensions stored as arrays (multi-select). Kept in sync with data/taxonomy.json.
MULTI_FIELDS = ["land_use", "architecture", "subject", "tone"]


# ---------- manifest io ----------

DENYLIST = REPO / "deleted-photos.jsonl"


def deleted_keys():
    """Keys the human has deleted. The deny-list is AUTHORITATIVE: a key in here
    must never be in the manifest, however it got there."""
    out = set()
    if DENYLIST.exists():
        for line in DENYLIST.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    out.add(json.loads(line)["key"])
                except Exception:
                    pass
    return out


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


def camera_of(path):
    """EXIF camera model, normalized ('Canon EOS R8' -> 'EOS R8').
    None for film scans / missing EXIF (film carries no camera model)."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            model = (im.getexif() or {}).get(0x0110)
        if not model:
            return None
        model = str(model).strip().rstrip("\x00").strip()
        if model.startswith("Canon "):
            model = model[len("Canon "):]
        return model or None
    except Exception:
        return None


def state_map():
    """city -> state from data/places.json (e.g. Pittsburgh -> PA)."""
    try:
        places = json.loads((REPO / "data" / "places.json").read_text())
        return {p["city"]: p.get("state") for p in places if p.get("city")}
    except Exception:
        return {}


# ---------- sips helpers ----------

ROTATIONS = (0, 90, 180, 270)      # clockwise degrees; the only legal `rotate` values
# PIL's ROTATE_* transposes are COUNTER-clockwise, so a clockwise quarter-turn is
# ROTATE_270 and vice versa. Getting this backwards is silent on a 180 — always
# eyeball a 90 against the source.
_PIL_ROTATE = {90: "ROTATE_270", 180: "ROTATE_180", 270: "ROTATE_90"}


def norm_flip(v):
    """Normalise a mirror spec to '', 'h', 'v' or 'hv'. Both mirrors together is
    the same picture as a 180 rotation — that is fine, they compose as a group."""
    v = str(v or "").lower()
    return ("h" if "h" in v else "") + ("v" if "v" in v else "")


def toggle_flip(cur, axis):
    """Add/remove one mirror axis, so the button is a toggle rather than a set."""
    cur, axis = norm_flip(cur), norm_flip(axis)
    return norm_flip("".join(c for c in "hv" if (c in cur) != (c in axis)))


def is_mirrored(flip):
    """True when an ODD number of mirrors is applied — the case where rotation
    reverses on screen, because mirroring conjugates a rotation to its inverse.
    Two mirrors ('hv') is a 180 turn and reads the right way round again."""
    return len(norm_flip(flip)) == 1


def _apply_ops(im, rotate, flip):
    """The canonical order: rotate, then mirror in the FINAL (rotated) frame —
    which is what 'flip horizontally' means to someone looking at the photo."""
    from PIL import Image
    rotate, flip = norm_rotate(rotate), norm_flip(flip)
    if rotate:
        im = im.transpose(getattr(Image, _PIL_ROTATE[rotate]))
    if "h" in flip:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    if "v" in flip:
        im = im.transpose(Image.FLIP_TOP_BOTTOM)
    return im


def _unapply_ops(im, rotate, flip):
    """Exact inverse of _apply_ops — undo in reverse order. Geometrically lossless
    (only the re-encode costs anything), which is what lets a thumbnail be
    re-transformed in place instead of rebuilt from a 6000px source."""
    from PIL import Image
    rotate, flip = norm_rotate(rotate), norm_flip(flip)
    if "v" in flip:
        im = im.transpose(Image.FLIP_TOP_BOTTOM)
    if "h" in flip:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    if rotate:
        im = im.transpose(getattr(Image, _PIL_ROTATE[(360 - rotate) % 360]))
    return im


def retransform_thumb(path, old_rotate, old_flip, new_rotate, new_flip):
    """Re-orient an EXISTING thumbnail in place: ~0.3s, against ~9s to rebuild
    from source. Used for immediate feedback in the tagger; the background job
    then re-derives all three tiers from source and overwrites this, so the extra
    generation of WebP loss lives for a few seconds only."""
    from PIL import Image
    with Image.open(path) as im:
        im.load()
        im = _unapply_ops(im, old_rotate, old_flip)
        im = _apply_ops(im, new_rotate, new_flip)
        im.save(path, "WEBP", quality=THUMB_WEBP_Q)


def norm_rotate(v):
    """Coerce anything to a legal clockwise rotation. Junk becomes 0 rather than
    raising — one bad value must never abort a derive of 4,000 photos."""
    try:
        v = int(v or 0) % 360
    except (TypeError, ValueError):
        return 0
    return v if v in ROTATIONS else 0


def dims(path, rotate=0):
    """ORIENTED pixel dims — honors the EXIF orientation flag so a portrait shot
    (landscape sensor + orientation 6/8) reports portrait, then applies the
    record's manual `rotate` on top. Reads size + the orientation tag WITHOUT
    decoding pixels (fast at scale). Falls back to sips.

    These are SOURCE dims, not derivative dims — the tiers are pure downscales,
    so the ASPECT RATIO is what the site consumes (build_index `_ar`, the Cull
    grid's inline aspect-ratio, the collage srcset width math)."""
    w = h = None
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size  # lazy — no full decode
            orient = (im.getexif() or {}).get(0x0112, 1)  # 0x0112 = Orientation
            if orient in (5, 6, 7, 8):
                w, h = h, w
    except Exception:
        out = subprocess.run(
            ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
            capture_output=True, text=True,
        ).stdout
        mw = re.search(r"pixelWidth:\s*(\d+)", out)
        mh = re.search(r"pixelHeight:\s*(\d+)", out)
        w, h = (int(mw.group(1)), int(mh.group(1))) if mw and mh else (None, None)
    if w and h and norm_rotate(rotate) in (90, 270):
        w, h = h, w
    return (w, h)


def resize_to(src, dst, longest_edge, rotate=0, flip=""):
    """High-quality downscale to longest_edge, HONORING EXIF orientation — bakes
    the rotation into the pixels (and strips the flag) so straight-from-camera
    verticals aren't stored sideways. `rotate` (clockwise degrees) is the manual
    correction applied ON TOP, for sources whose flag is wrong or absent — film
    scans carry no orientation tag at all. Never upscales. Falls back to sips."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    rotate, flip = norm_rotate(rotate), norm_flip(flip)
    try:
        from PIL import Image, ImageOps
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)            # apply orientation to pixels
            im = _apply_ops(im, rotate, flip)           # then the manual correction
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            im.thumbnail((longest_edge, longest_edge), Image.LANCZOS)  # downscale only
            im.save(dst, "PNG")
        return
    except Exception:
        subprocess.run(
            ["sips", "-s", "format", "png", "-Z", str(longest_edge),
             *(["-r", str(rotate)] if rotate else []),   # sips -r is clockwise too
             *(["-f", "horizontal"] if "h" in flip else []),
             *(["-f", "vertical"] if "v" in flip else []),
             str(src), "--out", str(dst)],
            capture_output=True, text=True, check=True,
        )


# ---------- commands ----------

def cmd_scan(args):
    m = load_manifest()
    added = 0
    # Deny-list: photos deleted via the tagger must not be re-added on a re-scan,
    # even though the source JPEG still exists.
    deleted = deleted_keys()
    # ...and any that DID get back in are removed now. Skipping on add was not
    # enough once: 19 photos deleted 2026-07-16 were resurrected by a scan while
    # the deny-list was moving from data/ to the repo root, and stayed in the
    # manifest until they published.
    resurrected = [k for k in m if k in deleted]
    for k in resurrected:
        del m[k]
    if resurrected:
        print(f"scan: removed {len(resurrected)} deny-listed records that were back "
              f"in the manifest ({resurrected[0]}{'...' if len(resurrected) > 1 else ''})")
    shoots = [s for s in SHOOTS if (not args.shoot or s["slug"] == args.shoot)]
    for shoot in shoots:
        folder = PHOTOS_ROOT / shoot["folder"]
        if not folder.exists():
            print(f"  ! missing shoot folder: {folder}", file=sys.stderr)
            continue
        jpgs = []
        for pat in ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG"):
            jpgs.extend(folder.glob(pat))
        states = state_map()
        for f in sorted(set(jpgs)):
            key = f"{shoot['folder']}/{f.name}"
            if key in m or key in deleted:
                continue
            w, h = dims(f)
            m[key] = {
                "key": key,
                "file": f.name,
                "shoot": shoot["slug"],
                "city": shoot["city"],
                "state": shoot.get("state", states.get(shoot["city"])),
                "date": shoot["date"],
                "img_no": img_number(f.name),
                "width": w,
                "height": h,
                "rotate": 0,        # manual clockwise correction, applied at derive
                "flip": "",         # '' | 'h' | 'v' | 'hv' — mirror, applied after rotate
                "camera": shoot["camera"] if "camera" in shoot else camera_of(f),
                # tag fields (filled by tag-apply / neighborhoods)
                "neighborhood": None,
                "land_use": [],
                "architecture": [],
                "subject": [],
                "medium": shoot.get("medium"),
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


def _derive_one(rec, shoot, force=False):
    """Generate the three tiers for one record. Returns (thumb, avif, webp, was_present)
    or None if skipped/missing. `force` regenerates even when the files already
    exist — REQUIRED after a `rotate` change, because the output filenames never
    change (which is also why the R2 objects then need replacing)."""
    src = PHOTOS_ROOT / shoot["folder"] / rec["file"]
    slug = name_slug(rec["file"])
    out_dir = DERIV / rec["shoot"]
    thumb = out_dir / f"{slug}.thumb.webp"
    d_avif = out_dir / f"{slug}.display.avif"
    d_webp = out_dir / f"{slug}.display.webp"
    if not force and thumb.exists() and d_avif.exists() and d_webp.exists():
        return (thumb, d_avif, d_webp, True)
    if not src.exists():
        print(f"  ! missing source: {src}", file=sys.stderr)
        return None
    # IMG numbers repeat across shoots, so the slug alone is NOT unique — two
    # threads would write the same temp PNG and swap each other's pixels. Only
    # reachable once --force re-encodes existing files, but it is silent, so
    # namespace the temps by shoot.
    t_thumb = TMP / f"{rec['shoot']}__{slug}.thumb.png"
    t_disp = TMP / f"{rec['shoot']}__{slug}.disp.png"
    rotate, flip = norm_rotate(rec.get("rotate")), norm_flip(rec.get("flip"))
    resize_to(src, t_thumb, THUMB_EDGE, rotate, flip)
    resize_to(src, t_disp, DISPLAY_EDGE, rotate, flip)
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
        futs = {ex.submit(_derive_one, rec, shoot_by_slug[rec["shoot"]],
                          bool(getattr(args, "force", False))): rec for rec in items}
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
    n = kept = 0
    for rec in m.values():
        if rec["shoot"] != shoot or rec["img_no"] is None:
            continue
        # Only an EXISTING neighborhood is protected — not `reviewed`. The tagger
        # sets reviewed on every save, so skipping reviewed records made this a
        # no-op on exactly the photos that had been curated most. A neighborhood
        # already on the record is a human's answer and still wins; pass
        # --overwrite to replace it.
        if rec.get("neighborhood") and not getattr(args, "overwrite", False):
            kept += 1
            continue
        for b in breaks:
            if rec["img_no"] <= b["upto"]:
                rec["neighborhood"] = b["neighborhood"]
                n += 1
                break
    save_manifest(m)
    print(f"neighborhoods: set on {n} records for {shoot}"
          + (f", kept {kept} already set (--overwrite to replace)" if kept else ""))


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
        # collections merge by UNION — never drop a membership the human (or a prior pass) set
        if tags.get("collections"):
            rec["collections"] = sorted(set(rec.get("collections") or []) | set(tags["collections"]))
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
    rotated = sum(1 for r in m.values() if norm_rotate(r.get("rotate")) or norm_flip(r.get("flip")))
    if rotated:
        print(f"reoriented:   {rotated}")
    # A rotation reuses the SAME R2 object key, so nothing about the URL says it
    # is stale — this flag is the only record that the live pixels are wrong.
    pend = [k for k, r in m.items() if r.get("needs_upload")]
    if pend:
        print(f"\n!! {len(pend)} photo{'s' if len(pend) != 1 else ''} re-derived locally but NOT "
              f"re-uploaded — the site still shows the old pixels.")
        print("   python3 scripts/photos/pipeline.py upload-pending --out /tmp/pending.txt")
        print("   scripts/photos/upload_targeted.sh /tmp/pending.txt")
        print("   then PURGE those URLs in Cloudflare (images.gautamiyer.com is edge-cached,")
        print("   and an overwrite at the same key serves stale until TTL), then:")
        print("   python3 scripts/photos/pipeline.py upload-pending --clear")
    # The manifest is the publish list, so a deleted photo sitting in it is
    # live on the site. Surface that loudly rather than waiting for a scan.
    back = sorted(k for k in m if k in deleted_keys())
    if back:
        print(f"\n!! {len(back)} DELETED photos are back in the manifest — they will publish.")
        for k in back[:10]:
            print(f"     {k}")
        if len(back) > 10:
            print(f"     ...and {len(back) - 10} more")
        print("   Run `pipeline.py scan` to remove them (the deny-list wins).")


def cmd_rotate(args):
    """Rotate photos permanently, WITHOUT touching the source library.

    Rotation is stored as data (`rotate`, clockwise degrees) and re-applied every
    time the photo is derived, so it is reversible, diffable, and survives a
    re-derive. The source JPEG in ~/Documents is never modified — that library is
    the one layer this pipeline treats as read-only."""
    m = load_manifest()
    shoot_by_slug = {s["slug"]: s for s in SHOOTS}
    TMP.mkdir(parents=True, exist_ok=True)
    unknown = [k for k in args.keys if k not in m]
    if unknown:
        print(f"  ! unknown key: {unknown[0]}", file=sys.stderr)
        return 1
    changed = 0
    for k in args.keys:
        rec = m[k]
        cur = norm_rotate(rec.get("rotate"))
        curf = norm_flip(rec.get("flip"))
        newf = toggle_flip(curf, args.flip) if args.flip else curf
        if args.to is not None:
            new = norm_rotate(args.to)
        elif args.flip:
            new = cur                       # a pure flip leaves the rotation alone
        else:
            # On a mirrored photo a clockwise turn READS counter-clockwise, so the
            # stored value moves the other way to keep --by matching what you see.
            new = norm_rotate(cur - args.by if is_mirrored(curf) else cur + args.by)
        shoot = shoot_by_slug[rec["shoot"]]
        rec["rotate"] = new
        rec["flip"] = newf
        w, h = dims(PHOTOS_ROOT / shoot["folder"] / rec["file"], new)
        if w and h:
            rec["width"], rec["height"] = w, h
        res = _derive_one(rec, shoot, force=True)
        if res is None:
            print(f"  ! could not derive {k}", file=sys.stderr)
            continue
        _set_local_paths(rec, *res[:3])
        rec["needs_upload"] = True      # local pixels changed; R2 still has the old ones
        rec["derived_at"] = int(time.time())   # cache-buster: same filename, new bytes
        changed += 1
        fl = f"  flip {curf or '-'} -> {newf or '-'}" if curf != newf else (f"  flip {newf}" if newf else "")
        print(f"{k}: {cur}\u00b0 -> {new}\u00b0{fl}  ({rec['width']}x{rec['height']})")
    if changed:
        save_manifest(m)
        print(f"\nrotate: {changed} re-derived locally. They are NOT live yet — "
              f"run `pipeline.py upload-pending` for the R2 step.")
    return 0


def cmd_upload_pending(args):
    """List (or clear) derivatives whose pixels changed but whose R2 objects have
    not been replaced. A rotation reuses the same object key, so the flag is the
    ONLY thing that knows the live bytes are stale."""
    m = load_manifest()
    pend = {k: r for k, r in m.items() if r.get("needs_upload")}
    if args.clear:
        for r in pend.values():
            r.pop("needs_upload", None)
        if pend:
            save_manifest(m)
        print(f"upload-pending: cleared the flag on {len(pend)} photo"
              f"{'s' if len(pend) != 1 else ''}")
        return 0
    paths = []
    for r in pend.values():
        paths += [r[t] for t in ("thumb", "display_avif", "display_webp") if r.get(t)]
    text = "".join(x + "\n" for x in paths)
    if not args.out:
        sys.stdout.write(text)
        return 0
    Path(args.out).write_text(text)
    print(f"upload-pending: {len(paths)} files ({len(pend)} photos) -> {args.out}")
    print(f"   scripts/photos/upload_targeted.sh {args.out}")
    print("   then PURGE those URLs in Cloudflare, then `upload-pending --clear`")
    return 0


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
    d.add_argument("--force", action="store_true",
                   help="re-encode even when the derivatives already exist")
    ro = sub.add_parser("rotate", help="permanently rotate photos (source file untouched)")
    ro.add_argument("keys", nargs="+", help="manifest keys, e.g. \"Buffalo '26/Drop 1/IMG_2124.jpg\"")
    rg = ro.add_mutually_exclusive_group()
    rg.add_argument("--by", type=int, default=90, help="clockwise degrees to ADD (default 90)")
    rg.add_argument("--to", type=int, default=None, help="absolute clockwise rotation (0/90/180/270)")
    rg.add_argument("--flip", choices=("h", "v"), default=None,
                    help="toggle a mirror instead of rotating (h = left/right, v = top/bottom)")
    up = sub.add_parser("upload-pending", help="derivatives changed locally but stale on R2")
    up.add_argument("--out", default=None, help="write the path list here (for upload_targeted.sh)")
    up.add_argument("--clear", action="store_true", help="clear the flag after a verified upload")
    n = sub.add_parser("neighborhoods")
    n.add_argument("map")
    n.add_argument("--overwrite", action="store_true",
                   help="replace neighborhoods that are already set (default: keep them)")
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
        "rotate": cmd_rotate,
        "upload-pending": cmd_upload_pending,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
