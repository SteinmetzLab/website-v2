"""Write a refreshed CV from cv20250905.docx with the publication tables brought current.

The two tables are (year | authors + title | journal). Some entries keep authors and title
in one cell as two paragraphs, others split them over two rows; both shapes exist in the
source. New entries are cloned from an existing row so they inherit its formatting exactly,
rather than being built from scratch with guessed styles.

Usage:  python tools/update_cv.py
"""
import copy
import re
from pathlib import Path

import docx

NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CVDIR = Path(r"D:/Dropbox/cv/cv")
SRC = CVDIR / "cv20250905.docx"
DST = CVDIR / "cv20260811.docx"

# --- new entries, newest first, as (year, authors, title, journal) ----------------------
# Author strings follow the CV's own convention: surnames only, "..." for an elision,
# asterisks for co-first authorship.
SENIOR_NEW = [
    ("2026", "Ye, Ladd, MacKenzie, Kolich, Li, Birman, Bull, Daigle, Tasic, Zeng, Steinmetz",
     "Brain-wide Topographic Coordination of Rotating Waves", "Science"),
    ("", "Shaker, Schroeter, Birman, Steinmetz",
     "The Midbrain Reticular Formation in Contextual Control of Perceptual Decisions", "Neuron"),
    ("", "Siegle, Steinmetz",
     "Large-scale Electrophysiology at Single-spike Resolution | review", "Nature Rev Neurosci"),
    ("", "Roth, Chapuis, Winter, The International Brain Laboratory, ..., Horwitz, Steinmetz",
     "A Flexible Quality Metric for Electrophysiological Recordings Across Brain Regions "
     "and Species | preprint", "bioRxiv"),
    ("2025", "Lu, Li, Ladd, Matveev, Deole, Shea-Brown, Kutz, Steinmetz",
     "Benchmarking Probabilistic Time Series Forecasting Models on Neural Activity | preprint",
     "arXiv"),
]
MIDDLE_NEW = [
    ("2026", "Hjort, Garrett, Gordon, Ancell, Trzeciak, Lu, Bruchas, Witten, Steinmetz, Stuber",
     "Prefrontal to Ventral Tegmental Area Dynamics Drive Contingency Degradation", "Nature"),
]

# --- entries already present whose status or title has changed -------------------------
# match on a distinctive fragment; (find, field, new value)
UPDATES = [
    (0, "Ultra-High Density Neuropixels", "journal", "Neuron"),
    (1, "Neuropixels Opto", "journal", "Nature Methods"),
    (1, "Neuropixels Opto", "title_strip_preprint", ""),
    (1, "A Multimodal Approach for Visualization", "journal", "Nature Comm"),
    (1, "A Multimodal Approach for Visualization", "title",
     "A Multimodal Approach for Visualizing and Identifying Electrophysiological Cell Types"),
    (1, "Active Filtering of Sequences", "journal", "Neuron"),
    (1, "Active Filtering of Sequences", "title",
     "Recurrent Cortical Networks Encode Natural Sensory Statistics via Sequence Filtering"),
]
# superseded by the published version added above
DELETE = [(0, "Brain-wide Topographic Coordination of Traveling Spiral Waves")]


def cell_text(tc):
    return re.sub(r"\s+", " ", "".join(t.text or "" for t in tc.iter(NS + "t"))).strip()


def set_para(p, text):
    """Replace a paragraph's text, keeping the first run's formatting.

    Works on the w:t elements rather than direct w:r children: a run can sit inside a
    hyperlink or a smart tag, in which case findall("r") returns nothing and the old text
    survives untouched."""
    ts = list(p.iter(NS + "t"))
    if not ts:
        # an empty cell has a bare w:p; give it a run so there is something to write into
        r = p.makeelement(NS + "r", {})
        t = p.makeelement(NS + "t", {})
        r.append(t)
        p.append(r)
        ts = [t]
    ts[0].text = text
    ts[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    for extra in ts[1:]:
        extra.text = ""


def set_cell(tc, texts):
    """Set a cell's paragraphs from a list of strings, reusing existing paragraphs."""
    paras = tc.findall(NS + "p")
    for i, text in enumerate(texts):
        if i < len(paras):
            set_para(paras[i], text)
        else:                                   # clone the last paragraph for extra lines
            new = copy.deepcopy(paras[-1])
            set_para(new, text)
            tc.append(new)
            paras = tc.findall(NS + "p")
    for extra in paras[len(texts):]:            # drop any paragraphs we did not need
        tc.remove(extra)


def find_row(tbl, fragment):
    for i, tr in enumerate(tbl._tbl.findall(NS + "tr")):
        if fragment.lower() in " ".join(cell_text(tc) for tc in tr.findall(NS + "tc")).lower():
            return i
    return None


def main():
    d = docx.Document(str(SRC))
    tables = {0: d.tables[0], 1: d.tables[1]}
    report = []

    # ---- updates in place ------------------------------------------------------------
    for ti, frag, field, value in UPDATES:
        tbl = tables[ti]
        trs = tbl._tbl.findall(NS + "tr")
        i = find_row(tbl, frag)
        if i is None:
            report.append(f"  !! could not find {frag!r} in table {ti}")
            continue
        tcs = trs[i].findall(NS + "tc")
        if field == "journal":
            # the journal may sit on this row or the row that carries the author names
            target = tcs[-1]
            if not cell_text(target):
                target = trs[i - 1].findall(NS + "tc")[-1]
            old = cell_text(target)
            set_cell(target, [value])
            report.append(f"  table {ti}: {frag[:40]!r} journal {old!r} -> {value!r}")
        elif field == "title":
            for tc in tcs:
                if frag.lower() in cell_text(tc).lower():
                    paras = tc.findall(NS + "p")
                    for p in paras:
                        if frag.lower() in cell_text(p).lower():
                            set_para(p, value)
                    report.append(f"  table {ti}: retitled -> {value[:56]!r}")
                    break
        elif field == "title_strip_preprint":
            for tc in tcs:
                for p in tc.findall(NS + "p"):
                    txt = cell_text(p)
                    if frag.lower() in txt.lower() and "| preprint" in txt:
                        set_para(p, txt.replace(" | preprint", ""))
                        report.append(f"  table {ti}: dropped the preprint label on {frag[:36]!r}")

    # ---- deletions -------------------------------------------------------------------
    for ti, frag in DELETE:
        tbl = tables[ti]
        i = find_row(tbl, frag)
        if i is None:
            report.append(f"  !! could not find {frag!r} to remove")
            continue
        trs = tbl._tbl.findall(NS + "tr")
        tr = trs[i]
        # If this row carries its year's label, the label has to survive the deletion:
        # otherwise the entries below it silently join the year above.
        year = cell_text(tr.findall(NS + "tc")[0])
        year_tc = copy.deepcopy(tr.findall(NS + "tc")[0])
        # the title may live on the following row; remove that too if it is a bare title
        nxt = trs[i + 1] if i + 1 < len(trs) else None
        tr.getparent().remove(tr)
        if nxt is not None and "Steinmetz" not in " ".join(cell_text(tc) for tc in nxt.findall(NS + "tc")):
            if frag.lower() in " ".join(cell_text(tc) for tc in nxt.findall(NS + "tc")).lower():
                nxt.getparent().remove(nxt)
        if year:
            after = tbl._tbl.findall(NS + "tr")[i]
            old_tc = after.findall(NS + "tc")[0]
            if not cell_text(old_tc):
                after.replace(old_tc, year_tc)
                report.append(f"  table {ti}: moved the {year} label down to the next entry")
        report.append(f"  table {ti}: removed the superseded preprint {frag[:44]!r}")

    # ---- insertions, cloning the first row so formatting carries over ----------------
    for ti, new in ((0, SENIOR_NEW), (1, MIDDLE_NEW)):
        tbl = tables[ti]
        template = copy.deepcopy(tbl._tbl.findall(NS + "tr")[0])
        first = tbl._tbl.findall(NS + "tr")[0]
        # anchor stays put, so inserting in list order keeps that order
        for year, authors, title, journal in new:
            tr = copy.deepcopy(template)
            tcs = tr.findall(NS + "tc")
            set_cell(tcs[0], [year])
            set_cell(tcs[1], [authors, title])
            set_cell(tcs[2], [journal])
            first.addprevious(tr)
            report.append(f"  table {ti}: added {title[:52]!r}")
    # A year is labelled once, on the first entry of that year. Inserting ahead of an
    # existing block can repeat it, so blank any label that matches the one above it.
    for ti, tbl in tables.items():
        seen = None
        for tr in tbl._tbl.findall(NS + "tr"):
            tcs = tr.findall(NS + "tc")
            if not tcs:
                continue
            y = cell_text(tcs[0])
            if not y:
                continue
            if y == seen:
                set_cell(tcs[0], [""])
                report.append(f"  table {ti}: removed a repeated {y} label")
            else:
                seen = y

    d.save(str(DST))
    print(f"wrote {DST}")
    print("\n".join(report))


if __name__ == "__main__":
    main()
