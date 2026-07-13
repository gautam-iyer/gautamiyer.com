#!/usr/bin/env python3
"""Near-duplicate detection over the photo library.

Computes perceptual hashes (dHash + aHash, 64-bit each) from the 1000px thumbs
in .photo-build/derivatives/ and clusters lookalikes into groups written to
data/duplicates.json, which the tagger's "Duplicates" mode renders for review.

Strategy (tuned for this library — sequential shooting bursts):
  - primary signal: dHash hamming distance <= DHASH_NEAR
  - corroboration: aHash hamming distance <= AHASH_NEAR (kills false positives
    on repeating textures like facades/grids)
  - candidate pairs are limited to (a) same shoot with |img_no| gap <= SEQ_GAP,
    or (b) any pair whose dHash distance <= DHASH_STRICT (cross-shoot re-edits)
  - union-find merges pairs into groups, sorted by shoot + img_no

Re-running refreshes detection but PRESERVES review state: groups whose exact
member sets were already dismissed (status "kept") stay dismissed.

Usage: python3 scripts/photos/dupes.py [--strict N] [--near N] [--gap N]
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "data" / "photos.json"
DERIV = REPO / ".photo-build" / "derivatives"
OUT = REPO / "data" / "duplicates.json"

DHASH_NEAR = 6      # <= bits differing on dHash for sequential candidates
AHASH_NEAR = 10     # corroboration threshold on aHash
DHASH_STRICT = 4    # cross-shoot pairs must be this close
SEQ_GAP = 8         # img_no window within a shoot


def hashes(path):
    """(dhash64, ahash64) from a thumb. PIL here lacks webp READ support on
    some installs — fall back to sips->png via a temp file if needed."""
    from PIL import Image
    try:
        im = Image.open(path)
        im.load()
    except Exception:
        import subprocess, tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as t:
            tmp = t.name
        subprocess.run(["sips", "-s", "format", "png", str(path), "--out", tmp],
                       capture_output=True, check=True)
        im = Image.open(tmp)
        im.load()
        Path(tmp).unlink(missing_ok=True)
    g = im.convert("L")
    # dHash: 9x8 horizontal gradient
    d = g.resize((9, 8), Image.LANCZOS)
    px = list(d.getdata())
    dh = 0
    for r in range(8):
        for c in range(8):
            dh = (dh << 1) | (1 if px[r * 9 + c] > px[r * 9 + c + 1] else 0)
    # aHash: 8x8 mean threshold
    a = g.resize((8, 8), Image.LANCZOS)
    ap = list(a.getdata())
    mean = sum(ap) / 64
    ah = 0
    for v in ap:
        ah = (ah << 1) | (1 if v > mean else 0)
    return dh, ah


def ham(a, b):
    return bin(a ^ b).count("1")


class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", type=int, default=DHASH_STRICT)
    ap.add_argument("--near", type=int, default=DHASH_NEAR)
    ap.add_argument("--gap", type=int, default=SEQ_GAP)
    args = ap.parse_args()

    m = json.loads(MANIFEST.read_text())
    recs = []
    missing = 0
    for key, r in m.items():
        if not r.get("thumb"):
            missing += 1
            continue
        p = DERIV / r["thumb"]
        if not p.exists():
            missing += 1
            continue
        recs.append((key, r, p))
    print(f"hashing {len(recs)} thumbs ({missing} skipped w/o local thumb)…")

    import concurrent.futures as cf
    H = {}
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(hashes, p): key for key, _, p in recs}
        done = 0
        for f in cf.as_completed(futs):
            H[futs[f]] = f.result()
            done += 1
            if done % 500 == 0:
                print(f"  {done}/{len(recs)}")

    # candidate pairs
    uf = UF()
    pairs = 0
    by_shoot = {}
    for key, r, _ in recs:
        by_shoot.setdefault(r["shoot"], []).append((r.get("img_no") or 0, key))
    # (a) sequential within shoot
    for shoot, lst in by_shoot.items():
        lst.sort()
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                if lst[j][0] - lst[i][0] > args.gap:
                    break
                k1, k2 = lst[i][1], lst[j][1]
                if ham(H[k1][0], H[k2][0]) <= args.near and ham(H[k1][1], H[k2][1]) <= AHASH_NEAR:
                    uf.union(k1, k2)
                    pairs += 1
    # (b) strict cross-shoot: bucket by dHash prefix to avoid O(n^2)
    buckets = {}
    for key, (dh, _) in H.items():
        buckets.setdefault(dh >> 44, []).append(key)  # top 20 bits
    for _, ks in buckets.items():
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                k1, k2 = ks[i], ks[j]
                if m[k1]["shoot"] == m[k2]["shoot"]:
                    continue
                if ham(H[k1][0], H[k2][0]) <= args.strict and ham(H[k1][1], H[k2][1]) <= AHASH_NEAR:
                    uf.union(k1, k2)
                    pairs += 1

    groups = {}
    for key in H:
        root = uf.find(key)
        groups.setdefault(root, set()).add(key)
    groups = [sorted(g, key=lambda k: (m[k]["shoot"], m[k].get("img_no") or 0))
              for g in groups.values() if len(g) > 1]
    groups.sort(key=lambda g: (m[g[0]]["shoot"], m[g[0]].get("img_no") or 0))

    # preserve prior review state for identical member sets
    prior = {}
    if OUT.exists():
        try:
            for g in json.loads(OUT.read_text())["groups"]:
                prior[tuple(sorted(g["keys"]))] = g.get("status", "open")
        except Exception:
            pass
    out = {"groups": [
        {"id": i + 1,
         "keys": g,
         "status": prior.get(tuple(sorted(g)), "open")}
        for i, g in enumerate(groups)
    ]}
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    open_n = sum(1 for g in out["groups"] if g["status"] == "open")
    print(f"{pairs} near-pairs -> {len(groups)} groups "
          f"({sum(len(g) for g in groups)} photos involved), {open_n} open")


if __name__ == "__main__":
    main()
