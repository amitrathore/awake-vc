# AwakeVC — Static Site

A clean, static HTML/CSS/JS rebuild of the AwakeVC Notion site, hosted on GitHub Pages.

## Structure

```
docs/
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
cd docs
python3 -m http.server 8000
# then open http://localhost:8000/
```

## GitHub Pages

This folder is wired up for GitHub Pages. Settings → Pages → Source =
`main` branch, folder = `/docs`. The `.nojekyll` marker stops Jekyll from
mangling filenames that contain parentheses and underscores.

## Rebuilding from the Notion export

The whole site is generated from `../notion-export/` by `../build.py`:

```bash
python3 build.py
```

This rewrites `docs/` in place. Edit the source markdown (or the script)
and rerun. No dependencies — stdlib only.

## Custom domain

To point `awake.vc` at this site, add a `CNAME` file to this folder
containing the domain, and configure the DNS A/CNAME record with your registrar.
