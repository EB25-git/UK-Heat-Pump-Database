# UK Heat Pumps Database

A comprehensive, searchable database of residential and commercial heat pumps available on the UK market. Built as a single-page static site with client-side data management.

## Repository contents

```
├── index.html      ← The entire website (single file)
├── CNAME           ← Custom domain for GitHub Pages
├── .nojekyll       ← Tells GitHub Pages to skip Jekyll processing
├── robots.txt      ← Search engine crawling rules
├── 404.html        ← Custom 404 error page
└── README.md       ← This file
```

---

## Deployment: GitHub → GitHub Pages → GoDaddy domain

### Step 1 — Create the GitHub repository

1. Go to [github.com](https://github.com) and sign in (or create a free account).
2. Click the **+** button (top-right) → **New repository**.
3. Name it something like `uk-heat-pumps-db` (or any name you prefer).
4. Set visibility to **Public** (required for free GitHub Pages).
5. **Do not** tick "Add a README file" — we already have one.
6. Click **Create repository**.

### Step 2 — Upload the site files

**Option A — Upload via the GitHub web interface (easiest):**

1. On your new empty repository page, click **"uploading an existing file"**.
2. Drag all the files from this folder onto the upload area:
   - `index.html`
   - `CNAME`
   - `.nojekyll`
   - `robots.txt`
   - `404.html`
   - `README.md`
3. Type a commit message like "Initial site upload".
4. Click **Commit changes**.

**Option B — Upload via Git command line:**

```bash
cd /path/to/this/folder
git init
git add .
git commit -m "Initial site upload"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/uk-heat-pumps-db.git
git push -u origin main
```

### Step 3 — Enable GitHub Pages

1. In your GitHub repository, go to **Settings** → **Pages** (in the left sidebar).
2. Under **Source**, select **Deploy from a branch**.
3. Under **Branch**, select **main** and **/ (root)**.
4. Click **Save**.
5. Wait 1–2 minutes. GitHub will show a green banner with your site URL, which will be something like `https://your-username.github.io/uk-heat-pumps-db/`.
6. Visit that URL to confirm the site is live.

### Step 4 — Connect your GoDaddy domain

#### 4a. Edit the CNAME file

Before configuring DNS, update the `CNAME` file in your repository to contain your actual domain:

1. In GitHub, click on the `CNAME` file → pencil icon (edit).
2. Replace `www.yourdomain.co.uk` with your actual domain, e.g. `www.ukheatpumps.co.uk`.
3. Commit the change.

#### 4b. Configure DNS in GoDaddy

1. Log in to [GoDaddy](https://www.godaddy.com) → **My Products** → find your domain → **DNS**.
2. **Delete** any existing A records or CNAME records for `@` and `www` that you don't need.
3. **Add four A records** (these point the root domain to GitHub Pages):

   | Type | Name | Value             | TTL    |
   |------|------|-------------------|--------|
   | A    | @    | 185.199.108.153   | 600    |
   | A    | @    | 185.199.109.153   | 600    |
   | A    | @    | 185.199.110.153   | 600    |
   | A    | @    | 185.199.111.153   | 600    |

4. **Add a CNAME record** (this points `www` to GitHub Pages):

   | Type  | Name | Value                                        | TTL    |
   |-------|------|----------------------------------------------|--------|
   | CNAME | www  | `your-username.github.io` | 600    |

   Replace `your-username` with your actual GitHub username.

5. Click **Save**.

#### 4c. Enable HTTPS in GitHub Pages

1. Wait 15–30 minutes for DNS to propagate (can take up to 48 hours in rare cases).
2. Go back to GitHub → **Settings** → **Pages**.
3. Under **Custom domain**, type your domain (e.g. `www.ukheatpumps.co.uk`) and click **Save**.
4. Once the DNS check passes, tick **Enforce HTTPS**.

#### 4d. Verify

- Visit `https://www.yourdomain.co.uk` — the site should load.
- Visit `https://yourdomain.co.uk` (without www) — it should redirect to the www version.

---

## Updating the site

### Updating product data or content

Since the admin panel saves changes to **localStorage** (browser-only), any edits you make as admin only exist in your own browser. To update the live site's default data for all visitors:

1. Make your changes in the admin panel.
2. Use **Admin → Settings → Export all records (CSV)** to download the current database.
3. Edit `index.html` locally — update the `SEED` array in the `<script>` section with your new data.
4. Bump the localStorage version key (search for `hpdb_v5` and change to `hpdb_v6`, etc.) so returning visitors pick up the new defaults.
5. Commit and push to GitHub. GitHub Pages will redeploy automatically within ~1 minute.

### Updating Guide or Contact page content

The same principle applies — edit the `DEFAULT_GUIDE` and `DEFAULT_CONTACT` objects in the `<script>` section of `index.html`, then push to GitHub.

### Quick edits via GitHub

For small changes, you can edit `index.html` directly on GitHub:

1. Click on `index.html` in your repository.
2. Click the pencil icon (edit).
3. Make your changes.
4. Click **Commit changes**. The site redeploys automatically.

---

## Update the meta tags

Before going live, search and replace these placeholders in `index.html`:

| Find                          | Replace with                     |
|-------------------------------|----------------------------------|
| `www.yourdomain.co.uk`        | Your actual domain               |
| `https://www.yourdomain.co.uk/` | Your actual full URL           |

Also update these in `robots.txt` and `CNAME`.

---

## Architecture notes

### How data works

- **SEED data** (hardcoded in `index.html`) is the baseline dataset all visitors see on first load.
- **localStorage** stores any admin changes, click tracking, and CMS content edits — but only in the current browser.
- When a visitor first loads the site, they get the SEED data. If you've previously visited and the localStorage version matches, it uses the cached version.
- Bumping the version key (e.g. `hpdb_v5` → `hpdb_v6`) forces all returning visitors to reload from the updated SEED.

### Limitations of the static approach

- **No shared database** — each visitor sees the SEED defaults; admin edits are local only.
- **Click tracking** — records clicks in the current browser only, not across all visitors.
- **No login security** — the admin password is stored client-side and can be viewed in source. This is a UI gate, not real security.

### Future upgrades (if needed)

If you outgrow the static approach, the natural next step would be:

1. **Add a lightweight backend** (e.g. Supabase, Firebase, or a simple Node/Express API) to store products in a real database.
2. **Add analytics** — embed [Plausible](https://plausible.io) or [Fathom](https://usefathom.com) for privacy-friendly visitor tracking, or Google Analytics.
3. **Server-side admin auth** — replace the client-side password with proper authentication.

None of these require rebuilding the frontend — the existing UI can be adapted to fetch from an API instead of localStorage.

---

## Licence

This project and its data are provided for informational purposes. Product specifications are sourced from manufacturer datasheets and may change without notice. Always verify with the manufacturer before making purchasing decisions.
