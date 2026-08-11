"""Export a compact, web-ready spike raster from real Kilosort output.

Reads the sorter folder directly off the lab server (read-only) and writes
``assets/raster_b64.json``: per-neuron probe positions plus every spike in a 90 s window,
as base64 typed arrays (~150 KB for ~38k spikes).
"""
import base64
import json
from pathlib import Path

import numpy as np

KS = Path(r"Y:/Subjects/2024NPWorkshop/largerDataset")
OUT = Path(__file__).resolve().parent.parent / "assets"

FS = 30000.0        # sample rate (also in params.py)
MIN_RATE = 0.1      # spikes/s — drop near-silent clusters
T0, T1 = 300.0, 390.0   # the exported window, seconds into the recording
BIN_MS = 2          # time quantisation; 90 s / 2 ms = 45000 bins, fits uint16

st = np.load(KS / "spike_times.npy").astype(np.float64).ravel() / FS
sc = np.load(KS / "spike_clusters.npy").astype(np.int64).ravel()
sp_t = np.load(KS / "spike_templates.npy").astype(np.int64).ravel()
templates = np.load(KS / "templates.npy")          # (nTemplates, nSamples, nChannels)
chanpos = np.load(KS / "channel_positions.npy")    # (nChannels, 2) in microns

# Each template's peak channel gives its position along the probe.
amp = templates.max(axis=1) - templates.min(axis=1)
tmpl_y = chanpos[amp.argmax(axis=1), 1]

clusters = np.unique(sc)
clu_y = np.zeros(clusters.size)
clu_n = np.zeros(clusters.size, dtype=np.int64)
for i, c in enumerate(clusters):
    m = sc == c
    clu_n[i] = m.sum()
    clu_y[i] = tmpl_y[np.bincount(sp_t[m]).argmax()]

dur_all = st.max() - st.min()
keep = (clu_n / dur_all) > MIN_RATE
kc, ky = clusters[keep], clu_y[keep]
print(f"{keep.sum()} of {clusters.size} clusters above {MIN_RATE} spikes/s")

# `channel_positions` y is distance from the probe TIP, so a LARGER y sits closer to the brain
# surface. Sort descending so row 0 — drawn at the top of a canvas — is the most superficial
# unit and the probe tip lands at the bottom, which is how a raster is normally read.
order = np.argsort(-ky)
kc, ky = kc[order], ky[order]
row_of = {int(c): i for i, c in enumerate(kc)}
assert kc.size < 256, "row index must fit in a uint8"

sel = (st >= T0) & (st < T1) & np.isin(sc, kc)
ts = st[sel] - T0
rows = np.fromiter((row_of[int(c)] for c in sc[sel]), dtype=np.int32, count=int(sel.sum()))
o = np.argsort(ts, kind="stable")     # the web decoder binary-searches on time
ts, rows = ts[o], rows[o]
print(f"{ts.size} spikes in the {T1 - T0:.0f} s window")

tb = np.clip(np.round(ts * 1000 / BIN_MS), 0, 65535).astype(np.uint16)
rb = rows.astype(np.uint8)

asset = {
    "meta": {
        "source": "Steinmetz Lab Neuropixels recording (Kilosort output)",
        "n_neurons": int(kc.size),
        "duration_s": float(T1 - T0),
        "n_spikes": int(tb.size),
        "bin_ms": BIN_MS,
        "y_from_tip_um": [float(ky.min()), float(ky.max())],
    },
    # microns from the probe tip, one per row, in drawing order (top row first)
    "depth": [round(float(v), 1) for v in ky],
    "t": base64.b64encode(tb.tobytes()).decode("ascii"),
    "r": base64.b64encode(rb.tobytes()).decode("ascii"),
}
p = OUT / "raster_b64.json"
p.write_text(json.dumps(asset, separators=(",", ":")))
print(f"wrote {p}  {p.stat().st_size / 1024:.1f} KB  "
      f"({kc.size} neurons, y {ky.min():.0f}-{ky.max():.0f} um from tip)")
