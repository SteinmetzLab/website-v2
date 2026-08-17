"""Verify make_np2_movie's display-order remapping against the raw export.

The step that could be silently wrong is `rank[row]`: spikes arrive indexed by original
unit, the movie draws by display position, and a bad permutation would put every spike on
the wrong neuron while still producing a perfectly plausible-looking raster. Nothing about
the picture would give it away, so check it directly -- recover which original unit each
display row is by matching its full metadata row, and require the spike trains to be
identical.

    python tools/check_np2_movie.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_np2_movie import SRC, SPAN_S, load_units      # noqa: E402


def main() -> int:
    raw = np.load(SRC)
    meta_raw, row_raw, t_raw = raw["meta"], raw["row"], raw["t_ms"]
    u = load_units()
    mo = u["meta"]
    fail = 0

    # 1. the display order is the one make_np2.py (and so the web page) uses
    key = list(zip(mo[:, 0], mo[:, 1], -mo[:, 2]))
    if key != sorted(key):
        print("FAIL: display order is not (probe, shank, depth descending)")
        fail += 1
    else:
        print("display order   probe, then shank, then depth descending      OK")

    # 2. spike trains follow their unit through the permutation. Sample the block
    #    boundaries, where an off-by-one would land, plus a random spread.
    rng = np.random.RandomState(0)
    rows = np.unique(np.r_[0, 137, 138, 574, 575, 1039, 1040, len(mo) - 1,
                           rng.randint(0, len(mo), 16)])
    bad = []
    for r in rows:
        hit = np.where((meta_raw == mo[r][None, :]).all(1))[0]
        if len(hit) != 1:
            bad.append((r, f"{len(hit)} original units match"))
            continue
        a = np.sort(t_raw[row_raw == hit[0]])
        b = np.sort(u["t_sorted"][u["r_sorted"] == r])
        if len(a) != len(b) or not np.allclose(a, b):
            bad.append((r, f"{len(a)} vs {len(b)} spikes"))
    if bad:
        for r, why in bad:
            print(f"FAIL: display row {r}: {why}")
        fail += 1
    else:
        print(f"spike trains    {len(rows)} display rows match their original unit  OK")

    # 3. a frame's time slice really holds SPAN_S of recording, no more, no less
    t0 = 10_000.0
    lo, hi = np.searchsorted(u["t_sorted"], [t0, t0 + SPAN_S * 1000])
    direct = int(((t_raw >= t0) & (t_raw < t0 + SPAN_S * 1000)).sum())
    if hi - lo != direct:
        print(f"FAIL: frame window sliced {hi-lo:,}, direct count {direct:,}")
        fail += 1
    else:
        print(f"frame window    {SPAN_S:g} s slice = {direct:,} spikes, counted directly  OK")

    # 4. nothing dropped on the way through
    if len(u["t_sorted"]) != len(t_raw):
        print(f"FAIL: {len(u['t_sorted']):,} spikes carried, {len(t_raw):,} in the export")
        fail += 1
    else:
        print(f"conservation    {len(t_raw):,} spikes, {len(mo):,} units carried through  OK")

    print("\n" + ("all checks passed" if not fail else f"{fail} check(s) FAILED"))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
