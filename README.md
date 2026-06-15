# Heat Pumps Database — site repository

This repository holds both the interactive database **and** the generated SEO pages.

```
index.html              ← the interactive app (Browse / Compare / Visualise / Admin)
products.json           ← the product data the SEO pages are built from
build.py                ← the generator (run by Claude; you don't need to run it)
sitemap.xml             ← every URL, regenerated on each build
robots.txt              ← points search engines at the sitemap
products/<slug>/        ← 1,411 individual product pages  (generated)
manufacturers/<slug>/   ← 40 manufacturer pages + an A–Z index  (generated)
types/<slug>/           ← category pages: source type, refrigerant, application  (generated)
.nojekyll               ← tells GitHub Pages to serve folders as-is
CNAME                   ← your custom domain (keep your existing one)
```

Every product, manufacturer and category now has its **own URL** with a unique title,
meta description, `Product` / `BreadcrumbList` JSON-LD, and internal links. That is what
lets pages like *"Dimplex System H 8kW specifications"* rank in Google, instead of the
whole site competing as a single page.

---

## How updates work now (Option 1)

You are on **Option 1: Claude builds, you commit.** Nothing about *how you get changes*
has changed — you still ask me to add a manufacturer or import data, and I hand back the
finished files. The only difference is you now commit a **folder of files** instead of a
single `index.html`.

The flow for any data change:

1. You ask me to add/edit products (a deep-dive, an Excel import, a correction).
2. I update `products.json` **and** the app's data, run `build.py`, and give you back the
   complete updated repository.
3. You commit the whole thing to GitHub. GitHub Pages publishes it.

**Do not hand-edit the generated pages** under `products/`, `manufacturers/` or `types/` —
the next build overwrites them. Data lives in `products.json` (and the app's built-in copy),
which I keep in sync for you.

### Committing a folder to GitHub

Because a rebuild touches hundreds of files, the easiest way to commit is **GitHub Desktop**
(free): open the repo, it shows every changed file, type a summary, click *Commit* then *Push*.
One click publishes everything.

The browser upload at github.com also works — you can drag the whole folder onto the repo —
but with 1,400+ files Desktop is far smoother.

### First-time setup (only if not already done)

1. **GitHub Pages:** repo *Settings → Pages → Deploy from a branch → main / root.*
2. **Keep your `CNAME` file** with your domain (e.g. `www.heatpumpdatabase.com`) so the custom
   domain survives each commit.
3. **Submit the sitemap** in Google Search Console: *Sitemaps → add* `sitemap.xml`. Do this once;
   Google re-reads it automatically after that. Re-indexing of new pages takes roughly 2–4 weeks,
   and SEO results build over 2–4 months.

---

## Moving to Option 2 later (automation)

When you're comfortable, Option 2 makes publishing self-serve: you commit only the small
`products.json`, and a **GitHub Action** runs `build.py` in the cloud and publishes the result —
no more committing a big folder. The build script is identical; Option 2 just adds one workflow
file and a Pages setting. Ask me when you want it and I'll wire it up. Until then, Option 1 keeps
every moving part on my side.

---

## Notes

- Internal links use the production domain set at the top of `build.py`
  (`BASE_URL = "https://www.heatpumpdatabase.com"`). Change that one line if your domain changes.
- The interactive `index.html` is unchanged and still works on its own (even opened as a local
  file). It carries its own copy of the data so it never depends on `products.json` loading.
- `build.py` needs only Python 3 (standard library) — no packages to install.
