"""
The IFLA talk: "Designing for the Reviewer". Twenty minutes in the programme, five of them for questions,
so fifteen minutes of talking: thirteen slides, then the thank-you slide, then four backup slides for questions.

    .venv/bin/python scripts/build_talk.py

Writes data/dist/designing-for-the-reviewer.pptx (speaker notes inside), data/dist/speaking-script.docx
(the same notes, printable, with the clock) and data/dist/talk-preview/*.png (a rough drawing of every slide,
for checking the layout where PowerPoint is not at hand).

It is built on the symposium's own template, as src/export/slides.py is, but with a different idea of a
slide: one claim, one picture, as few words as will carry it. The figures are from docs/numbers.md (28 September
2026), the paper, and data/finetune/. The screenshots in data/slides/ are of the real review desk.
Every text box is measured with real font metrics before it is placed; a box that would overflow stops the build.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lxml import etree  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.enum.dml import MSO_LINE  # noqa: E402
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE  # noqa: E402
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN  # noqa: E402
from pptx.oxml.ns import qn  # noqa: E402
from pptx.util import Inches, Pt  # noqa: E402

from src.export.slides import TEMPLATE, as_pptx, clone, named, set_text  # noqa: E402

OUT = ROOT / "data/dist"
SHOTS = ROOT / "data/slides"
TITLE = "Designing for the Reviewer"
SUBTITLE = "A human-in-the-loop AI pipeline for news-driven authority file maintenance"
PRESENTER = "Ashwin Nair"
INSTITUTION = "National Library Board, Singapore"
EMAIL = "nair.ashwin1994@gmail.com"

NAVY, RED, INK, TEAL, GREY = (RGBColor.from_string(c) for c in ("071E4B", "BE1737", "0E2841", "156082", "5A6370"))
PALE, TEAL_PALE, RED_PALE = (RGBColor.from_string(c) for c in ("F1F3F6", "E3EFF4", "FBEAED"))
GREEN, GREEN_PALE, AMBER, AMBER_PALE = (RGBColor.from_string(c) for c in ("1F7A45", "E5F2EA", "9A6212", "FBF1DC"))
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LINE = RGBColor.from_string("C9CED6")
FONT_NAME = "Arial"        # the template's own face (Nimbus Sans) is Arial's twin, and its metrics are known here

L, R = 0.6, 12.73
W = R - L

# ---- measuring text, so nothing overflows --------------------------------------------------

_FILES = {False: "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf", True: "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf"}
_loaded: dict = {}


def _font(bold, px=200):
    key = (bold, px)
    if key not in _loaded:
        _loaded[key] = ImageFont.truetype(_FILES[bold], px)
    return _loaded[key]


def _wide(ch):
    return ord(ch) >= 0x2E80


def width_pt(text, pt, bold):
    cjk = sum(1 for c in text if _wide(c))
    rest = "".join(c for c in text if not _wide(c))
    return _font(bold).getlength(rest) * pt / 200 + cjk * pt


def wrap(text, pt, bold, box_pt):
    """The lines a paragraph breaks into at this size and width."""
    lines = []
    for raw in text.split("\n"):
        cur = ""
        for token in _tokens(raw):
            trial = cur + token
            if cur and width_pt(trial.rstrip(), pt, bold) > box_pt:
                lines.append(cur.rstrip())
                cur = token.lstrip()
            else:
                cur = trial
        lines.append(cur.rstrip())
    return lines


def _tokens(text):
    out, cur = [], ""
    for ch in text:
        if _wide(ch):
            if cur:
                out.append(cur); cur = ""
            out.append(ch)
        else:
            cur += ch
            if ch == " ":
                out.append(cur); cur = ""
    if cur:
        out.append(cur)
    return out


def P(text="", size=18, bold=False, color=INK, align="l", after=0, italic=False, runs=None, bullet=False):
    return dict(text=text, size=size, bold=bold, color=color, align=align, after=after, italic=italic, runs=runs, bullet=bullet)


def need_pt(paras, box_pt):
    total = 0.0
    for p in paras:
        text = "".join(t for t, _ in p["runs"]) if p["runs"] else p["text"]
        bold = p["bold"] or bool(p["runs"] and any(o.get("bold") for _, o in p["runs"]))
        size = max([p["size"]] + [o.get("size", 0) for _, o in (p["runs"] or [])])
        total += len(wrap(text, size, bold, box_pt - (BULLET_PT if p["bullet"] else 0))) * size * 1.2 + p["after"]
    return total


# ---- drawing on a slide --------------------------------------------------------------------

BULLET_PT = 18          # the hanging indent of a bullet, in points
TAG = ["?"]
PROBLEMS: list[str] = []


def _fill(shape, color):
    if color is None:
        shape.fill.background()
    else:
        shape.fill.solid()
        shape.fill.fore_color.rgb = color


def tbox(slide, x, y, w, h, paras, anchor="t", fill=None, line=None, radius=None, inset=(0.1, 0.06), line_w=1.5, shape=None):
    """A text box (or a filled shape holding text), checked to fit."""
    if fill is not None or line is not None or radius is not None or shape is not None:
        kind = shape or (MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE)
        box = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
        box.shadow.inherit = False
        if radius and kind == MSO_SHAPE.ROUNDED_RECTANGLE:
            box.adjustments[0] = min(0.5, radius / min(w, h))
        _fill(box, fill)
        if line is None:
            box.line.fill.background()
        else:
            box.line.color.rgb = line
            box.line.width = Pt(line_w)
    else:
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = Inches(inset[0])
    frame.margin_top = frame.margin_bottom = Inches(inset[1])
    frame.vertical_anchor = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}[anchor]
    inner_w, inner_h = (w - 2 * inset[0]) * 72, (h - 2 * inset[1]) * 72
    used = need_pt(paras, inner_w)
    if used > inner_h + 1:
        first = (paras[0]["text"] or "".join(t for t, _ in paras[0]["runs"] or []))[:48]
        PROBLEMS.append(f"slide {TAG[0]}: text needs {used / 72:.2f} in, box gives {inner_h / 72:.2f} in: {first!r}")
    for i, p in enumerate(paras):
        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        para.alignment = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}[p["align"]]
        para.space_after = Pt(p["after"])
        para.space_before = Pt(0)
        para.line_spacing = 1.0
        if p["bullet"]:
            pPr = para._p.get_or_add_pPr()
            pPr.set("marL", str(BULLET_PT * 12700))
            pPr.set("indent", str(-BULLET_PT * 12700))
            bu = etree.SubElement(pPr, qn("a:buChar"))
            bu.set("char", "•")
        for text, opts in (p["runs"] or [(p["text"], {})]):
            run = para.add_run()
            run.text = text
            f = run.font
            f.name = FONT_NAME
            f.size = Pt(opts.get("size", p["size"]))
            f.bold = opts.get("bold", p["bold"])
            f.italic = opts.get("italic", p["italic"])
            f.color.rgb = opts.get("color", p["color"])
            if opts.get("strike"):
                run._r.get_or_add_rPr().set("strike", "sngStrike")
    return box


def block(slide, x, y, w, h, color, radius=None, line=None, line_w=1.5, shape=None):
    kind = shape or (MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE)
    box = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    box.shadow.inherit = False
    if radius and kind == MSO_SHAPE.ROUNDED_RECTANGLE:
        box.adjustments[0] = min(0.5, radius / min(w, h))
    _fill(box, color)
    if line is None:
        box.line.fill.background()
    else:
        box.line.color.rgb = line
        box.line.width = Pt(line_w)
    return box


def arrow(slide, x1, y1, x2, y2, color=GREY, width=2.25):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = color
    c.line.width = Pt(width)
    tail = etree.SubElement(c.line._get_or_add_ln(), qn("a:tailEnd"))
    tail.set("type", "triangle")
    return c


def disc(slide, cx, cy, d, color, label, size=16):
    return tbox(slide, cx - d / 2, cy - d / 2, d, d, [P(label, size, True, WHITE, "c")], anchor="m", fill=color, shape=MSO_SHAPE.OVAL, inset=(0, 0))


def pill(slide, x, y, w, h, label, fill, color=WHITE, size=13):
    return tbox(slide, x, y, w, h, [P(label, size, True, color, "c")], anchor="m", fill=fill, radius=h / 2, inset=(0.05, 0.02))


def picture(slide, name, x, y, w=None, h=None, border=True):
    path = SHOTS / name
    im = Image.open(path)
    aspect = im.width / im.height
    if w is None:
        w = h * aspect
    if h is None:
        h = w / aspect
    pic = slide.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(w), Inches(h))
    if border:
        pic.line.color.rgb = LINE
        pic.line.width = Pt(1)
    return pic, w, h


# ---- the slides ----------------------------------------------------------------------------

def s_labour(s):
    """The problem, in one picture: a day's reading, and the few articles in it that matter."""
    x0, y0, cell, gap = 0.75, 1.95, 0.36, 0.1
    tbox(s, 0.6, 1.4, 5.0, 0.45, [P("ONE DAY, THREE SINGAPORE FEEDS", 13, True, GREY)], anchor="m", inset=(0.05, 0.04))
    hot = {9, 23, 44}
    for k in range(60):
        r, c = divmod(k, 10)
        block(s, x0 + c * (cell + gap), y0 + r * (cell + gap), cell, cell, RED if k in hot else LINE, radius=0.04)
    tbox(s, 0.6, 4.75, 5.3, 1.1, [P("60 Singapore articles a day", 20, True, NAVY, after=3), P("2 or 3 report a change to a record", 20, True, RED, after=3), P("The outlets publish more. These are their Singapore feeds.", 14, False, GREY)], inset=(0.05, 0.05))
    x1 = 6.1
    w = R - x1
    tbox(s, x1, 1.4, w, 1.7, [P("WHAT A RECORD IS", 12, True, GREY, after=4),
                              P("The library’s one agreed entry for a person, organisation or place: name, dates, posts, a short description. Other systems copy it.", 17, False, INK)],
         fill=PALE, radius=0.1, inset=(0.22, 0.14))
    tbox(s, x1, 3.25, w, 1.55, [P("THE LABOUR", 12, True, GREY, after=4),
                                P("To find the two or three, a person reads all sixty, every day, and that is only the Singapore feeds. Another outlet or language means more.", 17, False, INK)],
         fill=PALE, radius=0.1, inset=(0.22, 0.14))
    tbox(s, x1, 4.95, w, 1.2, [P("Can an AI do the reading, and leave people the deciding?", 24, True, WHITE)], anchor="m", fill=NAVY, radius=0.1, inset=(0.25, 0.1))
    tbox(s, L, 6.3, W, 0.65, [P("Live feed, 3 August to 28 September 2026: 3,511 articles from the outlets’ Singapore feeds, 149 passed our first filter. Our file, TTE, holds 52,437 name records that discovery systems, "
                                "the national archives, other agencies and VIAF draw on.", 13, False, GREY)], inset=(0.05, 0.04))


def s_pipeline(s):
    stages = [("1", "Ingest", "Titles and summaries from three news feeds", "no AI", False),
              ("2", "Relevance", "Titles only: does this change a record?", "AI", False),
              ("3", "Extraction", "People, places, facts, and one quoted sentence", "AI", False),
              ("4", "Retrieval", "Candidate records, by character similarity", "no AI", False),
              ("5", "Resolution", "Same entity? What does the record lack?", "AI", False),
              ("6", "A person", "Decides, then makes the change in TTE by hand", "", True)]
    gap = 0.3
    w = (W - 5 * gap) / 6
    for i, (n, name, what, tag, human) in enumerate(stages):
        x = L + i * (w + gap)
        tbox(s, x, 1.95, w, 2.35, [P(n, 14, True, RGBColor.from_string("F4A3B0") if human else TEAL, after=2), P(name, 19, True, WHITE if human else INK, after=6),
                                   P(what, 14, False, WHITE if human else INK)], fill=NAVY if human else PALE, radius=0.1, inset=(0.14, 0.1),
             line=None if human else LINE, line_w=1)
        if tag:
            pill(s, x + 0.14, 3.9, 0.8, 0.28, tag, TEAL if tag == "AI" else GREY, size=12)
        if i < 5:
            arrow(s, x + w + 0.02, 3.1, x + w + gap - 0.02, 3.1, GREY, 1.75)
    tbox(s, L, 1.45, 5 * w + 4 * gap, 0.4, [P("Runs on a schedule, unattended", 15, True, TEAL, "c")], anchor="m")
    block(s, L, 1.88, 5 * w + 4 * gap, 0.04, TEAL)
    tbox(s, L + 5 * (w + gap), 1.45, w, 0.4, [P("Human gate", 15, True, RED, "c")], anchor="m", inset=(0.02, 0.06))
    block(s, L + 5 * (w + gap), 1.88, w, 0.04, RED)
    stats = [("298,790", "articles read, 2015 to 2026"), ("28,090", "judged relevant"), ("48,696", "entities extracted"),
             ("9,844", "changes proposed to existing records")]
    for i, (big, label) in enumerate(stats):
        x = L + i * 3.07
        tbox(s, x, 4.65, 2.87, 1.45, [P(big, 36, True, NAVY, after=2), P(label, 15, False, GREY)], fill=WHITE, line=LINE, radius=0.1, line_w=1, inset=(0.2, 0.1))
    tbox(s, L, 6.3, W, 0.5, [P("As of 28 September 2026. Another 22,331 entities have no TTE record yet. None of the proposals has been through a formal evaluation.", 14, False, GREY)],
         anchor="m")


def s_editing(s):
    scale = 10.4 / 636
    tbox(s, L, 1.5, 10.5, 0.4, [P("A description in TTE, before: 636 characters", 17, True, INK)], anchor="m", inset=(0.02, 0.04))
    block(s, L, 1.95, 636 * scale, 0.7, NAVY, radius=0.06)
    tbox(s, L, 3.0, 10.5, 0.4, [P("After the model “merged” in a new fact: 405 characters", 17, True, INK)], anchor="m", inset=(0.02, 0.04))
    block(s, L, 3.45, 405 * scale, 0.7, TEAL, radius=0.06)
    block(s, L + 405 * scale, 3.45, 231 * scale, 0.7, RED_PALE, line=RED, line_w=2)
    tbox(s, L + 405 * scale, 3.45, 231 * scale, 0.7, [P("231 gone", 17, True, RED, "c")], anchor="m")
    tbox(s, L + 405 * scale - 3.3, 4.2, 6.6, 0.8, [P("His Navy career · ten years as Deputy Prime Minister · every constituency he held", 15, False, RED, "c")], anchor="t")
    tbox(s, L, 5.15, W, 0.5, [P("No error message. Nobody would notice without the old and new text side by side.", 20, True, INK)], anchor="m", inset=(0.02, 0.04))
    fixes = [("Shown as a diff", "what is added and what is removed, in colour"), ("We measure what survives", "counted against the old text only"),
             ("Heavy deletions get a warning", "before the reviewer sees the rewrite")]
    for i, (head, sub) in enumerate(fixes):
        x = L + i * 4.1
        tbox(s, x, 5.75, 3.9, 1.05, [P(head, 17, True, GREEN, after=2), P(sub, 14, False, GREY)], fill=GREEN_PALE, radius=0.1, inset=(0.2, 0.1), anchor="m")


def s_redesign(s):
    h = 3.45
    tbox(s, L, 1.3, 4.1, 0.6, [P("Version 3: two documents, one question, a stamp. It plays like Papers, Please.", 13, True, GREY)], anchor="m", inset=(0.02, 0.02))
    pic1, w1, h1 = picture(s, "desk-v3-identity.png", L, 1.95, h=h)
    x2 = L + w1 + 0.4
    tbox(s, x2, 1.3, 5.0, 0.6, [P("Redesign: one card, one question", 14, True, TEAL)], anchor="m", inset=(0.02, 0.02))
    pic2, w2, h2 = picture(s, "desk-new-identity.png", x2, 1.95, h=h)
    x3 = x2 + w2 + 0.4
    changes = ["One card per question", "The news always on top", "“In TTE now”, then “After you accept”", "Ticks and crosses, not paragraphs", "“No thanks” means discard"]
    tbox(s, x3, 1.3, R - x3, 0.6, [P("What changed", 14, True, TEAL)], anchor="m", inset=(0.02, 0.02))
    tbox(s, x3, 1.95, R - x3, h, [P(t, 15, True, INK, after=10, bullet=True) for t in changes], fill=TEAL_PALE, radius=0.1, inset=(0.18, 0.16))
    tbox(s, L, 5.75, W, 1.0, [P("“It feels like Tinder.”   A first-time user, outside the library", 24, True, INK, "c", italic=True)], anchor="m", fill=PALE, radius=0.1)


def b_numbers(s):
    rows = [("Articles collected", "295,279 archive + 3,511 live", "298,790"), ("Judged relevant", "27,941 + 149", "28,090  (9.4%)"),
            ("Entities extracted", "48,387 + 309", "48,696"), ("Matched, proposes a change", "9,779 + 65", "9,844"), ("Matched, nothing to add", "6,238 + 36", "6,274"),
            ("Not in TTE yet", "22,125 + 206", "22,331"), ("Unsure which record", "5,919 + 2", "5,921"), ("Decided by a reviewer", "0 + 0", "0")]
    tbox(s, L, 1.4, 5, 0.4, [P("Stage", 14, True, GREY)], anchor="m")
    tbox(s, 6.2, 1.4, 4, 0.4, [P("Archive + live", 14, True, GREY)], anchor="m")
    tbox(s, 10.2, 1.4, 2.5, 0.4, [P("Total", 14, True, GREY, "r")], anchor="m")
    for i, (a, b, c) in enumerate(rows):
        y = 1.85 + i * 0.58
        block(s, L, y + 0.52, W, 0.012, LINE)
        tbox(s, L, y, 5.5, 0.52, [P(a, 18, False, INK)], anchor="m")
        tbox(s, 6.2, y, 4, 0.52, [P(b, 16, False, GREY)], anchor="m")
        tbox(s, 10.2, y, 2.5, 0.52, [P(c, 18, True, NAVY, "r")], anchor="m")
    tbox(s, L, 6.55, W, 0.4, [P("As of 28 September 2026. TTE’s copy holds 52,437 name records; TTE as a whole holds about 1.8 million.", 13, False, GREY)], anchor="m", inset=(0.02, 0.02))


def b_small_model(s):
    rows = [("Flag everything", 0.19, "100"), ("mmBERT-small, frozen", 0.53, "50"), ("e5-small + logistic regression", 0.58, "45"),
            ("e5-small + gradient boosting", 0.61, "43"), ("Word counts + logistic regression", 0.66, "40"), ("e5-small + small neural net", 0.66, "35"),
            ("mmBERT-small, fine-tuned", 0.75, "25")]
    tbox(s, L, 1.4, 4.2, 0.4, [P("Approach", 14, True, GREY)], anchor="m")
    tbox(s, 4.8, 1.4, 4.9, 0.4, [P("F1 on the test year (higher is better)", 14, True, GREY)], anchor="m")
    tbox(s, 10.1, 1.4, 2.63, 0.4, [P("Passed on, per 100", 14, True, GREY, "r")], anchor="m", inset=(0.02, 0.06))
    for i, (name, f1, passed) in enumerate(rows):
        y = 1.88 + i * 0.6
        tbox(s, L, y, 4.2, 0.5, [P(name, 16, i == 6, INK)], anchor="m", inset=(0.02, 0.02))
        block(s, 4.8, y + 0.07, 4.2 * f1 / 0.8, 0.36, TEAL if i == 6 else (LINE if i == 0 else RGBColor.from_string("7FA9BC")), radius=0.05)
        tbox(s, 4.8 + 4.2 * f1 / 0.8 + 0.08, y, 0.8, 0.5, [P(f"{f1:.2f}", 16, True, INK)], anchor="m", inset=(0.02, 0.02))
        tbox(s, 10.1, y, 2.63, 0.5, [P(passed, 18, True, NAVY, "r")], anchor="m", inset=(0.02, 0.02))
    tbox(s, L, 6.15, W, 0.7, [P("Scored against the internal model’s labels, not people’s. On 69 hard cases a person judged, the fine-tuned model scores 0.22: it copies the labeller’s mistakes. “Passed on” is the share of articles sent to the next stage to keep 95% of the relevant ones.", 13, False, GREY)],
         anchor="m", inset=(0.02, 0.02))


def b_evaluation(s):
    cols = [("Three labelled sheets", ["Relevance: every article the pipeline passed, plus a stratified sample of what it rejected", "Identity: matched and rejected pairs",
                                      "Extraction: articles checked against what was pulled from them"]),
            ("Careful labelling", ["Labellers never see the pipeline’s answer", "50 rows of each sheet are marked twice: Cohen’s kappa", "Labels are frozen before scoring"]),
            ("What is reported", ["Precision, recall and F1 for relevance and extraction", "Match precision and recall, split by Latin and Chinese names",
                                  "Time per change, with each cataloguer as their own control"])]
    for i, (head, lines) in enumerate(cols):
        x = L + i * 4.1
        paras = [P(head, 19, True, TEAL, after=10)] + [P(t, 15, False, INK, after=8, bullet=True) for t in lines]
        tbox(s, x, 1.5, 3.9, 3.9, paras, fill=PALE, radius=0.1, inset=(0.22, 0.18))
    tbox(s, L, 5.65, W, 0.6, [P("All of it drawn from one month of the live feed. The crossover: two cataloguers use the tool, two read the news as before, and they swap at six weeks.", 15, False, GREY)],
         anchor="m", inset=(0.02, 0.02))


def b_cost_legal(s):
    cols = [("Cost", ["One person built it", "Free tiers: hosted database, scheduled task runner, gemini-3.8-flash with thinking on high", "Paid access: under SGD 15 a month at today’s volume (an estimate, excluding staff time)"]),
            ("Law and accountability", ["The article is fetched to be analysed; the text is not kept", "Designed for Singapore’s computational data analysis exception (Copyright Act 2021, ss. 243 to 244). Check yours.", "Facts about living people reach a file others use, so a named cataloguer decides every change"]),
            ("Why not embeddings?", ["In a small pilot, two different people scored closer than one person’s name in two scripts", "Retrieval uses character similarity on the name and its romanisation, and no model", "Not compared systematically"])]
    for i, (head, lines) in enumerate(cols):
        x = L + i * 4.1
        paras = [P(head, 19, True, TEAL, after=10)] + [P(t, 15, False, INK, after=8, bullet=True) for t in lines]
        tbox(s, x, 1.5, 3.9, 4.1, paras, fill=PALE, radius=0.1, inset=(0.22, 0.18))


# ---- the new main slides --------------------------------------------------------------------

LIM_AFTER = ("Distinguished Singaporean public servant who dedicated over four decades to public service across defense, education, diplomacy, "
             "research, and food security, serving as Chairman of A*STAR and founding chairman of the Singapore Food Agency.")
LIM_BEFORE_KEPT = "Chairman of A*STAR"
LIM_BEFORE_GONE = (" (2007-2019), Adjunct Professor at the Lee Kuan Yew School of Public Policy (2013-) and Permanent Secretary at the Ministry of "
                   "Education (2003-2007), Chief of Defence Force (April 2000 to March 2003) and Chief of Army (July 1998 to March 2000).")


LIM_QUOTE = ("Lim Chuan Poh, aged 64 and with a military background, has dedicated more than 40 years to public service, contributing immensely to "
             "Singapore's defense, education, diplomacy, research and innovation, and food safety, and was awarded the Meritorious Service Medal this year's National Day.")


def s_promise(s):
    """What the room will leave with: one idea and four questions, asked here and answered by the end."""
    tbox(s, L, 1.4, W, 1.55, [P("“Human in the loop” is only true if the human can see enough to disagree.", 30, True, WHITE)], anchor="m", fill=NAVY, radius=0.12, inset=(0.4, 0.12))
    tbox(s, L, 3.15, W, 0.45, [P("FOUR QUESTIONS TO TAKE HOME", 14, True, GREY)], anchor="m", inset=(0.05, 0.04))
    questions = ["Is it the same person?", "What did it remove?", "Does the quote back THIS change?", "What did it leave out?"]
    for i, q in enumerate(questions):
        x = L + i * 3.07
        tbox(s, x, 3.7, 2.87, 2.2, [P(str(i + 1), 26, True, RED if i == 3 else TEAL, after=4), P(q, 20, True, INK)], fill=PALE, radius=0.1, inset=(0.2, 0.14))
    tbox(s, L, 6.1, W, 0.6, [P("Each one comes from a real card in our live system. Ask them of any AI-suggested change to a record.", 17, False, GREY, "c")], anchor="m")


def s_cold_open(s):
    """The first version of the screen, as a reviewer met it: the article's sentence and the AI's proposal, and nothing of what the record said before."""
    tbox(s, L, 1.3, W, 0.45, [P("This is everything the first version of our screen showed.", 18, True, GREY)], anchor="m", inset=(0.02, 0.04))
    block(s, 1.0, 1.85, 11.33, 4.45, WHITE, radius=0.1, line=LINE, line_w=1.5)
    tbox(s, 1.2, 2.0, 10.93, 1.45, [P("IN THE NEWS   ·   Lianhe Zaobao, 13 August 2026 (translated)", 12, True, GREY, after=4), P("“" + LIM_QUOTE + "”", 16, False, INK)],
         fill=RGBColor.from_string("F3EFE6"), radius=0.08, inset=(0.2, 0.12))
    tbox(s, 1.2, 3.6, 10.93, 1.85, [P("THE AI PROPOSES THIS DESCRIPTION FOR THE RECORD “Lim, Chuan Poh”", 12, True, TEAL, after=4), P(LIM_AFTER, 20, False, INK)],
         radius=0.08, inset=(0.2, 0.1))
    tbox(s, 1.2, 5.58, 3.2, 0.6, [P("Accept", 18, True, WHITE, "c")], anchor="m", fill=GREEN, radius=0.08)
    tbox(s, 4.6, 5.58, 3.2, 0.6, [P("No change", 18, True, INK, "c")], anchor="m", fill=WHITE, line=LINE, radius=0.08, line_w=2)
    tbox(s, L, 6.4, W, 0.5, [P("Hold on to your answer. We will come back to it.", 20, True, TEAL, "c")], anchor="m")


def s_journey(s):
    tbox(s, L, 1.55, 3.7, 2.6, [P("THE STRAITS TIMES · 31 AUG", 12, True, GREY, after=6),
                                P("Social service veteran Gerard Ee steps down as chairperson of Agency for Integrated Care", 20, True, INK)],
         fill=RGBColor.from_string("F3EFE6"), radius=0.1, inset=(0.22, 0.18))
    arrow(s, 4.35, 2.85, 4.95, 2.85, GREY, 3)
    for i, (name, sub) in enumerate([("Gerard Ee", "stepping down"), ("Anita Fam", "taking over")]):
        tbox(s, 5.05, 1.55 + i * 1.4, 3.3, 1.2, [P(name, 22, True, INK, after=2), P(sub, 15, False, GREY)], fill=PALE, radius=0.1, inset=(0.2, 0.1), anchor="m")
        arrow(s, 8.45, 2.15 + i * 1.4, 9.05, 2.15 + i * 1.4, GREY, 3)
    for i, (name, sub) in enumerate([("Card 1: Ee, Gerard", "3 changes proposed"), ("Card 2: Fam, Anita", "2 changes proposed")]):
        tbox(s, 9.15, 1.55 + i * 1.4, 3.58, 1.2, [P(name, 19, True, INK, after=2), P(sub, 15, False, GREY)], fill=WHITE, line=TEAL, line_w=2, radius=0.1,
             inset=(0.2, 0.1), anchor="m")
    steps = [("AI reads", TEAL), ("AI proposes", TEAL), ("A person decides", RED), ("Nothing is written without them", NAVY)]
    for i, (label, color) in enumerate(steps):
        x = L + i * 3.07
        tbox(s, x, 4.6, 2.87, 1.2, [P(label, 20, True, WHITE, "c")], anchor="m", fill=color, radius=0.1)
        if i < 3:
            arrow(s, x + 2.88, 5.2, x + 3.06, 5.2, GREY, 2)
    tbox(s, L, 6.05, W, 0.7, [P("Both cards go to a cataloguer. Only a person can change the file.", 20, True, INK, "c")], anchor="m")


def s_removed(s):
    pic, pw, ph = picture(s, "desk-new-lim-diff.png", L, 1.35, h=5.5)
    x0 = L + pw + 0.35
    w = R - x0
    tbox(s, x0, 1.35, w, 2.05, [P("BEFORE: what the record said", 12, True, RED, after=4),
                                P(runs=[(LIM_BEFORE_KEPT, {"bold": True, "color": INK}), (LIM_BEFORE_GONE, {"color": RED})], size=16)],
         fill=RED_PALE, radius=0.1, inset=(0.2, 0.12))
    tbox(s, x0, 3.55, w, 1.75, [P("AFTER: what the AI proposed", 12, True, GREEN, after=4), P(LIM_AFTER, 16, False, INK)], fill=GREEN_PALE, radius=0.1, inset=(0.2, 0.12))
    tbox(s, x0, 5.45, 1.9, 1.35, [P("9%", 48, True, RED)], anchor="m", inset=(0.05, 0.05))
    tbox(s, x0 + 1.9, 5.45, w - 1.9, 1.35, [P("of the original survives. There was no error message. The error is the pipeline’s, not his.", 17, False, INK)], anchor="m", inset=(0.05, 0.05))


def s_wrong_person(s):
    pic, pw, ph = picture(s, "desk-new-lee-identity.png", L, 1.35, h=5.5)
    x0 = L + pw + 0.4
    w = R - x0
    half = (w - 0.2) / 2
    for i, (big, label) in enumerate([("71", "the age in the article"), ("1888", "the birth year of the record offered")]):
        tbox(s, x0 + i * (half + 0.2), 1.35, half, 1.9, [P(big, 54, True, NAVY, after=2), P(label, 14, False, GREY)], fill=PALE, radius=0.1, inset=(0.2, 0.1), anchor="m")
    tbox(s, x0, 3.4, w, 1.0, [P("71 and 1888 cannot be one person.", 24, True, WHITE, "c")], anchor="m", fill=RED, radius=0.1)
    tbox(s, x0, 4.55, w, 2.3, [P("The model flagged it, and a reviewer found the right record, an engineer, by search.", 17, True, INK, after=8),
                               P("In the English article, the same man matched correctly. Of 66 Chinese-named people in our feed, TTE holds the Chinese name for 17.", 15, False, GREY)],
         inset=(0.05, 0.05))


def s_quote_gap(s):
    pic, pw, ph = picture(s, "desk-new-tang-death.png", L, 1.4, w=6.2)
    x0 = L + pw + 0.4
    w = R - x0
    tbox(s, x0, 1.4, w, 1.2, [P("The change", 13, True, GREY, after=3), P("Replace the day of death, 15, with 16", 20, True, INK)], fill=PALE, radius=0.1, inset=(0.2, 0.1), anchor="m")
    tbox(s, x0, 2.75, w, 1.4, [P("The sentence on screen", 13, True, AMBER, after=3), P("“…has passed away at the age of 94.” There is no date in it.", 17, False, INK)],
         fill=AMBER_PALE, radius=0.1, inset=(0.2, 0.1), anchor="m")
    tbox(s, x0, 4.3, w, 1.85, [P("Behind it, not shown", 13, True, RED, after=3),
                               P("CNA and The Straits Times, as we recorded them: the 15th. Zaobao, the one source on screen: the 16th.", 16, False, INK)],
         fill=RED_PALE, radius=0.1, inset=(0.2, 0.1), anchor="m")
    tbox(s, L, 6.3, W, 0.55, [P("I cannot tell you which date is right. Neither can the screen.", 20, True, NAVY, "c")], anchor="m")


def s_reveal(s):
    pic, pw, ph = picture(s, "desk-new-fam-change.png", L, 1.35, h=4.55)
    sx = pw / 1502
    block(s, L + 18 * sx, 1.35 + 262 * sx, 1466 * sx, 138 * sx, None, radius=0.05, line=RED, line_w=3)
    ghost = tbox(s, L, 1.35 + ph + 0.12, pw, 0.85, [P("NOT PROPOSED:  “Chairperson of the Agency for Integrated Care, from 2026”", 15, True, AMBER, "c")], anchor="m",
                 fill=AMBER_PALE, radius=0.08, line=AMBER, line_w=2.25)
    ghost.line.dash_style = MSO_LINE.DASH
    x0 = L + pw + 0.4
    w = R - x0
    tbox(s, x0, 1.35, w, 1.4, [P("The quote is about her awards", 18, True, RED, after=3), P("Nothing on screen says she is the new chairperson.", 15, False, INK)],
         fill=RED_PALE, radius=0.1, inset=(0.2, 0.1), anchor="m")
    tbox(s, x0, 2.9, w, 1.2, [P("Her description got no edit", 18, True, AMBER, after=3), P("His did.", 15, False, INK)], fill=AMBER_PALE, radius=0.1, inset=(0.2, 0.1), anchor="m")
    tbox(s, x0, 4.25, w, 1.35, [P("A reviewer can check what was proposed. They cannot see what was left out.", 19, True, WHITE)], fill=NAVY, radius=0.1, inset=(0.25, 0.1), anchor="m")
    tbox(s, x0, 5.75, w, 1.1, [P("Not solved. We changed the prompts so an appointment is recorded when announced: written and code-tested, not yet re-run on the model.", 13, False, GREY)],
         inset=(0.05, 0.05))


def s_four_questions(s):
    items = [("1", "Is it the same person?", "A record born in 1888, for an article about a 71-year-old.", TEAL),
             ("2", "What did it remove?", "A Chief of Army and a Chief of Defence Force, replaced by a compliment.", TEAL),
             ("3", "Does the quote back THIS change?", "A death date changed to the 16th, with a quote that has no date.", TEAL),
             ("4", "What did it leave out?", "Her new post as chairperson. Nothing on screen shows it.", RED)]
    for i, (n, question, seen, color) in enumerate(items):
        x, y = L + (i % 2) * 6.1, 1.4 + (i // 2) * 2.45
        tbox(s, x, y, 5.95, 2.3, [P(n, 26, True, color, after=2), P(question, 26, True, INK, after=6), P("Seen in this talk: " + seen, 16, False, GREY)],
             fill=PALE, radius=0.12, inset=(0.28, 0.12))
    tbox(s, L, 6.3, W, 0.6, [P("If the screen cannot answer these, the human in the loop is a formality.", 22, True, NAVY, "c")], anchor="m")


def s_unknown_and_next(s):
    cols = [("Not measured yet", ["Whether each proposal is correct", "Whether it saves time", "Next: labelled sheets, then cataloguers swapping between the tool and reading the news"]),
            ("What it took", ["One person, on free tiers", "Paid access: under SGD 15 a month (estimated)", "The hard part was the screen, not the model"]),
            ("Before you start", ["Check your copyright exception (ours: Singapore’s computational data analysis provision)", "Nothing reaches the file without a named person’s decision"])]
    for i, (head, lines) in enumerate(cols):
        x = L + i * 4.1
        tbox(s, x, 1.5, 3.9, 4.6, [P(head, 24, True, TEAL, after=14)] + [P(t, 19, False, INK, after=14, bullet=True) for t in lines],
             fill=PALE, radius=0.1, inset=(0.25, 0.2))
    tbox(s, L, 6.3, W, 0.55, [P("Two cataloguers have used the first version. Nobody has yet measured whether it is right.", 17, True, NAVY, "c")], anchor="m")


def b_more_cards(s):
    cards = [("Kevin Tan", "Article: a neuroscience institute. Record offered: academic, writer, historian. Name similarity 1.00. The model flagged it."),
             ("Order of Friendship", "Proposed award: “First-Class Order of Friendship (2026)”. The country, Kazakhstan, is in the AI’s own summary but not in the value."),
             ("Singapore Airlines", "Five awards proposed. “World’s Best Airline (2026)” and “Skytrax World’s Best Airline (2026)” are the same award."),
             ("Mediacorp", "Five candidate records for one company: the group, its radio, its studios and two television companies."),
             ("A national swimmer", "A rewrite that keeps 63%: his place at the 2012 Olympics and his school are removed, and a new sentence is added.")]
    for i, (head, body) in enumerate(cards):
        x, y = L + (i % 2) * 6.1, 1.45 + (i // 2) * 1.85
        tbox(s, x, y, 5.95, 1.7, [P(head, 18, True, TEAL, after=3), P(body, 14, False, INK)], fill=PALE, radius=0.1, inset=(0.22, 0.12), anchor="m")


def b_schema(s):
    tiles = [("34 KB", "of cataloguing guidance pasted into the prompt. The model skimmed it, used short field names anyway, and found fewer entities."),
             ("8,149 of 22,996", "archive articles came back in the requested structure, on a platform that cannot enforce one. The rest came back as prose."),
             ("113 fields", "in TTE’s guidelines, with exact names. The live pipeline’s model API enforces them, and has not failed this way.")]
    for i, (big, label) in enumerate(tiles):
        x = L + i * 4.1
        tbox(s, x, 1.55, 3.9, 4.3, [P(big, 32, True, NAVY, after=10), P(label, 17, False, INK)], fill=PALE, radius=0.1, inset=(0.25, 0.25))
    tbox(s, L, 6.1, W, 0.6, [P("A prompt asks. Code checks.", 22, True, TEAL, "c")], anchor="m")


# ---- the talk, in order --------------------------------------------------------------------
# (title, builder, minutes, notes). The notes are spoken, in the first person. The talk opens on the title slide (15 seconds)
# and the thank-you slide carries the close. Between them: ten slides. The problem comes first, then the split, then the test.

TALK = [
    ("One idea, four questions", s_promise, 0.75,
     "Here is what you will leave with: one idea, and four questions.\n\n"
     "The idea: “human in the loop” is only true if the human can see enough to disagree. You will hear that phrase in every AI policy discussion, and very few people say what it takes. In this talk it comes down to one screen.\n\n"
     "The four questions are ones you can ask of any AI-suggested change to a catalogue record, whether it comes from a vendor, a colleague, or your own pipeline. Each one comes from a real card in our live system. "
     "I will show you the card, you will see what the screen hid, and by the end you will have all four."),
    ("Sixty Singapore articles a day. Two or three matter.", s_labour, 1.5,
     "Start with the problem, because the rest only makes sense with it. Every library keeps records of the people, organisations and places it catalogues: one agreed name, dates, posts, a short description. "
     "Ours is called TTE. It holds fifty-two thousand names, and other systems lean on it: our discovery systems, the national archives, other agencies, and VIAF.\n\n"
     "Records go stale. Someone takes a new post. Someone dies. An organisation is renamed. How do we find out? From the news. A specialist reads the Singapore papers, in English and Chinese, every day. "
     "We follow the Singapore feeds of three outlets, and those carry about sixty articles a day. The outlets publish far more overall; this is only the Singapore section. About two or three report something that changes a record. To find those two or three, a person has to read all sixty. Every day. And that is only the Singapore feeds. Add an outlet or a language, and it grows.\n\n"
     "That is the labour. So we asked: can an AI do the reading, and leave the people the deciding?"),
        ("The AI does the reading. A person does the deciding.", s_journey, 1.5,
     "So we split the job. Here is how it works, on one article. The Straits Times, 31 August: a social service veteran, Gerard Ee, steps down as chairperson of the Agency for Integrated Care. Anita Fam takes over.\n\n"
     "The AI reads the article and finds two people. It finds each one's record and proposes changes. Gerard Ee's card has three. Anita Fam's has two. Those cards go to a cataloguer.\n\n"
     "Nothing is written to the file by the AI, ever. The AI reads, the AI proposes, a person decides. That is the whole design. Everything else I am going to say is about what that person is shown when they decide."),
        ("You are the reviewer. Approve?", s_cold_open, 1.25,
     "Now you are the cataloguer. This is everything the first version of our screen showed. At the top, a sentence from a news article: a man aged sixty-four, a military background, "
     "forty years in public service, awarded a national medal. Below it, the description our AI proposes for his record. It draws on the article, and it reads well.\n\n"
     "Would you approve it? Take ten seconds. [PAUSE, and let them read.] Hold on to your answer. I will come back to it."),
    ("The reveal: a career replaced by a compliment", s_removed, 1.5,
     "Now back to the description you were asked to approve. On the left is the real screen as it looks today. On the right is what the AI replaced.\n\n"
     "The record said: Chairman of A*STAR; Permanent Secretary at the Ministry of Education; Chief of Defence Force; Chief of Army. Every post, with dates. The AI replaced all of it with a sentence saying he dedicated over four decades to public service. About nine per cent of the original survives. It replaced a career with a compliment.\n\n"
     "There was no error message. The first version of our screen showed the article's sentence and the new text, and nothing of the old description. You could not have known unless you had the old one in front of you. To be clear: the error is the pipeline's, not his."),
    ("Papers, Please, or Tinder?", s_redesign, 1.5,
     "So we changed the screen. Let me tell you what the first one was like. If you have played Papers, Please, you know the feeling: you are a border inspector, you have two documents, you compare them against the rules, and you stamp approved or denied. "
     "Our first desk was built to play like that. The article on one side, the record on the other, one question, a stamp.\n\n"
     "Two cataloguers used it and found problems, and helped redesign it. Then a first-time user, someone outside the library, looked at it and said: it feels like Tinder.\n\n"
     "That is the opposite of what we want. Papers, Please makes you slow down and look. Tinder makes you swipe. The same screen can be either, and the design decides which. So the redesign has one card and one question. The news is always on top, then what the record says now, then what it will say after you accept. Ticks and crosses for the identity checks. And 'No thanks' means discard."),
    ("A name match is not an identity match", s_wrong_person, 1.25,
     "Now three things the old screens hid. First, the wrong person.\n\n"
     "This is a Chinese-language article about a man aged seventy-one who won a national science medal. We match Chinese names a second time through an English spelling, which raised our match rate from forty to seventy-seven per cent. But the spelling is the model's guess. "
     "This guess landed on Lee Choon Seng: a banker, born in 1888. A man of seventy-one and a man born in 1888 cannot be the same person.\n\n"
     "The model flagged it itself, and the reviewer found the right record, an engineer, by search. In the English article, the same man matched correctly. The screen has to put the facts side by side, and it has to say when a record was found through a guess."),
    ("The sources that disagree stay out of sight", s_quote_gap, 1.25,
     "Second: what supports a change. A reviewer is shown the sources that back a change. Not the ones that disagree with it.\n\n"
     "This record has a day of death: the fifteenth. The AI proposes the sixteenth. Look at the sentence on the screen. It says he died aged ninety-four. There is no date in it at all.\n\n"
     "What the screen does not show: CNA and The Straits Times, as we recorded them, say he died on the fifteenth. Zaobao, which supplied the proposal, said the sixteenth. I cannot tell you which is right, and the screen cannot either. A death date goes into a file that other agencies and VIAF draw on. A change shown with only its own supporters invites you to approve it."),
    ("What no screen shows: what was left out", s_reveal, 1.75,
     "Third, and this is the one we have not solved. Back to the article from the start: Gerard Ee steps down, Anita Fam takes over. This is her card. It asks: add Agency for Integrated Care to her affiliations?\n\n"
     "That is fine. Now look at the quote. It is about her awards. Nothing on the screen says she is the new chairperson. And her description got no edit, though his did.\n\n"
     "The AI had caught the fact. The last step left it out, probably because her post starts the next day, and nothing told it what to do with an announced appointment. A reviewer can check what was proposed. They cannot see what was left out. In this case the only way to know is to have read the article.\n\n"
     "We have changed the prompts so that an appointment is recorded when it is announced, and each change now quotes its own sentence. We have tested the code, but we have not yet re-run the model on this article. What we have not solved is showing a reviewer what the article says that no change covers."),
    ("The four questions, again", s_four_questions, 1.0,
     "These are the four I promised. Is it the same person? We saw a record born in 1888 offered for a man of seventy-one. What did it remove? A Chief of Army, replaced by a compliment. "
     "Does the quote back this change? A death date changed, with a quote that has no date. And the hard one: what did it leave out? A new post, and nothing on the screen shows it.\n\n"
     "If the screen in front of you cannot answer these, the human in the loop is a formality."),
    ("What we do not know, and what you could do", s_unknown_and_next, 1.0,
     "What do we know? Less than I would like. Can a person decide each proposal? Yes: two cataloguers used the first version and helped redesign it. Is each proposal correct? We have not measured that. Does it save time? Not yet either. "
     "Next come labelled sheets from one month of the feed, with labellers who cannot see the AI's answer, and then a field test where cataloguers swap between the tool and reading the news.\n\n"
     "What would it take for you? One person built this, on free tiers. Paid access is estimated at under fifteen Singapore dollars a month. The hard part was never the model. It was the screen.\n\n"
     "And before you start, check your copyright position. Ours is Singapore's computational data analysis provision, and the article is read, not stored. Nothing reaches our file without a named person's decision. That is the safeguard."),
]

TITLE_NOTES = ("Good afternoon. I am Ashwin Nair, from the National Library Board in Singapore. I want to talk about a screen: the one that sits between an AI and a catalogue record.")
CLOSE_NOTES = ("So: Papers, Please, not Tinder. A human in the loop is only real if the human can see enough to disagree. Build the screen so that a person can look, and so that they can see what was left out.\n\n"
               "Thank you. I would be glad to take your questions. The next slides are backup, if they help: the six stages, the numbers, the evaluation plan, cost and law, the schema lesson, whether a small model could do the first filter, more cards, and an earlier deletion.")

BACKUP = [
    ("Backup: the six stages", s_pipeline, "Only if asked. Six stages. The first five run on a schedule, unattended. Relevance reads only the title and summary and passes about four in a hundred. Extraction pulls out people, organisations and places, the facts reported about each under TTE's own field names, and one quoted sentence. "
     "Retrieval finds candidate records with character similarity on the name and its romanisation, and no model. Resolution is the only stage that sees the article and the record together. The sixth stage is a person; the pipeline never writes to TTE."),
    ("Backup: the numbers", b_numbers, "Only if asked. These are from 28 September 2026. The archive is the three outlets' own archives since 2015, read once through an internal model; the live feed has run nightly since 3 August. "
     "Nothing has been decided by a reviewer in a formal evaluation. About 6,000 matches had nothing to add, and 22,331 entities have no TTE record at all."),
    ("Backup: the evaluation plan", b_evaluation, "Only if asked. Three sheets from one month of the feed. Labellers never see the pipeline's answer, fifty rows of each are marked twice so we can report Cohen's kappa, and labels are frozen before scoring. "
     "Relevance and extraction are scored with precision, recall and F1; identity matching with match precision and recall, split by Latin and Chinese script names. The crossover compares time per change."),
    ("Backup: cost, law and retrieval", b_cost_legal, "Only if asked. Cost: free tiers throughout, under fifteen Singapore dollars a month estimated if paid, excluding staff time and the platform used for the archive. "
     "Law: the article is fetched only to be analysed, one evidence sentence is kept and the text is discarded; we rely on Singapore's computational data analysis exception, and another jurisdiction should check its own. "
     "Retrieval: in a small pilot, embeddings scored two different people as more similar than one person's name in two scripts, so we use trigram similarity. We did not compare retrieval methods systematically."),
    ("Backup: the schema belongs in code", b_schema, "Only if asked. A prompt asks; code checks. When we pasted 34 kilobytes of cataloguing guidance into the prompt, the model skimmed it, used short field names anyway, and found fewer entities per article. A longer prompt was a worse one. "
     "On the archive platform, which cannot hold output to a schema, extraction returned the requested structure for 8,149 of 22,996 articles in the first round. Through the public API, which enforces the schema, the live pipeline has not failed this way."),
    ("Backup: could a small model do the first filter?", b_small_model, "Only if asked. We tested whether a small multilingual model could do the relevance step instead of a large language model. "
     "A 140-million-parameter model, fine-tuned for half an hour on one gaming GPU, reaches an F1 of 0.75 against the archive's labels, and passes about 25 articles in 100 to the next stage while keeping 95 per cent of the relevant ones. "
     "Plain word counts with logistic regression reach 0.66 on a CPU with no neural network. "
     "But the labels belong to another model, not to people. On 69 hard cases a person judged, the fine-tuned model does worse than before fine-tuning, because it has learned the labeller's mistakes. So this shows the first filter can be cheap. It does not show that it is right."),
    ("Backup: more cards from the live deck", b_more_cards, "Only if asked. Kevin Tan: a common name, similarity 1.00, a different person; the model flagged it. The Order of Friendship: many countries have one, and the value we propose leaves the country out although the AI's own summary names Kazakhstan. "
     "Singapore Airlines: the same award proposed twice under two names. Mediacorp: five candidate records for one company, which is the corporate-body hierarchy problem every authority file has. And a national swimmer, whose rewrite keeps 63 per cent and drops his place at the 2012 Olympics."),
    ("Backup: an earlier deletion, 636 to 405", s_editing, "Only if asked. The earlier case from the paper: a description cut from 636 characters to 405, losing a Navy career, ten years as Deputy Prime Minister and every constituency held, and still called a merge. "
     "The Lim Chuan Poh card in the talk is the same failure, caught this time by the warning. We now show the change as a diff, measure how much of the old text survives, and warn when a rewrite deletes heavily."),
]


# ---- building the deck ---------------------------------------------------------------------

def build(out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    work = out.with_suffix(".template.pptx")
    prs = Presentation(as_pptx(TEMPLATE, work))
    title_slide, content, spare, section, thanks = list(prs.slides)[:5]
    made, notes, titles, numbers = [], [], [], []

    # 1. title
    TAG[0] = "title"
    set_text(named(title_slide, "Rectangle 4"), TITLE)
    shape5 = named(title_slide, "Rectangle 5")
    set_text(shape5, PRESENTER)
    shape5.text_frame.paragraphs[0].add_run().text = f"\n{INSTITUTION}"
    sub = tbox(title_slide, 1.09, 5.0, 6.0, 0.9, [P(SUBTITLE, 18, False, WHITE)], inset=(0.1, 0.04))
    made.append(title_slide)
    notes.append(TITLE_NOTES)
    titles.append(TITLE)

    def add_content(title, builder, backup=False):
        slide = clone(prs, content)
        TAG[0] = title
        assert len(title) <= 60, f"title too long ({len(title)}): {title}"
        shape = named(slide, "Rectangle 2")
        numbers.append((slide, named(slide, "Rectangle 11")))
        shape.width = Inches(12.2 if not backup else 10.4)
        set_text(shape, title)
        if backup:
            pill(slide, 11.25, 0.27, 1.5, 0.4, "BACKUP", RED, size=13)
        builder(slide)
        made.append(slide)
        return slide

    for title, builder, _minutes, spoken in TALK:
        add_content(title, builder)
        notes.append(spoken)
        titles.append(title)

    # the thank-you slide, after the talk
    set_text(named(thanks, "Rectangle 4"), "Papers, Please, not Tinder.")
    set_text(named(thanks, "Rectangle 5"), PRESENTER)
    named(thanks, "Rectangle 5").text_frame.paragraphs[0].add_run().text = f"\n{EMAIL}"
    made.append(thanks)
    notes.append(CLOSE_NOTES)
    titles.append("Thank you, and questions")

    for title, builder, spoken in BACKUP:
        add_content(title, builder, backup=True)
        notes.append(spoken)
        titles.append(title)

    # order the slides as listed, and drop the two template slides we did not use
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    ids = prs.slides._sldIdLst
    entries = {el.rId: el for el in list(ids)}
    wanted = [prs.part.relate_to(slide.part, RT.SLIDE) for slide in made]
    for el in list(ids):
        ids.remove(el)
    for rid in wanted:
        ids.append(entries[rid])
    for gone in (spare, section, content):      # the template's own slides: the clones carry everything
        prs.part.drop_rel(prs.part.relate_to(gone.part, RT.SLIDE))

    place = {slide.slide_id: i for i, slide in enumerate(made, 1)}
    for slide, shape in numbers:
        set_text(shape, f"{place[slide.slide_id]:02d}")
    for slide, text in zip(made, notes):
        slide.notes_slide.notes_text_frame.text = text
    prs.save(out)
    work.unlink(missing_ok=True)
    return out, titles, notes


def script_docx(path: Path, titles, notes):
    import docx
    from docx.shared import Pt as DPt
    d = docx.Document()
    d.styles["Normal"].font.name = "Arial"
    d.styles["Normal"].font.size = DPt(11)
    d.add_heading("Designing for the Reviewer: speaking script", 0)
    d.add_paragraph("IFLA AI symposium, 20-minute slot: about 15 minutes of talking, then 5 for questions. The times are a running clock at an easy pace "
                    "(about 130 words a minute). The talk opens on the title slide and a test for the room; the thank-you slide carries the close, and every slide after it is backup, for questions only.")
    clock = 0.0
    total_words = 0
    plan = [0.25] + [t[2] for t in TALK] + [0.5]
    for i, (title, spoken) in enumerate(zip(titles, notes), 1):
        words = len(spoken.split())
        total_words += words if i <= len(TALK) + 2 else 0
        minutes = plan[i - 1] if i <= len(plan) else None
        stamp = f"  [{int(clock)}:{int(round((clock % 1) * 60)):02d}]" if minutes is not None else "  [backup]"
        d.add_heading(f"Slide {i}: {title}{stamp}", level=2)
        for chunk in spoken.split("\n\n"):
            d.add_paragraph(chunk)
        if minutes is not None:
            clock += minutes
    d.add_paragraph(f"\nSpoken words in the talk: about {total_words}, which is roughly {total_words / 130:.0f} minutes at 130 words a minute.")
    d.save(path)
    return total_words


# ---- a rough drawing of each slide, for checking the layout ---------------------------------

PX = 100   # pixels per inch
_CJK_FILES = {False: "/mnt/c/Windows/Fonts/msyh.ttc", True: "/mnt/c/Windows/Fonts/msyhbd.ttc"}


def _face(wide, bold, px):
    path = _CJK_FILES[bold] if wide and Path(_CJK_FILES[bold]).exists() else _FILES[bold]
    return ImageFont.truetype(path, px)


def _runs(text):
    out = []
    for ch in text:
        if out and out[-1][0] == _wide(ch):
            out[-1][1] += ch
        else:
            out.append([_wide(ch), ch])
    return out


def mixed_width(text, px, bold):
    return sum(_face(w, bold, px).getlength(t) for w, t in _runs(text))


def draw_mixed(dr, x, y, text, px, bold, fill):
    for w, t in _runs(text):
        f = _face(w, bold, px)
        dr.text((x, y), t, font=f, fill=fill)
        x += f.getlength(t)


def preview(pptx_path: Path, folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.png"):
        old.unlink()
    prs = Presentation(pptx_path)
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    for n, slide in enumerate(prs.slides, 1):
        im = Image.new("RGB", (int(13.333 * PX), int(7.5 * PX)), "white")
        dr = ImageDraw.Draw(im)
        for sh in slide.shapes:
            x, y, w, h = (sh.left or 0) / 914400 * PX, (sh.top or 0) / 914400 * PX, (sh.width or 0) / 914400 * PX, (sh.height or 0) / 914400 * PX
            if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                pic = Image.open(__import__("io").BytesIO(sh.image.blob)).convert("RGB").resize((max(1, int(w)), max(1, int(h))))
                im.paste(pic, (int(x), int(y)))
                continue
            if sh.shape_type == MSO_SHAPE_TYPE.LINE or sh.__class__.__name__ == "Connector":
                try:
                    dr.line([(x, y), (x + w, y + h)], fill=(90, 99, 112), width=3)
                except Exception:
                    pass
                continue
            try:
                has_fill = sh.fill.type is not None and sh.fill.type == 1
                fillc = tuple(sh.fill.fore_color.rgb) if has_fill else None
            except Exception:
                fillc = None
            try:
                linec = tuple(sh.line.color.rgb) if sh.line.fill.type == 1 else None
            except Exception:
                linec = None
            try:
                kind = sh.auto_shape_type
            except ValueError:
                kind = None                                  # a plain text box
            box = [x, y, x + w, y + h]
            if fillc or linec:
                lw = max(1, int((sh.line.width or 12700) / 12700)) if linec else 0
                if kind == MSO_SHAPE.OVAL:
                    dr.ellipse(box, fill=fillc, outline=linec, width=lw)
                elif kind == MSO_SHAPE.ROUNDED_RECTANGLE:
                    r = min(w, h) * (sh.adjustments[0] if len(sh.adjustments) else 0.1)
                    dr.rounded_rectangle(box, radius=r, fill=fillc, outline=linec, width=lw)
                else:
                    dr.rectangle(box, fill=fillc, outline=linec, width=lw)
            if sh.has_text_frame and sh.text_frame.text.strip():
                tf = sh.text_frame
                ml, mt = (tf.margin_left or 91440) / 914400 * PX, (tf.margin_top or 45720) / 914400 * PX
                mr = (tf.margin_right or 91440) / 914400 * PX
                lines = []
                for p in tf.paragraphs:
                    runs = p.runs
                    if not runs:
                        continue
                    pt = max((r.font.size.pt if r.font.size else 18) for r in runs)
                    bold = any(r.font.bold for r in runs)
                    colr = (0, 0, 0)
                    for r in runs:                                   # a theme colour has no rgb: fall back to black
                        try:
                            if r.font.color and r.font.color.type is not None:
                                colr = tuple(r.font.color.rgb)
                                break
                        except AttributeError:
                            pass
                    text = "".join(r.text for r in runs)
                    bullet = p._p.pPr is not None and p._p.pPr.find(qn("a:buChar")) is not None
                    for k, ln in enumerate(wrap(text, pt, bold, (w - ml - mr) / PX * 72 - (BULLET_PT if bullet else 0))):
                        lines.append((("•  " if bullet and k == 0 else ("   " if bullet else "")) + ln, pt, bold, colr, p.alignment))
                    lines.append(("", (p.space_after.pt if p.space_after else 0) / 1.2, False, colr, None))
                total = sum(pt * 1.2 for _, pt, *_ in lines) / 72 * PX
                anchor = tf.vertical_anchor
                cy = y + mt if anchor in (None, MSO_ANCHOR.TOP) else (y + (h - total) / 2 if anchor == MSO_ANCHOR.MIDDLE else y + h - total - mt)
                for ln, pt, bold, colr, align in lines:
                    px_size = max(6, int(pt / 72 * PX))
                    lw_ = mixed_width(ln, px_size, bool(bold)) if ln else 0
                    if align == PP_ALIGN.CENTER:
                        tx = x + (w - lw_) / 2
                    elif align == PP_ALIGN.RIGHT:
                        tx = x + w - mr - lw_
                    else:
                        tx = x + ml
                    if ln:
                        draw_mixed(dr, tx, cy, ln, px_size, bool(bold), colr)
                    cy += pt * 1.2 / 72 * PX
        im.save(folder / f"slide-{n:02d}.png")


if __name__ == "__main__":
    deck, titles, notes = build(OUT / "designing-for-the-reviewer.pptx")
    words = script_docx(OUT / "speaking-script.docx", titles, notes)
    preview(deck, OUT / "talk-preview")
    for problem in PROBLEMS:
        print("OVERFLOW", problem)
    print(f"{deck}: {len(titles)} slides ({len(TALK) + 2} to the thank-you slide), about {words} spoken words (~{words / 130:.1f} min at 130 wpm)")
    sys.exit(1 if PROBLEMS else 0)
