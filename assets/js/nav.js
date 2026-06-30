// Side navigation drawer.
// Opens on hover of the sliver handle / panel (with a close delay so it's easy
// to pull out and let sit), or pinned open by clicking the handle. Backdrop /
// Esc / a link click closes it. Nested submenus reveal on hover via CSS.
// The home submenu's [data-spy] links are highlighted from the
// `collectionchange` event that carousel.js fires for the dominant carousel.
(function () {
  const sn = document.querySelector('[data-sidenav]');
  if (!sn) return;
  const handle = sn.querySelector('.sidenav-handle');
  const panel = sn.querySelector('.sidenav-panel');
  const backdrop = document.querySelector('[data-sidenav-backdrop]');
  const CLOSE_DELAY = 950;

  let pinned = false;
  let hovering = false;
  let closeT = null;

  function update() {
    const open = pinned || hovering;
    sn.classList.toggle('open', open);
    if (backdrop) backdrop.classList.toggle('show', open);
  }
  function cancelClose() { if (closeT) { clearTimeout(closeT); closeT = null; } }
  function close() { cancelClose(); pinned = false; hovering = false; update(); }

  // Hover open is immediate; hover close waits, so the drawer is easy to keep open.
  sn.addEventListener('mouseenter', () => { cancelClose(); hovering = true; update(); });
  sn.addEventListener('mouseleave', () => {
    cancelClose();
    closeT = setTimeout(() => { closeT = null; hovering = false; update(); }, CLOSE_DELAY);
  });

  handle.addEventListener('click', (e) => { e.stopPropagation(); cancelClose(); pinned = !pinned; update(); });
  if (backdrop) backdrop.addEventListener('click', close);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
  panel.addEventListener('click', (e) => { if (e.target.closest('a')) close(); });

  // Highlight the submenu link for the carousel currently dominant on Home.
  const spy = Array.from(panel.querySelectorAll('[data-spy]'));
  if (spy.length) {
    document.addEventListener('collectionchange', (e) => {
      spy.forEach((a) => a.classList.toggle('current', a.dataset.spy === e.detail));
    });
  }
})();
