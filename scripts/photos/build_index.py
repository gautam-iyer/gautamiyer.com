#!/usr/bin/env python3
"""Denormalize photo membership into data/index.json so Hugo templates read a
collection's / place's photos as an O(1) map lookup instead of scanning the
whole manifest once per collection and per place (the biggest build-time lever
as the manifest grows — see the scaling assessment).

Emits (paths RELATIVE — templates prepend photo_base, so this stays valid if
the base/domain changes):
  {
    "collections": { "<slug>": [ item, ... ], ... },   # membership order = img_no
    "places":      { "<city>": [ item, ... ], ... },
    "hero":        [ {avif, webp, ar}, ... ],           # photos flagged hero:true
    "covers":      { "<city>": item }                    # the place_cover per city
  }
  item = { thumb, avif, webp, ar, title, meta }  (matches partials/collitems.html)

Run at deploy time (scripts/deploy.sh) BEFORE hugo, and commit the result so the
index always reflects the current manifest (the tagger edits photos.json; deploy
regenerates the index).
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"


def _ar(p):
    w, h = p.get("width"), p.get("height")
    return round(float(w) / h, 4) if (w and h and h > 0) else 1.5


def _title(p):
    return ", ".join(x for x in (p.get("neighborhood"), p.get("city"), p.get("state")) if x)


def _coll_item(p):
    """Shape consumed by partials/collitems.html (meta = tag_notes)."""
    return {
        "thumb": p.get("thumb"),
        "avif": p.get("display_avif"),
        "webp": p.get("display_webp"),
        "ar": _ar(p),
        "title": _title(p),
        "meta": p.get("tag_notes") or "",
        "cam": p.get("camera") or "",
    }


def _place_item(p):
    """Shape consumed by layouts/places/single.html (meta = architecture · subject)."""
    meta = list(p.get("architecture") or []) + list(p.get("subject") or [])
    return {
        "thumb": p.get("thumb"),
        "avif": p.get("display_avif"),
        "webp": p.get("display_webp"),
        "cam": p.get("camera") or "",
        "ar": _ar(p),
        "title": _title(p),
        "meta": " · ".join(meta),
    }


def main():
    photos = json.loads((DATA / "photos.json").read_text())
    registry = json.loads((DATA / "collections.json").read_text())["collections"]
    # Quarantine gate: photos in a `withheld` collection never reach the site.
    # The manifest itself is the publish list (nothing filters on tagged/reviewed),
    # so this is the one place un-QA'd or flagged frames can be held back while
    # still living in the manifest and the tagger. Mirrors layouts/partials/withheld.html.
    withheld = {c["slug"] for c in registry if c.get("withheld")}
    # Match Hugo's `range hugo.Data.photos` order (a map ranged by SORTED KEY) so
    # the generated lists render in the same order the templates did when they
    # scanned the manifest directly.
    recs = [photos[k] for k in sorted(photos)
            if photos[k].get("thumb") and not (withheld & set(photos[k].get("collections") or []))]
    held = sum(1 for k in photos if withheld & set(photos[k].get("collections") or []))

    collections, places, hero, covers = {}, {}, [], {}
    for p in recs:
        ci = _coll_item(p)
        for slug in (p.get("collections") or []):
            collections.setdefault(slug, []).append(ci)
        city = p.get("city")
        if city:
            places.setdefault(city, []).append(_place_item(p))
            # cover: first photo of the city (needs real dims), place_cover wins
            if p.get("width") and (p.get("height") or 0) > 0:
                if city not in covers or p.get("place_cover"):
                    covers[city] = {"thumb": p.get("thumb"), "ar": _ar(p)}
        if p.get("hero"):
            hero.append({"avif": ci["avif"], "webp": ci["webp"], "ar": ci["ar"], "cam": ci["cam"]})

    # Collage pools: for every collection flagged collage-eligible in the
    # registry, EXACTLY the curated members (photo.collage) — no top-up. A
    # deliberately small curation (e.g. "Free": 4 kids-running close-ups) must
    # stay small; the collage solver's tiered fallbacks guarantee a layout at
    # any pool size, small ones just render fewer, larger cells (possibly with
    # some crop). A collection with NOTHING curated pools its whole membership.
    collage = {}
    for slug in (c["slug"] for c in registry if c.get("collage") and not c.get("archived")):
        members = [p for p in recs if slug in (p.get("collections") or [])]
        pool = [p for p in members if p.get("collage")] or members
        if pool:
            collage[slug] = [_coll_item(p) for p in pool]

    # Essay refs: stable slugs set in the tagger ("utica-1") that the essay
    # shortcode {{< photo ref="utica-1" >}} resolves. Built from `recs`, so the
    # withheld gate still applies — a ref pointing at a staged or QA-held photo
    # deliberately resolves to NOTHING rather than leaking it onto an essay page.
    refs, ref_dupes = {}, {}
    for p in recs:
        r = (p.get("essay_ref") or "").strip()
        if not r:
            continue
        if r in refs:
            ref_dupes.setdefault(r, 1)
            ref_dupes[r] += 1
            continue
        # No caption here on purpose: it would be tag_notes, and photo.html
        # documents at length why an essay caption must never fall back to
        # internal QA prose. Shipping the field invites exactly that wiring.
        refs[r] = {"thumb": p.get("thumb"), "avif": p.get("display_avif"),
                   "webp": p.get("display_webp"), "ar": _ar(p)}
    # Only warn about a ref that resolves NOWHERE. A ref carried by both a
    # withheld and a published photo resolves fine to the published one, and
    # announcing it as broken points at the wrong problem.
    held_refs = sorted({r for k in photos
                        for r in [(photos[k].get("essay_ref") or "").strip()]
                        if r and r not in refs
                        and withheld & set(photos[k].get("collections") or [])})

    index = {"collections": collections, "places": places, "hero": hero,
             "covers": covers, "collage": collage, "refs": refs}
    (DATA / "index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")))
    print(f"index: {len(collections)} collections, {len(places)} places, "
          f"{len(hero)} hero, {len(covers)} covers, {len(collage)} collage pools, "
          f"{len(refs)} essay refs, {held} withheld -> data/index.json")
    for r, n in sorted(ref_dupes.items()):
        print(f"  !! essay ref '{r}' is on {n} photos — one ref must mean one photo")
    if held_refs:
        print(f"  !! {len(held_refs)} essay ref(s) point at WITHHELD photos and will "
              f"render nothing: {', '.join(held_refs[:6])}")


if __name__ == "__main__":
    main()
