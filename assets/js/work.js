/* /work index: view toggle (All / By Series) + kind filter.
   Deep links: /work/?series=the-psychic-highway opens the series view and
   scrolls to that group; /work/?kind=Walking%20Tour pre-selects a kind.
   The old page used inline onclick handlers, which the filter needed to reach
   anyway — one listener block is both cleaner and CSP-friendlier. */
(function () {
  var all = document.getElementById('view-all');
  var series = document.getElementById('view-series');
  if (!all || !series) return;
  var btns = document.querySelectorAll('.toggle-btn');
  var kindSel = document.querySelector('[data-role="kind"]');

  function showView(view) {
    all.classList.toggle('visible', view === 'all');
    series.classList.toggle('visible', view === 'series');
    btns.forEach(function (b) { b.classList.toggle('active', b.dataset.view === view); });
  }
  btns.forEach(function (b) {
    b.addEventListener('click', function () { showView(b.dataset.view); });
  });

  /* A row appears in BOTH views, so filter by selector, not by a cached list. */
  function applyKind(kind) {
    document.querySelectorAll('.work-item').forEach(function (it) {
      it.hidden = !!kind && it.dataset.kind !== kind;
    });
    /* Hide a year or series heading whose rows have all gone. */
    document.querySelectorAll('.work-list').forEach(function (list) {
      var any = list.querySelector('.work-item:not([hidden])');
      var group = list.closest('.series-group');
      if (group) group.hidden = !any;
      else {
        list.hidden = !any;
        var label = list.previousElementSibling;
        if (label && label.classList.contains('year-label')) label.hidden = !any;
      }
    });
  }
  if (kindSel) {
    kindSel.addEventListener('change', function () { applyKind(kindSel.value); });
  }

  var q = new URLSearchParams(location.search);
  var wantSeries = q.get('series');
  var wantKind = q.get('kind');
  if (wantKind && kindSel) { kindSel.value = wantKind; applyKind(wantKind); }
  if (wantSeries) {
    showView('series');
    /* The link carries a urlize'd slug; match it back against the headings. */
    document.querySelectorAll('.series-group').forEach(function (g) {
      var name = g.querySelector('.series-name');
      if (!name) return;
      var slug = name.textContent.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
      if (slug === wantSeries) g.scrollIntoView({ block: 'start' });
    });
  }
})();
