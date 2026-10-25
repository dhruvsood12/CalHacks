"""Grid of random thumbnails per class, for eyeballing label quality.

Usage: python3 contact_sheet.py sf311 [per_class] [out.jpg]
"""
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

root = Path(sys.argv[1])
n = int(sys.argv[2]) if len(sys.argv) > 2 else 8
out = sys.argv[3] if len(sys.argv) > 3 else str(root / "contact_sheet.jpg")
T, LABEL_W = 128, 170

classes = sorted(p for p in (root / "images").iterdir() if p.is_dir() and any(p.iterdir()))
sheet = Image.new("RGB", (LABEL_W + n * T, len(classes) * T), "white")
draw = ImageDraw.Draw(sheet)
for row, cdir in enumerate(classes):
    files = sorted(cdir.glob("*.jpg"))
    picks = random.Random(cdir.name).sample(files, min(n, len(files)))
    draw.text((6, row * T + T // 2 - 6), cdir.name, fill="black")
    for col, f in enumerate(picks):
        im = Image.open(f).convert("RGB")
        im.thumbnail((T, T))
        sheet.paste(im, (LABEL_W + col * T, row * T))
sheet.save(out, quality=85)
print(out)
