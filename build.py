#!/usr/bin/env python3
"""
build.py — Heat Pumps Database static-page generator (SEO multi-page architecture).

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

import json, os, re, html, shutil, datetime

# ───────────────────────── Config ─────────────────────────
BASE_URL  = "https://www.heatpumpdatabase.com"   # no trailing slash
SITE_NAME = "Heat Pumps Database"
ROOT      = os.path.dirname(os.path.abspath(__file__))
DATA      = os.path.join(ROOT, "products.json")
TODAY     = datetime.date.today().isoformat()

GENERATED_DIRS = ["products", "manufacturers", "types"]

TYPE_LABEL = {"ASHP": "Air Source (ASHP)", "GSHP": "Ground Source (GSHP)",
              "WSHP": "Water Source (WSHP)"}

# ───────────────────────── Helpers ─────────────────────────
def slugify(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-") or "item"

def esc(s):
    return html.escape(str(s), quote=True)

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
    if p.get("cop") is not None:
        cc = f" at {esc(p['cop_cond'])}" if p.get("cop_cond") else ""
        add("COP", f"{num(p['cop'])}{cc}")
    if p.get("scop") is not None: add("SCOP", num(p["scop"]))
    if p.get("eer")  is not None: add("EER (cooling)", num(p["eer"]))
    add("Operating range (air)", range_str(p.get("op_temp_min"), p.get("op_temp_max"), "\u00b0C", " to "))
    add("Flow temperature", range_str(p.get("flow_temp_min"), p.get("flow_temp_max"), "\u00b0C"))
    if p.get("peak_elec") is not None: add("Power input", f"{num(p['peak_elec'])} kW")
    if any(p.get(k) is not None for k in ("height", "width", "depth")):
        h, w, d = p.get("height"), p.get("width"), p.get("depth")
        dims = " \u00d7 ".join(num(x) for x in (h, w, d) if x is not None)
        add("Dimensions (H\u00d7W\u00d7D)", f"{dims} mm")
    if p.get("weight") is not None: add("Weight", f"{num(p['weight'])} kg")
    if p.get("noise") is not None:
        ref = f" ({esc(p['noise_ref'])})" if p.get("noise_ref") else ""
        add("Sound power level", f"{num(p['noise'])} dB(A){ref}")
    add("Data added", esc(p.get("date_added")))
    add("Data source", esc(p.get("source")))
    return rows

# ───────────────────────── HTML shell ─────────────────────────
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#16302f;background:#f6f9f8;line-height:1.6;-webkit-font-smoothing:antialiased}
a{color:#0f8a80;text-decoration:none}a:hover{text-decoration:underline}
header.site{background:#0F2B2B;color:#fff;padding:14px 0}
header.site .wrap{display:flex;align-items:center;gap:10px}
header.site a{color:#fff;font-weight:700;font-size:18px;letter-spacing:-.02em}
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
table.list{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e2e8e7;border-radius:12px;overflow:hidden;font-size:14px}
table.list th,table.list td{padding:10px 14px;text-align:left;border-bottom:1px solid #eef2f1}
table.list th{background:#fafcfb;color:#42514f;font-weight:600;font-size:12.5px;text-transform:uppercase;letter-spacing:.03em}
table.list tr:last-child td{border-bottom:none}
table.list tr:hover td{background:#fafdfc}
.cta{display:inline-block;margin-top:8px;background:#0F2B2B;color:#fff;padding:11px 20px;border-radius:10px;font-weight:600;font-size:14px}
.cta:hover{background:#16413f;text-decoration:none}
footer.site{border-top:1px solid #e2e8e7;padding:26px 0;color:#7a8a88;font-size:13px;margin-top:30px}
footer.site a{color:#7a8a88}
.disclaimer{background:#fff7ed;border:1px solid #fbe3c4;color:#92651f;border-radius:10px;padding:12px 16px;font-size:13px;margin:20px 0}
@media(max-width:560px){table.spec th{width:48%}h1{font-size:23px}}
"""

def page(title, description, canonical, body, jsonld_list, og_type="website"):
    blocks = "\n".join(
        '<script type="application/ld+json">%s</script>' % json.dumps(j, ensure_ascii=False)
        for j in jsonld_list
    )
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
<meta name="twitter:card" content="summary">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style>
{blocks}
</head>
<body>
<header class="site"><div class="wrap"><a href="{BASE_URL}/">{SITE_NAME}</a></div></header>
<main><div class="wrap">
{body}
</div></main>
<footer class="site"><div class="wrap">
<p>{SITE_NAME} &middot; A searchable database of UK heat pumps. Always confirm specifications with the manufacturer before purchase.</p>
<p style="margin-top:6px"><a href="{BASE_URL}/">Search the full database</a> &middot; <a href="{BASE_URL}/manufacturers/">All manufacturers</a></p>
</div></footer>
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

def breadcrumb_jsonld(items):
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "name": label,
                 **({"item": href} if href else {})}
                for i, (label, href) in enumerate(items)]}

# ───────────────────────── Page renderers ─────────────────────────
def product_card(p):
    bits = [t for t in (p.get("hp_type"), cap_str(p),
            (f"SCOP {num(p['scop'])}" if p.get("scop") is not None else None)) if t]
    return (f'<a class="card" href="{BASE_URL}/products/{p["_slug"]}/">'
            f'<div class="m">{esc(p["model"])}</div>'
            f'<div class="s">{esc(" \u00b7 ".join(bits))}</div></a>')

def render_product(p, by_mfr, by_type):
    slug = p["_slug"]
    url  = f"{BASE_URL}/products/{slug}/"
    mfr, model = p.get("manufacturer", ""), p.get("model", "")
    mslug = slugify(mfr)

    # meta description from the most useful specs
    d_bits = [TYPE_LABEL.get(p.get("hp_type"), p.get("hp_type") or "").split(" (")[0] + " heat pump"]
    if cap_str(p): d_bits.append(cap_str(p))
    if p.get("cop") is not None: d_bits.append(f"COP {num(p['cop'])}")
    if p.get("scop") is not None: d_bits.append(f"SCOP {num(p['scop'])}")
    if p.get("refrigerant"): d_bits.append(f"{p['refrigerant']} refrigerant")
    desc = f"{mfr} {model}: " + ", ".join([b for b in d_bits if b]).rstrip(", ") + \
           ". Full specifications and data."

    rows = "".join(f"<tr><th>{l}</th><td>{v}</td></tr>" for l, v in spec_rows(p))
    badges = "".join(f'<span class="badge">{esc(b)}</span>' for b in [
        TYPE_LABEL.get(p.get("hp_type"), p.get("hp_type")),
        p.get("type"), p.get("refrigerant"),
        (cap_str(p) if cap_str(p) else None)] if b)

    extra = ""
    if p.get("description"): extra += f"<p>{esc(p['description'])}</p>"
    if p.get("notes"):       extra += f"<p>{esc(p['notes'])}</p>"
    notes_html = f'<div class="notes"><h2>Notes</h2>{extra}</div>' if extra else ""

    mfr_link = ""
    if p.get("product_url"):
        mfr_link = (f'<p style="margin-top:16px"><a class="cta" href="{esc(p["product_url"])}" '
                    f'rel="nofollow" target="_blank">View manufacturer page &rarr;</a></p>')

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

    # Product JSON-LD
    props = []
    for l, v in spec_rows(p):
        if l not in ("Manufacturer", "Model", "Data source", "Data added"):
            props.append({"@type": "PropertyValue", "name": l,
                          "value": re.sub("<[^>]+>", "", str(v))})
    product_ld = {"@context": "https://schema.org", "@type": "Product",
                  "name": f"{mfr} {model}".strip(),
                  "url": url,
                  "category": TYPE_LABEL.get(p.get("hp_type"), "Heat pump"),
                  "brand": {"@type": "Brand", "name": mfr},
                  "additionalProperty": props}
    if p.get("product_code"): product_ld["mpn"] = p["product_code"]
    if extra: product_ld["description"] = re.sub("<[^>]+>", " ", extra).strip()

    body = (crumbs(crumb_items) +
            f"<h1>{esc(mfr)} {esc(model)}</h1>"
            f'<p class="sub">Specifications and technical data</p>'
            f'<div class="badges">{badges}</div>'
            f'<table class="spec">{rows}</table>'
            f'{mfr_link}{notes_html}'
            f'<div class="disclaimer">Data is compiled from manufacturer sources and may contain errors or '
            f'gaps. Always confirm specifications with the manufacturer before making decisions.</div>'
            f'{rel}'
            f'<h2 class="sec">Compare with other products</h2>'
            f'<p><a class="cta" href="{BASE_URL}/">Open the interactive database &rarr;</a></p>')

    title = f"{mfr} {model} \u2014 Specifications | {SITE_NAME}"
    return page(title, desc, url, body,
                [product_ld, breadcrumb_jsonld(crumb_items)], og_type="product")

def list_table(products):
    head = ("<tr><th>Model</th><th>Type</th><th>Capacity</th><th>COP</th>"
            "<th>SCOP</th><th>Refrigerant</th></tr>")
    rows = ""
    for p in products:
        rows += (f'<tr><td><a href="{BASE_URL}/products/{p["_slug"]}/">{esc(p["model"])}</a></td>'
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
    body = (crumbs(crumb_items) +
            f"<h1>{esc(mfr)} Heat Pumps</h1>"
            f'<p class="sub">{n} model{"s" if n != 1 else ""} in the database</p>' +
            list_table(sorted(products, key=lambda x: (x.get("hp_type") or "", x.get("cap_max") or 0))) +
            f'<p style="margin-top:20px"><a class="cta" href="{BASE_URL}/">Search the full database &rarr;</a></p>')
    item_ld = {"@context": "https://schema.org", "@type": "ItemList",
               "name": f"{mfr} heat pumps",
               "itemListElement": [
                   {"@type": "ListItem", "position": i + 1,
                    "url": f"{BASE_URL}/products/{p['_slug']}/",
                    "name": f"{mfr} {p['model']}"}
                   for i, p in enumerate(products)]}
    title = f"{mfr} Heat Pumps \u2014 Models & Specifications | {SITE_NAME}"
    return page(title, desc, url, body, [item_ld, breadcrumb_jsonld(crumb_items)])

def render_manufacturers_index(by_mfr):
    url = f"{BASE_URL}/manufacturers/"
    cards = "".join(
        f'<a class="card" href="{BASE_URL}/manufacturers/{slugify(m)}/">'
        f'<div class="m">{esc(m)}</div>'
        f'<div class="s">{len(by_mfr[m])} model{"s" if len(by_mfr[m])!=1 else ""}</div></a>'
        for m in sorted(by_mfr))
    crumb_items = [("Home", f"{BASE_URL}/"), ("Manufacturers", None)]
    body = (crumbs(crumb_items) +
            "<h1>Heat Pump Manufacturers</h1>"
            f'<p class="sub">{len(by_mfr)} brands in the database</p>'
            f'<div class="grid">{cards}</div>')
    return page(f"Heat Pump Manufacturers (A\u2013Z) | {SITE_NAME}",
                f"Browse heat pumps by manufacturer. {len(by_mfr)} brands with full specifications, "
                f"COP and SCOP data in the {SITE_NAME}.", url, body,
                [breadcrumb_jsonld(crumb_items)])

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
    crumb_items = [("Home", f"{BASE_URL}/"), ("Categories", None), (heading, None)]
    body = (crumbs([("Home", f"{BASE_URL}/"), (heading, None)]) +
            f"<h1>{esc(heading)}</h1>"
            f'<p class="sub">{len(products)} products &middot; {len(by_m)} manufacturers</p>'
            f'{sections}'
            f'<p style="margin-top:20px"><a class="cta" href="{BASE_URL}/">Open the interactive database &rarr;</a></p>')
    return page(f"{heading} | {SITE_NAME}", desc, url, body, [breadcrumb_jsonld(crumb_items)])

# ───────────────────────── Build ─────────────────────────
def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

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

    urls = [f"{BASE_URL}/"]

    # product pages
    for p in products:
        write(os.path.join(ROOT, "products", p["_slug"], "index.html"),
              render_product(p, by_mfr, by_type))
        urls.append(f"{BASE_URL}/products/{p['_slug']}/")

    # manufacturer pages + index
    for m, ps in by_mfr.items():
        write(os.path.join(ROOT, "manufacturers", slugify(m), "index.html"),
              render_manufacturer(m, ps))
        urls.append(f"{BASE_URL}/manufacturers/{slugify(m)}/")
    write(os.path.join(ROOT, "manufacturers", "index.html"),
          render_manufacturers_index(by_mfr))
    urls.append(f"{BASE_URL}/manufacturers/")

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

    for slug, heading, desc, ps in type_pages:
        write(os.path.join(ROOT, "types", slug, "index.html"),
              render_type(slug, heading, desc, ps))
        urls.append(f"{BASE_URL}/types/{slug}/")

    # sitemap.xml
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        sm.append(f"  <url><loc>{u}</loc><lastmod>{TODAY}</lastmod></url>")
    sm.append("</urlset>")
    write(os.path.join(ROOT, "sitemap.xml"), "\n".join(sm))

    # robots.txt
    write(os.path.join(ROOT, "robots.txt"),
          f"User-agent: *\nAllow: /\n\nSitemap: {BASE_URL}/sitemap.xml\n")

    print(f"Built {len(products)} product pages, {len(by_mfr)} manufacturer pages, "
          f"{len(type_pages)} category pages.")
    print(f"sitemap.xml lists {len(urls)} URLs.")

if __name__ == "__main__":
    main()
