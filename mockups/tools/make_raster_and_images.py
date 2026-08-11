"""Pack real raster into a compact base64 asset + downscale hero imagery to web sizes."""
import base64
import json
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(__file__).parent
PUZ = Path(r"D:/Dropbox/uw/puzzles")

# ---------------------------------------------------------------- raster -> base64
d = json.loads((OUT / "raster_real.json").read_text())
t_ms = np.asarray(d["t_ms"], dtype=np.int64)
row = np.asarray(d["row"], dtype=np.int64)
depth = np.asarray(d["depth"], dtype=np.float64)

o = np.argsort(t_ms, kind="stable")
t_ms, row = t_ms[o], row[o]

BIN = 2  # ms per bin -> 90 s = 45000 bins, fits uint16
tb = np.clip(t_ms // BIN, 0, 65535).astype(np.uint16)
rb = row.astype(np.uint8)
assert row.max() < 256, row.max()

asset = {
    "meta": d["meta"] | {"bin_ms": BIN},
    "depth": [round(float(x), 1) for x in depth],
    "t": base64.b64encode(tb.tobytes()).decode("ascii"),
    "r": base64.b64encode(rb.tobytes()).decode("ascii"),
}
p = OUT / "raster_b64.json"
p.write_text(json.dumps(asset, separators=(",", ":")))
print("raster_b64.json", round(p.stat().st_size / 1024, 1), "KB",
      "| neurons", len(depth), "| spikes", len(tb))

# ---------------------------------------------------------------- images
# (name, source, crop fractions (l,t,r,b) to remove the burned-in logo, target width, quality)
JOBS = [
    ("hero_raster",  "raster1.png",   (0.00, 0.00, 1.00, 0.86), 1600, 60),
    ("hero_wf",      "wf_edit.png",   (0.00, 0.14, 1.00, 1.00), 1200, 62),
    ("hero_ibl",     "IBL1.png",      (0.00, 0.13, 1.00, 1.00), 1500, 62),
    ("fig_mrf",      "MRF2.png",      (0.00, 0.00, 1.00, 0.87), 1200, 68),
    ("fig_spiral",   "Spiral1.png",   (0.00, 0.09, 1.00, 1.00), 1000, 66),
    ("fig_collman",  "collman2.png",  (0.00, 0.00, 1.00, 1.00), 1100, 62),
    ("fig_martin",   "purple_martinotti_10.webp", (0.0, 0.0, 1.0, 1.0), 1100, 62),
]

Image.MAX_IMAGE_PIXELS = None
for name, src, (l, t, r, b), w, q in JOBS:
    p = PUZ / src
    if not p.exists():
        print("MISSING", src)
        continue
    im = Image.open(p).convert("RGB")
    W, H = im.size
    im = im.crop((int(l * W), int(t * H), int(r * W), int(b * H)))
    scale = w / im.width
    im = im.resize((w, max(1, round(im.height * scale))), Image.LANCZOS)
    out = OUT / f"{name}.webp"
    im.save(out, "WEBP", quality=q, method=6)
    kb = out.stat().st_size / 1024
    print(f"{name:14s} {im.width}x{im.height}  {kb:7.1f} KB   (b64 ~{kb*1.34:.0f} KB)")
