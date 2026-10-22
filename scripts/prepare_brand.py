#!/usr/bin/env python3
"""Prepare faithful web derivatives; run with --source pointing to the logo folder.

Asset preparation requires Pillow. The normal site build remains stdlib-only.
"""
import argparse
import shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent

def prepare_social(originals, web, font_dir):
    """Render the current social card without replacing previously shared assets."""
    social = Image.new('RGB', (1200, 630), '#faf8f3')
    draw = ImageDraw.Draw(social)
    serif = ImageFont.truetype(str(font_dir / 'Georgia.ttf'), 84)
    sans = ImageFont.truetype(str(font_dir / 'Arial.ttf'), 28)
    small = ImageFont.truetype(str(font_dir / 'Arial.ttf'), 24)
    draw.text((80, 70), 'AWAKE.VC', font=small, fill='#8a3f14')
    for y, line in zip((155, 255, 355), ('Caution:', 'Agents', 'at Work.')):
        draw.text((76, y), line, font=serif, fill='#111217')
    draw.text((80, 505), 'Venture studio · Age of AI', font=sans, fill='#3a3b42')
    painted = Image.open(originals / 'AwakeVC - Painted Logo.png').convert('RGB')
    painted = painted.resize((400, 400), Image.Resampling.LANCZOS)
    social.paste(painted, (720, 115))
    social.save(web / 'social-agents.png', optimize=True)

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
    prepare_social(originals, web, args.font_dir)
    print('Prepared brand assets in', web)

if __name__ == '__main__':
    main()
