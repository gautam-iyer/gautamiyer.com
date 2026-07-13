// Sort + filter for tile grids (Collections, Places). A [data-tilegrid] holds
// the tiles; its [data-tilecontrols="<grid id>"] bar holds <select>s:
//   data-role="sort"   value = comma-separated dataset keys ("i" = original order)
//   data-role="filter" data-key=<dataset key>; value "" = all,
//                      "__multiple" = tiles flagged data-multi, else membership
//                      in the tile's pipe-delimited dataset[key].
(function () {
  document.querySelectorAll('[data-tilegrid]').forEach((grid) => {
    const controls = document.querySelector('[data-tilecontrols="' + grid.id + '"]');
    if (!controls) return;

    let tiles = Array.from(grid.children);
    // Camera priority: tiles flagged data-oldcam (majority old-camera content)
    // are stable-partitioned to the end of the DEFAULT order before it is
    // memorized as "original" — explicit A–Z/state sorts are untouched.
    tiles = tiles.filter((t) => !t.dataset.oldcam).concat(tiles.filter((t) => t.dataset.oldcam));
    tiles.forEach((t) => grid.appendChild(t));
    tiles.forEach((t, i) => (t.dataset.i = i)); // remember original order
    const sortSel = controls.querySelector('[data-role="sort"]');
    const filterSels = Array.from(controls.querySelectorAll('[data-role="filter"]'));

    function apply() {
      filterSels.forEach((sel) => {
        const key = sel.dataset.key;
        const val = sel.value;
        tiles.forEach((t) => {
          let show = true;
          if (val === '__multiple') show = t.dataset.multi === '1';
          else if (val) show = (t.dataset[key] || '').split('|').includes(val);
          if (!show) t.style.display = 'none';
          else if (t.style.display === 'none') t.style.display = '';
        });
      });
      // (single filter today; if multiple ever added, intersect instead)

      if (sortSel) {
        const keys = sortSel.value.split(',');
        tiles.slice().sort((a, b) => {
          for (const k of keys) {
            if (k === 'i') { const d = (+a.dataset.i) - (+b.dataset.i); if (d) return d; continue; }
            const av = (a.dataset[k] || '').toLowerCase();
            const bv = (b.dataset[k] || '').toLowerCase();
            if (av < bv) return -1;
            if (av > bv) return 1;
          }
          return 0;
        }).forEach((t) => grid.appendChild(t));
      }
    }

    [sortSel, ...filterSels].forEach((s) => s && s.addEventListener('change', apply));
    apply();
  });
})();
