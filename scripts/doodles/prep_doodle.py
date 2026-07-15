#!/usr/bin/env python3
"""Turn a hand-drawn black-ink-on-white scan into a clean, tintable web asset.

Pipeline: grayscale -> levels stretch (paper->pure white, ink->black) ->
invert to an ALPHA channel (ink = opaque, paper = transparent) -> trim to the
ink bounding box (+ small pad) -> cap longest edge (retina-generous) ->
optimized PNG. RGB is filled flat black so the file also renders fine as a
plain <img>; but the intent is CSS `mask-image`, where only alpha matters, so
the ink can be tinted any palette color at use-site.

Usage:
    python3 scripts/doodles/prep_doodle.py "<src.png>" <out-slug> [--maxedge N]
    # writes assets/img/doodles/<out-slug>.png and prints WxH + aspect ratio
"""
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageOps

REPO = Path(__file__).resolve().parents[2]
OUTDIR = REPO / "assets" / "img" / "doodles"

# Levels: source gray >= WHITE_PT is paper (alpha 0); <= BLACK_PT is solid ink
# (alpha 255); linear ramp between preserves anti-aliased edges. Tuned for
# marker scans on off-white paper; widen WHITE_PT down if paper reads as haze.
WHITE_PT = 205
BLACK_PT = 110
PAD = 12  # transparent padding around the trimmed ink, in source px


def prep(src: Path, slug: str, maxedge: int) -> None:
    im = Image.open(src)
    if im.mode in ("RGBA", "LA"):
        # flatten any existing transparency onto white before thresholding
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    gray = ImageOps.grayscale(im)

    # levels stretch -> alpha (inverted: dark ink -> high alpha)
    def to_alpha(p):
        if p >= WHITE_PT:
            return 0
        if p <= BLACK_PT:
            return 255
        return round((WHITE_PT - p) / (WHITE_PT - BLACK_PT) * 255)

    alpha = gray.point(to_alpha)

    rgba = Image.new("RGBA", im.size, (17, 17, 17, 0))  # #111 flat
    rgba.putalpha(alpha)

    bbox = alpha.getbbox()
    if not bbox:
        sys.exit("no ink found — check thresholds")
    l, t, r, b = bbox
    l, t = max(0, l - PAD), max(0, t - PAD)
    r, b = min(im.width, r + PAD), min(im.height, b + PAD)
    rgba = rgba.crop((l, t, r, b))

    if max(rgba.size) > maxedge:
        s = maxedge / max(rgba.size)
        rgba = rgba.resize((round(rgba.width * s), round(rgba.height * s)), Image.LANCZOS)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    out = OUTDIR / f"{slug}.png"
    rgba.save(out, optimize=True)
    w, h = rgba.size
    kb = out.stat().st_size / 1024
    print(f"wrote {out.relative_to(REPO)}  {w}x{h}  aspect={w/h:.4f}  {kb:.0f}KB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("slug")
    ap.add_argument("--maxedge", type=int, default=1400)
    a = ap.parse_args()
    prep(Path(a.src).expanduser(), a.slug, a.maxedge)
