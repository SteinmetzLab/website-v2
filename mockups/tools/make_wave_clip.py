"""Cut the rotating-wave panel out of the Ye et al. Science supplementary movie.

Source: papers/2023_zhiwen_spirals/spiralClip.mp4, the 2000x1600 four-panel figure movie
(brain map + traces on top, dF/F and phase maps below). For a small research card only the
phase panel is legible, and it is the one that actually shows the wave rotating, so we crop
to it -- brain plus its colour bar, dropping the timestamp and the axis caption.

Crop bounds are measured from the frames rather than hard-coded, so a re-render of the
source movie at a different size still lands correctly.

Usage:  python tools/make_wave_clip.py
"""
from pathlib import Path

import imageio
import numpy as np

SRC = Path(r"D:/Dropbox/papers/2023_zhiwen_spirals/spiralClip.mp4")
OUT = Path(__file__).resolve().parent.parent / "assets" / "clip_wave.mp4"
WIDTH = 560           # target width; height follows the crop's aspect
CRF = 30

# Fractional window on the source frame that contains the phase panel and its colour bar.
# The panel is the bottom-right quadrant. The bottom edge stops above the "phase radians"
# caption: the caption is non-black, so leaving it inside the window would pull the measured
# bounds down and leave a row of half-cut letters under the brain.
WINDOW = (0.565, 0.560, 0.955, 0.833)


def content_bounds(frames, x0, y0, x1, y1, thresh=18):
    """Tight box around non-black pixels inside the window, unioned over frames."""
    ys, xs = [], []
    for a in frames:
        sub = a[y0:y1, x0:x1]
        m = sub.max(axis=2) > thresh
        if not m.any():
            continue
        r = np.where(m.any(axis=1))[0]
        c = np.where(m.any(axis=0))[0]
        ys += [r[0], r[-1]]
        xs += [c[0], c[-1]]
    return (x0 + min(xs), y0 + min(ys), x0 + max(xs) + 1, y0 + max(ys) + 1)


def main():
    rd = imageio.get_reader(SRC)
    meta = rd.get_meta_data()
    fps = float(meta.get("fps", 30))
    frames = [np.asarray(f) for f in rd]
    h, w = frames[0].shape[:2]
    print(f"{SRC.name}: {w}x{h}, {len(frames)} frames @ {fps:g} fps")

    x0, y0, x1, y1 = (int(WINDOW[0] * w), int(WINDOW[1] * h),
                      int(WINDOW[2] * w), int(WINDOW[3] * h))
    # sample every 10th frame; the wave moves, so the union covers the whole brain
    bx0, by0, bx1, by1 = content_bounds(frames[::10], x0, y0, x1, y1)
    pad = 6
    bx0, by0 = max(0, bx0 - pad), max(0, by0 - pad)
    bx1, by1 = min(w, bx1 + pad), min(h, by1 + pad)
    print(f"crop {bx1-bx0}x{by1-by0} at ({bx0},{by0})  aspect {(bx1-bx0)/(by1-by0):.2f}")

    scale = WIDTH / (bx1 - bx0)
    ow = WIDTH - WIDTH % 2
    oh = int(round((by1 - by0) * scale)) // 2 * 2
    wr = imageio.get_writer(OUT, fps=fps, codec="libx264", macro_block_size=1,
                            ffmpeg_params=["-crf", str(CRF), "-preset", "veryslow",
                                           "-pix_fmt", "yuv420p", "-movflags", "+faststart"])
    from PIL import Image
    for a in frames:
        im = Image.fromarray(a[by0:by1, bx0:bx1]).resize((ow, oh), Image.LANCZOS)
        wr.append_data(np.asarray(im))
    wr.close()
    print(f"wrote {OUT.name}  {ow}x{oh}  {OUT.stat().st_size/1e6:.2f} MB  "
          f"{len(frames)/fps:.1f}s")


if __name__ == "__main__":
    main()
