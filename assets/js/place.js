// Place pages: "Read more" on long captions, and the collections menu.
(() => {
  // A caption of 2+ paragraphs shows its first paragraph plus a few lines of the
  // next, fading to the page, with "Read more" sitting on the fade. The button
  // takes the collection's accent from --accent on its section. The clamp never
  // takes more than CAP of the screen, so the photos always show on the first
  // screen — on a phone a single long paragraph runs 15+ lines, so it is
  // clamped too. (Markdownify returns a one-paragraph caption as bare text.)
  const PEEK = 2.6 // lines of the second paragraph that show through the fade
  const CAP = 0.4 // of the screen height
  // svh, measured once: unlike innerHeight it doesn't move with the mobile URL
  // bar, so scrolling never re-clamps a caption under the reader
  const probe = document.createElement('div')
  probe.style.cssText = 'position:absolute;visibility:hidden;height:100vh;height:100svh'
  document.body.appendChild(probe)
  const screenH = probe.offsetHeight || window.innerHeight
  probe.remove()
  const limit = (lh) => Math.max(CAP * screenH, 6 * lh)
  const caps = []
  document.querySelectorAll('.place-coll-caption').forEach((cap) => {
    const lh0 = parseFloat(getComputedStyle(cap).lineHeight) || 22
    if (cap.children.length < 2 && cap.scrollHeight <= limit(lh0) + 2 * lh0) return
    const section = cap.closest('.place-coll')
    const btn = document.createElement('button')
    btn.type = 'button'
    btn.className = 'read-more'
    btn.setAttribute('aria-expanded', 'false')
    cap.after(btn)
    const clamp = () => {
      if (!cap.classList.contains('is-clamped')) return
      const lh = parseFloat(getComputedStyle(cap).lineHeight) || 22
      // the caption is position:relative, so offsetTop is measured inside it
      const para = cap.children.length > 1 ? cap.children[1].offsetTop + PEEK * lh : Infinity
      cap.style.maxHeight = Math.min(para, limit(lh)) + 'px'
    }
    const set = (clamped) => {
      if (clamped) {
        cap.classList.add('is-clamped')
        clamp()
      } else {
        cap.classList.remove('is-clamped')
        cap.style.maxHeight = ''
      }
      btn.textContent = clamped ? 'Read more' : 'Show less'
      btn.setAttribute('aria-expanded', String(!clamped))
    }
    btn.addEventListener('click', () => {
      const opening = cap.classList.contains('is-clamped')
      set(!opening)
      // closing from far down the caption: bring the collection back into view
      if (!opening && section.getBoundingClientRect().top < 0) section.scrollIntoView()
    })
    set(true)
    caps.push(clamp)
  })
  if (caps.length) {
    // Line breaks move with the width, and again when the web font arrives.
    // Height-only resizes (the mobile URL bar) are ignored.
    let lastW = window.innerWidth
    window.addEventListener('resize', () => {
      if (window.innerWidth === lastW) return
      lastW = window.innerWidth
      caps.forEach((f) => f())
    })
    if (document.fonts) document.fonts.ready.then(() => caps.forEach((f) => f()))
  }

  // The collections menu: one line that scrolls sideways when the titles don't
  // fit, fading whichever edge has more. A mouse wheel scrolls it sideways too
  // (trackpads already do), but hands the page back at either end.
  const menu = document.querySelector('.place-menu')
  if (!menu) return
  const edges = () => {
    const max = menu.scrollWidth - menu.clientWidth
    menu.classList.toggle('more-left', menu.scrollLeft > 2)
    menu.classList.toggle('more-right', menu.scrollLeft < max - 2)
  }
  menu.addEventListener('scroll', edges, { passive: true })
  window.addEventListener('resize', edges)
  menu.addEventListener('wheel', (e) => {
    if (Math.abs(e.deltaX) >= Math.abs(e.deltaY)) return
    const max = menu.scrollWidth - menu.clientWidth
    if (max <= 0) return
    if ((e.deltaY < 0 && menu.scrollLeft <= 0) || (e.deltaY > 0 && menu.scrollLeft >= max)) return
    e.preventDefault()
    menu.scrollLeft += e.deltaY
  }, { passive: false })
  edges()
})()
