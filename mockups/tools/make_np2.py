"""Pack the NP2.0 Quad export into a web asset: one binary of spikes + a small JSON.

Format (static/np2_spikes.bin), all little-endian:
    per unit, in display order:
        varint  n_spikes
        varint  delta_ms x n_spikes      (first delta is from t=0)
Times are milliseconds from the start of the window. Deltas rather than absolute times
because at ~12 spikes/s the typical gap is well under 128 ms, so most spikes cost one byte.

The JSON carries per-unit metadata only, so it can be inlined in the page.

Usage:  python tools/make_np2.py [window_seconds]
"""
import json
import sys
from pathlib import Path

import numpy as np

SRC = Path(r"D:/temp/np2web/units.npz")
OUT_BIN = Path(__file__).resolve().parent.parent / "static" / "np2_spikes.bin"
OUT_JSON = Path(__file__).resolve().parent.parent / "assets" / "np2_units.json"
WINDOW_S = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0


def varint(v, out):
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            return


def main():
    z = np.load(SRC)
    meta, row, t_ms = z["meta"], z["row"], z["t_ms"]
    keep = t_ms < WINDOW_S * 1000
    row, t_ms = row[keep], t_ms[keep]

    # Display order: probe, then shank, then depth from the tip upward, so scrolling the
    # page walks down one shank at a time rather than jumping between probes.
    probe, shank, depth = meta[:, 0], meta[:, 1], meta[:, 2]
    order = np.lexsort((-depth, shank, probe))
    rank = np.empty(len(meta), np.int64)
    rank[order] = np.arange(len(meta))

    blob = bytearray()
    counts = np.zeros(len(meta), np.int64)
    srt = np.argsort(row, kind="stable")
    row_s, t_s = row[srt], t_ms[srt]
    bounds = np.searchsorted(row_s, np.arange(len(meta) + 1))
    for u in order:
        t = np.sort(t_s[bounds[u]:bounds[u + 1]]).astype(np.int64)
        counts[u] = len(t)
        varint(len(t), blob)
        prev = 0
        for x in t:
            varint(int(x) - prev, blob)
            prev = int(x)

    OUT_BIN.parent.mkdir(exist_ok=True)
    OUT_BIN.write_bytes(bytes(blob))

    units = [{"p": int(probe[u]), "s": int(shank[u]), "d": round(float(depth[u]), 1),
              "a": round(float(meta[u, 3]), 1), "n": int(counts[u])} for u in order]
    OUT_JSON.write_text(json.dumps({
        "_comment": ("QC-passing units from the NP2.0 Quad recording (KM_077, 2026-05-24), "
                     "in display order. Spike times live in static/np2_spikes.bin. "
                     "p/s = probe/shank, d = depth in um, a = amplitude in uV, "
                     "n = spikes in the window."),
        "window_s": WINDOW_S, "n_units": len(units),
        "n_spikes": int(counts.sum()), "units": units,
    }, separators=(",", ":")), encoding="utf-8")

    print(f"{len(units)} units, {int(counts.sum())} spikes in {WINDOW_S:.0f} s")
    print(f"  {OUT_BIN.name}:  {len(blob)/1e6:.2f} MB "
          f"({len(blob)/max(1,counts.sum()):.2f} bytes/spike)")
    print(f"  {OUT_JSON.name}: {OUT_JSON.stat().st_size/1024:.0f} KB")
    print(f"  depth range {depth.min():.0f}-{depth.max():.0f} um, "
          f"{len(np.unique(probe))} probes x 4 shanks")


if __name__ == "__main__":
    main()
