/* Heat Pump Database — heat pump noise calculator (MCS 020 a), England permitted development).
   Lp = Lw + 10·log10(Q / (4·π·r²)) − Ab   per heat pump, at each assessment position.
   Two heat pumps: Lp,total = 10·log10(10^(Lp1/10) + 10^(Lp2/10)).
   Result rounded to 0.1 dB and compared with the 37.0 dB(A) limit at every assessment position.
   Source: MCS 020 a) Issue 1.1 (14/04/2025), Steps 3–8. */
(function () {
  'use strict';
  var LIMIT = 37.0;
  var BARRIER = { // MCS 020 a) Step 6 matrix
    t1: { none: 10, partial: 5, full: 0 },
    t2: { none: 5, partial: 2.5, full: 0 },
    no: { none: 0, partial: 0, full: 0 }
  };
  var PRODUCTS = [];
  var state = { units: 1, positions: [] };
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (v) { return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); };
  var r1 = function (x) { return Math.round(x * 10) / 10; };
  var fmt1 = function (x) { return (Math.round(x * 10) / 10).toFixed(1); };

  function lp(lw, q, r, ab) { return lw + 10 * Math.log10(q / (4 * Math.PI * r * r)) - ab; }
  function sumLog(arr) { var s = 0; arr.forEach(function (v) { s += Math.pow(10, v / 10); }); return 10 * Math.log10(s); }
  // smallest distance at which one unit meets the limit on its own (rounded up to 0.1 m)
  function minDistance(lw, q, ab, target) {
    var r = Math.sqrt(q * Math.pow(10, (lw - ab - target) / 10) / (4 * Math.PI));
    return Math.ceil(r * 10 - 1e-9) / 10;
  }

  /* ---------- heat pump inputs ---------- */
  function unitVals(u) {
    var lw = parseFloat($('nc-lw-' + u).value);
    var qEl = document.querySelector('input[name="nc-q-' + u + '"]:checked');
    return { lw: isFinite(lw) ? lw : null, q: qEl ? parseFloat(qEl.value) : null };
  }

  function setUnits(n) {
    state.units = n;
    $('nc-unit-2').style.display = n === 2 ? '' : 'none';
    $('nc-units-1').classList.toggle('active', n === 1);
    $('nc-units-2').classList.toggle('active', n === 2);
    renderPositions();
  }

  /* ---------- product search ---------- */
  function setupSearch(u) {
    var inp = $('nc-search-' + u), list = $('nc-results-' + u);
    inp.addEventListener('input', function () {
      var q = inp.value.trim().toLowerCase();
      if (q.length < 2) { list.innerHTML = ''; list.style.display = 'none'; return; }
      var words = q.split(/\s+/);
      var hits = PRODUCTS.filter(function (p) {
        var s = (p.m + ' ' + p.n + ' ' + (p.c || '')).toLowerCase();
        return words.every(function (w) { return s.indexOf(w) >= 0; });
      }).slice(0, 12);
      list.innerHTML = hits.length ? hits.map(function (p) {
        return '<button type="button" class="nc-hit" data-id="' + p.i + '"><span class="nc-hit-name">' + esc(p.m + ' ' + p.n) + '</span>' +
          '<span class="nc-hit-meta">' + esc((p.c ? p.c + ' · ' : '') + (p.k != null ? p.k + ' kW · ' : '')) + '<b>' + p.lw + ' dB(A)</b></span></button>';
      }).join('') : '<div class="nc-hit-empty">No match with published sound power – enter it manually.</div>';
      list.style.display = 'block';
    });
    list.addEventListener('click', function (e) {
      var b = e.target.closest('.nc-hit'); if (!b) return;
      var p = PRODUCTS.find(function (x) { return String(x.i) === b.dataset.id; }); if (!p) return;
      $('nc-lw-' + u).value = p.lw;
      $('nc-picked-' + u).innerHTML = '✓ <a href="' + esc(p.u) + '" target="_blank" rel="noopener">' + esc(p.m + ' ' + p.n + (p.c ? ' (' + p.c + ')' : '')) + '</a> · ' + p.lw + ' dB(A)';
      inp.value = ''; list.innerHTML = ''; list.style.display = 'none';
      recalc();
    });
    document.addEventListener('click', function (e) { if (!e.target.closest('#nc-search-wrap-' + u)) { list.style.display = 'none'; } });
  }

  /* ---------- assessment positions ---------- */
  function newPosition() {
    return { desc: '', units: [{ r: 5, bt: 'no', ls: 'full' }, { r: 5, bt: 'no', ls: 'full' }] };
  }
  function addPosition() { state.positions.push(newPosition()); renderPositions(); }
  function removePosition(i) { state.positions.splice(i, 1); if (!state.positions.length) state.positions.push(newPosition()); renderPositions(); }

  function info(t, cls) { return '<span class="nc-i' + (cls ? ' ' + cls : '') + '" tabindex="0" role="button" aria-label="More information">i<span class="nc-tip" role="tooltip">' + t + '</span></span>'; }
  var TIP_R = 'Straight line from the <b>centre of the heat pump</b> to a point <b>1 m outside the centre</b> of the window or door, to 0.1 m.';
  var TIP_B = 'Only solid barriers with no gaps count, extending at least 1 m beyond each side of the heat pump. Open, slatted or damaged fences and hedges count as no barrier.';
  var TIP_L = 'Looking from the top edge of the heat pump: <b>Full</b> = window visible. <b>Partial</b> = visible if you move up to 0.25 m. <b>None</b> = completely hidden by the barrier.';
  function unitInputs(i, u) {
    var p = state.positions[i].units[u];
    var lab = state.units === 2 ? '<div class="nc-unit-lab">Heat pump ' + (u + 1) + '</div>' : '';
    return '<div class="nc-pos-unit">' + lab +
      '<div class="nc-grid3">' +
      '<div class="dm-field"><label>Distance (m) ' + info(TIP_R, 'l') + '</label><input type="number" min="0.5" max="200" step="0.1" value="' + p.r + '" data-i="' + i + '" data-u="' + u + '" data-k="r"></div>' +
      '<div class="dm-field"><label>Barrier ' + info(TIP_B) + '</label><select data-i="' + i + '" data-u="' + u + '" data-k="bt">' +
      opt('no', 'None', p.bt) + opt('t1', 'Wall / solid fence ≥18 mm', p.bt) + opt('t2', 'Solid fence <18 mm', p.bt) +
      '</select></div>' +
      '<div class="dm-field"><label>Line of sight ' + info(TIP_L, 'r') + '</label><select data-i="' + i + '" data-u="' + u + '" data-k="ls"' + (p.bt === 'no' ? ' disabled' : '') + '>' +
      opt('full', 'Full', p.ls) + opt('partial', 'Partial', p.ls) + opt('none', 'None', p.ls) +
      '</select></div>' +
      '</div></div>';
  }
  function opt(v, t, cur) { return '<option value="' + v + '"' + (v === cur ? ' selected' : '') + '>' + t + '</option>'; }

  function renderPositions() {
    var box = $('nc-positions');
    box.innerHTML = state.positions.map(function (pos, i) {
      return '<div class="nc-pos" id="nc-pos-' + i + '">' +
        '<div class="nc-pos-head"><span class="nc-pos-num">Window ' + (i + 1) + '</span>' +
        '<input type="text" maxlength="120" aria-label="Description" placeholder="Description, e.g. No. 16, 1st floor bedroom" value="' + esc(pos.desc) + '" data-i="' + i + '" data-k="desc">' +
        (state.positions.length > 1 ? '<button type="button" class="nc-link" data-remove="' + i + '">Remove</button>' : '') + '</div>' +
        unitInputs(i, 0) + (state.units === 2 ? unitInputs(i, 1) : '') +
        '<div class="nc-pos-result" id="nc-pos-res-' + i + '"></div>' +
        '</div>';
    }).join('');
    recalc();
  }

  function onPosInput(e) {
    var t = e.target, i = t.dataset.i, k = t.dataset.k; if (i == null || !k) return;
    var pos = state.positions[+i];
    if (k === 'desc') { pos.desc = t.value; recalc(); return; }
    var u = +t.dataset.u, v = t.value;
    pos.units[u][k] = k === 'r' ? parseFloat(v) : v;
    if (k === 'bt') { renderPositions(); return; }
    recalc();
  }

  /* ---------- calculation ---------- */
  function recalc() {
    var U = [unitVals(0), unitVals(1)].slice(0, state.units);
    var missing = U.some(function (x) { return x.lw == null || x.q == null; });
    var worst = null, allPass = true, anyCalc = false;
    state.positions.forEach(function (pos, i) {
      var el = $('nc-pos-res-' + i); if (!el) return;
      if (missing) { el.innerHTML = '<div class="nc-pending">Add the sound power level above.</div>'; allPass = false; return; }
      var parts = [], ok = true;
      U.forEach(function (unit, u) {
        var p = pos.units[u], ab = BARRIER[p.bt][p.bt === 'no' ? 'full' : p.ls];
        if (!(p.r > 0)) { ok = false; return; }
        parts.push({ u: u, lw: unit.lw, q: unit.q, r: p.r, ab: ab, lp: lp(unit.lw, unit.q, p.r, ab) });
      });
      if (!ok) { el.innerHTML = '<div class="nc-pending">Enter a distance greater than 0 m.</div>'; allPass = false; return; }
      anyCalc = true;
      var total = parts.length > 1 ? sumLog(parts.map(function (x) { return x.lp; })) : parts[0].lp;
      var tot1 = r1(total), pass = tot1 <= LIMIT;
      if (!pass) allPass = false;
      if (worst == null || tot1 > worst.v) worst = { v: tot1, i: i };
      var work = parts.map(function (x) {
        return '<div class="nc-work" style="color:#E4F6EC">' + (parts.length > 1 ? 'Heat pump ' + (x.u + 1) + ': ' : '') +
          x.lw + ' + 10·log(' + x.q + ' ÷ (4·π·' + x.r + '²)) − ' + x.ab + ' = <b>' + fmt1(x.lp) + ' dB(A)</b></div>';
      }).join('');
      if (parts.length > 1) work += '<div class="nc-work" style="color:#E4F6EC">Total: 10·log(10^(' + fmt1(parts[0].lp) + '/10) + 10^(' + fmt1(parts[1].lp) + '/10)) = <b>' + fmt1(total) + ' dB(A)</b></div>';
      var help = '';
      if (!pass) {
        var target = parts.length > 1 ? LIMIT - 3 : LIMIT; // two similar sources: each needs to be ~3 dB below the limit
        var tips = parts.filter(function (x) { return x.lp > target; }).map(function (x) {
          var d = minDistance(x.lw, x.q, x.ab, target);
          var maxLw = Math.floor((x.lw - (x.lp - (target + 0.04))) * 10) / 10;
          return (parts.length > 1 ? 'Heat pump ' + (x.u + 1) + ': ' : '') + 'needs about <b>' + d.toFixed(1) + ' m</b>, or a unit of <b>≤' + maxLw.toFixed(1) + ' dB(A)</b> at ' + x.r + ' m' + (parts.length > 1 ? ' (if both units are similar)' : '') + '.';
        });
        help = '<div class="nc-help">' + tips.join('<br>') + '</div>';
      }
      el.innerHTML = '<div class="nc-verdict ' + (pass ? 'pass' : 'fail') + '"><span class="nc-v-num">' + tot1.toFixed(1) + ' dB(A)</span>' +
        '<span class="nc-v-txt">' + (pass ? '✓ Within 37.0 dB(A)' : '✗ ' + (tot1 - LIMIT).toFixed(1) + ' dB over the limit') + '</span>' +
        '<span class="nc-v-work">' + info('<b>Working (MCS 020 a) Step 7)</b>' + work, 'r') + '</span></div>' + help;
    });
    var sum = $('nc-summary');
    if (missing || !anyCalc) { sum.className = 'nc-summary'; sum.innerHTML = '<div><div class="nc-sum-title">Result</div><div class="nc-sum-sub">Add the heat pump and at least one window.</div></div>'; return; }
    var n = state.positions.length;
    sum.className = 'nc-summary ' + (allPass ? 'pass' : 'fail');
    sum.innerHTML = '<div class="nc-sum-big">' + worst.v.toFixed(1) + ' <span>dB(A)</span></div><div>' +
      '<div class="nc-sum-title">' + (allPass ? '✓ Meets the 37 dB(A) limit' : '✗ Exceeds the 37 dB(A) limit') + '</div>' +
      '<div class="nc-sum-sub">Loudest of ' + n + ' window' + (n > 1 ? 's' : '') + ' (window ' + (worst.i + 1) + ').' +
      (allPass ? '' : ' Move the unit, add a solid barrier, reduce reflecting surfaces or pick a quieter model.') + '</div></div>';
  }

  /* ---------- print ---------- */
  function printReport() {
    var d = new Date();
    $('nc-print-date').textContent = d.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
    window.print();
  }

  /* ---------- init ---------- */
  function init() {
    if (!$('nc-app')) return;
    state.positions = [newPosition()];
    [0, 1].forEach(function (u) {
      setupSearch(u);
      $('nc-lw-' + u).addEventListener('input', function () { $('nc-picked-' + u).textContent = ''; recalc(); });
      Array.prototype.forEach.call(document.querySelectorAll('input[name="nc-q-' + u + '"]'), function (el) { el.addEventListener('change', recalc); });
    });
    $('nc-units-1').addEventListener('click', function () { setUnits(1); });
    $('nc-units-2').addEventListener('click', function () { setUnits(2); });
    $('nc-add-pos').addEventListener('click', addPosition);
    $('nc-print').addEventListener('click', printReport);
    var box = $('nc-positions');
    box.addEventListener('input', onPosInput);
    box.addEventListener('change', onPosInput);
    box.addEventListener('click', function (e) { var b = e.target.closest('[data-remove]'); if (b) removePosition(+b.dataset.remove); });
    renderPositions();
    fetch('/noise-products.json').then(function (r) { return r.json(); }).then(function (d) {
      PRODUCTS = d;
      var c = $('nc-db-count'); if (c) c.textContent = d.length.toLocaleString('en-GB');
      // ?id=123 pre-fills heat pump 1 (used by links from product pages)
      var m = location.search.match(/[?&]id=(\d+)/);
      if (m) {
        var p = d.find(function (x) { return String(x.i) === m[1]; });
        if (p) { $('nc-lw-0').value = p.lw; $('nc-picked-0').innerHTML = '✓ <a href="' + esc(p.u) + '">' + esc(p.m + ' ' + p.n + (p.c ? ' (' + p.c + ')' : '')) + '</a> · ' + p.lw + ' dB(A)'; recalc(); }
      }
    }).catch(function () {});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
  window.__noiseCalc = { lp: lp, sumLog: sumLog, minDistance: minDistance, BARRIER: BARRIER };
})();
