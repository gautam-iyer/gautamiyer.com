// True justified gallery layout (Flickr / Google-Photos style).
// Packs the *visible* items of each .jgallery into full-width rows and scales
// each row to fill the container exactly — left and right edges flush — while
// preserving every photo's real aspect ratio (--ar = width/height), so nothing
// is cropped. Sets width/height inline per item. Re-run on resize and whenever
// filtering changes which items are visible (photos.js calls justifyGalleries).
(function () {
  function ar(el) {
    return parseFloat(el.style.getPropertyValue('--ar')) || 1.5;
  }

  function justify(container) {
    const cs = getComputedStyle(container);
    const targetH = parseFloat(cs.getPropertyValue('--thumb-h')) || 300;
    const gap = parseFloat(cs.columnGap || cs.gap) || 8;
    const W = container.clientWidth;
    if (!W) return;

    const items = Array.from(container.children).filter(
      (el) => el.style.display !== 'none'
    );

    let row = [];
    let arSum = 0;

    function flush(fill) {
      if (!row.length) return;
      const avail = W - gap * (row.length - 1);
      const h = fill ? avail / arSum : targetH; // full rows fill width; last row keeps targetH
      row.forEach((el) => {
        el.style.width = Math.floor(h * ar(el)) + 'px';
        el.style.height = Math.floor(h) + 'px';
      });
      row = [];
      arSum = 0;
    }

    items.forEach((el) => {
      row.push(el);
      arSum += ar(el);
      // Once the row at target height would overflow the container, commit it
      // and stretch it to fill the width exactly.
      if (targetH * arSum + gap * (row.length - 1) >= W) flush(true);
    });
    flush(false); // trailing partial row: natural height, left-aligned
  }

  function justifyGalleries() {
    document.querySelectorAll('.jgallery').forEach(justify);
  }
  window.justifyGalleries = justifyGalleries;

  let raf = null;
  window.addEventListener('resize', () => {
    if (raf) cancelAnimationFrame(raf);
    raf = requestAnimationFrame(justifyGalleries);
  });

  justifyGalleries();
})();
