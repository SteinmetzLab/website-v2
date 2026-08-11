"""Build the People section's portraits and render manifest.

Roster comes from `data/people.json` (this project's own file, reconciled from Nick's roster
table and the CV). Photographs are still pulled from the old Jekyll repo's
`assets/img/people/`, cropped square with an upward bias since those are landscape portraits
and the face sits above centre. Members with no photo get `img: null` and the page falls back
to a monogram tile.

Writes:
    assets/people.json          name / role / url / image filename, in display order
    assets/people/<slug>.webp   240 px square portraits
    tools/people_check.png      contact sheet, to confirm nothing is badly cropped
"""
import json
import os
import time

import numpy as np
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

OLD = Path(r"D:/Dropbox/code/SteinmetzLab.github.io")
OUT = Path(__file__).resolve().parent.parent / "assets"
PORTRAITS = OUT / "people"

SIZE = 240
QUALITY = 64
TOP_BIAS = 0.36   # fallback crop centre when no face is found (0.5 = dead centre)

_CASCADE = None


def face_centre(im):
    """Centre of the largest detected face, as (fx, fy) fractions of the image.

    Falls back to (0.5, TOP_BIAS) when detection fails -- these are ordinary snapshots,
    not passport photos, so a few will not resolve and the old heuristic is fine there.
    """
    global _CASCADE
    import cv2
    if _CASCADE is None:
        _CASCADE = cv2.CascadeClassifier(
            os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml"))
    g = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2GRAY)
    g = cv2.equalizeHist(g)
    faces = _CASCADE.detectMultiScale(g, scaleFactor=1.08, minNeighbors=6,
                                      minSize=(max(40, g.shape[0] // 12),) * 2)
    if len(faces) == 0:
        return 0.5, TOP_BIAS, False
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    # aim a little above the face centre so the crop keeps hair and not just chin
    return (x + w / 2) / g.shape[1], (y + h * 0.42) / g.shape[0], True

ROSTER = Path(__file__).resolve().parent.parent / "data/people.json"
# Display order: PI, then staff, then each cohort in seniority (join-date) order.
GROUP_ORDER = ["pi", "staff", "postdoc", "grad", "undergrad", "highschool"]

active = json.loads(ROSTER.read_text(encoding="utf-8"))["person"]
unknown = {p.get("group") for p in active} - set(GROUP_ORDER)
if unknown:
    raise SystemExit(f"unknown group(s) in {ROSTER.name}: {sorted(unknown)}")
active.sort(key=lambda p: (GROUP_ORDER.index(p["group"]), p.get("joined", "9999")))
print(f"{len(active)} current members from {ROSTER.name}")

# The tree lives inside Dropbox, which intermittently holds handles on files it is syncing.
# Clear stale outputs file-by-file and retry writes rather than removing the directory.
PORTRAITS.mkdir(parents=True, exist_ok=True)
for old in PORTRAITS.glob("*.webp"):
    try:
        old.unlink()
    except OSError as e:
        print(f"  (could not remove {old.name}: {e})")


def save_retry(im, dst, attempts=5):
    for i in range(attempts):
        try:
            im.save(dst, "WEBP", quality=QUALITY, method=6)
            return True
        except OSError:
            if i == attempts - 1:
                raise
            time.sleep(0.4)
    return False

def slug(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")


records, thumbs, detected = [], [], []
for p in active:
    stem = p.get("img")
    src = None
    # A null img (or the old site's "noPhoto" placeholder) falls back to a monogram tile,
    # which looks deliberate rather than like a missing asset.
    if stem and stem != "noPhoto":
        for cand in (f"{stem}.jpg", f"{stem}_md.jpg", f"{stem}.jpeg", f"{stem}.png"):
            q = OLD / "assets/img/people" / cand
            if q.exists():
                src = q
                break
    if src is None:
        print(f"  -- no photo for {p['name']} (img={stem!r}) - monogram")
        records.append({"name": p["name"], "role": p["role"], "url": p.get("url", ""),
                        "group": p["group"], "joined": p.get("joined", ""), "img": None})
        continue
    stem = slug(p["name"])   # key the output on the person, so shared source files can't collide

    im = Image.open(src).convert("RGB")
    w, h = im.size
    side = min(w, h)
    fx, fy, found = face_centre(im)
    left = max(0, min(w - side, fx * w - side / 2))
    top = max(0, min(h - side, fy * h - side / 2))
    im = im.crop((int(left), int(top), int(left) + side, int(top) + side))
    im = im.resize((SIZE, SIZE), Image.LANCZOS)
    dst = PORTRAITS / f"{stem}.webp"
    save_retry(im, dst)
    detected.append(found)
    records.append({"name": p["name"], "role": p["role"], "url": p.get("url", ""),
                    "group": p["group"], "joined": p.get("joined", ""), "img": stem})
    thumbs.append((p["name"], im))
    print(f"  {p['name']:22s} {src.name:22s} -> {dst.name} "
          f"{dst.stat().st_size / 1024:.1f} KB  {'face' if found else 'FALLBACK'}")

(OUT / "people.json").write_text(json.dumps(records, indent=1), encoding="utf-8")
total = sum(f.stat().st_size for f in PORTRAITS.glob("*.webp"))
print(f"faces detected: {sum(detected)}/{len(detected)}")
print(f"wrote {len(records)} records, {total / 1024:.0f} KB of portraits "
      f"(~{total * 1.34 / 1024:.0f} KB base64)")

cols = 6
rows = -(-len(thumbs) // cols)
fig, axs = plt.subplots(rows, cols, figsize=(2 * cols, 2.25 * rows), dpi=100)
for ax, (name, im) in zip(axs.ravel(), thumbs):
    ax.imshow(im)
    ax.set_title(name, fontsize=7)
    ax.axis("off")
for ax in axs.ravel()[len(thumbs):]:
    ax.axis("off")
fig.tight_layout()
fig.savefig(Path(__file__).resolve().parent / "people_check.png", facecolor="white")
print("wrote tools/people_check.png")
