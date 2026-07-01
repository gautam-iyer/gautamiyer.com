// Infinite center-mode carousels for the home featured collections, with a
// "one at a time" spotlight: only the dominant carousel (most in view) plays
// and is fully opaque; the others fade to white and pause. A single
// IntersectionObserver hands off as you scroll and fires a `collectionchange`
// event so the side-nav can highlight the matching collection.
//
// Each carousel loops infinitely: the track is flanked by a full clone set on
// each side so there are always photos left and right; when a move lands in a
// clone set we snap (no animation) to the equivalent original. Clones carry no
// [data-lb] (no lightbox duplicates); clicking one proxies to its original.
(function () {
  const DELAY = 3000;
  const controllers = [];

  function initCarousel(root) {
    const track = root.querySelector('.carousel-track');
    const originals = Array.from(track.children);
    const N = originals.length;
    if (N === 0) return null;

    // Shuffle so each visit shows the collection's photos in a fresh order
    // (Fisher–Yates), then reflect that order in the DOM before cloning.
    if (N > 1) {
      for (let x = N - 1; x > 0; x--) {
        const y = Math.floor(Math.random() * (x + 1));
        [originals[x], originals[y]] = [originals[y], originals[x]];
      }
      originals.forEach((s) => track.appendChild(s));
    }

    originals.forEach((s, i) => (s.dataset.idx = i));

    if (N > 1) {
      const mkClone = (s) => {
        const c = s.cloneNode(true);
        c.removeAttribute('data-lb');
        c.dataset.clone = '1';
        return c;
      };
      originals.map(mkClone).forEach((c) => track.insertBefore(c, originals[0]));
      originals.map(mkClone).forEach((c) => track.appendChild(c));
    }

    const slides = Array.from(track.children);
    const mid = N > 1 ? N : 0;
    let i = mid;
    let timer = null;
    let active = false;

    function center(animate) {
      const slide = slides[i];
      if (!slide) return; // safety: never index past the (cloned) track
      if (!animate) track.style.transition = 'none';
      const offset = root.clientWidth / 2 - (slide.offsetLeft + slide.offsetWidth / 2);
      track.style.transform = `translateX(${offset}px)`;
      slides.forEach((s, j) => s.classList.toggle('on', j === i));
      if (!animate) {
        void track.offsetWidth;
        track.style.transition = '';
      }
    }

    function go(n) { i = n; center(true); }

    track.addEventListener('transitionend', (e) => {
      // Only the track's own slide transition — ignore slide scale transitions
      // that bubble up (they'd snap the seam mid-animation and twitch).
      if (e.target !== track || e.propertyName !== 'transform' || N <= 1) return;
      if (i < N || i >= 2 * N) {
        i = N + ((((i - N) % N) + N) % N);
        center(false);
      }
    });

    function start() { stop(); if (active && N > 1) timer = setInterval(() => go(i + 1), DELAY); }
    function stop() { if (timer) { clearInterval(timer); timer = null; } }

    root.querySelector('.carousel-prev').addEventListener('click', (e) => { e.stopPropagation(); if (N > 1) { go(i - 1); start(); } });
    root.querySelector('.carousel-next').addEventListener('click', (e) => { e.stopPropagation(); if (N > 1) { go(i + 1); start(); } });

    track.addEventListener('click', (e) => {
      const slide = e.target.closest('.carousel-slide');
      if (slide && slide.dataset.clone) originals[+slide.dataset.idx].click();
    });

    // Re-center on resize, coalesced to one reflow per frame (center() forces a
    // synchronous layout read, so an unthrottled handler janks on mobile
    // orientation / URL-bar changes). Slide geometry is fixed by CSS
    // (height + aspect-ratio), so there is no need to recenter on image load.
    let rzraf = null;
    window.addEventListener('resize', () => {
      if (rzraf) cancelAnimationFrame(rzraf);
      rzraf = requestAnimationFrame(() => center(false));
    });

    center(false);

    const section = root.closest('.fc-collection');
    return {
      id: section ? section.id : null,
      color: root.dataset.color || null,
      section,
      activate() { if (active) return; active = true; root.classList.remove('dormant'); start(); },
      deactivate() { active = false; root.classList.add('dormant'); stop(); },
    };
  }

  // Tint the page's background grid to a faint wash of the active carousel's
  // accent (or back to neutral gray when no carousel is in view). It's just a
  // CSS custom property feeding a static background-image — no measurable cost.
  const docEl = document.documentElement;
  // Grid toggled OFF for now: don't tint the background grid to the active
  // collection color. Flip to true (and restore --grid-color in main.css) to
  // bring the tinted grid back.
  const GRID_TINT = false;
  function setGrid(color) {
    if (!GRID_TINT) return;
    if (color) docEl.style.setProperty('--grid-color', 'color-mix(in srgb, ' + color + ' 16%, transparent)');
    else docEl.style.removeProperty('--grid-color');
  }

  document.querySelectorAll('[data-carousel]').forEach((r) => {
    const c = initCarousel(r);
    if (c) controllers.push(c);
  });
  if (!controllers.length) return;

  function announce(id) { document.dispatchEvent(new CustomEvent('collectionchange', { detail: id })); }

  // Top carousel leads on load; the rest start dormant (dimmed).
  controllers.forEach((c, idx) => (idx === 0 ? c.activate() : c.deactivate()));
  setGrid(controllers[0].color);
  // Defer the first highlight: nav.js's listener is a separate deferred script
  // that runs after this one, so dispatching synchronously would be missed.
  setTimeout(() => announce(controllers[0].id), 0);

  // Hand off to the most-visible carousel as the page scrolls. Runs even for a
  // single carousel so the grid tint resets to neutral when it scrolls away.
  if ('IntersectionObserver' in window) {
    const ratios = new Map();
    const byEl = new Map();
    controllers.forEach((c) => { if (c.section) byEl.set(c.section, c); });
    let currentId = controllers[0].id;

    const io = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        if (en.isIntersecting) ratios.set(en.target, en.intersectionRatio);
        else ratios.delete(en.target);
      });
      let bestEl = null;
      let bestR = -1;
      ratios.forEach((r, el) => { if (r > bestR) { bestR = r; bestEl = el; } });
      const winner = bestEl && byEl.get(bestEl);
      if (!winner) { setGrid(null); return; } // no carousel in view → neutral grid
      setGrid(winner.color);
      if (winner.id === currentId) return;
      currentId = winner.id;
      controllers.forEach((c) => (c === winner ? c.activate() : c.deactivate()));
      announce(currentId);
    }, { threshold: [0.15, 0.4, 0.7], rootMargin: '-10% 0px -10% 0px' });

    controllers.forEach((c) => { if (c.section) io.observe(c.section); });
  }
})();
