"""Rasterise the extracted mark.svg with matplotlib so it can be eyeballed."""
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.path import Path as MPath
from matplotlib.patches import PathPatch

svg = Path(__file__).parent / "mark.svg"
s = svg.read_text(encoding="utf-8")
vb = [float(x) for x in re.search(r'viewBox="([^"]+)"', s).group(1).split()]
d = re.search(r'\bd="([^"]*)"', s).group(1)

verts, codes = [], []
for cm in re.finditer(r"([MLCZ])([^MLCZ]*)", d):
    cmd = cm.group(1)
    ns = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", cm.group(2))]
    pts = [(ns[i], ns[i + 1]) for i in range(0, len(ns) - 1, 2)]
    if cmd == "M":
        verts.append(pts[0]); codes.append(MPath.MOVETO)
        for p in pts[1:]:
            verts.append(p); codes.append(MPath.LINETO)
    elif cmd == "L":
        for p in pts:
            verts.append(p); codes.append(MPath.LINETO)
    elif cmd == "C":
        for i in range(0, len(pts) - 2, 3):
            verts.extend(pts[i:i + 3]); codes.extend([MPath.CURVE4] * 3)
    elif cmd == "Z":
        verts.append((0.0, 0.0)); codes.append(MPath.CLOSEPOLY)

print("segments:", len(codes))
fig, ax = plt.subplots(figsize=(4, 4), dpi=140)
fig.patch.set_facecolor("#141318")
ax.set_facecolor("#141318")
ax.add_patch(PathPatch(MPath(verts, codes), fill=False, ec="#e2c79a", lw=1.6,
                       joinstyle="round", capstyle="round"))
ax.set_xlim(vb[0], vb[2]); ax.set_ylim(vb[3], vb[1])
ax.set_aspect("equal"); ax.axis("off")
out = svg.with_name("mark_check.png")
fig.savefig(out, facecolor=fig.get_facecolor(), bbox_inches="tight")
print("wrote", out)
