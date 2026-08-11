"""Extract the IBL brain-wide-map movie from the BioE talk and crop it to the 3D panel.

The slide's GIF is a four-up: horizontal and sagittal projections down the left, the
off-axis whole brain on the right, and a trial timeline plus controls along the bottom.
Only the off-axis brain is wanted, so this measures where the drawn content actually sits
across every frame and crops to that, rather than to hand-guessed pixel coordinates.

Source: viz.internationalbrainlab.org -- credit the International Brain Laboratory if used.
"""
import zipfile
from pathlib import Path

import imageio
import numpy as np
from PIL import Image, ImageSequence

PPTX = Path(r"D:/Dropbox/presentations/2026-02-19_BioE/2026-02-19_BioE.pptx")
MEMBER = "ppt/media/image30.gif"
OUT = Path(__file__).resolve().parent.parent / "video"
SCRATCH = Path(r"C:/Users/nicks/AppData/Local/Temp/claude"
               r"/D--Dropbox-code-SteinmetzLabWebsite-v2/54be176e-9864-4ccd-93af-1dabcac66c72"
               r"/scratchpad")

# Region of the four-up that holds the off-axis brain: right of the two side panels and
# above the timeline strip. Content bounds are then measured inside this window.
SEARCH = dict(x0=575, x1=1920, y0=0, y1=855)
FPS = 30


def frames():
    with zipfile.ZipFile(PPTX) as z:
        raw = z.read(MEMBER)
    p = SCRATCH / "ibl.gif"
    p.write_bytes(raw)
    im = Image.open(p)
    durs, out = [], []
    for f in ImageSequence.Iterator(im):
        durs.append(f.info.get("duration", 70))
        out.append(np.asarray(f.convert("RGB")))
    return out, float(np.median(durs))


def main():
    fr, dur_ms = frames()
    H, W, _ = fr[0].shape
    print(f"{len(fr)} frames, {W}x{H}, {dur_ms:.0f} ms/frame -> {len(fr)*dur_ms/1000:.2f}s")

    win = np.stack([f[SEARCH["y0"]:SEARCH["y1"], SEARCH["x0"]:SEARCH["x1"]] for f in fr])
    lum = win.max(axis=0).max(axis=2)          # brightest each pixel ever gets
    on = lum > 18                               # anything meaningfully above the black bg
    ys, xs = np.where(on)
    pad = 18
    x0 = SEARCH["x0"] + max(0, xs.min() - pad)
    x1 = SEARCH["x0"] + min(win.shape[2], xs.max() + pad)
    y0 = SEARCH["y0"] + max(0, ys.min() - pad)
    y1 = SEARCH["y0"] + min(win.shape[1], ys.max() + pad)
    # even dimensions for h264
    x1 -= (x1 - x0) % 2
    y1 -= (y1 - y0) % 2
    print(f"content crop: x {x0}-{x1}  y {y0}-{y1}  ({x1-x0}x{y1-y0})")

    # resample the GIF's timing onto a standard 30 fps, preserving duration
    dur_s = len(fr) * dur_ms / 1000
    n_out = int(round(dur_s * FPS))
    idx = np.clip((np.arange(n_out) / FPS * 1000 / dur_ms).astype(int), 0, len(fr) - 1)

    OUT.mkdir(exist_ok=True)
    path = OUT / "ibl-brainwide.mp4"
    w = imageio.get_writer(path, fps=FPS, codec="libx264", macro_block_size=1,
                           ffmpeg_params=["-crf", "20", "-preset", "slow",
                                          "-pix_fmt", "yuv420p"])
    for i in idx:
        w.append_data(fr[i][y0:y1, x0:x1])
    w.close()
    print(f"wrote {path}  {n_out} frames  {dur_s:.2f}s  {path.stat().st_size/1e6:.1f} MB")

    Image.fromarray(fr[len(fr) // 3][y0:y1, x0:x1]).save(SCRATCH / "ibl_crop_check.png")
    print("wrote ibl_crop_check.png")


if __name__ == "__main__":
    main()
