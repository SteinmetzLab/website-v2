"""Render the 1,745-neuron wall as a standalone movie for slides.

The a2-array.html page draws this raster in a canvas you scroll by hand. A talk needs the
same thing on a timer, so this replays it: hold at the top while the raster sweeps, then
walk down the wall from the first neuron to the last while it keeps sweeping, then hold at
the bottom. The time axis runs in real time throughout -- one second of recording per
second of video -- so the spike rates you see are the rates that were recorded.

Data comes from the full export (D:/temp/np2web/units.npz, 120 s), not from the 30 s
window packed into static/np2_spikes.bin, so nothing has to loop.

Display order matches tools/make_np2.py exactly: probe, then shank, then y along the shank
descending. `meta[:, 2]` is the median of Kilosort's spike_positions y, i.e. micrometres
along the shank measured from the bottom of the channel map, increasing toward the brain
surface -- so walking down the movie walks down into the brain.

    python tools/make_np2_movie.py                  # 5 s hold, 30 s scroll, 5 s hold
    python tools/make_np2_movie.py --scroll 45      # slower walk down the wall
    python tools/make_np2_movie.py --span 4         # narrower time window, faster drift
    python tools/make_np2_movie.py --preview 6      # stills instead, to check the layout

Output: video/np2_wall_1745.mp4 (H.264 / yuv420p, no audio), which is what Google Drive
wants for Insert > Video in Slides.
"""
import argparse
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import imageio

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(r"D:/temp/np2web/units.npz")
OUT_DIR = ROOT / "video"
PALETTES = ROOT / "src/partials/palettes.css"

# ---- geometry ---------------------------------------------------------------------
W, H = 1920, 1080
SS = 2                      # supersample factor; dots and the scroll are anti-aliased
FPS = 30
ROW = 3.4                   # px per neuron, the spacing a2-array.html uses
SPAN_S = 8.0                # default seconds of recording across the frame, as on the page
SPEED = 1.0                 # real time: seconds of data per second of video
DOT_W = 2                   # px at 1x

FONT_DIR = Path(r"C:/Windows/Fonts")


def palette(name: str = "teal") -> dict:
    """The site's own palette tokens, so the movie matches the page it comes from."""
    css = PALETTES.read_text(encoding="utf-8")
    m = re.search(r'\[data-palette="%s"\]\s*\{(.*?)\}' % name, css, re.S)
    if not m:
        raise SystemExit(f"palette {name!r} not found in {PALETTES.name}")
    return dict(re.findall(r"--([\w-]+):\s*([^;]+);", m.group(1)))


def rgb(h: str) -> np.ndarray:
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.uint8)


def shank_shades(pal: dict, faithful: bool = False) -> np.ndarray:
    """(3 probes, 4 shanks, 3) uint8 -- one color family per probe, one shade per shank.

    a2-array.html walks the four shanks down to 0.42 of the probe's color with almost no
    white mixed back in. On a bright screen a foot away that is a clean ramp; projected in
    a lit room the darkest two shanks of every probe fall to something like rgb(17 86 73)
    and simply vanish, and probe 02's family -- already the neutral one -- goes with them.
    So the movie keeps the same hues and the same brightest-shank-first ordering but
    compresses the ramp and mixes toward white rather than black, which holds all twelve
    shades above the projector's floor. Pass faithful=True to reproduce the page exactly.
    """
    base = [rgb(pal["accent"]), rgb(pal["accent-2"]), rgb(pal["di-2"])]
    f, lift = ([1.0, 0.78, 0.58, 0.42], 0.06) if faithful \
        else ([1.0, 0.84, 0.70, 0.57], 0.26)
    out = np.zeros((3, 4, 3), np.uint8)
    for p, c in enumerate(base):
        for s, k in enumerate(f):
            out[p, s] = np.clip(np.round(c.astype(float) * k + 255 * (1 - k) * lift), 0, 255)
    return out


def load_units():
    """Spikes and metadata in display order, plus a time-sorted spike index."""
    if not SRC.exists():
        raise SystemExit(f"{SRC} not found -- it is the 120 s export web_export.py writes.")
    z = np.load(SRC)
    meta, row, t_ms = z["meta"], z["row"], z["t_ms"]

    probe, shank, depth = meta[:, 0], meta[:, 1], meta[:, 2]
    order = np.lexsort((-depth, shank, probe))     # identical to make_np2.py
    rank = np.empty(len(meta), np.int64)
    rank[order] = np.arange(len(meta))

    row = rank[row]                                 # spikes now index display position
    srt = np.argsort(t_ms, kind="stable")
    return dict(
        meta=meta[order],
        n=len(meta),
        t_sorted=t_ms[srt].astype(np.float64),
        r_sorted=row[srt].astype(np.int64),
        dur_ms=float(t_ms.max()),
    )


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def scroll_track(n_frames, hold_s, scroll_s, ease_s, max_scroll):
    """Rows scrolled per frame: still, then a trapezoidal ramp down the wall, then still.

    A trapezoid rather than a single ease over the whole descent -- an ease-everywhere
    profile makes the middle of the wall race past and the two ends crawl, which reads as
    an accident. Easing only the first and last `ease_s` keeps one honest constant speed
    for the bulk of it and still starts and stops without a jerk.
    """
    t = np.arange(n_frames) / FPS
    v = np.zeros(n_frames)
    a, b = hold_s, hold_s + scroll_s
    inside = (t >= a) & (t < b)
    u = t[inside] - a
    v[inside] = smoothstep(u / ease_s) * smoothstep((scroll_s - u) / ease_s)
    pos = np.cumsum(v) / FPS
    if pos[-1] > 0:
        pos *= max_scroll / pos[-1]                 # land exactly on the last neuron
    return np.minimum(pos, max_scroll)


# ---- text -------------------------------------------------------------------------

def fonts():
    """The readout sits at one size; only the shank labels and key step down from it.

    The three readout lines are deliberately the same size as each other -- a big headline
    over small detail turns the overlay into the subject, and the subject is the wall.
    """
    def f(name, size):
        return ImageFont.truetype(str(FONT_DIR / name), size)
    return dict(
        head=f("arialbd.ttf", 22),
        body=f("arial.ttf", 22),
        key=f("arial.ttf", 18),
    )


def text_w(draw, s, font):
    try:
        return draw.textbbox((0, 0), s, font=font)[2]
    except AttributeError:               # Pillow < 8
        return draw.textsize(s, font=font)[0]


def scrims():
    """Soft darkening under the three places text sits, so it stays readable.

    Combined with maximum() rather than a sum: where two scrims overlap a sum would
    double the darkening and leave a visible seam along the join.
    """
    xs, ys = np.arange(W), np.arange(H)
    left = 1.0 - smoothstep((xs - 380) / 260.0)
    narrow = 1.0 - smoothstep((xs - 290) / 300.0)
    right = smoothstep((xs - (W - 450)) / 310.0)
    top = 1.0 - smoothstep((ys - 130) / 130.0)
    bottom = smoothstep((ys - (H - 250)) / 190.0)

    sc = np.zeros((H, W))
    sc = np.maximum(sc, 0.86 * top[:, None] * left[None, :])       # the readout
    sc = np.maximum(sc, 0.92 * bottom[:, None] * narrow[None, :])  # the probe key
    sc = np.maximum(sc, 0.64 * np.ones((H, 1)) * right[None, :])   # the shank labels
    return sc[..., None]


def headline(ps, blocks):
    """Colored segments naming the shanks on screen.

    A frame holds ~318 of the 1,745 rows and the shanks run 26-248 units, so two to four
    of them are usually in view at once. Naming only the topmost row's shank -- what the
    page's own HUD does -- would be quietly wrong for most of the descent.
    """
    p0, s0 = ps[blocks[0][0]]
    p1, s1 = ps[blocks[-1][0]]
    if len(blocks) == 1:
        return [(f"Probe {p0:02d} \u00b7 Shank {s0}", (p0, s0))]
    if p0 == p1:
        return [(f"Probe {p0:02d} \u00b7 Shanks {s0}\u2013{s1}", (p0, s0))]
    return [(f"Probe {p0:02d} Shank {s0}", (p0, s0)), ("  \u2192  ", None),
            (f"Probe {p1:02d} Shank {s1}", (p1, s1))]


def render(args):
    pal = palette(args.palette)
    span_s = args.span
    shades = shank_shades(pal, args.faithful)
    deep = rgb(pal["deep"])
    ink, ink2, ink3 = rgb(pal["di"]), rgb(pal["di-2"]), rgb(pal["di-3"])
    u = load_units()
    n = u["n"]

    visible = int(np.ceil(H / ROW))
    max_scroll = max(0, n - visible)
    n_frames = int(round((2 * args.hold + args.scroll) * FPS))
    pos = scroll_track(n_frames, args.hold, args.scroll, args.ease, max_scroll)

    span_ms = span_s * 1000
    need_ms = n_frames / FPS * SPEED * 1000 + span_ms
    if need_ms > u["dur_ms"]:
        raise SystemExit(f"need {need_ms/1000:.0f} s of data, export holds "
                         f"{u['dur_ms']/1000:.0f} s -- shorten --scroll")

    # per-unit color, in display order
    ps = u["meta"][:, :2].astype(int)
    row_col = shades[ps[:, 0], ps[:, 1]]

    # contiguous runs of one (probe, shank): the twelve blocks the descent walks through
    kk = ps[:, 0] * 4 + ps[:, 1]
    bstart = np.r_[0, np.where(np.diff(kk) != 0)[0] + 1]
    bend = np.r_[bstart[1:], n]

    # ---- 2x buffers -----------------------------------------------------------
    Wb, Hb = W * SS, H * SS
    rowb, dotw = ROW * SS, DOT_W * SS
    doth = max(1, int(round(rowb * 0.8)))
    bg = np.empty((Hb, Wb, 3), np.uint8)
    bg[:] = deep
    dy = np.arange(doth)[None, :, None]
    dx = np.arange(dotw)[None, None, :]
    reps = doth * dotw

    # ---- overlay furniture ----------------------------------------------------
    fnt = fonts()
    sc = scrims()

    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / args.name

    # --preview writes a handful of stills instead of the movie, which is the cheap way
    # to check the overlay against real spikes before paying for 1,200 frames.
    todo = range(n_frames)
    writer = None
    if args.preview:
        todo = [int(round(f * (n_frames - 1))) for f in
                np.linspace(0, 1, args.preview)]
    else:
        # crf 27 rather than the 18-20 the other renderers use. This frame is mostly flat
        # ground with a few thousand 2 px dots on it, and at 1:1 the two are not tellable
        # apart -- but 40 s at crf 18 is 67 MB and at 27 it is 22 MB, which is the
        # difference between a file you can mail and one you cannot.
        writer = imageio.get_writer(
            path, fps=FPS, codec="libx264", macro_block_size=1,
            ffmpeg_params=["-crf", str(args.crf), "-preset", "slow", "-pix_fmt", "yuv420p",
                           "-movflags", "+faststart"])

    for i in todo:
        t0 = i * (1000.0 / FPS) * SPEED
        scroll = pos[i]
        first = int(np.floor(scroll))
        nrows = min(n - first, visible + 2)

        lo, hi = np.searchsorted(u["t_sorted"], [t0, t0 + span_ms])
        rows = u["r_sorted"][lo:hi]
        keep = (rows >= first) & (rows < first + nrows)
        rows = rows[keep]
        tm = u["t_sorted"][lo:hi][keep] - t0

        frame = bg.copy()
        if len(rows):
            px = np.clip((tm / span_ms * Wb).astype(np.int64), 0, Wb - dotw)
            py = np.clip(((rows - scroll) * rowb).astype(np.int64), 0, Hb - doth)
            flat = ((py[:, None, None] + dy) * Wb + (px[:, None, None] + dx)).ravel()
            frame.reshape(-1, 3)[flat] = np.repeat(row_col[rows], reps, axis=0)

        img = Image.fromarray(frame).resize((W, H), Image.BOX)
        a = np.asarray(img).astype(np.float32) * (1.0 - sc)
        img = Image.fromarray(a.astype(np.uint8))
        d = ImageDraw.Draw(img)

        # ---- the readout, upper left -----------------------------------------
        last = first + nrows
        blocks = [(bs, be) for bs, be in zip(bstart, bend) if be > first and bs < last]
        x, y = 56, 48
        for part, k in headline(ps, blocks):
            col = tuple(int(v) for v in (shades[k[0], k[1]] if k else ink3))
            d.text((x, y), part, font=fnt["head"], fill=col)
            x += text_w(d, part, fnt["head"])
        y += 32
        d.text((56, y), f"Neurons {first + 1:,}\u2013{last:,} of {n:,}",
               font=fnt["body"], fill=tuple(int(v) for v in ink))
        y += 32
        d.text((56, y), f"t = {t0 / 1000:.1f} s", font=fnt["body"],
               fill=tuple(int(v) for v in ink2))

        # ---- one label per shank on screen, right edge ------------------------
        # The depth span belongs to a shank, not to the frame: each shank is a full pass
        # from the top of the recorded band down to the tip, so a single top-to-bottom
        # range across a frame that holds three of them would mean nothing.
        ylast = -1e9
        for bs, be in blocks:
            vs, ve = max(bs, first), min(be, last) - 1
            col = tuple(int(v) for v in shades[ps[bs, 0], ps[bs, 1]])
            yb = (bs - scroll) * ROW
            if 0 < yb < H:                       # rule where this shank starts
                dim = tuple(int(v * 0.62 + int(deep[j]) * 0.38) for j, v in enumerate(col))
                d.line([(0, yb), (W - 60, yb)], fill=dim, width=1)
            # A shank whose boundary sits just under the frame edge would otherwise print
            # on top of the one above it, since both clamp to the same y. Push each label
            # clear of the last, and give up on slivers too thin to be worth naming.
            if ve - vs + 1 < 8:
                continue
            ty = max(int(min(max(yb, 10), H - 56)), int(ylast + 48))
            if ty > H - 56:
                continue
            lab = f"Probe {ps[bs, 0]:02d} \u00b7 Shank {ps[bs, 1]}"
            sub = f"{u['meta'][vs, 2]:,.0f}\u2013{u['meta'][ve, 2]:,.0f} \u00b5m along shank"
            d.text((W - 42 - text_w(d, lab, fnt["key"]), ty), lab,
                   font=fnt["key"], fill=col)
            d.text((W - 42 - text_w(d, sub, fnt["key"]), ty + 22), sub,
                   font=fnt["key"], fill=tuple(int(v) for v in ink3))
            ylast = ty

        # ---- probe key, lower left -------------------------------------------
        # No progress bar anywhere: how far down the wall you are is exactly the thing
        # the movie should not advertise -- the point is that it keeps going.
        ky = H - 148
        d.text((56, ky), "Shank", font=fnt["key"], fill=tuple(int(v) for v in ink3))
        for s in range(4):
            d.text((146 + s * 32, ky), str(s), font=fnt["key"],
                   fill=tuple(int(v) for v in ink3))
        ky += 28
        for p in range(3):
            d.text((56, ky), f"Probe {p:02d}", font=fnt["key"],
                   fill=tuple(int(v) for v in ink3))
            for s in range(4):
                x0 = 140 + s * 32
                d.rectangle([x0, ky + 5, x0 + 24, ky + 12],
                            fill=tuple(int(v) for v in shades[p, s]))
            ky += 28

        arr = np.asarray(img)
        if writer is None:
            q = OUT_DIR / f"preview_{i:04d}.png"
            img.save(q)
            print(f"  {q.name}  t={t0/1000:5.1f}s  neuron {first + 1:,}")
            continue
        writer.append_data(arr)
        if i % 60 == 0:
            print(f"  frame {i:4d}/{n_frames}  t={t0/1000:5.1f}s  "
                  f"neuron {first + 1:5,}", flush=True)

    if writer is None:
        return None
    writer.close()
    print(f"\n{path}")
    print(f"  {n_frames} frames, {n_frames / FPS:.1f} s, {W}x{H} @ {FPS} fps, "
          f"{path.stat().st_size / 1e6:.1f} MB")
    return path


def main(argv):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--hold", type=float, default=5.0, help="still seconds at each end")
    p.add_argument("--scroll", type=float, default=30.0, help="seconds to walk the wall")
    p.add_argument("--ease", type=float, default=1.5, help="ramp in/out of the scroll")
    p.add_argument("--span", type=float, default=SPAN_S,
                   help="seconds of recording across the frame width; the time axis stays "
                        "real time either way, a wider span just slows the leftward drift")
    p.add_argument("--crf", type=int, default=27,
                   help="x264 quality, lower is bigger; 18 for a master to re-encode from")
    p.add_argument("--palette", default="teal")
    p.add_argument("--name", default="np2_wall_1745.mp4")
    p.add_argument("--preview", type=int, default=0,
                   help="write N stills spread over the run instead of the movie")
    p.add_argument("--faithful", action="store_true",
                   help="use the page's exact shank shades, dark ends and all")
    render(p.parse_args(argv))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
