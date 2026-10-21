#!/usr/bin/env python3
"""Denormalize photo membership into data/index.json so Hugo templates read a
collection's / place's photos as an O(1) map lookup instead of scanning the
whole manifest once per collection and per place (the biggest build-time lever
as the manifest grows — see the scaling assessment).

Emits (paths RELATIVE — templates prepend photo_base, so this stays valid if
the base/domain changes):
  {
    "collections": { "<slug>": [ item, ... ], ... },   # in sequence (photo_order)
    "places":      { "<city>": [ item, ... ], ... },
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


def _coll_places(c):
    """A collection's places: `places` when set, else its single `place`."""
    return c.get("places") or ([c["place"]] if c.get("place") else [])


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

    # ONE VISIBLE COLLECTION PER PHOTO. `collections` is the photo's tag list
    # (move it around freely); it is SHOWN in exactly one of them: `shown_in`
    # when that is still a visible membership, else its first visible
    # membership in registry order. A photo shown nowhere stays in the manifest
    # and the tagger but appears in no collection, wall or collage. Mirrored in
    # scripts/validate.py and the tagger (displayColl) — keep the three agreed.
    visible = [c["slug"] for c in registry
               if not (c.get("hidden") or c.get("archived") or c.get("withheld"))]
    vis_rank = {s: i for i, s in enumerate(visible)}

    def shown_in(p):
        mem = [s for s in (p.get("collections") or []) if s in vis_rank]
        if not mem:
            return None
        pick = p.get("shown_in")
        return pick if pick in mem else min(mem, key=vis_rank.get)

    # Cities with at least one visible single-place collection: their place
    # page shows collection walls, so their fallback cover must be a shown photo.
    curated_cities = {_coll_places(c)[0] for c in registry
                      if c["slug"] in vis_rank and len(_coll_places(c)) == 1}

    # SEQUENCE. Every collection is shown in a fixed order: the registry's
    # `photo_order` (keys, set by dragging in the tagger's Places mode) first,
    # then any member not in it — old-camera (EOS 7D) frames after the rest,
    # then by key (shoot folder, IMG number). New members therefore land at the
    # end until he places them. Mirrored in the tagger's collSeq().
    big = 10 ** 6
    seq_pos = {c["slug"]: {k: i for i, k in enumerate(c.get("photo_order") or [])}
               for c in registry}

    def in_sequence(slug, ps):
        pos = seq_pos.get(slug, {})
        return sorted(ps, key=lambda p: (pos.get(p["key"], big),
                                         p.get("camera") == "EOS 7D", p["key"]))

    collections, places, covers = {}, {}, {}
    for p in recs:
        d = shown_in(p)
        # Hidden collections (home-hero) are not display collections, so they
        # keep listing every member exactly as before.
        for slug in (p.get("collections") or []):
            if slug == d or slug not in vis_rank:
                collections.setdefault(slug, []).append(p)
        city = p.get("city")
        if city:
            places.setdefault(city, []).append(_place_item(p))
            # cover: first photo of the city (needs real dims), place_cover wins.
            # In a curated city the FALLBACK only considers photos that are
            # actually shown (an unsorted frame renders nowhere else on the
            # site); an explicitly flagged cover is his choice and always wins.
            if (p.get("width") and (p.get("height") or 0) > 0
                    and (d or p.get("place_cover") or city not in curated_cities)):
                if city not in covers or p.get("place_cover"):
                    covers[city] = {"thumb": p.get("thumb"), "ar": _ar(p)}

    collections = {slug: [_coll_item(p) for p in in_sequence(slug, ps)]
                   for slug, ps in collections.items()}

    # Wall pools for EVERY visible collection (place pages draw one wall per
    # collection): every shown member, in sequence. ▦ (photo.collage) does NOT
    # narrow these — it is home-page curation, and narrowing place walls by it
    # left Coltsville showing 2 of 13 photos (its ▦ flags predate place walls).
    # Home collage pools: for every collection flagged collage-eligible in the
    # registry, EXACTLY the curated members (photo.collage) — no top-up. A
    # deliberately small curation (e.g. "Free": 4 kids-running close-ups) must
    # stay small; the collage solver's tiered fallbacks guarantee a layout at
    # any pool size, small ones just render fewer, larger cells (possibly with
    # some crop). A collection with NOTHING curated pools its whole membership.
    walls, collage = {}, {}
    eligible = {c["slug"] for c in registry if c.get("collage")}
    for slug in visible:
        members = in_sequence(slug, [p for p in recs if shown_in(p) == slug])
        if not members:
            continue
        walls[slug] = [_coll_item(p) for p in members]
        if slug in eligible:
            collage[slug] = [_coll_item(p) for p in
                             ([p for p in members if p.get("collage")] or members)]

    # Place pages: a city's SINGLE-place collections, in display order —
    # `place_order` (set per collection in the tagger), then home rank, then
    # registry order. Collections spanning several places (`places` with >1
    # entry) belong to no place page; they live on /collections/ under the
    # "Multiple" filter. A city with no entry here keeps its legacy album.
    place_colls = {}
    for c in registry:
        pls = _coll_places(c)
        if c["slug"] in walls and len(pls) == 1:
            place_colls.setdefault(pls[0], []).append(c)
    place_colls = {city: [c["slug"] for c in sorted(cs, key=lambda c: (
        c.get("place_order") or big, c.get("collage_rank") or big, vis_rank[c["slug"]]))]
        for city, cs in place_colls.items()}

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

    index = {"collections": collections, "places": places,
             "covers": covers, "collage": collage, "walls": walls,
             "place_colls": place_colls, "refs": refs}
    (DATA / "index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")))
    print(f"index: {len(collections)} collections, {len(places)} places, "
          f"{len(covers)} covers, {len(collage)} collage pools, "
          f"{len(walls)} walls, {len(place_colls)} curated places, "
          f"{len(refs)} essay refs, {held} withheld -> data/index.json")
    for r, n in sorted(ref_dupes.items()):
        print(f"  !! essay ref '{r}' is on {n} photos — one ref must mean one photo")
    if held_refs:
        print(f"  !! {len(held_refs)} essay ref(s) point at WITHHELD photos and will "
              f"render nothing: {', '.join(held_refs[:6])}")


if __name__ == "__main__":
    main()
