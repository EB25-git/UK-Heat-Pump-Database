/* Heat Pump Database — v265 theme behaviour.
   Loaded after the app (index.html) and on every static page. Leaves the original markup in place
   and rearranges/augments it at load time:
   - desktop nav links in the header (app + static pages)
   - Browse page: search band, HP type buttons, filter sidebar, market map, compare tray, SCOP bars on cards
   Needs window.__hpState (db / filtered / compareIds getters) from index.html for the Browse features. */
(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var esc = function (v) { return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); };

  /* ── Header links (same labels and targets as the burger menu) ── */
  var KN = ['knowledge', 'what-is-a-heat-pump', 'cop-scop', 'flow-temp', 'refrigerants', 'install-costs', 'funding', 'planning', 'faq', 'guide', 'links'];
  function navApp() {
    var nav = $('.nav'), brand = $('.nav-brand');
    if (!nav || !brand || $('#nav-links')) return;
    var d = document.createElement('div');
    d.className = 'nav-links'; d.id = 'nav-links';
    d.innerHTML =
      '<button data-page="browse">Browse</button>' +
      '<a href="/manufacturers/">Manufacturers</a>' +
      '<button data-page="compare">Compare</button>' +
      '<a href="/best/">Best Heat Pumps</a>' +
      '<button data-page="analytics">Visualise</button>' +
      '<a href="/heat-pump-size-calculator/">Size Calculator</a>' +
      '<button data-page="knowledge">Knowledge</button>' +
      '<a href="/news/">News &amp; Insight</a>';
    brand.insertAdjacentElement('afterend', d);
    d.addEventListener('click', function (e) {
      var b = e.target.closest('button[data-page]');
      if (b && window.showPage) window.showPage(b.dataset.page);
    });
    var sync = function () {
      var v = $('.page.show'); if (!v) return;
      var p = v.id.replace(/^page-/, '');
      $$('#nav-links [data-page]').forEach(function (b) {
        var dp = b.dataset.page;
        b.classList.toggle('on', dp === p || (dp === 'knowledge' && KN.indexOf(p) >= 0));
      });
    };
    $$('.page').forEach(function (pg) { new MutationObserver(sync).observe(pg, { attributes: true, attributeFilter: ['class'] }); });
    sync();
  }
  function navStatic() {
    var wrap = $('header.site .wrap'), brand = $('header.site .brand');
    if (!wrap || !brand || $('header.site .nav-links')) return;
    var path = location.pathname, h = location.hash;
    var items = [
      ['Browse', '/', path === '/' || path === '/index.html'],
      ['Manufacturers', '/manufacturers/', path.indexOf('/manufacturers/') === 0],
      ['Compare', '/#compare', path.indexOf('/heat-pump-comparison/') === 0],
      ['Best Heat Pumps', '/best/', path.indexOf('/best/') === 0 || path.indexOf('/top-10/') === 0],
      ['Visualise', '/#analytics', false],
      ['Size Calculator', '/heat-pump-size-calculator/', path.indexOf('/heat-pump-size-calculator/') === 0],
      ['Knowledge', '/#knowledge', path.indexOf('/knowledge/') === 0],
      ['News &amp; Insight', '/news/', path.indexOf('/news/') === 0]
    ];
    var n = document.createElement('nav');
    n.className = 'nav-links'; n.setAttribute('aria-label', 'Main');
    n.innerHTML = items.map(function (i) { return '<a href="' + i[1] + '"' + (i[2] ? ' class="on"' : '') + '>' + i[0] + '</a>'; }).join('');
    brand.insertAdjacentElement('afterend', n);
  }

  /* ── Browse page ── */
  function browse() {
    var page = $('#page-browse'), S = window.__hpState;
    if (!page || !S || $('.browse-layout')) return;
    var hero = $('.hero', page), inner = $('.hero-inner', hero), textCol = inner && inner.firstElementChild;
    var search = $('.search-wrap', page), stats = $('.hero-stats', page);
    var toolbar = $('.toolbar', page), panel = $('#filter-panel'), container = $('.container', page);
    if (!hero || !textCol || !search || !toolbar || !panel || !container) return;

    // search band: search box, HP type buttons, market map toggle, stats line
    var find = document.createElement('div');
    find.className = 'hero-find'; find.id = 'hero-find';
    find.appendChild(search);
    var row = document.createElement('div');
    row.className = 'hero-row';
    row.innerHTML =
      '<div class="hp-seg" role="group" aria-label="HP type">' +
      ['', 'ASHP', 'GSHP', 'WSHP'].map(function (v) { return '<button type="button" data-hp="' + v + '" aria-pressed="' + (v === '' ? 'true' : 'false') + '">' + (v || 'All') + '</button>'; }).join('') +
      '</div>' +
      '<button type="button" class="maptog" id="map-tog" aria-expanded="false" aria-controls="hp-map">' +
      '<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><circle cx="3" cy="11" r="1.6"/><circle cx="6.5" cy="7" r="1.6"/><circle cx="9" cy="9.5" r="1.6"/><circle cx="12.5" cy="4" r="1.6"/><path d="M1 1v14h14" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>' +
      '<span>Show market map</span></button>' +
      '<button type="button" class="maptog filt-mob">Filters</button>';
    find.appendChild(row);
    textCol.appendChild(find);
    if (stats) textCol.appendChild(stats);
    var map = document.createElement('figure');
    map.className = 'hp-map'; map.id = 'hp-map'; map.hidden = true;
    map.innerHTML =
      '<div class="hp-map-head"><b>SCOP vs heating capacity</b><span>Click a dot to open it</span></div>' +
      '<svg id="hp-map-svg" viewBox="0 0 440 200" role="img" aria-label="Scatter plot of SCOP against maximum heating capacity, products matching your filters highlighted"></svg>' +
      '<div class="hp-map-key"><span><i style="background:#8FE3B0"></i>Matches your filters</span><span><i style="background:rgba(255,255,255,.3)"></i>Rest of the database</span></div>' +
      '<div class="hp-map-tip" id="hp-map-tip"></div>';
    inner.appendChild(map);

    // sidebar layout: filters | toolbar + results
    var layout = document.createElement('div'); layout.className = 'browse-layout';
    var main = document.createElement('div'); main.className = 'browse-main';
    toolbar.parentNode.insertBefore(layout, toolbar);
    layout.appendChild(panel); layout.appendChild(main);
    main.appendChild(toolbar); main.appendChild(container);
    var close = document.createElement('button');
    close.type = 'button'; close.className = 'filter-close'; close.textContent = 'Show results';
    panel.appendChild(close);

    // compare tray
    var tray = document.createElement('div');
    tray.className = 'cmp-tray'; tray.id = 'cmp-tray'; tray.setAttribute('aria-live', 'polite');
    tray.innerHTML = '<div class="cmp-tray-in"><div class="cmp-slots" id="cmp-slots-tray"></div>' +
      '<button type="button" class="cmp-clear">Clear</button><button type="button" class="cmp-go" id="cmp-go">Compare</button></div>';
    page.appendChild(tray);

    var hpSel = $('#filt-hptype');
    row.addEventListener('click', function (e) {
      var b = e.target.closest('.hp-seg button');
      if (b) { hpSel.value = b.dataset.hp; window.applyFilters(); return; }
      if (e.target.closest('#map-tog')) { toggleMap(); return; }
      if (e.target.closest('.filt-mob')) window.toggleFilters();
    });
    close.addEventListener('click', function () { window.toggleFilters(); });
    function syncSeg() { $$('.hp-seg button').forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.hp === hpSel.value)); }); }

    // compare tray
    function byId(id) { for (var i = 0; i < S.db.length; i++) if (S.db[i].id === id) return S.db[i]; return null; }
    function renderTray() {
      var ids = S.compareIds, h = '';
      for (var i = 0; i < 3; i++) {
        var d = byId(ids[i]);
        h += d ? '<span class="cmp-slot">' + esc(d.manufacturer + ' ' + d.model) + '<button type="button" data-rm="' + d.id + '" aria-label="Remove ' + esc(d.model) + '">×</button></span>'
               : '<span class="cmp-slot empty">+ Compare</span>';
      }
      $('#cmp-slots-tray').innerHTML = h;
      var on = ids.length > 0;
      tray.classList.toggle('show', on && page.classList.contains('show'));
      document.body.classList.toggle('cmp-open', on && page.classList.contains('show'));
      var g = $('#cmp-go'); g.disabled = ids.length < 2; g.textContent = 'Compare' + (ids.length ? ' (' + ids.length + '/3)' : '');
    }
    function trayRemove(id) {
      window.removeCompare(id);
      var b = document.getElementById('cmp-btn-' + id);
      if (b) { b.textContent = '+ Compare'; b.classList.remove('added'); }
      renderTray(); drawMap();
    }
    tray.addEventListener('click', function (e) {
      var r = e.target.closest('[data-rm]');
      if (r) { trayRemove(+r.dataset.rm); return; }
      if (e.target.closest('.cmp-clear')) { S.compareIds.slice().forEach(trayRemove); return; }
      if (e.target.closest('.cmp-go')) window.showPage('compare');
    });
    if (typeof window.addCompare === 'function') {
      var add = window.addCompare;
      window.addCompare = function () { var r = add.apply(this, arguments); renderTray(); drawMap(); return r; };
    }
    new MutationObserver(renderTray).observe(page, { attributes: true, attributeFilter: ['class'] });

    // market map
    var M = { X0: 30, X1: 432, Y0: 20, Y1: 176, lmin: 0, lmax: Math.log(1000), built: false };
    var mx = function (c) { return M.X0 + (Math.log(Math.max(1, Math.min(1000, c))) - M.lmin) / (M.lmax - M.lmin) * (M.X1 - M.X0); };
    var my = function (v) { return M.Y1 - (Math.max(2, Math.min(7, v)) - 2) / 5 * (M.Y1 - M.Y0); };
    function buildMap() {
      var g = '';
      [2, 3, 4, 5, 6, 7].forEach(function (v) { g += '<line x1="' + M.X0 + '" x2="' + M.X1 + '" y1="' + my(v) + '" y2="' + my(v) + '" stroke="rgba(255,255,255,.08)"/><text x="' + (M.X0 - 6) + '" y="' + (my(v) + 3.5) + '" text-anchor="end">' + v + '</text>'; });
      [1, 10, 100, 1000].forEach(function (c) { g += '<text x="' + mx(c) + '" y="' + (M.Y1 + 16) + '" text-anchor="middle">' + c + (c === 1000 ? ' kW' : '') + '</text>'; });
      g += '<text x="' + M.X0 + '" y="10">SCOP</text><g id="hp-map-pts">';
      S.db.forEach(function (d) { if (d.cap_max > 0 && d.scop > 0) g += '<circle class="bg" data-id="' + d.id + '" r="1.8" cx="' + mx(d.cap_max).toFixed(1) + '" cy="' + my(d.scop).toFixed(1) + '"/>'; });
      $('#hp-map-svg').innerHTML = g + '</g>'; M.built = true;
    }
    function drawMap() {
      if (map.hidden) return;
      if (!M.built) buildMap();
      var on = {}, cmp = S.compareIds, grp = $('#hp-map-pts'), lit = [];
      S.filtered.forEach(function (d) { on[d.id] = 1; });
      $$('circle', grp).forEach(function (c) {
        var id = +c.dataset.id, hit = !!on[id], inCmp = cmp.indexOf(id) >= 0;
        c.setAttribute('class', hit ? 'on' : 'bg');
        c.setAttribute('r', hit ? (inCmp ? 5 : 3.2) : 1.8);
        if (hit && inCmp) { c.setAttribute('stroke', '#fff'); c.setAttribute('stroke-width', '2'); } else c.removeAttribute('stroke');
        if (hit) lit.push(c);
      });
      lit.forEach(function (c) { grp.appendChild(c); });
    }
    function toggleMap() {
      var b = $('#map-tog'), open = b.getAttribute('aria-expanded') !== 'true';
      b.setAttribute('aria-expanded', String(open));
      $('span', b).textContent = open ? 'Hide market map' : 'Show market map';
      map.hidden = !open; hero.classList.toggle('map-open', open);
      if (open) drawMap(); else $('#hp-map-tip').classList.remove('show');
    }
    var svg = $('#hp-map-svg'), tip = $('#hp-map-tip');
    svg.addEventListener('mousemove', function (e) {
      var c = e.target.closest('circle.on'); if (!c) { tip.classList.remove('show'); return; }
      var d = byId(+c.dataset.id); if (!d) return;
      var bb = map.getBoundingClientRect(), cb = c.getBoundingClientRect();
      tip.textContent = d.manufacturer + ' ' + d.model + ' · ' + d.cap_max + ' kW · SCOP ' + d.scop;
      tip.style.left = (cb.left - bb.left + cb.width / 2) + 'px'; tip.style.top = (cb.top - bb.top - 6) + 'px';
      tip.classList.add('show');
    });
    svg.addEventListener('mouseleave', function () { tip.classList.remove('show'); });
    svg.addEventListener('click', function (e) { var c = e.target.closest('circle.on'); if (c && window.openModal) window.openModal(+c.dataset.id); });
    $('#hp-grid').addEventListener('mouseover', function (e) {
      if (map.hidden) return;
      $$('#hp-map-pts .hot').forEach(function (x) { x.classList.remove('hot'); });
      var card = e.target.closest('.hp-card'); if (!card) return;
      var m = (card.getAttribute('onclick') || '').match(/openModal\((\d+)\)/); if (!m) return;
      var d = $('#hp-map-pts circle.on[data-id="' + m[1] + '"]');
      if (d) { d.classList.add('hot'); d.parentNode.appendChild(d); }
    });

    // SCOP bars on cards (added after each render)
    function meters() {
      $$('#hp-grid .hp-spec').forEach(function (s) {
        var l = $('.hp-spec-label', s);
        if (!l || l.textContent.trim() !== 'SCOP' || $('.hp-meter', s)) return;
        var v = parseFloat(($('.hp-spec-cop span', s) || {}).textContent);
        if (!(v > 0)) return;
        var w = Math.max(4, Math.min(100, (v - 2.5) / 3.5 * 100));
        $('.hp-spec-val', s).insertAdjacentHTML('beforeend', '<span class="hp-meter" aria-hidden="true"><i style="width:' + w + '%"></i></span>');
      });
    }
    // results count in bold
    var rc = $('#res-count');
    function boldCount() { var m = rc.textContent.match(/^(\d+)(.*)$/); if (m && !$('b', rc)) rc.innerHTML = '<b>' + m[1] + '</b>' + esc(m[2]); }

    // react to every re-render of the results (filters, search, sort, infinite scroll)
    var pending = false;
    function onRender() {
      if (pending) return; pending = true;
      requestAnimationFrame(function () { pending = false; meters(); boldCount(); syncSeg(); drawMap(); renderTray(); });
    }
    new MutationObserver(onRender).observe($('#hp-grid'), { childList: true });
    new MutationObserver(onRender).observe(rc, { childList: true, characterData: true, subtree: true });
    onRender();
  }

  function init() { navApp(); navStatic(); browse(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(init, 0); });
  else setTimeout(init, 0);
})();
