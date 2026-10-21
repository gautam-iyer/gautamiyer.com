// Justified photo gallery: EVERY item of each .jgallery, in order, in rows that
// fill the container exactly — left and right edges flush, the last row too —
// each photo at its real aspect ratio (--ar = width/height), so nothing is
// cropped. Row breaks are chosen by DP so every row lands as close as it can
// to the target height (--thumb-h, px): cost = Σ log²(row h / target), at most
// MAX photos a row. Greedy filling left a short last row at an arbitrary
// height; the DP spreads the slack over the whole gallery instead. Sets each
// item's width/height inline, and tells a srcset image its laid-out width so
// big cells on retina pull the display tier. Re-run on resize.
// Used by place pages: each collection's wall (every photo of the collection —
// Gautam, 2026-10-21) and the legacy album of a place not yet curated.
(function () {
  const MAX = 8;
  const ar = (el) => parseFloat(el.style.getPropertyValue('--ar')) || 1.5;

  function justify(container) {
    const cs = getComputedStyle(container);
    const T = parseFloat(cs.getPropertyValue('--thumb-h')) || 300;
    const gap = parseFloat(cs.columnGap) || 8;
    // 1px of slack: rows are laid out by flex-wrap, and a row whose subpixel
    // widths summed past the container would wrap its last photo.
    const W = container.clientWidth - 1;
    if (W <= 0) return;
    const items = Array.from(container.children);
    const ars = items.map(ar);
    const n = items.length;
    const rowH = (i, j, A) => (W - gap * (j - i - 1)) / A;

    const cost = new Array(n + 1).fill(Infinity);
    const from = new Array(n + 1).fill(0);
    cost[0] = 0;
    for (let j = 1; j <= n; j++) {
      let A = 0;
      for (let i = j - 1; i >= Math.max(0, j - MAX); i--) {
        A += ars[i];
        const c = cost[i] + Math.pow(Math.log(rowH(i, j, A) / T), 2);
        if (c < cost[j]) { cost[j] = c; from[j] = i; }
      }
    }

    for (let j = n; j > 0; j = from[j]) {
      const i = from[j];
      let A = 0;
      for (let k = i; k < j; k++) A += ars[k];
      const h = rowH(i, j, A);
      for (let k = i; k < j; k++) {
        const el = items[k];
        const w = h * ars[k];
        el.style.width = w + 'px';
        el.style.height = h + 'px';
        const img = el.querySelector('img[srcset]');
        if (img) img.sizes = Math.round(w) + 'px';
      }
    }
  }

  function justifyGalleries() {
    document.querySelectorAll('.jgallery').forEach(justify);
  }

  let raf = null;
  window.addEventListener('resize', () => {
    if (raf) cancelAnimationFrame(raf);
    raf = requestAnimationFrame(justifyGalleries);
  });

  justifyGalleries();
})();
