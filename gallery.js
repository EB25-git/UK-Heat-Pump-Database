/* /heat-pump-gallery/ - filters, sorting and paging over /gallery-data.json.
   The first tiles are already in the HTML (crawlable); this script takes over once the data loads.
   Filter state is mirrored in the query string so a filtered view can be shared or bookmarked. */
(function () {
  'use strict';
  var $ = function (i) { return document.getElementById(i); };
  var grid = $('gal-grid'), cnt = $('gal-count'), more = $('gal-more');
  var IDS = { cap: 'gal-cap', app: 'gal-app', type: 'gal-type', ref: 'gal-ref', mfr: 'gal-mfr', mode: 'gal-mode', sort: 'gal-sort', photo: 'gal-photo' };
  var DEF = { sort: 'photo-first', photo: 'yes' };
  var PAGE = 120, limit = PAGE, db = [];
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function v(k) { var e = $(IDS[k]); return e ? e.value : ''; }
  function fmt(n) { return (Math.round(n * 100) / 100).toString(); }
  function match(d) {
    var c = v('cap');
    if (c) { var p = c.split('-'), lo = +p[0], hi = +p[1]; if (d.k == null || d.k <= lo && lo > 0 || d.k > hi) return false; }
    if (v('app') && d.a !== v('app')) return false;
    if (v('type') && d.t !== v('type')) return false;
    if (v('ref') && (d.r || []).indexOf(v('ref')) < 0) return false;
    if (v('mfr') && d.m !== v('mfr')) return false;
    if (v('mode') && d.md !== v('mode')) return false;
    if (v('photo') === 'yes' && !(d.im && d.im.length)) return false;
    return true;
  }
  function az(a, b) { return String(a.m).localeCompare(String(b.m)) || String(a.n).localeCompare(String(b.n)) || (a.k || 0) - (b.k || 0); }
  function sortRows(rows) {
    var s = v('sort');
    var cmp = s === 'mfr-az' ? az
      : s === 'cap-desc' ? function (a, b) { return (b.k || 0) - (a.k || 0) || az(a, b); }
      : s === 'cap-asc' ? function (a, b) { return (a.k || 9e9) - (b.k || 9e9) || az(a, b); }
      : s === 'cop-desc' ? function (a, b) { return (b.cop || 0) - (a.cop || 0) || az(a, b); }
      : s === 'noise-asc' ? function (a, b) { return (a.nz || 999) - (b.nz || 999) || az(a, b); }
      : s === 'date-desc' ? function (a, b) { return String(b.d || '').localeCompare(String(a.d || '')) || az(a, b); }
      : function (a, b) { var x = a.im ? 0 : 1, y = b.im ? 0 : 1; return x - y || az(a, b); };
    return rows.sort(cmp);
  }
  function tile(d) {
    var imgs = d.im || [], alt = esc(d.m + ' ' + d.n + (d.c ? ' ' + d.c : ''));
    var spec = [d.k != null ? fmt(d.k) + ' kW' : '', (d.r || []).join(' / ')].filter(Boolean).map(esc).join(' &middot; ');
    var pic;
    if (imgs.length) {
      pic = '<span class="gal-ph" data-imgs="' + esc(JSON.stringify(imgs)) + '" data-i="0"><img class="gal-img" src="' + esc(imgs[0]) + '" alt="' + alt + '" loading="lazy" width="300" height="300">';
      if (imgs.length > 1) {
        pic += '<button type="button" class="gal-nav prev" aria-label="Previous photo" data-step="-1">&#8249;</button>' +
          '<button type="button" class="gal-nav next" aria-label="Next photo" data-step="1">&#8250;</button>' +
          '<span class="gal-imgcount">1/' + imgs.length + '</span><span class="gal-dots">' +
          imgs.map(function (_, n) { return '<span class="gal-dot' + (n ? '' : ' on') + '"></span>'; }).join('') + '</span>';
      }
      pic += '</span>';
    } else {
      pic = '<span class="gal-ph empty">' + (d.lg ? '<img src="' + esc(d.lg) + '" alt="">' : '') + '<span>Photo to come</span></span>';
    }
    return '<a class="gal-tile" href="/products/' + esc(d.s) + '/">' + pic + '<span class="gal-meta"><span class="gal-mfr">' + esc(d.m) +
      '</span><span class="gal-model">' + esc(d.n) + '</span><span class="gal-spec">' + spec + '</span></span></a>';
  }
  function syncUrl() {
    var q = new URLSearchParams();
    Object.keys(IDS).forEach(function (k) { var x = v(k); if (x !== (DEF[k] || '')) q.set(k, x); });
    var s = q.toString();
    history.replaceState(null, '', location.pathname + (s ? '?' + s : ''));
  }
  function render() {
    var rows = sortRows(db.filter(match)), withPhoto = 0;
    rows.forEach(function (d) { if (d.im) withPhoto++; });
    var shown = rows.slice(0, limit);
    var empty = '<p>No products match these filters.</p>';
    if (!rows.length && v('photo') === 'yes') {
      var save = $(IDS.photo).value; $(IDS.photo).value = '';
      var n = db.filter(match).length; $(IDS.photo).value = save;
      if (n) empty = '<p>No photos yet for this selection. <a href="#" id="gal-show-all">Show all ' + n.toLocaleString('en-GB') + ' matching products</a> (without photos).</p>';
    }
    grid.innerHTML = shown.map(tile).join('') || empty;
    cnt.innerHTML = '<strong>' + rows.length.toLocaleString('en-GB') + '</strong> matching product' + (rows.length === 1 ? '' : 's') +
      (v('photo') === 'yes' ? '' : ' &middot; <strong>' + withPhoto.toLocaleString('en-GB') + '</strong> with a photo') +
      (rows.length > shown.length ? ' &middot; showing ' + shown.length : '') +
      ' &middot; <a href="#" id="gal-reset">reset filters</a>';
    more.innerHTML = rows.length > shown.length ? '<button type="button" id="gal-more-btn">Show more</button>' : '';
    syncUrl();
  }
  function reset() {
    Object.keys(IDS).forEach(function (k) { var e = $(IDS[k]); if (e) e.value = DEF[k] || ''; });
    limit = PAGE; render();
  }
  document.addEventListener('click', function (e) {
    var t = e.target;
    if (t.id === 'gal-reset') { e.preventDefault(); reset(); return; }
    if (t.id === 'gal-more-btn') { limit += PAGE; render(); return; }
    if (t.id === 'gal-show-all') { e.preventDefault(); $(IDS.photo).value = ''; limit = PAGE; render(); return; }
    var step = t.getAttribute && t.getAttribute('data-step');
    if (step) {
      e.preventDefault(); e.stopPropagation();
      var ph = t.closest('.gal-ph'), imgs = JSON.parse(ph.getAttribute('data-imgs') || '[]');
      var i = ((+ph.getAttribute('data-i') || 0) + (+step) + imgs.length) % imgs.length;
      ph.setAttribute('data-i', i);
      ph.querySelector('img.gal-img').src = imgs[i];
      [].forEach.call(ph.querySelectorAll('.gal-dot'), function (el, n) { el.classList.toggle('on', n === i); });
      var c = ph.querySelector('.gal-imgcount'); if (c) c.textContent = (i + 1) + '/' + imgs.length;
    }
  });
  Object.keys(IDS).forEach(function (k) {
    var e = $(IDS[k]); if (!e) return;
    e.addEventListener('change', function () { limit = PAGE; render(); });
  });
  var q = new URLSearchParams(location.search);
  Object.keys(IDS).forEach(function (k) {
    var e = $(IDS[k]); if (!e) return;
    var want = q.has(k) ? q.get(k) : (DEF[k] || '');
    if ([].some.call(e.options, function (o) { return o.value === want; })) e.value = want;
  });
  fetch('/gallery-data.json?v=' + (document.documentElement.getAttribute('data-gv') || '1'))
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var pre = d.pre || '', lg = d.lg || {};
      db = (d.p || []).map(function (x) {
        if (x.im) x.im = x.im.map(function (u) { return u.charAt(0) === '/' || u.indexOf('http') === 0 ? u : pre + u; });
        x.lg = lg[x.m]; return x;
      });
      render();
    })
    .catch(function () { cnt.textContent = 'Could not load the full gallery - showing a selection.'; });
})();
