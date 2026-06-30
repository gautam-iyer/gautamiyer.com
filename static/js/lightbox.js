// Generic lightbox: any element with [data-lb] (+ data-avif/data-webp/data-title/data-meta)
// opens a darkened full-view overlay. Reuses the .lightbox CSS from main.css.
(function () {
  const triggers = document.querySelectorAll('[data-lb]');
  if (!triggers.length) return;

  const lb = document.createElement('div');
  lb.className = 'lightbox';
  lb.innerHTML =
    '<div class="lightbox-close">CLOSE ✕</div>' +
    '<div class="lightbox-image"><picture></picture></div>' +
    '<div class="lightbox-caption"><div class="lightbox-title"></div><div class="lightbox-meta"></div></div>';
  document.body.appendChild(lb);
  const pic = lb.querySelector('picture');
  const titleEl = lb.querySelector('.lightbox-title');
  const metaEl = lb.querySelector('.lightbox-meta');

  function open(el) {
    const { avif, webp, title, meta } = el.dataset;
    pic.innerHTML = '';
    if (avif) {
      const s = document.createElement('source');
      s.type = 'image/avif';
      s.srcset = avif;
      pic.appendChild(s);
    }
    const img = document.createElement('img');
    img.src = webp || avif;
    img.alt = title || '';
    pic.appendChild(img);
    titleEl.textContent = title || '';
    metaEl.textContent = meta || '';
    lb.classList.add('open');
    document.body.style.overflow = 'hidden';
  }
  function close() {
    lb.classList.remove('open');
    document.body.style.overflow = '';
    pic.innerHTML = '';
  }

  triggers.forEach((el) => el.addEventListener('click', () => open(el)));
  lb.addEventListener('click', close);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && lb.classList.contains('open')) close();
  });
})();
