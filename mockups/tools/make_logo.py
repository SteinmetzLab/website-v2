"""Extract the circuit-brain mark from the lab logo PDF-derived SVG into a tiny,
single-colour, recolourable SVG (stroke = currentColor)."""
import re
from pathlib import Path

OUT = Path(__file__).parent
src = (OUT / "logo_h.svg").read_text(encoding="utf-8")

PATH_RE = re.compile(r"<path\b([^>]*?)/>", re.S)
D_RE = re.compile(r'\bd="([^"]*)"')
TR_RE = re.compile(r'transform="matrix\(([^)]*)\)"')
NUM_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")

paths = []
for m in PATH_RE.finditer(src):
    attrs = m.group(1)
    if 'fill="none"' not in attrs or "stroke=" not in attrs:
        continue  # skip the background rect and any filled art
    d = D_RE.search(attrs)
    if not d:
        continue
    a = b = c = dd = e = f = None
    tr = TR_RE.search(attrs)
    if tr:
        a, b, c, dd, e, f = [float(x) for x in NUM_RE.findall(tr.group(1))]
    paths.append((d.group(1), (a, b, c, dd, e, f) if tr else None))

print("stroked paths:", len(paths))

CMD_RE = re.compile(r"([MLCZmlcz])([^MLCZmlcz]*)")


def xform(pt, t):
    if t is None:
        return pt
    a, b, c, d, e, f = t
    x, y = pt
    return (a * x + c * y + e, b * x + d * y + f)


def parse(d, t):
    """Return list of (cmd, [transformed points]) — absolute commands only in this file."""
    out = []
    for cm in CMD_RE.finditer(d):
        cmd, body = cm.group(1), cm.group(2)
        assert cmd in "MLCZ", f"relative command {cmd!r} not handled"
        nums = [float(x) for x in NUM_RE.findall(body)]
        pts = [xform((nums[i], nums[i + 1]), t) for i in range(0, len(nums) - 1, 2)]
        out.append((cmd, pts))
    return out


parsed = [parse(d, t) for d, t in paths]


def bbox(p):
    xs = [q[0] for _, pts in p for q in pts]
    ys = [q[1] for _, pts in p for q in pts]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


boxes = [bbox(p) for p in parsed]
allx = [b[0] for b in boxes if b] + [b[2] for b in boxes if b]
ally = [b[1] for b in boxes if b] + [b[3] for b in boxes if b]
print(f"overall bbox x {min(allx):.0f}..{max(allx):.0f}  y {min(ally):.0f}..{max(ally):.0f}")

# The source PDF is a working sheet: two standalone marks on the top row, then three full
# lockups below. Isolate the top-left standalone mark.
XCUT, YCUT = 340.0, 330.0
mark = [p for p, b in zip(parsed, boxes) if b and b[2] < XCUT and b[3] < YCUT]
rest = [p for p, b in zip(parsed, boxes) if not (b and b[2] < XCUT and b[3] < YCUT)]
print("mark paths:", len(mark), " other paths:", len(rest))

mb = bbox([seg for p in mark for seg in p])
print(f"mark bbox {mb[0]:.1f} {mb[1]:.1f} {mb[2]:.1f} {mb[3]:.1f}")

PAD = 3.0
x0, y0, x1, y1 = mb[0] - PAD, mb[1] - PAD, mb[2] + PAD, mb[3] + PAD
w, h = x1 - x0, y1 - y0


def emit(p):
    parts = []
    for cmd, pts in p:
        if cmd == "Z":
            parts.append("Z")
            continue
        coords = " ".join(f"{q[0]-x0:.2f} {q[1]-y0:.2f}" for q in pts)
        parts.append(f"{cmd}{coords}")
    return " ".join(parts)


ds = " ".join(emit(p) for p in mark)
ds = re.sub(r"\s+", " ", ds).strip()

svg = (
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.2f} {h:.2f}" '
    f'fill="none" stroke="currentColor" stroke-width="3.13" '
    f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    f'<path d="{ds}"/></svg>'
)
p = OUT / "mark.svg"
p.write_text(svg, encoding="utf-8")
print("wrote", p, round(p.stat().st_size / 1024, 1), "KB", f"viewBox {w:.1f}x{h:.1f}")
