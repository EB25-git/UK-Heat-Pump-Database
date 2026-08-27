#!/usr/bin/env python3
"""
build.py — Heat Pump Database static-page generator (SEO multi-page architecture).

Reads products.json (the data) and generates individually-rankable static pages:
  products/<slug>/index.html        one page per product
  manufacturers/<slug>/index.html   one page per manufacturer  (+ manufacturers/index.html)
  types/<slug>/index.html           category pages (source type, refrigerant, application)
  sitemap.xml                       lists every URL for search engines
  robots.txt                        points crawlers at the sitemap

The interactive app (index.html) is left untouched; these pages link into it.
Run:  python3 build.py
Requires only the Python standard library.
"""

import json, os, re, html, shutil, datetime, hashlib

# ───────────────────────── Config ─────────────────────────
BASE_URL  = "https://www.heatpumpdatabase.com"   # no trailing slash
SITE_NAME = "Heat Pump Database"

# Default social-share image (1200x630) used for og:image / twitter:image on any
# page that doesn't have a more specific picture. OG_IMAGE_BY_MFR is the future
# extension point for per-product-range photos: add {"Manufacturer": "images/...jpg"}
# and rebuild - no other code change needed. See get_og_image() / get_logo_url().
DEFAULT_OG_IMAGE = f"{BASE_URL}/images/og-default.jpg"
OG_IMAGE_BY_MFR = {}
GA_MEASUREMENT_ID = "G-3XMG9G84HQ"   # same GA4 property as the interactive app (index.html),
                                     # so static-page and app traffic land in one place
ROOT      = os.path.dirname(os.path.abspath(__file__))
DATA      = os.path.join(ROOT, "products.json")
NEWS_DATA = os.path.join(ROOT, "news.json")
TODAY     = datetime.date.today().isoformat()

GENERATED_DIRS = ["products", "manufacturers", "types", "knowledge", "best", "heat-pump-size-calculator", "news"]

TYPE_LABEL = {"ASHP": "Air Source (ASHP)", "GSHP": "Ground Source (GSHP)",
              "WSHP": "Water Source (WSHP)"}

# Legacy category-page slugs from an earlier version of the site's refrigerant
# grouping (compound "X/Y option" categories, before it settled on one page
# per single refrigerant value). Google still has some of these indexed from
# years back; rather than let them hard-404, redirect each to today's closest
# equivalent single-refrigerant category page. Checked against GSC's 404
# coverage report (2026-08-05) — every target here is confirmed to still be
# generated. If a target ever stops being generated, main() silently skips
# writing that one redirect rather than pointing at nothing.
LEGACY_TYPE_REDIRECTS = {
    "r1234ze-e-r515b-option-heat-pumps": "r1234ze-heat-pumps",
    "r1234ze-r515b-option-heat-pumps": "r1234ze-heat-pumps",
    "r32-low-gwp-heat-pumps": "r32-heat-pumps",
    "r1233zd-e-heat-pumps": "r1233zd-heat-pumps",
    "r513a-r134a-option-heat-pumps": "r513a-heat-pumps",
    "r134a-r1234ze-option-heat-pumps": "r134a-heat-pumps",
}

# ───────────────────────── Helpers ─────────────────────────
def slugify(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-") or "item"

def esc(s):
    return html.escape(str(s), quote=True)

def track_attr(*args):
    """Build an onclick="trackOut(...)" attribute value that is safe to embed in an
    HTML attribute: each arg is JSON-encoded (so strings/None become valid JS literals),
    then the whole onclick expression is HTML-escaped so embedded quotes can't break out
    of the surrounding attribute."""
    js_arglist = ",".join(json.dumps(a, ensure_ascii=False) for a in args)
    return esc(f"trackOut({js_arglist})")

def num(x):
    """Trim trailing .0 from whole-number floats for display."""
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)

def cap_str(p):
    lo, hi = p.get("cap_min"), p.get("cap_max")
    if hi is None and lo is None: return None
    if lo is not None and hi is not None and lo != hi:
        return f"{num(lo)}\u2013{num(hi)} kW"
    return f"{num(hi if hi is not None else lo)} kW"

def temp_cond_str(v):
    """Format a max_heat/cool_capacity_temp value \u2014 either a plain outdoor temp
    number (e.g. -3) or a full condition string (e.g. 'A-7/W35')."""
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return f" at {num(v)}\u00b0C"
    s = str(v).strip()
    if not s:
        return ""
    if "/" in s or any(c.isalpha() for c in s):
        return f" at {s}"
    return f" at {s}\u00b0C"

def range_str(lo, hi, unit, joiner="\u2013"):
    if lo is None and hi is None: return None
    if lo is not None and hi is not None:
        return f"{num(lo)}{joiner}{num(hi)} {unit}"
    v = hi if hi is not None else lo
    return f"{'up to ' if hi is not None else 'from '}{num(v)} {unit}"

def derive_range(model):
    """Normalise a product's model string down to its model range/series name,
    by stripping a trailing capacity token (e.g. ', 13kW' or ' 13kW') and/or a
    trailing voltage parenthetical (e.g. ' (400V)'). Many manufacturers embed
    the capacity variant directly in the model string (Baxi 'HP60 High Monobloc,
    13kW', Bosch 'Compress 2000 AWF 10kW (230V)'), so without this, otherwise-
    identical ranges would be treated as distinct products for review-matching
    purposes. Used only to key into REVIEWS_BY_RANGE below - not stored or shown
    anywhere else, so it's safe to be a best-effort heuristic rather than a
    curated field.
    """
    s = model or ""
    s = re.sub(r'\s*\(\d{2,3}V\)\s*$', '', s)
    s = re.sub(r'[,]?\s*\d+(\.\d+)?\s*kW\s*$', '', s)
    s = re.sub(r'\s*\(\d{2,3}V\)\s*$', '', s)
    s = s.strip().rstrip(',').strip()
    return s if s else (model or "")

def load_reviews():
    """Load the manually-curated reviews.json (list of {manufacturer, range,
    type, title, source, url, date, note}) and index it by (manufacturer,
    derived range). type is one of 'review_article', 'news_article', 'youtube'.
    Missing/unreadable file -> no reviews shown anywhere, site still builds fine.
    """
    path = os.path.join(ROOT, "reviews.json")
    if not os.path.exists(path):
        return {}
    try:
        entries = json.load(open(path, encoding="utf-8"))
    except Exception:
        return {}
    idx = {}
    for e in entries:
        key = (e.get("manufacturer", "").strip(), e.get("range", "").strip())
        idx.setdefault(key, []).append(e)
    return idx

REVIEWS_BY_RANGE = load_reviews()

_YT_ID_RE = re.compile(
    r'(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_-]{6,})'
)

def youtube_thumb(url):
    m = _YT_ID_RE.search(url or "")
    if not m:
        return None
    return f"https://i.ytimg.com/vi/{m.group(1)}/hqdefault.jpg"

def render_reviews(p):
    key = (p.get("manufacturer", "").strip(), derive_range(p.get("model")).strip())
    entries = REVIEWS_BY_RANGE.get(key)
    if not entries:
        return ""
    pid, mfr, model = p.get("id"), p.get("manufacturer"), p.get("model")

    articles = [e for e in entries if e.get("type") in ("review_article", "news_article")]
    videos = [e for e in entries if e.get("type") == "youtube"]

    out = ['<h2 class="sec">Reviews &amp; further reading</h2>']

    if articles:
        rows = []
        for e in articles:
            tag = "Review" if e.get("type") == "review_article" else "News"
            onclick = track_attr("review", pid, mfr, model, e.get("source"))
            date_bit = f' <span class="rv-date">{esc(e["date"][:7])}</span>' if e.get("date") else ""
            note_bit = f'<div class="rv-note">{esc(e["note"])}</div>' if e.get("note") else ""
            rows.append(
                f'<li class="rv-item"><span class="rv-tag rv-tag-{esc(e.get("type"))}">{tag}</span> '
                f'<a href="{esc(e["url"])}" target="_blank" rel="nofollow noopener" onclick="{onclick}">'
                f'{esc(e.get("title") or e.get("source") or "Read more")}</a>'
                f' <span class="rv-source">&mdash; {esc(e.get("source",""))}</span>{date_bit}{note_bit}</li>'
            )
        out.append(f'<ul class="rv-list">{"".join(rows)}</ul>')

    if videos:
        cards = []
        for e in videos:
            thumb = youtube_thumb(e.get("url"))
            if not thumb:
                continue
            onclick = track_attr("youtube", pid, mfr, model, e.get("source"))
            date_bit = f'<div class="yt-date">{esc(e["date"][:7])}</div>' if e.get("date") else ""
            cards.append(
                f'<a class="yt-card" href="{esc(e["url"])}" target="_blank" rel="nofollow noopener" onclick="{onclick}">'
                f'<span class="yt-thumb-wrap"><img class="yt-thumb" src="{esc(thumb)}" alt="" loading="lazy" width="320" height="180">'
                f'<span class="yt-play">&#9658;</span></span>'
                f'<span class="yt-title">{esc(e.get("title") or e.get("source") or "Watch on YouTube")}</span>'
                f'<span class="yt-source">{esc(e.get("source",""))}</span>{date_bit}</a>'
            )
        if cards:
            out.append(f'<div class="yt-grid">{"".join(cards)}</div>')

    return "".join(out)

def spec_rows(p):
    """Ordered (label, value) pairs for the spec table — only populated fields."""
    rows = []
    add = lambda l, v: rows.append((l, v)) if v not in (None, "", "null") else None
    add("Manufacturer", esc(p.get("manufacturer")))
    add("Model", esc(p.get("model")))
    add("Model code", esc(p.get("product_code")))
    if p.get("hp_type"): add("Heat pump type", esc(TYPE_LABEL.get(p["hp_type"], p["hp_type"])))
    add("Application", esc(p.get("type")))
    add("Refrigerant", esc(p.get("refrigerant")))
    add("Mode", esc(p.get("mode")))
    add("Heating capacity", cap_str(p))
    if p.get("max_heat_capacity") is not None:
        add("Max heating output (low temp)", f"{num(p['max_heat_capacity'])} kW{esc(temp_cond_str(p.get('max_heat_capacity_temp')))}")
    if p.get("cop") is not None:
        cc = f" at {esc(p['cop_cond'])}" if p.get("cop_cond") else ""
        add("COP (heating)", f"{num(p['cop'])}{cc}")
    if p.get("scop") is not None:
        sc = p.get("scop_cond")
        if sc and sc != "not stated":
            add("SCOP (heating)", f"{num(p['scop'])} at {esc(sc)}")
        else:
            add("SCOP (heating)", f"{num(p['scop'])} (conditions not stated)")
    add("Operating range (air)", range_str(p.get("op_temp_min"), p.get("op_temp_max"), "\u00b0C", " to "))
    add("Heating flow temperature", range_str(p.get("flow_temp_min"), p.get("flow_temp_max"), "\u00b0C"))
    if p.get("peak_elec") is not None: add("Power input", f"{num(p['peak_elec'])} kW")
    if p.get("electrical"): add("Electrical supply", esc(p["electrical"]))
    # Cooling
    clo, chi = p.get("cool_cap_min"), p.get("cool_cap_max")
    if clo is not None or chi is not None:
        add("Cooling capacity", range_str(clo, chi, " kW") if (clo is not None and chi is not None) else f"{num(chi if chi is not None else clo)} kW")
    if p.get("max_cool_capacity") is not None:
        add("Max cooling output (high temp)", f"{num(p['max_cool_capacity'])} kW{esc(temp_cond_str(p.get('max_cool_capacity_temp')))}")
    add("Cooling flow temperature", range_str(p.get("cool_flow_temp_min"), p.get("cool_flow_temp_max"), "\u00b0C"))
    if p.get("eer") is not None:
        ec = f" at {esc(p['eer_cond'])}" if p.get("eer_cond") else ""
        add("EER (cooling)", f"{num(p['eer'])}{ec}")
    if p.get("seer") is not None:
        sec = f" at {esc(p['seer_cond'])}" if p.get("seer_cond") else ""
        add("SEER (cooling)", f"{num(p['seer'])}{sec}")
    if any(p.get(k) is not None for k in ("height", "width", "depth")):
        h, w, d = p.get("height"), p.get("width"), p.get("depth")
        dims = " \u00d7 ".join(num(x) for x in (h, w, d) if x is not None)
        add("Dimensions (H\u00d7W\u00d7D)", f"{dims} mm")
    if p.get("weight") is not None: add("Operational Weight", f"{num(p['weight'])} kg")
    if p.get("noise") is not None:
        ref = f" ({esc(p['noise_ref'])})" if p.get("noise_ref") else ""
        add("Sound power level", f"{num(p['noise'])} dB(A){ref}")
    if p.get("price_min") is not None:
        checked = f" (checked {esc(p['price_check_date'])})" if p.get("price_check_date") else ""
        if p.get("price_max") is None or p["price_min"] == p["price_max"]:
            add("Price (unit only)", f"~£{num(p['price_min'])}{checked}")
        else:
            add("Price (unit only)", f"£{num(p['price_min'])}&ndash;£{num(p['price_max'])}{checked}")
    add("Data added", esc(p.get("date_added")))
    add("Data source", esc(p.get("source")))
    if p.get("mcs_listed"):
        add("MCS certification", "&#10003; MCS listed &mdash; eligible for Boiler Upgrade Scheme (MCS-certified install required)")
        if p.get("mcs_cert"): add("MCS certificate no.", esc(p["mcs_cert"]))
        if p.get("mcs_url"):
            add("MCS listing", f'<a href="{esc(p["mcs_url"])}" target="_blank" rel="noopener nofollow">View on MCS &#8599;</a>')
    if p.get("heatpumpmonitor_url"):
        add("Real-world performance data", f'<a href="{esc(p["heatpumpmonitor_url"])}" target="_blank" rel="noopener nofollow">View on HeatpumpMonitor.org &#8599;</a>')
    return rows

# ───────────────────────── HTML shell ─────────────────────────
MFR_FILTER_CSS = """
/* ── Manufacturers page filters ── */
.flag-icon{width:16px;height:12px;vertical-align:-1.5px;border-radius:2px;box-shadow:0 0 0 1px rgba(0,0,0,.06)}
.mfr-filter-bar{background:#fff;border:1px solid #e2e8e7;border-radius:12px;padding:16px 18px;margin-bottom:20px}
.mfr-filter-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.mfr-filter-col label.filter-label{display:block;font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:#5b6b6b;font-weight:600;margin-bottom:5px}
.mfr-filter-col select.filt{width:100%;padding:9px 12px;border:1px solid #e2e8e7;border-radius:8px;font-size:13px;font-family:'Inter',sans-serif;background:#fff;color:#16302f;cursor:pointer;appearance:auto}
.mfr-filter-col select.filt:focus{border-color:#3ECCC0;outline:none}
.f-slider-val{font-size:11px;color:#0D7377;font-weight:600;float:right;text-transform:none;letter-spacing:0}
.range-wrap{position:relative;height:30px;margin-top:2px}
.range-wrap.focus .range-thumb{box-shadow:0 0 0 4px rgba(62,204,192,.35)}
.range-track{position:absolute;top:13px;left:5%;right:5%;height:4px;background:#eef2f1;border-radius:3px}
.range-fill{position:absolute;top:13px;height:4px;background:#3ECCC0;border-radius:3px}
.range-thumb{position:absolute;top:7px;width:16px;height:16px;border-radius:50%;background:#fff;border:2.5px solid #0D7377;box-shadow:0 1px 3px rgba(0,0,0,.18);transform:translateX(-50%);pointer-events:none;box-sizing:border-box}
.range-wrap input[type=range]{position:absolute;top:0;left:0;width:100%;height:30px;margin:0;opacity:0;pointer-events:none;-webkit-appearance:none;appearance:none}
.range-wrap input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;width:24px;height:30px;pointer-events:auto;cursor:pointer}
.range-wrap input[type=range]::-moz-range-thumb{width:24px;height:30px;pointer-events:auto;cursor:pointer;border:none;background:transparent}
.mfr-filter-footer{display:flex;align-items:center;justify-content:space-between;margin-top:14px;padding-top:12px;border-top:1px solid #eef2f1}
#mf-count{font-size:12.5px;color:#5b6b6b}
.mf-clear-btn{background:none;border:1px solid #e2e8e7;color:#42514f;font-size:12.5px;padding:6px 12px;border-radius:7px;cursor:pointer;font-family:'Inter',sans-serif}
.mf-clear-btn:hover{border-color:#3ECCC0;color:#0D7377}
.mfr-empty{display:none;color:#5b6b6b;font-size:14px;padding:32px 0;text-align:center}
.news-filter{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 22px}
.news-chip{background:#fff;border:1px solid #e2e8e7;color:#42514f;font-family:'Inter',sans-serif;font-size:13px;font-weight:600;padding:7px 15px;border-radius:20px;cursor:pointer;transition:all .15s}
.news-chip:hover{border-color:#3ECCC0;color:#0D7377}
.news-chip.active{background:#0D7377;border-color:#0D7377;color:#fff}
.news-chip .nf-n{font-weight:500;opacity:.65;margin-left:6px}
.news-chip.is-empty{opacity:.5}
.news-empty{display:none;color:#5b6b6b;font-size:14px;padding:34px 0;text-align:center}
@media(max-width:720px){.mfr-filter-grid{grid-template-columns:1fr 1fr}}
@media(max-width:480px){.mfr-filter-grid{grid-template-columns:1fr}}

"""

MFR_FILTER_JS = """
(function(){
  var CAP_STOPS=[0,1,2,3,4,5,6,8,10,12,15,20,25,30,40,50,60,80,100,150,200,300,400,500,700,1000];
  var SF={capLo:0,capHi:1000};
  function capFromIdx(i){return CAP_STOPS[Math.max(0,Math.min(CAP_STOPS.length-1,i))];}
  function mkDual(el,vEl){
    var n=CAP_STOPS.length-1;
    el.innerHTML='<div class="range-track"></div><div class="range-fill"></div><div class="range-thumb"></div><div class="range-thumb"></div>'+
      '<input type="range" min="0" max="'+n+'" step="1" value="0" aria-label="Minimum heating capacity">'+
      '<input type="range" min="0" max="'+n+'" step="1" value="'+n+'" aria-label="Maximum heating capacity">';
    var inputs=el.querySelectorAll('input'),lo=inputs[0],hi=inputs[1],fill=el.querySelector('.range-fill'),thumbs=el.querySelectorAll('.range-thumb'),t1=thumbs[0],t2=thumbs[1];
    function upd(fire){
      var a=Math.min(+lo.value,+hi.value),b=Math.max(+lo.value,+hi.value);
      var pa=5+a/n*90,pb=5+b/n*90;fill.style.left=pa+'%';fill.style.width=(pb-pa)+'%';
      t1.style.left=pa+'%';t2.style.left=pb+'%';
      SF.capLo=capFromIdx(a);SF.capHi=capFromIdx(b);
      vEl.textContent=(a===0&&b===n)?'Any':SF.capLo+'–'+(b===n?'1000+':SF.capHi)+' kW';
      if(fire)mfApplyFilters();
    }
    [lo,hi].forEach(function(i){
      i.addEventListener('input',function(){upd(true);});
      i.addEventListener('focus',function(){el.classList.add('focus');});
      i.addEventListener('blur',function(){el.classList.remove('focus');});
    });
    el._reset=function(){lo.value=0;hi.value=n;upd(false);};
    upd(false);
  }
  window.mfApplyFilters=function(){
    var typeSel=document.getElementById('mf-type'),mcsSel=document.getElementById('mf-mcs'),countrySel=document.getElementById('mf-country');
    if(!typeSel||!mcsSel||!countrySel)return;
    var type=typeSel.value,mcs=mcsSel.value,country=countrySel.value;
    var capActive=(SF.capLo>0||SF.capHi<1000);
    var cards=document.querySelectorAll('#mfr-grid .card');
    var shown=0;
    cards.forEach(function(c){
      var ok=true;
      if(type){
        var types=(c.getAttribute('data-types')||'').split(',');
        if(types.indexOf(type)===-1)ok=false;
      }
      if(ok&&mcs==='mcs'&&c.getAttribute('data-mcs')!=='1')ok=false;
      if(ok&&country&&c.getAttribute('data-country')!==country)ok=false;
      if(ok&&capActive){
        var loA=c.getAttribute('data-cap-lo'),hiA=c.getAttribute('data-cap-hi');
        if(loA===''||hiA===''||loA===null||hiA===null){
          ok=false;
        }else{
          var lo=+loA,hi=+hiA;
          if(hi<SF.capLo)ok=false;
          if(SF.capHi<1000&&lo>SF.capHi)ok=false;
        }
      }
      c.style.display=ok?'':'none';
      if(ok)shown++;
    });
    var countEl=document.getElementById('mf-count');
    if(countEl)countEl.textContent=shown+' manufacturer'+(shown!==1?'s':'')+(shown!==cards.length?' of '+cards.length:'');
    var emptyEl=document.getElementById('mfr-empty');
    if(emptyEl)emptyEl.style.display=shown===0?'block':'none';
  };
  window.mfClearFilters=function(){
    var typeSel=document.getElementById('mf-type'),mcsSel=document.getElementById('mf-mcs'),countrySel=document.getElementById('mf-country');
    if(typeSel)typeSel.value='';
    if(mcsSel)mcsSel.value='';
    if(countrySel)countrySel.value='';
    var sl=document.getElementById('mf-sl-cap');
    if(sl&&sl._reset)sl._reset();
    mfApplyFilters();
  };
  function init(){
    var sl=document.getElementById('mf-sl-cap');
    if(!sl||sl._init)return;
    sl._init=true;
    mkDual(sl,document.getElementById('mf-sv-cap'));
    mfApplyFilters();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);
  else init();
})();
"""

CALC_CSS = """
/* ── Heat pump size calculator ── */
.dm-tabs{display:flex;gap:8px;margin:18px 0 22px;border-bottom:1px solid #e2e8e7}
.dm-tab{background:none;border:none;padding:10px 4px;margin-right:22px;font-size:14.5px;font-weight:600;color:#7a8a88;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px;font-family:'Inter',sans-serif}
.dm-tab.active{color:#0D7377;border-bottom-color:#0D7377}
.dm-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px;margin-bottom:8px}
.dm-field label{display:block;font-size:12.5px;font-weight:600;color:#42514f;margin-bottom:6px}
.dm-field input[type=number],.dm-field select{width:100%;height:40px;padding:9px 12px;border:1px solid #e2e8e7;border-radius:10px;font-size:13.5px;font-family:'Inter',sans-serif;background:#fff;color:#0F2B2B;box-sizing:border-box;line-height:1.2;appearance:auto}
.dm-check-row{display:flex;align-items:center;gap:8px;font-size:13.5px;color:#42514f;margin-top:10px}
.dm-check-row input{width:16px;height:16px;flex:none}
.dm-results{background:#064E50;color:#fff;border-radius:16px;padding:26px 28px;margin:26px 0}
.dm-result-row{display:flex;flex-wrap:wrap;gap:28px;margin-bottom:2px}
.dm-result-block{flex:1 1 200px;min-width:170px}
.dm-result-label{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:rgba(255,255,255,.6);margin-bottom:4px}
.dm-result-value{font-size:30px;font-weight:700;letter-spacing:-.02em}
.dm-result-sub{font-size:12.5px;color:rgba(255,255,255,.65);margin-top:6px}
.dm-hint{font-size:11.5px;color:#7a8a88;line-height:1.5;margin-top:5px}
.dm-note{font-size:12.5px;color:#7a8a88;line-height:1.6;margin:14px 0}
.dm-assumptions{background:#f3f7f6;border-radius:10px;padding:14px 18px;font-size:12.5px;color:#42514f;line-height:1.7;margin:18px 0}
.dm-rec-group-label{font-size:13.5px;font-weight:600;color:#42514f;margin:18px 0 10px}
.dm-rec-group-label:first-child{margin-top:0}
.dm-rec-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px;margin-bottom:6px}
.dm-rec-empty{color:#7a8a88;font-size:13px;margin-bottom:6px}
.dm-rec-card{display:block;background:#fff;border:1px solid #e2e8e7;border-radius:12px;padding:16px 18px;text-decoration:none;color:inherit;transition:border-color .15s,box-shadow .15s}
.dm-rec-card:hover{border-color:#3ECCC0;box-shadow:0 6px 22px rgba(15,43,43,.08);text-decoration:none}
.dm-rec-card-brand{font-size:12px;color:#7a8a88;text-transform:uppercase;letter-spacing:.03em;font-weight:600}
.dm-rec-card-name{font-size:15px;font-weight:600;color:#0F2B2B;margin-top:2px}
.dm-rec-card-badges{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}
.dm-badge{background:#e7f4f2;color:#0c6f66;border:1px solid #cde9e5;border-radius:999px;padding:3px 10px;font-size:11.5px;font-weight:500}
.dm-badge-ref{background:#f3f7f6;color:#42514f;border-color:#e2e8e7}
.dm-rec-card-specs{display:flex;gap:14px;margin-top:10px;font-size:12.5px;color:#42514f;flex-wrap:wrap}
.dm-rec-card-price{margin-top:8px;font-size:13px;color:#0D7377;font-weight:600}
.dm-rec-card-link{margin-top:10px;font-size:12.5px;color:#0D7377;font-weight:600}
@media (max-width:640px){.dm-result-value{font-size:24px}.dm-results{padding:20px}}
"""

CSS = """
/* ── Best-of ranking pages ── */
.best-toc{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 28px}
.best-toc a{display:inline-block;background:#e7f4f2;color:#0c6f66;border:1px solid #cde9e5;border-radius:999px;padding:5px 14px;font-size:13px;font-weight:500;text-decoration:none}
.best-toc a:hover{background:#d4ece7}
.best-section{margin-bottom:44px;padding-top:8px;scroll-margin-top:80px}
.best-section:not(:last-of-type){border-bottom:1px solid #e2e8e7;padding-bottom:36px}
.composite-sub{font-size:11.5px;color:#8a9694;font-weight:400}
.best-winner{display:flex;align-items:center;gap:18px;background:linear-gradient(135deg,#0F2B2B,#14403d);border-radius:14px;padding:20px 24px;margin:6px 0 24px;color:#fff}
.best-winner img{width:56px;height:56px;border-radius:10px;background:#fff;object-fit:contain;padding:6px;flex:none}
.best-winner .bw-crown{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#3ECCC0;font-weight:600;margin-bottom:2px}
.best-winner .bw-name{font-size:19px;font-weight:600;letter-spacing:-.01em}.best-winner .bw-name a{color:#fff}
.best-winner .bw-val{margin-left:auto;text-align:right;flex:none}
.best-winner .bw-num{font-size:26px;font-weight:700;color:#3ECCC0;line-height:1.1}
.best-winner .bw-lab{font-size:12px;color:rgba(255,255,255,.55)}
.best-scroll{overflow-x:auto;border-radius:12px;border:1px solid #e2e8e7}
.best-scroll table.list{border:none;margin:0;min-width:640px}
table.best-table th{position:sticky;top:0;background:#fafcfb;z-index:1}
table.best-table tr:nth-child(even) td{background:#fafcfb}
table.best-table tr:hover td{background:#eef7f5}
td.rank{width:44px;text-align:center}
.rank-badge{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:50%;font-weight:600;font-size:13px;color:#42514f;background:#eef2f1}
.rank-1 .rank-badge{background:#f6d873;color:#5c4a00}
.rank-2 .rank-badge{background:#dfe4e6;color:#454d50}
.rank-3 .rank-badge{background:#e8c39e;color:#5e3c14}
.best-model{display:flex;align-items:center;gap:10px}
.best-model img{width:26px;height:26px;border-radius:6px;object-fit:contain;background:#fff;border:1px solid #eef2f1;flex:none}
.metric-cell{min-width:120px}
.metric-val{font-weight:600}
.metric-bar{height:5px;border-radius:3px;background:#e7f0ee;margin-top:5px;overflow:hidden}
.metric-bar i{display:block;height:100%;border-radius:3px;background:linear-gradient(90deg,#3ECCC0,#0f8a80)}
.hub-leader{font-size:12.5px;color:#0c6f66;margin-top:4px}

*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#16302f;background:#f6f9f8;line-height:1.6;-webkit-font-smoothing:antialiased}
a{color:#0f8a80;text-decoration:none}a:hover{text-decoration:underline}
header.site{background:#0F2B2B;height:60px;display:flex;align-items:center}
header.site .wrap{display:flex;align-items:center;width:100%}
header.site .brand{display:flex;align-items:center;gap:10px;text-decoration:none;font-family:'Inter',system-ui,sans-serif;font-size:19px;letter-spacing:-.03em;margin-right:auto}
header.site .brand:hover{text-decoration:none}
.wm-bold{color:#3ECCC0;font-weight:700}
.wm-light{color:rgba(255,255,255,.55);font-weight:300;margin-left:2px}
.burger{background:none;border:none;cursor:pointer;display:flex;flex-direction:column;gap:5px;padding:8px;margin-left:16px;position:relative;z-index:52}
.burger span{display:block;width:22px;height:2px;background:#fff;border-radius:2px;transition:all .3s}
.burger.open span:nth-child(1){transform:rotate(45deg) translate(5px,5px)}
.burger.open span:nth-child(2){opacity:0}
.burger.open span:nth-child(3){transform:rotate(-45deg) translate(5px,-5px)}
.burger-menu{position:fixed;top:60px;right:0;width:280px;background:#0F2B2B;border-left:1px solid rgba(255,255,255,.08);box-shadow:-8px 0 40px rgba(0,0,0,.3);transform:translateX(100%);transition:transform .3s ease;z-index:51;display:flex;flex-direction:column;max-height:calc(100vh - 60px);overflow-y:auto;-webkit-overflow-scrolling:touch;overscroll-behavior:contain}
.burger-menu.open{transform:translateX(0)}
.burger-item{background:none;border:none;color:rgba(255,255,255,.6);font-size:15px;font-family:'Inter',sans-serif;font-weight:400;padding:16px 28px;text-align:left;transition:all .2s;border-bottom:1px solid rgba(255,255,255,.05);letter-spacing:.01em;width:100%;display:block;text-decoration:none;box-sizing:border-box}
.burger-item:hover{background:rgba(255,255,255,.05);color:#fff;text-decoration:none}
.burger-item.active{color:#3ECCC0;font-weight:500}
.burger-subitem{padding-left:50px;font-size:14px;position:relative}
.burger-subitem::before{content:"";position:absolute;left:30px;top:50%;width:9px;height:1px;background:rgba(255,255,255,.28)}.burger-toggle{display:flex;align-items:center;justify-content:space-between}.burger-chevron{width:8px;height:8px;border-right:1.5px solid currentColor;border-bottom:1.5px solid currentColor;transform:rotate(45deg);transition:transform .25s ease;flex:none;margin-left:8px;opacity:.55}.burger-toggle.open .burger-chevron{transform:rotate(-135deg)}.burger-subgroup{max-height:0;overflow:hidden;transition:max-height .3s ease;flex-shrink:0}.burger-subgroup.open{max-height:1000px}.burger-menu>.burger-item,.burger-menu>.burger-subgroup{flex-shrink:0}
.burger-overlay{position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:49;opacity:0;pointer-events:none;transition:opacity .3s}
.burger-overlay.open{opacity:1;pointer-events:auto}
@media(max-width:560px){.burger-menu{width:100%}}
.wrap{max-width:960px;margin:0 auto;padding:0 20px}
main{padding:28px 0 56px}
nav.crumbs{font-size:13px;color:#5b6b6b;margin-bottom:18px}
nav.crumbs a{color:#5b6b6b}nav.crumbs span{color:#9aa}
h1{font-size:28px;letter-spacing:-.02em;line-height:1.2;margin-bottom:6px}
.sub{color:#5b6b6b;font-size:15px;margin-bottom:24px}
.badges{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 26px}
.badge{background:#e7f4f2;color:#0c6f66;border:1px solid #cde9e5;border-radius:999px;padding:4px 12px;font-size:13px;font-weight:500}
table.spec{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e2e8e7;border-radius:12px;overflow:hidden}
table.spec th,table.spec td{text-align:left;padding:11px 16px;border-bottom:1px solid #eef2f1;font-size:14.5px;vertical-align:top}
table.spec th{width:42%;color:#42514f;font-weight:500;background:#fafcfb}
table.spec tr:last-child th,table.spec tr:last-child td{border-bottom:none}
.notes{background:#fff;border:1px solid #e2e8e7;border-radius:12px;padding:18px 20px;margin-top:18px;font-size:14.5px;color:#34433f}
.article-body{max-width:720px}
.article-body h2{font-size:20px;letter-spacing:-.01em;margin:30px 0 12px;color:#0F2B2B}
.article-body h3{font-size:16px;margin:22px 0 10px;color:#0F2B2B}
.article-body p{color:#5b6b6b;font-size:14.5px;line-height:1.7;margin:0 0 14px}
.article-body strong{color:#16302f}
.article-body table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e2e8e7;border-radius:12px;overflow:hidden;font-size:13.5px;margin:0 0 18px}
.article-body th{text-align:left;padding:10px 14px;border-bottom:1px solid #eef2f1;background:#fafcfb;color:#42514f;font-weight:600}
.article-body td{padding:9px 14px;border-bottom:1px solid #eef2f1}
.article-body .callout{background:#fff;border:1px solid #e2e8e7;border-left:4px solid #3ECCC0;border-radius:8px;padding:16px 20px;margin:0 0 20px;font-size:14px;color:#34433f}
.article-meta{display:flex;gap:10px;align-items:center;font-size:12.5px;color:#8a9694;flex-wrap:wrap}
.article-hero{margin:18px 0 26px;border-radius:14px;overflow:hidden;border:1px solid #e2e8e7;max-width:760px}.article-hero img{width:100%;display:block;cursor:zoom-in}.article-hero-credit{padding:9px 14px;font-size:12px;color:#8a9694;background:#fafcfb;border-top:1px solid #eef2f1;display:flex;gap:12px;align-items:baseline;justify-content:space-between}.article-hero-zoom{flex-shrink:0;color:#0D7377;font-weight:600;white-space:nowrap}.article-tldr{max-width:760px;margin:0 0 24px;background:#f2fbfa;border:1px solid #cdeae6;border-left:4px solid #0D7377;border-radius:10px;padding:14px 20px;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}.article-tldr-label{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:#0D7377;flex-shrink:0}.article-tldr p{margin:0;color:#34433f;font-size:14px;line-height:1.6;flex:1;min-width:200px}
.article-cat{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.03em}
.article-cat-insight{background:#e6f4f3;color:#0D7377}
.article-cat-product{background:#fdf1e0;color:#a3660a}
.article-cat-update{background:#e8eef5;color:#2b5a8a}
.news-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}
.news-card{display:block;background:#fff;border:1px solid #e2e8e7;border-radius:12px;padding:18px 20px;transition:border-color .15s,box-shadow .15s;text-decoration:none}
.news-card:hover{border-color:#3ECCC0;box-shadow:0 6px 22px rgba(15,43,43,.07)}
.news-card h3{font-size:16px;margin:8px 0 6px;color:#0F2B2B}
.news-card p{font-size:13.5px;color:#5b6b6b;line-height:1.6;margin:0}
.news-list{display:flex;flex-direction:column;gap:18px}
.news-row{display:flex;gap:22px;background:#fff;border:1px solid #e2e8e7;border-radius:14px;padding:18px;text-decoration:none;transition:border-color .15s,box-shadow .15s}
.news-row:hover{border-color:#3ECCC0;box-shadow:0 6px 22px rgba(15,43,43,.07)}
.news-row-thumb{flex:0 0 260px;width:260px;height:170px;border-radius:10px;overflow:hidden;background:#eef3f2;display:flex;align-items:center;justify-content:center}
.news-row-thumb img{width:100%;height:100%;object-fit:cover;display:block}
.news-row-thumb.placeholder{color:#9fb0af;font-size:13px;text-align:center;padding:0 16px}
.news-row-body{flex:1;min-width:0;display:flex;flex-direction:column;justify-content:center}
.news-row h3{font-size:20px;margin:8px 0 8px;color:#0F2B2B;letter-spacing:-.01em}
.news-row p{font-size:14.5px;color:#5b6b6b;line-height:1.65;margin:0}
@media (max-width:640px){.news-row{flex-direction:column}.news-row-thumb{width:100%;flex-basis:auto;height:180px}}
.notes h2{font-size:15px;margin-bottom:6px;color:#0F2B2B}
h2.sec{font-size:18px;margin:34px 0 12px;letter-spacing:-.01em}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
.card{display:block;background:#fff;border:1px solid #e2e8e7;border-radius:12px;padding:14px 16px;transition:border-color .15s,box-shadow .15s}
.card:hover{border-color:#3ECCC0;box-shadow:0 6px 22px rgba(15,43,43,.07);text-decoration:none}
.card .m{font-weight:600;color:#0F2B2B;font-size:14.5px;line-height:1.35}
.card .s{color:#5b6b6b;font-size:12.5px;margin-top:4px}
.card.has-logo{display:flex;gap:12px;align-items:flex-start}
.card .logo-thumb{width:40px;height:40px;border-radius:8px;object-fit:contain;background:#f3f7f6;border:1px solid #e2e8e7;padding:4px;flex-shrink:0}
.mfr-logo{width:64px;height:64px;border-radius:10px;object-fit:contain;background:#f3f7f6;border:1px solid #e2e8e7;padding:6px;margin-bottom:14px}
.mfr-logo-sm{width:32px;height:32px;border-radius:7px;object-fit:contain;background:#f3f7f6;border:1px solid #e2e8e7;padding:3px;vertical-align:middle;margin-right:8px}
.mfr-header{display:flex;align-items:center;gap:14px;margin-bottom:2px}
.product-photo-block{margin-bottom:20px;text-align:center}
.product-photo{max-width:360px;width:100%;height:auto;max-height:360px;object-fit:contain}
.photo-credit{font-size:11.5px;color:#8a9694;margin-top:8px}
.product-photo{cursor:zoom-in}
.product-photo-thumbs{display:flex;gap:8px;justify-content:center;flex-wrap:wrap;margin-top:10px}
.product-photo-thumb{width:52px;height:52px;object-fit:cover;border-radius:8px;border:2px solid #e2e8e7;cursor:pointer;opacity:.7;transition:opacity .15s,border-color .15s}
.product-photo-thumb:hover{opacity:1}
.product-photo-thumb.active{opacity:1;border-color:#0D7377}
.photo-lightbox{display:none;position:fixed;inset:0;background:rgba(15,43,43,.92);z-index:500;align-items:center;justify-content:center;padding:32px;cursor:zoom-out}
.photo-lightbox.open{display:flex}
.photo-lightbox img{max-width:92vw;max-height:88vh;object-fit:contain;box-shadow:0 20px 60px rgba(0,0,0,.4);border-radius:6px;cursor:default}
.photo-lightbox-close{position:fixed;top:18px;right:22px;background:rgba(255,255,255,.12);color:#fff;border:none;width:40px;height:40px;border-radius:50%;font-size:20px;cursor:pointer;line-height:1}
.trademark-note{font-size:11.5px;color:#8a9694;margin-top:26px;line-height:1.5}
table.list{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e2e8e7;border-radius:12px;overflow:hidden;font-size:14px}
table.list th,table.list td{padding:10px 14px;text-align:left;border-bottom:1px solid #eef2f1}
table.list th{background:#fafcfb;color:#42514f;font-weight:600;font-size:12.5px;text-transform:uppercase;letter-spacing:.03em}
table.list tr:last-child td{border-bottom:none}
table.list tr:hover td{background:#fafdfc}
table.list tr.grp-row td{background:#f3f7f6;font-weight:600;color:#0F2B2B;font-size:12.5px;text-transform:uppercase;letter-spacing:.02em;padding:8px 14px}
table.list tr.grp-row:hover td{background:#f3f7f6}
.cta{display:inline-block;margin-top:8px;background:#0F2B2B;color:#fff;padding:11px 20px;border-radius:10px;font-weight:600;font-size:14px}
.cta:hover{background:#16413f;text-decoration:none}
footer.site{border-top:1px solid #e2e8e7;padding:26px 0;color:#7a8a88;font-size:13px;margin-top:30px}
footer.site a{color:#7a8a88}
.disclaimer{background:#fff7ed;border:1px solid #fbe3c4;color:#92651f;border-radius:10px;padding:12px 16px;font-size:13px;margin:20px 0}
@media(max-width:560px){table.spec th{width:48%}h1{font-size:23px}}
/* ── Reviews & further reading (product pages) ── */
.rv-list{list-style:none;background:#fff;border:1px solid #e2e8e7;border-radius:12px;padding:4px 0;margin:0}
.rv-item{padding:12px 18px;border-bottom:1px solid #eef2f1;font-size:14.5px;line-height:1.5}
.rv-item:last-child{border-bottom:none}
.rv-tag{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.03em;text-transform:uppercase;padding:2px 8px;border-radius:999px;margin-right:6px;vertical-align:middle}
.rv-tag-review_article{background:#e7f4f2;color:#0c6f66}
.rv-tag-news_article{background:#eef2fb;color:#3b4fa3}
.rv-source{color:#5b6b6b;font-size:13px}
.rv-date{color:#9aa8a6;font-size:12.5px}
.rv-note{color:#5b6b6b;font-size:13px;margin-top:3px}
.yt-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,300px));gap:14px;margin-top:12px}
.yt-card{display:block;background:#fff;border:1px solid #e2e8e7;border-radius:12px;overflow:hidden;transition:border-color .15s,box-shadow .15s}
.yt-card:hover{border-color:#3ECCC0;box-shadow:0 6px 22px rgba(15,43,43,.07);text-decoration:none}
.yt-thumb-wrap{position:relative;display:block;background:#0F2B2B}
.yt-thumb{width:100%;aspect-ratio:16/9;object-fit:cover;display:block}
.yt-play{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:44px;height:44px;border-radius:50%;background:rgba(15,43,43,.75);color:#fff;display:flex;align-items:center;justify-content:center;font-size:16px;padding-left:3px}
.yt-title{display:block;padding:10px 14px 2px;font-weight:600;color:#0F2B2B;font-size:13.5px;line-height:1.35}
.yt-source{display:block;padding:0 14px;color:#5b6b6b;font-size:12.5px}
.yt-date{display:block;padding:2px 14px 12px;color:#9aa8a6;font-size:12px}
"""

def burger_menu(active=None):
    knowledge_active = active in ("what-is-a-heat-pump", "cop-scop", "flow-temp", "refrigerants", "install-costs", "funding", "planning", "faq", "guide", "links", "knowledge")
    def it(label, href, key=None, sub=False, extra=""):
        cls = "burger-item" + (" burger-subitem" if sub else "")
        if key == active or (key == "knowledge" and knowledge_active):
            cls += " active"
        return f'<a class="{cls}" href="{href}"{extra}>{label}</a>'
    k_open = " open" if knowledge_active else ""
    k_expanded = "true" if knowledge_active else "false"
    k_cls = "burger-item burger-toggle" + (" active" if knowledge_active else "")
    knowledge_block = (
        f'<button class="{k_cls}{k_open}" id="k-toggle" aria-expanded="{k_expanded}" aria-controls="k-group" onclick="toggleKnowledge()">'
        f'Knowledge<span class="burger-chevron" aria-hidden="true"></span></button>'
        f'<div class="burger-subgroup{k_open}" id="k-group">'
        + it("What Is a Heat Pump?", f"{BASE_URL}/knowledge/what-is-a-heat-pump/", "what-is-a-heat-pump", sub=True)
        + it("Installation Costs", f"{BASE_URL}/knowledge/installation-costs/", "install-costs", sub=True)
        + it("Funding &amp; Grants", f"{BASE_URL}/knowledge/funding/", "funding", sub=True)
        + it("Planning Permission", f"{BASE_URL}/knowledge/planning-permission/", "planning", sub=True)
        + it("Understanding COP &amp; SCOP", f"{BASE_URL}/knowledge/cop-scop/", "cop-scop", sub=True)
        + it("Flow Temperature &amp; Efficiency", f"{BASE_URL}/knowledge/flow-temperature/", "flow-temp", sub=True)
        + it("Refrigerant Guide", f"{BASE_URL}/knowledge/refrigerants/", "refrigerants", sub=True)
        + it("FAQ", f"{BASE_URL}/#faq", "faq", sub=True)
        + it("Site Guide", f"{BASE_URL}/#guide", "guide", sub=True)
        + it("Useful Links", f"{BASE_URL}/#links", "links", sub=True)
        + '</div>'
    )
    c_active = active == "compare"
    c_open = " open" if c_active else ""
    c_cls = "burger-item burger-toggle" + (" active" if c_active else "")
    compare_block = (
        f'<button class="{c_cls}{c_open}" id="c-toggle" aria-expanded="{"true" if c_active else "false"}" aria-controls="c-group" onclick="toggleCompare()">'
        f'Compare<span class="burger-chevron" aria-hidden="true"></span></button>'
        f'<div class="burger-subgroup{c_open}" id="c-group">'
        + it("Compare Selected", f"{BASE_URL}/#compare", "compare", sub=True)
        + '</div>'
    )
    return (
        it("Browse", f"{BASE_URL}/", "browse")
        + it("Manufacturers", f"{BASE_URL}/manufacturers/", "manufacturers")
        + compare_block
        + it("Best Heat Pumps", f"{BASE_URL}/best/", "best")
        + it("Visualise", f"{BASE_URL}/#analytics", "analytics")
        + it("Size Calculator", f"{BASE_URL}/heat-pump-size-calculator/", "size-calc")
        + knowledge_block
        + it("News &amp; Insight", f"{BASE_URL}/news/", "news")
        + it("About &amp; Contact us", f"{BASE_URL}/#contact", "contact")
        + it("Terms of Use", f"{BASE_URL}/#terms", "terms",
             extra=' style="margin-top:auto;border-top:1px solid rgba(255,255,255,.08);font-size:12px;color:rgba(255,255,255,.35)"')
    )

def page(title, description, canonical, body, jsonld_list, og_type="website", active=None, og_image=None):
    blocks = "\n".join(
        '<script type="application/ld+json">%s</script>' % json.dumps(j, ensure_ascii=False)
        for j in jsonld_list
    )
    if og_image:
        og_image_tag = (f'<meta property="og:image" content="{og_image}">\n'
                         f'<meta property="og:image:width" content="1200">\n'
                         f'<meta property="og:image:height" content="630">\n'
                         f'<meta name="twitter:image" content="{og_image}">\n')
        twitter_card = "summary_large_image"
    else:
        og_image_tag = ""
        twitter_card = "summary"
    return f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="{og_type}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{canonical}">
<meta property="og:site_name" content="{SITE_NAME}">
{og_image_tag}<meta name="twitter:card" content="{twitter_card}">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="icon" type="image/png" sizes="96x96" href="/favicon-96.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style>
{blocks}
<script>
window.dataLayer=window.dataLayer||[];
window.gtag=function(){{dataLayer.push(arguments);}};
function loadGA(){{
  if(document.getElementById('ga-script'))return;
  var s=document.createElement('script');s.id='ga-script';s.async=true;
  s.src='https://www.googletagmanager.com/gtag/js?id={GA_MEASUREMENT_ID}';
  document.head.appendChild(s);
  gtag('js',new Date());
  gtag('config','{GA_MEASUREMENT_ID}');
}}
if(localStorage.getItem('cookie_consent')==='accepted')loadGA();
function acceptCookies(){{localStorage.setItem('cookie_consent','accepted');var b=document.getElementById('cookie-banner');if(b)b.style.display='none';loadGA();}}
function declineCookies(){{localStorage.setItem('cookie_consent','declined');var b=document.getElementById('cookie-banner');if(b)b.style.display='none';}}
function trackOut(){{
  if(typeof window.gtag!=='function'||localStorage.getItem('cookie_consent')!=='accepted')return;
  var a=Array.prototype.slice.call(arguments);
  window.gtag('event','outbound_click',{{link_type:a[0]||'unknown',product_id:a[1],manufacturer:a[2],model:a[3],retailer_name:a[4]||null,source:'static_page'}});
}}
</script>
</head>
<body>
<header class="site"><div class="wrap"><a class="brand" href="{BASE_URL}/">
<svg viewBox="0 0 28 28" width="26" height="26" fill="none" aria-hidden="true"><g transform="translate(14,14)"><circle r="12.5" stroke="#3ECCC0" stroke-width="1.2" opacity=".3"/><circle r="2" fill="#3ECCC0"/><path d="M0 -3 C-1 -6.5 -4 -9.5 -7 -11" stroke="#3ECCC0" stroke-width="1.8" stroke-linecap="round"/><path d="M0 -3 C-1 -6.5 -4 -9.5 -7 -11" stroke="#3ECCC0" stroke-width="1.8" stroke-linecap="round" transform="rotate(60)"/><path d="M0 -3 C-1 -6.5 -4 -9.5 -7 -11" stroke="#3ECCC0" stroke-width="1.8" stroke-linecap="round" transform="rotate(120)"/><path d="M0 -3 C-1 -6.5 -4 -9.5 -7 -11" stroke="#3ECCC0" stroke-width="1.8" stroke-linecap="round" transform="rotate(180)"/><path d="M0 -3 C-1 -6.5 -4 -9.5 -7 -11" stroke="#3ECCC0" stroke-width="1.8" stroke-linecap="round" transform="rotate(240)"/><path d="M0 -3 C-1 -6.5 -4 -9.5 -7 -11" stroke="#3ECCC0" stroke-width="1.8" stroke-linecap="round" transform="rotate(300)"/></g></svg>
<span><span class="wm-bold">Heat Pump</span><span class="wm-light">Database</span></span></a>
<button class="burger" id="bbtn" aria-label="Menu" onclick="tB()"><span></span><span></span><span></span></button>
<nav class="burger-menu" id="bmenu">{burger_menu(active)}</nav>
</div></header>
<div class="burger-overlay" id="bov" onclick="cB()"></div>
<div class="photo-lightbox" id="photo-lightbox" onclick="closePhotoLightbox()"><button class="photo-lightbox-close" onclick="event.stopPropagation();closePhotoLightbox()" aria-label="Close">&#10005;</button><img id="photo-lightbox-img" src="" alt="" onclick="event.stopPropagation()"></div>
<main><div class="wrap">
{body}
</div></main>
<footer class="site"><div class="wrap">
<p>{SITE_NAME} &middot; A searchable database of UK heat pumps. Always confirm specifications with the manufacturer before purchase.</p>
<p style="margin-top:6px"><a href="{BASE_URL}/">Search the full database</a> &middot; <a href="{BASE_URL}/manufacturers/">All manufacturers</a> &middot; <a href="{BASE_URL}/knowledge/what-is-a-heat-pump/">What is a heat pump?</a> &middot; <a href="{BASE_URL}/knowledge/installation-costs/">Installation costs</a> &middot; <a href="{BASE_URL}/knowledge/refrigerants/">Refrigerant guide</a> &middot; <a href="{BASE_URL}/knowledge/cop-scop/">COP &amp; SCOP</a> &middot; <a href="{BASE_URL}/knowledge/flow-temperature/">Flow temperature</a> &middot; <a href="{BASE_URL}/news/">News &amp; Insight</a></p>
</div></footer>
<div id="cookie-banner" style="display:none;position:fixed;bottom:0;left:0;right:0;background:#0F2B2B;color:#fff;padding:14px 24px;z-index:200;font-size:13px;line-height:1.5">
<div class="wrap" style="display:flex;gap:16px;align-items:center;justify-content:space-between;flex-wrap:wrap">
<span>This site uses cookies to help us understand how visitors use the site. No personal data is shared with third parties.</span>
<span style="display:flex;gap:8px;flex-shrink:0">
<button onclick="acceptCookies()" style="background:#3ECCC0;color:#0F2B2B;border:none;padding:8px 16px;border-radius:6px;font-weight:600;cursor:pointer">Accept</button>
<button onclick="declineCookies()" style="background:transparent;color:#fff;border:1px solid #3a5757;padding:8px 16px;border-radius:6px;cursor:pointer">Decline</button>
</span>
</div>
</div>
<script>function tB(){{['bbtn','bmenu','bov'].forEach(function(i){{document.getElementById(i).classList.toggle('open')}})}}function cB(){{['bbtn','bmenu','bov'].forEach(function(i){{document.getElementById(i).classList.remove('open')}})}}function toggleKnowledge(){{var t=document.getElementById('k-toggle'),g=document.getElementById('k-group');var open=!g.classList.contains('open');t.classList.toggle('open',open);g.classList.toggle('open',open);t.setAttribute('aria-expanded',open);}}function toggleCompare(){{var t=document.getElementById('c-toggle'),g=document.getElementById('c-group');var open=!g.classList.contains('open');t.classList.toggle('open',open);g.classList.toggle('open',open);t.setAttribute('aria-expanded',open);}}if(!localStorage.getItem('cookie_consent')){{var cb=document.getElementById('cookie-banner');if(cb)cb.style.display='block';}}function openPhotoLightbox(src,alt){{var lb=document.getElementById('photo-lightbox');var img=document.getElementById('photo-lightbox-img');img.src=src;img.alt=alt||'';lb.classList.add('open');document.body.style.overflow='hidden';}}function closePhotoLightbox(){{var lb=document.getElementById('photo-lightbox');lb.classList.remove('open');document.getElementById('photo-lightbox-img').src='';document.body.style.overflow='';}}document.addEventListener('keydown',function(e){{if(e.key==='Escape')closePhotoLightbox();}});</script>
</body>
</html>
"""

def crumbs(items):
    parts = []
    for i, (label, href) in enumerate(items):
        if href and i < len(items) - 1:
            parts.append(f'<a href="{href}">{esc(label)}</a>')
        else:
            parts.append(f'<span>{esc(label)}</span>')
    return '<nav class="crumbs">' + ' &rsaquo; '.join(parts) + '</nav>'

def breadcrumb_jsonld(items, self_url=None):
    out = []
    n = len(items)
    for i, (label, href) in enumerate(items):
        li = {"@type": "ListItem", "position": i + 1, "name": label}
        u = href or (self_url if i == n - 1 else None)
        if u:
            li["item"] = u
        out.append(li)
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": out}

# ───────────────────────── Page renderers ─────────────────────────
LOGO_SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logos")
LOGO_OUT_DIR = "images/manufacturers"
LOGO_EXT_PRIORITY = [".svg", ".png", ".webp", ".avif", ".jpg", ".jpeg", ".gif"]

# A small curated palette (not random/ugly hues) used to give each generated
# wordmark badge a distinct, deterministic background color per manufacturer.
BADGE_PALETTE = [
    "#0F2B2B", "#0f8a80", "#2b6cb0", "#6b46c1", "#b7402a",
    "#1f7a4d", "#a0522d", "#4a5568", "#2c7a7b", "#8a5a2b",
]

def _badge_color(name):
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return BADGE_PALETTE[h % len(BADGE_PALETTE)]

def _badge_label(name):
    """Short label for the generated badge: initials for multi-word names,
    first 4 chars for single-word names (keeps it legible at small sizes)."""
    words = [w for w in re.split(r"[\s-]+", name) if w]
    if len(words) >= 2:
        return "".join(w[0] for w in words[:3]).upper()
    return name[:4].upper()

def _badge_svg(name):
    color = _badge_color(name)
    label = esc(_badge_label(name))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">'
            f'<rect width="64" height="64" rx="12" fill="{color}"/>'
            f'<text x="32" y="40" font-family="Inter,Arial,sans-serif" font-size="22" '
            f'font-weight="700" fill="#fff" text-anchor="middle">{label}</text></svg>')

_LOGO_CACHE = {}

def get_og_image(mfr=None):
    """Return the social-share (og:image) URL for a page. Looks up a per-
    manufacturer/product-range override in OG_IMAGE_BY_MFR first, falling back
    to the site-wide default photo. Adding a real per-range image later requires
    no code change - just add the file under images/ and register it in
    OG_IMAGE_BY_MFR, mirroring get_logo_url() below.
    """
    if mfr and mfr in OG_IMAGE_BY_MFR:
        return f"{BASE_URL}/{OG_IMAGE_BY_MFR[mfr]}"
    return DEFAULT_OG_IMAGE

def get_logo_url(mfr):
    """Return the site-relative URL for a manufacturer's logo, writing the file
    into the build output the first time it's needed. Prefers a real logo file
    dropped in ./logos/{slug}.{ext} (svg/png/webp/jpg, checked in that order);
    falls back to a generated text/wordmark badge (no external assets, no
    copyright exposure) so every manufacturer always has *something* to show.
    Swapping in a real logo later requires no code change - just add the file
    and rebuild.
    """
    if mfr in _LOGO_CACHE:
        return _LOGO_CACHE[mfr]
    slug = slugify(mfr)
    out_rel = None
    for ext in LOGO_EXT_PRIORITY:
        src = os.path.join(LOGO_SRC_DIR, slug + ext)
        if os.path.isfile(src):
            out_rel = f"{LOGO_OUT_DIR}/{slug}{ext}"
            dest = os.path.join(ROOT, out_rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(src, dest)
            break
    if out_rel is None:
        out_rel = f"{LOGO_OUT_DIR}/{slug}.svg"
        write(os.path.join(ROOT, out_rel), _badge_svg(mfr))
    url = f"{BASE_URL}/{out_rel}"
    _LOGO_CACHE[mfr] = url
    return url

# ─── Per-product photos (real SKU photography, opt-in per manufacturer) ───
# Mirrors get_logo_url() above: drop a file under ./product-images/ and register
# it here (keyed by product_code) - no other code change needed. Several SKUs
# that are cosmetically identical (e.g. different capacity variants sharing one
# physical casing) can point at the same source file.
PRODUCT_IMAGE_SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "product-images")
PRODUCT_IMAGE_OUT_DIR = "images/products"
PRODUCT_IMAGE_BY_CODE = {
    "HPID6R32": "grant-aerona3-r32-6kw.jpg",
    "HPID10R32": "grant-aerona3-r32-10kw.jpg",
    "HPID13R32": "grant-aerona3-r32-13-17kw.jpg",
    "HPID17R32": "grant-aerona3-r32-13-17kw.jpg",
    "HPR2904": "grant-aerona-290-4kw.jpg",
    "HPR29065": "grant-aerona-290-4kw.jpg",
    "HPR2909": "grant-aerona-290-4kw.jpg",
    "HPR29012": "grant-aerona-290-12-155kw.jpg",
    "HPR290155": "grant-aerona-290-12-155kw.jpg",
    # Cool Energy: ProInverter iH+ range photographed per SKU; GroundTec GTi
    # range shares one photo across all capacities (same casing/product shot).
    "CE-iH6+": "cool-energy-ih6.webp",
    "CE-iH12+": "cool-energy-ih12.png",
    "CE-iH12+ 3PH": "cool-energy-ih12-3ph.webp",
    "CE-iH24+": "cool-energy-ih24.png",
    "CE-iH24+ 3PH": "cool-energy-ih24-3ph.webp",
    "CE-iH80+ 3PH": "cool-energy-ih80-3ph.png",
    "CE-iH100+ 3PH": "cool-energy-ih100-3ph.webp",
    "CE-iH240+ 3PH": "cool-energy-ih240-3ph.webp",
    "CE-GTI6": "cool-energy-groundtec.webp",
    "CE-GTI12": "cool-energy-groundtec.webp",
    "CE-GTI24": "cool-energy-groundtec.webp",
    # Global Energy Systems: GRS-CQ range (Cartmel/Castletown/Rothesay) is one
    # casing across capacities, photographed once; Leeds Single/Quattro share
    # a photo since Quattro is a 4-unit cascade of the same physical module.
    "GRS-CQ10Pd/NhG3-E": "global-energy-castletown.png",
    "GRS-CQ6.0Pd/NhG3-E": "global-energy-castletown.png",
    "GRS-CQ8.0Pd/NhG3-E": "global-energy-castletown.png",
    "CAER410MOD1": "global-energy-caernarfon.png",
    "WIN410MOD1": "global-energy-winchester.png",
    "LCNR410MOD1": "global-energy-lincoln.png",
    "GE40501-001-00": "global-energy-leeds.png",
    "GE40501-004-00": "global-energy-leeds.png",
    # Kronoterm: ADAPT MAX commercial cascade (one casing photographed per
    # module count - 1/2/3/4 modules); ADAPT MAX 10070 also has a real-world
    # installation shot alongside the studio render. ADAPT 2 shares one
    # casing per size (S/M/L) with colour options for the M size (Corten and
    # Olio finishes) - first entry in each list is the primary/hero photo.
    "ADAPTMAX10035": "kronoterm-adaptmax-10035.jpg",
    "ADAPTMAX10070": ["kronoterm-adaptmax-10070.jpg", "kronoterm-adaptmax-install.jpg"],
    "ADAPTMAX10105": "kronoterm-adaptmax-10105.jpg",
    "ADAPTMAX10140": "kronoterm-adaptmax-10140.jpg",
    "ADAPT-S-2": "kronoterm-adapt-2-s.jpg",
    "ADAPT-2-M-1F": ["kronoterm-adapt-2-m-corten.jpg", "kronoterm-adapt-2-m-olio.jpg"],
    "ADAPT-2-M-3F": ["kronoterm-adapt-2-m-corten.jpg", "kronoterm-adapt-2-m-olio.jpg"],
    "ADAPT-2-L": "kronoterm-adapt-2-l.jpg",
    # Etera (GSHP): identical casing across S/M/L UF and L 3F variants. Hero
    # studio shot, plus a real-world showroom photo and the manufacturer's
    # pipe-connection configuration diagrams as gallery extras.
    "2222000142599": ["kronoterm-etera.jpg", "kronoterm-etera-showroom.jpg",
                       "kronoterm-etera-connections-1.jpg", "kronoterm-etera-connections-2.jpg",
                       "kronoterm-etera-connections-3.jpg"],
    "ETERA-M-UF": ["kronoterm-etera.jpg", "kronoterm-etera-showroom.jpg",
                   "kronoterm-etera-connections-1.jpg", "kronoterm-etera-connections-2.jpg",
                   "kronoterm-etera-connections-3.jpg"],
    "2222000142612": ["kronoterm-etera.jpg", "kronoterm-etera-showroom.jpg",
                       "kronoterm-etera-connections-1.jpg", "kronoterm-etera-connections-2.jpg",
                       "kronoterm-etera-connections-3.jpg"],
    "2222000142629": ["kronoterm-etera.jpg", "kronoterm-etera-showroom.jpg",
                       "kronoterm-etera-connections-1.jpg", "kronoterm-etera-connections-2.jpg",
                       "kronoterm-etera-connections-3.jpg"],
    # Navien PEM750: one casing across the whole 4/6/8/10/17kW range - same
    # photo for every capacity variant (confirmed, unit doesn't change look).
    "PEM750V004PGKC": "navien-pem750.jpg",
    "PEM750V006PGKC": "navien-pem750.jpg",
    "PEM750V008PGKC": "navien-pem750.jpg",
    "PEM750V010PGKC": "navien-pem750.jpg",
    "PEM750V017PGKC": "navien-pem750.jpg",
    # InstaGen IG range: each capacity has its own distinct photo set
    # (single-fan cabinet for IG4-IG10, twin-fan cabinet for IG12/IG16) -
    # source files were pre-named per model, first angle used as hero.
    "IG4-MP1-A1": ["instagen-ig4-1.jpg", "instagen-ig4-2.jpg", "instagen-ig4-3.jpg",
                   "instagen-ig4-4.jpg", "instagen-ig4-5.jpg", "instagen-ig4-6.jpg"],
    "IG6-MP1-A1": ["instagen-ig6-1.jpg", "instagen-ig6-2.jpg", "instagen-ig6-3.jpg",
                   "instagen-ig6-4.jpg", "instagen-ig6-5.jpg", "instagen-ig6-6.jpg"],
    "IG8-MP1-A1": ["instagen-ig8-1.jpg", "instagen-ig8-2.jpg", "instagen-ig8-3.jpg",
                   "instagen-ig8-4.jpg", "instagen-ig8-5.jpg", "instagen-ig8-6.jpg"],
    "IG10-MP1-A1": ["instagen-ig10-1.jpg", "instagen-ig10-2.jpg", "instagen-ig10-3.jpg",
                    "instagen-ig10-4.jpg", "instagen-ig10-5.jpg", "instagen-ig10-6.jpg"],
    "IG12-MP1-A1": ["instagen-ig12-1.jpg", "instagen-ig12-2.jpg", "instagen-ig12-3.jpg",
                    "instagen-ig12-4.jpg", "instagen-ig12-5.jpg", "instagen-ig12-6.jpg",
                    "instagen-ig12-7.jpg", "instagen-ig12-8.jpg"],
    "IG16-MP1-A1": ["instagen-ig16-1.jpg", "instagen-ig16-2.jpg", "instagen-ig16-3.jpg",
                    "instagen-ig16-4.jpg", "instagen-ig16-5.jpg", "instagen-ig16-6.jpg"],
    # Samsung EHS range: one photo set per model family, shared across every
    # capacity within that family (source folder was organised by family
    # name, not per-kW code). The "-2"/"-3" files are the full-resolution
    # studio shots for the two R290 mono families, so they're used as the
    # hero with the smaller front-view thumbnail kept as a third gallery
    # image; HT Quiet and the split R410A unit only have thumbnail-res source
    # photography available.
    "AE050CXYDEK/EU": ["samsung-ehs-mono-r290-2.jpg", "samsung-ehs-mono-r290-3.jpg", "samsung-ehs-mono-r290-1.jpg"],
    "AE080CXYDEK/EU": ["samsung-ehs-mono-r290-2.jpg", "samsung-ehs-mono-r290-3.jpg", "samsung-ehs-mono-r290-1.jpg"],
    "AE120CXYDEK/EU": ["samsung-ehs-mono-r290-2.jpg", "samsung-ehs-mono-r290-3.jpg", "samsung-ehs-mono-r290-1.jpg"],
    "AE160CXYDEK/EU": ["samsung-ehs-mono-r290-2.jpg", "samsung-ehs-mono-r290-3.jpg", "samsung-ehs-mono-r290-1.jpg"],
    "AE050CXYBEK/EU": ["samsung-ehs-mono-r290-pump-2.jpg", "samsung-ehs-mono-r290-pump-3.jpg", "samsung-ehs-mono-r290-pump-1.jpg"],
    "AE080CXYBEK/EU": ["samsung-ehs-mono-r290-pump-2.jpg", "samsung-ehs-mono-r290-pump-3.jpg", "samsung-ehs-mono-r290-pump-1.jpg"],
    "AE120CXYBEK/EU": ["samsung-ehs-mono-r290-pump-2.jpg", "samsung-ehs-mono-r290-pump-3.jpg", "samsung-ehs-mono-r290-pump-1.jpg"],
    "AE160CXYBEK/EU": ["samsung-ehs-mono-r290-pump-2.jpg", "samsung-ehs-mono-r290-pump-3.jpg", "samsung-ehs-mono-r290-pump-1.jpg"],
    "AE160AXEDEH/EU": "samsung-ehs-split-r410a-1.jpg",
    "AE080BXYDEG/EU": ["samsung-ehs-mono-ht-quiet-1.jpg", "samsung-ehs-mono-ht-quiet-2.jpg", "samsung-ehs-mono-ht-quiet-3.jpg"],
    "AE120BXYDEG/EU": ["samsung-ehs-mono-ht-quiet-1.jpg", "samsung-ehs-mono-ht-quiet-2.jpg", "samsung-ehs-mono-ht-quiet-3.jpg"],
    "AE140BXYDEG/EU": ["samsung-ehs-mono-ht-quiet-1.jpg", "samsung-ehs-mono-ht-quiet-2.jpg", "samsung-ehs-mono-ht-quiet-3.jpg"],
    # Ideal Heating: one photo set per range, used across every capacity in it.
    # Ideal publishes range-level product photography rather than per-SKU shots,
    # so this mirrors the manufacturer's own approach. Note that each range does
    # span two cabinet sizes (HP290 4.5/6kW are 717x1299x426 vs 865x1385x523 for
    # 8-14kW; Logic Air 4/5kW are 798x1095x518 vs 1008x1095x518 for 8/10kW), and
    # the supplied renders show the larger one - exact dimensions for the specific
    # SKU are always in the spec table on the page.
    "241486": ["ideal-hp290-8-14kw-1-front.jpg", "ideal-hp290-8-14kw-2-left.jpg",
               "ideal-hp290-8-14kw-3-right.jpg", "ideal-hp290-8-14kw-4-back.jpg"],
    "241487": ["ideal-hp290-8-14kw-1-front.jpg", "ideal-hp290-8-14kw-2-left.jpg",
               "ideal-hp290-8-14kw-3-right.jpg", "ideal-hp290-8-14kw-4-back.jpg"],
    "241488": ["ideal-hp290-8-14kw-1-front.jpg", "ideal-hp290-8-14kw-2-left.jpg",
               "ideal-hp290-8-14kw-3-right.jpg", "ideal-hp290-8-14kw-4-back.jpg"],
    "241489": ["ideal-hp290-8-14kw-1-front.jpg", "ideal-hp290-8-14kw-2-left.jpg",
               "ideal-hp290-8-14kw-3-right.jpg", "ideal-hp290-8-14kw-4-back.jpg"],
    "241490": ["ideal-hp290-8-14kw-1-front.jpg", "ideal-hp290-8-14kw-2-left.jpg",
               "ideal-hp290-8-14kw-3-right.jpg", "ideal-hp290-8-14kw-4-back.jpg"],
    "241491": ["ideal-hp290-8-14kw-1-front.jpg", "ideal-hp290-8-14kw-2-left.jpg",
               "ideal-hp290-8-14kw-3-right.jpg", "ideal-hp290-8-14kw-4-back.jpg"],
    "AH750664": ["ideal-logic-air-1-front.jpg", "ideal-logic-air-2-left.jpg",
                 "ideal-logic-air-3-right.jpg"],
    "AH750665": ["ideal-logic-air-1-front.jpg", "ideal-logic-air-2-left.jpg",
                 "ideal-logic-air-3-right.jpg"],
    "AH750666": ["ideal-logic-air-1-front.jpg", "ideal-logic-air-2-left.jpg",
                 "ideal-logic-air-3-right.jpg"],
    "AH750667": ["ideal-logic-air-1-front.jpg", "ideal-logic-air-2-left.jpg",
                 "ideal-logic-air-3-right.jpg"],
}
# Fallback for products with no product_code (Baxi, Clade, Fenagy, Intergas,
# Octopus Energy, Rhoss, Sabroe all have null product_code in the source
# data) - keyed on the unique row "id" instead, same file-drop workflow.
PRODUCT_IMAGE_BY_ID = {
    1444: "octopus-cosy-6.jpg",
    1445: "octopus-cosy-9.jpg",
    1446: "octopus-cosy-12.jpg",
}
_PRODUCT_IMAGE_CACHE = {}

def _copy_product_image(fname):
    """Copy one registered image file into the build output (cached), return
    its site-relative URL, or None if the source file is missing."""
    if fname in _PRODUCT_IMAGE_CACHE:
        return _PRODUCT_IMAGE_CACHE[fname]
    src = os.path.join(PRODUCT_IMAGE_SRC_DIR, fname)
    if not os.path.isfile(src):
        return None
    out_rel = f"{PRODUCT_IMAGE_OUT_DIR}/{fname}"
    dest = os.path.join(ROOT, out_rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copyfile(src, dest)
    url = f"{BASE_URL}/{out_rel}"
    _PRODUCT_IMAGE_CACHE[fname] = url
    return url

def _product_image_entry(p):
    """Look up the raw PRODUCT_IMAGE_BY_CODE/BY_ID entry for a product: a
    single filename, a list of filenames (gallery, first = primary), or
    None."""
    code = p.get("product_code")
    entry = PRODUCT_IMAGE_BY_CODE.get(code) if code else None
    if not entry:
        entry = PRODUCT_IMAGE_BY_ID.get(p.get("id"))
    return entry

def get_product_images(p):
    """Return the full list of site-relative photo URLs for a product (may
    be empty). First item is always the primary/hero photo."""
    entry = _product_image_entry(p)
    if not entry:
        return []
    fnames = entry if isinstance(entry, list) else [entry]
    urls = [_copy_product_image(f) for f in fnames]
    return [u for u in urls if u]

def get_product_image(p):
    """Return the site-relative URL for a product's primary photo, or None
    if this SKU has no photo registered. Writes the file into the build
    output the first time it's needed (same copy-on-build approach as
    get_logo_url)."""
    urls = get_product_images(p)
    return urls[0] if urls else None

def product_card(p):
    bits = [t for t in (p.get("hp_type"), cap_str(p),
            (f"SCOP {num(p['scop'])}" if p.get("scop") is not None else None)) if t]
    bits_str = " \u00b7 ".join(bits)
    mfr = p.get("manufacturer", "")
    logo = get_logo_url(mfr)
    return (f'<a class="card has-logo" href="{BASE_URL}/products/{p["_slug"]}/">'
            f'<img class="logo-thumb" src="{logo}" alt="{esc(mfr)} logo" loading="lazy" width="40" height="40">'
            f'<span><div class="m">{esc(p["model"])}</div>'
            f'<div class="s">{esc(bits_str)}</div></span></a>')

def load_suppliers():
    """Parse the MFR_SUPPLIERS map (strict JSON) out of the app's index.html."""
    p = os.path.join(ROOT, "index.html")
    if not os.path.exists(p):
        return {}
    t = open(p, encoding="utf-8").read()
    i = t.find("const MFR_SUPPLIERS = ")
    if i == -1:
        return {}
    start = t.find("{", i)
    end = t.find("\n};", start)
    if end == -1:
        return {}
    try:
        return json.loads(t[start:end + 2])
    except Exception:
        return {}

SUPPLIERS = load_suppliers()

def render_suppliers(p):
    s = SUPPLIERS.get(p.get("manufacturer"))
    if not s:
        return ""
    pid, mfr, model = p.get("id"), p.get("manufacturer"), p.get("model")
    rows = []
    if s.get("direct"):
        onclick = track_attr("manufacturer_direct", pid, mfr, model, None)
        rows.append(f'<tr><th>Availability</th><td>Direct sales from manufacturer: '
                    f'<a href="{esc(s["direct"])}" rel="nofollow" target="_blank" onclick="{onclick}">{esc(p["manufacturer"])}</a></td></tr>')
    for sup in (s.get("suppliers") or [])[:5]:
        onclick = track_attr("retailer", pid, mfr, model, sup["name"])
        rows.append(f'<tr><th>UK Supplier</th><td>'
                    f'<a href="{esc(sup["url"])}" rel="nofollow" target="_blank" onclick="{onclick}">{esc(sup["name"])}</a></td></tr>')
    if not rows:
        return ""
    return '<h2 class="sec">Where to buy (UK)</h2><table class="spec">' + "".join(rows) + "</table>"

def render_mcs(p):
    if not p.get("mcs_listed"):
        return ""
    link = (f' <a href="{esc(p["mcs_url"])}" target="_blank" rel="noopener nofollow" '
            f'style="display:inline-flex;align-items:center;gap:4px;background:#0a6b3b;color:#fff;'
            f'font-size:11px;font-weight:600;padding:4px 10px;border-radius:20px;text-decoration:none;'
            f'vertical-align:middle">View on MCS &#8599;</a>') if p.get("mcs_url") else ""
    cert = (f' <span style="font-weight:500;color:#5F7E7E">Cert no. {esc(p["mcs_cert"])}</span>') if p.get("mcs_cert") else ""
    return ('<p style="margin:14px 0 0;font-size:13.5px;color:#0a6b3b;font-weight:600">'
            '&#10003; MCS listed product &mdash; eligible for the Boiler Upgrade Scheme, '
            f'subject to an MCS-certified installation.{cert}{link}</p>')

def render_verified(p):
    v = p.get("verified")
    if v:
        if v is True or v == 'Manual verification':
            label = 'Manually verified by Heat Pump Database'
        else:
            label = f'Verified via {esc(v)} data'
        return (f'<p style="margin:14px 0 0;font-size:13.5px;color:#0F8074;font-weight:600">'
                f'&#10003; {label}</p>')
    return ('<p style="margin:14px 0 0;font-size:13.5px;color:#9a7b1f;font-weight:600">'
            '&#9675; Awaiting verification</p>')

def render_correction(p):
    from urllib.parse import quote
    url = f"{BASE_URL}/products/{p['_slug']}/"
    cop = p.get("cop"); scop = p.get("scop")
    subject = f"Data correction: {p.get('manufacturer','')} {p.get('model','')} (ID {p.get('id')})"
    body = (
        "I would like to suggest a correction to the following heat pump record on Heat Pump Database.\n\n"
        "--- Product (please keep this section so we can identify the record) ---\n"
        f"ID: {p.get('id')}\n"
        f"Manufacturer: {p.get('manufacturer','')}\n"
        f"Model: {p.get('model','')}\n"
        + (f"Product code: {p.get('product_code')}\n" if p.get('product_code') else "")
        + f"Page: {url}\n"
        f"Current COP: {cop if cop is not None else '—'}" + (f" ({p.get('cop_cond')})" if p.get('cop_cond') else "") + "\n"
        f"Current SCOP: {scop if scop is not None else '—'}" + (f" ({p.get('scop_cond')})" if p.get('scop_cond') else "") + "\n"
        f"Verification: {p['verified'] if p.get('verified') else 'Awaiting verification'}\n\n"
        "--- Your correction ---\n"
        "Which field(s) are incorrect:\n\n"
        "Correct value(s):\n\n"
        "Source (datasheet link / certificate number, so we can verify):\n\n"
    )
    href = "mailto:info@heatpumpdatabase.com?subject=" + quote(subject) + "&body=" + quote(body)
    return (f'<p style="margin:10px 0 0;font-size:12.5px"><a href="{esc(href)}" '
            f'style="color:#5a6b6b">&#9998; Suggest a correction to this data</a></p>')

def render_product(p, by_mfr, by_type):
    slug = p["_slug"]
    url  = f"{BASE_URL}/products/{slug}/"
    mfr, model = p.get("manufacturer", ""), p.get("model", "")
    mslug = slugify(mfr)

    # Disambiguation: many manufacturers reuse one generic model/series name across
    # several distinct SKUs (capacity variants, phase variants, etc.), distinguished
    # only by product_code. Left alone, every such page would share an identical
    # <title>/<h1> - bad for both search matching and readers. Append whatever
    # actually distinguishes this SKU from its same-named siblings.
    siblings = [q for q in by_mfr.get(mfr, []) if q.get("model") == model]
    disambig = ""
    if len(siblings) > 1:
        caps = set((q.get("cap_min"), q.get("cap_max")) for q in siblings)
        codes = set(str(q.get("product_code")) for q in siblings)
        if len(caps) > 1 and cap_str(p):
            disambig = f" ({cap_str(p)})"
        elif len(codes) > 1 and p.get("product_code"):
            disambig = f" ({p['product_code']})"
    display_name = f"{mfr} {model}{disambig}"

    # meta description from the most useful specs
    d_bits = [TYPE_LABEL.get(p.get("hp_type"), p.get("hp_type") or "").split(" (")[0] + " heat pump"]
    if cap_str(p): d_bits.append(cap_str(p))
    if p.get("cop") is not None: d_bits.append(f"COP {num(p['cop'])}")
    if p.get("scop") is not None: d_bits.append(f"SCOP {num(p['scop'])}")
    if p.get("refrigerant"): d_bits.append(f"{p['refrigerant']} refrigerant")
    desc = f"{display_name}: " + ", ".join([b for b in d_bits if b]).rstrip(", ") + \
           ". Full specifications and data."

    rows = "".join(f"<tr><th>{l}</th><td>{v}</td></tr>" for l, v in spec_rows(p))
    badges = "".join(f'<span class="badge">{esc(b)}</span>' for b in [
        TYPE_LABEL.get(p.get("hp_type"), p.get("hp_type")),
        p.get("type"), p.get("refrigerant"),
        (cap_str(p) if cap_str(p) else None)] if b)

    extra = ""
    if p.get("description"): extra += f"<p>{esc(p['description'])}</p>"
    notes_html = f'<div class="notes">{extra}</div>' if extra else ""

    mfr_link = ""
    if p.get("product_url"):
        onclick = track_attr("manufacturer", p.get("id"), mfr, model, None)
        mfr_link = (f'<p style="margin-top:16px"><a class="cta" href="{esc(p["product_url"])}" '
                    f'rel="nofollow" target="_blank" onclick="{onclick}">View manufacturer page &rarr;</a></p>')

    # related: same manufacturer, then same type (different mfr)
    same_mfr = [q for q in by_mfr.get(mfr, []) if q["_slug"] != slug][:8]
    same_typ = [q for q in by_type.get(p.get("hp_type"), []) if q.get("manufacturer") != mfr][:6]
    rel = ""
    if same_mfr:
        rel += f'<h2 class="sec">More from {esc(mfr)}</h2><div class="grid">' + \
               "".join(product_card(q) for q in same_mfr) + "</div>"
    if same_typ:
        lbl = TYPE_LABEL.get(p.get("hp_type"), p.get("hp_type"))
        rel += f'<h2 class="sec">Other {esc(lbl)} heat pumps</h2><div class="grid">' + \
               "".join(product_card(q) for q in same_typ) + "</div>"

    crumb_items = [("Home", f"{BASE_URL}/"),
                   ("Manufacturers", f"{BASE_URL}/manufacturers/"),
                   (mfr, f"{BASE_URL}/manufacturers/{mslug}/"),
                   (model, None)]

    # "Also known as" line: retailers/datasheets/articles often list the same SKU
    # under slightly different names or codes. Surfacing known aliases helps a
    # visitor confirm they've landed on the right page even if they searched using
    # a different source's naming, and feeds the alternateName values below.
    aliases = [a for a in (p.get("aliases") or []) if a and a.strip() and a.strip() != model]
    aliases_html = ""
    if aliases:
        aliases_html = (f'<p class="sub">Also known as: '
                         f'{esc(", ".join(aliases))}</p>')

    # Minimal schema.org identity block: name/alternateName/sku/manufacturer.
    # We deliberately omit offers/review/aggregateRating rather than fabricate
    # commerce or ratings data this site doesn't have. Google's "Product"
    # rich-result type requires one of those three properties, and flags pages
    # typed as Product without them as a Search Console structured-data error
    # (seen 2026-08-21: "Either offers, review, or aggregateRating should be
    # specified"). Since we're not seeking Product rich results, we use
    # schema.org's ProductModel type instead - "a datasheet or vendor
    # specification of a product", which is exactly what this page is - a
    # spec sheet, not a commerce listing. Google's Product-snippet validator
    # only checks items typed exactly "Product", so ProductModel isn't
    # subject to the offers/review/aggregateRating requirement, and every
    # other property below (brand, sku, image, category, additionalProperty
    # specs) remains valid since ProductModel inherits from Product. (If real
    # pricing/reviews are ever added, switch back to "Product" and add a
    # valid offers/aggregateRating block.)
    product_ld = {
        "@context": "https://schema.org",
        "@type": "ProductModel",
        "name": display_name,
        "manufacturer": {"@type": "Organization", "name": mfr},
    }
    alt_names = list(dict.fromkeys(aliases + ([p["product_code"]] if p.get("product_code") else [])))
    if alt_names:
        product_ld["alternateName"] = alt_names
    if p.get("product_code"):
        product_ld["sku"] = p["product_code"]
    if url:
        product_ld["url"] = url
    # Rich attributes: description, brand, image, category, and the key
    # specifications as PropertyValue entries (still no offers/review — see above).
    product_ld["brand"] = {"@type": "Brand", "name": mfr}
    if p.get("description"):
        product_ld["description"] = p["description"]
    product_ld["image"] = get_product_image(p) or get_logo_url(mfr)
    if p.get("hp_type"):
        product_ld["category"] = TYPE_LABEL.get(p["hp_type"], p["hp_type"])
    props = []
    def prop(name, value, unit=None):
        if value is None or value == "":
            return
        pv = {"@type": "PropertyValue", "name": name, "value": value}
        if unit:
            pv["unitText"] = unit
        props.append(pv)
    prop("Heat pump type", TYPE_LABEL.get(p.get("hp_type"), p.get("hp_type")))
    prop("Refrigerant", p.get("refrigerant"))
    cap = cap_str(p)
    prop("Heating capacity", cap)
    if p.get("cop") is not None:
        prop("COP" + (f" ({p['cop_cond']})" if p.get("cop_cond") else ""), p["cop"])
    if p.get("scop") is not None:
        prop("SCOP" + (f" ({p['scop_cond']})" if p.get("scop_cond") else ""), p["scop"])
    if p.get("seer") is not None:
        prop("SEER", p["seer"])
    if p.get("flow_temp_max") is not None:
        prop("Max flow temperature", p["flow_temp_max"], "\u00b0C")
    if p.get("noise") is not None:
        prop("Sound power level", p["noise"], "dB(A)")
    if p.get("refrigerant"):
        pass
    if p.get("mode"):
        prop("Mode", p["mode"])
    if p.get("electrical"):
        prop("Electrical supply", p["electrical"])
    if props:
        product_ld["additionalProperty"] = props

    logo = get_logo_url(mfr)
    photos = get_product_images(p)
    photo = photos[0] if photos else None
    if photo:
        thumbs_html = ""
        if len(photos) > 1:
            thumb_items = "".join(
                f'<img class="product-photo-thumb{" active" if i == 0 else ""}" src="{u}" '
                f'alt="{esc(display_name)} photo {i+1}" loading="lazy" '
                f'onclick="event.stopPropagation();document.querySelector(\'.product-photo\').src=this.src;'
                f'document.querySelectorAll(\'.product-photo-thumb\').forEach(t=>t.classList.remove(\'active\'));'
                f'this.classList.add(\'active\')">'
                for i, u in enumerate(photos))
            thumbs_html = f'<div class="product-photo-thumbs">{thumb_items}</div>'
        photo_html = (f'<div class="product-photo-block"><img class="product-photo" src="{photo}" '
                      f'alt="{esc(display_name)}" width="320" height="320" loading="eager" '
                      f'onclick="openPhotoLightbox(this.src,this.alt)">'
                      f'{thumbs_html}'
                      f'<div class="photo-credit">Image courtesy of {esc(mfr)} &middot; click photo to enlarge</div></div>')
    else:
        photo_html = ""
    body = (crumbs(crumb_items) +
            photo_html +
            f'<div class="mfr-header"><img class="mfr-logo-sm" src="{logo}" alt="{esc(mfr)} logo" width="32" height="32">'
            f"<h1>{esc(display_name)}</h1></div>"
            f'<p class="sub">Specifications and technical data</p>'
            f'{aliases_html}'
            f'<div class="badges">{badges}</div>'
            f'<table class="spec">{rows}</table>'
            f'{mfr_link}{notes_html}{render_suppliers(p)}{render_verified(p)}{render_correction(p)}'
            f'<div class="disclaimer">Data is compiled from manufacturer sources and may contain errors or '
            f'gaps. Always confirm specifications with the manufacturer before making decisions.</div>'
            f'{render_reviews(p)}'
            f'{rel}'
            f'<h2 class="sec">Compare with other products</h2>'
            f'<p><a class="cta" href="{BASE_URL}/">Open the interactive database &rarr;</a></p>'
            f'<p class="trademark-note">The {esc(mfr)} name and logo are trademarks of their respective owner '
            f'and are used here for identification purposes only.</p>')

    title = f"{display_name} \u2014 Specifications | {SITE_NAME}"
    return page(title, desc, url, body,
                [breadcrumb_jsonld(crumb_items, url), product_ld], og_type="product",
                og_image=get_og_image(mfr))

def list_table(products):
    head = ("<tr><th>Model</th><th>Product code</th><th>Type</th><th>Capacity</th><th>COP</th>"
            "<th>SCOP</th><th>Refrigerant</th></tr>")
    groups = {}
    order = []
    for p in products:
        m = p.get("model") or ""
        if m not in groups:
            groups[m] = []
            order.append(m)
        groups[m].append(p)
    rows = ""
    for m in order:
        rows += f'<tr class="grp-row"><td colspan="7">{esc(m)}</td></tr>'
        for p in groups[m]:
            rows += (f'<tr><td><a href="{BASE_URL}/products/{p["_slug"]}/">{esc(p["model"])}</a></td>'
                     f'<td>{esc(p.get("product_code") or "")}</td>'
                     f'<td>{esc(p.get("hp_type") or "")}</td>'
                     f'<td>{esc(cap_str(p) or "")}</td>'
                     f'<td>{esc(num(p["cop"]) if p.get("cop") is not None else "")}</td>'
                     f'<td>{esc(num(p["scop"]) if p.get("scop") is not None else "")}</td>'
                     f'<td>{esc(p.get("refrigerant") or "")}</td></tr>')
    return f'<table class="list">{head}{rows}</table>'

def render_manufacturer(mfr, products):
    mslug = slugify(mfr)
    url = f"{BASE_URL}/manufacturers/{mslug}/"
    n = len(products)
    types = sorted({TYPE_LABEL.get(p.get("hp_type"), p.get("hp_type")) for p in products if p.get("hp_type")})
    desc = (f"{mfr} heat pumps: {n} models in the {SITE_NAME}. "
            f"Compare {', '.join(types).lower()} specifications, COP and SCOP data.")
    crumb_items = [("Home", f"{BASE_URL}/"),
                   ("Manufacturers", f"{BASE_URL}/manufacturers/"),
                   (mfr, None)]
    logo = get_logo_url(mfr)
    body = (crumbs(crumb_items) +
            f'<div class="mfr-header"><img class="mfr-logo" src="{logo}" alt="{esc(mfr)} logo" width="64" height="64">'
            f"<h1>{esc(mfr)} Heat Pumps</h1></div>"
            f'<p class="sub">{n} model{"s" if n != 1 else ""} in the database</p>' +
            list_table(sorted(products, key=lambda x: (x.get("model") or "", x.get("cap_max") or 0))) +
            f'<p style="margin-top:20px"><a class="cta" href="{BASE_URL}/">Search the full database &rarr;</a></p>'
            f'<p class="trademark-note">The {esc(mfr)} name and logo are trademarks of their respective owner '
            f'and are used here for identification purposes only.</p>')
    item_ld = {"@context": "https://schema.org", "@type": "ItemList",
               "name": f"{mfr} heat pumps",
               "itemListElement": [
                   {"@type": "ListItem", "position": i + 1,
                    "url": f"{BASE_URL}/products/{p['_slug']}/",
                    "name": f"{mfr} {p['model']}"}
                   for i, p in enumerate(products)]}
    title = f"{mfr} Heat Pumps \u2014 Models & Specifications | {SITE_NAME}"
    return page(title, desc, url, body, [item_ld, breadcrumb_jsonld(crumb_items, url)],
                active="manufacturers", og_image=get_og_image(mfr))

# ISO 3166-1 alpha-2 codes, used to render actual flag images (flagcdn.com) instead of
# Unicode flag emoji — Windows' default emoji font has no flag glyphs, so emoji flags render
# as plain letters/boxes there even though they work fine on macOS/iOS.
COUNTRY_CODE = {
    "United Kingdom": "gb", "Ireland": "ie",
    "Germany": "de", "France": "fr",
    "Italy": "it", "Spain": "es",
    "Netherlands": "nl", "Sweden": "se",
    "Denmark": "dk", "Finland": "fi",
    "Austria": "at", "Liechtenstein": "li",
    "Slovenia": "si", "Czech Republic": "cz",
    "Japan": "jp", "South Korea": "kr",
    "China": "cn", "United States": "us",
}

def flag_img(country, css_class="flag-icon"):
    """Return an <img> tag for a country's flag, or '' if the country/code is unknown."""
    code = COUNTRY_CODE.get(country)
    if not code:
        return ""
    return (f'<img class="{css_class}" src="https://flagcdn.com/{code}.svg" '
            f'width="16" height="12" alt="" loading="lazy">')

MANUFACTURER_COUNTRY = {
    "Acond": "Czech Republic",
    "Adlar": "United Kingdom",
    "Aira": "Sweden",
    "Airwell": "France",
    "Alpha Innotec": "Germany",
    "Ariston": "Italy",
    "Atlantic": "France",
    "Baxi": "United Kingdom",
    "Beretta": "Italy",
    "Bosch": "Germany",
    "CIAT": "France",
    "CTC": "Sweden",
    "Carrier": "United States",
    "Clade": "United Kingdom",
    "Clivet": "Italy",
    "Cool Energy": "United Kingdom",
    "Daikin": "Japan",
    "Dimplex": "Ireland",
    "Ebac": "United Kingdom",
    "EcoFlow": "China",
    "Ecoforest": "Spain",
    "Fenagy": "Denmark",
    "Firebird": "Ireland",
    "Fujitsu": "Japan",
    "GEA": "Germany",
    "Global Energy Systems": "United Kingdom",
    "Glow-worm": "United Kingdom",
    "Grant": "Ireland",
    "Haier": "China",
    "Harnitek": "China",
    "Heliotherm": "Austria",
    "Hisa": "United Kingdom",
    "Hisense": "China",
    "Hitachi": "Japan",
    "Hoval": "Liechtenstein",
    "Ideal Heating": "United Kingdom",
    "InstaGen": "United Kingdom",
    "Intergas": "Netherlands",
    "Kensa": "United Kingdom",
    "Keyter": "Spain",
    "Kronoterm": "Slovenia",
    "LG": "South Korea",
    "Lailey and Coates": "United Kingdom",
    "M-Tec": "Austria",
    "MasterTherm": "Czech Republic",
    "Midea": "China",
    "Mitsubishi Electric": "Japan",
    "Modutherm": "United Kingdom",
    "Navien": "South Korea",
    "Nibe": "Sweden",
    "Ochsner": "Austria",
    "Ochsner Energietechnik": "Austria",
    "Octopus Energy": "United Kingdom",
    "Oilon": "Finland",
    "Panasonic": "Japan",
    "Peak": "United Kingdom",
    "Qvantum": "Sweden",
    "Rank": "Spain",
    "Rhoss": "Italy",
    "Riello": "Italy",
    "Sabroe": "Denmark",
    "Samsung": "South Korea",
    "Sime": "Italy",
    "Solid Energy": "Denmark",
    "Star Renewable Energy": "United Kingdom",
    "Stiebel Eltron": "Germany",
    "Swegon": "Sweden",
    "Thermia": "Sweden",
    "Thermonova": "Denmark",
    "Toshiba": "Japan",
    "Trane": "United States",
    "Trianco": "United Kingdom",
    "Vaillant": "Germany",
    "Viessmann": "Germany",
    "Warmflow": "United Kingdom",
    "Wondrwall": "United Kingdom",
    "York": "United States",
}

def render_manufacturers_index(by_mfr):
    url = f"{BASE_URL}/manufacturers/"

    # ── per-manufacturer stats, computed straight from the product data so
    # they never drift out of date on rebuild ──
    all_products = [p for ps in by_mfr.values() for p in ps]
    n_countries = len({MANUFACTURER_COUNTRY[m] for m in by_mfr if m in MANUFACTURER_COUNTRY})

    intro = (
        '<p style="color:#42514f;font-size:14.5px;line-height:1.7;margin:0 0 24px;max-width:720px">'
        f'{len(by_mfr)} manufacturers, {len(all_products):,} products across {n_countries} countries. '
        'Each card shows country, product mix and MCS-listed models &mdash; use the filters below to narrow the list.</p>'
    )

    country_set = set()
    card_data = []  # (name, html, country) — built once so we can also derive the filter dropdown options

    def _mfr_card(m):
        ps = by_mfr[m]
        n = len(ps)
        mcs_n = sum(1 for p in ps if p.get("mcs_listed") is True)
        # heating flow (flow/return loop) temperature range — NOT the ambient/environmental
        # operating range — so this reflects what water temperature the units can deliver
        flow_los = [p["flow_temp_min"] for p in ps if p.get("flow_temp_min") is not None]
        flow_his = [p["flow_temp_max"] for p in ps if p.get("flow_temp_max") is not None]
        flow_range = f'{num(min(flow_los))}°C to {num(max(flow_his))}°C' if flow_los and flow_his else None

        cap_los = [p["cap_min"] for p in ps if p.get("cap_min") is not None]
        cap_his = [p["cap_max"] for p in ps if p.get("cap_max") is not None]
        cap_lo = min(cap_los) if cap_los else None
        cap_hi = max(cap_his) if cap_his else None

        def _type_count(prefix):
            return sum(1 for p in ps if str(p.get("hp_type") or "").upper().startswith(prefix))
        type_counts = ((_type_count("ASHP"), "ASHP"), (_type_count("GSHP"), "GSHP"), (_type_count("WSHP"), "WSHP"))
        type_parts = [f'{c} {label}' for c, label in type_counts if c > 0]
        types_attr = ",".join(label for c, label in type_counts if c > 0)

        country = MANUFACTURER_COUNTRY.get(m)
        flag = flag_img(country)
        if country:
            country_set.add(country)

        row_lines = [f'{n} model{"s" if n != 1 else ""}']
        if country:
            row_lines.append(f'{flag} {esc(country)}')
        if mcs_n:
            row_lines.append(f'{mcs_n} MCS-listed')
        if flow_range:
            row_lines.append(f'Flow temp {flow_range}')
        if type_parts:
            row_lines.append(' · '.join(type_parts))

        lines = "".join(f'<div class="s">{row}</div>' for row in row_lines)

        data_attrs = (
            f'data-mcs="{1 if mcs_n else 0}" '
            f'data-types="{esc(types_attr)}" '
            f'data-country="{esc(country or "")}" '
            f'data-cap-lo="{cap_lo if cap_lo is not None else ""}" '
            f'data-cap-hi="{cap_hi if cap_hi is not None else ""}"'
        )

        return (f'<a class="card has-logo" {data_attrs} href="{BASE_URL}/manufacturers/{slugify(m)}/">'
                f'<img class="logo-thumb" src="{get_logo_url(m)}" alt="{esc(m)} logo" loading="lazy" width="40" height="40">'
                f'<span><div class="m">{esc(m)}</div>{lines}</span></a>')

    cards = "".join(_mfr_card(m) for m in sorted(by_mfr))

    country_options = "".join(
        f'<option value="{esc(c)}">{esc(c)}</option>'
        for c in sorted(country_set)
    )

    filter_bar = f'''
<style>{MFR_FILTER_CSS}</style>
<div class="mfr-filter-bar">
  <div class="mfr-filter-grid">
    <div class="mfr-filter-col">
      <label class="filter-label" for="mf-type">Heat pump type</label>
      <select class="filt" id="mf-type" onchange="mfApplyFilters()">
        <option value="">Any type</option>
        <option value="ASHP">Air source (ASHP)</option>
        <option value="GSHP">Ground source (GSHP)</option>
        <option value="WSHP">Water source (WSHP)</option>
      </select>
    </div>
    <div class="mfr-filter-col">
      <label class="filter-label" for="mf-mcs">MCS certification</label>
      <select class="filt" id="mf-mcs" onchange="mfApplyFilters()">
        <option value="">Any</option>
        <option value="mcs">Has MCS-listed products</option>
      </select>
    </div>
    <div class="mfr-filter-col">
      <label class="filter-label" for="mf-country">Country</label>
      <select class="filt" id="mf-country" onchange="mfApplyFilters()">
        <option value="">Any country</option>
        {country_options}
      </select>
    </div>
    <div class="mfr-filter-col">
      <label class="filter-label">Heating capacity <span class="f-slider-val" id="mf-sv-cap">Any</span></label>
      <div class="range-wrap" id="mf-sl-cap"></div>
    </div>
  </div>
  <div class="mfr-filter-footer">
    <span id="mf-count"></span>
    <button type="button" class="mf-clear-btn" onclick="mfClearFilters()">Clear filters</button>
  </div>
</div>
<p class="mfr-empty" id="mfr-empty">No manufacturers match those filters.</p>
'''

    crumb_items = [("Home", f"{BASE_URL}/"), ("Manufacturers", None)]
    body = (crumbs(crumb_items) +
            "<h1>Heat Pump Manufacturers</h1>"
            f'<p class="sub">{len(by_mfr)} brands in the database</p>'
            f'{intro}'
            f'{filter_bar}'
            f'<div class="grid" id="mfr-grid">{cards}</div>'
            f'<script>{MFR_FILTER_JS}</script>')
    return page(f"Heat Pump Manufacturers (A–Z) | {SITE_NAME}",
                f"Browse heat pumps by manufacturer. {len(by_mfr)} brands with full specifications, "
                f"COP and SCOP data in the {SITE_NAME}.", url, body,
                [breadcrumb_jsonld(crumb_items, url)], active="manufacturers", og_image=get_og_image())

def render_type(slug, heading, desc, products):
    url = f"{BASE_URL}/types/{slug}/"
    # group by manufacturer for readability
    by_m = {}
    for p in products:
        by_m.setdefault(p.get("manufacturer", ""), []).append(p)
    sections = ""
    for m in sorted(by_m):
        sections += (f'<h2 class="sec">{esc(m)}</h2>' +
                     list_table(sorted(by_m[m], key=lambda x: x.get("cap_max") or 0)))
    crumb_items = [("Home", f"{BASE_URL}/"), (heading, None)]
    body = (crumbs([("Home", f"{BASE_URL}/"), (heading, None)]) +
            f"<h1>{esc(heading)}</h1>"
            f'<p class="sub">{len(products)} products &middot; {len(by_m)} manufacturers</p>'
            f'{sections}'
            f'<p style="margin-top:20px"><a class="cta" href="{BASE_URL}/">Open the interactive database &rarr;</a></p>')
    return page(f"{heading} | {SITE_NAME}", desc, url, body, [breadcrumb_jsonld(crumb_items, url)],
                og_image=get_og_image())


# ───────────────────────── Best-of ranking pages ─────────────────────────
def _cond_is(p, field, prefix):
    return str(p.get(field) or "").replace(" ", "").upper().startswith(prefix)

def _dedupe_variants(ranked, metric):
    """Collapse near-identical variants (same manufacturer, same model family,
    same metric value) so one product family doesn't fill the table."""
    out, seen = [], set()
    for p in ranked:
        fam = " ".join((p.get("model") or "").split()[:2])
        key = (p.get("manufacturer"), fam, p.get(metric))
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out

BEST_PAGES = [
    {"slug": "best-air-source-heat-pumps-by-scop",
     "title": "Best Air Source Heat Pumps by SCOP",
     "h1": "Best Air Source Heat Pumps by SCOP",
     "desc": "The most efficient air source heat pumps ranked by SCOP at 35\u00b0C flow. Top {n} of {pool} ASHPs compared on seasonal efficiency.",
     "intro": "Ranked by SCOP (seasonal coefficient of performance) at a 35\u00b0C flow temperature \u2014 the fairest single measure of real-world heating efficiency. Only products with a published SCOP at W35 are included.",
     "filter": lambda p: p.get("hp_type") == "ASHP" and p.get("scop") and "35" in str(p.get("scop_cond") or ""),
     "sort": lambda p: -(p.get("scop") or 0), "metric": "scop", "metric_label": "SCOP (W35)"},

    {"slug": "quietest-air-source-heat-pumps",
     "title": "Quietest Air Source Heat Pumps",
     "h1": "Quietest Air Source Heat Pumps",
     "desc": "The quietest air source heat pumps ranked by sound power level. Top {n} of {pool} ASHPs under 25 kW compared.",
     "intro": "Ranked by published sound power level (dB(A)) \u2014 lowest first. Limited to units up to 25 kW with a declared sound power figure, the measure used for UK permitted-development noise assessments (MCS 020).",
     "filter": lambda p: p.get("hp_type") == "ASHP" and p.get("noise") and (p.get("cap_max") or 99) <= 25
                and "power" in str(p.get("noise_ref") or "").lower(),
     "sort": lambda p: (p.get("noise") or 999), "metric": "noise", "metric_label": "Sound power dB(A)"},

    {"slug": "best-r290-heat-pumps",
     "title": "Best R290 (Propane) Heat Pumps",
     "h1": "Best R290 (Propane) Heat Pumps by SCOP",
     "desc": "The best heat pumps using natural refrigerant R290, ranked by SCOP. Top {n} of {pool} R290 models compared.",
     "intro": "R290 (propane) is a natural refrigerant with a GWP of just 3, and typically enables higher flow temperatures. These are the most efficient R290 heat pumps in the database, ranked by SCOP.",
     "filter": lambda p: p.get("refrigerant") == "R290" and p.get("scop"),
     "sort": lambda p: -(p.get("scop") or 0), "metric": "scop", "metric_label": "SCOP"},

    {"slug": "best-small-heat-pumps-3-6kw",
     "title": "Best Small Heat Pumps (3\u20136 kW)",
     "h1": "Best Small Heat Pumps (3\u20136 kW) by SCOP",
     "desc": "The best small air source heat pumps (3\u20136 kW) for flats and small homes, ranked by SCOP. Top {n} of {pool} compared.",
     "intro": "Small-capacity heat pumps (3\u20136 kW) suit well-insulated flats and smaller homes. Ranked by SCOP \u2014 seasonal efficiency at 35\u00b0C flow.",
     "filter": lambda p: p.get("hp_type") == "ASHP" and p.get("scop") and p.get("cap_max") and 3 <= p["cap_max"] <= 6.5,
     "sort": lambda p: -(p.get("scop") or 0), "metric": "scop", "metric_label": "SCOP"},

    {"slug": "best-medium-heat-pumps-7-12kw",
     "title": "Best Medium Heat Pumps (7\u201312 kW)",
     "h1": "Best Medium Heat Pumps (7\u201312 kW) by SCOP",
     "desc": "The best 7\u201312 kW air source heat pumps for typical UK homes, ranked by SCOP. Top {n} of {pool} compared.",
     "intro": "The 7\u201312 kW band covers most three- and four-bedroom UK homes. Ranked by SCOP \u2014 seasonal efficiency at 35\u00b0C flow.",
     "filter": lambda p: p.get("hp_type") == "ASHP" and p.get("scop") and p.get("cap_max") and 6.5 < p["cap_max"] <= 12,
     "sort": lambda p: -(p.get("scop") or 0), "metric": "scop", "metric_label": "SCOP"},

    {"slug": "best-large-heat-pumps-13-25kw",
     "title": "Best Large Heat Pumps (13\u201325 kW)",
     "h1": "Best Large Heat Pumps (13\u201325 kW) by SCOP",
     "desc": "The best 13\u201325 kW heat pumps for large homes and small commercial buildings, ranked by SCOP. Top {n} of {pool} compared.",
     "intro": "Large-capacity units (13\u201325 kW) suit big or older homes and light commercial use. Ranked by SCOP \u2014 seasonal efficiency at 35\u00b0C flow.",
     "filter": lambda p: p.get("hp_type") == "ASHP" and p.get("scop") and p.get("cap_max") and 12 < p["cap_max"] <= 25,
     "sort": lambda p: -(p.get("scop") or 0), "metric": "scop", "metric_label": "SCOP"},

]

BEST_TOP_N = 10

COMPOSITE_SCORING_EXPLANATION = (
    "Each qualifying air source heat pump is scored 0\u201310 on three measures - SCOP at "
    "35\u00b0C flow, published sound power level, and price per kW of peak heating capacity - "
    "scaled between the best and worst product in the qualifying pool, with lower noise and "
    "lower price per kW scoring higher. The three 0\u201310 scores are added for a total out of "
    "30. Unlike the single-metric rankings elsewhere on this site, a blended score like this can "
    "place a product highly even if it doesn\u2019t lead on any one measure, and a product with "
    "the single highest SCOP can be overtaken by one that\u2019s merely good across all three. "
    "Limited to residential-sized (under 20kW) air source heat pumps with a published SCOP at "
    "W35, sound power level and price all available.")

def _composite_ashp_ranking(products):
    """'Best Overall' ASHP ranking: SCOP (W35), noise and price-per-kW each
    normalised to a 0-10 score across the qualifying pool, then summed for an
    overall score out of 30. Returns (top_10_ranked, qualifying_pool_size)."""
    pool = [p for p in products
            if p.get("hp_type") == "ASHP"
            and (p.get("cap_max") or 0) > 0 and p.get("cap_max") < 20
            and p.get("scop") and _cond_is(p, "scop_cond", "W35")
            and p.get("noise") is not None
            and p.get("gbp_per_kw") is not None]
    if not pool:
        return [], 0

    scops = [p["scop"] for p in pool]
    noises = [p["noise"] for p in pool]
    gbps = [p["gbp_per_kw"] for p in pool]
    smin, smax = min(scops), max(scops)
    nmin, nmax = min(noises), max(noises)
    gmin, gmax = min(gbps), max(gbps)

    def norm(v, vmin, vmax, invert=False):
        if vmax == vmin:
            return 10.0
        frac = (v - vmin) / (vmax - vmin)
        if invert: frac = 1 - frac
        return round(frac * 10, 2)

    scored = []
    for p in pool:
        q = dict(p)
        q["_scop_score"] = norm(p["scop"], smin, smax)
        q["_noise_score"] = norm(p["noise"], nmin, nmax, invert=True)
        q["_gbp_score"] = norm(p["gbp_per_kw"], gmin, gmax, invert=True)
        q["_total"] = round(q["_scop_score"] + q["_noise_score"] + q["_gbp_score"], 2)
        scored.append(q)
    scored.sort(key=lambda p: -p["_total"])

    # dedupe exact same manufacturer+model (keep the best-scoring listing per model)
    out, seen = [], set()
    for p in scored:
        key = (p.get("manufacturer"), p.get("model"))
        if key in seen:
            continue
        seen.add(key)
        out.append(p)

    return out[:10], len(pool)

def _render_composite_section(ranked, pool_size):
    n = len(ranked)
    rows = ""
    for i, p in enumerate(ranked, 1):
        rank_cls = f' class="rank-{i}"' if i <= 3 else ""
        logo = get_logo_url(p.get("manufacturer", ""))
        rows += (f'<tr{rank_cls}><td class="rank"><span class="rank-badge">{i}</span></td>'
                 f'<td><span class="best-model"><img src="{logo}" alt="" loading="lazy" width="26" height="26">'
                 f'<a href="{BASE_URL}/products/{p["_slug"]}/">{esc(p.get("manufacturer",""))} {esc(p.get("model",""))}</a></span></td>'
                 f'<td>{esc(cap_str(p) or "")}</td>'
                 f'<td>{num(p["scop"])}<span class="composite-sub"> ({p["_scop_score"]:.1f}/10)</span></td>'
                 f'<td>{num(p["noise"])} dB(A)<span class="composite-sub"> ({p["_noise_score"]:.1f}/10)</span></td>'
                 f'<td>\u00a3{num(p["gbp_per_kw"])}<span class="composite-sub"> ({p["_gbp_score"]:.1f}/10)</span></td>'
                 f'<td class="metric-cell"><span class="metric-val">{p["_total"]:.1f}</span>'
                 f'<span class="metric-bar"><i style="width:{round(p["_total"]/30*100)}%"></i></span></td>'
                 f'</tr>')

    w = ranked[0]
    winner_html = (
        f'<div class="best-winner">'
        f'<img src="{get_logo_url(w.get("manufacturer",""))}" alt="{esc(w.get("manufacturer",""))} logo" width="56" height="56">'
        f'<div><div class="bw-crown">#1 \u00b7 Best Overall Air Source Heat Pump</div>'
        f'<div class="bw-name"><a href="{BASE_URL}/products/{w["_slug"]}/">{esc(w.get("manufacturer",""))} {esc(w.get("model",""))}</a></div></div>'
        f'<div class="bw-val"><div class="bw-num">{w["_total"]:.1f}</div><div class="bw-lab">Score / 30</div></div>'
        f'</div>')

    explanation_html = ('<div class="article-tldr"><span class="article-tldr-label">Scoring</span>'
                         '<p>' + COMPOSITE_SCORING_EXPLANATION + '</p></div>')

    table_html = (f'<div class="best-scroll"><table class="list best-table">'
                  f'<tr><th>#</th><th>Model</th><th>Capacity</th><th>SCOP (W35)</th><th>Noise</th>'
                  f'<th>\u00a3/kW</th><th>Score</th></tr>{rows}</table></div>')

    return (f'<section id="best-overall-ashp" class="best-section">'
            f'<h2 class="sec">Best Overall Air Source Heat Pumps</h2>'
            f'<p class="sub">Top {n} of {pool_size} qualifying ASHPs \u00b7 updated {TODAY}</p>'
            + explanation_html +
            f'<p>A single blended ranking across efficiency, noise and price, rather than one metric at a time '
            f'like the rankings below.</p>'
            + winner_html + table_html +
            f'</section>')

def _best_table_and_winner(cfg, ranked):
    """Build the ranking <table> and the #1 winner-card HTML for one
    BEST_PAGES config's already-filtered/sorted product list, used by
    render_best_single_page() to render each stacked section."""
    show_cond = cfg.get("show_cond")
    show_flow = cfg.get("show_flow")
    show_type = cfg.get("show_type")
    show_price = cfg.get("show_price")
    metric = cfg["metric"]

    head_cells = "<th>#</th><th>Model</th>"
    if show_type: head_cells += "<th>Type</th>"
    head_cells += "<th>Capacity</th><th>" + cfg["metric_label"] + "</th>"
    if show_price: head_cells += "<th>Price (RRP)</th>"
    if show_cond: head_cells += "<th>Test condition</th>"
    if show_flow: head_cells += "<th>Max flow</th>"
    head_cells += "<th>Refrigerant</th>"
    if metric != "noise": head_cells += "<th>Noise</th>"

    # relative bar widths: for noise lower is better, invert scale
    vals = [p.get(metric) for p in ranked if isinstance(p.get(metric), (int, float))]
    vmin, vmax = (min(vals), max(vals)) if vals else (0, 1)
    def bar_pct(v):
        if not isinstance(v, (int, float)) or vmax == vmin:
            return 100
        if metric in ("noise", "gbp_per_kw"):  # lower is better for both
            return round(30 + 70 * (vmax - v) / (vmax - vmin))
        return round(30 + 70 * (v - vmin) / (vmax - vmin))

    rows = ""
    for i, p in enumerate(ranked, 1):
        mv = p.get(metric)
        mv_s = num(mv) if isinstance(mv, (int, float)) else esc(str(mv or ""))
        if metric == "gbp_per_kw" and isinstance(mv, (int, float)):
            mv_s = f"£{mv_s}"
        noise_s = f"{num(p['noise'])} dB(A)" if p.get("noise") is not None else ""
        price_s = ""
        if show_price:
            pmin, pmax = p.get("price_min"), p.get("price_max")
            if pmin is not None and pmax is not None and pmin != pmax:
                price_s = f"£{num(pmin)}–£{num(pmax)}"
            elif pmin is not None:
                price_s = f"£{num(pmin)}"
            elif pmax is not None:
                price_s = f"£{num(pmax)}"
        rank_cls = f" class=\"rank-{i}\"" if i <= 3 else ""
        logo = get_logo_url(p.get("manufacturer", ""))
        row = (f'<tr{rank_cls}><td class="rank"><span class="rank-badge">{i}</span></td>'
               f'<td><span class="best-model"><img src="{logo}" alt="" loading="lazy" width="26" height="26">'
               f'<a href="{BASE_URL}/products/{p["_slug"]}/">{esc(p.get("manufacturer",""))} {esc(p.get("model",""))}</a></span></td>')
        if show_type:
            row += f'<td>{esc(p.get("hp_type") or "")}</td>'
        row += (f'<td>{esc(cap_str(p) or "")}</td>'
                f'<td class="metric-cell"><span class="metric-val">{mv_s}</span>'
                f'<span class="metric-bar"><i style="width:{bar_pct(mv)}%"></i></span></td>')
        if show_price:
            row += f'<td>{esc(price_s)}</td>'
        if show_cond:
            cond_field = "cop_cond" if metric == "cop" else "scop_cond"
            row += f'<td>{esc(str(p.get(cond_field) or ""))}</td>'
        if show_flow:
            row += f'<td>{num(p["flow_temp_max"])}\u00b0C</td>' if p.get("flow_temp_max") else "<td></td>"
        row += f'<td>{esc(p.get("refrigerant") or "")}</td>'
        if metric != "noise":
            row += f'<td>{noise_s}</td>'
        row += '</tr>'
        rows += row

    w = ranked[0]
    wv = w.get(metric)
    wv_s = num(wv) if isinstance(wv, (int, float)) else esc(str(wv or ""))
    winner_html = (
        f'<div class="best-winner">'
        f'<img src="{get_logo_url(w.get("manufacturer",""))}" alt="{esc(w.get("manufacturer",""))} logo" width="56" height="56">'
        f'<div><div class="bw-crown">#1 \u00b7 {cfg["title"]}</div>'
        f'<div class="bw-name"><a href="{BASE_URL}/products/{w["_slug"]}/">{esc(w.get("manufacturer",""))} {esc(w.get("model",""))}</a></div></div>'
        f'<div class="bw-val"><div class="bw-num">{wv_s}</div><div class="bw-lab">{cfg["metric_label"]}</div></div>'
        f'</div>')

    table_html = f'<div class="best-scroll"><table class="list best-table">{"<tr>" + head_cells + "</tr>"}{rows}</table></div>'
    return winner_html, table_html

def render_best_single_page(composite, sections):
    """The site's one ranking destination: the blended 'Best Overall ASHP'
    score at the top, followed by every single-metric ranking category
    stacked as its own list section on the same page, rather than an index
    of cards linking out to separate per-category pages (this replaced the
    old /top-10/ multi-page section). `composite` is (ranked, pool_size)
    from _composite_ashp_ranking(); `sections` is a list of
    (cfg, ranked, pool_size) tuples in BEST_PAGES order."""
    url = f"{BASE_URL}/best/"
    crumb_items = [("Home", f"{BASE_URL}/"), ("Best Heat Pumps", None)]

    composite_ranked, composite_pool = composite
    toc = ""
    item_lds = []
    if composite_ranked:
        toc += '<a href="#best-overall-ashp">Best Overall Air Source Heat Pumps</a>'
        item_lds.append({"@context": "https://schema.org", "@type": "ItemList",
                          "name": "Best Overall Air Source Heat Pumps", "numberOfItems": len(composite_ranked),
                          "itemListElement": [
                              {"@type": "ListItem", "position": i + 1,
                               "url": f"{BASE_URL}/products/{p['_slug']}/",
                               "name": f"{p.get('manufacturer','')} {p.get('model','')}"}
                              for i, p in enumerate(composite_ranked)]})
    toc += "".join(f'<a href="#{cfg["slug"]}">{cfg["title"]}</a>' for cfg, _, _ in sections)

    section_html = _render_composite_section(composite_ranked, composite_pool) if composite_ranked else ""
    for cfg, ranked, pool_size in sections:
        n = len(ranked)
        winner_html, table_html = _best_table_and_winner(cfg, ranked)
        section_html += (
            f'<section id="{cfg["slug"]}" class="best-section">'
            f'<h2 class="sec">{cfg["title"]}</h2>'
            f'<p class="sub">Top {n} of {pool_size} qualifying products \u00b7 updated {TODAY}</p>'
            f'<p>{cfg["intro"]}</p>'
            + winner_html + table_html +
            f'</section>')
        item_lds.append({"@context": "https://schema.org", "@type": "ItemList",
                          "name": cfg["title"], "numberOfItems": n,
                          "itemListElement": [
                              {"@type": "ListItem", "position": i + 1,
                               "url": f"{BASE_URL}/products/{p['_slug']}/",
                               "name": f"{p.get('manufacturer','')} {p.get('model','')}"}
                              for i, p in enumerate(ranked)]})

    total_rankings = len(sections) + (1 if composite_ranked else 0)
    body = (crumbs(crumb_items) +
            "<h1>Best Heat Pumps \u2014 Rankings</h1>"
            f'<p class="sub">{total_rankings} data-driven rankings \u00b7 updated {TODAY}</p>'
            f'<p>Every ranking below is generated automatically from the specifications in the {SITE_NAME}, '
            f'compared at matching test conditions wherever possible, and updates as new products are added.</p>'
            f'<div class="best-toc">{toc}</div>'
            + section_html +
            f'<p style="margin-top:20px"><a class="cta" href="{BASE_URL}/#compare">Compare selected products side-by-side &rarr;</a></p>')

    return page(f"Best Heat Pumps {TODAY[:4]} \u2014 Data-Driven Rankings | {SITE_NAME}",
                f"The best heat pumps ranked by real specification data: SCOP, noise, refrigerant and capacity band. "
                f"{total_rankings} rankings on one page, updated automatically from the {SITE_NAME}.",
                url, body, item_lds + [breadcrumb_jsonld(crumb_items, url)], active="best", og_image=get_og_image())

# ───────────────────────── Build ─────────────────────────
def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def _lastmod_hash(obj):
    """Deterministic content fingerprint used to decide sitemap <lastmod> dates.
    We hash the underlying data behind each page (not the rendered HTML, since
    that can contain build-time-only text like "updated {TODAY}" on the best-of
    pages) so a page's lastmod only advances when something a visitor would
    actually see has changed - not on every rebuild. Google explicitly discounts
    lastmod signals it can't trust, so a sitemap where every URL shares today's
    date on every deploy is worse than no lastmod at all."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()[:16]

def extract_app_section(start_id, end_marker):
    """Pull a knowledge page's inner HTML out of the app (index.html) so the
    static SEO page and the in-app page never drift apart."""
    app_path = os.path.join(ROOT, "index.html")
    if not os.path.exists(app_path):
        return None
    app = open(app_path, encoding="utf-8").read()
    start = app.find(f'<div class="page" id="{start_id}">')
    if start == -1:
        return None
    end = app.find(end_marker, start)
    block = app[start:end if end != -1 else len(app)]
    marker = '<div style="padding:8px 0 4px">'
    if marker not in block:
        return None
    inner = block.split(marker, 1)[1]
    for _ in range(3):                       # drop padding/container/page wrapper closers
        inner = inner.rstrip()
        if inner.endswith('</div>'):
            inner = inner[:-len('</div>')]
    inner = inner.strip()
    inner = re.sub(r'^\s*<nav\b.*?</nav>', '', inner, count=1, flags=re.S)   # drop in-app breadcrumb
    inner = re.sub(r'\s*onclick="(?:showPage|openFaqItem)\([^)]*\)[^"]*"', '', inner)  # neutralise app handlers
    inner = inner.replace('href="#"', f'href="{BASE_URL}/"')
    return inner.strip()

# Knowledge guides that exist as app sections and are mirrored to static SEO pages.
# end_marker is the HTML comment that opens the NEXT section in index.html.
KNOWLEDGE_PAGES = [
    {"page_id": "page-what-is-a-heat-pump", "end_marker": "<!-- ═══ REFRIGERANT GUIDE ═══ -->",
     "dir": "what-is-a-heat-pump", "active": "what-is-a-heat-pump", "crumb": "What Is a Heat Pump?",
     "headline": "What Is a Heat Pump?",
     "title": f"What Is a Heat Pump? A Plain-English Guide | {SITE_NAME}",
     "desc": ("What a heat pump is and how it works, explained for complete beginners with diagrams. "
              "Includes a straight comparison against gas boilers and the key things to consider before switching.")},
    {"page_id": "page-refrigerants", "end_marker": "<!-- ═══ COP & SCOP GUIDE ═══ -->",
     "dir": "refrigerants", "active": "refrigerants", "crumb": "Refrigerant Guide",
     "headline": "Heat Pump Refrigerants Compared",
     "title": f"Heat Pump Refrigerants Compared: GWP, Safety & F-Gas Rules | {SITE_NAME}",
     "desc": ("Compare the refrigerants used in heat pumps: GWP, safety class, pros and cons, and the "
              "EU and UK F-Gas regulations. R290, R32, R410A, CO2, ammonia, HFOs and low-GWP blends.")},
    {"page_id": "page-cop-scop", "end_marker": "<!-- ═══ FLOW TEMPERATURE GUIDE ═══ -->",
     "dir": "cop-scop", "active": "cop-scop", "crumb": "Understanding COP & SCOP",
     "headline": "Understanding COP & SCOP",
     "title": f"Understanding Heat Pump COP & SCOP: Test Conditions Explained | {SITE_NAME}",
     "desc": ("What COP and SCOP mean for heat pumps, why test conditions like A7/W35 and W35 vs W55 "
              "matter, how seasonal SCOP differs from COP, and how to compare efficiency figures fairly.")},
    {"page_id": "page-flow-temp", "end_marker": "<!-- ═══ INSTALLATION COSTS GUIDE ═══ -->",
     "dir": "flow-temperature", "active": "flow-temp", "crumb": "Flow Temperature & Efficiency",
     "headline": "Flow Temperature & Efficiency",
     "title": f"Heat Pump Flow Temperature & Efficiency Explained | {SITE_NAME}",
     "desc": ("Why a lower flow temperature makes a heat pump more efficient, the trade-off with radiator "
              "and underfloor sizing, weather compensation, and how flow temperature relates to COP and SCOP.")},
    {"page_id": "page-install-costs", "end_marker": "<!-- ═══ FUNDING GUIDE ═══ -->",
     "dir": "installation-costs", "active": "install-costs", "crumb": "Installation Costs",
     "headline": "ASHP Installation Costs Explained",
     "title": f"Air Source Heat Pump Installation Costs UK 2026 | {SITE_NAME}",
     "desc": ("A breakdown of what a UK air source heat pump installation costs: the unit itself, hot water "
              "cylinder, controls, and radiator upgrades, plus typical totals before and after the Boiler "
              "Upgrade Scheme grant.")},
    {"page_id": "page-funding", "end_marker": "<!-- ═══ PLANNING PERMISSION GUIDE ═══ -->",
     "dir": "funding", "active": "funding", "crumb": "Funding & Grants",
     "headline": "Heat Pump Funding & Grants in the UK",
     "title": f"Heat Pump Funding & Grants UK 2026: BUS, VAT, Scotland & More | {SITE_NAME}",
     "desc": ("Every UK funding route for a heat pump in one place: the Boiler Upgrade Scheme, 0% VAT, "
              "Home Energy Scotland, Warm Homes: Local Grant, ECO4 and Northern Ireland support: amounts, "
              "eligibility and how to apply.")},
    {"page_id": "page-planning", "end_marker": "<!-- ═══ FAQ ═══ -->",
     "dir": "planning-permission", "active": "planning", "crumb": "Planning Permission",
     "headline": "UK Planning Permission for Heat Pumps",
     "title": f"UK Planning Permission for Heat Pumps 2026: England, Wales, Scotland & NI | {SITE_NAME}",
     "desc": ("Do you need planning permission for a heat pump? Permitted development rules, the "
              "application process, and typical costs for England, Wales, Scotland and Northern Ireland.")},
]

def render_knowledge_page(cfg):
    inner = extract_app_section(cfg["page_id"], cfg["end_marker"])
    if not inner:
        return None
    url = f'{BASE_URL}/knowledge/{cfg["dir"]}/'
    crumb_items = [("Home", f"{BASE_URL}/"), (cfg["crumb"], None)]
    article_ld = {"@context": "https://schema.org", "@type": "Article",
                  "headline": cfg["headline"], "description": cfg["desc"], "url": url,
                  "publisher": {"@type": "Organization", "name": SITE_NAME},
                  "mainEntityOfPage": url}
    return page(cfg["title"], cfg["desc"], url, crumbs(crumb_items) + inner,
                [article_ld, breadcrumb_jsonld(crumb_items, url)], og_type="article", active=cfg["active"],
                og_image=get_og_image())

# News article images: drop a file under ./news-images/ and reference its
# filename via the "image" field on the article entry in news.json - mirrors
# get_product_image()/get_logo_url() above (copy-on-build, cached).
NEWS_IMAGE_SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news-images")
NEWS_IMAGE_OUT_DIR = "images/news"
_NEWS_IMAGE_CACHE = {}

def get_news_image(article):
    fname = article.get("image")
    if not fname:
        return None
    if fname in _NEWS_IMAGE_CACHE:
        return _NEWS_IMAGE_CACHE[fname]
    src = os.path.join(NEWS_IMAGE_SRC_DIR, fname)
    if not os.path.isfile(src):
        return None
    out_rel = f"{NEWS_IMAGE_OUT_DIR}/{fname}"
    dest = os.path.join(ROOT, out_rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copyfile(src, dest)
    url = f"{BASE_URL}/{out_rel}"
    _NEWS_IMAGE_CACHE[fname] = url
    return url

# ─── News (product press releases, site updates, insights) ───
# Source of truth is news.json - a plain list of articles, newest-first isn't
# required in the file (we sort on load). Add a new article by appending an
# entry there and rebuilding; no other code change needed.
NEWS_CATEGORY_LABEL = {"insight": "Insight", "product": "Product News", "update": "Site Update"}
NEWS_CATEGORY_CLASS = {"insight": "article-cat-insight", "product": "article-cat-product", "update": "article-cat-update"}

def load_news():
    if not os.path.isfile(NEWS_DATA):
        return []
    with open(NEWS_DATA, encoding="utf-8") as f:
        articles = json.load(f)
    articles.sort(key=lambda a: a.get("date", ""), reverse=True)
    return articles

def _news_date_str(iso_date):
    try:
        return datetime.date.fromisoformat(iso_date).strftime("%-d %B %Y")
    except Exception:
        return iso_date or ""

def _news_cat_badge(article):
    cat = article.get("category", "update")
    label = NEWS_CATEGORY_LABEL.get(cat, cat.title())
    cls = NEWS_CATEGORY_CLASS.get(cat, "article-cat-update")
    return f'<span class="article-cat {cls}">{esc(label)}</span>'

def _news_card(article):
    url = f'{BASE_URL}/news/{article["slug"]}/'
    return (f'<a class="news-card" href="{url}">'
            f'{_news_cat_badge(article)}'
            f'<h3>{esc(article["title"])}</h3>'
            f'<p>{esc(article.get("summary", ""))}</p>'
            f'<div class="article-meta" style="margin-top:10px">{esc(_news_date_str(article.get("date")))}</div>'
            f'</a>')

def _news_row(article):
    """Full-width preview row with an image thumbnail, used on the news index."""
    url = f'{BASE_URL}/news/{article["slug"]}/'
    img_url = get_news_image(article)
    if img_url:
        thumb = f'<div class="news-row-thumb"><img src="{img_url}" alt="{esc(article["title"])}" loading="lazy"></div>'
    else:
        thumb = '<div class="news-row-thumb placeholder">Heat Pump Database</div>'
    cat = article.get("category", "update")
    return (f'<a class="news-row" data-cat="{esc(cat)}" href="{url}">'
            f'{thumb}'
            f'<div class="news-row-body">'
            f'{_news_cat_badge(article)}'
            f'<h3>{esc(article["title"])}</h3>'
            f'<p>{esc(article.get("summary", ""))}</p>'
            f'<div class="article-meta" style="margin-top:10px">{esc(_news_date_str(article.get("date")))}</div>'
            f'</div>'
            f'</a>')

NEWS_FILTER_JS = """
function newsFilter(btn){
  var cat=btn.getAttribute('data-cat');
  var chips=document.querySelectorAll('#news-filter .news-chip');
  for(var i=0;i<chips.length;i++){chips[i].classList.toggle('active',chips[i]===btn);}
  var rows=document.querySelectorAll('#news-list .news-row'),shown=0;
  for(var j=0;j<rows.length;j++){
    var match=(cat==='all'||rows[j].getAttribute('data-cat')===cat);
    rows[j].style.display=match?'':'none';
    if(match)shown++;
  }
  document.getElementById('news-empty').style.display=shown?'none':'block';
}
"""

def render_news_index(articles):
    url = f"{BASE_URL}/news/"
    title = f"News & Insight | {SITE_NAME}"
    desc = ("Product press releases, site updates and data-driven insights from Heat Pump Database - "
            "including deep dives into the specification data behind every product in the database.")
    crumb_items = [("Home", f"{BASE_URL}/"), ("News & Insight", None)]
    if articles:
        rows = "".join(_news_row(a) for a in articles)
        # Category filter. Every category in NEWS_CATEGORY_LABEL gets a chip
        # (not just the ones currently populated) so the taxonomy stays visible
        # as new articles land; empty ones are dimmed but still selectable.
        counts = {}
        for a in articles:
            c = a.get("category", "update")
            counts[c] = counts.get(c, 0) + 1
        chips = [f'<button type="button" class="news-chip active" data-cat="all" '
                 f'onclick="newsFilter(this)">All<span class="nf-n">{len(articles)}</span></button>']
        for key, label in NEWS_CATEGORY_LABEL.items():
            n = counts.get(key, 0)
            empty = " is-empty" if n == 0 else ""
            chips.append(f'<button type="button" class="news-chip{empty}" data-cat="{esc(key)}" '
                         f'onclick="newsFilter(this)">{esc(label)}<span class="nf-n">{n}</span></button>')
        filter_bar = f'<div class="news-filter" id="news-filter">{"".join(chips)}</div>'
        body_inner = (filter_bar
                      + f'<div class="news-list" id="news-list">{rows}</div>'
                      + '<p class="news-empty" id="news-empty">No articles in this category yet.</p>'
                      + f'<script>{NEWS_FILTER_JS}</script>')
    else:
        body_inner = '<p style="color:#5b6b6b">No articles published yet - check back soon.</p>'
    body = (crumbs(crumb_items) +
            '<h1 style="font-size:28px;letter-spacing:-.02em;margin:0 0 8px">News &amp; Insight</h1>'
            '<p style="color:#5b6b6b;font-size:15px;line-height:1.6;margin:0 0 24px;max-width:680px">'
            'New product press releases, site updates, and insights drawn directly from the specification '
            'data in this database.</p>' + body_inner)
    ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": "News & Insight",
          "description": desc, "url": url, "publisher": {"@type": "Organization", "name": SITE_NAME}}
    return page(title, desc, url, body, [ld, breadcrumb_jsonld(crumb_items, url)], og_type="website",
                active="news", og_image=get_og_image())

def render_news_article(article, all_articles):
    url = f'{BASE_URL}/news/{article["slug"]}/'
    title = f'{article["title"]} | {SITE_NAME} News'
    desc = article.get("summary", article["title"])
    crumb_items = [("Home", f"{BASE_URL}/"), ("News & Insight", f"{BASE_URL}/news/"), (article["title"], None)]
    date_str = _news_date_str(article.get("date"))
    author = article.get("author")
    author_bit = f'<span> &middot; by {esc(author)}</span>' if author else ""
    header = f'<div class="article-meta">{_news_cat_badge(article)}<span>{esc(date_str)}</span>{author_bit}</div>'
    img_url = get_news_image(article)
    hero = ""
    if img_url:
        img_credit = article.get("image_credit", SITE_NAME)
        hero = (f'<div class="article-hero"><img src="{img_url}" alt="{esc(article["title"])}" '
                f'onclick="openPhotoLightbox(this.src,this.alt)">'
                f'<div class="article-hero-credit">{esc(img_credit)}'
                f'<span class="article-hero-zoom">Click to enlarge</span></div></div>')
    # Optional "TL;DR" summary strip - one or two sentences, rendered right
    # after the hero image and before the full body. Set via the "tldr" field
    # on the article entry in news.json (a plain string). Purely optional -
    # articles without one render exactly as before.
    tldr_text = article.get("tldr") or ""
    if isinstance(tldr_text, list):  # tolerate the old list-of-bullets shape
        tldr_text = " ".join(tldr_text)
    tldr_block = ""
    if tldr_text:
        tldr_block = (f'<div class="article-tldr"><span class="article-tldr-label">TL;DR</span>'
                       f'<p>{esc(tldr_text)}</p></div>')
    others = [a for a in all_articles if a["slug"] != article["slug"]][:3]
    related = ""
    if others:
        related = ('<h2 style="font-size:18px;margin:34px 0 12px">More from News &amp; Insight</h2>'
                    f'<div class="news-grid">{"".join(_news_card(a) for a in others)}</div>')
    body = (crumbs(crumb_items) +
            f'<h1 style="font-size:28px;letter-spacing:-.02em;margin:0 0 10px;max-width:760px">{esc(article["title"])}</h1>'
            + header + hero + tldr_block +
            f'<div class="article-body">{article.get("body_html", "")}</div>'
            + related)
    ld = {"@context": "https://schema.org", "@type": "NewsArticle", "headline": article["title"],
          "description": desc, "url": url, "datePublished": article.get("date"),
          "publisher": {"@type": "Organization", "name": SITE_NAME},
          "mainEntityOfPage": url}
    if author:
        ld["author"] = {"@type": "Organization", "name": author}
    if img_url:
        ld["image"] = img_url
    return page(title, desc, url, body, [ld, breadcrumb_jsonld(crumb_items, url)], og_type="article",
                active="news", og_image=img_url or get_og_image())

def render_size_calculator_page():
    title = f"Heat Pump Size Calculator — What kW Do You Need? | {SITE_NAME}"
    desc = ("Free UK heat pump size calculator. Estimate the kW your home needs and your annual "
            "running cost in seconds, then see matching air and ground source heat pumps from the database.")
    canonical = f"{BASE_URL}/heat-pump-size-calculator/"
    jsonld = [{
        "@context": "https://schema.org",
        "@type": "WebApplication",
        "name": "Heat Pump Size Calculator",
        "url": canonical,
        "applicationCategory": "UtilitiesApplication",
        "operatingSystem": "Any (web browser)",
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "GBP"},
        "description": desc,
        "isPartOf": {"@type": "WebSite", "name": SITE_NAME, "url": f"{BASE_URL}/"}
    }]
    body = f"""
<style>{CALC_CSS}</style>
<nav class="crumbs"><a href="{BASE_URL}/">Home</a> &rsaquo; <span>Heat Pump Size Calculator</span></nav>
<h1>Heat Pump Size Calculator</h1>
<p class="sub">Get a ballpark design heat loss (for sizing) and annual heat demand (for running costs) for a home, then see which heat pumps in the database could cover it. Start with a quick estimate, or switch to the detailed version to refine it.</p>
<p class="dm-note">For residential properties only. This is an indicative planning tool, not a substitute for a full room-by-room heat loss survey &mdash; get one from an <a href="https://mcscertified.com/product-directory/" target="_blank" rel="noopener">MCS-certified installer</a> before sizing or buying a system.</p>

<div class="dm-tabs">
  <button class="dm-tab active" id="dm-tab-simple" onclick="demandSetMode('simple')">Simple estimate</button>
  <button class="dm-tab" id="dm-tab-detailed" onclick="demandSetMode('detailed')">Detailed estimate</button>
</div>

<div id="dm-form-simple">
  <div class="dm-grid">
    <div class="dm-field">
      <label for="dm-s-floorarea">Total floor area, all storeys (m&sup2;)</label>
      <input type="number" id="dm-s-floorarea" min="20" max="1000" step="1" value="90" oninput="demandRecalc()">
      <div class="dm-hint">Total internal floor area added up across every floor of the home &mdash; the same figure as on an EPC, not just the ground-floor footprint.</div>
    </div>
    <div class="dm-field">
      <label for="dm-s-ptype">Property type</label>
      <select id="dm-s-ptype" onchange="demandRecalc()"></select>
    </div>
    <div class="dm-field">
      <label for="dm-s-ageband">Age of property</label>
      <select id="dm-s-ageband" onchange="demandRecalc()"></select>
    </div>
    <div class="dm-field">
      <label for="dm-s-insulation">Insulation upgrades</label>
      <select id="dm-s-insulation" onchange="demandRecalc()">
        <option value="asbuilt">As built for its age</option>
        <option value="upgraded">Some upgrades (loft + cavity wall insulated)</option>
        <option value="high">Well insulated (external wall insulation / near current Building Regs)</option>
      </select>
    </div>
    <div class="dm-field">
      <label for="dm-s-scop">Assumed SCOP</label>
      <input type="number" id="dm-s-scop" value="3.5" min="2" max="6" step="0.1" oninput="demandRecalc()">
      <div class="dm-hint">Seasonal efficiency of the heat pump you might install &mdash; check a model's SCOP on its product page.</div>
    </div>
    <div class="dm-field">
      <label for="dm-s-price">Electricity price (p/kWh)</label>
      <input type="number" id="dm-s-price" value="25.3" min="5" max="60" step="0.1" oninput="demandRecalc()">
      <div class="dm-hint">Defaults to the current Ofgem price cap unit rate &mdash; edit for your own tariff.</div>
    </div>
  </div>
</div>

<div id="dm-form-detailed" style="display:none">
  <div class="dm-grid">
    <div class="dm-field">
      <label for="dm-d-floorarea">Total floor area, all storeys (m&sup2;)</label>
      <input type="number" id="dm-d-floorarea" min="20" max="1000" step="1" value="90" oninput="demandRecalc()">
      <div class="dm-hint">Total internal floor area added up across every floor of the home &mdash; the same figure as on an EPC, not just the ground-floor footprint.</div>
    </div>
    <div class="dm-field">
      <label for="dm-d-ptype">Property type</label>
      <select id="dm-d-ptype" onchange="demandRecalc()"></select>
    </div>
    <div class="dm-field">
      <label for="dm-d-storeys">Number of storeys</label>
      <select id="dm-d-storeys" onchange="demandRecalc()">
        <option value="1">1 (single storey)</option>
        <option value="1.5">1.5 (dormer / chalet)</option>
        <option value="2" selected>2</option>
        <option value="3">3+</option>
      </select>
      <div class="dm-hint">Only used to split your total floor area above into per-floor wall &amp; roof area &mdash; doesn't need to be exact.</div>
    </div>
    <div class="dm-field">
      <label for="dm-d-ageband">Age of property</label>
      <select id="dm-d-ageband" onchange="demandRecalc()"></select>
    </div>
    <div class="dm-field">
      <label for="dm-d-region">UK region</label>
      <select id="dm-d-region" onchange="demandRecalc()"></select>
    </div>
    <div class="dm-field">
      <label for="dm-d-glazing">Glazing</label>
      <select id="dm-d-glazing" onchange="demandRecalc()"></select>
    </div>
    <div class="dm-field">
      <label for="dm-d-ventilation">Ventilation</label>
      <select id="dm-d-ventilation" onchange="demandRecalc()"></select>
    </div>
    <div class="dm-field">
      <label for="dm-d-internaltemp">Target indoor temp (&deg;C)</label>
      <input type="number" id="dm-d-internaltemp" min="16" max="24" step="0.5" value="21" oninput="demandRecalc()">
    </div>
    <div class="dm-field">
      <label for="dm-d-scop">Assumed SCOP</label>
      <input type="number" id="dm-d-scop" value="3.5" min="2" max="6" step="0.1" oninput="demandRecalc()">
      <div class="dm-hint">Seasonal efficiency of the heat pump you might install &mdash; check a model's SCOP on its product page.</div>
    </div>
    <div class="dm-field">
      <label for="dm-d-price">Electricity price (p/kWh)</label>
      <input type="number" id="dm-d-price" value="25.3" min="5" max="60" step="0.1" oninput="demandRecalc()">
      <div class="dm-hint">Defaults to the current Ofgem price cap unit rate &mdash; edit for your own tariff.</div>
    </div>
  </div>
  <div class="dm-check-row">
    <input type="checkbox" id="dm-d-wallupgrade" onchange="demandRecalc()"><label for="dm-d-wallupgrade">Walls insulated beyond original build (cavity fill / external wall insulation)</label>
  </div>
  <div class="dm-check-row">
    <input type="checkbox" id="dm-d-roofupgrade" onchange="demandRecalc()"><label for="dm-d-roofupgrade">Loft/roof insulation topped up to modern standard (~270mm)</label>
  </div>
  <div class="dm-assumptions" id="dm-assumptions"></div>
</div>

<div class="dm-results">
  <div class="dm-result-row">
    <div class="dm-result-block">
      <div class="dm-result-label">Design heat loss (peak)</div>
      <div class="dm-result-value" id="dm-peak-value">&mdash;</div>
      <div class="dm-result-sub" id="dm-peak-sub"></div>
    </div>
    <div class="dm-result-block">
      <div class="dm-result-label">Estimated annual heat demand</div>
      <div class="dm-result-value" id="dm-annual-value">&mdash;</div>
      <div class="dm-result-sub" id="dm-annual-sub"></div>
    </div>
    <div class="dm-result-block">
      <div class="dm-result-label">Estimated annual running cost</div>
      <div class="dm-result-value" id="dm-cost-value">&mdash;</div>
      <div class="dm-result-sub" id="dm-cost-sub"></div>
    </div>
  </div>
</div>

<h2 class="sec">Heat pumps that could cover this</h2>
<p class="sub" style="margin-bottom:4px">Residential models from the database whose rated heating capacity covers the estimated design heat loss above: up to 6 air source (ASHP) and 2 ground source (GSHP) options.</p>
<div id="dm-rec-groups"></div>

<p class="dm-note">Method: whole-dwelling fabric and ventilation heat loss following the CIBSE Domestic Heating Design Guide approach, using indicative UK regional design temperatures and degree-day data. U-values are typical defaults for the age band selected, not measured values for your actual property, and envelope areas are estimated from floor area, storeys and property shape rather than measured room-by-room. Figures exclude solar and internal gains, which in practice reduce real-world running costs somewhat. Always confirm sizing with a full MCS heat-loss survey before purchase &mdash; see our <a href="{BASE_URL}/knowledge/installation-costs/">installation costs guide</a> for what that typically involves.</p>

<h2 class="sec">Related reading</h2>
<div class="grid">
  <a class="card" href="{BASE_URL}/knowledge/installation-costs/"><div class="m">Installation costs</div><div class="s">What a UK ASHP install actually costs, broken down</div></a>
  <a class="card" href="{BASE_URL}/knowledge/cop-scop/"><div class="m">Understanding COP &amp; SCOP</div><div class="s">How to compare running-cost efficiency between models</div></a>
  <a class="card" href="{BASE_URL}/knowledge/flow-temperature/"><div class="m">Flow temperature &amp; efficiency</div><div class="s">Why radiator sizing matters for running costs</div></a>
  <a class="card" href="{BASE_URL}/"><div class="m">Browse the full database</div><div class="s">3,000+ heat pumps with full specifications</div></a>
</div>
<script src="/demand-calc.js" defer></script>
"""
    return page(title, desc, canonical, body, jsonld, active="size-calc")

def main():
    with open(DATA, encoding="utf-8") as f:
        products = json.load(f)

    # clean previously generated output
    for d in GENERATED_DIRS:
        shutil.rmtree(os.path.join(ROOT, d), ignore_errors=True)

    # assign unique slugs
    seen = {}
    for p in products:
        base = slugify(f"{p.get('manufacturer','')} {p.get('model','')}")
        slug = base
        if slug in seen:
            slug = f"{base}-{p.get('id','')}"
            k = 2
            while slug in seen:
                slug = f"{base}-{p.get('id','')}-{k}"; k += 1
        seen[slug] = True
        p["_slug"] = slug

    # Derived £/kW (peak heating capacity) figure, used by the residential
    # best-of "value" rankings below. Uses the midpoint of price_min/price_max
    # where both are known, otherwise whichever one is available. Only set
    # when both a price and a peak capacity (cap_max) exist.
    for p in products:
        pmin, pmax, cap = p.get("price_min"), p.get("price_max"), p.get("cap_max")
        price = None
        if pmin is not None and pmax is not None:
            price = (pmin + pmax) / 2
        elif pmin is not None:
            price = pmin
        elif pmax is not None:
            price = pmax
        if price is not None and cap:
            p["gbp_per_kw"] = round(price / cap)

    by_mfr, by_type = {}, {}
    for p in products:
        by_mfr.setdefault(p.get("manufacturer", ""), []).append(p)
        by_type.setdefault(p.get("hp_type"), []).append(p)

    # --- Per-page content fingerprints, for sitemap.xml <lastmod> ---
    # See _lastmod_hash() above. product_hash_by_id lets every page that lists
    # or aggregates products (manufacturer/category/best-of pages) derive its
    # own fingerprint from exactly the product data it displays, so it only
    # gets a fresh lastmod when a product it actually shows has changed.
    product_hash_by_id = {
        p.get("id"): _lastmod_hash({k: v for k, v in p.items() if k != "_slug"})
        for p in products
    }
    lastmod_path = os.path.join(ROOT, "lastmod.json")
    try:
        with open(lastmod_path, encoding="utf-8") as f:
            prev_lastmod = json.load(f)   # read-only snapshot from the last build
    except FileNotFoundError:
        prev_lastmod = {}
    lastmod_cache = {}   # freshly rebuilt this run, written out at the end

    def _lastmod_for(url, page_hash):
        """Return this URL's lastmod date: today's date if its content hash is
        new or changed since the *last build* (never against updates made
        earlier in this same run), otherwise the date already on record - so
        the sitemap only claims a page changed when it really did."""
        prev = prev_lastmod.get(url)
        date = TODAY if (not prev or prev.get("hash") != page_hash) else prev["date"]
        lastmod_cache[url] = {"hash": page_hash, "date": date}
        return date

    urls = [f"{BASE_URL}/"]
    with open(os.path.join(ROOT, "index.html"), "rb") as f:
        _lastmod_for(f"{BASE_URL}/", hashlib.sha256(f.read()).hexdigest()[:16])

    # product pages
    for p in products:
        write(os.path.join(ROOT, "products", p["_slug"], "index.html"),
              render_product(p, by_mfr, by_type))
        url = f"{BASE_URL}/products/{p['_slug']}/"
        urls.append(url)
        _lastmod_for(url, product_hash_by_id[p.get("id")])

    # --- Slug history & redirect stubs ---
    # A product's URL slug is derived from its manufacturer+model text, so any time
    # that text is corrected (e.g. fixing a generic name that collided with sibling
    # products - see the MasterTherm/CTC/Grant cases), the URL changes. This site has
    # no server-side redirect support (static GitHub Pages hosting), so without this,
    # every corrected product silently orphans its previously-indexed URL: Google
    # keeps it in the index pointing at a 404 forever. slug_history.json persists
    # every slug a product has ever had; any historical slug no longer claimed by a
    # live product gets a lightweight redirect stub (meta-refresh + canonical) so
    # search engines consolidate to the current URL instead of hard-404ing.
    history_path = os.path.join(ROOT, "slug_history.json")
    try:
        with open(history_path, encoding="utf-8") as f:
            slug_history = json.load(f)
    except FileNotFoundError:
        slug_history = {}

    for p in products:
        pid = str(p.get("id", ""))
        hist = slug_history.setdefault(pid, [])
        if p["_slug"] not in hist:
            hist.append(p["_slug"])

    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(slug_history, f, indent=2, ensure_ascii=False)

    current_slugs = {p["_slug"] for p in products}
    current_url_by_id = {str(p.get("id", "")): f"{BASE_URL}/products/{p['_slug']}/" for p in products}
    redirect_count = 0
    for pid, hist in slug_history.items():
        target = current_url_by_id.get(pid)
        if not target:
            continue  # product no longer exists at all; nothing to redirect to
        for old_slug in hist:
            if old_slug in current_slugs:
                continue  # still a live slug (current, or reused/claimed by another product)
            stub = (f"<!DOCTYPE html><html lang=\"en-GB\"><head><meta charset=\"utf-8\">"
                    f"<title>Redirecting\u2026 | {SITE_NAME}</title>"
                    f"<link rel=\"canonical\" href=\"{target}\">"
                    f"<meta http-equiv=\"refresh\" content=\"0; url={target}\">"
                    f"</head><body><p>This page has moved. "
                    f"<a href=\"{target}\">Continue to the updated page</a>.</p></body></html>")
            write(os.path.join(ROOT, "products", old_slug, "index.html"), stub)
            redirect_count += 1

    # manufacturer pages + index
    for m, ps in by_mfr.items():
        write(os.path.join(ROOT, "manufacturers", slugify(m), "index.html"),
              render_manufacturer(m, ps))
        url = f"{BASE_URL}/manufacturers/{slugify(m)}/"
        urls.append(url)
        _lastmod_for(url, _lastmod_hash(sorted(product_hash_by_id[p.get("id")] for p in ps)))
    write(os.path.join(ROOT, "manufacturers", "index.html"),
          render_manufacturers_index(by_mfr))
    url = f"{BASE_URL}/manufacturers/"
    urls.append(url)
    _lastmod_for(url, _lastmod_hash(sorted(by_mfr.keys())))

    # category pages: source type
    type_pages = []
    for code, label in TYPE_LABEL.items():
        ps = by_type.get(code, [])
        if ps:
            type_pages.append((slugify(label.split(" (")[0] + " heat pumps"),
                               label.split(" (")[0] + " Heat Pumps",
                               f"Browse {label.split(' (')[0].lower()} heat pumps in the {SITE_NAME}: "
                               f"{len(ps)} models with full specifications, COP and SCOP data.", ps))
    # refrigerant pages
    by_ref = {}
    for p in products:
        if p.get("refrigerant"):
            by_ref.setdefault(p["refrigerant"], []).append(p)
    for ref, ps in by_ref.items():
        if len(ps) >= 5:
            type_pages.append((slugify(f"{ref} heat pumps"), f"{ref} Heat Pumps",
                               f"Heat pumps using {ref} refrigerant: {len(ps)} models with full "
                               f"specifications in the {SITE_NAME}.", ps))
    # application pages
    by_app = {}
    for p in products:
        if p.get("type"):
            by_app.setdefault(p["type"], []).append(p)
    for app, ps in by_app.items():
        type_pages.append((slugify(f"{app} heat pumps"), f"{app} Heat Pumps",
                           f"{app} heat pumps: {len(ps)} models with specifications, COP and SCOP "
                           f"data in the {SITE_NAME}.", ps))

    seen_type_slugs = set()
    for slug, heading, desc, ps in type_pages:
        if slug in seen_type_slugs:
            continue   # same slug already produced by an earlier grouping pass
        seen_type_slugs.add(slug)
        write(os.path.join(ROOT, "types", slug, "index.html"),
              render_type(slug, heading, desc, ps))
        url = f"{BASE_URL}/types/{slug}/"
        urls.append(url)
        _lastmod_for(url, _lastmod_hash(sorted(product_hash_by_id[p.get("id")] for p in ps)))

    # redirect stubs for legacy category-page slugs (see LEGACY_TYPE_REDIRECTS)
    # - not added to `urls`/sitemap, same as product slug redirects: these
    # exist only so an old indexed/bookmarked URL doesn't hard-404.
    legacy_type_redirects_written = 0
    for old_slug, target_slug in LEGACY_TYPE_REDIRECTS.items():
        if target_slug not in seen_type_slugs or old_slug in seen_type_slugs:
            continue  # target no longer exists, or old_slug is itself a live page now
        target_url = f"{BASE_URL}/types/{target_slug}/"
        stub = (f"<!DOCTYPE html><html lang=\"en-GB\"><head><meta charset=\"utf-8\">"
                f"<title>Redirecting\u2026 | {SITE_NAME}</title>"
                f"<link rel=\"canonical\" href=\"{target_url}\">"
                f"<meta http-equiv=\"refresh\" content=\"0; url={target_url}\">"
                f"</head><body><p>This page has moved. "
                f"<a href=\"{target_url}\">Continue to the updated page</a>.</p></body></html>")
        write(os.path.join(ROOT, "types", old_slug, "index.html"), stub)
        legacy_type_redirects_written += 1

    # knowledge guides (static SEO pages generated from the app content)
    kg_count = 0
    for cfg in KNOWLEDGE_PAGES:
        html_ = render_knowledge_page(cfg)
        if html_:
            write(os.path.join(ROOT, "knowledge", cfg["dir"], "index.html"), html_)
            url = f'{BASE_URL}/knowledge/{cfg["dir"]}/'
            urls.append(url)
            _lastmod_for(url, hashlib.sha256(html_.encode("utf-8")).hexdigest()[:16])
            kg_count += 1

    # news (product press releases, site updates, insights)
    news_articles = load_news()
    for article in news_articles:
        html_ = render_news_article(article, news_articles)
        write(os.path.join(ROOT, "news", article["slug"], "index.html"), html_)
        url = f'{BASE_URL}/news/{article["slug"]}/'
        urls.append(url)
        _lastmod_for(url, hashlib.sha256(html_.encode("utf-8")).hexdigest()[:16])
    news_index_html = render_news_index(news_articles)
    write(os.path.join(ROOT, "news", "index.html"), news_index_html)
    news_index_url = f"{BASE_URL}/news/"
    urls.append(news_index_url)
    _lastmod_for(news_index_url, hashlib.sha256(news_index_html.encode("utf-8")).hexdigest()[:16])

    # redirect stub: /knowledge/boiler-upgrade-scheme/ was the URL for this guide
    # before it was renamed and expanded into the broader "funding" hub page.
    # It was live (indexed) briefly, so redirect rather than 404 it. Not added
    # to the sitemap, same as the legacy product/type redirects above.
    _bus_redirect_target = f"{BASE_URL}/knowledge/funding/"
    _bus_redirect_stub = (f"<!DOCTYPE html><html lang=\"en-GB\"><head><meta charset=\"utf-8\">"
            f"<title>Redirecting\u2026 | {SITE_NAME}</title>"
            f"<link rel=\"canonical\" href=\"{_bus_redirect_target}\">"
            f"<meta http-equiv=\"refresh\" content=\"0; url={_bus_redirect_target}\">"
            f"</head><body><p>This page has moved. "
            f"<a href=\"{_bus_redirect_target}\">Continue to the updated page</a>.</p></body></html>")
    write(os.path.join(ROOT, "knowledge", "boiler-upgrade-scheme", "index.html"), _bus_redirect_stub)

    # The site's ranking destination is now the single consolidated /best/
    # page ("Best Heat Pumps"): the blended composite score at the top,
    # followed by every single-metric BEST_PAGES category as its own
    # stacked section. This replaced the earlier /top-10/ multi-page
    # section (a separate hub plus 9 individual per-metric pages) - the two
    # were showing overlapping rankings on separate URLs, so /top-10/ has
    # been retired in favour of this one page. Old /best/<slug>/ and
    # /top-10/(...)/ URLs get redirect stubs below in case any were
    # indexed or bookmarked.
    best_sections = []
    for cfg in BEST_PAGES:
        pool = [p for p in products if cfg["filter"](p)]
        ranked = sorted(pool, key=cfg["sort"])
        ranked = _dedupe_variants(ranked, cfg["metric"])[:cfg.get("top_n", BEST_TOP_N)]
        if len(ranked) < 5:
            continue
        best_sections.append((cfg, ranked, len(pool)))

    composite_ranked, composite_pool = _composite_ashp_ranking(products)
    write(os.path.join(ROOT, "best", "index.html"),
          render_best_single_page((composite_ranked, composite_pool), best_sections))
    url = f"{BASE_URL}/best/"
    urls.append(url)
    _lastmod_for(url, _lastmod_hash(
        [("__composite_ashp__", [p.get("id") for p in composite_ranked])] +
        [(cfg["slug"], [p.get("id") for p in ranked]) for cfg, ranked, _ in best_sections]))

    # best_winners: product id -> list of {title, url} for every ranking on
    # /best/ where that product is the #1 result. Consumed by the interactive
    # app (index.html) to show a small trophy badge on the product's card and
    # in its detail modal, so a #1 result is visible without leaving the app.
    best_winners = {}
    if composite_ranked:
        _pid = composite_ranked[0].get("id")
        best_winners.setdefault(_pid, []).append(
            {"title": "Best Overall Air Source Heat Pumps", "url": f"{BASE_URL}/best/#best-overall-ashp"})
    for cfg, ranked, _pool in best_sections:
        if ranked:
            _pid = ranked[0].get("id")
            best_winners.setdefault(_pid, []).append(
                {"title": cfg["title"], "url": f"{BASE_URL}/best/#{cfg['slug']}"})

    # redirect stubs: general Best Of categories used to each have their own
    # /best/<slug>/ page; they're now sections on the single /best/ page.
    for _old_slug in ("best-air-source-heat-pumps-by-scop", "quietest-air-source-heat-pumps",
                       "best-r290-heat-pumps", "best-small-heat-pumps-3-6kw",
                       "best-medium-heat-pumps-7-12kw", "best-large-heat-pumps-13-25kw",
                       "best-high-temperature-heat-pumps"):
        _target = f"{BASE_URL}/best/#{_old_slug}"
        _stub = (f"<!DOCTYPE html><html lang=\"en-GB\"><head><meta charset=\"utf-8\">"
                 f"<title>Redirecting\u2026 | {SITE_NAME}</title>"
                 f"<link rel=\"canonical\" href=\"{BASE_URL}/best/\">"
                 f"<meta http-equiv=\"refresh\" content=\"0; url={_target}\">"
                 f"</head><body><p>This ranking now lives on the combined Best Of page. "
                 f"<a href=\"{_target}\">Continue to the updated page</a>.</p></body></html>")
        write(os.path.join(ROOT, "best", _old_slug, "index.html"), _stub)

    # redirect stubs: /top-10/ (hub + all individual per-metric pages) has
    # been retired in favour of the single /best/ page above.
    for _old_slug in (None, "ashp-scop", "ashp-price-per-kw", "ashp-quietest", "ashp-seer",
                       "wshp-scop", "wshp-quietest", "wshp-seer", "gshp-scop",
                       "gshp-price-per-kw", "gshp-quietest"):
        _target = f"{BASE_URL}/best/"
        _stub = (f"<!DOCTYPE html><html lang=\"en-GB\"><head><meta charset=\"utf-8\">"
                 f"<title>Redirecting\u2026 | {SITE_NAME}</title>"
                 f"<link rel=\"canonical\" href=\"{_target}\">"
                 f"<meta http-equiv=\"refresh\" content=\"0; url={_target}\">"
                 f"</head><body><p>Top 10 rankings are now part of the combined Best Heat Pumps page. "
                 f"<a href=\"{_target}\">Continue to the updated page</a>.</p></body></html>")
        _out_path = (os.path.join(ROOT, "top-10", "index.html") if _old_slug is None
                     else os.path.join(ROOT, "top-10", _old_slug, "index.html"))
        write(_out_path, _stub)

    # heat pump size calculator: standalone interactive page (not extracted
    # from the app, unlike the knowledge guides) so it gets its own indexable
    # URL, title and meta description instead of living only inside the SPA.
    calc_html = render_size_calculator_page()
    write(os.path.join(ROOT, "heat-pump-size-calculator", "index.html"), calc_html)
    url = f"{BASE_URL}/heat-pump-size-calculator/"
    urls.append(url)
    _lastmod_for(url, hashlib.sha256(calc_html.encode("utf-8")).hexdigest()[:16])

    # calc-products.json: trimmed residential-only dataset (id, capacity,
    # efficiency, price, product URL) that the calculator page's demand-calc.js
    # fetches client-side for its "heat pumps that could cover this"
    # recommendations. Kept separate and far smaller than the full data.js so
    # the calculator page doesn't need to load the whole app's dataset.
    calc_products = [
        {
            "id": p.get("id"),
            "manufacturer": p.get("manufacturer"),
            "model": p.get("model"),
            "hp_type": p.get("hp_type"),
            "type": p.get("type"),
            "cap_min": p.get("cap_min"),
            "cap_max": p.get("cap_max"),
            "refrigerant": p.get("refrigerant"),
            "cop": p.get("cop"),
            "scop": p.get("scop"),
            "price_min": p.get("price_min"),
            "price_max": p.get("price_max"),
            "url": f"{BASE_URL}/products/{p['_slug']}/",
        }
        for p in products
        if p.get("type") == "Residential" and p.get("cap_max") is not None
    ]
    write(os.path.join(ROOT, "calc-products.json"), json.dumps(calc_products, ensure_ascii=False))

    # sitemap.xml - lastmod comes from lastmod_cache (see _lastmod_for above),
    # which only advances a URL's date when its content actually changed.
    with open(lastmod_path, "w", encoding="utf-8") as f:
        json.dump(lastmod_cache, f, indent=2, ensure_ascii=False, sort_keys=True)

    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        date = lastmod_cache.get(u, {}).get("date", TODAY)
        sm.append(f"  <url><loc>{u}</loc><lastmod>{date}</lastmod></url>")
    sm.append("</urlset>")
    write(os.path.join(ROOT, "sitemap.xml"), "\n".join(sm))

    # logos.js: manufacturer -> logo URL map, consumed by the interactive app
    # (index.html) so its product cards can show the same logo/badge used on
    # the static pages, without the client needing to guess file extensions.
    logo_map = {m: get_logo_url(m) for m in by_mfr}
    write(os.path.join(ROOT, "logos.js"),
          "const MFR_LOGOS = " + json.dumps(logo_map, ensure_ascii=False) + ";\n")

    # product-images.js: lookup key -> real photo URL map, same idea as
    # logos.js but for per-SKU product photography (see PRODUCT_IMAGE_BY_CODE
    # / PRODUCT_IMAGE_BY_ID). Keyed by product_code where available, falling
    # back to the numeric row id for products with no product_code (Octopus
    # Energy etc) - the client checks product_code first, then id. Consumed
    # by the interactive app so its product detail modal can show the same
    # photo used on the static pages.
    # Values are a single URL string for products with one photo, or a list
    # of URLs (first = primary/hero) for products with a gallery - the
    # client's PRODUCT_IMAGES consumers handle both shapes.
    photo_map = {}
    for p in products:
        code = p.get("product_code")
        pid = p.get("id")
        key = code if (code and code in PRODUCT_IMAGE_BY_CODE) else (pid if pid in PRODUCT_IMAGE_BY_ID else None)
        if key is not None:
            urls = get_product_images(p)
            if urls:
                photo_map[key] = urls[0] if len(urls) == 1 else urls
    write(os.path.join(ROOT, "product-images.js"),
          "const PRODUCT_IMAGES = " + json.dumps(photo_map, ensure_ascii=False) + ";\n")

    # best-winners.js: product id -> [{title,url}] for #1 results on /best/,
    # computed above during the best-of build. Same delivery pattern as
    # logos.js/product-images.js.
    write(os.path.join(ROOT, "best-winners.js"),
          "const BEST_WINNERS = " + json.dumps(best_winners, ensure_ascii=False) + ";\n")

    # robots.txt
    write(os.path.join(ROOT, "robots.txt"),
          f"User-agent: *\nAllow: /\n\nSitemap: {BASE_URL}/sitemap.xml\n")

    print(f"Built {len(products)} product pages, {len(by_mfr)} manufacturer pages, "
          f"{len(type_pages)} category pages, {kg_count} knowledge pages, "
          f"{len(best_sections)} best-of ranking sections (1 page), "
          f"{len(news_articles)} news articles.")
    print(f"sitemap.xml lists {len(urls)} URLs.")
    print(f"Wrote {redirect_count} redirect stub(s) for retired product slugs.")

if __name__ == "__main__":
    main()
