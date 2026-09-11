#!/usr/bin/env python3
"""
Build a PORTABLE TAGGING PACKET: a zip holding small thumbnails plus one
self-contained HTML tagger that runs from file:// with no server, no Python
and no network. Tag on any machine (work laptop, tablet), hit "Download
changes", mail the little JSON back, and apply it with apply_packet.py.

  python3 scripts/photos/make_packet.py --shoot durham-2026-04-24
  python3 scripts/photos/make_packet.py --unreviewed --limit 600 --out lunch.zip
  python3 scripts/photos/make_packet.py --collection storefronts-of-durham

Size guide at the default 360px/q60 (~24 KB a photo):
  170 photos ≈ 4 MB · 600 ≈ 14 MB · 900 ≈ 21 MB · the whole library ≈ 97 MB.
Most mail servers cap attachments at 25 MB, so --limit 800 is a safe packet.
"""
import argparse, datetime, hashlib, json, os, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parent))
from packet_common import EDITABLE, MULTI, FLAGS, rev  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"
DERIV = REPO / ".photo-build" / "derivatives"
TEMPLATE = Path(__file__).resolve().parent / "packet_tagger.html"





def encode(args_tuple):
    src, dst, width, quality = args_tuple
    # PIL here has no webp read support, so go through sips for the decode.
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        png = tf.name
    try:
        r = subprocess.run(["sips", "-s", "format", "png", str(src), "--out", png],
                           capture_output=True)
        if r.returncode != 0:
            return f"sips failed: {src.name}"
        r = subprocess.run(["cwebp", "-quiet", "-q", str(quality),
                            "-resize", str(width), "0", png, "-o", str(dst)],
                           capture_output=True)
        if r.returncode != 0:
            return f"cwebp failed: {src.name}"
        return None
    finally:
        os.unlink(png)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shoot", help="only this shoot slug")
    ap.add_argument("--collection", help="only members of this collection slug")
    ap.add_argument("--city", help="only this city")
    ap.add_argument("--unreviewed", action="store_true", help="only reviewed:false records")
    ap.add_argument("--untagged", action="store_true", help="only tagged:false records")
    ap.add_argument("--limit", type=int, help="cap the number of photos")
    ap.add_argument("--width", type=int, default=360, help="thumbnail WIDTH in px (default 360); portrait frames end up taller")
    ap.add_argument("--quality", type=int, default=60, help="webp quality (default 60)")
    ap.add_argument("--out", default=None, help="output zip path")
    ap.add_argument("--manifest", default=None, help="manifest to read (default data/photos.json)")
    args = ap.parse_args()

    man_path = Path(args.manifest) if args.manifest else DATA / "photos.json"
    photos = json.loads(man_path.read_text())
    colls = json.loads((DATA / "collections.json").read_text())["collections"]
    tax = json.loads((DATA / "taxonomy.json").read_text())

    # ---- select
    sel = []
    for k, r in photos.items():
        if args.shoot and r.get("shoot") != args.shoot: continue
        if args.city and r.get("city") != args.city: continue
        if args.collection and args.collection not in (r.get("collections") or []): continue
        if args.unreviewed and r.get("reviewed"): continue
        if args.untagged and r.get("tagged"): continue
        if not r.get("thumb"): continue
        if not (DERIV / r["thumb"]).exists(): continue
        sel.append((k, r))
    sel.sort(key=lambda kr: (kr[1].get("shoot") or "", kr[1].get("img_no") or 0, kr[0]))
    if args.limit: sel = sel[:args.limit]
    if not sel:
        sys.exit("no photos matched those filters")

    label = args.shoot or args.collection or args.city or ("unreviewed" if args.unreviewed else "packet")
    out_zip = Path(args.out) if args.out else REPO / f"tagging-packet-{label}.zip"

    print(f"packet: {len(sel)} photos  ({args.width}px q{args.quality})")

    staging = Path(tempfile.mkdtemp(prefix="packet-"))
    imgdir = staging / "img"
    imgdir.mkdir(parents=True)

    # ---- re-encode small thumbs, named by an index so no filename can collide
    jobs, records = [], []
    for i, (k, r) in enumerate(sel):
        name = f"{i:05d}.webp"
        jobs.append((DERIV / r["thumb"], imgdir / name, args.width, args.quality))
        records.append({
            "key": k, "img": f"img/{name}", "file": r.get("file"),
            "shoot": r.get("shoot"), "img_no": r.get("img_no"),
            "camera": r.get("camera"), "date": r.get("date"),
            "w": r.get("width"), "h": r.get("height"),
            "reviewed": bool(r.get("reviewed")), "tagged": bool(r.get("tagged")),
            "rev": rev(r),
            **{f: r.get(f) for f in EDITABLE},
        })

    errs = []
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
        for n, e in enumerate(ex.map(encode, jobs), 1):
            if e: errs.append(e)
            if n % 100 == 0: print(f"  encoded {n}/{len(jobs)}")
    if errs:
        # Shipping a zip whose images are missing means tagging a photo you
        # cannot see. Refuse rather than hand over a quietly broken packet.
        print(f"  !! {len(errs)} encode failures:")
        for e in errs[:8]:
            print("   ", e)
        shutil.rmtree(staging, ignore_errors=True)
        sys.exit("aborted — no packet written")

    payload = {
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "label": label,
        "manifest_md5": hashlib.md5(man_path.read_bytes()).hexdigest(),
        "photos": records,
        "collections": [{k: c.get(k) for k in ("slug", "title", "withheld", "archived")} for c in colls],
        "taxonomy": tax["dimensions"],
    }

    html = TEMPLATE.read_text()
    html = html.replace("/*__PACKET_DATA__*/null", json.dumps(payload, ensure_ascii=False))
    (staging / "tagger.html").write_text(html)
    (staging / "README.txt").write_text(
        "PORTABLE TAGGER\n"
        "===============\n\n"
        "1. Unzip the whole folder somewhere (keep tagger.html next to the img/ folder).\n"
        "2. Double-click tagger.html. It opens in your browser and runs entirely offline —\n"
        "   nothing is uploaded and no install is needed.\n"
        "3. Tag away. Every change is saved in the browser automatically, so closing the\n"
        "   tab or sleeping the laptop will not lose your work.\n"
        "4. When you are done, click 'Download changes'. You get a small .json file.\n"
        "5. Mail that json back and it gets applied with:\n"
        "       python3 scripts/photos/apply_packet.py <the-file>.json\n\n"
        f"This packet: {len(records)} photos, label '{label}',\n"
        f"generated {payload['generated_at']}.\n"
    )

    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(staging.rglob("*")):
            if p.is_file(): z.write(p, p.relative_to(staging))
    shutil.rmtree(staging, ignore_errors=True)

    mb = out_zip.stat().st_size / 1048576
    print(f"\nwrote {out_zip}  ({mb:.1f} MB)")
    if mb > 24: print("  !! over ~24 MB — most mail servers will bounce it. Re-run with --limit or --width 300.")


if __name__ == "__main__":
    main()
