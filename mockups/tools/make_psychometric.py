"""Three-choice psychometric assembling itself from single trials, as a looping clip.

Data: Steinmetz et al. 2019, mouse Lederberg, all 7 sessions pooled (the subject with the
best high-contrast performance -- see that paper's Extended Data Fig 1d,l).

Shows the pedestal-0% condition: trials where at most one side had contrast, which is the
row the paper highlights in EDF1k. x is the contrast difference; the three curves are the
probability of turning left, turning right, and holding still (NoGo). They sum to 1 by
construction, which is why NoGo peaks where the evidence is ambiguous.

Individual trials rain into three lanes at the top -- one lane per choice -- and the
proportions below settle as evidence accumulates. The curves are the probabilistic observer
model of Burgess et al. 2017 (Cell Reports 20:2513, Equations 1-3), the same model whose
fits are drawn in that paper's Figure 6:

    f(c)       = c^n / (c50^n + c^n)                                        (Eq 1)
    zL, zR     = bL + sL f(cL),  bR + sR f(cR)                              (Eq 2)
    log(pL/p0) = zL,   log(pR/p0) = zR                                      (Eq 3)

so pNoGo = 1 / (1 + e^zL + e^zR). The six parameters (bL, bR, sL, sR, c50, n) are fit by
maximum likelihood.

FIT_ALL_PEDESTALS picks which of the paper's two treatments to use. True (default) fits
every trial, so one parameter set serves all pedestals as in Figure 6, and the curve drawn
is that fit evaluated along the pedestal-0 slice. It costs about 0.1 at the +-25% points,
which are pulled by discrimination trials the viewer cannot see.

False instead fits only the pedestal-0 trials that are plotted, as in Figure 3C where the
detection task IS the pedestal-0 case. It tracks these dots more closely but degenerates:
with no trials where both sides carry contrast, nothing constrains the shape of f, the fit
runs to n = 0.5 and c50 = 0.17, and the curves become a near-vertical step at zero. The
data really do say that any contrast at all is enough -- Lederberg is ~95% correct at 25%
contrast -- so the compressive fit is not wrong, just uninformative about contrast.

Usage:  python tools/make_psychometric.py [palette ...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_videos import FPS, MONO, OUT, load_palettes, ramp_lut, rgb  # noqa: E402

ALF = Path(r"D:/Dropbox/ucl/data/CoriMullerRadnitz/alf/Lederberg")
FIT_ALL_PEDESTALS = True           # see the note in the module docstring
W, H = 1024, 704
T_RAIN, T_CURVE, T_HOLD, T_FADE = 13.0, 2.0, 3.0, 1.5

LANE_TOP, LANE_H = 54, 30          # the three trial lanes
PLOT = dict(l=112, r=54, t=176, b=92)


def load_pooled():
    """Pool every Lederberg session; keep non-repeat trials at pedestal 0."""
    CL, CR, CH, FB = [], [], [], []
    sessions = sorted(p for p in ALF.iterdir() if p.is_dir())
    for s in sessions:
        cl = np.load(s / "cwStimOn.contrastLeft.npy").ravel()
        cr = np.load(s / "cwStimOn.contrastRight.npy").ravel()
        ch = np.load(s / "cwResponse.choice.npy").ravel()
        fb = np.load(s / "cwFeedback.type.npy").ravel()
        rep = np.load(s / "cwTrials.repNum.npy").ravel()
        n = min(len(cl), len(cr), len(ch), len(fb), len(rep))
        k = rep[:n] == 1                       # drop repeat-after-error trials
        CL.append(cl[:n][k]); CR.append(cr[:n][k])
        CH.append(ch[:n][k]); FB.append(fb[:n][k])
    cl, cr, ch, fb = (np.concatenate(x) for x in (CL, CR, CH, FB))
    print(f"{len(sessions)} sessions, {len(cl)} non-repeat trials")

    # Derive the choice coding from the data instead of assuming it: on unequal-contrast
    # trials that were rewarded, the choice value IS the correct side.
    right_code = int(np.bincount(ch[(cr > cl) & (fb == 1)].astype(int)).argmax())
    left_code = int(np.bincount(ch[(cl > cr) & (fb == 1)].astype(int)).argmax())
    nogo_code = int(np.bincount(ch[(cl == 0) & (cr == 0) & (fb == 1)].astype(int)).argmax())
    assert len({right_code, left_code, nogo_code}) == 3, "choice codes not distinct"
    print(f"choice codes -> left {left_code}, right {right_code}, nogo {nogo_code}  "
          f"(derived from rewarded trials)")

    code = ch.astype(int)
    y = np.select([code == left_code, code == right_code],
                  [0, 1], default=2)           # 0 left, 1 right, 2 nogo

    ped0 = (cl == 0) | (cr == 0)               # pedestal 0%: at most one side has contrast
    dc = (cr - cl)[ped0] * 100                 # contrast difference, per cent
    outcome = y[ped0]
    print(f"{ped0.sum()} pedestal-0 trials | levels {np.unique(dc)} | "
          f"outcome mix {np.bincount(outcome) / len(outcome)}")
    return cl, cr, y, dc, outcome


# ---------------------------------------------------------------- observer model ---
def model_probs(th, cl, cr):
    """Burgess et al. 2017 Equations 1-3; returns P(left), P(right), P(NoGo)."""
    bL, bR, sL, sR, lc50, ln = th
    c50, n = np.exp(lc50), np.exp(ln)
    f = lambda c: c ** n / (c50 ** n + c ** n)                            # noqa: E731
    zL, zR = bL + sL * f(cl), bR + sR * f(cr)
    m = np.maximum(0, np.maximum(zL, zR))                                 # stable softmax
    eL, eR, e0 = np.exp(zL - m), np.exp(zR - m), np.exp(-m)
    tot = eL + eR + e0
    return eL / tot, eR / tot, e0 / tot


def fit_model(cl, cr, y):
    """Maximum likelihood over all six parameters, using every trial."""
    def nll(th):
        pL, pR, p0 = model_probs(th, cl, cr)
        p = np.where(y == 0, pL, np.where(y == 1, pR, p0))
        return -np.log(np.clip(p, 1e-12, None)).sum()

    th = np.array([-1.0, -1.0, 3.0, 3.0, np.log(0.2), np.log(1.0)])
    for tol in (1e-8, 1e-10):
        th = minimize(nll, th, method="Nelder-Mead",
                      options={"maxiter": 20000, "xatol": tol, "fatol": tol}).x
    pL, pR, p0 = model_probs(th, cl, cr)
    acc = (np.argmax(np.c_[pL, pR, p0], axis=1) == y).mean()
    print(f"observer model: bL={th[0]:+.3f} bR={th[1]:+.3f} sL={th[2]:.3f} sR={th[3]:.3f} "
          f"c50={np.exp(th[4]):.3f} n={np.exp(th[5]):.3f} | -logL={nll(th):.1f} | "
          f"{acc:.1%} of choices explained")
    return th


def wilson(k, n, z=1.96):
    """95% binomial interval, Wilson score -- stays inside [0,1] when p is 0 or 1."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def model_curve(th, dgrid):
    """The fit along the pedestal-0 slice: one side carries the contrast, the other zero."""
    d = dgrid / 100.0
    cl = np.clip(-d, 0, None)
    cr = np.clip(d, 0, None)
    return model_probs(th, cl, cr)


def export_json(theta, dc, outcome, levels):
    """Hand the fit and the measured points to the website, which redraws them live.

    The page needs no trial data: six parameters regenerate the curves at any width, and
    the palette then colours them, which an embedded video could never do."""
    pts = []
    for L in levels:
        sel = outcome[dc == L]
        row = {"dc": int(L), "n": int(sel.size), "p": [], "ci": []}
        for oc in (0, 1, 2):
            hits = int((sel == oc).sum())
            row["p"].append(round(hits / sel.size, 4))
            row["ci"].append([round(v, 4) for v in wilson(hits, sel.size)])
        pts.append(row)
    bL, bR, sL, sR, lc50, ln = theta
    out = {
        "_comment": ("Burgess et al. 2017 observer model fit to Steinmetz 2019 mouse "
                     "Lederberg, 7 sessions. p and ci are [left, right, nogo]; ci is a 95% "
                     "Wilson binomial interval. Curves are regenerated from params in JS."),
        "params": {"bL": round(bL, 5), "bR": round(bR, 5), "sL": round(sL, 5),
                   "sR": round(sR, 5), "c50": round(float(np.exp(lc50)), 5),
                   "n": round(float(np.exp(ln)), 5)},
        "points": pts,
    }
    p = Path(__file__).resolve().parent.parent / "assets" / "psychometric.json"
    p.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"  wrote {p.name}  ({p.stat().st_size} bytes, {len(pts)} conditions)")


def main(argv):
    cl, cr, y, dc, outcome = load_pooled()
    k = slice(None) if FIT_ALL_PEDESTALS else ((cl == 0) | (cr == 0))
    theta = fit_model(cl[k], cr[k], y[k])
    GX = np.linspace(-100, 100, 240)
    curve = model_curve(theta, GX)             # (P left, P right, P nogo) along the slice
    levels = np.unique(dc)
    export_json(theta, dc, outcome, levels)
    order = np.random.default_rng(0).permutation(len(dc))
    dc, outcome = dc[order], outcome[order]
    n_per = np.array([(dc == L).sum() for L in levels])

    dur = T_RAIN + T_CURVE + T_HOLD + T_FADE
    n_frames = int(round(dur * FPS))
    x0, x1 = PLOT["l"], W - PLOT["r"]
    y0, y1 = PLOT["t"], H - PLOT["b"]
    X = lambda c: x0 + (c + 100) / 200 * (x1 - x0)          # noqa: E731
    Y = lambda p: y1 - p * (y1 - y0)                        # noqa: E731

    rng = np.random.default_rng(1)
    xj = rng.uniform(-3.2, 3.2, len(dc))
    yj = rng.uniform(0.18, 0.82, len(dc))

    f_big = ImageFont.truetype(str(MONO), 15)
    f_sm = ImageFont.truetype(str(MONO), 12)
    pals = load_palettes()
    LANES = ("Left", "NoGo", "Right")

    for pal_name in (argv or ["teal"]):
        pal = pals[pal_name]
        lut = ramp_lut(pal)
        deep, di, di2, di3, drule = (rgb(pal["deep"]), rgb(pal["di"]), rgb(pal["di-2"]),
                                     rgb(pal["di-3"]), rgb(pal["drule"]))
        # left = cool end of the ramp, right = warm end, nogo = neutral ink
        col = {0: tuple(lut[70]), 1: tuple(lut[238]), 2: di2}
        lane_y = {0: LANE_TOP, 2: LANE_TOP + LANE_H, 1: LANE_TOP + 2 * LANE_H}

        path = OUT / f"psychometric-{pal_name}.mp4"
        OUT.mkdir(exist_ok=True)
        wr = imageio.get_writer(path, fps=FPS, codec="libx264", macro_block_size=1,
                                ffmpeg_params=["-crf", "20", "-preset", "slow",
                                               "-pix_fmt", "yuv420p"])
        for fi in range(n_frames):
            t = fi / FPS
            img = Image.new("RGB", (W, H), deep)
            d = ImageDraw.Draw(img)
            fade = 1.0 if t < dur - T_FADE else max(0.0, 1 - (t - (dur - T_FADE)) / T_FADE)
            mix = lambda c: tuple(int(deep[i] + (c[i] - deep[i]) * fade) for i in range(3))  # noqa: E731

            # ---- axes -----------------------------------------------------
            d.line([x0, y0, x0, y1], fill=mix(drule))
            d.line([x0, y1, x1, y1], fill=mix(drule))
            for p in (0, 0.5, 1.0):
                d.line([x0, Y(p), x1, Y(p)], fill=mix(drule))
                d.text((x0 - 42, Y(p) - 8), f"{p:.1f}", font=f_sm, fill=mix(di3))
            for c in (-100, -50, 0, 50, 100):
                d.line([X(c), y1, X(c), y1 + 5], fill=mix(drule))
                d.text((X(c) - 13, y1 + 12), f"{c:+d}" if c else "0", font=f_sm, fill=mix(di3))
            d.text((x0 - 100, (y0 + y1) // 2 - 30), "Proportion", font=f_sm, fill=mix(di3))
            d.text((x0 - 100, (y0 + y1) // 2 - 14), "choices", font=f_sm, fill=mix(di3))
            d.text(((x0 + x1) // 2 - 96, y1 + 42), "Contrast difference (%)",
                   font=f_sm, fill=mix(di3))

            # ---- trial lanes ----------------------------------------------
            k = int(np.clip(t / T_RAIN, 0, 1) * len(dc))
            for lane, oc in ((0, 0), (1, 2), (2, 1)):
                yy = LANE_TOP + lane * LANE_H
                d.text((x0 - 96, yy + 8), LANES[lane], font=f_sm, fill=mix(col[oc]))
                d.line([x0, yy + LANE_H - 4, x1, yy + LANE_H - 4],
                       fill=mix(tuple(int(v * 0.45) for v in drule)))
            for i in range(k):
                oc = outcome[i]
                yy = lane_y[oc] + yj[i] * (LANE_H - 8)
                xx = X(dc[i] + xj[i])
                d.rectangle([xx - 1, yy - 1, xx + 1, yy + 1], fill=mix(col[oc]))

            # ---- running proportions, with 95% binomial intervals ----------
            for oc in (0, 1, 2):
                for j, L in enumerate(levels):
                    sel = np.where(dc[:k] == L)[0]
                    if sel.size < 4:
                        continue
                    hits = int((outcome[sel] == oc).sum())
                    p = hits / sel.size
                    lo_ci, hi_ci = wilson(hits, sel.size)
                    r = 2.5 + 6.0 * min(1.0, sel.size / max(1, n_per[j]))
                    cx, cy = X(L), Y(p)
                    d.line([cx, Y(lo_ci), cx, Y(hi_ci)], fill=mix(col[oc]), width=2)
                    d.ellipse([cx - r, cy - r, cx + r, cy + r],
                              fill=mix(col[oc]), outline=mix(deep))

            # ---- observer-model fit, drawn left to right -------------------
            if t > T_RAIN:
                f = min(1.0, (t - T_RAIN) / T_CURVE)
                m = max(2, int(len(GX) * f))
                for oc in (0, 1, 2):
                    d.line([(X(c), Y(float(p))) for c, p in zip(GX[:m], curve[oc][:m])],
                           fill=mix(col[oc]), width=3, joint="curve")
                # mid-right stays clear: by there the right curve is at 1 and the left at 0
                d.text((x1 - 262, y0 + 120), "observer model, Burgess et al. 2017",
                       font=f_sm, fill=mix(di3))

            # ---- readout ---------------------------------------------------
            d.text((x1 - 150, LANE_TOP - 26), f"{k:4d} / {len(dc)} trials",
                   font=f_sm, fill=mix(di3))
            d.text((x0, LANE_TOP - 26), "Lederberg  7 sessions  pedestal 0%",
                   font=f_sm, fill=mix(di2))

            wr.append_data(np.asarray(img))
        wr.close()
        print(f"  {path.name}  {n_frames} frames  {dur:.1f}s  "
              f"{path.stat().st_size/1e6:.1f} MB")


if __name__ == "__main__":
    main(sys.argv[1:])
