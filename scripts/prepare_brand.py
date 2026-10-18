#!/usr/bin/env python3
"""Prepare faithful web derivatives; run with --source pointing to the logo folder.

Asset preparation requires Pillow. The normal site build remains stdlib-only.
"""
import argparse
import shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent

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
    social = Image.new('RGB', (1200, 630), '#faf8f3')
    draw = ImageDraw.Draw(social)
    serif = ImageFont.truetype(str(args.font_dir / 'Georgia.ttf'), 80)
    sans = ImageFont.truetype(str(args.font_dir / 'Arial.ttf'), 32)
    small = ImageFont.truetype(str(args.font_dir / 'Arial.ttf'), 20)
    draw.text((80, 100), 'AWAKE.VC', font=small, fill='#8a3f14')
    draw.text((76, 185), 'awake.vc', font=serif, fill='#111217')
    draw.text((80, 310), 'Venture Studio', font=sans, fill='#3a3b42')
    draw.text((80, 357), 'for the Age of AI', font=sans, fill='#3a3b42')
    draw.line((80, 490, 350, 490), fill='#e5e0d4', width=2)
    painted = Image.open(originals / 'AwakeVC - Painted Logo.png').convert('RGB')
    painted = painted.resize((400, 400), Image.Resampling.LANCZOS)
    social.paste(painted, (720, 115))
    social.save(web / 'social.png', optimize=True)
    print('Prepared brand assets in', web)

if __name__ == '__main__':
    main()
