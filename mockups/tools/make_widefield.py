"""Export a compact, web-reconstructable widefield movie from real SVD data.

The browser rebuilds frames as dF(t) = U @ dV(t), so the payload is a handful of spatial
components plus a short temporal window rather than a video file.

The whole camera field of view is kept -- no mask. Normalisation is by a single scalar F0
(the median of the mean image over cortex) rather than per pixel, because dividing pixel-wise
makes dim regions outside the cranial window explode and saturate into flat slabs.

RECTIFY shifts each pixel so that its own low percentile over the window sits at zero, and
the page then runs a plain dark-to-bright ramp instead of a symmetric one. That is what puts
true black outside the brain: with a symmetric map, an inactive pixel sits mid-ramp, which is
the brightest part of every palette, so the surround glowed. The offset is folded in as one
extra spatial component whose temporal weight is constant, so the browser's dF = U @ dV
reconstruction needs no special case. Note this gives each pixel its own baseline, which is a
display choice, not what we would do for analysis.
"""
import base64
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import butter, filtfilt

SESS = Path(r"Y:/Subjects/ZYE_0092/2025-06-02/1/blue")
OUT = Path(__file__).resolve().parent.parent / "assets"

K = 8           # spatial components to keep
BLOCK = 4       # 560 -> 140 px
NFRAMES = 900   # temporal window length
T0 = 12000      # start frame (skip the beginning of the session)
LOWPASS_HZ = 5  # display-only smoothing; we do NOT do this for analysis
RECTIFY = True  # per-pixel baseline -> zero maps to black (see the module docstring)
PCTILE = 5      # which per-pixel percentile counts as that pixel's baseline
# The camera frame as stored already has anterior at the top and the midline vertical, so no
# reorientation is needed here. (An earlier version looked rotated in the browser only because
# the pixel bytes were written column-major while the page indexed them row-major.)
TRANSPOSE = False

print("loading U (first %d components, contiguous in F-order)..." % K)
U = np.ascontiguousarray(
    np.load(SESS / "svdSpatialComponents.npy", mmap_mode="r")[:, :, :K], dtype=np.float64)
mean_img = np.asarray(np.load(SESS / "meanImage.npy", mmap_mode="r"), dtype=np.float64)

ts = np.asarray(np.load(SESS / "svdTemporalComponents.timestamps.npy", mmap_mode="r")).ravel()
fps = 1.0 / np.median(np.diff(ts))
print(f"frame rate {fps:.2f} Hz, session {ts[-1] - ts[0]:.0f} s, {ts.size} frames")

V = np.ascontiguousarray(
    np.load(SESS / "svdTemporalComponents.npy", mmap_mode="r")[T0:T0 + NFRAMES, :K],
    dtype=np.float64)


def block_mean(a, b):
    """Downsample the first two axes by an integer factor."""
    h, w = a.shape[:2]
    h, w = (h // b) * b, (w // b) * b
    a = a[:h, :w]
    return a.reshape((h // b, b, w // b, b) + a.shape[2:]).mean(axis=(1, 3))


Ud = block_mean(U, BLOCK)
Md = block_mean(mean_img[..., None], BLOCK)[..., 0]

if TRANSPOSE:
    Ud = np.swapaxes(Ud, 0, 1)
    Md = Md.T

H, W = Md.shape
print("downsampled to", H, W, "| transposed" if TRANSPOSE else "")

# One scalar baseline, taken over the bright (cortex) part of the mean image.
F0 = float(np.median(Md[Md > np.percentile(Md, 70)]))
Up = Ud / F0

# Display-only temporal smoothing. Filtering the temporal components is equivalent to
# filtering the reconstructed movie, since the reconstruction is linear.
if LOWPASS_HZ:
    b, a = butter(3, LOWPASS_HZ / (fps / 2), btype="low")
    V = filtfilt(b, a, V, axis=0)
    print(f"low-passed V at {LOWPASS_HZ} Hz (order 3, zero-phase)")

dV = V - V.mean(axis=0, keepdims=True)

frames = Up.reshape(-1, K) @ dV.T

if RECTIFY:
    # Each pixel's own 5th percentile becomes its zero.
    pix_base = np.percentile(frames, PCTILE, axis=1)
    frames = frames - pix_base[:, None]
    lim = float(np.percentile(frames, 99.5))
    # Fold the offset in as an extra component with a constant temporal weight, so the
    # page reconstructs the rectified movie with no change to its inner loop.
    Up = np.concatenate([Up.reshape(-1, K), -pix_base[:, None]], axis=1).reshape(H, W, K + 1)
    dV = np.concatenate([dV, np.ones((dV.shape[0], 1))], axis=1)
    K += 1
    print(f"rectified at the {PCTILE}th percentile per pixel; "
          f"upper limit {lim:.4f} (zero is now the dark end of the ramp)")
else:
    lim = float(np.percentile(np.abs(frames), 99.5))
    print(f"F0 = {F0:.0f} counts; dF/F0 symmetric limit {lim:.4f}")

# ---- quantise -------------------------------------------------------------------
u_scale = np.abs(Up).reshape(-1, K).max(axis=0)
u_scale[u_scale == 0] = 1.0
Uq = np.clip(np.round(Up / u_scale * 127.0), -127, 127).astype(np.int8)

v_scale = np.abs(dV).max(axis=0)
v_scale[v_scale == 0] = 1.0
Vq = np.clip(np.round(dV / v_scale * 32000.0), -32000, 32000).astype(np.int16)

err = np.abs((Uq * (u_scale / 127.0)).reshape(-1, K) @ (Vq * (v_scale / 32000.0)).T
             - frames).max() / lim
print(f"max quantisation error {err * 100:.2f}% of colour limit")

asset = {
    "meta": {
        "source": "Steinmetz Lab widefield calcium imaging (SVD-compressed)",
        "subject": "ZYE_0092", "date": "2025-06-02",
        "fps": round(float(fps), 3), "n_frames": int(NFRAMES),
        "n_components": K, "px": [int(H), int(W)],
        "limit": round(lim, 6), "f0_counts": round(F0, 1),
        # "rectified": zero is the dark end; otherwise the map is symmetric about zero
        "rectified": bool(RECTIFY), "baseline_pctile": PCTILE if RECTIFY else None,
    },
    "u_scale": [float(x) for x in u_scale],
    "v_scale": [float(x) for x in v_scale],
    # Row-major within each component (index = k*H*W + row*W + col) so the page can write
    # straight into an ImageData buffer, which is also row-major.
    "U": base64.b64encode(np.ascontiguousarray(np.transpose(Uq, (2, 0, 1))).tobytes()).decode(),
    "V": base64.b64encode(np.ascontiguousarray(Vq).tobytes()).decode(),
}
p = OUT / "widefield_b64.json"
p.write_text(json.dumps(asset, separators=(",", ":")))
print("wrote", p, round(p.stat().st_size / 1024, 1), "KB")

# ---- eyeball a few frames ------------------------------------------------------
# Top row is the mean image (to judge which way is anterior); below it, sample frames.
show = np.linspace(0, NFRAMES - 1, 5).astype(int)
fig, axs = plt.subplots(1, 6, figsize=(15, 2.9), dpi=110)
axs[0].imshow(Md, cmap="gray")
axs[0].set_title("mean image (orientation)", fontsize=8)
axs[0].axis("off")
for ax, t in zip(axs[1:], show):
    ax.imshow(frames[:, t].reshape(H, W), cmap="magma",
              vmin=0 if RECTIFY else -lim, vmax=lim,
              interpolation="bilinear")
    ax.set_title(f"t = {t / fps:.2f} s", fontsize=8)
    ax.axis("off")
fig.tight_layout()
fig.savefig(Path(__file__).resolve().parent / "wf_frames_check.png", facecolor="white")
print("wrote tools/wf_frames_check.png")
