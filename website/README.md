# AwakeVC — Static Site

A clean, static HTML/CSS/JS rebuild of the AwakeVC Notion site, ready to host on GitHub Pages.

## Structure

```
website/
├── index.html       # Home page — hero + Meta-section grid
├── pages/           # 87 individual topic pages (one per Notion page)
├── css/styles.css   # All styling (Fraunces + Inter from Google Fonts)
├── js/main.js       # Tiny mobile-nav toggle
├── images/          # All images flattened with unique filenames
└── .nojekyll        # Tell GitHub Pages to serve files as-is
```

Everything is pre-rendered — no build step required to serve.

## Local preview

```bash
cd website
python3 -m http.server 8000
# then open http://localhost:8000/
```

## Deploying to GitHub Pages

### Option 1 — project-site (most common)

1. Commit this folder to a repo.
2. In **Settings → Pages**, set *Source* to the branch and folder:
   - *Branch*: `main`
   - *Folder*: `/website`
3. Save. Your site will appear at `https://<user>.github.io/<repo>/` in ~1 minute.

The `.nojekyll` file is already present so GitHub serves the files directly
without running Jekyll (which would otherwise swallow filenames containing
parentheses and underscores).

### Option 2 — top-level repo

If you want the site to live at `https://<user>.github.io/<repo>/` with no
`website/` subpath, either:

- Move the contents of `website/` to the repo root, **or**
- Set the Pages source to *GitHub Actions* and use a workflow that deploys
  `website/` as the artifact root.

### Option 3 — user/org site (apex)

To host at `https://<user>.github.io`, push the *contents* of `website/` to
the root of a repo named `<user>.github.io`.

## Rebuilding from the Notion export

The whole site is generated from `../notion-export/` by `../build.py`:

```bash
python3 build.py
```

This rewrites `website/` in place. Edit the source markdown (or the script)
and rerun. No dependencies — stdlib only.

## Custom domain

If pointing `awake.vc` at this site, add a `CNAME` file to this folder
containing the domain, and configure the DNS record with your registrar.
