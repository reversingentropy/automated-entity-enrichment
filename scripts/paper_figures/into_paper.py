"""
Put the new figures, their captions and the Section 6 corrections into a copy of the paper, as tracked changes.

    uv run python scripts/paper_figures/into_paper.py

Reads the paper, never writes it: the copy is docs/paper-figures-proposed.docx. Every change is a Word tracked change
by "Claude", to accept or reject one by one: the old figure images deleted and the new ones inserted, Figure 5 and
its caption added, two captions and three sentences of Section 6 edited. Checks before saving that rejecting every
change gives back the paper's text exactly, and prints the word count before the references, before and after.
"""

import copy
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.shared import Cm

ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "docs" / ("Designing for the Reviewer A Human-in-the-Loop AI Pipeline for News-Driven Knowledge Base "
                        "Maintenance at the National Library and Archives Board.docx")
OUT = ROOT / "docs" / "paper-figures-proposed.docx"
FIGS = ROOT / "data" / "dist" / "paper-figures"
AUTHOR, WHEN = "Claude", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
_ids = iter(range(90001, 99999))

# the paper's sentences, and what replaces them
EDITS = [
    ("Figure 2. ", "showing identity verification, field-level review, and description diff.",
     "on the Section 2 example: (a) identity verification, (b) field-level review and (c) description diff."),
    ("Figure 4. ", " (exploratory one-off check, indicative only)", ""),
    ("A natural question is how far", "it was run beside gemini-3.8-flash on stored decisions",
     "it was run against the pipeline's stored decisions"),
    ("A natural question is how far", "Starting from 3,747 articles, gemini-3.8-flash kept",
     "Starting from 3,747 articles, the nightly Gemini model kept"),
    ("A natural question is how far",
     "Because neither set of relevance decisions was compared against human labels in this experiment, these figures "
     "measure agreement and downstream workload rather than precision or recall.",
     "With no human labels here, these figures measure agreement and workload, not precision or recall."),
    ("A natural question is how far", "At resolution, both models matched the same 61 records out of 2,281 entities.",
     "At resolution, Jev and the stored answers each matched 61 in 100 of 2,281 held-out entities to an existing "
     "record."),
    ("On the 48 cards decided by a reviewer",
     "On the 48 cards decided by a reviewer, the human amended 39 records, created 6 new records, and judged 3 not worth "
     "a record. With Jev making the decisions and Gemini generating any required text, the same 48 cards became 8 "
     "amendments, 18 no-change decisions, 12 new records, 2 not-worth decisions, and 8 cases dropped before review. Jev "
     "reached the reviewer's final outcome on 16 of the 48 cards (33%), answering in milliseconds compared to roughly 33 "
     "seconds per card.",
     "Figure 5 compares the 48 cards a reviewer decided with two replays on stored data. Had the stored proposals "
     "been accepted unreviewed, they would have matched the reviewer's outcome on 43 of the 48; with Jev deciding, "
     "and the stored text reused, on 16 (33%), in milliseconds against roughly 33 seconds per card. Most of the gap "
     "comes from replacing the model, not from removing the person."),
]
FIG5_AFTER = "On the 48 cards decided by a reviewer"
FIG5_CAPTION = ("Figure 5. Outcomes on 48 pilot cards: decided by one reviewer; the stored proposals accepted "
                "unreviewed (41 from the archive's internal model); Jev's decisions, unreviewed. Outcome kinds only; "
                "cards chosen partly where they disagreed.")


def mark(tag: str):
    el = docx.oxml.OxmlElement(tag)
    el.set(qn("w:id"), str(next(_ids)))
    el.set(qn("w:author"), AUTHOR)
    el.set(qn("w:date"), WHEN)
    return el


def as_deleted(run):
    """Wrap a run in a tracked deletion; its text becomes deleted text."""
    d = mark("w:del")
    run.addprevious(d)
    d.append(run)
    for t in run.findall(qn("w:t")):
        t.tag = qn("w:delText")
    return d


def as_inserted(run, after):
    i = mark("w:ins")
    after.addnext(i)
    i.append(run)
    return i


def text_run(template, text: str):
    r = docx.oxml.OxmlElement("w:r")
    rpr = template.find(qn("w:rPr")) if template is not None else None
    if rpr is not None:
        r.append(copy.deepcopy(rpr))
    t = docx.oxml.OxmlElement("w:t")
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text
    r.append(t)
    return r


def split_run(run, at: int):
    """Split a text run at a character offset; returns the second half (or None at the end)."""
    t = run.find(qn("w:t"))
    s = t.text or ""
    if at <= 0 or at >= len(s):
        return None
    tail = copy.deepcopy(run)
    t.text = s[:at]
    tail.find(qn("w:t")).text = s[at:]
    tail.find(qn("w:t")).set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    run.addnext(tail)
    return tail


def replace(paragraph, old: str, new: str):
    """Tracked replacement of `old` with `new` in one paragraph, across however many runs it spans."""
    runs = [r for r in paragraph._p.findall(qn("w:r")) if r.find(qn("w:t")) is not None]
    full = "".join(r.find(qn("w:t")).text or "" for r in runs)
    at = full.find(old)
    assert at >= 0, (old[:60], full[:120])
    end = at + len(old)
    # split runs so that old starts and ends on run boundaries
    pos = 0
    for r in list(runs):
        s = r.find(qn("w:t")).text or ""
        a, b = pos, pos + len(s)
        if a < at < b:
            split_run(r, at - a)
        pos = b
    runs = [r for r in paragraph._p.findall(qn("w:r")) if r.find(qn("w:t")) is not None]
    pos = 0
    for r in list(runs):
        s = r.find(qn("w:t")).text or ""
        a, b = pos, pos + len(s)
        if a < end < b:
            split_run(r, end - a)
        pos = b
    runs = [r for r in paragraph._p.findall(qn("w:r")) if r.find(qn("w:t")) is not None]
    pos, gone = 0, []
    for r in runs:
        s = r.find(qn("w:t")).text or ""
        if pos >= at and pos + len(s) <= end and s:
            gone.append(r)
        pos += len(s)
    template = copy.deepcopy(gone[0])
    last = None
    for r in gone:
        last = as_deleted(r)
    if new:
        as_inserted(text_run(template, new), last)


def picture_run(doc, paragraph, path: Path, width_cm: float = 15.2):
    run = paragraph.add_run()
    run.add_picture(str(path), width=Cm(width_cm))
    return run._r


def swap_figure(doc, paragraph, path: Path):
    """Delete every image in the paragraph and insert the new one after them, tracked."""
    old = [r for r in paragraph._p.findall(qn("w:r")) if r.find(".//" + qn("w:drawing")) is not None]
    assert old, "no image in this paragraph"
    new = picture_run(doc, paragraph, path)
    last = None
    for r in old:
        last = as_deleted(r)
    as_inserted(new, last)


def new_paragraph_after(anchor, like):
    """A new, tracked paragraph after `anchor`, formatted like `like`."""
    p = docx.oxml.OxmlElement("w:p")
    ppr = like._p.find(qn("w:pPr"))
    ppr = copy.deepcopy(ppr) if ppr is not None else docx.oxml.OxmlElement("w:pPr")
    rpr = ppr.find(qn("w:rPr"))
    if rpr is None:
        rpr = docx.oxml.OxmlElement("w:rPr")
        ppr.append(rpr)
    rpr.append(mark("w:ins"))     # the paragraph mark itself is inserted
    p.append(ppr)
    anchor._p.addnext(p)
    return docx.text.paragraph.Paragraph(p, anchor._parent)


def plain(doc, accept: bool) -> list[str]:
    """The text as Word shows it with every change accepted, or every change rejected."""
    out = []
    for p in doc.paragraphs:
        if not accept and p._p.find(qn("w:pPr") + "/" + qn("w:rPr") + "/" + qn("w:ins")) is not None:
            continue
        s = []
        for el in p._p.iter():
            inside = {a.tag for a in el.iterancestors()}
            if el.tag == qn("w:t") and (accept or qn("w:ins") not in inside):
                s.append(el.text or "")
            if el.tag == qn("w:delText") and not accept:
                s.append(el.text or "")
        out.append("".join(s))
    return out


def words_before_references(lines: list[str]) -> int:
    n = 0
    for t in lines:
        if t.strip().lower().startswith("references"):
            break
        n += len(t.split())
    return n


def find(doc, start: str):
    hits = [p for p in doc.paragraphs if p.text.strip().startswith(start)]
    assert len(hits) == 1, (start, len(hits))
    return hits[0]


def main() -> int:
    if not PAPER.exists():
        sys.exit(f"Not found: {PAPER}")
    original = docx.Document(str(PAPER))
    before = [p.text for p in original.paragraphs]
    doc = docx.Document(str(PAPER))
    images = [p for p in doc.paragraphs if p._p.find(".//" + qn("w:drawing")) is not None]
    assert len(images) == 4, f"expected the four figure paragraphs, found {len(images)}"
    for p, n in zip(images, (1, 2, 3, 4)):
        swap_figure(doc, p, FIGS / f"figure-{n}.png")
    for start, old, new in EDITS:
        replace(find(doc, start), old, new)
    # Figure 5 and its caption after the 48-card paragraph, laid out like Figure 4 and its caption
    anchor = next(p for p in doc.paragraphs if FIG5_AFTER in "".join(t.text or "" for t in p._p.iter(qn("w:delText"))))
    fig4_image, fig4_caption = images[3], find(doc, "Figure 4. ")
    img_p = new_paragraph_after(anchor, fig4_image)
    run = picture_run(doc, img_p, FIGS / "figure-5.png")
    ins = mark("w:ins")
    run.addprevious(ins)
    ins.append(run)
    cap_p = new_paragraph_after(img_p, fig4_caption)
    template = next(r for r in fig4_caption._p.iter(qn("w:r")) if r.find(qn("w:t")) is not None)
    ins = mark("w:ins")
    cap_p._p.append(ins)
    ins.append(text_run(template, FIG5_CAPTION))

    rejected = [t for t in plain(doc, accept=False)]
    assert rejected == before, "rejecting every change does not give back the paper"
    accepted = plain(doc, accept=True)
    doc.save(str(OUT))
    reopened = docx.Document(str(OUT))
    count = lambda d: len(d.element.body.findall(".//" + qn("w:drawing")))
    assert count(reopened) == count(original) + 5, "the new images are not all in the copy"   # 6 old (now deleted) + 5 new
    deleted = len(reopened.element.body.findall(".//" + qn("w:del") + "//" + qn("w:drawing")))
    inserted = len(reopened.element.body.findall(".//" + qn("w:ins") + "//" + qn("w:drawing")))
    assert (deleted, inserted) == (6, 5), (deleted, inserted)
    print(f"Wrote {OUT.relative_to(ROOT)}")
    print(f"Words before the references: {words_before_references(before)} now, {words_before_references(accepted)} with every change accepted")
    print("Rejecting every change gives back the paper's text exactly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
