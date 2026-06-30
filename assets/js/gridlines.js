// Darkens specific lines of the background grid (rather than adding new ones).
// Any [data-darkline] element marks the grid row at its top to be darkened;
// [data-darkline="both"] also darkens the row at its bottom. Each dark line is
// drawn at an EXACT grid multiple (from the same Y=0 origin as the body grid),
// so it sits precisely on an existing faint grid line — it reads as that line
// darkened. Lines live in one absolute overlay behind the content.
(function () {
  var targets = document.querySelectorAll('[data-darkline]');
  if (!targets.length) return;
  var GRID = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--grid'), 10) || 40;

  var overlay = document.createElement('div');
  overlay.className = 'gridlines';
  document.body.appendChild(overlay);

  // row -> width type. "full" spans the whole grid (section dividers);
  // "content" spans only the content column (chip lines, matching the hero +
  // colored collection rules). "full" wins if a row is marked both ways.
  function mark(rows, row, type) {
    var cur = rows.get(row);
    rows.set(row, cur === 'full' || type === 'full' ? 'full' : 'content');
  }

  var content = document.querySelector('main');

  function draw() {
    overlay.style.height = document.documentElement.scrollHeight + 'px';
    // Content-width lines align to the actual content column (same left edge as
    // the hero, collections, headings and chip text) rather than a fixed gutter,
    // so they stay aligned regardless of scrollbar width.
    var cl = content ? content.getBoundingClientRect() : null;
    var rows = new Map();
    targets.forEach(function (el) {
      var r = el.getBoundingClientRect();
      var top = r.top + window.scrollY;
      var both = el.dataset.darkline === 'both';
      var type = both ? 'content' : 'full';
      mark(rows, Math.round(top / GRID), type); // snap to the nearest grid row
      if (both) mark(rows, Math.round((top + r.height) / GRID), type);
    });
    overlay.innerHTML = '';
    rows.forEach(function (type, row) {
      var ln = document.createElement('div');
      ln.className = 'gridline-dark';
      ln.style.top = (row * GRID) + 'px';
      if (type === 'content' && cl) {
        ln.style.left = (cl.left + window.scrollX) + 'px';
        ln.style.right = 'auto';
        ln.style.width = cl.width + 'px';
      }
      overlay.appendChild(ln);
    });
  }

  draw();
  window.addEventListener('load', draw);
  var rt;
  window.addEventListener('resize', function () { clearTimeout(rt); rt = setTimeout(draw, 150); });
})();
