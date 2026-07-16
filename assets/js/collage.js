// Hero collage: pack one collection's photos into the full-bleed hero box with
// ZERO cropping. Every photo keeps its exact aspect ratio; a fixed horizontal
// gap separates cells, and the leftover vertical space is distributed as the
// row gap. The layout search tries many shuffles × row-height targets and
// keeps the arrangement whose solved row gap lands closest to the column gap,
// so the grout reads as one consistent padding. (This replaces the old
// scale-to-fit approach, which cropped up to ~10% at low photo counts.)
(() => {
  const box = document.querySelector('[data-collage]')
  const pools = window.COLLAGE_POOLS
  const slugs = pools ? Object.keys(pools).filter((s) => (pools[s] || []).length) : []
  if (!box || !slugs.length) return
  // One eligible collection per visit, at random.
  const slug = slugs[Math.floor(Math.random() * slugs.length)]
  const items = pools[slug]

  // Caption: collection name + place, linking to the collection page.
  const cap = document.querySelector('[data-collage-caption]')
  const meta = (window.COLLAGE_META || {})[slug]
  if (cap && meta) {
    cap.textContent = meta.place ? `${meta.title} · ${meta.place}` : meta.title
    cap.href = meta.href
    cap.hidden = false
  }

  const GAP = 8 // px — column gap; the search aims the row gap at this too
  const TRIES = 160 // candidate orders examined per layout (cheap: O(n) each)

  function shuffled(arr) {
    const a = arr.slice()
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1))
      ;[a[i], a[j]] = [a[j], a[i]]
    }
    return a
  }

  // Candidate orders are generated ONCE per visit and reused by every layout()
  // call, so the layout is a pure function of (W, H): the same photos stay put
  // until the page is reloaded — no reshuffling on scroll-driven resizes.
  const ORDERS = Array.from({ length: TRIES }, () => shuffled(items))

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
    if (a.v < 2 || a.v > 34 || Math.abs(a.v - a.g) > 1.5) return null
    return a
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
    const mobile = W < 700
    const base = mobile ? H / 2.8 : H / 2.2

    // Search: for each candidate order × row-height target × mode, refine to a
    // unified gap (column gap == row gap) and keep the arrangement whose gap is
    // closest to the design GAP. Flush layouts win ties; framed mode rescues
    // pools whose aspect mix can't tile the box flush.
    let best = null
    for (let t = 0; t < TRIES; t++) {
      const order = ORDERS[t]
      for (const f of [0.8, 0.95, 1.1, 1.3]) {
        for (const mode of ['flush', 'framed']) {
          const p = refine(order, W, H, base * f, GAP, mode)
          if (!p) continue
          const score =
            Math.abs(p.v - p.g) * 4 + Math.abs(p.v - GAP) * 0.25 + (mode === 'framed' ? 1 : 0)
          if (!best || score < best.score) best = { ...p, score }
        }
      }
      if (best && best.score < 0.6) break
    }
    if (!best) return

    box.style.rowGap = best.v + 'px'
    box.style.paddingTop = box.style.paddingBottom = best.mode === 'framed' ? best.v + 'px' : '0'
    box.textContent = ''
    for (const { row, h } of best.rows) {
      const r = document.createElement('div')
      r.className = 'collage-row'
      r.style.height = h + 'px'
      r.style.columnGap = best.g + 'px'
      for (const it of row) {
        const cell = document.createElement('button')
        cell.type = 'button'
        cell.className = 'collage-cell'
        cell.setAttribute('data-lb', '')
        cell.dataset.avif = it.avif
        cell.dataset.webp = it.webp
        cell.dataset.title = it.title || ''
        cell.dataset.meta = it.meta || ''
        cell.style.width = it.ar * h + 'px'
        cell.style.flex = 'none'
        const img = document.createElement('img')
        img.src = it.thumb
        img.alt = it.title || ''
        img.decoding = 'async'
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
})()
