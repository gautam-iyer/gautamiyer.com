#!/usr/bin/env python3
"""Data integrity checks for gautamiyer.com.

Every check here exists because the thing it checks for actually went wrong in
production at least once. Run it before a deploy; CI runs it on every push.

    python3 scripts/validate.py          # errors fail, warnings print
    python3 scripts/validate.py --strict # warnings fail too

ERRORS are invariants that have caused a bad publish. WARNINGS are latent risks
(an arbitrary place cover, a city with no collection) that are Gautam's call,
not a build failure — they must not turn CI red for a judgement he hasn't made.
"""

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"

errors = []
warnings = []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def load(name, root=DATA):
    p = root / name
    if not p.exists():
        err(f"{name} is missing")
        return None
    try:
        return json.loads(p.read_text())
    except Exception as e:  # noqa: BLE001
        err(f"{name} is not valid JSON: {e}")
        return None


def unwrap(obj, key):
    """data files are sometimes {key: [...]} and sometimes a bare list."""
    if isinstance(obj, dict) and key in obj:
        return obj[key]
    return obj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="treat warnings as failures")
    args = ap.parse_args()

    photos = load("photos.json")
    collections = load("collections.json")
    taxonomy = load("taxonomy.json")
    places = load("places.json")
    if photos is None or collections is None:
        report(args)
        return

    recs = photos if isinstance(photos, list) else list(photos.values())
    keys = list(photos.keys()) if isinstance(photos, dict) else []
    cols = unwrap(collections, "collections")
    dims = unwrap(taxonomy, "dimensions") if taxonomy else []
    plist = unwrap(places, "places") if places else []

    by_slug = {c["slug"]: c for c in cols}
    withheld_slugs = {c["slug"] for c in cols if c.get("withheld")}
    published = [r for r in recs if not (withheld_slugs & set(r.get("collections") or []))]

    # ---- 1. the deny-list is authoritative -------------------------------
    # The dead-photo bug: 19 deleted frames were re-added by a scan and went
    # live. Skipping deny-listed keys on ADD never removes one already in.
    deny_path = REPO / "deleted-photos.jsonl"
    if not deny_path.exists():
        err("deleted-photos.jsonl is missing from the REPO ROOT (it must not live under data/)")
    elif keys:
        denied = set()
        for i, line in enumerate(deny_path.read_text().splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                denied.add(json.loads(line)["key"])
            except Exception:  # noqa: BLE001
                err(f"deleted-photos.jsonl line {i} is not valid JSON")
        back = denied & set(keys)
        if back:
            err(
                f"{len(back)} DELETED photo(s) are back in the manifest and would "
                f"publish: {sorted(back)[:5]}"
            )

    # data/ must stay Hugo-parseable: a stray .jsonl there kills the build.
    for stray in DATA.glob("*.jsonl"):
        err(f"{stray.name} is under data/ — Hugo parses everything there and will die on JSONL")

    # ---- 2. the withheld gate -------------------------------------------
    for slug in ("staging", "needs-review"):
        c = by_slug.get(slug)
        if c is None:
            warn(f"no '{slug}' collection in the registry (the publish gate relies on it)")
        elif not c.get("withheld"):
            err(f"collection '{slug}' is NOT marked withheld — its photos would publish")

    # ---- 3. collection membership resolves -------------------------------
    unknown = defaultdict(int)
    for r in recs:
        for slug in r.get("collections") or []:
            if slug not in by_slug:
                unknown[slug] += 1
    for slug, n in sorted(unknown.items()):
        err(f"{n} photo(s) reference collection '{slug}', which is not in the registry")

    # ---- 4. taxonomy conformance ----------------------------------------
    # Vision taggers emit "Facade" without the cedilla, plus out-of-vocab
    # styles like "Queen Anne". Both have reached the manifest before.
    for d in dims:
        allowed = set(d.get("values") or [])
        if not allowed:
            continue
        seen = Counter()
        for r in recs:
            v = r.get(d["key"])
            if v is None:
                continue
            for item in (v if isinstance(v, list) else [v]):
                if item not in allowed:
                    seen[item] += 1
        for bad, n in sorted(seen.items()):
            err(f"{n} photo(s) carry {d['key']}={bad!r}, which is not in taxonomy.json")

    # ---- 5. one place_cover per city ------------------------------------
    covers = defaultdict(list)
    for r in recs:
        if r.get("place_cover") and r.get("city"):
            covers[r["city"]].append(r.get("file"))
    for city, files in sorted(covers.items()):
        if len(files) > 1:
            err(f"{city} has {len(files)} place_cover flags (must be exactly one): {files}")

    # A city with no explicit cover falls back to "first photo in sort order",
    # which once put a private portrait on Buffalo's public tile. Warning, not
    # an error: picking covers is curation.
    pub_cities = Counter(r.get("city") for r in published if r.get("city"))
    nocover = [(c, n) for c, n in pub_cities.most_common() if c not in covers]
    if nocover:
        warn(
            f"{len(nocover)} city/cities have no explicit place_cover, so their tile is "
            f"sort-dependent: " + ", ".join(f"{c} ({n})" for c, n in nocover[:8])
            + (" …" if len(nocover) > 8 else "")
        )

    # ---- 6. essay refs ---------------------------------------------------
    refs = defaultdict(list)
    for r in recs:
        if r.get("essay_ref"):
            refs[r["essay_ref"]].append(r.get("file"))
    for ref, files in sorted(refs.items()):
        if len(files) > 1:
            err(f"essay_ref {ref!r} is used by {len(files)} photos: {files}")

    published_refs = {r["essay_ref"] for r in published if r.get("essay_ref")}
    shortcode = re.compile(r"{{<\s*photo\s+[^>]*ref=\"([^\"]+)\"")
    for md in (REPO / "content").rglob("*.md"):
        for ref in shortcode.findall(md.read_text()):
            if ref not in refs:
                err(f"{md.relative_to(REPO)} references photo ref {ref!r}, which no photo carries")
            elif ref not in published_refs:
                err(
                    f"{md.relative_to(REPO)} references {ref!r}, but that photo is "
                    f"withheld — it will render as a gap"
                )

    # ---- 7. geography ----------------------------------------------------
    known_cities = {p["city"] for p in plist if p.get("city")}
    missing = sorted({r.get("city") for r in published if r.get("city")} - known_cities)
    for city in missing:
        err(f"city {city!r} has published photos but no data/places.json entry (no state, no place page)")

    nocity = sum(1 for r in published if not r.get("city"))
    if nocity:
        warn(f"{nocity} published photo(s) have no city")

    for c in cols:
        for p in [c.get("place")] + list(c.get("places") or []):
            if p and p not in known_cities:
                warn(f"collection {c['slug']!r} names place {p!r}, which is not in places.json "
                     f"(the /collections place filter won't match it)")

    # ---- 8. index.json is in step with the manifest ----------------------
    # deploy.sh regenerates it before hugo, but a manual push can skip that and
    # ship a stale index — the templates read the index, not the manifest.
    idx_path = DATA / "index.json"
    if idx_path.exists():
        before = idx_path.read_text()
        try:
            subprocess.run(
                [sys.executable, "scripts/photos/build_index.py"],
                cwd=REPO, capture_output=True, check=True,
            )
            if idx_path.read_text() != before:
                err("data/index.json is STALE — rerun scripts/photos/build_index.py and commit it")
                idx_path.write_text(before)
        except subprocess.CalledProcessError as e:
            err(f"build_index.py failed: {e.stderr.decode()[:300]}")
    else:
        err("data/index.json is missing")

    # ---- 9. tier paths ---------------------------------------------------
    # A record with tier paths but no derivatives usually means DELETED.
    nothumb = [r.get("file") for r in published if not r.get("thumb")]
    if nothumb:
        warn(f"{len(nothumb)} published photo(s) have no thumb and will render broken: {nothumb[:5]}")

    pending = [r.get("file") for r in recs if r.get("needs_upload")]
    if pending:
        warn(
            f"{len(pending)} photo(s) have needs_upload set — local pixels changed but R2 still "
            f"has the old ones. Run: pipeline.py upload-pending"
        )

    report(args)


def report(args):
    for w in warnings:
        print(f"warn:  {w}")
    for e in errors:
        print(f"ERROR: {e}")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    if errors or (args.strict and warnings):
        sys.exit(1)
    print("data OK")


if __name__ == "__main__":
    main()
