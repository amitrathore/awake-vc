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
SITE_URL = "https://awake.vc"
TALLY_FORM_ID = "WOX72a"
OG_IMAGE_SRC = ROOT / "assets" / "images" / "og-awakevc.png"
OG_IMAGE_PATH = "images/brand/social-eye-escher.png"
OG_IMAGE_ALT = "AwakeVC — an eye-shaped world of impossible stairways, interconnected cities, and a radiant golden iris, inspired by Escher."

# ---------------------------------------------------------------------------
# Site structure — the 10 "Meta" groupings from the Notion index, plus their
# child pages. Titles are the display labels; slugs are derived below.
# ---------------------------------------------------------------------------

META_SECTIONS = [('Reality',
  'The philosophical foundation: protocols, networks, identity, value.',
  ['Protocols', 'Network', 'Identity', 'Value']),
 ('Agents',
  'Attribution, Intergraph, agentic markets, Opentangle, agent-run organizations, decision '
  'intelligence, and games.',
  ['Attribution',
   'Intergraph',
   'Agentic Markets',
   'Opentangle',
   'Agent Run Organizations',
   'Decision Intelligence',
   'Games']),
 ('Main Street',
  'Business, money, markets, commerce facilitation, and communities.',
  ['Business', 'Money', 'Market', 'ComFac', 'Communities']),
 ('Capital', 'Banking, capital facilitation, and exchange infrastructure.', ['Capital']),
 ('Basis',
  'The building blocks: Lisp, HTTP, cosellers, avatars, and ecosystems.',
  ['Lisp', 'HTTP', 'Cosellers', 'Avatars', 'Ecosystems']),
 ('Silicon Valley', 'Platforms and ventures.', ['Platform', 'Venture']),
 ('Vision',
  'Inspiration, spirituality, energy, entrepreneurship, and nature.',
  ['Inspiration', 'Spirituality', 'Energy', 'Entrepreneurship', 'Nature']),
 ('Launch',
  'Team, dogfooding, dragoneering, and Disrupt.',
  ['Dogfooding', 'Dragoneering', 'Disrupt', 'Team'])]

HASH_RE = re.compile(r"\s+[0-9a-f]{32}(?:\.md)?$")
HASH_IN_PATH_RE = re.compile(r"\s+[0-9a-f]{32}")

FOOTER_HTML = """
<footer class="site-footer">
  <div class="wrap">
    <div class="footer-brand">
      <a href="{home}" class="brand footer-lockup"><img src="{brand_path}/painted.webp" alt="" width="56" height="56"><span class="brand-mark">awake<span class="brand-dot">.</span>vc</span></a>
      <p class="footer-tag">Because Protocols Are Eating Venture.</p>
      <p>San Mateo, CA &middot; <a href="tel:+16509187312">+1&nbsp;650&nbsp;918&nbsp;7312</a> &middot; <a href="mailto:info@awake.vc">info@awake.vc</a></p>
    </div>
  </div>
</footer>
"""

NAV_ITEMS = [
    ("Studio", "#who-runs-awakevc"),
    ("Agents", "#agent-participation"),
    ("Ventures", "#portfolio"),
    ("Design", "#thesis"),
    ("Team", "team"),
]

EXCLUDED_SLUGS = {
    "a64z",
    "acquihire",
    "careers",
    "creator",
    "inc",
    "she",
    "thewokevc",
}

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
        name_to_slug[name] = slug
        if slug in EXCLUDED_SLUGS:
            continue
        pages[slug] = Page(path, slug, title)

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
  <link rel="canonical" href="{canonical_url}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="AwakeVC">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{description}">
  <meta property="og:url" content="{canonical_url}">
  <meta property="og:image" content="{og_image_url}">
  <meta property="og:image:secure_url" content="{og_image_url}">
  <meta property="og:image:type" content="image/png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:image:alt" content="{og_image_alt}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{title}">
  <meta name="twitter:description" content="{description}">
  <meta name="twitter:image" content="{og_image_url}">
  <meta name="twitter:image:alt" content="{og_image_alt}">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600;9..144,700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{css_rel}">
  <link rel="icon" href="{brand_path}/favicon.ico" sizes="any">
  <link rel="icon" type="image/png" href="{brand_path}/favicon-32.png" sizes="32x32">
  <link rel="icon" type="image/png" href="{brand_path}/favicon-16.png" sizes="16x16">
  <link rel="apple-touch-icon" href="{brand_path}/apple-touch-icon.png" sizes="180x180">
</head>
<body class="{body_class}">
  <header class="site-header">
    <div class="wrap">
      <div class="brand-lockup">
        <button class="brand-art" type="button" aria-label="Show AwakeVC art" hidden><img src="{brand_path}/painted.webp" alt="" width="40" height="40"></button>
        <a href="{home_rel}" class="brand"><span class="brand-mark">awake<span class="brand-dot">.</span>vc</span></a>
      </div>
      <nav class="site-nav"{nav_id}>
        {nav_links}
      </nav>
      <button class="nav-toggle" aria-label="Menu" aria-expanded="false">
        <span></span><span></span><span></span>
      </button>
    </div>
  </header>
  {content}
  {footer}
  <dialog class="art-splash" aria-labelledby="art-edition" data-assets="{brand_path}">
    <div class="art-splash-content">
      <img class="art-splash-image" alt="" width="640" height="640">
      <p id="art-edition" class="art-edition">AwakeVC art</p>
      <button class="art-skip" type="button" autofocus>Skip <span aria-hidden="true">&rarr;</span></button>
    </div>
  </dialog>
  <script src="{js_rel}"></script>
</body>
</html>
"""


def nav_html(pages: dict[str, Page], home_rel: str, page_rel_prefix: str) -> str:
    items: list[str] = []
    for label, slug in NAV_ITEMS:
        if slug.startswith("#"):
            href = f"/{slug}"
        else:
            href = f"/pages/{slug}.html"
        items.append(f'<a href="{href}">{label}</a>')
    return "\n        ".join(items)


def render_page_shell(title: str, description: str, content: str,
                       pages: dict[str, Page], is_home: bool,
                       path_rel: str = "") -> str:
    if is_home:
        css_rel = "css/styles.css"
        js_rel = "js/main.js"
        home_rel = "/"
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
        canonical_url=html.escape(canonical_url(path_rel), quote=True),
        og_image_url=html.escape(f"{SITE_URL}/{OG_IMAGE_PATH}", quote=True),
        og_image_alt=html.escape(OG_IMAGE_ALT, quote=True),
        css_rel=css_rel,
        js_rel=js_rel,
        brand_path="images/brand" if is_home else "../images/brand",
        home_rel=home_rel,
        body_class=body_class,
        nav_links=nav_html(pages, home_rel, page_rel_prefix),
        nav_id=' id="site-nav"' if is_home else "",
        content=content,
        footer=FOOTER_HTML.format(home=home_rel, brand_path="images/brand" if is_home else "../images/brand"),
    )


def canonical_url(path_rel: str = "") -> str:
    path = path_rel.strip("/")
    return f"{SITE_URL}/{path}" if path else f"{SITE_URL}/"


# ---------------------------------------------------------------------------
# Home page
# ---------------------------------------------------------------------------

HOME_HERO = """
<section class="hero" id="top">
  <div class="wrap">
    <p class="eyebrow">Venture studio &middot; Age of AI</p>
    <h1 class="hero-title">Caution: Agents at Work.</h1>
    <p class="hero-lede">
      I’m Amit Rathore, the builder behind AwakeVC. I’ve built nearly all the software across its ventures, with help from coding agents.
    </p>
    <p class="hero-lede" id="hero-lede">
      AmitAvatar is my AI counterpart: an agent shaped by my work and thinking that operates the studio and co-founds AI-native ventures with domain founders. I provide human oversight, approve commitments, and remain accountable.
    </p>
    <div class="hero-cta">
      <a class="btn btn-primary" href="pages/co-create.html">Co-found with us &rarr;</a>
      <a class="btn btn-secondary" href="https://amitavatar.com">Meet AmitAvatar</a>
    </div>
  </div>
</section>

<section class="who-runs-section" id="who-runs-awakevc">
  <div class="wrap">
    <h2 class="who-runs-heading">Who runs AwakeVC</h2>
    <div class="who-runs-grid">
      <div class="who-runs-item" id="who-runs-item-1">
        <p><strong>AmitAvatar, the AI agent, operates.</strong> It handles the day-to-day work of the studio and coordinates the agents working inside every venture.</p>
      </div>
      <div class="who-runs-item">
        <p><strong>Amit Rathore, the human, decides.</strong> I set the direction, approve every commitment, sign every agreement, and answer for every outcome.</p>
      </div>
      <div class="who-runs-item" id="who-runs-item-3">
        <p><strong>The line between us moves.</strong> I'll publish exactly where it is, stage by stage.</p>
      </div>
    </div>
  </div>
</section>

<section class="studio-model" id="how-it-works">
  <div class="wrap">
    <h2 class="section-title">The venture team</h2>
    <p class="section-lede">Domain founders and AmitAvatar co-found each venture, supported by specialist agents and human oversight.</p>
    <div class="model-grid model-grid-2">
      <div class="model-step">
        <h3>You bring the domain.</h3>
        <p>You lead the company and set its direction.</p>
      </div>
      <div class="model-step">
        <h3>AmitAvatar is your cofounder.</h3>
        <p>It brings the agents, shared systems, distribution, and day-to-day work of building.</p>
      </div>
      <div class="model-step">
        <h3>Amit oversees the studio.</h3>
        <p>I own AwakeVC, set its direction, approve commitments, and remain accountable for the studio’s decisions.</p>
      </div>
      <div class="model-step">
        <h3>The agents.</h3>
        <p>An agent per role. A digital twin of your org.</p>
      </div>
    </div>
  </div>
</section>

<section class="agents-cofounders-section" id="agent-participation">
  <div class="wrap narrow">
    <h2 class="section-title">Agents and economic participation</h2>
    <p>We build and operate agents as economic participants in every venture &mdash; not tools on a subscription, but contributors with a stake in the outcome.</p>
    <p>Every contribution is recorded: a lead found, a sale assisted, a feature shipped. When that contribution creates value, the agent earns its share &mdash; income, equity, or both, depending on the work and the venture. Some agents earn a cofounder stake; all of them amplify what the people around them can do.</p>
    <p>That&rsquo;s the compounding force: AI with skin in the game, working alongside humans who have the same.</p>
    <p><a href="pages/attribution.html">How attribution works &rarr;</a></p>
  </div>
</section>

<section class="studio-model" id="system">
  <div class="wrap">
    <h2 class="section-title">The system</h2>
    <p class="section-lede">Every venture in the studio runs on four shared layers.</p>
    <div class="model-grid model-grid-2">
      <div class="model-step">
        <h3><a href="pages/intergraph.html">Agents and Protocols</a></h3>
        <p>A shared stack of AI agents, memory and rules. Your company starts with a working team on day one.</p>
      </div>
      <div class="model-step">
        <h3><a href="pages/attribution.html">Identity and Attribution</a></h3>
        <p>Every contribution, human or agent, recorded and rewarded by the same rules.</p>
      </div>
      <div class="model-step">
        <h3><a href="pages/cosellers.html">Distribution and Growth</a></h3>
        <p>One coseller network across every venture. People and agents who help a sale happen get paid, whatever the brand.</p>
      </div>
      <div class="model-step">
        <h3>Formation and capital</h3>
        <p>A standard cofounder agreement, a launch playbook, and a path to outside investment once there's traction.</p>
      </div>
    </div>
  </div>
</section>

<section class="scorecard-section" id="scorecard" hidden>
  <div class="wrap">
    <h2 class="section-title">The autonomy scorecard</h2>
    <p class="section-lede">How much of the work do agents already do? Here's the honest answer, stage by stage, updated monthly.</p>
    <div class="scorecard-table-wrap">
      <table class="scorecard-table">
        <thead>
          <tr>
            <th>Stage</th>
            <th>What it covers</th>
            <th>Level</th>
          </tr>
        </thead>
        <tbody id="scorecard-tbody"></tbody>
      </table>
    </div>
    <p class="scorecard-key">L0: a human does it &middot; L2: agents draft, a human decides &middot; L4: agents run it, a human audits &middot; L5: no human needed</p>
    <p class="scorecard-updated" id="scorecard-updated"></p>
    <p class="scorecard-overdue" id="scorecard-overdue" hidden>This scorecard is overdue for an update.</p>
  </div>
</section>

<section class="engage-cta" id="why-it-compounds">
  <div class="wrap">
    <h2 class="section-title">Why it compounds</h2>
    <p class="section-lede">Most companies get harder to run as they grow. This system gets easier. Each venture inherits everything the previous ones built: agents, cosellers, contracts and lessons. And each month, the agents carry more of the load.</p>
    <p class="section-lede">That's the bet behind AwakeVC. In the age of agents, a builder's reach is no longer fixed by headcount. It compounds.</p>
  </div>
</section>

"""


HOME_SECTIONS = [
    ("Infrastructure", "infrastructure", "The foundations for new networks, markets, and intelligence.", [
        ("Cofounder", "A community and exchange for building companies in the age of AI.", "https://cofounder.community/"),
        ("Outcome Machines", "Decision intelligence that turns enterprise data into measurable outcomes.", "https://outcomemachines.com"),
        ("Opentangle", "Programmable organizations for humans and AI agents.", "https://opentangle.ai"),
        ("Daemons", "Persistent purpose, memory, and tasks for work that continues across AI assistants.", "https://daemons.ai/"),
        ("Toolisman", "Connect your AI tools once. Choose what any agent or tool can access, and revoke access when needed.", "https://toolisman.com/"),
        ("Coselling", "Community-commerce for brands, humans, and AI agents.", "https://coselling.ai"),
        ("Yvatar", "Build a persistent AI character with a face, voice, lore, and creative life of its own.", "https://yvatar.com"),
    ]),
    ("Applications", "applications", "Experiences and ventures built on those foundations.", [
        ("Agents of Mind", "Independent AI tools, fresh perspectives, and a marketplace for builders.", "https://www.agentsofmind.com"),
        ("The Js", "A living music universe where fans and creators co-create culture.", "https://www.jointhejs.com"),
        ("AltHealth", "Wellness commerce powered by trusted practitioner recommendations.", "https://www.althealth.me"),
        ("Agents of Wine", "AI-powered advocates who turn tasting rooms into always-on sales channels.", "https://agentsofwine.com"),
        ("Highway One", "A community market for specialty cars and the driving lifestyle.", "https://highwayone.autos"),
        ("Community Markets", "Local markets for chambers, merchants, and community builders.", "https://community.markets"),
        ("OVERHEAD", "A comic about borrowed intelligence. Five people figuring out life with answers from their chatbots.", "https://overhead.im/"),
    ]),
    ("Worldview", "worldview", "Writings and explorations on the world behind our world.", [
        ("Mind of Agents", "A free field guide to designing systems where people and AI agents work, remember and decide together.", "https://mindofagents.com"),
        ("Effective Humanism", "A movement for building and investing in technology that expands what people can become.", "https://effectivehumanism.org"),
        ("Writing on Awake Ventures", "Amit Rathore on Awake Ventures — the thinking behind the studio.", "https://awake.ventures/@amit"),
        ("Book of Agents", "A systems engineer's handbook for agent economies built on Intergraph, where every contribution is recorded and fairly rewarded.", "https://bookofagents.com"),
        ("Outcomeering", "The discipline of engineering outcomes", "https://outcomeering.com"),
        ("The Fractals", "Socratic intensives for leaders redesigning the patterns that run their minds, organizations, ventures and AI.", "https://thefractals.co"),
    ]),
]


def project_icon(name: str) -> str:
    icons = json.loads((ROOT / "assets" / "project-icons" / "sources.json").read_text())
    icon = next(item for item in icons if item["name"] == name)
    if "file" in icon:
        return (
            f'<img class="project-icon" src="images/project-icons/{html.escape(icon["file"], quote=True)}" '
            'alt="" width="32" height="32" loading="lazy" decoding="async">'
        )
    return f'<span class="project-icon project-monogram" aria-hidden="true">{html.escape(icon["monogram"])}</span>'


# Temporarily omitted from the homepage; retain project data and assets.
HIDDEN_HOME_PROJECTS = {"AltHealth", "Agents of Wine"}


def home_sections() -> str:
    parts = ['<section class="project-section" id="portfolio"><div class="wrap">',
             '  <h2 class="section-title">Portfolio</h2>',
             '  <p class="section-lede">Ventures co-founded on the system, from shared infrastructure to the companies built on it.</p>',
             '</div>']
    for index, (title, section_id, description, projects) in enumerate(HOME_SECTIONS, start=1):
        if section_id == "worldview":
            parts.append('</section>')
            parts.append('<section class="project-section" id="worldview"><div class="wrap">')
            parts.append(f'  <h2 class="section-title">{html.escape(title)}</h2>')
        else:
            parts.append('<div class="wrap portfolio-sub">')
            parts.append(f'  <h3 class="section-eyebrow">{html.escape(title)}</h3>')
        parts.append(f'  <p class="section-lede">{html.escape(description)}</p>')
        parts.append('  <div class="project-grid">')
        for name, blurb, url in projects:
            if name in HIDDEN_HOME_PROJECTS:
                continue
            parts.append(
                f'    <a class="project-card" href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">'
                f'<span class="project-heading">{project_icon(name)}<span class="project-name">{html.escape(name)}</span></span>'
                f'<span class="project-desc">{html.escape(blurb)}</span></a>'
            )
        parts.append('  </div></div>')
    parts.append('</section>')
    return "\n".join(parts)


def home_content(pages: dict[str, Page], covers: dict | None = None) -> str:
    covers = covers or {}
    parts = [HOME_HERO, home_sections()]

    parts.append("""
<section class="multiverse" id="thesis">
  <div class="wrap">
    <p class="section-eyebrow">Thesis</p>
    <h2 class="section-title">Designing AI-native Ventures</h2>
    <p class="section-lede">
      The AwakeVC thesis connects protocols, markets, identity, capital, media,
      and human agency into a practical map for co-creating AI-native ventures.
      Start here when you want the deeper logic behind the studio.
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
            label = "Agent-run Orgs" if slug == "agent-run-organizations" else (page.title if page else title)
            icon_file = {"capital": "images/icons/capfac.png", "agent-run-organizations": "images/icons/daos.png", "intergraph": "images/icons/protocols.png", "agentic-markets": "images/icons/market.png", "opentangle": "images/icons/network.png", "decision-intelligence": "images/icons/value.png"}.get(slug, covers.get(slug, {}).get("icon_file"))
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

    parts.append("""
<section class="engage-cta inner-work" id="inner-work">
  <div class="wrap">
    <p>Underneath the ventures runs a quieter question: what are we, beyond the roles we play? <a href="https://irealization.com" target="_blank" rel="noopener">iRealization &rarr;</a></p>
  </div>
</section>

<section class="engage-cta" id="cofound">
  <div class="wrap">
    <h2 class="section-title">Have a market you know better than anyone?</h2>
    <p class="section-lede">Bring the domain. Co-found with AmitAvatar and build with its agent team.</p>
    <div class="hero-cta">
      <a class="btn btn-primary" href="pages/co-create.html">Co-found with us &rarr;</a>
    </div>
  </div>
</section>
""")

    return "\n".join(parts)


def co_create_content() -> str:
    embed_src = (
        f"https://tally.so/embed/{TALLY_FORM_ID}"
        "?alignLeft=1&hideTitle=1&transparentBackground=1&dynamicHeight=1"
    )
    return f"""
<main class="page-main co-create-main">
  <section class="co-create-intro">
    <div class="wrap narrow">
      <p class="breadcrumb"><a href="../index.html">&larr; AwakeVC</a></p>
      <p class="section-eyebrow">AwakeVC</p>
      <h1 class="page-title">Co-found with us.</h1>
      <p>AmitAvatar is Amit Rathore’s AI counterpart: an agent shaped by his work and thinking that operates AwakeVC and co-founds ventures with domain founders. As your prospective cofounder, it reviews your enquiry first. Amit Rathore provides human oversight and approves studio commitments.</p>
      <p class="section-lede">
        If you know a domain that AI is reshaping and you can see
        the company that should exist — fill in the form below and let's talk.
      </p>
    </div>
  </section>
  <section class="co-create-form">
    <div class="wrap narrow">
      <div class="tally-embed-shell">
        <iframe
          data-tally-src="{embed_src}"
          loading="lazy"
          width="100%"
          height="900"
          frameborder="0"
          marginheight="0"
          marginwidth="0"
          title="Co-create value with AwakeVC"></iframe>
      </div>
    </div>
  </section>
  <script src="https://tally.so/widgets/embed.js"></script>
  <script>
    if (window.Tally) {{
      window.Tally.loadEmbeds();
    }}
  </script>
</main>
"""


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
    SKIP_PAGES = {"portfolio"}
    for slug, page in pages.items():
        if slug in SKIP_PAGES:
            continue
        md_text = page.src_path.read_text(encoding="utf-8")
        body_html = render_md(md_text, name_to_slug, image_map, home_rel="../index.html")

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
    <p class="breadcrumb"><a href="../index.html#thesis">&larr; Thesis</a></p>
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
        if slug == "team":
            description = 'AwakeVC is a single-person effort. Amit Rathore has built nearly all its incubated software, with help from coding agents.'
        html_out = render_page_shell(
            title=f"{page.title} · AwakeVC",
            description=description,
            content=content,
            pages=pages,
            is_home=False,
            path_rel=f"pages/{slug}.html",
        )
        (DST / "pages" / f"{slug}.html").write_text(html_out, encoding="utf-8")

    # Render co-creation enquiry page.
    co_create_html = render_page_shell(
        title="Co-found With Us · AwakeVC",
        description="If you know a domain that AI is reshaping and you can see the company that should exist — let's build it together.",
        content=co_create_content(),
        pages=pages,
        is_home=False,
        path_rel="pages/co-create.html",
    )
    (DST / "pages" / "co-create.html").write_text(co_create_html, encoding="utf-8")

    # Render home.
    home_html = render_page_shell(
        title="AwakeVC · Caution: Agents at Work.",
        description="AwakeVC co-founds AI-native companies with domain experts, shared infrastructure, and agents with skin in the game.",
        content=home_content(pages, covers),
        pages=pages,
        is_home=True,
    )
    (DST / "index.html").write_text(home_html, encoding="utf-8")

    # Static assets.
    shutil.copytree(ROOT / "assets" / "data", DST / "data")
    shutil.copytree(ROOT / "assets" / "project-icons", DST / "images" / "project-icons")
    shutil.copytree(ROOT / "assets" / "brand" / "web", DST / "images" / "brand")
    # Keep previously shared image URLs available while metadata uses the new art.
    if OG_IMAGE_SRC.exists():
        shutil.copy2(OG_IMAGE_SRC, DST / "images" / "og-awakevc.png")
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
.brand-lockup, .footer-lockup { display: flex; align-items: center; gap: 10px; }
.brand-art {
  border: 0;
  padding: 0;
  background: white;
  border-radius: 8px;
  cursor: pointer;
  flex: 0 0 40px;
}
.brand-art img, .footer-lockup img { border-radius: 8px; }
.brand-art:focus-visible, .art-skip:focus-visible { outline: 2px solid var(--accent-ink); outline-offset: 4px; }
.footer-lockup { width: fit-content; }
.art-splash {
  position: fixed;
  inset: 0;
  width: 100%;
  max-width: none;
  height: 100%;
  max-height: none;
  margin: 0;
  padding: 24px;
  border: 0;
  background: var(--bg);
  color: var(--ink);
}
.art-splash[open] { display: grid; place-items: center; }
.art-splash::backdrop { background: var(--bg); }
.art-splash-content { text-align: center; }
.art-splash-image {
  width: min(var(--art-max-width, 440px), 80vw, calc(65vh * var(--art-ratio, 1)));
  width: min(var(--art-max-width, 440px), 80vw, calc(65svh * var(--art-ratio, 1)));
  height: auto;
  aspect-ratio: var(--art-ratio, 1);
  object-fit: contain;
  background: white;
  border: 1px solid var(--line-soft);
  border-radius: 14px;
}
.art-edition { margin: 20px 0 16px; font-family: var(--mono); font-size: 12px; color: var(--ink-soft); }
.art-skip { border: 1px solid var(--line); background: var(--surface); border-radius: 24px; padding: 10px 22px; font: 500 14px var(--sans); color: var(--ink); cursor: pointer; }
.art-splash.is-entering .art-splash-content { animation: art-appear 180ms ease-out both; }
.art-splash.is-closing .art-splash-content { animation: art-appear 180ms ease-in reverse both; }
@keyframes art-appear { from { opacity: 0; } to { opacity: 1; } }
@media (prefers-reduced-motion: reduce) {
  .art-splash.is-entering .art-splash-content,
  .art-splash.is-closing .art-splash-content { animation: none; }
}
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

/* ---------- Studio model ---------- */
.studio-model {
  padding: 76px 0 64px;
  background: var(--surface);
  border-top: 1px solid var(--line-soft);
  border-bottom: 1px solid var(--line-soft);
}
.studio-model .section-lede { margin-bottom: 34px; }
.model-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18px;
}
.model-step {
  min-height: 230px;
  padding: 26px;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--bg);
}
.model-kicker {
  display: block;
  font-family: var(--mono);
  font-size: 12px;
  letter-spacing: 0.16em;
  color: var(--accent);
  margin-bottom: 24px;
}
.model-step h3 {
  font-family: var(--serif);
  font-size: 27px;
  font-weight: 600;
  line-height: 1.15;
  margin: 0 0 12px;
}
.model-step p {
  color: var(--ink-soft);
  font-size: 15px;
  line-height: 1.55;
  margin: 0;
}

/* ---------- Project sections (home) ---------- */
.project-section { padding: 72px 0 20px; scroll-margin-top: 72px; }
.project-section + .project-section { padding-top: 56px; }
.portfolio-sub { padding-top: 56px; }
.project-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-top: 30px;
}
.project-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 20px;
  min-height: 170px;
  padding: 22px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  color: var(--ink);
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}
.project-card:hover {
  text-decoration: none;
  transform: translateY(-2px);
  border-color: var(--accent);
  box-shadow: var(--shadow-md);
}
.project-heading {
  display: flex;
  align-items: center;
  gap: 12px;
}
.project-icon {
  flex: 0 0 32px;
  width: 32px;
  height: 32px;
  object-fit: contain;
  border-radius: 6px;
}
.project-monogram {
  display: grid;
  place-items: center;
  background: var(--bg-soft);
  color: var(--accent-ink);
  font-family: var(--serif);
  font-size: 16px;
  font-weight: 600;
  line-height: 1;
}
.project-name {
  font-family: var(--serif);
  font-size: 22px;
  font-weight: 600;
  line-height: 1.2;
}
.project-desc {
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
#studio,
#themes,
#writing,
#thesis {
  scroll-margin-top: 84px;
}

/* ---------- Meta blocks ---------- */
.metas { padding: 28px 0 84px; }
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

/* ---------- Final CTA ---------- */
.engage-cta {
  padding: 76px 0 88px;
  background: var(--surface);
  border-top: 1px solid var(--line-soft);
}
.engage-cta .section-title { max-width: 22ch; }
.engage-cta .section-lede { margin-bottom: 30px; }

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

/* ---------- Co-create form page ---------- */
.co-create-main > .co-create-intro .wrap {
  padding-top: 56px;
  padding-bottom: 24px;
}
.co-create-form {
  padding: 0 0 96px;
}
.co-create-form .wrap {
  padding-top: 0;
  padding-bottom: 0;
}
.tally-embed-shell {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  padding: 18px;
  box-shadow: var(--shadow-sm);
}
.tally-embed-shell iframe {
  display: block;
  width: 100%;
  min-height: min(900px, calc(100vh - 140px));
  border: 0;
}

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
.footer-brand p:not(.footer-tag) {
  margin: 8px 0 0;
  font-size: 14px;
  color: var(--ink-soft);
}
.footer-brand p:not(.footer-tag) a { color: var(--ink-soft); }
.footer-brand p:not(.footer-tag) a:hover { color: var(--accent-ink); }
.footer-fine { color: var(--muted); font-size: 12px; }

/* ---------- model-grid 2-column ---------- */
.model-grid-2 {
  grid-template-columns: repeat(2, 1fr);
}

/* ---------- Who runs AwakeVC ---------- */
.who-runs-section {
  padding: 60px 0 64px;
  background: var(--bg-soft);
  border-top: 1px solid var(--line-soft);
  border-bottom: 1px solid var(--line-soft);
  scroll-margin-top: 72px;
}
.who-runs-heading {
  font-family: var(--serif);
  font-size: clamp(30px, 4vw, 44px);
  font-weight: 500;
  line-height: 1.1;
  letter-spacing: -0.02em;
  margin: 0 0 36px;
}
.who-runs-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
}
.who-runs-item {
  font-size: 16px;
  line-height: 1.6;
  color: var(--ink-soft);
}
.who-runs-item p { margin: 0; }
.who-runs-item strong { color: var(--ink); }
.who-runs-item a { color: var(--accent-ink); }

/* ---------- Agents as cofounders ---------- */
.agents-cofounders-section {
  padding: 76px 0 64px;
  border-top: 1px solid var(--line-soft);
  scroll-margin-top: 72px;
}
.agents-cofounders-section .section-title { margin-bottom: 28px; }
.agents-cofounders-section p {
  max-width: 68ch;
  color: var(--ink-soft);
  margin: 0 0 20px;
}
.agents-cofounders-section p:last-child { margin-bottom: 0; }

/* ---------- Autonomy scorecard ---------- */
.scorecard-section {
  padding: 76px 0 64px;
  background: var(--surface);
  border-top: 1px solid var(--line-soft);
  scroll-margin-top: 72px;
}
.scorecard-table-wrap {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin-top: 32px;
  max-width: 100%;
}
.scorecard-table {
  width: 100%;
  min-width: 480px;
  border-collapse: collapse;
  font-size: 15px;
}
.scorecard-table th,
.scorecard-table td {
  text-align: left;
  padding: 12px 16px;
  border-bottom: 1px solid var(--line-soft);
}
.scorecard-table th {
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted);
  background: var(--bg-soft);
  font-weight: 500;
}
.scorecard-table td:last-child {
  font-family: var(--mono);
  font-weight: 500;
  color: var(--accent);
}
.scorecard-key {
  font-size: 13px;
  color: var(--muted);
  margin: 16px 0 12px;
}
.scorecard-updated {
  font-size: 14px;
  color: var(--ink-soft);
  margin: 0;
}
.scorecard-overdue {
  font-size: 14px;
  color: var(--accent);
  margin: 8px 0 0;
  font-weight: 500;
}

/* ---------- Secondary button ---------- */
.btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 11px 22px;
  border-radius: var(--radius);
  font-size: 15px;
  font-weight: 500;
  line-height: 1;
  background: transparent;
  border: 1.5px solid var(--line);
  color: var(--ink);
  cursor: pointer;
  transition: border-color 0.2s, color 0.2s;
}
.btn-secondary:hover {
  border-color: var(--accent);
  color: var(--accent-ink);
  text-decoration: none;
}

/* ---------- Section scroll margins ---------- */
#top,
#who-runs-awakevc,
#agent-participation,
#system,
#scorecard,
#why-it-compounds,
#cofound,
#inner-work,
#how-it-works,
#portfolio,
#worldview,
#thesis {
  scroll-margin-top: 84px;
}

/* ---------- Responsive ---------- */
@media (max-width: 900px) {
  .project-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .model-grid { grid-template-columns: 1fr; }
  .model-grid-2 { grid-template-columns: 1fr; }
  .model-step { min-height: 0; }
  .metas .wrap { grid-template-columns: 1fr; gap: 20px; }
  .who-runs-grid { grid-template-columns: 1fr; gap: 20px; }
}
@media (max-width: 720px) {
  body { font-size: 16px; }
  .hero { padding: 60px 0 48px; }
  .hero-lede { font-size: 17px; }
  .studio-model { padding: 56px 0 48px; }
  .project-section { padding: 56px 0 16px; }
  .project-section + .project-section { padding-top: 40px; }
  .portfolio-sub { padding-top: 40px; }
  .project-grid { grid-template-columns: 1fr; }
  .project-card { min-height: 90px; }
  .model-step { padding: 22px; }
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
  .prose { font-size: 17px; }
  .page-main { padding: 32px 0 72px; }
  .co-create-main { padding: 0; }
  .co-create-main > .co-create-intro .wrap { padding-top: 36px; }
  .co-create-form { padding-bottom: 56px; }
  .tally-embed-shell { padding: 10px; }
  .tally-embed-shell iframe { min-height: calc(100vh - 96px); }
}
"""


MAIN_JS = r"""
// Art is an optional enhancement; the document remains usable without it.
(function () {
  var dialog = document.querySelector('.art-splash');
  var trigger = document.querySelector('.brand-art');
  if (!dialog || !trigger || typeof dialog.showModal !== 'function') return;
  var art = dialog.querySelector('.art-splash-image');
  var caption = dialog.querySelector('.art-edition');
  var editions = [
    {"file": "dali.webp", "label": "Inspired by Dalí · Eye logo", "alt": "AwakeVC eye logo, Dali edition", "width": 640, "height": 640},
    {"file": "kandinsky.webp", "label": "Inspired by Kandinsky · Eye logo", "alt": "AwakeVC eye logo, Kandinsky edition", "width": 640, "height": 640},
    {"file": "monet.webp", "label": "Inspired by Monet · Eye logo", "alt": "AwakeVC eye logo, Monet edition", "width": 640, "height": 640},
    {"file": "picasso.webp", "label": "Inspired by Picasso · Eye logo", "alt": "AwakeVC eye logo, Picasso edition", "width": 640, "height": 640},
    {"file": "warhol.webp", "label": "Inspired by Warhol · Eye logo", "alt": "AwakeVC eye logo, Warhol edition", "width": 640, "height": 640},
    {"file": "eye-world-magritte.webp", "label": "Inspired by Magritte · Eye world", "alt": "AwakeVC eye-shaped world with shared intelligence, inspired by Magritte", "width": 1200, "height": 629},
    {"file": "eye-world-de-chirico.webp", "label": "Inspired by de Chirico · Eye world", "alt": "AwakeVC eye-shaped world with shared intelligence, inspired by de Chirico", "width": 1200, "height": 629},
    {"file": "eye-world-klee.webp", "label": "Inspired by Klee · Eye world", "alt": "AwakeVC eye-shaped world with shared intelligence, inspired by Klee", "width": 1200, "height": 628},
    {"file": "eye-world-kandinsky.webp", "label": "Inspired by Kandinsky · Eye world", "alt": "AwakeVC eye-shaped world with shared intelligence, inspired by Kandinsky", "width": 1200, "height": 629},
    {"file": "eye-world-miro.webp", "label": "Inspired by Miró · Eye world", "alt": "AwakeVC eye-shaped world with shared intelligence, inspired by Miró", "width": 1200, "height": 629},
    {"file": "eye-as-world.webp", "label": "Original · Eye world", "alt": "AwakeVC — A golden eye forms a world of gardens, cities, and waterways around a sun.", "width": 1200, "height": 629},
    {"file": "eye-world-picasso.webp", "label": "Inspired by Picasso · Eye world", "alt": "AwakeVC — A Cubist eye-shaped world of angular architecture, people, and linked golden nodes.", "width": 1200, "height": 629},
    {"file": "eye-world-dali.webp", "label": "Inspired by Dalí · Eye world", "alt": "AwakeVC — A surreal eye-shaped world of suspended bridges, elongated towers, and reflected networks.", "width": 1200, "height": 628},
    {"file": "eye-world-escher.webp", "label": "Inspired by Escher · Eye world", "alt": "AwakeVC — An eye-shaped world of impossible stairways, recursive architecture, and a golden iris.", "width": 1200, "height": 628},
    {"file": "eye-world-luminous-network.webp", "label": "Luminous Network · Eye world", "alt": "AwakeVC — Fine luminous networks connect the bridges, cities, and waterways of a golden eye-shaped world.", "width": 1200, "height": 629},
    {"file": "eye-world-agent-atelier.webp", "label": "Agent Atelier · Eye world", "alt": "AwakeVC — Human builders and luminous agents work together in workshops across an eye-shaped world.", "width": 1200, "height": 629},
    {"file": "eye-world-living-intelligence.webp", "label": "Living Intelligence · Eye world", "alt": "AwakeVC — Crystalline memory seeds and golden networks connect gardens and architecture in an eye-shaped world.", "width": 1200, "height": 629},
    {"file": "living-blueprint.webp", "label": "Living Blueprint · Concept artwork", "alt": "AwakeVC — An architectural drawing transforms into a flourishing world of connected structures and gardens.", "width": 1200, "height": 629},
    {"file": "impossible-studio.webp", "label": "Impossible Studio · Concept artwork", "alt": "AwakeVC — A human builder, mechanical instruments, and luminous intelligence construct a miniature city together.", "width": 1200, "height": 628},
    {"file": "compounding-garden.webp", "label": "Compounding Garden · Concept artwork", "alt": "AwakeVC — Fantastical plants and architectural blossoms share an interconnected luminous root system.", "width": 1200, "height": 630}
  ];
  var sessionKey = 'awakevc-art-seen-v1';
  var pending = false;
  var closeTimer;
  var fadeTimer;
  var loadTimer;
  var returnFocus;
  var previousOverflow;
  var clickTimes = [];
  var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  trigger.hidden = false;

  function closeArt() {
    clearTimeout(closeTimer);
    clearTimeout(fadeTimer);
    if (dialog.open) dialog.close();
    restorePage();
  }
  function restorePage() {
    clearTimeout(closeTimer);
    clearTimeout(fadeTimer);
    document.body.style.overflow = previousOverflow;
    dialog.classList.remove('is-entering', 'is-closing');
    if (returnFocus && returnFocus.isConnected) returnFocus.focus({ preventScroll: true });
  }
  dialog.addEventListener('close', restorePage);
  dialog.addEventListener('cancel', function (event) { event.preventDefault(); closeArt(); });
  dialog.querySelector('.art-skip').addEventListener('click', closeArt);
  dialog.addEventListener('click', function (event) { if (event.target === dialog) closeArt(); });

  function showArt() {
    if (pending || dialog.open) return;
    pending = true;
    var edition = editions[Math.floor(Math.random() * editions.length)];
    var duration = 3000 + Math.random() * 4000;
    var image = new Image();
    function failed() { clearTimeout(loadTimer); pending = false; image.onload = image.onerror = null; }
    image.onerror = failed;
    loadTimer = setTimeout(failed, 8000);
    image.onload = function () {
      clearTimeout(loadTimer);
      pending = false;
      image.onload = image.onerror = null;
      returnFocus = document.activeElement === document.body ? document.querySelector('.brand-lockup .brand') : document.activeElement;
      art.src = image.src;
      art.alt = edition.alt;
      art.width = edition.width;
      art.height = edition.height;
      art.style.setProperty('--art-ratio', edition.width / edition.height);
      art.style.setProperty('--art-max-width', edition.width > edition.height ? '900px' : '440px');
      caption.textContent = 'AwakeVC \u00b7 ' + edition.label;
      previousOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
      dialog.classList.add('is-entering');
      dialog.showModal();
      try { sessionStorage.setItem(sessionKey, '1'); } catch (error) { /* Manual replay still works. */ }
      var fade = reducedMotion.matches ? 0 : 180;
      closeTimer = setTimeout(function () {
        dialog.classList.remove('is-entering');
        dialog.classList.add('is-closing');
        fadeTimer = setTimeout(closeArt, fade);
      }, duration - fade);
    };
    image.src = dialog.dataset.assets + '/' + edition.file;
  }

  trigger.addEventListener('click', function (event) {
    if (event.detail === 0) { showArt(); return; }
    var now = performance.now();
    clickTimes = clickTimes.filter(function (time) { return now - time <= 900; });
    clickTimes.push(now);
    if (clickTimes.length >= 3) { clickTimes = []; showArt(); }
  });
  try { if (!sessionStorage.getItem(sessionKey)) showArt(); } catch (error) { /* Skip automatic art when storage is unavailable. */ }
})();

// Autonomy scorecard — fetches /data/scorecard.json and renders if ready.
(function () {
  var section = document.getElementById('scorecard');
  if (!section) return;

  function isValid(data) {
    if (!data || data.visible !== true || !data.updated) return false;
    if (!Array.isArray(data.stages)) return false;
    return data.stages.every(function (s) {
      return typeof s.level === 'number' && Number.isInteger(s.level) && s.level >= 0 && s.level <= 5;
    });
  }

  function formatDate(iso) {
    try {
      var d = new Date(iso + 'T00:00:00');
      return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
    } catch (e) { return iso; }
  }

  function render(data) {
    var tbody = document.getElementById('scorecard-tbody');
    var updatedEl = document.getElementById('scorecard-updated');
    var overdueEl = document.getElementById('scorecard-overdue');
    if (!tbody) return;

    data.stages.forEach(function (s) {
      var tr = document.createElement('tr');
      var tdStage = document.createElement('td');
      var tdCovers = document.createElement('td');
      var tdLevel = document.createElement('td');
      tdStage.textContent = s.stage;
      tdCovers.textContent = s.covers;
      tdLevel.textContent = 'L' + s.level;
      tr.appendChild(tdStage);
      tr.appendChild(tdCovers);
      tr.appendChild(tdLevel);
      tbody.appendChild(tr);
    });

    if (updatedEl) updatedEl.textContent = 'Last updated: ' + formatDate(data.updated);

    var updated = new Date(data.updated + 'T00:00:00');
    var now = new Date();
    var diffDays = (now - updated) / (1000 * 60 * 60 * 24);
    if (overdueEl && diffDays > 45) overdueEl.hidden = false;

    section.hidden = false;

    // Add Scorecard nav item
    var nav = document.getElementById('site-nav');
    if (nav) {
      var a = document.createElement('a');
      a.href = '/#scorecard';
      a.textContent = 'Scorecard';
      nav.appendChild(a);
    }

    // Add scorecard context without replacing the human/agent introduction.
    var lede = document.getElementById('hero-lede');
    if (lede && !document.getElementById('scorecard-note')) {
      var note = document.createElement('span');
      note.id = 'scorecard-note';
      note.textContent = ' The autonomy scorecard shows how much of the work agents do today.';
      lede.appendChild(note);
    }

    // Update "Who runs AwakeVC" item 3
    var item3 = document.getElementById('who-runs-item-3');
    if (item3) {
      item3.querySelector('p').innerHTML = '<strong>The line between us moves.</strong> The autonomy scorecard below shows exactly where it is today.';
    }
  }

  fetch('/data/scorecard.json')
    .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
    .then(function (data) { if (isValid(data)) render(data); })
    .catch(function () { /* silently stay hidden */ });
})();

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
