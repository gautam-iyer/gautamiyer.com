// Generic lightbox with prev/next navigation. Any element with [data-lb]
// (+ data-avif/data-webp/data-title/data-meta) is a slide; arrows / keyboard /
// swipe move between all slides on the page (i.e. the whole collection).
(function () {
  const triggers = Array.from(document.querySelectorAll('[data-lb]'));
  if (!triggers.length) return;

  const lb = document.createElement('div');
  lb.className = 'lightbox';
  lb.innerHTML =
    '<div class="lightbox-close">CLOSE ✕</div>' +
    '<button class="lightbox-nav prev" aria-label="Previous">‹</button>' +
    '<button class="lightbox-nav next" aria-label="Next">›</button>' +
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
  const navigable = () => triggers.some((t, i) => i !== idx && isVisible(t));

  function render() {
    const d = triggers[idx].dataset;
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

  function open(i) {
    idx = i;
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
    for (let n = 0; n < triggers.length; n++) {
      i = (i + step + triggers.length) % triggers.length;
      if (isVisible(triggers[i])) { idx = i; render(); return; }
    }
  }

  triggers.forEach((el, i) => el.addEventListener('click', () => open(i)));
  prevBtn.addEventListener('click', (e) => { e.stopPropagation(); go(-1); });
  nextBtn.addEventListener('click', (e) => { e.stopPropagation(); go(1); });
  lb.querySelector('.lightbox-close').addEventListener('click', (e) => { e.stopPropagation(); close(); });
  // click on the dark backdrop closes; clicks on the image/arrows do not
  lb.addEventListener('click', (e) => { if (e.target === lb) close(); });
  lb.querySelector('.lightbox-image').addEventListener('click', (e) => e.stopPropagation());

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
