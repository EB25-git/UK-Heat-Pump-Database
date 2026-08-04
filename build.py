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
TODAY     = datetime.date.today().isoformat()

GENERATED_DIRS = ["products", "manufacturers", "types", "knowledge", "best"]

TYPE_LABEL = {"ASHP": "Air Source (ASHP)", "GSHP": "Ground Source (GSHP)",
              "WSHP": "Water Source (WSHP)"}

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
        if p["price_min"] == p["price_max"]:
            add("Price (unit only)", f"~£{num(p['price_min'])} (checked {esc(p.get('price_check_date'))})")
        else:
            add("Price (unit only)", f"£{num(p['price_min'])}&ndash;£{num(p['price_max'])} (checked {esc(p.get('price_check_date'))})")
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
CSS = """
/* ── Best-of ranking pages ── */
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
.burger-menu{position:fixed;top:60px;right:0;width:280px;background:#0F2B2B;border-left:1px solid rgba(255,255,255,.08);box-shadow:-8px 0 40px rgba(0,0,0,.3);transform:translateX(100%);transition:transform .3s ease;z-index:51;display:flex;flex-direction:column;max-height:calc(100vh - 60px);overflow-y:auto}
.burger-menu.open{transform:translateX(0)}
.burger-item{background:none;border:none;color:rgba(255,255,255,.6);font-size:15px;font-family:'Inter',sans-serif;font-weight:400;padding:16px 28px;text-align:left;transition:all .2s;border-bottom:1px solid rgba(255,255,255,.05);letter-spacing:.01em;width:100%;display:block;text-decoration:none;box-sizing:border-box}
.burger-item:hover{background:rgba(255,255,255,.05);color:#fff;text-decoration:none}
.burger-item.active{color:#3ECCC0;font-weight:500}
.burger-subitem{padding-left:50px;font-size:14px;position:relative}
.burger-subitem::before{content:"";position:absolute;left:30px;top:50%;width:9px;height:1px;background:rgba(255,255,255,.28)}.burger-toggle{display:flex;align-items:center;justify-content:space-between}.burger-chevron{width:8px;height:8px;border-right:1.5px solid currentColor;border-bottom:1.5px solid currentColor;transform:rotate(45deg);transition:transform .25s ease;flex:none;margin-left:8px;opacity:.55}.burger-toggle.open .burger-chevron{transform:rotate(-135deg)}.burger-subgroup{max-height:0;overflow:hidden;transition:max-height .3s ease}.burger-subgroup.open{max-height:420px}
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
"""

def burger_menu(active=None):
    knowledge_active = active in ("what-is-a-heat-pump", "cop-scop", "flow-temp", "refrigerants", "install-costs", "faq", "guide", "links", "knowledge")
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
        + it("Understanding COP &amp; SCOP", f"{BASE_URL}/knowledge/cop-scop/", "cop-scop", sub=True)
        + it("Flow Temperature &amp; Efficiency", f"{BASE_URL}/knowledge/flow-temperature/", "flow-temp", sub=True)
        + it("Refrigerant Guide", f"{BASE_URL}/knowledge/refrigerants/", "refrigerants", sub=True)
        + it("FAQ", f"{BASE_URL}/#faq", "faq", sub=True)
        + it("Site Guide", f"{BASE_URL}/#guide", "guide", sub=True)
        + it("Useful Links", f"{BASE_URL}/#links", "links", sub=True)
        + '</div>'
    )
    c_active = active in ("compare", "best")
    c_open = " open" if c_active else ""
    c_cls = "burger-item burger-toggle" + (" active" if c_active else "")
    compare_block = (
        f'<button class="{c_cls}{c_open}" id="c-toggle" aria-expanded="{"true" if c_active else "false"}" aria-controls="c-group" onclick="toggleCompare()">'
        f'Compare<span class="burger-chevron" aria-hidden="true"></span></button>'
        f'<div class="burger-subgroup{c_open}" id="c-group">'
        + it("Compare Selected", f"{BASE_URL}/#compare", "compare", sub=True)
        + it("Best Of Rankings", f"{BASE_URL}/best/", "best", sub=True)
        + '</div>'
    )
    return (
        it("Browse", f"{BASE_URL}/", "browse")
        + it("Manufacturers", f"{BASE_URL}/manufacturers/", "manufacturers")
        + compare_block
        + it("Visualise", f"{BASE_URL}/#analytics", "analytics")
        + knowledge_block
        + it("Contact", f"{BASE_URL}/#contact", "contact")
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
<main><div class="wrap">
{body}
</div></main>
<footer class="site"><div class="wrap">
<p>{SITE_NAME} &middot; A searchable database of UK heat pumps. Always confirm specifications with the manufacturer before purchase.</p>
<p style="margin-top:6px"><a href="{BASE_URL}/">Search the full database</a> &middot; <a href="{BASE_URL}/manufacturers/">All manufacturers</a> &middot; <a href="{BASE_URL}/knowledge/what-is-a-heat-pump/">What is a heat pump?</a> &middot; <a href="{BASE_URL}/knowledge/installation-costs/">Installation costs</a> &middot; <a href="{BASE_URL}/knowledge/refrigerants/">Refrigerant guide</a> &middot; <a href="{BASE_URL}/knowledge/cop-scop/">COP &amp; SCOP</a> &middot; <a href="{BASE_URL}/knowledge/flow-temperature/">Flow temperature</a></p>
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
<script>function tB(){{['bbtn','bmenu','bov'].forEach(function(i){{document.getElementById(i).classList.toggle('open')}})}}function cB(){{['bbtn','bmenu','bov'].forEach(function(i){{document.getElementById(i).classList.remove('open')}})}}function toggleKnowledge(){{var t=document.getElementById('k-toggle'),g=document.getElementById('k-group');var open=!g.classList.contains('open');t.classList.toggle('open',open);g.classList.toggle('open',open);t.setAttribute('aria-expanded',open);}}function toggleCompare(){{var t=document.getElementById('c-toggle'),g=document.getElementById('c-group');var open=!g.classList.contains('open');t.classList.toggle('open',open);g.classList.toggle('open',open);t.setAttribute('aria-expanded',open);}}if(!localStorage.getItem('cookie_consent')){{var cb=document.getElementById('cookie-banner');if(cb)cb.style.display='block';}}</script>
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

    # Minimal schema.org/Product identity block: name/alternateName/sku/manufacturer
    # only. We deliberately still omit offers/review/aggregateRating (see below) —
    # this block exists purely to give search engines the alternate names/codes a
    # product is known by, not to seek Product rich-result eligibility.
    # NOTE: No offers/review/aggregateRating are emitted. Google's Product rich
    # result requires one of those — none apply to an informational spec database.
    # We deliberately omit them rather than fabricate commerce data. (If real
    # pricing/reviews are ever added, a valid offers block can be added here.)
    product_ld = {
        "@context": "https://schema.org",
        "@type": "Product",
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
    product_ld["image"] = get_logo_url(mfr)
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
    body = (crumbs(crumb_items) +
            f'<div class="mfr-header"><img class="mfr-logo-sm" src="{logo}" alt="{esc(mfr)} logo" width="32" height="32">'
            f"<h1>{esc(display_name)}</h1></div>"
            f'<p class="sub">Specifications and technical data</p>'
            f'{aliases_html}'
            f'<div class="badges">{badges}</div>'
            f'<table class="spec">{rows}</table>'
            f'{mfr_link}{notes_html}{render_suppliers(p)}{render_verified(p)}{render_correction(p)}'
            f'<div class="disclaimer">Data is compiled from manufacturer sources and may contain errors or '
            f'gaps. Always confirm specifications with the manufacturer before making decisions.</div>'
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

def render_manufacturers_index(by_mfr):
    url = f"{BASE_URL}/manufacturers/"
    cards = "".join(
        f'<a class="card has-logo" href="{BASE_URL}/manufacturers/{slugify(m)}/">'
        f'<img class="logo-thumb" src="{get_logo_url(m)}" alt="{esc(m)} logo" loading="lazy" width="40" height="40">'
        f'<span><div class="m">{esc(m)}</div>'
        f'<div class="s">{len(by_mfr[m])} model{"s" if len(by_mfr[m])!=1 else ""}</div></span></a>'
        for m in sorted(by_mfr))
    crumb_items = [("Home", f"{BASE_URL}/"), ("Manufacturers", None)]
    body = (crumbs(crumb_items) +
            "<h1>Heat Pump Manufacturers</h1>"
            f'<p class="sub">{len(by_mfr)} brands in the database</p>'
            f'<div class="grid">{cards}</div>')
    return page(f"Heat Pump Manufacturers (A\u2013Z) | {SITE_NAME}",
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

    {"slug": "best-air-source-heat-pumps-by-cop",
     "title": "Best Air Source Heat Pumps by COP",
     "h1": "Best Air Source Heat Pumps by COP (A7/W35)",
     "desc": "Air source heat pumps with the highest COP at A7/W35 test conditions. Top {n} of {pool} ASHPs ranked.",
     "intro": "Ranked by COP at the standard A7/W35 test point (7\u00b0C outdoor air, 35\u00b0C flow). Only products tested at this condition are included, so figures are directly comparable.",
     "filter": lambda p: p.get("hp_type") == "ASHP" and p.get("cop") and _cond_is(p, "cop_cond", "A7/W35"),
     "sort": lambda p: -(p.get("cop") or 0), "metric": "cop", "metric_label": "COP (A7/W35)"},

    {"slug": "best-ground-source-heat-pumps",
     "title": "Best Ground Source Heat Pumps",
     "h1": "Best Ground Source Heat Pumps by COP",
     "desc": "The most efficient ground source heat pumps ranked by COP. Top {n} of {pool} GSHPs compared.",
     "intro": "Ground source heat pumps ranked by their published COP. Test conditions are shown for each product \u2014 B0/W35 (brine at 0\u00b0C, 35\u00b0C flow) is the most common benchmark.",
     "filter": lambda p: p.get("hp_type") == "GSHP" and p.get("cop"),
     "sort": lambda p: -(p.get("cop") or 0), "metric": "cop", "metric_label": "COP", "show_cond": True},

    {"slug": "best-water-source-heat-pumps",
     "title": "Best Water Source Heat Pumps",
     "h1": "Best Water Source Heat Pumps by COP",
     "desc": "The most efficient water source heat pumps ranked by COP. Top {n} of {pool} WSHPs compared.",
     "intro": "Water source heat pumps ranked by their published COP. Test conditions are shown for each product \u2014 W10/W35 (water at 10\u00b0C, 35\u00b0C flow) is the most common benchmark.",
     "filter": lambda p: p.get("hp_type") == "WSHP" and p.get("cop"),
     "sort": lambda p: -(p.get("cop") or 0), "metric": "cop", "metric_label": "COP", "show_cond": True},

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

    {"slug": "best-high-temperature-heat-pumps",
     "title": "Best High-Temperature Heat Pumps",
     "h1": "Best High-Temperature Heat Pumps (70\u00b0C+ flow)",
     "desc": "Heat pumps capable of 70\u00b0C+ flow temperatures \u2014 ideal radiator retrofits \u2014 ranked by SCOP. Top {n} of {pool} compared.",
     "intro": "High-temperature heat pumps reach 70\u00b0C+ flow, letting them replace a boiler without changing radiators. Ranked by SCOP among models with a maximum flow temperature of 70\u00b0C or higher.",
     "filter": lambda p: (p.get("flow_temp_max") or 0) >= 70 and p.get("scop"),
     "sort": lambda p: -(p.get("scop") or 0), "metric": "scop", "metric_label": "SCOP", "show_flow": True, "show_type": True},
]

BEST_TOP_N = 20

def render_best_page(cfg, ranked, pool_size, all_cfgs):
    url = f"{BASE_URL}/best/{cfg['slug']}/"
    n = len(ranked)
    desc = cfg["desc"].format(n=n, pool=pool_size)
    crumb_items = [("Home", f"{BASE_URL}/"), ("Best Of", f"{BASE_URL}/best/"), (cfg["title"], None)]
    show_cond = cfg.get("show_cond")
    show_flow = cfg.get("show_flow")
    metric = cfg["metric"]

    show_type = cfg.get("show_type")
    head_cells = "<th>#</th><th>Model</th>"
    if show_type: head_cells += "<th>Type</th>"
    head_cells += "<th>Capacity</th><th>" + cfg["metric_label"] + "</th>"
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
        if metric == "noise":
            return round(30 + 70 * (vmax - v) / (vmax - vmin))
        return round(30 + 70 * (v - vmin) / (vmax - vmin))

    rows = ""
    for i, p in enumerate(ranked, 1):
        mv = p.get(metric)
        mv_s = num(mv) if isinstance(mv, (int, float)) else esc(str(mv or ""))
        noise_s = f"{num(p['noise'])} dB(A)" if p.get("noise") is not None else ""
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

    # winner hero card
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

    others = "".join(
        f'<a class="card" href="{BASE_URL}/best/{c["slug"]}/"><span><div class="m">{c["title"]}</div></span></a>'
        for c in all_cfgs if c["slug"] != cfg["slug"])

    body = (crumbs(crumb_items) +
            f"<h1>{cfg['h1']}</h1>"
            f'<p class="sub">Top {n} of {pool_size} qualifying products \u00b7 updated {TODAY}</p>'
            f'<p>{cfg["intro"]}</p>'
            + winner_html +
            f'<div class="best-scroll"><table class="list best-table">{"<tr>" + head_cells + "</tr>"}{rows}</table></div>'
            f'<p style="margin-top:14px;font-size:13px;color:#5b6b6b">Rankings are generated automatically from '
            f'manufacturer-published data in the {SITE_NAME} and refresh as new products are added. '
            f'Figures come from different manufacturers\u2019 datasheets and certification documents; always '
            f'confirm specifications with the manufacturer. Products without the relevant published figure are excluded.</p>'
            f'<h2 class="sec">More rankings</h2><div class="grid">{others}</div>'
            f'<p style="margin-top:20px"><a class="cta" href="{BASE_URL}/">Open the interactive database &rarr;</a></p>')

    item_ld = {"@context": "https://schema.org", "@type": "ItemList",
               "name": cfg["title"], "numberOfItems": n,
               "itemListElement": [
                   {"@type": "ListItem", "position": i + 1,
                    "url": f"{BASE_URL}/products/{p['_slug']}/",
                    "name": f"{p.get('manufacturer','')} {p.get('model','')}"}
                   for i, p in enumerate(ranked)]}
    return page(f"{cfg['title']} ({TODAY[:4]}) | {SITE_NAME}", desc, url, body,
                [item_ld, breadcrumb_jsonld(crumb_items, url)], active="best", og_image=get_og_image())

def render_best_index(cfgs_with_counts):
    url = f"{BASE_URL}/best/"
    crumb_items = [("Home", f"{BASE_URL}/"), ("Best Of", None)]
    cards = ""
    for c, n, leader in cfgs_with_counts:
        lv = leader.get(c["metric"])
        lv_s = num(lv) if isinstance(lv, (int, float)) else str(lv or "")
        cards += (
            f'<a class="card has-logo" href="{BASE_URL}/best/{c["slug"]}/">'
            f'<img class="logo-thumb" src="{get_logo_url(leader.get("manufacturer",""))}" alt="" loading="lazy" width="40" height="40">'
            f'<span><div class="m">{c["title"]}</div>'
            f'<div class="s">Top {n} ranked</div>'
            f'<div class="hub-leader">\U0001F3C6 {esc(leader.get("manufacturer",""))} {esc(leader.get("model",""))} \u00b7 {c["metric_label"]} {lv_s}</div>'
            f'</span></a>')
    body = (crumbs(crumb_items) +
            "<h1>Best Heat Pumps \u2014 Rankings</h1>"
            f'<p class="sub">{len(cfgs_with_counts)} data-driven rankings \u00b7 updated {TODAY}</p>'
            f'<p>Every ranking below is generated automatically from the specifications in the {SITE_NAME}, '
            f'compared at matching test conditions wherever possible. They update as new products are added.</p>'
            f'<div class="grid">{cards}</div>'
            f'<p style="margin-top:20px"><a class="cta" href="{BASE_URL}/#compare">Compare selected products side-by-side &rarr;</a></p>')
    return page(f"Best Heat Pumps {TODAY[:4]} \u2014 Data-Driven Rankings | {SITE_NAME}",
                f"The best heat pumps ranked by real specification data: SCOP, COP, noise and flow temperature. "
                f"{len(cfgs_with_counts)} rankings updated automatically from the {SITE_NAME}.",
                url, body, [breadcrumb_jsonld(crumb_items, url)], active="best", og_image=get_og_image())

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
     "title": f"Heat Pump Refrigerants Compared \u2014 GWP, Safety & F-Gas Rules | {SITE_NAME}",
     "desc": ("Compare the refrigerants used in heat pumps: GWP, safety class, pros and cons, and the "
              "EU and UK F-Gas regulations. R290, R32, R410A, CO2, ammonia, HFOs and low-GWP blends.")},
    {"page_id": "page-cop-scop", "end_marker": "<!-- ═══ FLOW TEMPERATURE GUIDE ═══ -->",
     "dir": "cop-scop", "active": "cop-scop", "crumb": "Understanding COP & SCOP",
     "headline": "Understanding COP & SCOP",
     "title": f"Understanding Heat Pump COP & SCOP \u2014 Test Conditions Explained | {SITE_NAME}",
     "desc": ("What COP and SCOP mean for heat pumps, why test conditions like A7/W35 and W35 vs W55 "
              "matter, how seasonal SCOP differs from COP, and how to compare efficiency figures fairly.")},
    {"page_id": "page-flow-temp", "end_marker": "<!-- ═══ INSTALLATION COSTS GUIDE ═══ -->",
     "dir": "flow-temperature", "active": "flow-temp", "crumb": "Flow Temperature & Efficiency",
     "headline": "Flow Temperature & Efficiency",
     "title": f"Heat Pump Flow Temperature & Efficiency Explained | {SITE_NAME}",
     "desc": ("Why a lower flow temperature makes a heat pump more efficient, the trade-off with radiator "
              "and underfloor sizing, weather compensation, and how flow temperature relates to COP and SCOP.")},
    {"page_id": "page-install-costs", "end_marker": "<!-- ═══ FAQ ═══ -->",
     "dir": "installation-costs", "active": "install-costs", "crumb": "Installation Costs",
     "headline": "ASHP Installation Costs Explained",
     "title": f"Air Source Heat Pump Installation Costs UK 2026 | {SITE_NAME}",
     "desc": ("A breakdown of what a UK air source heat pump installation costs: the unit itself, hot water "
              "cylinder, controls, and radiator upgrades, plus typical totals before and after the Boiler "
              "Upgrade Scheme grant.")},
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

    # best-of ranking pages
    best_built = []
    for cfg in BEST_PAGES:
        pool = [p for p in products if cfg["filter"](p)]
        ranked = sorted(pool, key=cfg["sort"])
        ranked = _dedupe_variants(ranked, cfg["metric"])[:BEST_TOP_N]
        if len(ranked) < 5:
            continue
        write(os.path.join(ROOT, "best", cfg["slug"], "index.html"),
              render_best_page(cfg, ranked, len(pool), BEST_PAGES))
        url = f"{BASE_URL}/best/{cfg['slug']}/"
        urls.append(url)
        # order matters for a ranking page - a reshuffle is a real content change
        _lastmod_for(url, _lastmod_hash([(p.get("id"), product_hash_by_id[p.get("id")]) for p in ranked]))
        best_built.append((cfg, len(ranked), ranked[0]))
    write(os.path.join(ROOT, "best", "index.html"), render_best_index(best_built))
    url = f"{BASE_URL}/best/"
    urls.append(url)
    _lastmod_for(url, _lastmod_hash([(cfg["slug"], winner.get("id")) for cfg, _, winner in best_built]))

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

    # robots.txt
    write(os.path.join(ROOT, "robots.txt"),
          f"User-agent: *\nAllow: /\n\nSitemap: {BASE_URL}/sitemap.xml\n")

    print(f"Built {len(products)} product pages, {len(by_mfr)} manufacturer pages, "
          f"{len(type_pages)} category pages, {kg_count} knowledge pages, "
          f"{len(best_built)} best-of ranking pages.")
    print(f"sitemap.xml lists {len(urls)} URLs.")
    print(f"Wrote {redirect_count} redirect stub(s) for retired product slugs.")

if __name__ == "__main__":
    main()
