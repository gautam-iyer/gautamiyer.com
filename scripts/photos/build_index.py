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
    }


def _place_item(p):
    """Shape consumed by layouts/places/single.html (meta = architecture · subject)."""
    meta = list(p.get("architecture") or []) + list(p.get("subject") or [])
    return {
        "thumb": p.get("thumb"),
        "avif": p.get("display_avif"),
        "webp": p.get("display_webp"),
        "ar": _ar(p),
        "title": _title(p),
        "meta": " · ".join(meta),
    }


def main():
    photos = json.loads((DATA / "photos.json").read_text())
    # Match Hugo's `range hugo.Data.photos` order (a map ranged by SORTED KEY) so
    # the generated lists render in the same order the templates did when they
    # scanned the manifest directly.
    recs = [photos[k] for k in sorted(photos) if photos[k].get("thumb")]

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
            hero.append({"avif": ci["avif"], "webp": ci["webp"], "ar": ci["ar"]})

    index = {"collections": collections, "places": places, "hero": hero, "covers": covers}
    (DATA / "index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")))
    print(f"index: {len(collections)} collections, {len(places)} places, "
          f"{len(hero)} hero, {len(covers)} covers -> data/index.json")


if __name__ == "__main__":
    main()
