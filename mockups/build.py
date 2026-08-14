"""Assemble each mockup in src/ into a page in out/, plus the shared files it links to.

Templates use these placeholders:
    {{FONTS}}            -> @font-face rules pointing at the linked woff subsets
    {{MARK}}             -> the circuit-brain logo mark as inline SVG (stroke: currentColor)
    {{IMG:name}}         -> URL of assets/<name>.webp
    {{VIDEO:name}}       -> URL of assets/<name>.mp4   (a looping clip)
    {{SCRIPT:name}}      -> <script src> for a linked script: `engine`, or one of
                            LINKED_SCRIPTS, each of which defines one global
    {{PARTIAL:name}}     -> contents of src/partials/<name>
    {{DATA:name}}        -> contents of assets/<name>_b64.json, pasted in as a literal
    {{JSON:name}}        -> contents of assets/<name>.json, minified, as a JS literal

The last two inline their payload. The deployed A2 and NS pages use {{SCRIPT:...}} instead;
{{DATA}} and {{JSON}} remain for the older comparison mockups, which are single files on
purpose so one of them can be mailed to somebody as an attachment.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).parent
ASSETS = ROOT / "assets"
SRC = ROOT / "src"
OUT = ROOT / "out"

# ---------------------------------------------------------------------------
# Linked assets
#
# These pages used to inline every font, clip, recording and portrait as base64,
# which is right for emailing somebody a single self-contained file and wrong for
# a site: the homepage came to 2.6 MB, and because it was all *inside* the HTML,
# none of it could be cached -- the same fonts and the same 141-neuron recording
# were downloaded again in full on every page.
#
# Now each of those is written into out/assets/ under a content-hashed name and
# referenced by URL. The hash is what makes this safe to cache: the file name
# changes whenever the bytes do, so a stale copy can never be served, and the
# assets themselves never need to expire. It also means the browser fetches only
# what a page actually renders -- all four typeface families ship, but a font is
# only requested if something on the page is set in it.
# ---------------------------------------------------------------------------
ASSET_DIR = "assets"
_asset_out = OUT          # which build's assets/ we are writing into
_emitted: dict[str, str] = {}   # logical name -> URL, so one file is written once


def _emit(name: str, data: bytes) -> str:
    """Write `data` into <out>/assets/ under a content-hashed name; return its URL.

    `name` is a logical name with an extension, e.g. "clip_wave.mp4"; any slashes
    in it are flattened, since assets/ is one flat directory."""
    key = f"{_asset_out}|{name}"
    if key in _emitted:
        return _emitted[key]
    flat = name.replace("/", "-")
    stem, _, ext = flat.rpartition(".")
    url = f"{ASSET_DIR}/{stem}.{hashlib.sha256(data).hexdigest()[:10]}.{ext}"
    p = _asset_out / url
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_bytes(data)
    _emitted[key] = url
    return url


def _use_asset_dir(dest: Path) -> None:
    """Point the emitters at `dest` and clear its assets/, so a rebuild cannot leave
    the previous build's hashed files lying around next to the current ones."""
    global _asset_out
    _asset_out = dest
    d = dest / ASSET_DIR
    if d.is_dir():
        for f in d.iterdir():
            if f.is_file():
                f.unlink()

# Candidate typeface options. Each supplies a condensed display face and a body face at two
# weights; one monospace is shared by all of them. `adjust` normalizes x-height against Open
# Sans so switching option doesn't change how big the running text looks.
FONT_OPTIONS = {
    "opensans": {"adjust": 100.0},
    "plex": {"adjust": 103.7},
    "barlow": {"adjust": 102.9},
    "archivo": {"adjust": 100.2},
}


def _face(family: str, weight: str, role: str, adjust: float | None = None) -> str:
    p = ASSETS / f"font-{role}.b64.txt"
    if not p.exists():
        raise SystemExit(f"missing font subset {p.name} -- run tools/make_fonts.py")
    extra = f"size-adjust:{adjust}%;" if adjust and adjust != 100.0 else ""
    # The subsets are stored as base64 text because that is what inlining needed; a
    # linked face wants the woff itself, so decode on the way out.
    url = _emit(f"font-{role}.woff", base64.b64decode(p.read_text().strip()))
    return (
        f"@font-face{{font-family:'{family}';font-style:normal;font-weight:{weight};"
        f"font-display:block;{extra}"
        f"src:url({url}) format('woff')}}"
    )


def fonts_css() -> str:
    """All four switchable sans options plus the shared mono (mockups A, B, C)."""
    out = [_face("SLMono", "400", "mono-400")]
    for slug, cfg in FONT_OPTIONS.items():
        out.append(_face(f"SLC-{slug}", "700", f"{slug}-cond"))
        out.append(_face(f"SLS-{slug}", "400", f"{slug}-400", cfg["adjust"]))
        out.append(_face(f"SLS-{slug}", "700", f"{slug}-700", cfg["adjust"]))
    return "\n".join(out)


def fonts_css_serif() -> str:
    """Just what mockup D needs -- EB Garamond plus one sans and the mono -- rather than
    all four switchable options, which would add ~180 KB it never uses."""
    return "\n".join([
        _face("SLSerif", "400", "serif-400"),
        _face("SLSerif", "600", "serif-600"),
        (_face("SLSerif", "400", "serif-italic")
         .replace("font-style:normal", "font-style:italic")),
        _face("SLS-plex", "400", "plex-400"),
        _face("SLS-plex", "700", "plex-700"),
        _face("SLMono", "400", "mono-400"),
    ])


def img_uri(name: str) -> str:
    # a name may include a subfolder, e.g. people/nick-steinmetz
    return _emit(f"{name}.webp", (ASSETS / f"{name}.webp").read_bytes())


def video_uri(name: str) -> str:
    return _emit(f"{name}.mp4", (ASSETS / f"{name}.mp4").read_bytes())


def json_literal(name: str) -> str:
    """Inline a data file as a JS object literal, dropping the _comment key."""
    d = json.loads((ASSETS / f"{name}.json").read_text(encoding="utf-8"))
    if isinstance(d, dict):
        d.pop("_comment", None)
    return json.dumps(d, separators=(",", ":"))


# What a page can pull in as a linked <script> rather than pasting into its own. Each of
# these defines one global; they are classic scripts, so the browser runs them in document
# order and the global is already there by the time the page's inline script runs. That is
# what keeps this a pure size change -- no async, no callbacks, no page code touched.
#
# The recording is the reason this matters more than the byte count suggests: every page
# draws the sliver of raster behind the header, so the same 149 KB used to be re-downloaded
# on every single navigation. Linked, it is fetched once for the whole site.
LINKED_SCRIPTS = {
    "raster": ("RASTER", lambda: (ASSETS / "raster_b64.json").read_text(encoding="utf-8")),
    "widefield": ("WIDEFIELD",
                  lambda: (ASSETS / "widefield_b64.json").read_text(encoding="utf-8")),
    "np2_units": ("NP2", lambda: json_literal("np2_units")),
}


def script_tag(name: str) -> str:
    """{{SCRIPT:name}} -> a <script src> for one of the linked scripts, or for the engine."""
    if name == "engine":
        js = (SRC / "partials" / "engine.js").read_text(encoding="utf-8")
    else:
        var, load = LINKED_SCRIPTS[name]
        js = f"var {var} = {load().strip()};\n"
    # Same reasoning as ascii_safe(): escape rather than rely on the host's charset.
    js = "".join(c if ord(c) < 128 else f"\\u{ord(c):04x}" for c in js)
    return f'<script src="{_emit(name + ".js", js.encode("ascii"))}"></script>'


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
         "fourteen fifteen sixteen seventeen eighteen nineteen").split()
_TENS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty"}


def spell(n: int) -> str:
    """Small-number word form, so a headline like 'Nineteen of us' can't go stale."""
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    base = _TENS.get(tens * 10, str(n))
    return base if not ones else f"{base}-{_ONES[ones]}"


def people_count() -> int:
    return len(json.loads((ROOT / "data/people.json").read_text(encoding="utf-8")))


def people_html() -> str:
    """Render the People grid from data/people.json -- the same data the old Jekyll site
    used, so adding or removing a lab member stays a one-line edit to a data file."""
    recs = json.loads((ROOT / "data/people.json").read_text(encoding="utf-8"))

    def monograms(records) -> dict[str, str]:
        """Assign a short, unique label to each person who has no photo.

        Two people can share initials (Alex Wu / Annie Wu), and the obvious fallback can
        collide with somebody else's initials in turn (Alex -> "AL" clashes with Allison
        Lin). So allocate in display order, taking the first candidate not already used.
        """
        used: set[str] = set()
        chosen: dict[str, str] = {}
        for r in records:
            if r.get("img"):
                continue
            parts = [w for w in r["name"].split() if w]
            first, last = parts[0], parts[-1]
            candidates = [
                "".join(w[0] for w in parts)[:2],
                first[:2],
                first[0] + last[:2],
                first[:3],
            ]
            label = next((c.upper() for c in candidates if c.upper() not in used),
                         (first[:2] + str(len(used))).upper())
            used.add(label)
            chosen[r["name"]] = label
        return chosen

    mono_of = monograms(recs)
    out = []
    for p in recs:
        name, role, url = p["name"], p.get("role", ""), p.get("url") or ""
        if p.get("img"):
            uri = img_uri(f"people/{p['img']}")
            face = f'<img class="person__pic" src="{uri}" alt="" loading="lazy">'
        else:
            face = (f'<div class="person__pic person__pic--mono">'
                    f'{_esc(mono_of[name])}</div>')
        tag, attrs = ("a", f' href="{_esc(url)}"') if url else ("div", "")
        out.append(
            f'<{tag} class="person has-corner"{attrs}>{face}'
            f'<span class="person__n">{_esc(name)}</span>'
            f'<span class="person__r">{_esc(role)}</span></{tag}>'
        )
    return "\n      ".join(out)


_SPLIT = re.compile(r"(<(?:script|style)\b[^>]*>.*?</(?:script|style)>)", re.S | re.I)
_TAGGED = re.compile(r"(<(script|style)\b[^>]*>)(.*)(</\2>)", re.S | re.I)


def ascii_safe(html: str) -> str:
    """Escape every non-ASCII character so the page renders correctly even when the host
    serves it without a charset (we never get to emit our own <meta charset>).

    HTML text takes numeric character references; script bodies take JS \\uXXXX escapes,
    because character references are *not* decoded inside <script> or <style>.
    """
    out = []
    for part in _SPLIT.split(html):
        m = _TAGGED.match(part or "")
        if not m:
            out.append("".join(c if ord(c) < 128 else f"&#{ord(c)};" for c in part))
            continue
        open_tag, kind, body, close_tag = m.groups()
        if kind.lower() == "style":
            bad = {c for c in body if ord(c) >= 128}
            if bad:
                raise SystemExit(
                    "non-ASCII in a <style> block cannot be escaped safely: "
                    + " ".join(f"{c!r} (U+{ord(c):04X})" for c in sorted(bad))
                )
            out.append(part)
        else:
            body = "".join(c if ord(c) < 128 else f"\\u{ord(c):04x}" for c in body)
            out.append(open_tag + body + close_tag)
    return "".join(out)


GROUP_LABEL = {
    "pi": "PI", "staff": "Staff", "postdoc": "Postdoc",
    "grad": "Graduate", "undergrad": "Undergraduate", "highschool": "High school",
}


def people_rows() -> str:
    """The same roster as a table body, for mockup C's data-dense treatment."""
    recs = json.loads((ROOT / "data/people.json").read_text(encoding="utf-8"))
    out = []
    for p in recs:
        name, url = p["name"], p.get("url") or ""
        cell = f'<a href="{_esc(url)}">{_esc(name)}</a>' if url else _esc(name)
        year = (p.get("joined") or "")[:4]
        out.append(
            f'<tr><td>{cell}</td><td class="n">{_esc(p.get("role", ""))}</td>'
            f'<td class="n">{_esc(GROUP_LABEL.get(p.get("group", ""), ""))}</td>'
            f'<td class="n">{_esc(year)}</td></tr>'
        )
    return "\n          ".join(out)


def people_quiet() -> str:
    """A restrained list treatment for mockup D: small round portrait, name, role."""
    recs = json.loads((ROOT / "data/people.json").read_text(encoding="utf-8"))
    out = []
    for p in recs:
        name, role = p["name"], p.get("role", "")
        if p.get("img"):
            uri = img_uri(f"people/{p['img']}")
            face = f'<img class="who__face" src="{uri}" alt="" loading="lazy">'
        else:
            face = '<span class="who__face who__face--none" aria-hidden="true"></span>'
        out.append(
            f'<li class="who">{face}<span class="who__t">'
            f'<span class="who__n">{_esc(name)}</span>'
            f'<span class="who__r">{_esc(role)}</span></span></li>'
        )
    return "\n        ".join(out)


# Author copies of the papers, served from static/papers/ alongside the site.
PDF_BASE = "papers/"


def pdf_url(name: str) -> str:
    """Percent-encode the filename: these are 'Author et al - year - Journal.pdf'."""
    return PDF_BASE + urllib.parse.quote(name)


JOURNAL_SHORT = {
    "Nature Reviews Neuroscience": "Nat Rev Neurosci", "Nature Communications": "Nat Commun",
    "Nature Methods": "Nat Methods", "Nature Methods (in press)": "Nat Methods",
    "Nature Neuroscience": "Nat Neurosci", "Current Biology": "Curr Biol",
    "Journal of Neuroscience": "J Neurosci", "Nature Protocols": "Nat Protoc",
    "PLoS Computational Biology": "PLoS Comput Biol", "Cell Reports": "Cell Rep",
    "Journal of Neurophysiology": "J Neurophysiol", "Scientific Data": "Sci Data",
}
# Which of pubs.json's many tags to expose as filters, and what to call them.
DEFAULT_PUB_FILTER = "selected"      # which chip the Publications page opens on
PUB_FILTERS = [("all", "Everything"), ("selected", "Selected"), ("neuropixels", "Neuropixels"),
               ("brainwide", "Brain-wide"), ("widefield", "Cortex-wide imaging"), ("vision", "Vision"),
               ("behavior", "Behavior"), ("methods", "Methods &amp; tools"),
               ("preprint", "Preprints")]


def _authors(p: dict) -> str:
    a = p.get("authors_short") or p.get("authors") or []
    a = [re.sub(r"<[^>]+>", "", str(x)) for x in a]
    if len(a) > 12:
        a = a[:9] + ["..."] + a[-2:]
    return ", ".join(a)


def pubs_all() -> str:
    """Every paper in data/pubs.json, newest first, grouped under its year."""
    papers = json.loads((ROOT / "data/pubs.json").read_text(encoding="utf-8"))["papers"]
    papers.sort(key=lambda p: (-int(p["year"]), p.get("title", "")))
    out, year = [], None
    for p in papers:
        if p["year"] != year:
            year = p["year"]
            out.append(f'<h3 class="pubyear" data-year="{_esc(year)}">{_esc(year)}</h3>')
        tags = " ".join(p.get("tags", []))
        jr = p.get("journal", "")
        pdf = ""
        if p.get("pdflink"):
            pdf = (f'<a class="pub__pdf" href="{_esc(pdf_url(p["pdflink"]))}" '
                   f'title="Author copy (PDF)">PDF</a>')
        out.append(
            f'<div class="pub" data-tags="{_esc(tags)}">'
            f'<a class="pub__hit" href="{_esc(p.get("link", "#"))}">'
            f'<span class="pub__yr">{_esc(year)}</span><span>'
            f'<span class="pub__t">{_esc(p.get("title", ""))}</span>'
            f'<span class="pub__a">{_esc(_authors(p))}</span></span>'
            f'<span class="pub__j">{_esc(JOURNAL_SHORT.get(jr, jr))}</span></a>{pdf}</div>'
        )
    return "\n      ".join(out)


def pubs_recent(n: int = 8) -> str:
    """The front page shows only 'selected' papers, newest first -- the same judgement the
    Publications page defaults to, rather than whatever happened to appear most recently."""
    papers = json.loads((ROOT / "data/pubs.json").read_text(encoding="utf-8"))["papers"]
    papers = [p for p in papers if "selected" in p.get("tags", [])]
    papers.sort(key=lambda p: (-int(p["year"]), p.get("title", "")))
    out = []
    for p in papers[:n]:
        jr = p.get("journal", "")
        # same two-part row as the Publications page: .pub is the container, .pub__hit
        # carries the grid and the link. They must stay in step -- when only this one
        # still emitted a bare <a class="pub">, the front-page list lost its layout.
        pdf = ""
        if p.get("pdflink"):
            pdf = (f'<a class="pub__pdf" href="{_esc(pdf_url(p["pdflink"]))}" '
                   f'title="Author copy (PDF)">PDF</a>')
        out.append(
            f'<div class="pub" data-tags="{_esc(" ".join(p.get("tags", [])))}">'
            f'<a class="pub__hit" href="{_esc(p.get("link", "#"))}">'
            f'<span class="pub__yr">{_esc(p["year"])}</span><span>'
            f'<span class="pub__t">{_esc(p.get("title", ""))}</span>'
            f'<span class="pub__a">{_esc(_authors(p))}</span></span>'
            f'<span class="pub__j">{_esc(JOURNAL_SHORT.get(jr, jr))}</span></a>{pdf}</div>'
        )
    return "\n      ".join(out)


def pub_chips_two() -> str:
    """Just Selected / Everything, for the personal site: the same filter mechanism as the
    lab page, without the topic chips that page needs."""
    return "\n      ".join(
        f'<button class="chip" data-tag="{t}" '
        f'aria-pressed="{"true" if t == DEFAULT_PUB_FILTER else "false"}">{label}</button>'
        for t, label in (("selected", "Selected"), ("all", "Everything")))


def pub_chips() -> str:
    return "\n      ".join(
        f'<button class="chip" data-tag="{t}" '
        f'aria-pressed="{"true" if t == DEFAULT_PUB_FILTER else "false"}">'
        f"{label}</button>" for t, label in PUB_FILTERS)


GROUP_LABEL = {
    "pi": "Principal investigator", "staff": "Staff scientists", "postdoc": "Postdocs",
    "grad": "Graduate students", "undergrad": "Undergraduate scientists",
    "highschool": "High-school students", "rotation": "Rotation students",
}


def people_by_group() -> str:
    """The People page: the same cards as the front page, under a heading per cohort."""
    recs = json.loads((ROOT / "data/people.json").read_text(encoding="utf-8"))
    cards = people_html().split("\n      ")          # reuse the card markup exactly
    assert len(cards) == len(recs), (len(cards), len(recs))
    out, group = [], None
    for rec, card in zip(recs, cards):
        g = rec.get("group", "")
        if g != group:
            if group is not None:
                out.append("</div>")
            group = g
            out.append(f'<h3 class="cohort">{_esc(GROUP_LABEL.get(g, g))}</h3>')
            out.append('<div class="people">')
        out.append(card)
    out.append("</div>")
    return "\n      ".join(out)


# Alumni are grouped by position in the same order as the current roster, so the two
# halves of the People page read the same way down the page.
ALUMNI_ORDER = ["Research scientist", "Postdoc", "Graduate student", "Rotation student",
                "MD-PhD Rotation Student", "Undergraduate", "High-school student"]
ALUMNI_HEADING = {"Research scientist": "Research scientists", "Postdoc": "Postdocs",
                  "Graduate student": "Graduate students",
                  "Rotation student": "Rotation students",
                  "MD-PhD Rotation Student": "Rotation students",
                  "Undergraduate": "Undergraduate scientists",
                  "High-school student": "High-school students"}


def alumni_html() -> str:
    """Former members grouped by position, most recent departure first within each group."""
    rows = json.loads((ROOT / "data/alumni.json").read_text(encoding="utf-8"))["alumni"]

    def last_year(a):
        years = re.findall(r"\d{4}", a["years"])
        return int(years[-1]) if years else 0

    def rank(a):
        role = a.get("role", "")
        return ALUMNI_ORDER.index(role) if role in ALUMNI_ORDER else len(ALUMNI_ORDER)

    rows = sorted(rows, key=lambda a: (rank(a), -last_year(a), a["name"].split()[-1]))
    out, group = [], None
    for a in rows:
        heading = ALUMNI_HEADING.get(a.get("role", ""), a.get("role", ""))
        if heading != group:
            group = heading
            if out:
                out.append("</ul>")
            out.append(f'<h3 class="cohort">{_esc(group)}</h3>')
            out.append('<ul class="alumni">')
        note = a.get("note", "")
        now = a.get("now", "")
        tail = ""
        if now:
            tail = f'<span class="alum__now">now {_esc(now)}</span>'
        elif note:
            tail = f'<span class="alum__note">{_esc(note)}</span>'
        out.append(
            f'<li class="alum"><span class="alum__y">{_esc(a["years"])}</span>'
            f'<span class="alum__n">{_esc(a["name"])}</span>'
            f'<span class="alum__r">{_esc(a["role"])}</span>{tail}</li>'
        )
    return "\n        ".join(out)


def resources_html() -> str:
    """The Open Science columns. Growing this section means editing data/resources.json."""
    cols = json.loads((ROOT / "data/resources.json").read_text(encoding="utf-8"))["columns"]
    out = []
    for c in cols:
        rows = "\n          ".join(
            f'<li><a href="{_esc(i["href"])}">{_esc(i["label"])}</a>'
            + (f' &mdash; {_esc(i["note"])}' if i.get("note") else "")
            + (f'<span class="res__cite">{_esc(i["cite"])}</span>' if i.get("cite") else "")
            + "</li>"
            for i in c["items"])
        out.append(f'<div class="res__col">\n        <h3>{_esc(c["title"])}</h3>\n'
                   f"        <ul>\n          {rows}\n        </ul>\n      </div>")
    return "\n      ".join(out)


NEWS_KIND = {"paper": "Paper", "award": "Award", "lab": "Lab"}
MONTHS = ("", "January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December")


def _news_date(raw: str) -> tuple:
    """'2026-06' -> (('2026', '06'), 'June 2026'). A bare '2026' is allowed and sorts to the
    end of its year, so an entry whose month is unknown needs no invented one."""
    y, _, m = str(raw).partition("-")
    m = m[:2].lstrip("0")
    if m.isdigit() and 1 <= int(m) <= 12:
        return (y, f"{int(m):02d}"), f"{MONTHS[int(m)]} {y}"
    return (y, "00"), y


def _news_items() -> list:
    items = json.loads((ROOT / "data/news.json").read_text(encoding="utf-8"))["item"]
    return sorted(items, key=lambda i: _news_date(i["date"])[0], reverse=True)


def _news_item_html(it: dict, with_kind: bool = True) -> str:
    kind = it.get("kind", "lab")
    label = _news_date(it["date"])[1]
    title = _esc(it["title"])
    if it.get("link"):
        title = f'<a class="item__link" href="{_esc(it["link"])}">{title}</a>'
    note = f'<p>{_esc(it["note"])}</p>' if it.get("note") else ""
    chip = (f'<span class="kind kind--{kind}">{NEWS_KIND.get(kind, kind)}</span>'
            if with_kind else "")
    return (f'<article class="item"><p class="item__d">{label}{chip}</p>'
            f'<div class="item__b"><h3>{title}</h3>{note}</div></article>')


def news_all() -> str:
    out, year = [], None
    for it in _news_items():
        y = _news_date(it["date"])[0][0]
        if y != year:
            year = y
            out.append(f'<h3 class="pubyear">{_esc(year)}</h3>')
        out.append(_news_item_html(it))
    return "\n      ".join(out)


def news_latest(n: int = 3) -> str:
    """The front page carries the newest few, without the kind chips."""
    return "\n      ".join(_news_item_html(it, with_kind=False) for it in _news_items()[:n])


CV_PDF = "Steinmetz_CV_2026-08-11.pdf"


def family_links(name: str, deploy: bool = False) -> dict:
    """Where the shared nav and footer should point, given which page they land in.

    A and A2 are separate families with their own homepage and subpages; A also has no
    People page, so its People link stays an anchor on the front page."""
    if name.startswith("ns-"):
        # deploy=True writes the names the personal site actually serves
        return {"HOME": "index.html" if deploy else "ns-index.html",
                "PUBS": "publications.html" if deploy else "ns-publications.html",
                "CV": CV_PDF}
    if name.startswith("a2-"):
        return {"HOME": "a2-signal.html", "PUBS": "a2-publications.html",
                "NEWS": "a2-news.html", "PEOPLE_PAGE": "a2-people.html",
                "JOIN": "a2-join.html", "CONTACT": "a2-contact.html",
                "TEACHING": "a2-teaching.html", "ARRAY": "a2-array.html"}
    # A predates these pages, so its links stay where they were
    return {"HOME": "a-signal.html", "PUBS": "a-publications.html",
            "NEWS": "a-news.html", "PEOPLE_PAGE": "a-signal.html#people",
            "JOIN": "a-signal.html#join", "CONTACT": "a-signal.html#join",
            "TEACHING": "a-signal.html", "ARRAY": "a2-array.html"}


def render(template: str, name: str = "a-signal.html", deploy: bool = False) -> str:
    s = template
    # {{PEOPLE}} renders the roster grid; the nav's link token is {{PEOPLE_PAGE}}. They are
    # different lengths on purpose -- a prefix collision here silently ate the grid once.

    # Partials first, and repeatedly: a partial may itself contain {{FONTS}}, {{MARK}} or
    # even another {{PARTIAL:...}}, and those must still get expanded.
    def partial_sub_first(m: re.Match) -> str:
        return (SRC / "partials" / m.group(1)).read_text(encoding="utf-8")

    for _ in range(6):
        s, n = re.subn(r"\{\{PARTIAL:([\w.\-]+)\}\}", partial_sub_first, s)
        if not n:
            break
    else:
        raise SystemExit("partial includes nested more than 6 deep - probably a cycle")

    for k, v in family_links(name, deploy).items():
        s = s.replace("{{" + k + "}}", v)
    s = s.replace("{{FONTS_SERIF}}", fonts_css_serif())
    s = s.replace("{{FONTS}}", fonts_css())
    s = s.replace("{{MARK}}", (ASSETS / "mark.svg").read_text(encoding="utf-8").strip())
    s = s.replace("{{PEOPLE}}", people_html())
    s = s.replace("{{PEOPLE_ROWS}}", people_rows())
    s = s.replace("{{PEOPLE_QUIET}}", people_quiet())
    s = s.replace("{{PUBS_ALL}}", pubs_all())
    s = s.replace("{{PUB_CHIPS}}", pub_chips())
    s = s.replace("{{PUB_CHIPS_TWO}}", pub_chips_two())
    s = s.replace("{{PUBS_RECENT}}", pubs_recent())
    s = s.replace("{{PUB_COUNT}}", str(len(json.loads(
        (ROOT / "data/pubs.json").read_text(encoding="utf-8"))["papers"])))
    s = s.replace("{{NEWS_ALL}}", news_all())
    s = s.replace("{{NEWS_LATEST}}", news_latest())
    np2 = json.loads((ASSETS / "np2_units.json").read_text(encoding="utf-8"))
    s = s.replace("{{NP2_UNITS}}", f'{np2["n_units"]:,}')
    s = s.replace("{{NP2_WINDOW}}", str(int(np2["window_s"])))
    s = s.replace("{{NP2_DEEPEST}}", f'{max(u["d"] for u in np2["units"]):,.0f}')
    s = s.replace("{{RESOURCES}}", resources_html())
    s = s.replace("{{PEOPLE_BY_GROUP}}", people_by_group())
    s = s.replace("{{ALUMNI}}", alumni_html())
    s = s.replace("{{ALUMNI_COUNT}}", str(len(json.loads(
        (ROOT / "data/alumni.json").read_text(encoding="utf-8"))["alumni"])))
    s = s.replace("{{PEOPLE_COUNT_WORD}}", spell(people_count()).capitalize())
    s = s.replace("{{PEOPLE_COUNT}}", str(people_count()))

    def data_sub(m: re.Match) -> str:
        return (ASSETS / f"{m.group(1)}_b64.json").read_text(encoding="utf-8").strip()

    def img_sub(m: re.Match) -> str:
        return img_uri(m.group(1))

    def partial_sub(m: re.Match) -> str:
        return (SRC / "partials" / m.group(1)).read_text(encoding="utf-8")

    s = re.sub(r"\{\{PARTIAL:([\w.\-]+)\}\}", partial_sub, s)
    s = re.sub(r"\{\{DATA:([\w\-]+)\}\}", data_sub, s)
    s = re.sub(r"\{\{IMG:([\w\-/]+)\}\}", img_sub, s)
    s = re.sub(r"\{\{VIDEO:([\w\-]+)\}\}", lambda m: video_uri(m.group(1)), s)
    s = re.sub(r"\{\{JSON:([\w\-]+)\}\}", lambda m: json_literal(m.group(1)), s)
    s = re.sub(r"\{\{SCRIPT:([\w\-]+)\}\}", lambda m: script_tag(m.group(1)), s)

    left = re.findall(r"\{\{[^}]+\}\}", s)
    if left:
        raise SystemExit(f"unresolved placeholders: {sorted(set(left))}")
    return ascii_safe(s)


# Without a viewport meta, phones lay the page out at ~980 CSS px and then scale the
# result down to fit, so 16 px text arrives at about 6 px. These pages used to be
# fragments with no <html>/<head>, because they were previewed inside a wrapper that
# supplied one; served directly by GitHub Pages they need their own. The parser closes
# <head> itself at the first <header>, so title and style still land in the head.
DOC_HEAD = (
    "<!doctype html>\n"
    '<html lang="en">\n'
    "<head>\n"
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
)
DOC_TAIL = "\n</body>\n</html>\n"


GENERATED_BANNER = (
    "<!-- GENERATED FILE - DO NOT EDIT.\n"
    "     Every edit here is destroyed the next time build.py runs.\n"
    "     Prose lives in src/{name}; lists live in data/*.json. See EDITING.md. -->\n")


MANIFEST = OUT / ".build-manifest.json"
# Which built page a deployment serves at "/". Copied, not symlinked, so the output
# folder can be published as-is by any static host.
HOMEPAGE = "a2-signal.html"


def _digest(b: str) -> str:
    return hashlib.sha256(b.encode("utf-8")).hexdigest()


PERSONAL = {"ns-index.html": "index.html", "ns-publications.html": "publications.html"}


def build_personal() -> int:
    """Write the personal site under out-personal/, with the filenames it actually serves.

    Separate from out/ because the same source has to link to ns-index.html when it is
    previewed alongside the lab site, and to index.html once it is the site."""
    dest = ROOT / "out-personal"
    dest.mkdir(exist_ok=True)
    _use_asset_dir(dest)
    for src_name, out_name in PERSONAL.items():
        html = (GENERATED_BANNER.format(name=src_name) + DOC_HEAD
                + render((SRC / src_name).read_text(encoding="utf-8"), src_name, deploy=True)
                + DOC_TAIL)
        (dest / out_name).write_text(html, encoding="utf-8")
        print(f"{out_name:26s} {len(html)/1024:8.1f} KB")
    for f in sorted((ROOT / "static").iterdir()):
        if f.is_file() and f.name.startswith("Steinmetz_CV"):
            (dest / f.name).write_bytes(f.read_bytes())
            print(f"{f.name:26s} {f.stat().st_size/1024:8.1f} KB  (static)")
    # GitHub Pages runs Jekyll over a user site by default; we are already built
    (dest / ".nojekyll").write_text("", encoding="utf-8")
    return 0


# Where the Jekyll site's URLs went. Those paths are in Google, in email signatures and on
# other labs' pages, and every one of them would 404 the day this site replaces it. GitHub
# Pages has no redirect config, so each becomes a directory with a meta-refresh index.html;
# the canonical link is there so search engines fold the old URL into the new one rather
# than indexing both.
REDIRECTS = {
    "about": "a2-signal.html#research",
    "pubs": "a2-publications.html",
    "all_pubs": "a2-publications.html",
    "people": "a2-people.html",
    "news": "a2-news.html",
    "join": "a2-join.html",
    "contact": "a2-contact.html",
    "teaching": "a2-teaching.html",
    "neusci490": "a2-teaching.html",
    "shared": "a2-signal.html#resources",
    "dei": "a2-join.html",
    "ethics": "a2-join.html",
    "categories": "index.html",
    # postings that were their own page; the Join page is where they live now
    "npultra_pd": "a2-join.html",
    "ibl_scientist": "a2-join.html",
}

SITE_URL = "https://www.steinmetzlab.net/"


def _stub(target: str, page: str, title: str, body: str) -> str:
    """`target` is relative, so a stub still works under a github.io sub-path; `page` is
    the same destination as a site-root path, which is what the canonical link needs."""
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<meta http-equiv="refresh" content="0; url={target}">\n'
        f'<link rel="canonical" href="{SITE_URL}{page}">\n'
        f"<title>{title}</title>\n</head>\n<body>\n"
        f'<p>{body} <a href="{target}">Continue to the Steinmetz Lab site</a>.</p>\n'
        "</body>\n</html>\n"
    )


def write_redirects() -> None:
    """The old permalinks, and a 404 for everything else (including the news posts, which
    lived at /:title/ and cannot be mapped one to one)."""
    for old, new in REDIRECTS.items():
        d = OUT / old
        d.mkdir(exist_ok=True)
        (d / "index.html").write_text(
            _stub("../" + new, new, "Moved", "This page has moved."), encoding="utf-8")
    # 404.html is served for any depth of missing path, so its link has to be root-relative
    # rather than "../": there is no telling how far down the URL that produced it was.
    (OUT / "404.html").write_text(
        _stub("/", "", "Page not found",
              "That page is not part of the redesigned site."), encoding="utf-8")
    print(f"{'redirects':22s} {len(REDIRECTS) + 1:8d} stubs")


def main(argv: list[str]) -> int:
    if "--personal" in argv:
        return build_personal()
    OUT.mkdir(exist_ok=True)
    _use_asset_dir(OUT)
    force = "--force" in argv
    argv = [a for a in argv if a != "--force"]
    targets = argv[1:] or [p.name for p in sorted(SRC.glob("*.html"))]

    # Editing out/*.html by hand is the one mistake that silently loses work: the next
    # build overwrites it with no trace. We record what we wrote, so if a built file no
    # longer matches, someone edited it and we stop instead of destroying the change.
    seen = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    if not force:
        edited = [n for n in targets
                  if n in seen and (OUT / n).exists()
                  and _digest((OUT / n).read_text(encoding="utf-8")) != seen[n]]
        if edited:
            print("!! these built files have been edited since the last build:")
            for n in edited:
                print(f"     out/{n}")
            print("   Those edits belong in src/ or data/ -- see EDITING.md.")
            print("   To discard them and rebuild anyway: python build.py --force")
            return 1

    for name in targets:
        src = SRC / name
        if not src.exists():
            print(f"!! missing {src}")
            return 1
        html = (GENERATED_BANNER.format(name=name) + DOC_HEAD
                + render(src.read_text(encoding="utf-8"), name) + DOC_TAIL)
        dst = OUT / name
        dst.write_text(html, encoding="utf-8")
        seen[name] = _digest(html)
        print(f"{name:22s} {len(html)/1024:8.1f} KB")
    # static/ ships verbatim: PDFs and anything else that has to stay a real file rather
    # than being inlined as a data URI.
    static = ROOT / "static"
    if static.is_dir():
        n_sub, sz_sub = 0, 0
        for f in sorted(static.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(static)
            dst = OUT / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists() and dst.stat().st_size == f.stat().st_size:
                pass                      # skip rewriting hundreds of MB every build
            else:
                dst.write_bytes(f.read_bytes())
            if rel.parent == Path("."):
                print(f"{f.name:22s} {f.stat().st_size/1024:8.1f} KB  (static)")
            else:
                n_sub += 1
                sz_sub += f.stat().st_size
        if n_sub:
            print(f"{'static subfolders':22s} {sz_sub/1e6:8.1f} MB  ({n_sub} files)")

    write_redirects()
    # GitHub Pages runs Jekyll over a branch-published site by default, and a leading
    # underscore anywhere would make it drop files. We are already built.
    (OUT / ".nojekyll").write_text("", encoding="utf-8")

    if HOMEPAGE in targets:
        index = (OUT / HOMEPAGE).read_text(encoding="utf-8")
        (OUT / "index.html").write_text(index, encoding="utf-8")
        seen["index.html"] = _digest(index)
        print(f'{"index.html":22s} {len(index)/1024:8.1f} KB  (copy of {HOMEPAGE})')
    MANIFEST.write_text(json.dumps(seen, indent=1, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
