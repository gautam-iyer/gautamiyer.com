/* Site-wide chart theme + helpers, layered on the vendored Chart.js
   (assets/js/vendor/chart.umd.js — load it first via asset-js.html).

   CHART PALETTE: chart-tuned variants of the hugo.toml accent palette, same
   five hue families in the same order (steel becomes teal — a neutral gray
   can't carry series identity). Validated for lightness band, chroma floor,
   colorblind separation (all-pairs) and 3:1 contrast on white.
   Blue, gold, teal, terracotta, purple: */
window.SiteCharts = (function () {
  if (typeof Chart === 'undefined') return null;

  var PAL = ['#2a5c9e', '#b3872a', '#0f93a8', '#c14a3e', '#ad63c4'];
  var INK = {
    text: '#333', soft: '#666', faint: '#999',
    grid: '#ececec', axis: '#ddd', surface: '#fff'
  };
  var FAMILY = getComputedStyle(document.body).fontFamily || "'Inter', sans-serif";

  /* ---- global defaults: Inter, ink-token text, recessive hairline grid ---- */
  var D = Chart.defaults;
  D.font.family = FAMILY;
  D.font.size = 12;
  D.color = INK.soft;
  D.borderColor = INK.grid;
  D.animation = { duration: 300 };
  D.maintainAspectRatio = false;
  D.plugins.legend.position = 'top';
  D.plugins.legend.align = 'start';
  D.plugins.legend.labels.usePointStyle = true;
  D.plugins.legend.labels.pointStyle = 'circle';
  D.plugins.legend.labels.boxWidth = 7;
  D.plugins.legend.labels.boxHeight = 7;
  D.plugins.legend.labels.color = INK.text;
  D.plugins.legend.labels.padding = 16;
  D.plugins.tooltip.backgroundColor = INK.surface;
  D.plugins.tooltip.titleColor = INK.text;
  D.plugins.tooltip.bodyColor = INK.soft;
  D.plugins.tooltip.borderColor = INK.axis;
  D.plugins.tooltip.borderWidth = 1;
  D.plugins.tooltip.cornerRadius = 3;
  D.plugins.tooltip.padding = 10;
  D.plugins.tooltip.titleFont = { weight: '600' };
  D.plugins.tooltip.displayColors = false;

  /* ---- crosshair: vertical hairline through the hovered x (opt-in:
     options.crosshair = true on line charts) ---- */
  Chart.register({
    id: 'siteCrosshair',
    afterDatasetsDraw: function (c) {
      if (!c.config.options.crosshair) return;
      var t = c.tooltip;
      if (!t || !t.opacity || !t.dataPoints || !t.dataPoints.length) return;
      var g = c.ctx;
      g.save();
      g.strokeStyle = INK.axis;
      g.lineWidth = 1;
      g.beginPath();
      g.moveTo(t.dataPoints[0].element.x, c.chartArea.top);
      g.lineTo(t.dataPoints[0].element.x, c.chartArea.bottom);
      g.stroke();
      g.restore();
    }
  });

  /* ---- direct end-labels for line charts (opt-in: options.endLabels = true).
     Ink text (identity comes from the line the label sits on); labels that
     would collide are skipped — the legend carries those. Reserve room with
     layout.padding.right. ---- */
  Chart.register({
    id: 'siteEndLabels',
    afterDatasetsDraw: function (c) {
      if (!c.config.options.endLabels) return;
      var ends = [];
      c.getSortedVisibleDatasetMetas().forEach(function (m) {
        var el = m.data[m.data.length - 1];
        if (el) ends.push({ x: el.x, y: el.y, label: c.data.datasets[m.index].label });
      });
      ends.sort(function (a, b) { return a.y - b.y; });
      var g = c.ctx, lastY = -1e9;
      g.save();
      g.font = '600 11px ' + FAMILY;
      g.fillStyle = INK.text;
      g.textAlign = 'left';
      g.textBaseline = 'middle';
      ends.forEach(function (e) {
        if (e.y - lastY < 13) return;
        g.fillText(e.label, e.x + 8, e.y);
        lastY = e.y;
      });
      g.restore();
    }
  });

  /* ---- value labels at bar tips (opt-in: options.barValues = true | 'max').
     'max' labels only the peak bar — selective, per the house style. ---- */
  Chart.register({
    id: 'siteBarValues',
    afterDatasetsDraw: function (c) {
      var opt = c.config.options.barValues;
      if (!opt) return;
      var horiz = c.config.options.indexAxis === 'y';
      var data = c.data.datasets[0].data;
      var peak = Math.max.apply(null, data);
      var g = c.ctx;
      g.save();
      g.font = '500 11px ' + FAMILY;
      g.fillStyle = INK.text;
      c.getDatasetMeta(0).data.forEach(function (el, i) {
        var v = data[i];
        if (v == null || (opt === 'max' && v !== peak)) return;
        var s = v.toLocaleString('en-US');
        if (horiz) {
          g.textAlign = 'left';
          g.textBaseline = 'middle';
          g.fillText(s, el.x + 6, el.y);
        } else {
          g.textAlign = 'center';
          g.textBaseline = 'bottom';
          g.fillText(s, el.x, el.y - 5);
        }
      });
      g.restore();
    }
  });

  /* ---- ordinary least squares, with enough inference for an R-style
     summary table and a 95% confidence band ---- */
  function ols(pts) {
    var n = pts.length, mx = 0, my = 0;
    pts.forEach(function (p) { mx += p[0]; my += p[1]; });
    mx /= n; my /= n;
    var sxx = 0, sxy = 0, sst = 0;
    pts.forEach(function (p) {
      sxx += (p[0] - mx) * (p[0] - mx);
      sxy += (p[0] - mx) * (p[1] - my);
      sst += (p[1] - my) * (p[1] - my);
    });
    var b1 = sxy / sxx, b0 = my - b1 * mx, sse = 0;
    pts.forEach(function (p) {
      var r = p[1] - (b0 + b1 * p[0]);
      sse += r * r;
    });
    var s2 = sse / (n - 2);
    var seB1 = Math.sqrt(s2 / sxx);
    var seB0 = Math.sqrt(s2 * (1 / n + mx * mx / sxx));
    // ~97.5th percentile of t for the df we see here (n ≥ ~30); fine for a CI band
    var tcrit = 2.0;
    function predict(x) { return b0 + b1 * x; }
    function band(x) {
      var half = tcrit * Math.sqrt(s2 * (1 / n + (x - mx) * (x - mx) / sxx));
      return [predict(x) - half, predict(x) + half];
    }
    function pFromT(t) {
      t = Math.abs(t);
      if (t > 3.3) return '< 0.001';
      // normal approximation — adequate at these sample sizes
      var p = 2 * (1 - 0.5 * (1 + erf(t / Math.SQRT2)));
      return p < 0.001 ? '< 0.001' : p.toFixed(3);
    }
    function erf(x) {
      var s = x < 0 ? -1 : 1;
      x = Math.abs(x);
      var t = 1 / (1 + 0.3275911 * x);
      var y = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
      return s * y;
    }
    return {
      n: n, slope: b1, intercept: b0,
      r2: 1 - sse / sst,
      seSlope: seB1, seIntercept: seB0,
      tSlope: b1 / seB1, tIntercept: b0 / seB0,
      pSlope: pFromT(b1 / seB1), pIntercept: pFromT(b0 / seB0),
      predict: predict, band: band
    };
  }

  /* ---- collapsible data-table view under a figure (accessibility fallback
     for every chart) ---- */
  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function table(figEl, head, rows) {
    var d = document.createElement('details');
    d.className = 'dp-tv';
    var html = '<summary>View the data as a table</summary><div class="dp-tv-scroll"><table><thead><tr>';
    head.forEach(function (h) { html += '<th>' + esc(h) + '</th>'; });
    html += '</tr></thead><tbody>';
    rows.forEach(function (r) {
      html += '<tr>';
      r.forEach(function (v) {
        html += '<td>' + (typeof v === 'number' ? v.toLocaleString('en-US') : esc(v)) + '</td>';
      });
      html += '</tr>';
    });
    html += '</tbody></table></div>';
    d.innerHTML = html;
    figEl.appendChild(d);
  }

  /* ---- the house column chart: single series, slot-1 blue, rounded caps,
     peak labeled. o: {labels, data, xTick?, yTick?, tipTitle?, tipLabel?,
     barValues?, options?} — options deep-merges last for one-off tweaks. ---- */
  function mergeDeep(dst, src) {
    Object.keys(src).forEach(function (k) {
      var v = src[k];
      if (v && typeof v === 'object' && !Array.isArray(v) && typeof dst[k] === 'object' && dst[k]) mergeDeep(dst[k], v);
      else dst[k] = v;
    });
    return dst;
  }
  function column(canvas, o) {
    var options = {
      barValues: o.barValues || 'max',
      layout: { padding: { top: 18 } },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { title: o.tipTitle, label: o.tipLabel } }
      },
      scales: {
        x: { grid: { display: false }, border: { color: INK.axis }, ticks: { maxRotation: 0, autoSkip: false, callback: o.xTick } },
        y: { border: { display: false }, ticks: { callback: o.yTick } }
      }
    };
    if (o.options) mergeDeep(options, o.options);
    return new Chart(canvas, {
      type: 'bar',
      data: {
        labels: o.labels,
        datasets: [{
          data: o.data,
          backgroundColor: PAL[0],
          maxBarThickness: 24,
          categoryPercentage: 0.8,
          borderRadius: { topLeft: 4, topRight: 4 },
          borderSkipped: 'bottom'
        }]
      },
      options: options
    });
  }

  function hexA(hex, a) {
    var v = parseInt(hex.slice(1), 16);
    return 'rgba(' + (v >> 16) + ',' + ((v >> 8) & 255) + ',' + (v & 255) + ',' + a + ')';
  }

  return { palette: PAL, ink: INK, family: FAMILY, ols: ols, table: table, column: column, alpha: hexA };
})();
