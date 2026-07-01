// Photos gallery: dropdown filtering + active-filter chips + shuffle + simple
// pagination + lightbox. Only the current page of the current filter is shown
// (display:none on the rest), so justify.js only lays out ~PAGE items at a time.
(function () {
  const gallery = document.querySelector('.gallery');
  if (!gallery) return;

  let items = Array.from(gallery.querySelectorAll('.gallery-item'));
  const selects = Array.from(document.querySelectorAll('.filter-select'));
  const activeWrap = document.querySelector('.active-filters');
  const countEl = document.querySelector('.photo-count');
  const pager = document.querySelector('[data-pager]');
  const shuffleBtn = document.querySelector('[data-shuffle]');
  const total = items.length;
  const PAGE = 60;
  let page = 1;

  // dim -> selected value ("" = any). `collections` is a pseudo-dim set via ?c=<slug>,
  // not a dropdown — it filters to one collection and shows a labeled chip.
  const filters = { collections: '' };
  selects.forEach((s) => (filters[s.dataset.dim] = ''));

  const COLLECTION_TITLES = window.COLLECTION_TITLES || {};
  const collParam = new URLSearchParams(location.search).get('c');
  if (collParam) filters.collections = collParam;

  // Multi-value dims are stored pipe-delimited; a photo matches if the selected
  // value is among its values. Single-value dims split to a one-element list.
  const matches = (item) =>
    Object.entries(filters).every(
      ([dim, val]) => !val || (item.dataset[dim] || '').split('|').includes(val)
    );

  function apply() {
    const matched = items.filter(matches);
    const pages = Math.max(1, Math.ceil(matched.length / PAGE));
    if (page > pages) page = pages;
    const start = (page - 1) * PAGE;
    const pageItems = new Set(matched.slice(start, start + PAGE));
    items.forEach((it) => { it.style.display = pageItems.has(it) ? '' : 'none'; });

    countEl.textContent =
      matched.length === total ? `${total} photographs` : `${matched.length} of ${total} photographs`;
    renderPager(pages, matched.length, start, pageItems.size);
    renderChips();
    // Re-justify so the visible page fills full rows edge-to-edge.
    if (window.justifyGalleries) window.justifyGalleries();
  }

  function renderPager(pages, matchedCount, start, showing) {
    if (!pager) return;
    pager.innerHTML = '';
    if (pages <= 1) return;
    const btn = (label, disabled, target) => {
      const b = document.createElement('button');
      b.className = 'pager-btn';
      b.innerHTML = label;
      b.disabled = disabled;
      if (!disabled) b.addEventListener('click', () => go(target));
      return b;
    };
    const info = document.createElement('span');
    info.className = 'pager-info';
    info.textContent = `${start + 1}–${start + showing} of ${matchedCount}  ·  page ${page}/${pages}`;
    pager.append(btn('← Prev', page === 1, page - 1), info, btn('Next →', page === pages, page + 1));
  }

  function go(p) {
    page = p;
    apply();
    gallery.scrollIntoView({ behavior: 'smooth', block: 'start' });
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
        page = 1;
        apply();
      });
      activeWrap.appendChild(chip);
    });
  }

  selects.forEach((sel) => {
    sel.addEventListener('change', () => {
      filters[sel.dataset.dim] = sel.value;
      page = 1; // new filter → back to the first page
      apply();
    });
  });

  if (shuffleBtn) {
    shuffleBtn.addEventListener('click', () => {
      for (let i = items.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [items[i], items[j]] = [items[j], items[i]];
      }
      items.forEach((it) => gallery.appendChild(it)); // reflect new order in the DOM
      page = 1;
      apply();
    });
  }

  apply();
  // The expanded-photo lightbox (prev/next/swipe) is handled by lightbox.js —
  // every .gallery-item carries [data-lb]; it navigates in DOM order (so it
  // follows shuffle) and skips items hidden by the filter/pagination.
})();
