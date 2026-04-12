#!/usr/bin/env python3
"""Download covers + icons from Notion CDN based on covers_manifest.json."""
import json, subprocess, urllib.parse, re, sys
from pathlib import Path

ROOT = Path(__file__).parent
MANIFEST = ROOT / "covers_manifest.json"
COVERS_DIR = ROOT / "docs" / "images" / "covers"
ICONS_DIR = ROOT / "docs" / "images" / "icons"
COVERS_DIR.mkdir(parents=True, exist_ok=True)
ICONS_DIR.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

def guess_ext(url: str, fallback: str) -> str:
    # The actual filename sits inside the percent-encoded inner URL.
    dec = urllib.parse.unquote(url)
    m = re.search(r"\.(png|jpe?g|gif|webp|svg)(?:[?&/]|$)", dec, re.I)
    if m:
        return "." + m.group(1).lower().replace("jpeg", "jpg")
    return fallback

def fetch(url: str, dest: Path, width: int = 2000):
    if "width=" in url:
        wider = re.sub(r"width=\d+", f"width={width}", url)
    else:
        sep = "&" if "?" in url else "?"
        wider = f"{url}{sep}width={width}"
    try:
        r = subprocess.run(
            ["curl", "-sSL", "--fail", "-A", UA, "-o", str(dest), wider],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
            print(f"  ERROR: {r.stderr.strip()}")
            dest.unlink(missing_ok=True)
            return False
        return True
    except Exception as e:
        print(f"  ERROR: {e}")
        return False

def main():
    manifest = json.loads(MANIFEST.read_text())
    updates = {}
    for slug, data in sorted(manifest.items()):
        local = {}
        if data.get("cover"):
            ext = guess_ext(data["cover"], ".jpg")
            out = COVERS_DIR / f"{slug}{ext}"
            if not out.exists():
                print(f"cover {slug}{ext}")
                if fetch(data["cover"], out):
                    local["cover_file"] = f"images/covers/{slug}{ext}"
            else:
                local["cover_file"] = f"images/covers/{slug}{ext}"
        if data.get("icon"):
            ext = guess_ext(data["icon"], ".png")
            out = ICONS_DIR / f"{slug}{ext}"
            if not out.exists():
                print(f"icon  {slug}{ext}")
                if fetch(data["icon"], out, width=200):
                    local["icon_file"] = f"images/icons/{slug}{ext}"
            else:
                local["icon_file"] = f"images/icons/{slug}{ext}"
        updates[slug] = {**data, **local}

    MANIFEST.write_text(json.dumps(updates, indent=2))
    covs = sum(1 for v in updates.values() if v.get("cover_file"))
    icos = sum(1 for v in updates.values() if v.get("icon_file"))
    print(f"\nDownloaded: {covs} covers, {icos} icons.")

if __name__ == "__main__":
    main()
