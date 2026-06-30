// Photos gallery: dropdown filtering + active-filter chips + lightbox.
(function () {
  const gallery = document.querySelector('.gallery');
  if (!gallery) return;

  const items = Array.from(gallery.querySelectorAll('.gallery-item'));
  const selects = Array.from(document.querySelectorAll('.filter-select'));
  const activeWrap = document.querySelector('.active-filters');
  const countEl = document.querySelector('.photo-count');
  const total = items.length;

  // dim -> selected value ("" = any). `collections` is a pseudo-dim set via ?c=<slug>,
  // not a dropdown — it filters to one collection and shows a labeled chip.
  const filters = { collections: '' };
  selects.forEach((s) => (filters[s.dataset.dim] = ''));

  const COLLECTION_TITLES = window.COLLECTION_TITLES || {};
  const collParam = new URLSearchParams(location.search).get('c');
  if (collParam) filters.collections = collParam;

  const labelFor = (dim) =>
    selects.find((s) => s.dataset.dim === dim)?.options[0].text || dim;

  function apply() {
    let shown = 0;
    items.forEach((item) => {
      // Multi-value dims are stored pipe-delimited; a photo matches if the
      // selected value is among its values. Single-value dims split to one item.
      const match = Object.entries(filters).every(
        ([dim, val]) => !val || (item.dataset[dim] || '').split('|').includes(val)
      );
      item.style.display = match ? '' : 'none';
      if (match) shown++;
    });
    countEl.textContent =
      shown === total ? `${total} photographs` : `${shown} of ${total} photographs`;
    // Re-justify so the visible set fills full rows edge-to-edge.
    if (window.justifyGalleries) window.justifyGalleries();
    renderChips();
  }

  function renderChips() {
    activeWrap.innerHTML = '';
    Object.entries(filters).forEach(([dim, val]) => {
      if (!val) return;
      const label = dim === 'collections' ? (COLLECTION_TITLES[val] || val) : val;
      const chip = document.createElement('span');
      chip.className = 'filter-tag';
      chip.innerHTML = `${label} <span class="x">✕</span>`;
      chip.addEventListener('click', () => {
        filters[dim] = '';
        const sel = selects.find((s) => s.dataset.dim === dim);
        if (sel) sel.value = '';
        apply();
      });
      activeWrap.appendChild(chip);
    });
  }

  selects.forEach((sel) => {
    sel.addEventListener('change', () => {
      filters[sel.dataset.dim] = sel.value;
      apply();
    });
  });

  apply();
  // The expanded-photo lightbox (with prev/next/swipe) is handled by the shared
  // lightbox.js — every .gallery-item carries [data-lb]. Nav skips filtered-out items.
})();
