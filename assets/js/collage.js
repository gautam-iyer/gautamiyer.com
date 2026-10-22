// Hero collage: pack one collection's photos into the full-bleed hero box.
// Tiered layout guarantee (best first, blank impossible):
//   1. flush   — exact aspect ratios, ONE solved unified gap (row == column)
//   2. framed  — same, with the gap also above/below (rescues stubborn pools)
//   3. crop    — justified rows at the design gap, scaled to fit; prefix and
//                pool-derived row-split targets keep the crop minimal, and a
//                collection that would crop past MAX_CROP to meet the photo
//                floor yields the wall to another (see MIN_SHOWN)
// A unified badness score picks across tiers; crop pays ~1.6 pts per % so
// gap-perfect layouts always win when they exist.
(() => {
  const boxes = Array.from(document.querySelectorAll('[data-collage]'))
  const pools = window.COLLAGE_POOLS
  const allSlugs = pools ? Object.keys(pools).filter((s) => (pools[s] || []).length) : []
  if (!boxes.length || !allSlugs.length) return

  // Each wall on the page gets a DIFFERENT collection, assigned in DOM order
  // from one WEIGHTED shuffle per visit (repeats only if there are more walls
  // than eligible pools). Collections carry an optional home rank set in the
  // tagger's "Home rank" column (1 = most likely): rank r → weight 0.75^(r−1),
  // so ranked pools are likelier — never certain — and unranked pools all sit
  // one step below the last ranked one. Efraimidis–Spirakis keys
  // (rand^(1/w), sort desc) give a weighted shuffle without replacement, so
  // the walls stay distinct. With no ranks set anywhere this is uniform.
  const cmeta = window.COLLAGE_META || {}
  const ranks = allSlugs.map((s) => (cmeta[s] && cmeta[s].rank) || 0).filter((r) => r > 0)
  const unranked = (ranks.length ? Math.max(...ranks) : 0) + 1
  const weight = (s) => Math.pow(0.75, ((cmeta[s] && cmeta[s].rank) || unranked) - 1)
  const picks = allSlugs
    .map((s) => ({ s, key: Math.pow(Math.random(), 1 / weight(s)) }))
    .sort((a, b) => b.key - a.key)
    .map((x) => x.s)

  const GAP = 8 // px — column gap; the search aims the row gap at this too

  // The wall reads the collection IN SEQUENCE (the order set in the tagger,
  // shipped pre-sorted by build_index.py): left to right, top to bottom, the
  // first photos that fit. The layout search varies only row heights and how
  // many rows (so how many photos) to show — never the order — so the result
  // is a pure function of (W, H). A fixed order gives the solver far fewer
  // tilings to choose from, so it sweeps row-height targets finely instead.
  const FACTORS = Array.from({ length: 40 }, (_, i) => 0.5 + (0.9 * i) / 39)

  // A wall shows at least MIN_SHOWN photos (the whole pool, if it is smaller)
  // — a hard rule, not a preference: the score below used to merely penalize
  // sparse layouts, and a gap-perfect pair of giant photos could still win
  // (Bridges of Pittsburgh at 1280×720). Meeting the floor can cost crop when a
  // pool is small and portrait-heavy, since a wide screen needs aspect mass to
  // fill; past MAX_CROP the collection gives up THIS wall to the next one in
  // the shuffle instead of mangling its photos. It can still win a wall at a
  // size it does fill (a phone, a taller window), so nothing is ever barred
  // outright. If no remaining collection fills the wall within budget, the
  // least-cropped one takes it.
  const MIN_SHOWN = 5
  const MAX_CROP = 0.25
  const cropOf = (c) => (c && c.mode === 'crop' ? Math.abs(1 - c.k) : 0)
  let unused = picks.slice()
  boxes.forEach((box) => {
    if (!unused.length) unused = picks.slice() // more walls than pools: repeat
    let slug = unused[0]
    let least = Infinity
    for (const s of unused) {
      const crop = cropOf(solve(pools[s], box.clientWidth, box.clientHeight))
      if (crop <= MAX_CROP) { slug = s; break }
      if (crop < least) { least = crop; slug = s }
    }
    unused = unused.filter((s) => s !== slug)
    initCollage(box, slug)
  })

  // The layout search for one pool in a W×H box — pure, so the wall
  // assignment above can ask every candidate collection before choosing.
  // Returns the lowest-badness layout showing at least the photo floor, or
  // null for a box with no size yet.
  function solve(items, W, H) {
  if (!W || !H) return null

  // Greedy rows at a target height with gap-aware widths; heights are EXACT
  // (h = usable width / sum of aspect ratios), never scaled afterwards.
  function plan(order, W, H, targetH, gap) {
    const rows = []
    let i = 0
    let sumH = 0
    // Build rows until the pool is exhausted or we're well past the box height;
    // evalGap picks the best PREFIX, so overshoot is harmless.
    while (i < order.length && sumH < H * 1.7) {
      const row = []
      let sumAr = 0
      const usable = (n) => W - gap * (n - 1)
      while (i < order.length && (row.length === 0 || sumAr * targetH + gap * row.length < W)) {
        row.push(order[i])
        sumAr += order[i].ar
        i++
      }
      if (row.length > 1) {
        const withH = usable(row.length) / sumAr
        const withoutAr = sumAr - row[row.length - 1].ar
        const withoutH = usable(row.length - 1) / withoutAr
        if (Math.abs(withoutH - targetH) < Math.abs(withH - targetH)) {
          i--
          row.pop()
          sumAr = withoutAr
        }
      }
      const h = usable(row.length) / sumAr
      rows.push({ row, h })
      sumH += h
    }
    return { rows, sumH }
  }

  // Refinement: solve for the gap g where the leftover row gap v(g) equals g —
  // ONE unified gap everywhere, still crop-free. v(g) is near-linear between
  // partition changes, so a secant step lands almost exactly; a few polish
  // iterations handle partition jumps.
  // mode 'flush':  gaps only BETWEEN rows (R-1 gutters), photos touch top+bottom.
  // mode 'framed': the same gap also above and below (R+1 gutters) — fallback
  // for pools whose aspect mix can't tile the box flush (still zero crop).
  // Every PREFIX of the planned rows is a candidate (2 rows, 3 rows, …): a pool
  // whose tail would force a degenerate row simply doesn't render its tail.
  function evalGap(order, W, H, targetH, g, mode) {
    const p = plan(order, W, H, targetH, g)
    if (p.rows.length < 2) return null
    let bestPrefix = null
    let sumH = 0
    for (let R = 1; R <= p.rows.length; R++) {
      sumH += p.rows[R - 1].h
      if (R < 2) continue
      const gutters = mode === 'framed' ? R + 1 : R - 1
      const v = (H - sumH) / gutters
      if (v < 2 || v > 34) continue
      if (!bestPrefix || Math.abs(v - g) < Math.abs(bestPrefix.v - g)) {
        bestPrefix = { rows: p.rows.slice(0, R), sumH, g, mode, v }
      }
    }
    return bestPrefix
  }
  function refine(order, W, H, targetH, g0, mode) {
    let a = evalGap(order, W, H, targetH, g0, mode)
    if (!a) return null
    for (let n = 0; n < 10; n++) {
      if (Math.abs(a.v - a.g) < 0.35) break
      // secant toward the fixed point v(g)=g
      const g1 = Math.max(2, Math.min(34, a.g + 1))
      const b = evalGap(order, W, H, targetH, g1, mode)
      if (!b) return null
      const s = (b.v - a.v) / (g1 - a.g)
      let next = Math.abs(1 - s) > 0.05 ? (a.v - s * a.g) / (1 - s) : (a.g + a.v) / 2
      if (!isFinite(next)) next = (a.g + a.v) / 2
      next = Math.max(2, Math.min(34, next))
      const c = evalGap(order, W, H, targetH, next, mode)
      if (!c) return null
      a = c
    }
    if (a.v < 2 || a.v > 48 || Math.abs(a.v - a.g) > 3) return null
    return a
  }

  // Guaranteed fallback: justified rows at the design GAP, prefix chosen to
  // minimize the exact-fill scale |1-k| — object-fit absorbs the (small) crop.
  // Always yields a layout, so the hero can never render blank.
  function cropCandidate(order, W, H, targetH) {
    const p = plan(order, W, H, targetH, GAP)
    if (!p.rows.length) return null
    let best = null
    let sumH = 0
    for (let R = 1; R <= p.rows.length; R++) {
      sumH += p.rows[R - 1].h
      const avail = H - GAP * (R - 1)
      if (avail <= 0) break
      const k = avail / sumH
      if (!best || Math.abs(1 - k) < Math.abs(1 - best.k)) {
        best = { rows: p.rows.slice(0, R), g: GAP, v: GAP, k, mode: 'crop' }
      }
    }
    return best
  }

  // Exhaustive search over the fixed sequence: every way to break a prefix
  // of it into rows (each row 1–8 photos, at most 7 rows, pruned to sane row
  // heights). For a given set of breaks the unified gap has a CLOSED FORM —
  // the box height is linear in g — so flush and framed need no iteration:
  //   H = Σ (W − g(nᵢ−1))/Aᵢ + g·gutters  ⇒  g = (H − Σ W/Aᵢ) / (gutters − Σ (nᵢ−1)/Aᵢ)
  // (Aᵢ = row i's summed aspect ratio). The crop tier is the same breaks at
  // the design gap, scaled to fill. Greedy rows at a target height (above)
  // only ever see one partition per target; with the order pinned, the
  // partition is the only freedom left, so this is where the good tilings are.
  function exhaustive(W, H, consider) {
    const n = items.length
    const rows = [] // { start, end, A }
    const close = () => {
      const R = rows.length
      let sWA = 0
      let sNA = 0
      for (const r of rows) { sWA += W / r.A; sNA += (r.end - r.start - 1) / r.A }
      const mk = (g, mode, k) => ({
        rows: rows.map((r) => ({ row: items.slice(r.start, r.end), h: (W - g * (r.end - r.start - 1)) / r.A })),
        g, v: g, mode, k,
      })
      for (const [mode, gutters] of [['flush', R - 1], ['framed', R + 1]]) {
        if (R < 2) continue
        const den = gutters - sNA
        if (Math.abs(den) < 1e-9) continue
        const g = (H - sWA) / den
        if (g >= 2 && g <= 34) consider(mk(g, mode))
      }
      const sumH = sWA - GAP * sNA
      const avail = H - GAP * (R - 1)
      if (avail > 0) consider(mk(GAP, 'crop', avail / sumH))
    }
    const dfs = (start, usedH) => {
      if (rows.length === 7) return
      let A = 0
      for (let end = start + 1; end <= Math.min(n, start + 8); end++) {
        A += items[end - 1].ar
        const h = (W - GAP * (end - start - 1)) / A
        if (h > H * 1.4) continue // too tall: one row would overfill the box
        if (h < H / 9) break // rows only get shorter as photos are added
        if (usedH + h > H * 1.45) continue
        rows.push({ start, end, A })
        close()
        dfs(end, usedH + h + GAP)
        rows.pop()
      }
    }
    dfs(0, 0)
  }

  // Unified "badness" across tiers: perfect unified gap ≈ 0; oversized or
  // inconsistent gaps accumulate points; crop counts ~1.6 points per % of crop
  // so it only wins when gap-based layouts are genuinely poor.
  function badness(c) {
    // Above the hard floor (MIN_SHOWN), still lean toward fuller walls:
    // penalize showing fewer photos than the pool could reasonably support.
    const count = c.rows.reduce((s, r) => s + r.row.length, 0)
    const wantMin = Math.min(6, items.length)
    // quadratic: 1 photo short is mild, 3-4 short (two giant photos) is
    // prohibitive — a denser layout with moderate crop must win instead
    const sparse = Math.pow(Math.max(0, wantMin - count), 2) * 2.2
    // Uneven rows: a short strip under a tall row reads as a mistake. Greedy
    // rows at one target height never produced these; free row breaks can.
    const hs = c.rows.map((r) => r.h)
    const uneven = Math.max(0, Math.max(...hs) / Math.min(...hs) - 1.7) * 6 + sparse
    if (c.mode === 'crop') return Math.abs(1 - c.k) * 160 + 2 + uneven
    return (
      Math.abs(c.v - c.g) * 4 +
      Math.abs(c.v - GAP) * 0.15 +
      Math.max(0, c.v - 34) * 1.5 +
      (c.mode === 'framed' ? 1 : 0) +
      uneven
    )
  }

  const mobile = W < 700
  const base = mobile ? H / 2.8 : H / 2.2

  // Search: for each row-height target (and every row break, below), try the no-crop
  // modes (flush, then framed) and the guaranteed crop fallback; keep the
  // lowest unified badness. The crop tier always yields SOMETHING, so a
  // blank hero is impossible at any viewport size.
  let best = null
  let sparse = null // fewer photos than the floor: only if nothing else exists
  const floor = Math.min(MIN_SHOWN, items.length)
  const consider = (c) => {
    if (!c) return
    const score = badness(c)
    if (c.rows.reduce((s, r) => s + r.row.length, 0) < floor) {
      if (!sparse || score < sparse.score) sparse = { ...c, score }
    } else if (!best || score < best.score) best = { ...c, score }
  }
  // Row-split targets derived from the pool itself: the row height that
  // divides the whole pool's aspect mass into exactly R rows. Rescues extreme
  // viewports (very wide/short) where the density ladder can't force a split.
  const totalAr = items.reduce((s, i) => s + i.ar, 0)
  for (const f of FACTORS) {
    for (const mode of ['flush', 'framed']) consider(refine(items, W, H, base * f, GAP, mode))
    consider(cropCandidate(items, W, H, base * f))
  }
  for (let R = 1; R <= 6; R++) consider(cropCandidate(items, W, H, (W * R) / totalAr))
  exhaustive(W, H, consider)
  return best || sparse
  } // solve

  function initCollage(box, slug) {
  const items = pools[slug]

  // Caption: collection name + place, linking to the collection page.
  // Scoped to this wall's section — every wall captions itself.
  const section = box.closest('.hero-collage') || document
  const cap = section.querySelector('[data-collage-caption]')
  // Only the FIRST wall is above the fold. The follow walls are a viewport or
  // more down, so their cells load lazily — otherwise all five walls' images
  // (~35 requests, and the retina ones pull the 3500px display tier) download
  // before the reader has scrolled to any of them. Layout is unaffected: row
  // heights and cell widths come from manifest aspect ratios, not from decoded
  // images, so nothing reflows when a lazy cell arrives.
  const lazy = section !== document && section.classList.contains('hero-collage--follow')
  const meta = (window.COLLAGE_META || {})[slug]
  if (cap && meta) {
    cap.textContent = meta.place ? `${meta.title} · ${meta.place}` : meta.title
    cap.href = meta.href
    cap.hidden = false
  }

  let lastW = 0
  let lastH = 0
  function layout() {
    const W = box.clientWidth
    const H = box.clientHeight
    if (!W || !H) return
    // Deterministic in (W, H) + already rendered → nothing to do. Mobile
    // browsers fire resize when the URL bar shows/hides; the box height uses
    // svh so its size doesn't change — skip instead of rebuilding the DOM.
    if (W === lastW && H === lastH) return
    lastW = W
    lastH = H
    const best = solve(items, W, H)
    if (!best) return

    const k = best.mode === 'crop' ? best.k : 1
    box.style.rowGap = best.v + 'px'
    box.style.paddingTop = box.style.paddingBottom = best.mode === 'framed' ? best.v + 'px' : '0'
    box.textContent = ''
    for (const { row, h } of best.rows) {
      const r = document.createElement('div')
      r.className = 'collage-row'
      r.style.height = h * k + 'px'
      r.style.columnGap = best.g + 'px'
      for (const it of row) {
        const cell = document.createElement('button')
        cell.type = 'button'
        cell.className = 'collage-cell'
        cell.setAttribute('data-lb', '')
        cell.dataset.avif = it.avif
        cell.dataset.webp = it.webp
        cell.dataset.title = it.title || ''
        cell.style.width = it.ar * h + 'px'
        cell.style.flex = 'none'
        const img = document.createElement('img')
        img.src = it.thumb
        // Crisp big cells without new derivatives: offer BOTH existing tiers
        // (thumb 1000px, display 3500px — longest-edge sized, so width =
        // edge×ar for portraits) and tell the browser the cell's laid-out CSS
        // width. It factors in devicePixelRatio itself: small cells keep the
        // cheap thumb, big cells on retina pull the display tier — the
        // zoomed-in shots stop looking soft.
        if (it.webp) {
          const tw = Math.round(it.ar >= 1 ? 1000 : 1000 * it.ar)
          const dw = Math.round(it.ar >= 1 ? 3500 : 3500 * it.ar)
          img.srcset = `${it.thumb} ${tw}w, ${it.webp} ${dw}w`
          img.sizes = Math.round(it.ar * h) + 'px'
        }
        img.alt = it.title || ''
        img.decoding = 'async'
        if (lazy) img.loading = 'lazy'
        cell.appendChild(img)
        r.appendChild(cell)
      }
      box.appendChild(r)
    }
  }

  let t
  window.addEventListener('resize', () => {
    clearTimeout(t)
    t = setTimeout(() => {
      // Relayout only on real width changes (rotation / window resize). Mobile
      // URL-bar show/hide only nudges heights — the collage must not change
      // underneath a scrolling reader.
      if (box.clientWidth !== lastW) layout()
    }, 150)
  })
  layout()
  } // initCollage
})()
