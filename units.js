/* Heat Pump Database - metric / imperial display toggle (v313).
   Data is stored and published in metric. When a visitor picks "Imperial",
   this script rewrites what is on screen (text only, never inputs, scripts,
   meta tags or URLs): °C -> °F, kW -> BTU/h, mm -> in, kg -> lb.
   Ranges and dimension triples that share one unit are converted together.
   A MutationObserver converts content the app renders later (cards, modal,
   compare table), and switching back restores the original text exactly.
   The choice is remembered in localStorage. */
(function () {
  'use strict';
  var KEY = 'hp_units';
  var OFF = /^\/heat-pump-(size|noise)-calculator\//.test(location.pathname); // calculators work in metric inputs
  var mode = 'metric';
  try { if (localStorage.getItem(KEY) === 'imperial') mode = 'imperial'; } catch (e) {}
  if (OFF) mode = 'metric';

  var SKIP = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEXTAREA: 1, INPUT: 1, SELECT: 1, OPTION: 1, CODE: 1, PRE: 1, TITLE: 1 };
  var orig = new WeakMap();   // text node -> original metric text
  var conv = new WeakMap();   // text node -> text we wrote
  var touched = [];           // nodes we changed (for restore)
  var NUM = '[-\\u2212+]?\\d[\\d,]*(?:\\.\\d+)?';
  var SEP = '(\\s*(?:\\u2013|\\u2014|-|to)\\s*)';
  var P = function (n) { return parseFloat(String(n).replace(/−/g, '-').replace(/,/g, '')); };
  var fmt = function (v, dp) { return v.toLocaleString('en-GB', { maximumFractionDigits: dp, minimumFractionDigits: 0 }).replace(/^-/, '−'); };
  var F = function (c) { return fmt(Math.round(P(c) * 9 / 5 + 32), 0); };
  var BTU = function (k) { var b = P(k) * 3412.142; return fmt(b >= 10000 ? Math.round(b / 100) * 100 : Math.round(b / 10) * 10, 0); };
  var IN = function (m) { var i = P(m) / 25.4; return fmt(i >= 100 ? Math.round(i) : Math.round(i * 10) / 10, 1); };
  var LB = function (k) { var l = P(k) * 2.20462; return fmt(l >= 10 ? Math.round(l) : Math.round(l * 10) / 10, 1); };

  var RULES = [
    // temperatures
    [new RegExp('(' + NUM + ')' + SEP + '(' + NUM + ')\\s*(?:\\u00b0\\s?C|\\u2103)', 'g'), function (m, a, s, b) { return F(a) + s + F(b) + ' °F'; }],
    [new RegExp('(' + NUM + ')\\s*(?:\\u00b0\\s?C|\\u2103)', 'g'), function (m, a) { return F(a) + ' °F'; }],
    // capacity (not kWh, not per-kW prices)
    [new RegExp('(' + NUM + ')' + SEP + '(' + NUM + ')\\s*kW(?![A-Za-z])', 'g'), function (m, a, s, b) { return BTU(a) + s + BTU(b) + ' BTU/h'; }],
    [new RegExp('(' + NUM + ')\\s*kW(?![A-Za-z])', 'g'), function (m, a) { return BTU(a) + ' BTU/h'; }],
    // dimensions
    [new RegExp('(' + NUM + ')\\s*[\\u00d7x]\\s*(' + NUM + ')(?:\\s*[\\u00d7x]\\s*(' + NUM + '))?\\s*mm\\b', 'g'), function (m, a, b, c) { return IN(a) + ' × ' + IN(b) + (c ? ' × ' + IN(c) : '') + ' in'; }],
    [new RegExp('(' + NUM + ')\\s*mm\\b', 'g'), function (m, a) { return IN(a) + ' in'; }],
    // weight
    [new RegExp('(' + NUM + ')\\s*kg\\b', 'g'), function (m, a) { return LB(a) + ' lb'; }]
  ];
  var QUICK = /°\s?C|℃|kW|mm\b|kg\b/;

  function convertText(t) {
    var out = t;
    for (var i = 0; i < RULES.length; i++) {
      out = out.replace(RULES[i][0], function () {
        var args = arguments, m = args[0], off = args[args.length - 2], str = args[args.length - 1];
        var prev = str.charAt(off - 1);
        if (prev === '/' || prev === '£' || /[A-Za-z0-9.]/.test(prev)) return m; // e.g. "£/kW", "A7/W35", "R32"
        return RULES[i][1].apply(null, args);
      });
    }
    return out;
  }
  function skip(el) {
    for (; el && el.nodeType === 1; el = el.parentNode) {
      if (SKIP[el.nodeName] || el.hasAttribute('data-no-units') || el.isContentEditable) return true;
    }
    return false;
  }
  function doNode(n) {
    if (n.nodeType !== 3) return;
    var t = n.data;
    if (!t || !QUICK.test(t) || conv.get(n) === t) return;
    if (skip(n.parentNode)) return;
    var c = convertText(t);
    if (c !== t) { orig.set(n, t); conv.set(n, c); touched.push(n); n.data = c; }
  }
  function walk(root) {
    if (!root) return;
    if (root.nodeType === 3) { doNode(root); return; }
    if (root.nodeType !== 1 || skip(root)) return;
    var w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null), n;
    var list = [];
    while ((n = w.nextNode())) list.push(n);
    list.forEach(doNode);
  }
  function restore() {
    touched.forEach(function (n) {
      var o = orig.get(n);
      if (o != null && n.data === conv.get(n)) n.data = o;
      orig.delete(n); conv.delete(n);
    });
    touched = [];
  }
  var obs = new MutationObserver(function (muts) {
    muts.forEach(function (m) {
      if (m.type === 'characterData') doNode(m.target);
      else m.addedNodes.forEach(walk);
    });
  });
  function apply() {
    document.documentElement.setAttribute('data-units', mode);
    if (mode === 'imperial') {
      walk(document.body);
      obs.observe(document.body, { childList: true, subtree: true, characterData: true });
    } else {
      obs.disconnect(); restore();
    }
    var t = document.querySelectorAll('.units-toggle button');
    for (var i = 0; i < t.length; i++) t[i].setAttribute('aria-pressed', String(t[i].getAttribute('data-u') === mode));
    try { window.dispatchEvent(new CustomEvent('hp:units', { detail: mode })); } catch (e) {}
  }
  window.hpSetUnits = function (u) {
    if (OFF) return;
    mode = u === 'imperial' ? 'imperial' : 'metric';
    try { localStorage.setItem(KEY, mode); } catch (e) {}
    if (window.gtag) window.gtag('event', 'units_toggle', { units: mode });
    apply();
  };
  window.hpUnits = function () { return mode; };
  function init() {
    if (OFF) { var tg = document.querySelectorAll('.units-toggle'); for (var i = 0; i < tg.length; i++) tg[i].hidden = true; }
    document.addEventListener('click', function (e) {
      var b = e.target.closest && e.target.closest('.units-toggle button[data-u]');
      if (b) { e.preventDefault(); window.hpSetUnits(b.getAttribute('data-u')); }
    });
    apply();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
