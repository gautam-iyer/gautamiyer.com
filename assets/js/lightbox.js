// Generic lightbox with prev/next navigation. Any element with [data-lb]
// (+ data-avif/data-webp/data-title/data-meta) is a slide. Navigation is scoped
// to the group the opened slide belongs to — a single carousel, or the gallery —
// so on the multi-carousel home page arrows stay within one collection.
(function () {
  const triggers = Array.from(document.querySelectorAll('[data-lb]'));
  if (!triggers.length) return;

  // The navigation group for a slide: its carousel/gallery container, else all.
  const groupOf = (el) => el.closest('[data-carousel], .jgallery, .collection-grid');
  // Precompute each slide's group ONCE (one closest() per trigger here) instead
  // of rescanning all triggers on every open — matters on /photos (1438 items).
  const groups = new Map();
  triggers.forEach((t) => {
    const g = groupOf(t) || document;
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(t);
  });
  let nav = triggers; // current navigable set (the opened slide's group)

  const lb = document.createElement('div');
  lb.className = 'lightbox';
  lb.innerHTML =
    '<div class="lightbox-close">CLOSE ✕</div>' +
    '<button class="lightbox-nav prev" aria-label="Previous">←</button>' +
    '<button class="lightbox-nav next" aria-label="Next">→</button>' +
    '<div class="lightbox-image"><picture></picture></div>' +
    '<div class="lightbox-caption"><div class="lightbox-title"></div><div class="lightbox-meta"></div></div>';
  document.body.appendChild(lb);

  const pic = lb.querySelector('picture');
  const titleEl = lb.querySelector('.lightbox-title');
  const metaEl = lb.querySelector('.lightbox-meta');
  const prevBtn = lb.querySelector('.lightbox-nav.prev');
  const nextBtn = lb.querySelector('.lightbox-nav.next');

  let idx = 0;
  // A trigger is navigable only if visible (on /photos, filters hide items).
  const isVisible = (el) => el.offsetParent !== null;
  const navigable = () => nav.some((t, i) => i !== idx && isVisible(t));

  function render() {
    lb.classList.remove('zoomed'); // reset zoom on open and on each navigation
    const d = nav[idx].dataset;
    pic.innerHTML = '';
    if (d.avif) {
      const s = document.createElement('source');
      s.type = 'image/avif';
      s.srcset = d.avif;
      pic.appendChild(s);
    }
    const img = document.createElement('img');
    img.src = d.webp || d.avif;
    img.alt = d.title || '';
    pic.appendChild(img);
    titleEl.textContent = d.title || '';
    metaEl.textContent = d.meta || '';
    const show = navigable();
    prevBtn.style.display = show ? '' : 'none';
    nextBtn.style.display = show ? '' : 'none';
  }

  function open(el) {
    // Scope navigation to the opened slide's group (its carousel/gallery).
    nav = groups.get(groupOf(el) || document) || triggers;
    idx = nav.indexOf(el);
    render();
    lb.classList.add('open');
    document.body.style.overflow = 'hidden';
  }
  function close() {
    lb.classList.remove('open');
    document.body.style.overflow = '';
    pic.innerHTML = '';
  }
  function go(step) {
    let i = idx;
    for (let n = 0; n < nav.length; n++) {
      i = (i + step + nav.length) % nav.length;
      if (isVisible(nav[i])) { idx = i; render(); return; }
    }
  }

  // One delegated listener instead of one per [data-lb] (1438 on /photos).
  // Carousel clone slides carry no [data-lb]; carousel.js proxies their clicks
  // to the real original, whose click bubbles here — so this covers them too.
  document.addEventListener('click', (e) => {
    const el = e.target.closest('[data-lb]');
    if (el) open(el);
  });
  prevBtn.addEventListener('click', (e) => { e.stopPropagation(); go(-1); });
  nextBtn.addEventListener('click', (e) => { e.stopPropagation(); go(1); });
  lb.querySelector('.lightbox-close').addEventListener('click', (e) => { e.stopPropagation(); close(); });
  // Click the photo to toggle one level of zoom; click anywhere else on the
  // black backdrop to close. (Arrows / close button stopPropagation, so they
  // never reach here.)
  lb.addEventListener('click', (e) => {
    if (e.target.closest('picture')) { lb.classList.toggle('zoomed'); return; }
    if (e.target.closest('.lightbox-caption')) return; // reading the caption shouldn't dismiss
    close();
  });

  document.addEventListener('keydown', (e) => {
    if (!lb.classList.contains('open')) return;
    if (e.key === 'Escape') close();
    else if (e.key === 'ArrowLeft') go(-1);
    else if (e.key === 'ArrowRight') go(1);
  });

  // touch swipe
  let x0 = null;
  lb.addEventListener('touchstart', (e) => { x0 = e.changedTouches[0].clientX; }, { passive: true });
  lb.addEventListener('touchend', (e) => {
    if (x0 === null) return;
    const dx = e.changedTouches[0].clientX - x0;
    if (Math.abs(dx) > 45) go(dx < 0 ? 1 : -1);
    x0 = null;
  }, { passive: true });
})();
