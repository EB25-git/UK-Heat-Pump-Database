/* Cylinders & Tanks browser - mirrors the homepage Browse UI (sidebar filters, toolbar, card grid / table).
   Data: /cylinders-data.json (written by build.py). */
(function () {
  'use strict';
  var $ = function (i) { return document.getElementById(i); };
  var esc = function (v) { return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); };
  var HPSET = null, HPNAME = '';
  var D = [], F = [], view = 'grid', page = 48, STEP = 48, obs = null, sortKey = null, sortDir = 1;
  var SF = { vLo: 0, vHi: 0, hl: 0, h: 0, w: 0, wt: 0 };
  var VSTOPS = [0, 50, 100, 120, 150, 170, 180, 200, 210, 250, 300, 400, 500, 750, 1000, 1500, 2000, 3000, 5000, 100000];
  var LIM = {};
  var fmt = function (v, u) { return v == null || v === '' ? '&mdash;' : esc((typeof v === 'number' ? (Math.round(v * 100) / 100).toLocaleString('en-GB') : v)) + (u || ''); };

  function mkDual(el, vEl, onchg) {
    var n = VSTOPS.length - 1;
    el.innerHTML = '<div class="range-track"></div><div class="range-fill"></div><div class="range-thumb"></div><div class="range-thumb"></div>' +
      '<input type="range" min="0" max="' + n + '" step="1" value="0" aria-label="Minimum volume">' +
      '<input type="range" min="0" max="' + n + '" step="1" value="' + n + '" aria-label="Maximum volume">';
    var ins = el.querySelectorAll('input'), lo = ins[0], hi = ins[1], fill = el.querySelector('.range-fill'), th = el.querySelectorAll('.range-thumb');
    function upd(fire) {
      var a = Math.min(+lo.value, +hi.value), b = Math.max(+lo.value, +hi.value), pa = 5 + a / n * 90, pb = 5 + b / n * 90;
      fill.style.left = pa + '%'; fill.style.width = (pb - pa) + '%'; th[0].style.left = pa + '%'; th[1].style.left = pb + '%';
      SF.vLo = a === 0 ? 0 : VSTOPS[a]; SF.vHi = b === n ? 0 : VSTOPS[b];
      vEl.textContent = (a === 0 && b === n) ? 'Any' : VSTOPS[a] + '–' + (b === n ? VSTOPS[n - 1] + '+' : VSTOPS[b]) + ' L';
      if (fire) onchg();
    }
    [lo, hi].forEach(function (i) { i.addEventListener('input', function () { upd(true); }); i.addEventListener('focus', function () { el.classList.add('focus'); }); i.addEventListener('blur', function () { el.classList.remove('focus'); }); });
    el._reset = function () { lo.value = 0; hi.value = n; upd(false); };
    upd(false);
  }
  function mkMax(el, vEl, key, max, step, unit, onchg) {
    max = Math.round(Math.ceil(max / step) * step * 100) / 100;
    el.innerHTML = '<div class="range-track"></div><div class="range-fill"></div><div class="range-thumb"></div>' +
      '<input type="range" min="0" max="' + max + '" step="' + step + '" value="' + max + '" aria-label="' + key + ' filter">';
    var inp = el.querySelector('input'), fill = el.querySelector('.range-fill'), th = el.querySelector('.range-thumb');
    function upd(fire) {
      var v = +inp.value, p = 5 + v / max * 90;
      fill.style.left = '5%'; fill.style.width = (p - 5) + '%'; th.style.left = p + '%';
      SF[key] = v >= max ? 0 : v;
      vEl.textContent = v >= max ? 'Any' : '≤' + (Math.round(v * 100) / 100).toLocaleString('en-GB') + unit;
      if (fire) onchg();
    }
    inp.addEventListener('input', function () { upd(true); });
    inp.addEventListener('focus', function () { el.classList.add('focus'); }); inp.addEventListener('blur', function () { el.classList.remove('focus'); });
    el._reset = function () { inp.value = max; upd(false); };
    upd(false);
  }

  function val(id) { var e = $(id); return e ? e.value : ''; }
  function filter() {
    var q = val('search-input').toLowerCase(), t = val('filt-ctype'), m = val('filt-mfr'), pp = val('filt-pp'),
      ct = val('filt-coil'), erp = val('filt-erp'), pr = val('filt-price'), hb = val('filt-hpb');
    F = D.filter(function (d) {
      if (q && (d.m + ' ' + d.n + ' ' + (d.c || '') + ' ' + (d.t || '')).toLowerCase().indexOf(q) < 0) return false;
      if (t && d.t !== t) return false;
      if (m && d.m !== m) return false;
      if (pp && (d.pp || 'No') !== pp) return false;
      if (ct && d.ct !== ct) return false;
      if (erp && d.erp !== erp) return false;
      if (pr === 'priced' && d.pn == null) return false;
      if (pr === 'unpriced' && d.pn != null) return false;
      if (hb && (d.hb || []).indexOf(hb) < 0) return false;
      if (HPSET && !HPSET[d.i]) return false;
      if (SF.vLo && (d.v == null || d.v < SF.vLo)) return false;
      if (SF.vHi && (d.v == null || d.v > SF.vHi)) return false;
      if (SF.hl && (d.hl == null || d.hl > SF.hl)) return false;
      if (SF.h && (d.h == null || d.h > SF.h)) return false;
      if (SF.w && (d.w == null || d.w > SF.w)) return false;
      if (SF.wt && (d.wt == null || d.wt > SF.wt)) return false;
      return true;
    });
    var s = val('sort-select'), num = function (k, dir) { return function (a, b) { var x = a[k], y = b[k]; if (x == null) return 1; if (y == null) return -1; return (x - y) * dir; }; };
    if (sortKey) {
      F.sort(function (a, b) { var x = a[sortKey], y = b[sortKey]; if (x == null || x === '') return 1; if (y == null || y === '') return -1; return (typeof x === 'number' ? x - y : String(x).localeCompare(String(y))) * sortDir; });
    } else if (s === 'vol-asc') F.sort(num('v', 1)); else if (s === 'vol-desc') F.sort(num('v', -1));
    else if (s === 'hl-asc') F.sort(num('hl', 1)); else if (s === 'price-asc') F.sort(num('pn', 1));
    else if (s === 'hp-desc') F.sort(num('k', -1));
    else F.sort(function (a, b) { return (a.m + ' ' + a.n).localeCompare(b.m + ' ' + b.n); });
    var nAct = [t, m, pp, ct, erp, pr, hb].filter(Boolean).length + (HPSET ? 1 : 0) + (SF.vLo || SF.vHi ? 1 : 0) + ['hl', 'h', 'w', 'wt'].filter(function (k) { return SF[k]; }).length;
    var badge = $('filter-badge'); badge.style.display = nAct ? '' : 'none'; badge.textContent = nAct;
    $('clear-filters-btn').style.display = nAct ? '' : 'none';
    [].forEach.call(document.querySelectorAll('.hp-seg button'), function (b) { b.setAttribute('aria-pressed', String(b.dataset.ct === t)); });
    $('res-count').innerHTML = '<b>' + F.length.toLocaleString('en-GB') + '</b> of ' + D.length.toLocaleString('en-GB') + ' cylinders &amp; tanks';
    page = STEP; render();
  }

  function card(d) {
    var dims = [d.h, d.w].filter(function (x) { return x != null; }).map(function (x) { return x.toLocaleString('en-GB'); }).join(' &times; ');
    return '<a class="hp-card" href="/cylinders/' + d.i + '/" style="text-decoration:none;color:inherit;display:block">' +
      '<div class="hp-card-head">' + (d.lg ? '<img class="hp-card-logo" src="' + d.lg + '" alt="' + esc(d.m) + ' logo" loading="lazy" width="36" height="36">' : '') +
      '<div style="min-width:0;flex:1"><div class="hp-card-brand">' + esc(d.m) + '</div><div class="hp-card-name">' + esc(d.n) + '</div>' +
      (d.c ? '<div class="hp-card-code" style="font-size:12px;color:var(--text3);margin-top:2px">' + esc(d.c) + '</div>' : '') +
      '<div class="hp-card-badges">' + (d.t ? '<span class="badge badge-ashp">' + esc(d.t) + '</span>' : '') +
      (d.pp === 'Yes' ? '<span class="badge badge-cool">Pre-plumbed</span>' : '') +
      (d.erp ? '<span class="badge badge-ref">ErP ' + esc(d.erp) + '</span>' : '') + '</div></div></div>' +
      '<div class="hp-card-body"><div class="hp-spec-grid">' +
      '<div class="hp-spec"><div class="hp-spec-label">Volume</div><div class="hp-spec-val">' + fmt(d.v, ' L') + '</div></div>' +
      '<div class="hp-spec"><div class="hp-spec-label">Standing heat loss</div><div class="hp-spec-val acc">' + fmt(d.hl, ' kWh/24h') + '</div></div>' +
      '<div class="hp-spec"><div class="hp-spec-label">Height &times; width</div><div class="hp-spec-val">' + (dims ? dims + ' mm' : '&mdash;') + '</div></div>' +
      '<div class="hp-spec"><div class="hp-spec-label">Weight (empty)</div><div class="hp-spec-val">' + fmt(d.wt, ' kg') + '</div></div>' +
      '<div class="hp-spec"><div class="hp-spec-label">Coil rating</div><div class="hp-spec-val">' + fmt(d.cr, ' kW') + '</div></div>' +
      '<div class="hp-spec"><div class="hp-spec-label">Price (unit only)</div><div class="hp-spec-val">' + (d.p ? esc(d.p) : '&mdash;') + '</div></div>' +
      '</div></div>' +
      '<div class="hp-card-footer" style="justify-content:space-between"><span style="font-size:12px;color:var(--text3)">' +
      (d.k ? d.k + ' compatible heat pump' + (d.k === 1 ? '' : 's') : '') + '</span>' +
      '<div class="card-actions"><span class="card-act card-act-cmp">View specs &rarr;</span></div></div></a>';
  }
  function row(d) {
    var dims = [d.h, d.w, d.dp].filter(function (x) { return x != null; }).map(function (x) { return x.toLocaleString('en-GB'); }).join(' &times; ');
    return '<tr onclick="location.href=\'/cylinders/' + d.i + '/\'"><td>' + esc(d.m) + '</td><td><a href="/cylinders/' + d.i + '/">' + esc(d.n) + '</a></td><td>' + esc(d.t || '') +
      '</td><td class="mv">' + fmt(d.v, ' L') + '</td><td class="mv acc">' + fmt(d.hl) + '</td><td class="mv">' + (dims || '&mdash;') +
      '</td><td class="mv">' + fmt(d.wt, ' kg') + '</td><td class="mv">' + fmt(d.cr, ' kW') + '</td><td>' + (d.p ? esc(d.p) : '&mdash;') + '</td><td class="mv">' + (d.k || '') + '</td></tr>';
  }
  function render() {
    var grid = $('hp-grid'), tbl = $('hp-table'), empty = $('empty-browse');
    empty.style.display = F.length ? 'none' : '';
    grid.style.display = view === 'grid' && F.length ? 'grid' : 'none';
    tbl.style.display = view === 'table' && F.length ? 'block' : 'none';
    if (obs) { obs.disconnect(); obs = null; }
    var list = F.slice(0, page), more = F.length > page;
    if (view === 'grid') grid.innerHTML = list.map(card).join('') + (more ? '<div id="grid-sentinel" style="grid-column:1/-1;height:1px"></div>' : '');
    else $('hp-tbody').innerHTML = list.map(row).join('') + (more ? '<tr id="grid-sentinel"><td colspan="10"></td></tr>' : '');
    var s = $('grid-sentinel');
    if (s) { obs = new IntersectionObserver(function (e) { if (e[0].isIntersecting) { page += STEP; render(); } }, { rootMargin: '600px' }); obs.observe(s); }
  }

  function setView(v) {
    view = v; $('vbtn-grid').classList.toggle('active', v === 'grid'); $('vbtn-table').classList.toggle('active', v === 'table'); render();
  }
  function toggleFilters() { $('filter-panel').classList.toggle('open'); $('filter-toggle-btn').classList.toggle('open'); }
  function clearAll() {
    ['search-input', 'filt-ctype', 'filt-mfr', 'filt-pp', 'filt-coil', 'filt-erp', 'filt-price', 'filt-hpb'].forEach(function (id) { if ($(id)) $(id).value = ''; });
    ['sl-vol', 'sl-hl', 'sl-h', 'sl-w', 'sl-wt'].forEach(function (id) { if ($(id) && $(id)._reset) $(id)._reset(); });
    if (HPSET) { location.href = '/cylinders/'; return; }
    filter();
  }
  function opts(id, vals) { var e = $(id); vals.forEach(function (v) { var o = document.createElement('option'); o.value = v; o.textContent = v; e.appendChild(o); }); }
  function uniq(k) { var s = {}; D.forEach(function (d) { var v = d[k]; (Array.isArray(v) ? v : [v]).forEach(function (x) { if (x != null && x !== '') s[x] = 1; }); }); return Object.keys(s).sort(function (a, b) { return a.localeCompare(b, 'en', { numeric: true }); }); }
  function maxOf(k, cap) { var m = 0; D.forEach(function (d) { if (d[k] != null && d[k] > m) m = d[k]; }); return Math.min(Math.ceil(m), cap); }

  function init(data) {
    D = data;
    opts('filt-ctype', uniq('t')); opts('filt-mfr', uniq('m')); opts('filt-coil', uniq('ct')); opts('filt-erp', uniq('erp')); opts('filt-hpb', uniq('hb'));
    mkDual($('sl-vol'), $('sv-vol'), filter);
    mkMax($('sl-hl'), $('sv-hl'), 'hl', Math.max(1, Math.min(maxOf('hl', 10), 10)), 0.05, ' kWh/24h', filter);
    mkMax($('sl-h'), $('sv-h'), 'h', maxOf('h', 3000), 10, ' mm', filter);
    mkMax($('sl-w'), $('sv-w'), 'w', maxOf('w', 2000), 10, ' mm', filter);
    mkMax($('sl-wt'), $('sv-wt'), 'wt', maxOf('wt', 1000), 5, ' kg', filter);
    ['filt-ctype', 'filt-mfr', 'filt-pp', 'filt-coil', 'filt-erp', 'filt-price', 'filt-hpb', 'sort-select'].forEach(function (id) { $(id).addEventListener('change', function () { if (id === 'sort-select') sortKey = null; filter(); }); });
    $('search-input').addEventListener('input', filter);
    $('vbtn-grid').addEventListener('click', function () { setView('grid'); });
    $('vbtn-table').addEventListener('click', function () { setView('table'); });
    $('filter-toggle-btn').addEventListener('click', toggleFilters);
    $('clear-filters-btn').addEventListener('click', clearAll);
    [].forEach.call(document.querySelectorAll('.filt-mob, .filter-close'), function (b) { b.addEventListener('click', toggleFilters); });
    document.querySelector('.hp-seg').addEventListener('click', function (e) { var b = e.target.closest('button'); if (!b) return; $('filt-ctype').value = b.dataset.ct; filter(); });
    [].forEach.call(document.querySelectorAll('#hp-table th[data-k]'), function (th) {
      th.addEventListener('click', function () { var k = th.dataset.k; if (sortKey === k) sortDir *= -1; else { sortKey = k; sortDir = 1; }
        [].forEach.call(document.querySelectorAll('.sort-arr'), function (a) { a.classList.remove('on'); a.textContent = '↕'; });
        var a = th.querySelector('.sort-arr'); a.classList.add('on'); a.textContent = sortDir === 1 ? '↑' : '↓'; filter(); });
    });
    var q = new URLSearchParams(location.search);
    if (q.get('type')) $('filt-ctype').value = q.get('type');
    if (q.get('mfr')) $('filt-mfr').value = q.get('mfr');
    if (q.get('hp')) $('filt-hpb').value = q.get('hp');
    var hpid = q.get('hpid');
    if (hpid) {
      fetch('/cylinders-by-hp.json?v=1').then(function (r) { return r.json(); }).then(function (m) {
        HPSET = {}; (m.h[hpid] || []).forEach(function (k) { HPSET[m.c[k][0]] = 1; });
        var note = document.createElement('div');
        note.className = 'faq-callout'; note.style.borderRadius = '10px'; note.style.margin = '0 0 12px';
        note.innerHTML = '<div class="faq-callout-inner"><span class="faq-callout-text">Showing cylinders &amp; tanks listed as compatible with ' + esc(q.get('hpname') || 'the selected heat pump') + '. <a href="/cylinders/">Show all</a></span></div>';
        var c = document.querySelector('.browse-main .container'); c.insertBefore(note, c.firstChild);
        filter();
      }).catch(filter);
    } else filter();
  }
  fetch('/cylinders-data.json?v=' + (window.CYL_V || 1)).then(function (r) { return r.json(); }).then(init)
    .catch(function () { $('res-count').textContent = 'Could not load cylinder data.'; });
})();
