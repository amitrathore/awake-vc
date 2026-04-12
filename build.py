#!/usr/bin/env python3
"""Build the AwakeVC static site from the Notion export.

Reads notion-export/ and emits a clean multi-page static site into website/.
No external dependencies — stdlib only, so it runs anywhere Python 3 is present.
"""
from __future__ import annotations

import csv
import html
import json
import re
import shutil
import unicodedata
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).parent
SRC = ROOT / "notion-export"
DST = ROOT / "docs"
COVERS_MANIFEST = ROOT / "covers_manifest.json"
SRC_ROOT_MD = SRC / "AwakeVC 3210c0891eaa43a485ab74a5d50c56a0.md"
SRC_PAGES = SRC / "AwakeVC"

# ---------------------------------------------------------------------------
# Site structure — the 10 "Meta" groupings from the Notion index, plus their
# child pages. Titles are the display labels; slugs are derived below.
# ---------------------------------------------------------------------------

META_SECTIONS = [
    ("Meta Reality",        "The philosophical foundation: protocols, networks, identity, value.",
     ["Protocols", "Network", "Identity", "Value"]),
    ("Meta Main Street",    "Business, money, markets, and commerce facilitation.",
     ["Business", "Money", "Market", "ComFac"]),
    ("Meta Wall Street",    "Banking, capital, and exchange infrastructure.",
     ["BankFac", "CapFac", "Exchange"]),
    ("Meta Basis",          "The building blocks: Lisp, HTTP, connections, cosellers, and the new retail.",
     ["Lisp", "HTTP", "Connections", "SaleRank", "Cosellers", "Retail 3 0",
      "Metaverse", "Avatars", "Web2 5", "Games", "Ecosystems"]),
    ("Meta Internet",       "Blockchain, crypto, Web3, DeFi, DAOs, and the MetaWeb.",
     ["Blockchain", "Crypto", "NFTs", "Web3", "MetaWeb", "Attribution",
      "Communities", "DeFi", "DAOs"]),
    ("Meta Silicon Valley", "Platforms, ventures, acceleration, and syndication.",
     ["Platform", "Venture", "Acceleration", "Syndication"]),
    ("Meta Vision",         "Inspiration, spirituality, energy, entrepreneurship, and nature.",
     ["Inspiration", "Spirituality", "Energy", "Entrepreneurship", "Nature"]),
    ("Meta Awake",          "Private equity, WokeVC, beyond all clouds, blog, team.",
     ["PE", "TheWokeVC", "Beyond All Clouds", "Blog", "Team"]),
    ("Meta Ventures",       "a64z, She, Creator, Acquihire, and Careers.",
     ["a64z", "She", "Creator", "Acquihire", "Careers"]),
    ("Meta Launch",         "Incorporation, dogfooding, dragoneering, the Studio, and Disrupt.",
     ["Inc", "Dogfooding", "Dragoneering", "Studio", "Disrupt"]),
]

HASH_RE = re.compile(r"\s+[0-9a-f]{32}(?:\.md)?$")
HASH_IN_PATH_RE = re.compile(r"\s+[0-9a-f]{32}")

FOOTER_HTML = """
<footer class="site-footer">
  <div class="wrap">
    <div class="footer-brand">
      <a href="{home}" class="brand-mark">Awake<span class="brand-dot">.</span>vc</a>
      <p class="footer-tag">Because Protocols Are Eating Venture.</p>
    </div>
    <div class="footer-meta">
      <p>San Mateo, CA &middot; <a href="tel:+16509187312">+1&nbsp;650&nbsp;918&nbsp;7312</a> &middot; <a href="mailto:info@awake.vc">info@awake.vc</a></p>
    </div>
  </div>
</footer>
"""

NAV_ITEMS = [
    ("About",     "about"),
    ("Protocols", "protocols"),
    ("Team",      "team"),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def strip_hash(stem: str) -> str:
    """Remove Notion's 32-hex-digit suffix from a filename or title."""
    return HASH_RE.sub("", stem).strip()


def slugify(text: str) -> str:
    text = strip_hash(text)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "page"


def title_from_md(md_text: str, fallback: str) -> str:
    for line in md_text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


# ---------------------------------------------------------------------------
# Page registry — walk the export, assign slugs, build a filename → slug map.
# ---------------------------------------------------------------------------

class Page:
    def __init__(self, src_path: Path, slug: str, title: str):
        self.src_path = src_path
        self.slug = slug
        self.title = title
        self.html_body = ""
        self.parent_slug: str | None = None


def collect_pages() -> tuple[dict[str, Page], dict[str, str]]:
    """Walk the export, assign unique slugs, return (pages_by_slug, md_name_to_slug).

    md_name_to_slug keys are bare filenames like 'Protocols 2d82....md' so we
    can rewrite Notion's URL-encoded internal links.
    """
    pages: dict[str, Page] = {}
    name_to_slug: dict[str, str] = {}
    used_slugs: set[str] = set()

    md_files = sorted(SRC_PAGES.rglob("*.md"))
    for path in md_files:
        name = path.name
        raw_title = strip_hash(path.stem)
        slug = slugify(raw_title)
        # Disambiguate — shouldn't happen with this export but be defensive.
        base = slug
        i = 2
        while slug in used_slugs:
            slug = f"{base}-{i}"
            i += 1
        used_slugs.add(slug)

        text = path.read_text(encoding="utf-8")
        title = title_from_md(text, raw_title)
        pages[slug] = Page(path, slug, title)
        name_to_slug[name] = slug

    return pages, name_to_slug


# ---------------------------------------------------------------------------
# Image handling — flatten all images into website/images/ with unique names.
# ---------------------------------------------------------------------------

def collect_and_copy_images() -> dict[str, str]:
    """Return a map from the *raw href* found in markdown → the new image URL
    relative to a page in website/pages/.

    We key by the basename and by the last-two-segments so that page-relative
    lookups ('Folder/file.jpg') and deeper lookups ('Foo/Bar/file.jpg') both
    resolve. In practice, each basename is already unique in this export.
    """
    images_dst = DST / "images"
    images_dst.mkdir(parents=True, exist_ok=True)

    href_map: dict[str, str] = {}
    for src_img in SRC.rglob("*"):
        if not src_img.is_file():
            continue
        if src_img.suffix.lower() not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}:
            continue

        clean_name = re.sub(r"\s+", "_", src_img.name)
        dst = images_dst / clean_name
        # If name collision, prefix with parent folder.
        if dst.exists() and not _same_file(src_img, dst):
            parent = re.sub(r"\s+", "_", strip_hash(src_img.parent.name))
            dst = images_dst / f"{parent}_{clean_name}"
        shutil.copy2(src_img, dst)

        # Keys we'll look up against (decoded forms of markdown hrefs).
        rel_to_src = src_img.relative_to(SRC).as_posix()
        href_map[rel_to_src] = dst.name
        href_map[src_img.name] = dst.name
        # Also register path-relative forms used in sub-page markdown.
        parts = src_img.parts
        for n in range(2, min(5, len(parts)) + 1):
            href_map["/".join(parts[-n:])] = dst.name
    return href_map


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_size == b.stat().st_size
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Minimal markdown parser. Handles headings, paragraphs, hr, images, links,
# bold/italic, inline code, and Notion <aside> callouts. No lists/tables/code
# fences — confirmed absent from this export.
# ---------------------------------------------------------------------------

FILENAMEY_RE = re.compile(r"^[\w\-\s.()\[\]]+\.(jpg|jpeg|png|gif|webp|svg)$", re.IGNORECASE)
PLACEHOLDER_ALT = {"untitled", "image", "unnamed"}
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
# Allow one level of balanced parens in URLs so filenames like "Awake_A64Z_(2).jpg" parse.
_URL = r"((?:[^()\s]|\([^)]*\))+)"
IMG_RE = re.compile(r"!\[([^\]]*)\]\(" + _URL + r"\)")
LINK_RE = re.compile(r"\[([^\]]*)\]\(" + _URL + r"\)")
BOLDITAL_RE = re.compile(r"\*\*\*(.+?)\*\*\*")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
ITAL_RE = re.compile(r"(?<!\*)\*([^\*\n]+?)\*(?!\*)")
CODE_RE = re.compile(r"`([^`]+)`")
FOOTER_MARKER = "Because Protocols Are Eating Venture"


_FOOTER_LINE_PATTERNS = [
    re.compile(r"!\[network-3139213_1920\.jpg\]"),
    re.compile(r"\[\*AwakeVC\*\]\(https://awake\.vc\)"),
    re.compile(r"^\s*3 E 3rd Ave"),
    re.compile(r"\+1\s*415\s*800\s*4888"),
    re.compile(r"\+14158004888"),
    re.compile(r"Because Protocols Are Eating Venture"),
    re.compile(r"Shoptype.*registered trademarks"),
    re.compile(r"Powered by \[Guruji\]"),
]


def strip_notion_footer(md_text: str) -> str:
    """Drop Notion's repeated page footer (network image, address, tagline).
    We target the specific lines so that non-footer content placed *after*
    the footer in the Notion export (e.g. the Amit-Bio subpage link on the
    Team page) survives."""
    lines = md_text.splitlines()
    kept: list[str] = []
    for line in lines:
        if any(p.search(line) for p in _FOOTER_LINE_PATTERNS):
            continue
        kept.append(line)
    # Collapse runs of blank lines and `---` that the strip may have left behind.
    out: list[str] = []
    prev_blank = False
    for line in kept:
        s = line.strip()
        if s == "":
            if prev_blank:
                continue
            prev_blank = True
            out.append("")
        else:
            prev_blank = False
            out.append(line)
    # Drop trailing stray `---` followed by only blanks.
    while out and (out[-1].strip() == "" or out[-1].strip() == "---"):
        out.pop()
    return "\n".join(out) + "\n"


def render_md(md_text: str, name_to_slug: dict[str, str],
              image_map: dict[str, str], home_rel: str) -> str:
    md_text = strip_notion_footer(md_text)
    lines = md_text.splitlines()
    out: list[str] = []
    i = 0
    in_aside = False
    aside_buf: list[str] = []
    paragraph: list[str] = []
    saw_first_heading = False  # suppress the page's own H1 — we render it in the template.

    def flush_paragraph():
        if paragraph:
            text = " ".join(paragraph).strip()
            if text:
                out.append(f"<p>{render_inline(text, name_to_slug, image_map, home_rel)}</p>")
            paragraph.clear()

    def flush_aside():
        nonlocal aside_buf
        if aside_buf:
            # Render aside contents as its own mini-document (paragraphs only).
            inner_lines = aside_buf
            aside_buf = []
            paras: list[str] = []
            cur: list[str] = []
            for ln in inner_lines:
                if not ln.strip():
                    if cur:
                        paras.append(" ".join(cur).strip())
                        cur = []
                else:
                    cur.append(ln.strip())
            if cur:
                paras.append(" ".join(cur).strip())
            rendered = "".join(
                f"<p>{render_inline(p, name_to_slug, image_map, home_rel)}</p>"
                for p in paras if p
            )
            out.append(f'<aside class="callout">{rendered}</aside>')

    while i < len(lines):
        line = lines[i]

        if line.strip() == "<aside>":
            flush_paragraph()
            in_aside = True
            aside_buf = []
            i += 1
            continue
        if line.strip() == "</aside>":
            in_aside = False
            flush_aside()
            i += 1
            continue
        if in_aside:
            aside_buf.append(line)
            i += 1
            continue

        if line.strip() == "---":
            flush_paragraph()
            out.append("<hr>")
            i += 1
            continue

        # Skip standalone lines that are just a link to a .csv (Notion
        # renders child-database links this way; we don't ship the CSVs).
        csv_only = LINK_RE.fullmatch(line.strip())
        if csv_only and unquote(csv_only.group(2)).lower().endswith(".csv"):
            i += 1
            continue

        m = HEADING_RE.match(line)
        if m:
            flush_paragraph()
            level = len(m.group(1))
            content = m.group(2).strip()
            if level == 1 and not saw_first_heading:
                # We render the main title in the template — drop it here.
                saw_first_heading = True
                i += 1
                continue
            # Demote any subsequent top-level heading: an article should have
            # one <h1>, so repeated `# Section` lines become section headers.
            if level == 1:
                level = 2
            rendered = render_inline(content, name_to_slug, image_map, home_rel)
            out.append(f"<h{level}>{rendered}</h{level}>")
            i += 1
            continue

        # Standalone image line becomes a figure.
        img_match = IMG_RE.fullmatch(line.strip())
        if img_match:
            flush_paragraph()
            alt = img_match.group(1)
            href = img_match.group(2)
            img_url = resolve_image(href, image_map)
            if img_url:
                alt_plain = strip_md(alt).strip()
                show_caption = (
                    bool(alt_plain)
                    and not FILENAMEY_RE.match(alt_plain)
                    and alt_plain.lower() not in PLACEHOLDER_ALT
                )
                caption = render_inline(alt, name_to_slug, image_map, home_rel) if show_caption else ""
                fig = f'<figure><img src="{img_url}" alt="{html.escape(alt_plain)}">'
                if caption:
                    fig += f"<figcaption>{caption}</figcaption>"
                fig += "</figure>"
                out.append(fig)
                # Skip the immediately-following paragraph if it duplicates the caption
                # (Notion often writes the caption twice: once as alt, once below).
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and show_caption and lines[j].strip() == alt.strip():
                    i = j + 1
                    continue
            i += 1
            continue

        if not line.strip():
            flush_paragraph()
            i += 1
            continue

        paragraph.append(line.strip())
        i += 1

    flush_paragraph()
    return "\n".join(out)


def strip_md(text: str) -> str:
    """Rough plain-text extractor for alt attributes."""
    text = IMG_RE.sub(lambda m: m.group(1), text)
    text = LINK_RE.sub(lambda m: m.group(1), text)
    text = BOLD_RE.sub(lambda m: m.group(1), text)
    text = ITAL_RE.sub(lambda m: m.group(1), text)
    text = CODE_RE.sub(lambda m: m.group(1), text)
    return text


def render_inline(text: str, name_to_slug: dict[str, str],
                  image_map: dict[str, str], home_rel: str) -> str:
    # Images first (they contain a bang prefix that would otherwise be eaten).
    def img_sub(m: re.Match) -> str:
        alt = m.group(1)
        href = m.group(2)
        url = resolve_image(href, image_map)
        if not url:
            return ""
        return f'<img src="{url}" alt="{html.escape(strip_md(alt))}">'
    text = IMG_RE.sub(img_sub, text)

    def link_sub(m: re.Match) -> str:
        label_md = m.group(1)
        href = m.group(2)
        decoded = unquote(href)
        # Drop empty-label links (Notion's "bookmark embed" syntax).
        if not label_md.strip():
            return ""
        # Drop links to files we don't ship (CSVs, etc.) — render label as plain text.
        if decoded.lower().endswith(".csv"):
            return render_inline(label_md, name_to_slug, image_map, home_rel)
        label = render_inline(label_md, name_to_slug, image_map, home_rel)
        resolved = resolve_link(href, name_to_slug)
        attrs = ""
        if resolved.startswith("http://") or resolved.startswith("https://"):
            attrs = ' target="_blank" rel="noopener"'
        return f'<a href="{resolved}"{attrs}>{label}</a>'
    text = LINK_RE.sub(link_sub, text)

    text = BOLDITAL_RE.sub(lambda m: f"<strong><em>{m.group(1)}</em></strong>", text)
    text = BOLD_RE.sub(lambda m: f"<strong>{m.group(1)}</strong>", text)
    text = ITAL_RE.sub(lambda m: f"<em>{m.group(1)}</em>", text)
    text = CODE_RE.sub(lambda m: f"<code>{m.group(1)}</code>", text)
    return text


def resolve_link(href: str, name_to_slug: dict[str, str]) -> str:
    decoded = unquote(href)
    # Notion internal — ends in .md
    if decoded.endswith(".md"):
        base = Path(decoded).name
        if base in name_to_slug:
            return f"{name_to_slug[base]}.html"
        # Fallback: slugify the title portion.
        return f"{slugify(Path(decoded).stem)}.html"
    if decoded.startswith("mailto:") or decoded.startswith("tel:"):
        return decoded
    if decoded.startswith("#"):
        return decoded
    if not re.match(r"^[a-z]+://", decoded):
        # Bare domain like 'BookOfAgents.com'
        if "." in decoded and " " not in decoded:
            return f"https://{decoded}"
    return decoded


def resolve_image(href: str, image_map: dict[str, str]) -> str:
    decoded = unquote(href)
    if decoded.startswith("http"):
        return decoded
    # Try full path first, then progressively shorter suffixes, then basename.
    candidates = [decoded, Path(decoded).name]
    parts = Path(decoded).parts
    for n in range(2, min(5, len(parts)) + 1):
        candidates.append("/".join(parts[-n:]))
    for key in candidates:
        if key in image_map:
            return f"../images/{image_map[key]}"
    return ""


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

BASE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600;9..144,700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{css_rel}">
</head>
<body class="{body_class}">
  <header class="site-header">
    <div class="wrap">
      <a href="{home_rel}" class="brand">
        <span class="brand-mark">Awake<span class="brand-dot">.</span>vc</span>
      </a>
      <nav class="site-nav">
        {nav_links}
      </nav>
      <button class="nav-toggle" aria-label="Menu" aria-expanded="false">
        <span></span><span></span><span></span>
      </button>
    </div>
  </header>
  {content}
  {footer}
  <script src="{js_rel}"></script>
</body>
</html>
"""


def nav_html(pages: dict[str, Page], home_rel: str, page_rel_prefix: str) -> str:
    items: list[str] = []
    for label, slug in NAV_ITEMS:
        # Re-point "About" to home.
        if slug == "about":
            href = home_rel
        else:
            href = f"{page_rel_prefix}{slug}.html"
        items.append(f'<a href="{href}">{label}</a>')
    return "\n        ".join(items)


def render_page_shell(title: str, description: str, content: str,
                       pages: dict[str, Page], is_home: bool) -> str:
    if is_home:
        css_rel = "css/styles.css"
        js_rel = "js/main.js"
        home_rel = "index.html"
        page_rel_prefix = "pages/"
        body_class = "home"
    else:
        css_rel = "../css/styles.css"
        js_rel = "../js/main.js"
        home_rel = "../index.html"
        page_rel_prefix = ""
        body_class = "page"
    return BASE_HTML.format(
        title=html.escape(title, quote=True),
        description=html.escape(description, quote=True),
        css_rel=css_rel,
        js_rel=js_rel,
        home_rel=home_rel,
        body_class=body_class,
        nav_links=nav_html(pages, home_rel, page_rel_prefix),
        content=content,
        footer=FOOTER_HTML.format(home=home_rel),
    )


# ---------------------------------------------------------------------------
# Home page
# ---------------------------------------------------------------------------

HOME_HERO = """
<section class="hero">
  <div class="wrap">
    <p class="eyebrow">Awakened Value Co-creation</p>
    <h1 class="hero-title">Protocols are <em>eating</em> venture.</h1>
    <p class="hero-lede">
      Awake Internet Protocols combine <strong>AI</strong> and <strong>FinTech</strong>
      to empower <strong>decentralized private equity</strong> for the agentic economy.
      A network of interconnected companies, co-creating value at the pace of AI.
    </p>
    <div class="hero-cta">
      <a class="btn btn-primary" href="pages/a64z.html">Meet a64z &rarr;</a>
    </div>
  </div>
</section>

<section class="callouts">
  <div class="wrap callouts-grid">
    <a class="card-link" href="https://EffectiveHumanism.org" target="_blank" rel="noopener">
      <span class="card-label">Philosophy</span>
      <span class="card-title">Effective Humanism</span>
      <span class="card-desc">Awakened Value Co-creation as a practice.</span>
    </a>
    <a class="card-link" href="https://BookOfAgents.com" target="_blank" rel="noopener">
      <span class="card-label">Writing</span>
      <span class="card-title">Book of Agents</span>
      <span class="card-desc">Building Intergraph.ai &mdash; stay tuned.</span>
    </a>
    <a class="card-link" href="https://Coselling.ai" target="_blank" rel="noopener">
      <span class="card-label">Product</span>
      <span class="card-title">Coselling.ai</span>
      <span class="card-desc">Community commerce for brands and agents.</span>
    </a>
    <a class="card-link" href="https://selltype.com" target="_blank" rel="noopener">
      <span class="card-label">Product</span>
      <span class="card-title">Selltype</span>
      <span class="card-desc">Growth intelligence for the Age of AI.</span>
    </a>
  </div>
</section>
"""


def home_content(pages: dict[str, Page], covers: dict | None = None) -> str:
    covers = covers or {}
    parts = [HOME_HERO]

    parts.append("""
<section class="multiverse">
  <div class="wrap">
    <p class="section-eyebrow">The Awake Multiverse</p>
    <h2 class="section-title">A whirlwind tour, by Meta.</h2>
    <p class="section-lede">
      A compendium of design constraints, market realities, philosophy, and methodology
      that together combine to form the foundation for the ecosystem powered by
      Awake Internet Protocols. If you read it all, you may find a few things you had
      not considered before.
    </p>
  </div>
</section>
""")

    parts.append('<section class="metas"><div class="wrap">')
    for meta_name, meta_blurb, page_titles in META_SECTIONS:
        parts.append(f'<div class="meta-block">')
        parts.append(f'  <div class="meta-header">')
        parts.append(f'    <h3>{html.escape(meta_name)}</h3>')
        parts.append(f'    <p>{html.escape(meta_blurb)}</p>')
        parts.append(f'  </div>')
        parts.append('  <ul class="meta-pages">')
        for title in page_titles:
            slug = slugify(title)
            page = pages.get(slug)
            label = page.title if page else title
            icon_file = covers.get(slug, {}).get("icon_file")
            icon_html = (
                f'<img class="meta-icon" src="{icon_file}" alt="" loading="lazy">'
                if icon_file else '<span class="meta-icon meta-icon-placeholder"></span>'
            )
            parts.append(
                f'    <li><a href="pages/{slug}.html">{icon_html}<span>{html.escape(label)}</span></a></li>'
            )
        parts.append('  </ul>')
        parts.append('</div>')
    parts.append('</div></section>')

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Portfolio page — merges all CSVs.
# ---------------------------------------------------------------------------

def portfolio_block() -> str:
    year_files = [
        ("2019", SRC_PAGES / "Portfolio" / "2019 cdf13b93ff824c0ab1c96ddaf1a37905.csv"),
        ("2020", SRC_PAGES / "Portfolio" / "2020 082244a9a1e542c2b16868c5b6c71be5.csv"),
        ("2021", SRC_PAGES / "Portfolio" / "2021 a91987639a5d40509e58ad45a9d0bea6.csv"),
        ("2022 Sneak Preview",
         SRC_PAGES / "Portfolio" / "2022 Sneak Preview 053cecec3d6246d1a5af3fad465b9424.csv"),
    ]
    out = ['<div class="portfolio">']
    for year, path in year_files:
        if not path.exists():
            continue
        out.append(f'<div class="portfolio-year">')
        out.append(f'  <h2>{html.escape(year)}</h2>')
        out.append(f'  <div class="portfolio-grid">')
        with path.open(encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("Name", "").strip()
                if not name:
                    continue
                out.append(f'    <div class="portfolio-item">{html.escape(name)}</div>')
        out.append('  </div>')
        out.append('</div>')
    out.append("</div>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def load_covers() -> dict:
    if not COVERS_MANIFEST.exists():
        return {}
    return json.loads(COVERS_MANIFEST.read_text())


def build():
    # Preserve scraped covers + icons across rebuilds.
    covers_backup = ROOT / ".covers-backup"
    if (DST / "images" / "covers").exists():
        if covers_backup.exists():
            shutil.rmtree(covers_backup)
        covers_backup.mkdir()
        shutil.copytree(DST / "images" / "covers", covers_backup / "covers")
        if (DST / "images" / "icons").exists():
            shutil.copytree(DST / "images" / "icons", covers_backup / "icons")

    if DST.exists():
        shutil.rmtree(DST)
    DST.mkdir(parents=True)
    (DST / "pages").mkdir()
    (DST / "css").mkdir()
    (DST / "js").mkdir()

    # Copy images first so resolve_image has a target.
    image_map = collect_and_copy_images()

    # Restore covers + icons.
    if covers_backup.exists():
        if (covers_backup / "covers").exists():
            shutil.copytree(covers_backup / "covers", DST / "images" / "covers")
        if (covers_backup / "icons").exists():
            shutil.copytree(covers_backup / "icons", DST / "images" / "icons")
        shutil.rmtree(covers_backup)

    covers = load_covers()

    # Walk export and build page registry.
    pages, name_to_slug = collect_pages()

    # Render each page.
    for slug, page in pages.items():
        md_text = page.src_path.read_text(encoding="utf-8")
        body_html = render_md(md_text, name_to_slug, image_map, home_rel="../index.html")

        # Append portfolio listing onto the portfolio page itself.
        if slug == "portfolio":
            body_html += "\n" + portfolio_block()

        cover_meta = covers.get(slug, {})
        cover_file = cover_meta.get("cover_file")
        icon_file = cover_meta.get("icon_file")
        cover_html = ""
        if cover_file:
            cover_html = (
                f'<div class="cover-hero" style="background-image:url(\'../{cover_file}\')"></div>'
            )
        title_inner = html.escape(page.title)
        if icon_file:
            title_inner = (
                f'<img class="page-icon" src="../{icon_file}" alt="" loading="lazy">'
                f'<span>{html.escape(page.title)}</span>'
            )
        content = f"""
<main class="page-main">
  {cover_html}
  <div class="wrap narrow">
    <p class="breadcrumb"><a href="../index.html">&larr; Awake Multiverse</a></p>
    <article class="prose">
      <h1 class="page-title{' with-icon' if icon_file else ''}">{title_inner}</h1>
      {body_html}
    </article>
  </div>
</main>
"""
        snippet = ""
        for raw in md_text.splitlines():
            s = raw.strip()
            if s and not s.startswith("#") and not s.startswith("!"):
                snippet = strip_md(s)
                break
        description = f"{page.title} — AwakeVC. {snippet[:160]}"
        html_out = render_page_shell(
            title=f"{page.title} · AwakeVC",
            description=description,
            content=content,
            pages=pages,
            is_home=False,
        )
        (DST / "pages" / f"{slug}.html").write_text(html_out, encoding="utf-8")

    # Render home.
    home_html = render_page_shell(
        title="AwakeVC · Because Protocols Are Eating Venture",
        description="Awake Internet Protocols combine AI and FinTech to empower decentralized private equity for the agentic economy.",
        content=home_content(pages, covers),
        pages=pages,
        is_home=True,
    )
    (DST / "index.html").write_text(home_html, encoding="utf-8")

    # Static assets.
    (DST / "css" / "styles.css").write_text(STYLES, encoding="utf-8")
    (DST / "js" / "main.js").write_text(MAIN_JS, encoding="utf-8")
    (DST / ".nojekyll").write_text("", encoding="utf-8")
    (DST / "CNAME").write_text("awake.vc\n", encoding="utf-8")

    print(f"Built {len(pages)} pages into {DST}")


# ---------------------------------------------------------------------------
# Static assets (inlined so the script stays self-contained)
# ---------------------------------------------------------------------------

STYLES = r"""
/* === AwakeVC static site === */
:root {
  --bg: #faf8f3;
  --bg-soft: #f3efe6;
  --surface: #ffffff;
  --ink: #111217;
  --ink-soft: #3a3b42;
  --muted: #7a7b82;
  --line: #e5e0d4;
  --line-soft: #efeadd;
  --accent: #b4531a;
  --accent-ink: #8a3f14;
  --accent-soft: #fbeedf;
  --serif: 'Fraunces', Georgia, 'Times New Roman', serif;
  --sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  --mono: 'JetBrains Mono', SFMono-Regular, Menlo, Consolas, monospace;
  --radius: 6px;
  --radius-lg: 14px;
  --shadow-sm: 0 1px 2px rgba(17, 18, 23, 0.04), 0 1px 3px rgba(17, 18, 23, 0.06);
  --shadow-md: 0 6px 20px rgba(17, 18, 23, 0.08);
}

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body {
  font-family: var(--sans);
  font-size: 17px;
  line-height: 1.65;
  color: var(--ink);
  background: var(--bg);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

img { max-width: 100%; height: auto; display: block; }
a { color: var(--accent-ink); text-decoration: none; }
a:hover { text-decoration: underline; text-decoration-thickness: 1.5px; text-underline-offset: 3px; }

.wrap {
  width: 100%;
  max-width: 1160px;
  margin: 0 auto;
  padding: 0 28px;
}
.wrap.narrow { max-width: 760px; }

/* ---------- Header / Nav ---------- */
.site-header {
  position: sticky;
  top: 0;
  z-index: 50;
  backdrop-filter: saturate(180%) blur(14px);
  -webkit-backdrop-filter: saturate(180%) blur(14px);
  background: rgba(250, 248, 243, 0.82);
  border-bottom: 1px solid var(--line-soft);
}
.site-header .wrap {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 64px;
}
.brand {
  font-family: var(--serif);
  font-weight: 600;
  font-size: 22px;
  letter-spacing: -0.01em;
  color: var(--ink);
}
.brand:hover { text-decoration: none; }
.brand-dot { color: var(--accent); }
.site-nav {
  display: flex;
  gap: 30px;
}
.site-nav a {
  font-size: 15px;
  font-weight: 500;
  color: var(--ink-soft);
  letter-spacing: 0.01em;
}
.site-nav a:hover { color: var(--accent-ink); text-decoration: none; }
.nav-toggle {
  display: none;
  background: none;
  border: 0;
  padding: 10px;
  cursor: pointer;
}
.nav-toggle span {
  display: block;
  width: 22px;
  height: 2px;
  background: var(--ink);
  margin: 4px 0;
  border-radius: 2px;
  transition: transform 0.2s, opacity 0.2s;
}

/* ---------- Hero (home) ---------- */
.hero {
  padding: 92px 0 72px;
  background:
    radial-gradient(1200px 500px at 10% -10%, rgba(180, 83, 26, 0.10), transparent 60%),
    radial-gradient(900px 500px at 110% 10%, rgba(180, 83, 26, 0.06), transparent 60%);
}
.eyebrow {
  font-family: var(--mono);
  font-size: 12px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--accent);
  margin: 0 0 18px;
}
.hero-title {
  font-family: var(--serif);
  font-size: clamp(48px, 8vw, 96px);
  font-weight: 500;
  line-height: 1.02;
  letter-spacing: -0.03em;
  margin: 0 0 24px;
  max-width: 16ch;
  color: var(--ink);
}
.hero-title em {
  font-style: italic;
  color: var(--accent-ink);
}
.hero-lede {
  font-size: 20px;
  line-height: 1.55;
  color: var(--ink-soft);
  max-width: 62ch;
  margin: 0 0 36px;
}
.hero-cta { display: flex; gap: 14px; flex-wrap: wrap; }
.btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 13px 22px;
  border-radius: 999px;
  font-size: 15px;
  font-weight: 500;
  letter-spacing: 0.01em;
  transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
  border: 1px solid transparent;
}
.btn-primary {
  background: var(--ink);
  color: var(--bg);
  box-shadow: var(--shadow-sm);
}
.btn-primary:hover { transform: translateY(-1px); text-decoration: none; box-shadow: var(--shadow-md); }
.btn-ghost {
  color: var(--ink);
  border-color: var(--line);
  background: var(--surface);
}
.btn-ghost:hover { border-color: var(--ink); text-decoration: none; }

/* ---------- Callout cards (home) ---------- */
.callouts { padding: 48px 0 24px; }
.callouts-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
.card-link {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 22px 22px 26px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  color: var(--ink);
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}
.card-link:hover {
  text-decoration: none;
  transform: translateY(-2px);
  border-color: var(--accent);
  box-shadow: var(--shadow-md);
}
.card-label {
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--muted);
}
.card-title {
  font-family: var(--serif);
  font-size: 22px;
  font-weight: 600;
  line-height: 1.2;
}
.card-desc {
  color: var(--ink-soft);
  font-size: 14px;
  line-height: 1.5;
}

/* ---------- Multiverse section ---------- */
.multiverse { padding: 80px 0 12px; }
.section-eyebrow {
  font-family: var(--mono);
  font-size: 12px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--accent);
  margin: 0 0 14px;
}
.section-title {
  font-family: var(--serif);
  font-size: clamp(34px, 5vw, 52px);
  font-weight: 500;
  line-height: 1.08;
  letter-spacing: -0.02em;
  margin: 0 0 22px;
  max-width: 20ch;
}
.section-lede {
  font-size: 18px;
  color: var(--ink-soft);
  max-width: 66ch;
  margin: 0;
}

/* ---------- Meta blocks ---------- */
.metas { padding: 28px 0 120px; }
.metas .wrap {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 28px 48px;
}
.meta-block {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  padding: 28px 30px 22px;
  transition: border-color 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
}
.meta-block:hover {
  border-color: var(--accent);
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}
.meta-header h3 {
  font-family: var(--serif);
  font-size: 24px;
  font-weight: 600;
  margin: 0 0 6px;
  letter-spacing: -0.01em;
}
.meta-header p {
  color: var(--muted);
  font-size: 14px;
  line-height: 1.55;
  margin: 0 0 18px;
}
.meta-pages {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px 8px;
}
.meta-pages li a {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border: 1px solid var(--line);
  border-radius: 999px;
  font-size: 13px;
  color: var(--ink-soft);
  background: var(--bg);
  transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}
.meta-icon {
  width: 18px;
  height: 18px;
  object-fit: contain;
  border-radius: 3px;
  flex-shrink: 0;
}
.meta-icon-placeholder {
  display: none;
}
.meta-pages li a:hover {
  background: var(--accent-soft);
  border-color: var(--accent);
  color: var(--accent-ink);
  text-decoration: none;
}

/* ---------- Cover hero ---------- */
.cover-hero {
  width: 100%;
  height: 280px;
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
}
@media (max-width: 720px) {
  .cover-hero { height: 180px; }
}

/* ---------- Article page ---------- */
.page-main { padding: 0; }
.page-main > .wrap { padding-top: 40px; padding-bottom: 96px; }
.page-main:not(:has(.cover-hero)) > .wrap { padding-top: 56px; }
.breadcrumb {
  font-family: var(--mono);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  margin: 0 0 28px;
}
.breadcrumb a { color: var(--muted); }
.breadcrumb a:hover { color: var(--accent-ink); }

.page-title {
  font-family: var(--serif);
  font-size: clamp(40px, 6vw, 64px);
  font-weight: 500;
  line-height: 1.05;
  letter-spacing: -0.025em;
  margin: 0 0 36px;
  color: var(--ink);
}
.page-title.with-icon {
  display: flex;
  align-items: center;
  gap: 16px;
}
.page-icon {
  width: 48px;
  height: 48px;
  object-fit: contain;
  flex-shrink: 0;
}

.prose { font-size: 18px; line-height: 1.75; color: var(--ink-soft); }
.prose h2 {
  font-family: var(--serif);
  font-size: 32px;
  font-weight: 600;
  line-height: 1.2;
  letter-spacing: -0.015em;
  margin: 48px 0 16px;
  color: var(--ink);
}
.prose h3 {
  font-family: var(--serif);
  font-size: 24px;
  font-weight: 600;
  line-height: 1.25;
  margin: 36px 0 12px;
  color: var(--ink);
}
.prose h4 {
  font-family: var(--sans);
  font-size: 15px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--accent);
  margin: 30px 0 8px;
}
.prose p { margin: 0 0 20px; }
.prose a { color: var(--accent-ink); border-bottom: 1px solid rgba(180, 83, 26, 0.3); }
.prose a:hover { border-bottom-color: var(--accent); text-decoration: none; }
.prose strong { color: var(--ink); font-weight: 600; }
.prose em { font-style: italic; }
.prose hr {
  border: 0;
  border-top: 1px solid var(--line);
  margin: 48px 0;
}
.prose figure { margin: 32px 0; }
.prose figure img {
  width: 100%;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
}
.prose figcaption {
  font-size: 14px;
  color: var(--muted);
  text-align: center;
  margin-top: 10px;
  font-style: italic;
}

.callout {
  background: var(--accent-soft);
  border-left: 3px solid var(--accent);
  border-radius: var(--radius);
  padding: 20px 24px;
  margin: 28px 0;
}
.callout p { margin: 0 0 12px; color: var(--ink-soft); }
.callout p:last-child { margin-bottom: 0; }
.callout a { color: var(--accent-ink); }

/* ---------- Portfolio ---------- */
.portfolio { margin-top: 40px; }
.portfolio-year { margin-bottom: 56px; }
.portfolio-year h2 {
  font-family: var(--serif);
  font-size: 28px;
  font-weight: 600;
  margin: 0 0 18px;
  color: var(--ink);
}
.portfolio-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}
.portfolio-item {
  padding: 22px 18px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  font-family: var(--serif);
  font-size: 18px;
  font-weight: 600;
  text-align: center;
  color: var(--ink);
  transition: border-color 0.2s ease, transform 0.15s ease;
}
.portfolio-item:hover {
  border-color: var(--accent);
  transform: translateY(-2px);
}

/* ---------- Footer ---------- */
.site-footer {
  margin-top: 40px;
  padding: 48px 0 64px;
  background: var(--bg-soft);
  border-top: 1px solid var(--line);
}
.site-footer .wrap {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 24px;
}
.footer-brand .brand-mark {
  font-family: var(--serif);
  font-size: 22px;
  font-weight: 600;
  color: var(--ink);
}
.footer-tag {
  font-style: italic;
  color: var(--muted);
  margin: 6px 0 0;
  font-size: 14px;
}
.footer-meta { text-align: right; font-size: 14px; color: var(--ink-soft); }
.footer-meta p { margin: 0 0 6px; }
.footer-meta a { color: var(--ink-soft); }
.footer-meta a:hover { color: var(--accent-ink); }
.footer-fine { color: var(--muted); font-size: 12px; }

/* ---------- Responsive ---------- */
@media (max-width: 900px) {
  .callouts-grid { grid-template-columns: repeat(2, 1fr); }
  .metas .wrap { grid-template-columns: 1fr; gap: 20px; }
}
@media (max-width: 720px) {
  body { font-size: 16px; }
  .hero { padding: 60px 0 48px; }
  .hero-lede { font-size: 17px; }
  .site-nav {
    position: absolute;
    top: 64px;
    left: 0;
    right: 0;
    background: var(--surface);
    border-bottom: 1px solid var(--line);
    flex-direction: column;
    gap: 0;
    padding: 12px 28px 20px;
    transform: translateY(-12px);
    opacity: 0;
    pointer-events: none;
    transition: transform 0.2s ease, opacity 0.2s ease;
  }
  .site-nav a { padding: 10px 0; border-bottom: 1px solid var(--line-soft); }
  .site-nav a:last-child { border-bottom: 0; }
  .site-nav.open {
    transform: translateY(0);
    opacity: 1;
    pointer-events: auto;
  }
  .nav-toggle { display: block; }
  .site-footer .wrap { flex-direction: column; }
  .footer-meta { text-align: left; }
  .prose { font-size: 17px; }
  .page-main { padding: 32px 0 72px; }
}
"""


MAIN_JS = r"""
// Mobile nav toggle — tiny and dependency-free.
(function () {
  var toggle = document.querySelector('.nav-toggle');
  var nav = document.querySelector('.site-nav');
  if (!toggle || !nav) return;
  toggle.addEventListener('click', function () {
    var open = nav.classList.toggle('open');
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  // Close on link click.
  nav.querySelectorAll('a').forEach(function (a) {
    a.addEventListener('click', function () {
      nav.classList.remove('open');
      toggle.setAttribute('aria-expanded', 'false');
    });
  });
})();
"""


if __name__ == "__main__":
    build()
