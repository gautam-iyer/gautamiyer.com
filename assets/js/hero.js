// Home hero: swap the server-rendered default for a random image of the right
// orientation (landscape on wide screens, portrait on narrow ones). The set is
// the `home-hero` collection, embedded as window.HERO_IMAGES.
(function () {
  const pic = document.querySelector('.hero-pic');
  const imgs = window.HERO_IMAGES;
  if (!pic || !Array.isArray(imgs) || imgs.length === 0) return;

  const portrait = window.matchMedia('(max-width: 700px)').matches;
  const wanted = imgs.filter((x) => (portrait ? x.ar < 1 : x.ar >= 1));
  const pool = wanted.length ? wanted : imgs;
  const pick = pool[Math.floor(Math.random() * pool.length)];

  const media = pic.closest('.hero-media');
  if (media && pick.ar) media.style.aspectRatio = pick.ar; // box matches image → no crop
  const source = pic.querySelector('source');
  const img = pic.querySelector('img');
  if (source && pick.avif) source.srcset = pick.avif;
  if (img) img.src = pick.webp || pick.avif;
})();
