// Hero collage: pack one collection's photos edge-to-edge into a fixed
// rectangle (the full-bleed hero box). Justified rows — each row of photos is
// scaled to a common height so it exactly fills the width — with the row set
// chosen so total height lands near the box height; the final uniform scale to
// EXACTLY the box height is absorbed by object-fit: cover (a few % of crop).
// Orientation-awareness falls out of the math: a narrow (portrait) box packs
// 1–2 mostly-portrait photos per row, a wide box packs 3–5.
(() => {
  const box = document.querySelector('[data-collage]')
  const pools = window.COLLAGE_POOLS
  const slugs = pools ? Object.keys(pools).filter((s) => (pools[s] || []).length) : []
  if (!box || !slugs.length) return
  // One eligible collection per visit, at random.
  const items = pools[slugs[Math.floor(Math.random() * slugs.length)]]

  // One shuffle per visit; stable across resizes so relayouts don't reshuffle.
  const pool = items.slice()
  for (let i = pool.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[pool[i], pool[j]] = [pool[j], pool[i]]
  }

  // Greedy row fill at a target height, justify each row to the full width.
  function plan(W, H, targetH) {
    const rows = []
    let i = 0
    let cum = 0
    while (cum < H && i < pool.length) {
      const row = []
      let sumAr = 0
      while (i < pool.length && (row.length === 0 || sumAr * targetH < W)) {
        row.push(pool[i])
        sumAr += pool[i].ar
        i++
      }
      // The greedy step overshoots (justified height lands under target when a
      // wide photo tips the row). If the row reads closer to target WITHOUT its
      // last photo, push that photo to the next row instead.
      if (row.length > 1) {
        const withH = W / sumAr
        const withoutAr = sumAr - row[row.length - 1].ar
        const withoutH = W / withoutAr
        if (Math.abs(withoutH - targetH) < Math.abs(withH - targetH)) {
          i--
          row.pop()
          sumAr = withoutAr
        }
      }
      const h = W / sumAr
      rows.push({ row, sumAr, h })
      cum += h
    }
    return { rows, cum }
  }

  function layout() {
    const W = box.clientWidth
    const H = box.clientHeight
    if (!W || !H) return
    const mobile = W < 700
    // Bigger cells = fewer photos on screen (a wall, not a mosaic): ~2-3 rows
    // desktop (roughly 8-12 photos), ~3-4 rows mobile.
    const base = mobile ? H / 2.8 : H / 2.2

    // Try a few target row heights; keep the plan whose exact-fill scale factor
    // is closest to 1 (least residual cropping).
    let best = null
    for (const f of [0.8, 1, 1.25]) {
      const p = plan(W, H, base * f)
      if (!p.rows.length) continue
      const k = H / p.cum
      if (!best || Math.abs(Math.log(k)) < Math.abs(Math.log(best.k))) best = { ...p, k }
    }
    if (!best) return

    box.textContent = ''
    for (const { row, sumAr, h } of best.rows) {
      const r = document.createElement('div')
      r.className = 'collage-row'
      r.style.height = h * best.k + 'px'
      for (const it of row) {
        const cell = document.createElement('button')
        cell.type = 'button'
        cell.className = 'collage-cell'
        cell.setAttribute('data-lb', '')
        cell.dataset.avif = it.avif
        cell.dataset.webp = it.webp
        cell.dataset.title = it.title || ''
        cell.dataset.meta = it.meta || ''
        cell.style.width = (it.ar / sumAr) * 100 + '%'
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
    t = setTimeout(layout, 150)
  })
  layout()
})()
