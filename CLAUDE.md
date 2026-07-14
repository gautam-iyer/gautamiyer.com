# gautamiyer.com — build notes

Hugo static site (personal site + photography portfolio). Live at https://gautamiyer.com via **Cloudflare Pages** (auto-builds from GitHub `main` on push; build = `hugo --gc --minify`, `HUGO_VERSION=0.159.0`). Images on **Cloudflare R2** (bucket `gautamiyer-photos`, public base = `photo_base` in `hugo.toml`).

## Deploy
- `scripts/deploy.sh "commit message"` — preflight builds (aborts if the build errors, so broken templates never reach prod), then commits + pushes. Prefer this over manual push.
- CSS/JS are **fingerprinted** via Hugo's asset pipeline (`assets/css`, `assets/js` → `resources.Get | minify | fingerprint`). URLs are content-hashed, so deploys cache-bust automatically — **no hard-refresh needed**. Never link `/css` or `/js` directly; use the `asset-js.html` partial (JS) or the head block (CSS).

## Photo pipeline (`scripts/photos/`)
- `pipeline.py` — manifest brain, keyed by relative path, idempotent, never clobbers `reviewed:true`. Subcommands: `scan [--shoot]`, `derive`, `tag-apply`, `neighborhoods`, `contact-sheet`, `prune`, `status`; global `--manifest` for staging. Add a shoot to the `SHOOTS` list, then scan→derive→tag→neighborhoods→`r2_upload.sh`→deploy.
- `tagger.py` — local review/curation app (localhost:8800); autosaves to `data/photos.json` + `data/collections.json`, sets `reviewed:true`. Modes: Tag / Collections / Edit members / **Duplicates** (reviews `data/duplicates.json` groups: keep-only-one, per-frame delete, dismiss).
- `dupes.py` — near-duplicate detection (dHash+aHash on thumbs; burst-window within shoot + strict cross-shoot) → `data/duplicates.json`. Re-run after ingests; preserves prior review state.
- Derivatives live in `.photo-build/` (gitignored); after R2 upload run `pipeline.py prune` (keeps thumbs).

## Camera provenance & priority
- Per-photo `camera` ("EOS 7D" = old body, "EOS R8" = new, null = film) — read from source EXIF at `scan`; per-shoot registry override (`"camera": None` for film folders). Tagger shows it (amber badge for 7D) + filter.
- **Old-camera content is deprioritized in the UI**: carousel + /photos shuffles stable-partition `data-cam="EOS 7D"` frames after everything else; the home hero pool excludes 7D; majority-7D collection/place tiles get `data-oldcam` and sort after the rest in the DEFAULT tile order (explicit sorts untouched). Film is never penalized. `cam` flows via build_index.py items → collitems.html → carousel.html/`layouts/photos/list.html` data attrs.

## Data
- `data/photos.json` — per-photo manifest. Tag dims land_use/architecture/subject/tone are **arrays** (multi-select); neighborhood/city/medium single. Tier paths are relative to the derivatives root; templates prepend `photo_base`.
- `data/taxonomy.json` — **single source of truth** for tag dimensions/values (drives tagger + gallery filters). Edit here to add a category.
- `data/collections.json` — collection registry `{slug,title,place,featured,order,color,type,...}`. Membership is per-photo in `photos.json` (`collections:[]`).

## Templates / front-end
- `partials/collitems.html` — returns a collection's photos as lightbox-ready dicts; **always call via `partialCached … $slug`** (dedupes + speeds the build). Use it instead of re-scanning `hugo.Data.photos`.
- `partials/lbthumb.html` — a `[data-lb]` thumbnail; `static`/`assets/js/lightbox.js` wires ALL `[data-lb]` on a page into one overlay with prev/next (arrows/keys/swipe), skipping hidden items. Used on home, collection pages, and `/photos`.
- `/photos` = filterable gallery (`assets/js/photos.js`, filtering only — lightbox is the shared one). `/collections/<slug>/` pages are generated from the registry by the content adapter `content/collections/_content.gotmpl`. `/places/<slug>/` are editorial hubs.

## Data projects (charts) — `/projects/<slug>/`
- **Everything content-shaped lives in `data/projects.json`.** A registry entry with `"layout": "data"` renders via `partials/project-data.html`: header/facts (same classes as tour pages), `intro` paragraphs, `stats` tiles, then `blocks` — an ordered list mixing `{type:"chart", id, title, sub, h, model?}` and `{type:"photos", items:[{key, caption}]}` (keys into `data/photos.json`; photos open in the shared lightbox). Reorder/retitle/recaption by editing JSON only — no template or JS changes.
- **Charts are drawn by per-project JS** listed in the entry's `"scripts"` (load order matters: `js/vendor/chart.umd.js` → `js/charts.js` → `js/projects/<slug>.js` → `js/lightbox.js` if the page has photos). The project JS holds the data arrays and binds to each chart block's `id`.
- **`assets/js/charts.js` = the only shared chart layer** (`window.SiteCharts`). Global Chart.js theming (Inter, ink text, hairline grids, white tooltips), plugins (`crosshair`, `endLabels` — collision-skipping, `barValues: true|'max'`), and helpers: `column()` (the house single-series bar chart — use it, don't hand-roll), `ols()` (slope/intercept/R²/SE/t/p + 95% CI `band(x)`), `table()` (collapsible data-table under a figure — add one per chart, it's the accessibility fallback), `alpha()`. Keep new reusable chart patterns HERE; keep one-off configs in the project JS.
- **Chart palette ≠ site palette.** The hugo.toml accents fail as data colors (validated: steel/purple read gray; blue↔purple collapses for colorblind readers). `charts.js` hardcodes chart-tuned same-hue variants: blue `#2a5c9e`, gold `#b3872a`, teal `#0f93a8`, terracotta `#c14a3e`, purple `#ad63c4`. Single-series charts always take slot-1 blue; multi-series assign slots in order, never cycled or reordered.
- **NYCHA specifics:** era arrays at the top of `assets/js/projects/nycha.js` are hand-copied from the workbook's Pivots sheet; the development-level scatter is spliced by `scripts/nycha_extract.py` (rewrites the `/*__DATA__*/` literal from the xlsx — rerun it when the workbook updates).
- Non-tour projects live at `/projects/<slug>/` (the content adapter paths by `type`; Walking Tours keep `/projects/walking-tours/<slug>/`). Home features projects sorted by registry `order`.
- Mobile: `.dp-canvas` height is forced to 300px under 640px (`!important` beats the per-figure inline `h`).

## Gotchas (learned the hard way)
- Go `html/template` forbids **dynamic attribute names** (`data-{{$k}}=` → `ZgotmplZ`); write data-attrs literally.
- Inside a nested `range`, `$` is the **Page**, not the loop item — capture `{{ $x := . }}` before the inner loop.
- Embed JSON for JS as `{{ $m | jsonify | safeJS }}` inline — the **minifier double-encodes** `<script type="application/json">`.
- Vision taggers emit `"Facade"` (no cedilla) — normalize to `"Façade"` after a tagging pass.
- Use `hugo.Data`, not deprecated `.Site.Data`.
