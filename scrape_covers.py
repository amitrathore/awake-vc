#!/usr/bin/env python3
"""Visit each exported Notion page headless, extract cover + icon URLs."""
import json, subprocess, sys, time, re
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from build import collect_pages

BROWSE = Path.home() / ".claude/skills/gstack/browse/dist/browse"

JS = r"""(()=>{
  const imgs = Array.from(document.querySelectorAll('img'));
  const icon = imgs.find(i => i.alt === 'Page icon');
  const notIcon = imgs.filter(i => i !== icon);
  // Cover heuristic: first image with width>=1000 and positioned near top
  let cover = null;
  for (const i of notIcon) {
    if (i.naturalWidth >= 800 && i.naturalHeight >= 200) {
      const r = i.getBoundingClientRect();
      if (r.top < 600) { cover = i; break; }
    }
  }
  return {
    title: document.title,
    cover: cover ? cover.src : null,
    coverW: cover ? cover.naturalWidth : 0,
    coverH: cover ? cover.naturalHeight : 0,
    icon: icon ? icon.src : null,
  };
})()"""

def run(args, capture=True):
    r = subprocess.run(args, capture_output=capture, text=True)
    return r.stdout.strip() if capture else None

def main():
    pages, _ = collect_pages()
    manifest_path = ROOT / "covers_manifest.json"
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())

    items = sorted(pages.items())
    for idx, (slug, page) in enumerate(items, 1):
        if slug in manifest:
            print(f"[{idx}/{len(items)}] {slug} — cached")
            continue
        stem = page.src_path.stem
        m = re.search(r"([0-9a-f]{32})$", stem)
        if not m:
            print(f"[{idx}/{len(items)}] {slug} — no UUID")
            continue
        uuid = m.group(1)
        url = f"https://awakevc.notion.site/{uuid}"
        print(f"[{idx}/{len(items)}] {slug} -> {uuid}")
        try:
            subprocess.run([str(BROWSE), "goto", url], capture_output=True, check=False, timeout=30)
            subprocess.run([str(BROWSE), "wait", "--load"], capture_output=True, check=False, timeout=30)
            time.sleep(1.2)  # let lazy-load settle
            out = subprocess.run([str(BROWSE), "js", JS], capture_output=True, text=True, timeout=20)
            data = json.loads(out.stdout.strip())
        except Exception as e:
            print(f"  ERROR: {e}")
            manifest[slug] = {"uuid": uuid, "url": url, "error": str(e)}
            manifest_path.write_text(json.dumps(manifest, indent=2))
            continue
        data["uuid"] = uuid
        data["url"] = url
        manifest[slug] = data
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(f"  cover={bool(data.get('cover'))} icon={bool(data.get('icon'))}")

    print(f"\nDone. {len(manifest)} pages in manifest.")

if __name__ == "__main__":
    main()
