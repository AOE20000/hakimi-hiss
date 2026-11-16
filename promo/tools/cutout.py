"""Cut out character poses from white background (rembg isnet-anime), trim, save RGBA PNG.

Usage: python tools/cutout.py [--force]
"""
import sys
import pathlib

from PIL import Image, ImageOps
from rembg import remove, new_session

root = pathlib.Path(__file__).resolve().parent.parent
raw, cut = root / "assets/chars/raw", root / "assets/chars/cut"
cut.mkdir(parents=True, exist_ok=True)
sess = new_session("isnet-anime")
for f in sorted(raw.glob("*.jpg")):
    out = cut / (f.stem + ".png")
    if out.exists() and "--force" not in sys.argv:
        continue
    im = Image.open(f).convert("RGB")
    rgba = remove(im, session=sess, post_process_mask=True)
    bbox = rgba.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    rgba = rgba.crop(bbox)
    rgba.save(out)
    print(f.stem, rgba.size, flush=True)

# pose03 = mirrored pose02 (hissing, facing left)
src = cut / "pose02.png"
if src.exists():
    ImageOps.mirror(Image.open(src)).save(cut / "pose03.png")
    print("pose03 mirrored")
