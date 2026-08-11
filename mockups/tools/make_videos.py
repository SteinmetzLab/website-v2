"""Render the two live panels from mockup A as shareable MP4s, one per palette.

Reproduces the page's own rendering -- same exported recordings, same colour ramps parsed
straight out of src/partials/palettes.css, same geometry as the CSS -- rather than
screen-capturing a browser, so the output is clean and deterministic.

    video/widefield-<palette>.mp4   the "Twenty-six seconds of mouse cortex" panel,
                                    including the HUD readout and the trace beneath it
    video/raster-<palette>.mp4      the hero raster in sweep mode, no page text

Usage:  python tools/make_videos.py [palette ...]
"""
from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

import imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
OUT = ROOT / "video"
MONO = ROOT / "tools/_fontcache/IBMPlexMono-Regular.ttf"

FPS = 30
PALETTES = ["indigo", "plasma", "teal", "atlas"]

# ---------------------------------------------------------------- palette parsing
def load_palettes() -> dict[str, dict[str, str]]:
    css = (ROOT / "src/partials/palettes.css").read_text(encoding="utf-8")
    out: dict[str, dict[str, str]] = {}
    for m in re.finditer(r'\[data-palette="(\w+)"\]\s*\{(.*?)\}', css, re.S):
        name, body = m.group(1), m.group(2)
        out[name] = {k: v.strip() for k, v in re.findall(r"--([\w-]+):\s*([^;]+);", body)}
    return out


def rgb(h: str) -> tuple[int, int, int]:
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def ramp_lut(pal: dict, n: int = 256) -> np.ndarray:
    """256x3 uint8 LUT across the palette ramp, matching rampLUT() in engine.js.

    Normally that is --d0..--d4 from the CSS; a variant may instead supply `_stops`,
    an arbitrary-length list of hex colours (used by the diverging colourmap tests)."""
    stops_hex = pal.get("_stops") or [pal[f"d{i}"] for i in range(5)]
    stops = np.array([rgb(h) for h in stops_hex], dtype=np.float64)
    seg = len(stops) - 1
    x = np.linspace(0, seg, n)
    j = np.clip(x.astype(int), 0, seg - 1)
    f = (x - j)[:, None]
    return (stops[j] * (1 - f) + stops[j + 1] * f).round().astype(np.uint8)


# ---------------------------------------------------------------- data loading
def b64arr(s: str, dtype) -> np.ndarray:
    return np.frombuffer(base64.b64decode(s), dtype=dtype)


def load_widefield():
    j = json.loads((ASSETS / "widefield_b64.json").read_text())
    H, W = j["meta"]["px"]
    K, T = j["meta"]["n_components"], j["meta"]["n_frames"]
    U = b64arr(j["U"], np.int8).astype(np.float32).reshape(K, H, W)
    U *= np.asarray(j["u_scale"], dtype=np.float32)[:, None, None] / 127.0
    V = b64arr(j["V"], np.int16).astype(np.float32).reshape(T, K)
    V *= np.asarray(j["v_scale"], dtype=np.float32)[None, :] / 32000.0
    return dict(U=U, V=V, H=H, W=W, K=K, T=T, limit=j["meta"]["limit"], fps=j["meta"]["fps"])


def load_raster():
    j = json.loads((ASSETS / "raster_b64.json").read_text())
    t = b64arr(j["t"], np.uint16).astype(np.int64) * j["meta"]["bin_ms"]
    return dict(t_ms=t, row=b64arr(j["r"], np.uint8).astype(np.int64),
                n=j["meta"]["n_neurons"], dur_ms=int(j["meta"]["duration_s"] * 1000))


# ---------------------------------------------------------------- widefield panel
def render_widefield(pal_name: str, pal: dict, wf: dict, out_name: str | None = None) -> Path:
    lut = ramp_lut(pal)
    P, G, TR = 14, 12, 52                    # padding / gap / trace height, from the CSS
    Wp, Hp = 752, 816
    S = Wp - 2 * P                            # square stage
    assert P + S + G + TR + P == Hp

    deep, dark, drule = rgb(pal["deep"]), rgb(pal["dark"]), rgb(pal["drule"])
    di, di2 = rgb(pal["di"]), rgb(pal["di-2"])

    U2 = wf["U"].reshape(wf["K"], -1)
    gain, lim = 1.35, wf["limit"]
    lim_eff = lim / gain

    # mean over the frame, per frame -- the trace, exactly as mockup A computes it
    u_mean = U2.mean(axis=1)
    trace = wf["V"] @ u_mean
    lo, hi = trace.min(), trace.max()
    pad = (hi - lo) * 0.12 or 1.0
    lo, hi = lo - pad, hi + pad

    font = ImageFont.truetype(str(MONO), 13)
    label = "dorsal cortex · dF/F"

    # sample the 35.09 Hz recording onto a 30 fps timeline, keeping real-time duration
    dur_s = wf["T"] / wf["fps"]
    n_out = int(round(dur_s * FPS))
    src_idx = np.clip((np.arange(n_out) / FPS * wf["fps"]).round().astype(int), 0, wf["T"] - 1)

    # "rectify": the alternative fix -- instead of recolouring, shift each pixel so its own
    # 5th-percentile over the window sits at zero, then run a plain black-to-bright ramp.
    # Included for comparison; it makes the edges black but gives every pixel its own
    # baseline, which is not something we would do in analysis.
    rect = pal.get("_rectify", False)
    # "demean": subtract each frame's own spatial mean. This data is dominated by a global
    # up/down state that moves the whole cortex together, so a diverging map still lights
    # the entire frame. Removing the common signal leaves regional structure hovering about
    # zero -- which is what a black-centred ramp needs, and is a defensible thing to show.
    demean = pal.get("_demean", False)
    pix_base = rng = lim_div = None
    if rect or demean:
        allf = (U2.T @ wf["V"].T)                      # (H*W, T)
        if rect:
            pix_base = np.percentile(allf, 5, axis=1)
            rng = float(np.percentile(allf - pix_base[:, None], 99.5))
        else:
            lim_div = float(np.percentile(np.abs(allf - allf.mean(axis=0)), 99.5)) / gain
        del allf

    OUT.mkdir(exist_ok=True)
    path = OUT / f"{out_name or 'widefield-' + pal_name}.mp4"
    writer = imageio.get_writer(path, fps=FPS, codec="libx264", macro_block_size=1,
                               ffmpeg_params=["-crf", "20", "-preset", "slow",
                                              "-pix_fmt", "yuv420p"])

    # static background: panel fill + 1px border
    base = np.empty((Hp, Wp, 3), np.uint8)
    base[:] = dark
    base[0, :] = base[-1, :] = base[:, 0] = base[:, -1] = drule
    base[P:P + S, P:P + S] = deep

    # trace geometry
    ty0, ty1 = P + S + G, P + S + G + TR
    tx = np.linspace(0, S - 1, wf["T"])
    tyv = (TR - 1) * (1 - (trace - lo) / (hi - lo)) + ty0

    for out_i, t in enumerate(src_idx):
        frame = base.copy()

        # --- cortex ---------------------------------------------------------
        px = (wf["V"][t] @ U2)
        if rect:
            x = np.clip((px - pix_base) / rng, 0, 1)
        elif demean:
            x = np.clip(((px - px.mean()) / lim_div + 1) * 0.5, 0, 1)
        else:
            x = np.clip((px / lim_eff + 1) * 0.5, 0, 1)
        x = x.reshape(wf["H"], wf["W"])
        img = lut[(x * 255).astype(np.uint8)]
        big = np.asarray(Image.fromarray(img).resize((S, S), Image.BILINEAR))
        frame[P:P + S, P:P + S] = big

        # --- trace: fill under the curve, then the line ---------------------
        fill_c = np.asarray(lut[200], np.float32)
        line_c = lut[210]
        col = np.clip(np.interp(np.arange(S), tx, tyv), ty0, ty1 - 1).astype(int)
        for xx in range(S):
            y = col[xx]
            seg = frame[y:ty1, P + xx].astype(np.float32)
            a = np.linspace(0.32, 0.0, max(1, ty1 - y))[:, None]
            frame[y:ty1, P + xx] = (seg * (1 - a) + fill_c * a).astype(np.uint8)
            frame[max(ty0, y - 1):y + 1, P + xx] = line_c

        # --- cursor on the trace -------------------------------------------
        cx = P + int(round((t / (wf["T"] - 1)) * (S - 1)))
        cur = np.asarray(lut[250], np.float32)
        blend = frame[ty0:ty1, cx].astype(np.float32) * 0.1 + cur * 0.9
        frame[ty0:ty1, cx] = blend.astype(np.uint8)

        # --- HUD: scrim, then the two readouts ------------------------------
        band = 46
        y0 = P + S - band
        sc = np.linspace(0.72, 0.0, band)[:, None, None]
        frame[y0:P + S, P:P + S] = (frame[y0:P + S, P:P + S] * (1 - sc)).astype(np.uint8)

        pil = Image.fromarray(frame)
        d = ImageDraw.Draw(pil)
        ty = P + S - 22
        d.text((P + 12, ty), label, font=font, fill=di2)
        secs = f"{t / wf['fps']:.2f} s"
        d.text((P + S - 12 - d.textlength(secs, font=font), ty), secs, font=font, fill=di)

        writer.append_data(np.asarray(pil))

    writer.close()
    print(f"  {path.name}  {n_out} frames  {dur_s:.1f}s  {path.stat().st_size/1e6:.1f} MB")
    return path


# ---------------------------------------------------------------- hero raster
def render_raster(pal_name: str, pal: dict, rs: dict, cycles: float = 2.0) -> Path:
    lut = ramp_lut(pal)
    Wv, Hv = 1600, 896
    deep, accent = rgb(pal["deep"]), rgb(pal["accent"])

    SPAN_S, SPEED = 9.0, 0.85          # as passed to SL.raster in mockup A
    SHADE_LO, SHADE_HI = 118, 255
    DOT_W, PAD = 2, 0.04

    top = int(Hv * PAD)
    usable = Hv * (1 - 2 * PAD)
    row_h = usable / rs["n"]
    dot_h = max(1, int(round(row_h * 0.82)))
    span_ms = SPAN_S * 1000

    # per-neuron colour, from its depth position along the probe
    shade = (SHADE_LO + (np.arange(rs["n"]) / rs["n"]) * (SHADE_HI - SHADE_LO)).astype(int)
    row_col = lut[np.clip(shade, 0, 255)]

    # vertical mask, matching the canvas's CSS mask-image
    ys = np.arange(Hv) / Hv
    vmask = np.clip(np.interp(ys, [0.0, 0.22, 0.72, 1.0], [0.0, 1.0, 1.0, 0.0]), 0, 1)[:, None]

    order = np.argsort(rs["t_ms"], kind="stable")
    t_sorted, r_sorted = rs["t_ms"][order], rs["row"][order]

    spk = np.zeros((Hv, Wv, 3), np.uint8)      # persistent, like the real canvas
    spk_a = np.zeros((Hv, Wv), bool)

    n_frames = int(round(cycles * (SPAN_S / SPEED) * FPS))
    OUT.mkdir(exist_ok=True)
    path = OUT / f"raster-{pal_name}.mp4"
    writer = imageio.get_writer(path, fps=FPS, codec="libx264", macro_block_size=1,
                               ffmpeg_params=["-crf", "20", "-preset", "slow",
                                              "-pix_fmt", "yuv420p"])

    bg = np.empty((Hv, Wv, 3), np.uint8)
    bg[:] = deep
    last_x = 0.0
    swept = 0.0

    for i in range(n_frames):
        swept += (1000 / FPS) * SPEED
        x = (swept % span_ms) / span_ms * Wv
        spans = [(last_x, x)] if x >= last_x else [(last_x, Wv), (0.0, x)]

        for xa_f, xb_f in spans:
            xa, xb = int(np.floor(xa_f)), min(Wv, int(np.ceil(xb_f)))
            if xb <= xa:
                continue
            spk_a[:, xa:xb] = False            # wipe only the columns being redrawn
            cycle = int(swept // span_ms)
            t0 = (cycle * span_ms + (xa / Wv) * span_ms) % rs["dur_ms"]
            t1 = t0 + ((xb - xa) / Wv) * span_ms
            lo_i, hi_i = np.searchsorted(t_sorted, [t0, t1])
            for k in range(lo_i, hi_i):
                px = xa + int(((t_sorted[k] - t0) / span_ms) * Wv)
                py = top + int(r_sorted[k] * row_h)
                spk[py:py + dot_h, px:px + DOT_W] = row_col[r_sorted[k]]
                spk_a[py:py + dot_h, px:px + DOT_W] = True
        last_x = x

        a = (spk_a[..., None] * vmask[..., None])
        frame = (bg * (1 - a) + spk * a).astype(np.uint8)

        # sweep bar with its glow, drawn over the mask like the DOM element it is
        xi = int(round(x))
        glow = 15
        for off in range(-glow, glow + 1):
            xx = xi + off
            if 0 <= xx < Wv:
                w = (1 - abs(off) / (glow + 1)) ** 2.2 * 0.42
                frame[:, xx] = np.clip(frame[:, xx] * (1 - w) + np.asarray(accent) * w, 0, 255)
        for xx in (xi - 1, xi, xi + 1):
            if 0 <= xx < Wv:
                frame[:, xx] = accent

        writer.append_data(frame)

    writer.close()
    print(f"  {path.name}  {n_frames} frames  {n_frames/FPS:.1f}s  {path.stat().st_size/1e6:.1f} MB")
    return path


# ------------------------------------------------------- hero raster, scroll mode
def render_raster_scroll(pal_name: str, pal: dict, rs: dict, seconds: float = 21.17) -> Path:
    """The other hero treatment: the whole raster slides leftward past a fixed frame, with
    no sweep bar. Every frame is a full repaint of the visible window, and spikes fade in
    and out at both edges -- matching drawScroll() in engine.js."""
    lut = ramp_lut(pal)
    Wv, Hv = 1600, 896
    deep = rgb(pal["deep"])

    SPAN_S, SPEED = 9.0, 0.85
    SHADE_LO, SHADE_HI = 118, 255
    DOT_W, PAD = 2, 0.04
    FADE = 0.08                        # fraction of the width the edge fade spans

    top = int(Hv * PAD)
    row_h = Hv * (1 - 2 * PAD) / rs["n"]
    dot_h = max(1, int(round(row_h * 0.82)))
    span_ms = SPAN_S * 1000

    shade = (SHADE_LO + (np.arange(rs["n"]) / rs["n"]) * (SHADE_HI - SHADE_LO)).astype(int)
    row_col = lut[np.clip(shade, 0, 255)].astype(np.float32)
    row_y = top + (np.arange(rs["n"]) * row_h).astype(int)

    ys = np.arange(Hv) / Hv
    vmask = np.clip(np.interp(ys, [0.0, 0.22, 0.72, 1.0], [0.0, 1.0, 1.0, 0.0]), 0, 1)[:, None]

    order = np.argsort(rs["t_ms"], kind="stable")
    t_sorted, r_sorted = rs["t_ms"][order], rs["row"][order]

    bg = np.empty((Hv, Hv and Wv, 3), np.float32)
    bg[:] = deep
    dy = np.arange(dot_h)[None, :, None]
    dx = np.arange(DOT_W)[None, None, :]

    n_frames = int(round(seconds * FPS))
    wrap_ms = max(1.0, rs["dur_ms"] - span_ms)

    OUT.mkdir(exist_ok=True)
    path = OUT / f"raster-scroll-{pal_name}.mp4"
    writer = imageio.get_writer(path, fps=FPS, codec="libx264", macro_block_size=1,
                               ffmpeg_params=["-crf", "20", "-preset", "slow",
                                              "-pix_fmt", "yuv420p"])

    for i in range(n_frames):
        t0 = (i * (1000 / FPS) * SPEED) % wrap_ms
        lo_i, hi_i = np.searchsorted(t_sorted, [t0, t0 + span_ms])
        tm = (t_sorted[lo_i:hi_i] - t0).astype(np.float32)
        rows = r_sorted[lo_i:hi_i]

        f = tm / span_ms
        alpha = np.where(f < FADE, f / FADE, np.where(f > 1 - FADE, (1 - f) / FADE, 1.0))
        px = np.clip((f * Wv).astype(int), 0, Wv - DOT_W)
        py = row_y[rows]

        acc_a = np.zeros(Hv * Wv, np.float32)
        acc_c = np.zeros((Hv * Wv, 3), np.float32)
        flat = ((py[:, None, None] + dy) * Wv + (px[:, None, None] + dx)).ravel()
        reps = dot_h * DOT_W
        acc_a[flat] = np.repeat(alpha, reps)
        acc_c[flat] = np.repeat(row_col[rows], reps, axis=0)

        a = (acc_a.reshape(Hv, Wv)[..., None] * vmask[..., None])
        frame = (bg * (1 - a) + acc_c.reshape(Hv, Wv, 3) * a).astype(np.uint8)
        writer.append_data(frame)

    writer.close()
    print(f"  {path.name}  {n_frames} frames  {n_frames/FPS:.1f}s  {path.stat().st_size/1e6:.1f} MB")
    return path


KINDS = {"widefield": render_widefield, "sweep": render_raster, "scroll": render_raster_scroll}

# ---------------------------------------------------------------- colourmap tests
# The cortex currently sits mid-ramp at rest, and the ramp's midpoint is its brightest
# colour -- which is why a quiet frame glows instead of fading into a dark page. Two
# independent ways to fix that:
#
#   1. RECOLOUR (variants below ending -div). Make the ramp diverging with black at the
#      centre, so zero deviation is black and both directions brighten away from it. The
#      data is untouched and the sign still reads.
#   2. RETRANSFORM (plasma-rect). Shift each pixel so its own low percentile is zero and
#      use a plain black-to-bright ramp. Also lands on black at the edges, but every pixel
#      then carries its own baseline.
CMAP_TESTS = {
    "teal-div": {"_stops": ["#3ee0bd", "#10564a", "#04060a", "#6e2a20", "#ff8a6a"]},
    "plasma-div": {"_stops": ["#b78cff", "#4b16a8", "#180a33", "#04030a",
                              "#4a0d2e", "#d02a7a", "#ffc24b"]},
    "indigo-div": {"_stops": ["#8f7bff", "#2d2a8c", "#05070f", "#0b5a72", "#35e0f5"]},
    "atlas-div": {"_stops": ["#7aa8ff", "#1b3060", "#06060a", "#5c4a10", "#ffd54a"]},
    "plasma-rect": {"_rectify": True,
                    "_stops": ["#04030a", "#3b0f6b", "#a02a8f", "#f0655a", "#ffd15c"]},
    # global signal removed, then a black-centred diverging ramp -- the combination that
    # actually keeps the surround dark frame after frame
    "plasma-divg": {"_demean": True,
                    "_stops": ["#b78cff", "#4b16a8", "#180a33", "#04030a",
                               "#4a0d2e", "#d02a7a", "#ffc24b"]},
    "teal-divg": {"_demean": True,
                  "_stops": ["#3ee0bd", "#10564a", "#04060a", "#6e2a20", "#ff8a6a"]},
    "atlas-divg": {"_demean": True,
                   "_stops": ["#7aa8ff", "#1b3060", "#06060a", "#5c4a10", "#ffd54a"]},
    # Rectified data with each palette's OWN existing ramp and no recolouring at all.
    # Every palette's --d0 is already near-black, so once a pixel's own low percentile is
    # the zero point, the ramp runs black -> bright with no invented hues.
    "teal-seq": {"_rectify": True},
    "indigo-seq": {"_rectify": True},
    "plasma-seq": {"_rectify": True},
    "atlas-seq": {"_rectify": True},
}


def render_cmap_tests(names: list[str], wf: dict, pals: dict) -> None:
    for name in names:
        cfg = CMAP_TESTS[name]
        base = pals.get(name.split("-")[0], pals["plasma"])
        pal = {**base, **cfg}          # panel chrome from a real palette, ramp from the test
        print(f"[cmap {name}]")
        render_widefield(name, pal, wf, out_name=f"cmaptest-{name}")


def main(argv: list[str]) -> int:
    args = argv[1:]
    kinds = list(KINDS)
    if "--kind" in args:
        k = args.index("--kind")
        kinds = args[k + 1].split(",")
        args = args[:k] + args[k + 2:]
    wanted = args or PALETTES

    pals = load_palettes()
    wf, rs = load_widefield(), load_raster()

    if kinds == ["cmap"]:
        render_cmap_tests(args or list(CMAP_TESTS), wf, pals)
        return 0

    print(f"widefield {wf['H']}x{wf['W']} x {wf['T']} frames @ {wf['fps']:.2f} Hz | "
          f"raster {rs['n']} neurons, {rs['dur_ms']/1000:.0f}s | kinds: {','.join(kinds)}")
    for name in wanted:
        if name not in pals:
            print(f"!! unknown palette {name}")
            continue
        print(f"[{name}]")
        for kind in kinds:
            if kind not in KINDS:
                print(f"!! unknown kind {kind}")
                continue
            KINDS[kind](name, pals[name], wf if kind == "widefield" else rs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
