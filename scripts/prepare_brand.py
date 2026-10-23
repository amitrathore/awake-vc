#!/usr/bin/env python3
"""Prepare faithful web derivatives; run with --source pointing to the logo folder.

Asset preparation requires Pillow. The normal site build remains stdlib-only.
"""
import argparse
import shutil
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent

def prepare_social(web):
    """Prepare the selected Escher-inspired Eye as a World artwork for social previews."""
    source = ROOT / 'assets/brand/og-concepts/eye-world-escher.png'
    with Image.open(source) as artwork:
        artwork.convert('RGB').resize((1200, 630), Image.Resampling.LANCZOS).save(
            web / 'social-eye-escher.png', optimize=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--font-dir', type=Path, default=Path('/System/Library/Fonts/Supplemental'))
    args = parser.parse_args()
    originals = ROOT / 'assets/brand/originals'
    web = ROOT / 'assets/brand/web'
    originals.mkdir(parents=True, exist_ok=True)
    web.mkdir(parents=True, exist_ok=True)
    for edition in ['Dali', 'Kandinsky', 'Monet', 'Painted', 'Picasso', 'Sparke', 'Warhol']:
        source = args.source / ('AwakeVC - ' + edition + ' Logo.png')
        if source.resolve() != (originals / source.name).resolve():
            shutil.copy2(source, originals / source.name)
        image = Image.open(source).convert('RGB')
        image.thumbnail((640, 640) if edition not in ('Painted', 'Sparke') else (180, 180), Image.Resampling.LANCZOS)
        image.save(web / (edition.lower() + '.webp'), quality=88, method=6)
    sparke = Image.open(originals / 'AwakeVC - Sparke Logo.png').convert('RGB')
    for size in (16, 32, 180):
        name = 'apple-touch-icon.png' if size == 180 else f'favicon-{size}.png'
        sparke.resize((size, size), Image.Resampling.LANCZOS).save(web / name, optimize=True)
    sparke.resize((48, 48), Image.Resampling.LANCZOS).save(web / 'favicon.ico', sizes=[(16, 16), (32, 32), (48, 48)])
    prepare_social(web)
    print('Prepared brand assets in', web)

if __name__ == '__main__':
    main()
