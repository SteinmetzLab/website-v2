"""Assemble each mockup in src/ into a single self-contained HTML file in out/.

Templates use these placeholders:
    {{FONTS}}            -> @font-face rules with the subset Open Sans faces inlined
    {{MARK}}             -> the circuit-brain logo mark as inline SVG (stroke: currentColor)
    {{DATA:name}}        -> contents of assets/<name>_b64.json  (real recording data)
    {{IMG:name}}         -> data: URI for assets/<name>.webp
    {{VIDEO:name}}       -> data: URI for assets/<name>.mp4   (a looping clip)
    {{JSON:name}}        -> contents of assets/<name>.json, minified, as a JS literal
    {{PARTIAL:name}}     -> contents of src/partials/<name>
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
ASSETS = ROOT / "assets"
SRC = ROOT / "src"
OUT = ROOT / "out"

# Candidate typeface options. Each supplies a condensed display face and a body face at two
# weights; one monospace is shared by all of them. `adjust` normalises x-height against Open
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
    return (
        f"@font-face{{font-family:'{family}';font-style:normal;font-weight:{weight};"
        f"font-display:block;{extra}"
        f"src:url(data:font/woff;base64,{p.read_text().strip()}) format('woff')}}"
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
    p = ASSETS / f"{name}.webp"
    return "data:image/webp;base64," + base64.b64encode(p.read_bytes()).decode("ascii")


def video_uri(name: str) -> str:
    p = ASSETS / f"{name}.mp4"
    return "data:video/mp4;base64," + base64.b64encode(p.read_bytes()).decode("ascii")


def json_literal(name: str) -> str:
    """Inline a data file as a JS object literal, dropping the _comment key."""
    d = json.loads((ASSETS / f"{name}.json").read_text(encoding="utf-8"))
    if isinstance(d, dict):
        d.pop("_comment", None)
    return json.dumps(d, separators=(",", ":"))


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
            uri = ("data:image/webp;base64,"
                   + base64.b64encode((ASSETS / "people" / f"{p['img']}.webp").read_bytes())
                   .decode("ascii"))
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
            uri = ("data:image/webp;base64,"
                   + base64.b64encode((ASSETS / "people" / f"{p['img']}.webp").read_bytes())
                   .decode("ascii"))
            face = f'<img class="who__face" src="{uri}" alt="" loading="lazy">'
        else:
            face = '<span class="who__face who__face--none" aria-hidden="true"></span>'
        out.append(
            f'<li class="who">{face}<span class="who__t">'
            f'<span class="who__n">{_esc(name)}</span>'
            f'<span class="who__r">{_esc(role)}</span></span></li>'
        )
    return "\n        ".join(out)


JOURNAL_SHORT = {
    "Nature Reviews Neuroscience": "Nat Rev Neurosci", "Nature Communications": "Nat Commun",
    "Nature Methods": "Nat Methods", "Nature Methods (in press)": "Nat Methods",
    "Nature Neuroscience": "Nat Neurosci", "Current Biology": "Curr Biol",
    "Journal of Neuroscience": "J Neurosci", "Nature Protocols": "Nat Protoc",
    "PLoS Computational Biology": "PLoS Comput Biol", "Cell Reports": "Cell Rep",
    "Journal of Neurophysiology": "J Neurophysiol", "Scientific Data": "Sci Data",
}
# Which of pubs.json's many tags to expose as filters, and what to call them.
PUB_FILTERS = [("all", "Everything"), ("selected", "Selected"), ("neuropixels", "Neuropixels"),
               ("brainwide", "Brain-wide"), ("widefield", "Widefield"), ("vision", "Vision"),
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
        out.append(
            f'<a class="pub" href="{_esc(p.get("link", "#"))}" data-tags="{_esc(tags)}">'
            f'<span class="pub__yr">{_esc(year)}</span><span>'
            f'<span class="pub__t">{_esc(p.get("title", ""))}</span>'
            f'<span class="pub__a">{_esc(_authors(p))}</span></span>'
            f'<span class="pub__j">{_esc(JOURNAL_SHORT.get(jr, jr))}</span></a>'
        )
    return "\n      ".join(out)


def pub_chips() -> str:
    return "\n      ".join(
        f'<button class="chip" data-tag="{t}" aria-pressed="{"true" if t == "all" else "false"}">'
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


def alumni_html() -> str:
    """Former members as a compact table: who, what they were, when, where they went."""
    rows = json.loads((ROOT / "data/alumni.json").read_text(encoding="utf-8"))["alumni"]
    out = []
    for a in rows:
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


def family_links(name: str) -> dict:
    """Where the shared nav and footer should point, given which page they land in.

    A and A2 are separate families with their own homepage and subpages; A also has no
    People page, so its People link stays an anchor on the front page."""
    if name.startswith("a2-"):
        return {"HOME": "a2-signal.html", "PUBS": "a2-publications.html",
                "NEWS": "a2-news.html", "PEOPLE_PAGE": "a2-people.html",
                "JOIN": "a2-join.html", "CONTACT": "a2-contact.html",
                "TEACHING": "a2-teaching.html", "ETHICS": "a2-ethics.html"}
    # A predates these pages, so its links stay where they were
    return {"HOME": "a-signal.html", "PUBS": "a-publications.html",
            "NEWS": "a-news.html", "PEOPLE_PAGE": "a-signal.html#people",
            "JOIN": "a-signal.html#join", "CONTACT": "a-signal.html#join",
            "TEACHING": "a-signal.html", "ETHICS": "a-signal.html"}


def render(template: str, name: str = "a-signal.html") -> str:
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

    for k, v in family_links(name).items():
        s = s.replace("{{" + k + "}}", v)
    s = s.replace("{{FONTS_SERIF}}", fonts_css_serif())
    s = s.replace("{{FONTS}}", fonts_css())
    s = s.replace("{{MARK}}", (ASSETS / "mark.svg").read_text(encoding="utf-8").strip())
    s = s.replace("{{PEOPLE}}", people_html())
    s = s.replace("{{PEOPLE_ROWS}}", people_rows())
    s = s.replace("{{PEOPLE_QUIET}}", people_quiet())
    s = s.replace("{{PUBS_ALL}}", pubs_all())
    s = s.replace("{{PUB_CHIPS}}", pub_chips())
    s = s.replace("{{PUB_COUNT}}", str(len(json.loads(
        (ROOT / "data/pubs.json").read_text(encoding="utf-8"))["papers"])))
    s = s.replace("{{NEWS_ALL}}", news_all())
    s = s.replace("{{NEWS_LATEST}}", news_latest())
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
    s = re.sub(r"\{\{IMG:([\w\-]+)\}\}", img_sub, s)
    s = re.sub(r"\{\{VIDEO:([\w\-]+)\}\}", lambda m: video_uri(m.group(1)), s)
    s = re.sub(r"\{\{JSON:([\w\-]+)\}\}", lambda m: json_literal(m.group(1)), s)

    left = re.findall(r"\{\{[^}]+\}\}", s)
    if left:
        raise SystemExit(f"unresolved placeholders: {sorted(set(left))}")
    return ascii_safe(s)


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


def main(argv: list[str]) -> int:
    OUT.mkdir(exist_ok=True)
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
        html = (GENERATED_BANNER.format(name=name)
                + render(src.read_text(encoding="utf-8"), name))
        dst = OUT / name
        dst.write_text(html, encoding="utf-8")
        seen[name] = _digest(html)
        print(f"{name:22s} {len(html)/1024:8.1f} KB")
    # static/ ships verbatim: PDFs and anything else that has to stay a real file rather
    # than being inlined as a data URI.
    static = ROOT / "static"
    if static.is_dir():
        for f in sorted(static.iterdir()):
            if f.is_file():
                (OUT / f.name).write_bytes(f.read_bytes())
                print(f"{f.name:22s} {f.stat().st_size/1024:8.1f} KB  (static)")

    if HOMEPAGE in targets:
        index = (OUT / HOMEPAGE).read_text(encoding="utf-8")
        (OUT / "index.html").write_text(index, encoding="utf-8")
        seen["index.html"] = _digest(index)
        print(f'{"index.html":22s} {len(index)/1024:8.1f} KB  (copy of {HOMEPAGE})')
    MANIFEST.write_text(json.dumps(seen, indent=1, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
