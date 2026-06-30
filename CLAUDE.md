# gautamiyer.com — build notes

Hugo static site (personal site + photography portfolio). Live at https://gautamiyer.com via **Cloudflare Pages** (auto-builds from GitHub `main` on push; build = `hugo --gc --minify`, `HUGO_VERSION=0.159.0`). Images on **Cloudflare R2** (bucket `gautamiyer-photos`, public base = `photo_base` in `hugo.toml`).

## Deploy
- `scripts/deploy.sh "commit message"` — preflight builds (aborts if the build errors, so broken templates never reach prod), then commits + pushes. Prefer this over manual push.
- CSS/JS are **fingerprinted** via Hugo's asset pipeline (`assets/css`, `assets/js` → `resources.Get | minify | fingerprint`). URLs are content-hashed, so deploys cache-bust automatically — **no hard-refresh needed**. Never link `/css` or `/js` directly; use the `asset-js.html` partial (JS) or the head block (CSS).

## Photo pipeline (`scripts/photos/`)
- `pipeline.py` — manifest brain, keyed by relative path, idempotent, never clobbers `reviewed:true`. Subcommands: `scan [--shoot]`, `derive`, `tag-apply`, `neighborhoods`, `contact-sheet`, `prune`, `status`; global `--manifest` for staging. Add a shoot to the `SHOOTS` list, then scan→derive→tag→neighborhoods→`r2_upload.sh`→deploy.
- `tagger.py` — local review/curation app (localhost:8800); autosaves to `data/photos.json` + `data/collections.json`, sets `reviewed:true`.
- Derivatives live in `.photo-build/` (gitignored); after R2 upload run `pipeline.py prune` (keeps thumbs).

## Data
- `data/photos.json` — per-photo manifest. Tag dims land_use/architecture/subject/tone are **arrays** (multi-select); neighborhood/city/medium single. Tier paths are relative to the derivatives root; templates prepend `photo_base`.
- `data/taxonomy.json` — **single source of truth** for tag dimensions/values (drives tagger + gallery filters). Edit here to add a category.
- `data/collections.json` — collection registry `{slug,title,place,featured,order,color,type,...}`. Membership is per-photo in `photos.json` (`collections:[]`).

## Templates / front-end
- `partials/collitems.html` — returns a collection's photos as lightbox-ready dicts; **always call via `partialCached … $slug`** (dedupes + speeds the build). Use it instead of re-scanning `hugo.Data.photos`.
- `partials/lbthumb.html` — a `[data-lb]` thumbnail; `static`/`assets/js/lightbox.js` wires ALL `[data-lb]` on a page into one overlay with prev/next (arrows/keys/swipe), skipping hidden items. Used on home, collection pages, and `/photos`.
- `/photos` = filterable gallery (`assets/js/photos.js`, filtering only — lightbox is the shared one). `/collections/<slug>/` pages are generated from the registry by the content adapter `content/collections/_content.gotmpl`. `/places/<slug>/` are editorial hubs.

## Gotchas (learned the hard way)
- Go `html/template` forbids **dynamic attribute names** (`data-{{$k}}=` → `ZgotmplZ`); write data-attrs literally.
- Inside a nested `range`, `$` is the **Page**, not the loop item — capture `{{ $x := . }}` before the inner loop.
- Embed JSON for JS as `{{ $m | jsonify | safeJS }}` inline — the **minifier double-encodes** `<script type="application/json">`.
- Vision taggers emit `"Facade"` (no cedilla) — normalize to `"Façade"` after a tagging pass.
- Use `hugo.Data`, not deprecated `.Site.Data`.
