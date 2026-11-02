/* Smart tariff running-cost calculator - heatpumpdatabase.com
   48 half-hour slots per day. All rates in pence/kWh, standing charges in pence/day. */
(function () {
  'use strict';
  var $ = function (i) { return document.getElementById(i); };
  var N = 48;
  var AGILE = [18.5,17.5,16.5,16.0,16.5,18.0,21.0,25.0,25.5,23.0,21.0,20.0,19.0,18.5,19.5,22.0,33.0,36.0,34.0,27.0,24.0,22.0,21.0,19.5];
  var HOUSE = [0.55,0.45,0.4,0.38,0.38,0.42,0.6,0.9,1.0,0.95,0.9,0.9,0.95,0.9,0.85,0.9,1.1,1.5,1.6,1.5,1.35,1.2,0.95,0.7];
  var SC = 54.83;
  var T = [
    {id:'flat', name:'Standard variable (price cap)', kind:'Flat rate', eg:'Any supplier&rsquo;s default tariff', sc:SC,
     r:{std:26.32}, lab:{std:'All day'}, b:[[0,24,'std']]},
    {id:'e7', name:'Economy 7', kind:'Two-rate', eg:'Older meters; night hours vary by region', sc:SC,
     r:{night:14.0, day:31.5}, lab:{night:'Night 00:00&ndash;07:00', day:'Day'}, b:[[0,7,'night'],[7,24,'day']]},
    {id:'cosy', name:'Three cheap windows + evening peak', kind:'Heat pump tariff', eg:'e.g. Cosy Octopus', sc:SC,
     r:{cheap:13.5, day:27.6, peak:41.4}, lab:{cheap:'Cheap 04&ndash;07, 13&ndash;16, 22&ndash;24', day:'Day', peak:'Peak 16&ndash;19'},
     b:[[0,4,'day'],[4,7,'cheap'],[7,13,'day'],[13,16,'cheap'],[16,19,'peak'],[19,22,'day'],[22,24,'cheap']]},
    {id:'disc', name:'Two discount windows, no peak', kind:'Heat pump tariff', eg:'e.g. EDF Heat Pump Tracker', sc:SC,
     r:{cheap:16.3, std:26.3}, lab:{cheap:'Cheap 04&ndash;07, 13&ndash;16', std:'Standard'},
     b:[[0,4,'std'],[4,7,'cheap'],[7,13,'std'],[13,16,'cheap'],[16,24,'std']]},
    {id:'half', name:'Half-price overnight + afternoon', kind:'Heat pump tariff', eg:'e.g. British Gas heat pump tariff', sc:SC,
     r:{cheap:13.16, std:26.32}, lab:{cheap:'Half price 00&ndash;07, 13&ndash;16', std:'Standard'},
     b:[[0,7,'cheap'],[7,13,'std'],[13,16,'cheap'],[16,24,'std']]},
    {id:'night', name:'Long overnight window + evening peak', kind:'Heat pump tariff', eg:'e.g. E.ON Next Pumped', sc:SC,
     r:{sop:16.9, op:21.3, peak:39.85}, lab:{sop:'Super off-peak 22&ndash;06', op:'Off-peak 06&ndash;16, 19&ndash;22', peak:'Peak 16&ndash;19'},
     b:[[0,6,'sop'],[6,16,'op'],[16,19,'peak'],[19,22,'op'],[22,24,'sop']]},
    {id:'aft', name:'Single afternoon window', kind:'Heat pump tariff', eg:'e.g. ScottishPower Heat Pump Saver', sc:SC,
     r:{cheap:14.0, std:26.32}, lab:{cheap:'Cheap 11&ndash;16', std:'Standard'},
     b:[[0,11,'std'],[11,16,'cheap'],[16,24,'std']]},
    {id:'ev', name:'EV tariff, 6-hour overnight window', kind:'EV tariff (eligible EV/charger needed)', eg:'e.g. Intelligent Octopus Go', sc:SC,
     r:{cheap:7.0, day:28.0}, lab:{cheap:'Cheap 23:30&ndash;05:30', day:'Day'},
     b:[[0,5.5,'cheap'],[5.5,23.5,'day'],[23.5,24,'cheap']]},
    {id:'agile', name:'Half-hourly dynamic prices', kind:'Dynamic tariff', eg:'e.g. Agile Octopus', sc:SC,
     r:{avg:22.0}, lab:{avg:'Average price (illustrative winter day shape)'}, dyn:true}
  ];
  var DEF = JSON.parse(JSON.stringify(T.map(function (t) { return {r:t.r, sc:t.sc}; })));
  T.forEach(function (t) { t.color = {}; });

  function rates(t) {
    var a = [], s, h, j;
    if (t.dyn) {
      var m = AGILE.reduce(function (x, y) { return x + y; }, 0) / 24, k = t.r.avg / m;
      for (s = 0; s < N; s++) a.push(AGILE[Math.floor(s / 2)] * k);
      return a;
    }
    for (s = 0; s < N; s++) {
      h = s / 2;
      for (j = 0; j < t.b.length; j++) if (h >= t.b[j][0] && h < t.b[j][1]) { a.push(t.r[t.b[j][2]]); break; }
    }
    return a;
  }
  function bandAt(t, s) {
    if (t.dyn) return null;
    var h = s / 2;
    for (var j = 0; j < t.b.length; j++) if (h >= t.b[j][0] && h < t.b[j][1]) return t.b[j][2];
  }
  function num(id, d) { var v = parseFloat($(id).value); return isFinite(v) ? v : d; }
  function gbp(x) { return '&pound;' + Math.round(x).toLocaleString('en-GB'); }
  function norm(a) { var s = a.reduce(function (x, y) { return x + y; }, 0); return a.map(function (x) { return x / s; }); }

  var FLOW = {35:1.0, 45:0.85, 50:0.79, 55:0.73};

  function inputs() {
    var I = {};
    I.mode = $('st-mode-gas').checked ? 'gas' : 'heat';
    if (I.mode === 'gas') {
      var g = num('st-gas', 11500), eff = num('st-eff', 85) / 100, dw = num('st-dhwpct', 20) / 100;
      I.heat = g * eff * (1 - dw); I.dhw = g * eff * dw; I.gas = g;
    } else {
      I.heat = num('st-heat', 8000); I.dhw = num('st-dhwkwh', 2000); I.gas = (I.heat + I.dhw) / 0.85;
    }
    I.scop35 = num('st-scop', 4.4);
    I.flow = parseInt($('st-flow').value, 10) || 45;
    I.scop = I.scop35 * (FLOW[I.flow] || 0.85);
    I.dcop = num('st-dcop', 2.8);
    I.house = $('st-house-on').checked ? num('st-house', 2700) : 0;
    I.shift = $('st-shift-on').checked ? num('st-shift', 30) / 100 : 0;
    I.pen = num('st-pen', 5) / 100;
    I.dhwCheap = $('st-dhw-cheap').checked;
    I.swing = $('st-diurnal').checked ? num('st-swing', 5) : 0;
    I.gasRate = num('st-gasrate', 7.97); I.gasSc = num('st-gassc', 29.68);
    return I;
  }

  function model(t, I) {
    var R = rates(t), s;
    // outdoor temperature shape: coldest around 06:00, warmest around 15:00
    var tout = [], w = [], mult = [];
    for (s = 0; s < N; s++) {
      var h = s / 2 + 0.25;
      tout.push(5 + (I.swing / 2) * Math.cos(2 * Math.PI * (h - 15) / 24));
    }
    for (s = 0; s < N; s++) { w.push(Math.max(0.5, 18 - tout[s])); mult.push(1 + 0.025 * (tout[s] - 5)); }
    w = norm(w);
    var k = 0; for (s = 0; s < N; s++) k += w[s] / mult[s];
    mult = mult.map(function (m) { return m * k; });
    var heat = w.map(function (x) { return x * I.heat; });
    // cheap slots
    var minR = Math.min.apply(null, R), cheap = [], i;
    if (t.dyn) {
      var idx = R.map(function (r, j) { return j; }).sort(function (a, b) { return R[a] - R[b]; });
      cheap = idx.slice(0, 12);
    } else {
      for (s = 0; s < N; s++) if (R[s] <= minR + 0.01) cheap.push(s);
    }
    var isCheap = {}; cheap.forEach(function (c) { isCheap[c] = 1; });
    var moved = 0;
    if (I.shift > 0 && cheap.length < N) {
      var tot = 0; for (s = 0; s < N; s++) if (!isCheap[s]) tot += heat[s];
      var target = tot * I.shift;
      var order = []; for (s = 0; s < N; s++) if (!isCheap[s]) order.push(s);
      order.sort(function (a, b) { return R[b] - R[a]; });
      for (i = 0; i < order.length && moved < target - 1e-9; i++) {
        var take = Math.min(heat[order[i]], target - moved);
        heat[order[i]] -= take; moved += take;
      }
      var add = moved * (1 + I.pen) / cheap.length;
      cheap.forEach(function (c) { heat[c] += add; });
    }
    // hot water
    var dhw = new Array(N).fill(0);
    if (I.dhwCheap) {
      var best = 0, bv = Infinity;
      for (s = 0; s < N; s++) {
        var v = 0, wt = 0;
        for (i = 0; i < 4; i++) { v += R[(s + i) % N]; wt += mult[(s + i) % N]; }
        v = v / wt;
        if (v < bv - 1e-9) { bv = v; best = s; }
      }
      for (i = 0; i < 4; i++) dhw[(best + i) % N] = I.dhw / 4;
    } else {
      [11, 12, 35, 36].forEach(function (c) { dhw[c] = I.dhw / 4; });
    }
    var hn = norm(HOUSE.concat([]).reduce(function (a, x) { a.push(x, x); return a; }, []));
    var eH = 0, eD = 0, cost = 0, houseCost = 0, prof = [];
    for (s = 0; s < N; s++) {
      var eh = heat[s] / (I.scop * mult[s]), ed = dhw[s] / (I.dcop * mult[s]), eo = hn[s] * I.house;
      eH += eh; eD += ed;
      cost += (eh + ed) * R[s] / 100; houseCost += eo * R[s] / 100;
      prof.push([eh / 365, ed / 365, eo / 365]);
    }
    var scy = t.sc * 365 / 100;
    return {t:t, R:R, kwh:eH + eD, hp:cost, house:houseCost, sc:scy, total:cost + houseCost + scy, prof:prof,
            shiftedPct:I.heat ? moved / I.heat * 100 : 0, cheapHrs:cheap.length / 2};
  }

  var sel = 'cosy', fired = false;
  function run() {
    var I = inputs();
    $('st-eff-scop').textContent = I.scop.toFixed(2);
    var res = T.map(function (t) { return model(t, I); });
    var flat = res[0];
    var sorted = res.slice().sort(function (a, b) { return a.total - b.total; });
    var max = Math.max.apply(null, res.map(function (r) { return r.total; }));
    var h = '<table class="st-tab"><thead><tr><th>Tariff</th><th class="st-r st-hide">Heat pump use</th><th class="st-r">Heating &amp; hot water</th><th class="st-r">Total bill</th><th class="st-r">vs standard</th></tr></thead><tbody>';
    sorted.forEach(function (r, i) {
      var d = r.total - flat.total;
      h += '<tr data-id="' + r.t.id + '" class="' + (r.t.id === sel ? 'on' : '') + (i === 0 ? ' best' : '') + '" tabindex="0">' +
        '<td><b>' + r.t.name + '</b>' + (i === 0 ? ' <span class="st-best">Cheapest</span>' : '') +
        '<div class="st-eg"><span class="st-hide">' + r.t.kind + ' &middot; </span>' + r.t.eg + '</div>' +
        '<div class="st-bar"><i style="width:' + (r.total / max * 100).toFixed(1) + '%"></i></div></td>' +
        '<td class="st-r st-hide">' + Math.round(r.kwh).toLocaleString('en-GB') + '&nbsp;kWh</td>' +
        '<td class="st-r">' + gbp(r.hp) + '</td>' +
        '<td class="st-r"><b>' + gbp(r.total) + '</b></td>' +
        '<td class="st-r ' + (d < -0.5 ? 'st-save' : d > 0.5 ? 'st-more' : '') + '">' + (Math.abs(d) < 0.5 ? '&ndash;' : (d < 0 ? '&minus;' : '+') + gbp(Math.abs(d))) + '</td></tr>';
    });
    h += '</tbody></table>';
    $('st-results').innerHTML = h;
    Array.prototype.forEach.call($('st-results').querySelectorAll('tr[data-id]'), function (tr) {
      var go = function () { sel = tr.getAttribute('data-id'); run(); var p = $('st-detail'); if (p && p.scrollIntoView && window.innerWidth < 760) p.scrollIntoView({behavior:'smooth', block:'start'}); };
      tr.addEventListener('click', go);
      tr.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
    });
    // gas comparison
    var best = sorted[0];
    var gasHeat = I.gas * I.gasRate / 100, gasSc = I.gasSc * 365 / 100;
    $('st-gas-out').innerHTML =
      '<div class="st-kpi"><span>Gas boiler (heating &amp; hot water)</span><b>' + gbp(gasHeat + gasSc) + '</b><em>' + gbp(gasHeat) + ' gas + ' + gbp(gasSc) + ' gas standing charge</em></div>' +
      '<div class="st-kpi"><span>Heat pump, standard tariff</span><b>' + gbp(flat.hp) + '</b><em>' + Math.round(flat.kwh).toLocaleString('en-GB') + ' kWh at ' + flat.t.r.std + 'p</em></div>' +
      '<div class="st-kpi st-kpi-g"><span>Heat pump, ' + best.t.name.toLowerCase() + '</span><b>' + gbp(best.hp) + '</b><em>' +
      (gasHeat + gasSc - best.hp >= 0 ? gbp(gasHeat + gasSc - best.hp) + ' a year less than gas' : gbp(best.hp - gasHeat - gasSc) + ' a year more than gas') +
      ' if you remove the gas meter</em></div>';
    detail(res.filter(function (r) { return r.t.id === sel; })[0] || res[0]);
    if (!fired && window.gtag) { fired = true; try { gtag('event', 'tariff_calc_run', {}); } catch (e) {} }
  }

  function ribbon(t, R) {
    R = R || rates(t);
    var mn = Math.min.apply(null, R), mx = Math.max.apply(null, R), s, h = '<div class="st-rib" aria-hidden="true">';
    var cnt = {}, mode = R[0], mc = 0;
    R.forEach(function (r) { var k = r.toFixed(2); cnt[k] = (cnt[k] || 0) + 1; if (cnt[k] > mc) { mc = cnt[k]; mode = r; } });
    for (s = 0; s < N; s++) {
      var r = R[s], c;
      if (t.dyn) {
        var f = mx > mn ? (r - mn) / (mx - mn) : 0;
        c = f < 0.15 ? '#22C79A' : f < 0.4 ? '#7FD1B2' : f < 0.6 ? '#E4E7EA' : f < 0.8 ? '#F6D38A' : '#E8836B';
      } else if (Math.abs(r - mode) < 0.01) c = '#E4E7EA';
      else if (r < mode) c = Math.abs(r - mn) < 0.01 ? '#22C79A' : '#7FD1B2';
      else c = (Math.abs(r - mx) < 0.01 && r > mode * 1.25) ? '#E8836B' : '#F6D38A';
      h += '<i style="background:' + c + '" title="' + String(Math.floor(s / 2)).padStart(2, '0') + ':' + (s % 2 ? '30' : '00') + ' ' + r.toFixed(1) + 'p"></i>';
    }
    return h + '</div><div class="st-rib-ax"><span>00</span><span>06</span><span>12</span><span>18</span><span>24</span></div>';
  }

  function detail(r) {
    var t = r.t, keys = Object.keys(t.r), h = '';
    h += '<h3>' + t.name + ' <span class="st-eg">' + t.eg + '</span></h3>' + ribbon(t, r.R);
    h += '<div class="st-edit">';
    keys.forEach(function (k) {
      h += '<label>' + t.lab[k] + ' (p/kWh)<input type="number" step="0.01" min="0" data-k="' + k + '" value="' + t.r[k] + '"></label>';
    });
    h += '<label>Standing charge (p/day)<input type="number" step="0.01" min="0" data-k="__sc" value="' + t.sc + '"></label>';
    h += '<button type="button" id="st-reset-t">Reset rates</button></div>';
    h += '<p class="st-hint">Type in the rates from your own quote or bill to see your real figure. Default rates are indicative only.</p>';
    h += chart(r);
    h += '<p class="st-hint">Average winter-day electricity by half hour (bars) and price (line). ' +
      (r.shiftedPct > 0.5 ? 'About ' + Math.round(r.shiftedPct) + '% of space heating moved into the ' + r.cheapHrs + ' cheapest hours.' : 'No heating moved: this tariff has no cheaper period.') + '</p>';
    $('st-detail').innerHTML = h;
    Array.prototype.forEach.call($('st-detail').querySelectorAll('input[data-k]'), function (inp) {
      inp.addEventListener('change', function () {
        var v = parseFloat(inp.value); if (!isFinite(v) || v < 0) return;
        if (inp.getAttribute('data-k') === '__sc') t.sc = v; else t.r[inp.getAttribute('data-k')] = v;
        run();
      });
    });
    $('st-reset-t').addEventListener('click', function () {
      var i = T.indexOf(t); t.r = JSON.parse(JSON.stringify(DEF[i].r)); t.sc = DEF[i].sc; run();
    });
  }

  function chart(r) {
    var W = 720, H = 220, L = 34, B = 24, TP = 10, RR = 40, cw = (W - L - RR) / N, s;
    var tot = r.prof.map(function (p) { return p[0] + p[1] + p[2]; });
    var ymax = Math.max.apply(null, tot) * 1.1 || 1, rmax = Math.max(45, Math.max.apply(null, r.R) * 1.1);
    var y = function (v) { return H - B - v / ymax * (H - B - TP); }, yr = function (v) { return H - B - v / rmax * (H - B - TP); };
    var g = '<svg class="st-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Daily electricity use and price by half hour">';
    for (s = 0; s <= 4; s++) {
      var yy = TP + (H - B - TP) * s / 4;
      g += '<line x1="' + L + '" x2="' + (W - RR) + '" y1="' + yy + '" y2="' + yy + '" stroke="#EEF4F1"/>';
      g += '<text x="' + (L - 4) + '" y="' + (yy + 4) + '" text-anchor="end" font-size="10" fill="#5A6A65">' + (ymax * (1 - s / 4)).toFixed(1) + '</text>';
      g += '<text x="' + (W - RR + 4) + '" y="' + (yy + 4) + '" font-size="10" fill="#8A5300">' + Math.round(rmax * (1 - s / 4)) + 'p</text>';
    }
    var cols = ['#0B6656', '#22C79A', '#B9C8C2'];
    for (s = 0; s < N; s++) {
      var base = 0;
      for (var j = 0; j < 3; j++) {
        var v = r.prof[s][j]; if (v <= 0) continue;
        g += '<rect x="' + (L + s * cw + 0.5).toFixed(1) + '" y="' + y(base + v).toFixed(1) + '" width="' + (cw - 1).toFixed(1) + '" height="' + (y(base) - y(base + v)).toFixed(1) + '" fill="' + cols[j] + '"/>';
        base += v;
      }
    }
    var pts = '';
    for (s = 0; s < N; s++) pts += (L + s * cw).toFixed(1) + ',' + yr(r.R[s]).toFixed(1) + ' ' + (L + (s + 1) * cw).toFixed(1) + ',' + yr(r.R[s]).toFixed(1) + ' ';
    g += '<polyline points="' + pts + '" fill="none" stroke="#C77700" stroke-width="2"/>';
    for (s = 0; s <= 24; s += 6) g += '<text x="' + (L + s * 2 * cw) + '" y="' + (H - 6) + '" text-anchor="middle" font-size="10" fill="#5A6A65">' + String(s).padStart(2, '0') + ':00</text>';
    g += '<text x="' + L + '" y="9" font-size="10" fill="#5A6A65">kWh</text></svg>';
    g += '<div class="st-leg"><span><i style="background:#0B6656"></i>Space heating</span><span><i style="background:#22C79A"></i>Hot water</span><span><i style="background:#B9C8C2"></i>Rest of home</span><span><i style="background:#C77700;height:3px"></i>Price</span></div>';
    return g;
  }

  // type ribbons in the overview section
  function ribbons() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-rib]'), function (el) {
      var t = T.filter(function (x) { return x.id === el.getAttribute('data-rib'); })[0];
      if (t) el.innerHTML = ribbon(t);
    });
  }

  function toggles() {
    var gas = $('st-mode-gas').checked;
    $('st-gasbox').style.display = gas ? '' : 'none';
    $('st-heatbox').style.display = gas ? 'none' : '';
    $('st-shift').disabled = $('st-pen').disabled = !$('st-shift-on').checked;
    $('st-house').disabled = !$('st-house-on').checked;
    $('st-swing').disabled = !$('st-diurnal').checked;
    $('st-shift-v').textContent = $('st-shift').value + '%';
  }

  // product picker (residential air source heat pumps with a 35 C SCOP)
  var PRODS = [];
  function picker() {
    fetch('/finder-products.json').then(function (r) { return r.json(); }).then(function (d) {
      PRODS = d.filter(function (p) { return p.t === 'ASHP' && p.a === 'Residential' && p.s; });
      var dl = $('st-plist'), o = '';
      PRODS.forEach(function (p) { o += '<option value="' + (p.m + ' ' + p.n + (p.c ? ' (' + p.c + ')' : '')).replace(/"/g, '&quot;') + '">'; });
      dl.innerHTML = o;
      var q = new URLSearchParams(location.search), id = parseInt(q.get('id'), 10);
      if (id) { var p = PRODS.filter(function (x) { return x.i === id; })[0]; if (p) choose(p); }
    }).catch(function () {});
    $('st-prod').addEventListener('change', function () {
      var v = $('st-prod').value;
      var p = PRODS.filter(function (x) { return (x.m + ' ' + x.n + (x.c ? ' (' + x.c + ')' : '')) === v; })[0];
      if (p) choose(p);
    });
  }
  function choose(p) {
    $('st-prod').value = p.m + ' ' + p.n + (p.c ? ' (' + p.c + ')' : '');
    $('st-scop').value = p.s;
    $('st-prod-note').innerHTML = 'SCOP ' + p.s + ' at 35&nbsp;&deg;C, ' + p.k + '&nbsp;kW &middot; <a href="/products/' + p.u + '/">view specs</a>';
    run();
  }

  function init() {
    if (!$('st-results')) return;
    ribbons();
    Array.prototype.forEach.call(document.querySelectorAll('#st-inputs input, #st-inputs select'), function (el) {
      if (el.id === 'st-prod') return;
      el.addEventListener('input', function () { toggles(); run(); });
      el.addEventListener('change', function () { toggles(); run(); });
    });
    toggles(); run(); picker();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
