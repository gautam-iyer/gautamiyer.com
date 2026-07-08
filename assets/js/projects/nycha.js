/* The Architecture of NYCHA — page charts.
   Source: NYCHA Development Data Book (Jan 2025 vintage), pivoted by
   completion era; development-level scatter for the regressions.
   Regenerate the data literals from the workbook via
   scripts/nycha_extract.py. */
(function () {
  var SC = window.SiteCharts;
  if (!SC) return;
  var PAL = SC.palette, INK = SC.ink;
  var BLUE = PAL[0], GOLD = PAL[1], TERRA = PAL[3];

  /* ---------- data (from the Pivots sheet; eras = completion half-decades) ---------- */
  var ERAS = ['1935-1940', '1940-1945', '1945-1950', '1950-1955', '1955-1960', '1960-1965', '1965-1970', '1970-1975', '1975-1980', '1980-1985', '1985-1990', '1990-1995', '1995-2000', '2000-2005', '2005-2010'];
  var APTS = [6272, 11601, 13469, 41682, 37263, 23205, 20998, 12970, 3808, 3616, 5484, 1589, 644, 13, 51];
  var APT_PER_BLDG = [72.8, 81.5, 92.3, 88.6, 100.7, 128.1, 137.9, 117.9, 98.8, 96.3, 57.2, 20.9, 27.8, 13, 50];
  var SITE_ACRES = [16.54, 13.66, 13.26, 18.14, 18.14, 7.85, 3.94, 2.36, 1.89, 3.23, 1.88, 1.05, 0.99, 0.11, 0.59];
  var COVER_ACRES = [4.47, 3.21, 2.82, 3.09, 2.82, 1.23, 0.69, 0.65, 0.63, 0.86, 0.72, 0.53, 0.42, 0.08, null];
  var PER_ROOM = [2290, 1234, 2279, 2619, 3232, 3923, 4785, 7174, 7476, 13929, 17313, 21072, 22819, 68595, 51149];

  // [completion year, stories, development, borough] — new construction only
  var DEV = /*__DATA__*/[[1936.33,4.5,"First Houses","Manhattan"],[1937.75,4.5,"Harlem River","Manhattan"],[1938.25,4,"Williamsburg","Brooklyn"],[1939.83,4,"Red Hook East","Brooklyn"],[1939.83,4,"Red Hook I","Brooklyn"],[1940.17,6,"Queensbridge North","Queens"],[1940.17,6,"Queensbridge South","Queens"],[1940.58,3.5,"South Jamaica I","Queens"],[1940.75,6,"Vladeck Ii","Manhattan"],[1940.83,6,"Vladeck","Manhattan"],[1941.33,9,"East River","Manhattan"],[1941.75,6,"Kingsborough","Brooklyn"],[1941.92,2,"Clason Point Gardens","Bronx"],[1944.08,8.5,"Ingersoll","Brooklyn"],[1944.08,9.5,"Whitman","Brooklyn"],[1947.5,11.5,"Elliott","Manhattan"],[1948.25,5.333333333333333,"Brownsville","Brooklyn"],[1948.92,9.5,"Amsterdam","Manhattan"],[1948.92,10,"Lincoln","Manhattan"],[1948.92,14,"Johnson","Manhattan"],[1949.0,6,"Marcy","Brooklyn"],[1949.0,11,"Riis","Manhattan"],[1949.0,11,"Riis Ii","Manhattan"],[1949.42,9.2,"Gowanus","Brooklyn"],[1949.75,12.5,"Wald","Manhattan"],[1949.92,6,"Woodside","Queens"],[1950.17,6,"South Beach","Staten Island"],[1950.42,6,"Pelham Parkway","Bronx"],[1950.42,6,"Todt Hill","Staten Island"],[1950.42,7.5,"Eastchester Gardens","Bronx"],[1950.5,6,"Glenwood","Brooklyn"],[1950.58,6,"Sheepshead Bay","Brooklyn"],[1950.75,6,"Berry","Staten Island"],[1950.75,14,"Albany","Brooklyn"],[1950.83,14,"Gun Hill","Bronx"],[1950.92,6,"Nostrand","Brooklyn"],[1950.92,9.5,"Patterson","Bronx"],[1951.08,6,"Ocean Bay Apartments (Oceanside)","Queens"],[1951.08,14,"Bronx River","Bronx"],[1951.17,10,"Boulevard","Brooklyn"],[1951.17,14,"Lexington","Manhattan"],[1951.17,14.5,"Sedgwick","Bronx"],[1951.25,14,"Dyckman","Manhattan"],[1951.42,10.5,"Parkside","Bronx"],[1951.5,6.5,"Ravenswood","Queens"],[1951.75,14,"Rangel","Manhattan"],[1951.83,6.5,"Astoria","Queens"],[1952.17,14.5,"Marble Hill","Bronx"],[1952.33,10,"Bland","Queens"],[1952.33,14,"Farragut","Brooklyn"],[1952.42,6,"Pomonok","Queens"],[1952.42,14,"Melrose","Bronx"],[1952.83,5,"Breukelen","Brooklyn"],[1953.25,17,"Smith","Manhattan"],[1953.42,7,"Cooper Park","Brooklyn"],[1953.75,8.5,"Edenwald","Bronx"],[1953.83,5,"Throggs Neck","Bronx"],[1954.42,7,"Gravesend","Brooklyn"],[1954.42,13.5,"Highbridge Gardens","Bronx"],[1954.67,4.5,"Mariner's Harbor","Staten Island"],[1954.67,14,"Saint Nicholas","Manhattan"],[1954.75,5,"South Jamaica Ii","Queens"],[1954.75,7,"Soundview","Bronx"],[1954.83,13.5,"King Towers","Manhattan"],[1955.08,7,"Sotomayor Houses","Bronx"],[1955.25,7,"Hammel","Queens"],[1955.33,7,"Cypress Hills","Brooklyn"],[1955.33,7.666666666666667,"Red Hook West","Brooklyn"],[1955.33,8.5,"Red Hook Ii","Brooklyn"],[1955.33,8.5,"Van Dyke I","Brooklyn"],[1955.58,7,"Brevoort","Brooklyn"],[1955.92,10,"Howard","Brooklyn"],[1956.42,8,"Bay View","Brooklyn"],[1956.83,11,"Forest","Bronx"],[1957.08,13.5,"Albany Ii","Brooklyn"],[1957.08,14,"Coney Island","Brooklyn"],[1957.58,16,"La Guardia","Manhattan"],[1957.67,9.333333333333334,"Washington","Manhattan"],[1957.75,17,"Grant","Manhattan"],[1958.08,10.5,"Carver","Manhattan"],[1958.08,11.5,"Marlboro","Brooklyn"],[1958.33,9.5,"Sumner","Brooklyn"],[1958.42,11.5,"Wagner","Manhattan"],[1958.5,11,"Linden","Brooklyn"],[1958.67,12.6,"Douglass I","Manhattan"],[1958.67,13.5,"Douglass","Manhattan"],[1958.67,15.2,"Douglass Ii","Manhattan"],[1959.25,21,"Saint Mary's Park","Bronx"],[1959.33,16,"Mill Brook","Bronx"],[1959.58,6.5,"Redfern","Queens"],[1959.58,11.333333333333334,"Baruch","Manhattan"],[1959.58,11.333333333333334,"Jefferson","Manhattan"],[1959.67,8,"Pink","Brooklyn"],[1960.25,16.5,"Bushwick","Brooklyn"],[1960.42,19,"Hylan","Brooklyn"],[1960.92,16,"Castle Hill","Bronx"],[1961.25,8,"Baisley Park","Queens"],[1961.42,16,"Tilden","Brooklyn"],[1961.42,20,"Manhattanville","Manhattan"],[1961.42,20,"Wilson","Manhattan"],[1961.67,8,"Ocean Bay Apartments (Bayside)","Queens"],[1961.83,12.333333333333334,"Monroe","Bronx"],[1962.0,16,"Mill Brook Extension","Bronx"],[1962.25,20,"Audubon","Manhattan"],[1962.33,4.5,"Stapleton","Staten Island"],[1962.5,16,"Lafayette","Brooklyn"],[1962.5,16,"Mckinley","Bronx"],[1962.92,8,"West Brighton I","Staten Island"],[1962.92,19,"Taft","Manhattan"],[1963.33,16,"Morrisania","Bronx"],[1963.5,16,"Jackson","Bronx"],[1963.75,6,"Baychester","Bronx"],[1963.83,20,"Lehman Village","Manhattan"],[1964.17,20,"Moore","Bronx"],[1964.17,20,"Murphy","Bronx"],[1964.25,8,"Richmond Terrace","Staten Island"],[1964.25,17.5,"Williams Plaza","Brooklyn"],[1964.25,20,"Gompers","Manhattan"],[1964.33,21,"Chelsea","Manhattan"],[1964.5,12,"Tompkins","Brooklyn"],[1964.58,18,"Adams","Bronx"],[1964.67,15.666666666666666,"Roosevelt I","Brooklyn"],[1964.92,21,"Butler","Bronx"],[1965.0,19,"Wise Towers","Manhattan"],[1965.0,19.5,"Straus","Manhattan"],[1965.17,15.5,"Fulton","Manhattan"],[1965.17,17,"131 Saint Nicholas Avenue","Manhattan"],[1965.17,20,"Rutgers","Manhattan"],[1965.17,21,"Mott Haven","Bronx"],[1965.42,16,"Douglass Addition","Manhattan"],[1965.5,24,"Isaacs","Manhattan"],[1965.58,18,"Morris I","Bronx"],[1965.58,18,"Morris Ii","Bronx"],[1965.58,20,"830 Amsterdam Avenue","Manhattan"],[1965.67,9,"Wsur (Site A) 120 West 94th Street","Manhattan"],[1965.67,18,"Wsur (Site C) 589 Amsterdam Avenue","Manhattan"],[1965.67,21,"Drew-Hamilton","Manhattan"],[1965.67,21,"Webster","Bronx"],[1965.67,22,"Wsur (Site B) 74 West 92nd Street","Manhattan"],[1965.75,13.5,"Clinton","Manhattan"],[1965.75,15,"Harlem River Ii","Manhattan"],[1965.75,21,"Independence","Brooklyn"],[1966.08,18.666666666666668,"Mitchel","Bronx"],[1966.92,14.5,"Roosevelt Ii","Brooklyn"],[1966.92,16,"Saratoga Village","Brooklyn"],[1966.92,21,"Wyckoff Gardens","Brooklyn"],[1967.17,11,"Carleton Manor","Queens"],[1967.33,24,"303 Vernon Avenue","Brooklyn"],[1967.92,17.5,"Low Houses","Brooklyn"],[1968.17,14,"Ocean Hill Apartments","Brooklyn"],[1968.25,17.333333333333332,"Glenmore Plaza","Brooklyn"],[1968.42,22,"Hughes Apartments","Brooklyn"],[1968.42,30,"Polo Grounds Towers","Manhattan"],[1969.17,22,"De Hostos Apartments","Manhattan"],[1969.25,15.5,"Boston Secor","Bronx"],[1969.25,25,"Holmes Towers","Manhattan"],[1969.42,6,"335 East 111th Street","Manhattan"],[1969.42,14.5,"Surfside Gardens","Brooklyn"],[1969.67,2,"Fenimore-Lefferts","Brooklyn"],[1969.92,15.5,"O'Dwyer Gardens","Brooklyn"],[1970.17,6,"Park Avenue-East 122nd, 123rd Streets","Manhattan"],[1970.67,10,"Latimer Gardens","Queens"],[1970.83,16,"Carey Gardens","Brooklyn"],[1970.92,6,"1471 Watson Avenue","Bronx"],[1970.92,6,"Hoe Avenue-East 173rd Street","Bronx"],[1971.17,21,"1010 East 178th Street","Bronx"],[1971.17,26,"344 East 28th Street","Manhattan"],[1971.33,6,"Eagle Avenue-East 163rd Street","Bronx"],[1971.58,8.666666666666666,"Metro North Plaza","Manhattan"],[1971.58,17,"Hernandez","Manhattan"],[1971.67,6,"Teller Avenue-East 166th Street","Bronx"],[1971.67,9.5,"Throggs Neck Addition","Bronx"],[1971.75,4,"Fiorentino Plaza","Brooklyn"],[1972.58,4,"Stuyvesant Gardens I","Brooklyn"],[1972.58,6,"572 Warren Street","Brooklyn"],[1972.58,6,"Bryant Avenue-East 174th Street","Bronx"],[1972.67,12,"Pennsylvania Avenue-Wortman Avenue","Brooklyn"],[1972.75,4,"104-14 Tapscott Street","Brooklyn"],[1973.33,3.5,"Armstrong I","Brooklyn"],[1973.33,8,"Robinson","Manhattan"],[1973.33,9.75,"Betances I","Bronx"],[1973.33,18,"Coney Island I (Site 1B)","Brooklyn"],[1973.33,20,"Bailey Avenue-West 193rd Street","Bronx"],[1973.5,4,"Betances Ii, 9A","Bronx"],[1973.5,5,"Betances Ii, 18","Bronx"],[1973.5,6,"Betances Ii, 13","Bronx"],[1973.58,8,"Davidson","Bronx"],[1973.58,12.5,"East 152nd Street-Courtlandt Avenue","Bronx"],[1973.67,6,"Unity Plaza (Sites 4-27)","Brooklyn"],[1973.67,10,"East 180th Street-Monterey Avenue","Bronx"],[1973.75,23,"Seward Park Extension","Manhattan"],[1973.83,6,"Unity Plaza (Sites 17,24,25A)","Brooklyn"],[1973.83,13,"Beach 41st Street-Beach Channel Drive","Queens"],[1973.92,3.5,"Betances Iv","Bronx"],[1973.92,14,"Coney Island I (Site 8)","Brooklyn"],[1974.0,27,"Amsterdam Addition","Manhattan"],[1974.25,4.5,"Weeksville Gardens","Brooklyn"],[1974.33,7,"Bracetti Plaza","Manhattan"],[1974.42,11,"Taylor Street-Wythe Avenue","Brooklyn"],[1974.5,14,"45 Allen Street","Manhattan"],[1974.5,17,"Coney Island I (Sites 4 & 5)","Brooklyn"],[1974.67,16,"Twin Parks West (Sites 1 & 2)","Bronx"],[1974.75,4,"Armstrong Ii","Brooklyn"],[1974.83,21,"Fort Independence Street-Heath Avenue","Bronx"],[1975.08,7,"Borinquen Plaza I","Brooklyn"],[1975.08,7.333333333333333,"Garvey (Group A)","Brooklyn"],[1975.25,26,"Two Bridges Ura (Site 7)","Manhattan"],[1975.92,7,"Borinquen Plaza Ii","Brooklyn"],[1976.17,3,"East New York City Line","Brooklyn"],[1976.25,31,"Atlantic Terminal Site 4B","Brooklyn"],[1977.42,14.5,"Harborview Terrace","Manhattan"],[1981.0,23.666666666666668,"Morrisania Air Rights","Bronx"],[1981.58,10.5,"Hope Gardens","Brooklyn"],[1983.25,13,"Campos Plaza Ii","Manhattan"],[1984.5,3,"Bushwick Ii (Groups A & C)","Brooklyn"],[1984.5,3,"Bushwick Ii (Groups B & D)","Brooklyn"],[1986.08,3,"Belmont-Sutter Area","Brooklyn"],[1986.92,3,"Bushwick Ii Cda (Group E)","Brooklyn"],[1986.92,5,"Claremont Parkway-Franklin Avenue","Bronx"],[1987.25,3,"Stebbins Avenue-Hewitt Place","Bronx"],[1987.75,3,"East 165th Street-Bryant Avenue","Bronx"],[1987.75,3,"East 173rd Street-Vyse Avenue","Bronx"],[1988.33,3,"South Bronx Area (Site 402)","Bronx"],[1988.42,6.5,"Lower East Side I Infill","Manhattan"],[1988.58,3,"Howard Avenue","Brooklyn"],[1988.67,3,"Union Avenue-East 166th Street","Bronx"],[1988.83,3,"Lower East Side Ii","Manhattan"],[1994.58,3,"Howard Avenue-Park Place","Brooklyn"],[1995.67,4.5,"Berry Street-South 9th Street","Brooklyn"],[1996.17,7,"154 West 84th Street","Manhattan"],[1997.25,4,"Lower East Side Iii","Manhattan"],[1997.42,3,"Marcy Avenue-Greene Avenue Site A","Brooklyn"],[1997.42,3,"Marcy Avenue-Greene Avenue Site B","Brooklyn"],[2003.92,6,"Stanton Street","Manhattan"],[2005.33,6,"Pss Grandparent Family Apartments","Bronx"]];

  var eraStart = ERAS.map(function (e) { return e.slice(0, 4); });
  function eraTip(items) { return ERAS[items[0].dataIndex].replace('-', '–'); }
  function fig(id) { return document.getElementById(id); }
  function ctx(id) { var el = fig(id); return el && el.querySelector('canvas'); }
  function fmt(v) { return v.toLocaleString('en-US'); }

  var eraXTick = function (v, i) { return i % 2 === 0 ? eraStart[i] : null; };

  /* ---------- fig 1: apartments completed per era ---------- */
  if (ctx('fig-waves')) {
    SC.column(ctx('fig-waves'), {
      labels: eraStart, data: APTS, xTick: eraXTick, yTick: fmt,
      tipTitle: eraTip, tipLabel: function (c) { return fmt(c.parsed.y) + ' apartments completed'; }
    });
    SC.table(fig('fig-waves'), ['Completed', 'Apartments'], ERAS.map(function (e, i) { return [e.replace('-', '–'), APTS[i]]; }));
  }

  /* ---------- fig 2: stories vs completion year — piecewise OLS ---------- */
  if (ctx('fig-stories')) {
    var BREAK = 1971;
    var up = DEV.filter(function (p) { return p[0] < BREAK; });
    var down = DEV.filter(function (p) { return p[0] >= BREAK; });
    var mUp = SC.ols(up), mDown = SC.ols(down);

    function seg(m, x0, x1) {
      var xs = [];
      for (var x = x0; x <= x1; x += 0.5) xs.push(x);
      return {
        fit: xs.map(function (x) { return { x: x, y: m.predict(x) }; }),
        lo: xs.map(function (x) { return { x: x, y: m.band(x)[0] }; }),
        hi: xs.map(function (x) { return { x: x, y: m.band(x)[1] }; })
      };
    }
    function bandSets(s) {
      return [
        { type: 'line', data: s.lo, borderWidth: 0, pointRadius: 0, pointHitRadius: 0, order: 3 },
        { type: 'line', data: s.hi, fill: '-1', backgroundColor: SC.alpha(TERRA, 0.1), borderWidth: 0, pointRadius: 0, pointHitRadius: 0, order: 3 },
        { type: 'line', data: s.fit, borderColor: TERRA, borderWidth: 2, pointRadius: 0, pointHitRadius: 0, order: 2 }
      ];
    }
    var sUp = seg(mUp, 1935, 1970.9), sDown = seg(mDown, 1971, 2006);

    new Chart(ctx('fig-stories'), {
      data: {
        datasets: bandSets(sUp).concat(bandSets(sDown), [{
          type: 'scatter',
          data: DEV.map(function (p) { return { x: p[0], y: p[1], name: p[2], boro: p[3] }; }),
          backgroundColor: BLUE,
          pointRadius: 4, pointHoverRadius: 6,
          pointBorderColor: INK.surface, pointBorderWidth: 1.5,
          order: 1
        }])
      },
      options: {
        plugins: {
          legend: { display: false },
          tooltip: {
            filter: function (item) { return item.dataset.type === 'scatter'; },
            callbacks: {
              title: function (items) { return items.length ? items[0].raw.name : ''; },
              label: function (c) {
                return (c.raw.boro ? c.raw.boro + ' · ' : '') + Math.floor(c.parsed.x) + ' · ' + c.parsed.y + ' stories';
              }
            }
          }
        },
        scales: {
          x: { type: 'linear', min: 1933, max: 2008, grid: { display: false }, border: { color: INK.axis }, ticks: { stepSize: 10, callback: function (v) { return v; } } },
          y: { min: 0, suggestedMax: 32, title: { display: true, text: 'Stories', color: INK.soft, font: { size: 11 } }, border: { display: false } }
        }
      }
    });
    SC.table(fig('fig-stories'), ['Development', 'Borough', 'Completed', 'Stories'],
      DEV.map(function (p) { return [p[2], p[3], Math.floor(p[0]), p[1]]; }));

    var el = document.getElementById('fig-stories-model');
    if (el) {
      function row(label, m) {
        return '<tr><td>' + label + '</td><td>' + (m.slope >= 0 ? '+' : '') + m.slope.toFixed(2) +
          '</td><td>' + m.seSlope.toFixed(3) + '</td><td>' + m.pSlope + '</td><td>' + m.r2.toFixed(2) +
          '</td><td>' + m.n + '</td></tr>';
      }
      el.innerHTML =
        '<div class="dp-model-caption">OLS &mdash; <em>stories ~ completion year</em>, fitted separately around 1970</div>' +
        '<table><thead><tr><th></th><th>Stories / yr</th><th>Std. error</th><th>p</th><th>R&sup2;</th><th>n</th></tr></thead><tbody>' +
        row('1936–1970', mUp) + row('1971–2005', mDown) +
        '</tbody></table>' +
        '<p class="dp-model-read">The average new development gained ' + Math.round(mUp.slope * 10) +
        ' stories per decade for thirty-five years, then shed ' + Math.abs(mDown.slope * 10).toFixed(0) +
        ' per decade after 1970.</p>';
    }
  }

  /* ---------- fig 3: the shrinking superblock (avg site vs building footprint) ---------- */
  if (ctx('fig-footprint')) {
    function lineSet(label, data, color) {
      return {
        label: label, data: data,
        borderColor: color, backgroundColor: color,
        borderWidth: 2, borderJoinStyle: 'round', borderCapStyle: 'round',
        cubicInterpolationMode: 'monotone', spanGaps: true,
        pointRadius: 0, pointHoverRadius: 5,
        pointHoverBorderColor: INK.surface, pointHoverBorderWidth: 2
      };
    }
    new Chart(ctx('fig-footprint'), {
      type: 'line',
      data: {
        labels: eraStart,
        datasets: [
          lineSet('Site area', SITE_ACRES, BLUE),
          lineSet('Building coverage', COVER_ACRES, GOLD)
        ]
      },
      options: {
        crosshair: true,
        endLabels: true,
        layout: { padding: { right: 118 } },
        interaction: { mode: 'index', intersect: false },
        plugins: {
          tooltip: {
            displayColors: true, usePointStyle: true, boxWidth: 7, boxHeight: 7,
            callbacks: {
              title: eraTip,
              label: function (c) { return ' ' + c.dataset.label + ': ' + c.parsed.y + ' acres'; }
            }
          }
        },
        scales: {
          x: { grid: { display: false }, border: { color: INK.axis }, ticks: { maxRotation: 0, autoSkip: false, callback: eraXTick } },
          y: { border: { display: false }, title: { display: true, text: 'Acres (average per development)', color: INK.soft, font: { size: 11 } } }
        }
      }
    });
    SC.table(fig('fig-footprint'), ['Completed', 'Avg site (acres)', 'Avg building coverage (acres)'],
      ERAS.map(function (e, i) { return [e.replace('-', '–'), SITE_ACRES[i] == null ? '—' : SITE_ACRES[i], COVER_ACRES[i] == null ? '—' : COVER_ACRES[i]]; }));
  }

  /* ---------- fig 4: apartments per building ---------- */
  if (ctx('fig-scale')) {
    SC.column(ctx('fig-scale'), {
      labels: eraStart, data: APT_PER_BLDG, xTick: eraXTick,
      tipTitle: eraTip, tipLabel: function (c) { return c.parsed.y + ' apartments per building (avg)'; }
    });
    SC.table(fig('fig-scale'), ['Completed', 'Apartments per building (avg)'],
      ERAS.map(function (e, i) { return [e.replace('-', '–'), APT_PER_BLDG[i]]; }));
  }

  /* ---------- fig 5: construction cost per rental room ---------- */
  if (ctx('fig-cost')) {
    SC.column(ctx('fig-cost'), {
      labels: eraStart, data: PER_ROOM, xTick: eraXTick,
      yTick: function (v) { return '$' + fmt(v); },
      tipTitle: eraTip, tipLabel: function (c) { return '$' + fmt(c.parsed.y) + ' per rental room (avg, nominal)'; }
    });
    SC.table(fig('fig-cost'), ['Completed', 'Avg cost per rental room (nominal $)'],
      ERAS.map(function (e, i) { return [e.replace('-', '–'), PER_ROOM[i]]; }));
  }
})();
