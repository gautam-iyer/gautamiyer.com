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

  // ── Lightbox ──
  const lb = document.getElementById('lightbox');
  const lbPic = document.getElementById('lightbox-picture');
  const lbTitle = document.getElementById('lightbox-title');
  const lbMeta = document.getElementById('lightbox-meta');

  function openLightbox(item) {
    const { avif, webp, title, caption } = item.dataset;
    lbPic.innerHTML = '';
    if (avif) {
      const s = document.createElement('source');
      s.type = 'image/avif';
      s.srcset = avif;
      lbPic.appendChild(s);
    }
    const img = document.createElement('img');
    img.src = webp || avif;
    img.alt = title || '';
    lbPic.appendChild(img);
    lbTitle.textContent = title || '';
    lbMeta.textContent = caption || '';
    lb.classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  function closeLightbox() {
    lb.classList.remove('open');
    document.body.style.overflow = '';
    lbPic.innerHTML = '';
  }

  items.forEach((item) =>
    item.addEventListener('click', () => openLightbox(item))
  );
  lb.addEventListener('click', closeLightbox);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && lb.classList.contains('open')) closeLightbox();
  });
})();
