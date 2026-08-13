"""Crop one new photo into a People-grid portrait.

`make_people.py` rebuilds the whole roster from the old Jekyll repo's image folder, which is
no use when someone hands over a single new snapshot. This does the same crop for one file:
square, centred on the detected face, 240 px, WEBP -- so a portrait added this way is
indistinguishable from the ones the batch script produced.

    python tools/crop_portrait.py data/kimmie.jpg kimmie-shenoy

Then set that slug as the person's `img` in data/people.json and rebuild.
"""
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PORTRAITS = ROOT / "assets/people"

SIZE = 240
QUALITY = 64
TOP_BIAS = 0.36   # fallback crop centre when no face is found (0.5 = dead centre)


FACE_FRAC = 0.40  # detected face height as a fraction of the finished square


def face_box(im):
    """(x, y, w, h) of the largest detected face in pixels, or None."""
    import cv2
    cascade = cv2.CascadeClassifier(
        os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml"))
    g = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2GRAY)
    g = cv2.equalizeHist(g)
    faces = cascade.detectMultiScale(g, scaleFactor=1.08, minNeighbors=6,
                                     minSize=(max(40, g.shape[0] // 12),) * 2)
    if len(faces) == 0:
        return None
    return max(faces, key=lambda f: f[2] * f[3])


def crop(src: Path, slug: str, zoom: float = 1.0) -> Path:
    """Write assets/people/<slug>.webp.

    The crop is sized so the detected face fills FACE_FRAC of the square, which is what
    makes a one-off portrait sit evenly beside the batch ones -- the sources vary from
    tight headshots to half-body snapshots, so a fixed min(w, h) square does not.
    `zoom` > 1 tightens further; the fallback when no face is found is the old behaviour.
    """
    im = Image.open(src).convert("RGB")
    w, h = im.size
    box = face_box(im)
    if box is None:
        cx, cy, side = 0.5 * w, TOP_BIAS * h, min(w, h)
    else:
        x, y, fw, fh = box
        cx = x + fw / 2
        # aim above the face centre so the crop keeps hair, not just chin
        cy = y + fh * 0.42
        side = fh / FACE_FRAC
    side = min(min(w, h), side / zoom)
    left = max(0, min(w - side, cx - side / 2))
    top = max(0, min(h - side, cy - side / 2))
    im = im.crop((int(left), int(top), int(left + side), int(top + side)))
    im = im.resize((SIZE, SIZE), Image.LANCZOS)
    PORTRAITS.mkdir(parents=True, exist_ok=True)
    dst = PORTRAITS / f"{slug}.webp"
    im.save(dst, "WEBP", quality=QUALITY, method=6)
    print(f"  {src.name:16s} -> {dst.name:24s} {dst.stat().st_size / 1024:5.1f} KB  "
          f"{'face' if box is not None else 'FALLBACK, check it'}  zoom={zoom:g}")
    return dst


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    crop(Path(sys.argv[1]), sys.argv[2],
         float(sys.argv[3]) if len(sys.argv) > 3 else 1.0)
