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


def _item(p):
    w, h = p.get("width"), p.get("height")
    ar = (float(w) / h) if (w and h and h > 0) else 1.5
    geo = [x for x in (p.get("neighborhood"), p.get("city"), p.get("state")) if x]
    return {
        "thumb": p.get("thumb"),
        "avif": p.get("display_avif"),
        "webp": p.get("display_webp"),
        "ar": round(ar, 4),
        "title": ", ".join(geo),
        "meta": p.get("tag_notes") or "",
    }


def main():
    photos = json.loads((DATA / "photos.json").read_text())
    recs = [p for p in photos.values() if p.get("thumb")]
    # stable order: by shoot then img_no (mirrors the manifest scan order)
    recs.sort(key=lambda p: (p.get("shoot") or "", p.get("img_no") or 0))

    collections, places, hero, covers = {}, {}, [], {}
    for p in recs:
        it = _item(p)
        for slug in (p.get("collections") or []):
            collections.setdefault(slug, []).append(it)
        city = p.get("city")
        if city:
            places.setdefault(city, []).append(it)
        if p.get("hero"):
            hero.append({"avif": it["avif"], "webp": it["webp"], "ar": it["ar"]})
        if p.get("place_cover") and city and city not in covers:
            covers[city] = it

    index = {"collections": collections, "places": places, "hero": hero, "covers": covers}
    (DATA / "index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")))
    print(f"index: {len(collections)} collections, {len(places)} places, "
          f"{len(hero)} hero, {len(covers)} covers -> data/index.json")


if __name__ == "__main__":
    main()
