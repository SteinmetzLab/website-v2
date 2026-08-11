"""Fetch and subset the candidate typefaces to inline-able WOFF.

Every family here is under the SIL Open Font License or Apache 2.0, so it can be
self-hosted on the lab site. Nothing is loaded from a CDN at runtime -- the built page
embeds the subsets as data URIs.

Each option supplies three roles:
    <slug>-cond   condensed / display face, used for headlines in caps
    <slug>-400    body regular
    <slug>-700    body bold
plus one shared monospace for numbers, units and captions.
"""
import base64
import io
import sys
import urllib.request
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

OUT = Path(__file__).resolve().parent.parent / "assets"
CACHE = Path(__file__).resolve().parent / "_fontcache"
CACHE.mkdir(exist_ok=True)

RAW = "https://raw.githubusercontent.com/google/fonts/main/"
WIN = Path("C:/Windows/Fonts")

# role -> either a google/fonts URL, or a local path for what is already installed
FACES = {
    # 1. Open Sans (Apache 2.0) -- the baseline already seen
    "opensans-cond": WIN / "Open Sans Condensed 700.ttf",
    "opensans-400": WIN / "Open Sans regular.ttf",
    "opensans-700": WIN / "Open Sans 700.ttf",

    # 2. IBM Plex (OFL) -- a technical superfamily; reads like scientific instrumentation
    "plex-cond": RAW + "ofl/ibmplexsanscondensed/IBMPlexSansCondensed-Bold.ttf",
    "plex-400": RAW + "ofl/ibmplexsans/IBMPlexSans%5Bwdth,wght%5D.ttf",
    "plex-700": RAW + "ofl/ibmplexsans/IBMPlexSans%5Bwdth,wght%5D.ttf",

    # 3. Barlow (OFL) -- signage grotesk, closest match to the logo's condensed wordmark
    "barlow-cond": RAW + "ofl/barlowcondensed/BarlowCondensed-Bold.ttf",
    "barlow-400": RAW + "ofl/barlow/Barlow-Regular.ttf",
    "barlow-700": RAW + "ofl/barlow/Barlow-Bold.ttf",

    # 4. Archivo (OFL) -- sturdier and wider; a deliberately less condensed voice
    "archivo-cond": RAW + "ofl/archivo/Archivo%5Bwdth,wght%5D.ttf",
    "archivo-400": RAW + "ofl/archivo/Archivo%5Bwdth,wght%5D.ttf",
    "archivo-700": RAW + "ofl/archivo/Archivo%5Bwdth,wght%5D.ttf",

    # shared monospace for data, units and captions
    "mono-400": RAW + "ofl/ibmplexmono/IBMPlexMono-Regular.ttf",

    # Mockup D only: a classical serif for the understated, donor-facing direction.
    "serif-400": RAW + "ofl/ebgaramond/EBGaramond%5Bwght%5D.ttf",
    "serif-600": RAW + "ofl/ebgaramond/EBGaramond%5Bwght%5D.ttf",
    "serif-italic": RAW + "ofl/ebgaramond/EBGaramond-Italic%5Bwght%5D.ttf",
}

# Variable fonts need pinning to a static instance before subsetting.
INSTANCE = {
    "plex-400": {"wght": 400, "wdth": 100},
    "plex-700": {"wght": 700, "wdth": 100},
    "archivo-cond": {"wght": 700, "wdth": 62},   # narrow + heavy, to echo the logo
    "archivo-400": {"wght": 400, "wdth": 100},
    "archivo-700": {"wght": 700, "wdth": 100},
    "serif-400": {"wght": 400},
    "serif-600": {"wght": 600},
    "serif-italic": {"wght": 400},
}

GLYPHS = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789"
    " .,;:!?'\"()[]{}/\\|-_+=*&%#@$<>~^`"
    "\u00b7\u00d7\u00b5\u2192\u2190\u2018\u2019\u201c\u201d\u2026\u00a9\u00b0\u2013\u2014"
    "\u00e9\u00e8\u00ea\u00fc\u00f6\u00e4\u00f1\u00e7\u00c9\u00dc\u00d6\u00c4"
)


def fetch(url: str) -> Path:
    name = url.rsplit("/", 1)[-1].replace("%5B", "[").replace("%5D", "]").replace(",", "_")
    dst = CACHE / name
    if not dst.exists():
        print("  downloading", name)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=90) as r:
            dst.write_bytes(r.read())
    return dst


def build(role: str, src) -> int:
    path = src if isinstance(src, Path) else fetch(src)
    font = TTFont(str(path))

    if role in INSTANCE and "fvar" in font:
        from fontTools.varLib import instancer
        font = instancer.instantiateVariableFont(font, INSTANCE[role], updateFontNames=False)

    opts = subset.Options()
    opts.flavor = "woff"
    opts.desubroutinize = True
    opts.layout_features = ["kern", "liga", "calt"]
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    sub = subset.Subsetter(options=opts)
    sub.populate(text=GLYPHS)
    sub.subset(font)
    font.flavor = "woff"
    buf = io.BytesIO()
    font.save(buf)
    data = buf.getvalue()
    (OUT / f"font-{role}.b64.txt").write_text(base64.b64encode(data).decode("ascii"))
    print(f"  {role:16s} {len(data) / 1024:6.1f} KB")
    return len(data)


total = 0
for role, src in FACES.items():
    try:
        total += build(role, src)
    except Exception as e:                                    # noqa: BLE001
        print(f"  !! {role}: {type(e).__name__}: {e}", file=sys.stderr)
print(f"total {total / 1024:.1f} KB woff  (~{total * 1.34 / 1024:.0f} KB as base64)")
