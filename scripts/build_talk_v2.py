"""
The IFLA talk, second pass: the user's own edited deck, restyled.

    .venv/bin/python scripts/build_talk_v2.py

Starts from data/dist/designing-for-the-reviewer.YOUR-EDITS-backup-1938.pptx, the deck as the user edited it in PowerPoint (their wording
and slide order), and writes data/dist/designing-for-the-reviewer-v3.pptx beside it (v2 is kept as it was). The user's own file is never written.

Style, within the IFLA template (its header bar and footer stay): a short label in the header, one big statement in the body, almost no boxes,
red only for the words that matter, screenshots large with a soft shadow. The title slide, the thank-you slide and the backup slides are the
user's, untouched. The problem slide is split in three, so each idea has its own slide; everything else keeps the user's order.

It reuses the measuring and drawing helpers of build_talk.py, so every text box is fit-checked before it is placed.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import build_talk as bt  # noqa: E402
from build_talk import (AMBER, GREEN, GREY, INK, LINE, NAVY, P, RED, TEAL, WHITE, MSO_LINE, MSO_SHAPE, RGBColor, arrow, block, disc, etree,  # noqa: E402
                        picture, qn, tbox, width_pt)
from pptx import Presentation  # noqa: E402
from pptx.util import Pt  # noqa: E402

from src.export.slides import clone, set_text  # noqa: E402

SRC = ROOT / "data/dist/designing-for-the-reviewer.YOUR-EDITS-backup-1938.pptx"
OUT = ROOT / "data/dist/designing-for-the-reviewer-v3.pptx"
SCRIPT = ROOT / "data/dist/speaking-script-v3.docx"
PREVIEW = ROOT / "data/dist/talk-preview-v3"

LM, RM = 0.9, 12.43
CW = RM - LM
PINK = RGBColor.from_string("E8A0AE")
BEIGE = RGBColor.from_string("F3EFE6")


# ---- small drawing helpers on top of build_talk's -------------------------------------------

def shadow(shape):
    """A soft shadow, the way a screenshot floats on a keynote slide."""
    sp = shape._element.spPr
    for old in sp.findall(qn("a:effectLst")):          # python-pptx may already have put an empty one there; two is invalid and PowerPoint refuses the file
        sp.remove(old)
    eff = etree.SubElement(sp, qn("a:effectLst"))
    sh = etree.SubElement(eff, qn("a:outerShdw"), blurRad="228600", dist="50800", dir="5400000", algn="t", rotWithShape="0")
    clr = etree.SubElement(sh, qn("a:srgbClr"), val="1B1F2A")
    etree.SubElement(clr, qn("a:alpha"), val="26000")


def float_picture(slide, name, x, y, w=None, h=None):
    pic, pw, ph = picture(slide, name, x, y, w=w, h=h, border=False)
    pic.auto_shape_type = MSO_SHAPE.ROUNDED_RECTANGLE
    prst = pic._element.spPr.find(qn("a:prstGeom"))
    av = prst.find(qn("a:avLst"))
    if av is None:
        av = etree.SubElement(prst, qn("a:avLst"))
    etree.SubElement(av, qn("a:gd"), name="adj", fmla="val 3500")
    shadow(pic)
    return pic, pw, ph


def rule(slide, x, y, w, h, color):
    return block(slide, x, y, w, h, color)


def label(slide, x, y, w, text, color=GREY, size=13, h=0.4):
    return tbox(slide, x, y, w, h, [P(text, size, True, color)], anchor="m", inset=(0.02, 0.02))


def keep_chrome(slide):
    """Remove everything but the template's own six shapes (header bar, red line, header text, footer bar, footer text, number)."""
    shapes = list(slide.shapes)
    assert shapes[0].top is not None and (shapes[0].width or 0) / 914400 > 13, "unexpected slide layout: no header bar first"
    for sh in shapes[6:]:
        sh._element.getparent().remove(sh._element)


def header(slide, text):
    set_text(slide.shapes[2], text)


# ---- the slides -----------------------------------------------------------------------------

def s_idea(s):
    tbox(s, LM, 1.35, CW, 2.2, [P(runs=[("“Human in the loop” is only true if the human ", {"color": INK}), ("can see enough to disagree.", {"color": RED})], size=42, bold=True)],
         inset=(0.02, 0.02))
    label(s, LM, 3.75, 6, "FOUR QUESTIONS TO TAKE HOME")
    qs = ["Is it the same entity?", "What did it remove or add?", "Is there evidence for this change?", "What was left out?"]
    for i, q in enumerate(qs):
        x = LM + i * 2.9
        rule(s, x, 4.25, 2.7, 0.05, RED if i == 3 else TEAL)
        tbox(s, x, 4.35, 2.7, 1.9, [P(str(i + 1), 34, True, RED if i == 3 else TEAL, after=2), P(q, 22, True, INK)], inset=(0.02, 0.04))
    tbox(s, LM, 6.4, CW, 0.5, [P("Each one comes from a real card in our live system. Ask them of any AI-suggested change to a record.", 17, False, GREY)], anchor="m", inset=(0.02, 0.02))


def s_problem(s):
    tbox(s, LM, 1.4, CW, 3.7, [P(runs=[("Every morning, someone reads the news to find the ", {"color": INK}), ("5 to 6", {"color": RED}), (" articles that matter.", {"color": INK})],
                                 size=56, bold=True)], inset=(0.02, 0.02))
    hot = {6, 21, 38, 51, 57}
    for k in range(60):
        r, c = divmod(k, 30)
        color = RED if k in hot else (PINK if k == 12 else LINE)
        block(s, 0.95 + c * 0.32, 5.55 + r * 0.32, 0.2, 0.2, color, shape=MSO_SHAPE.OVAL)
    tbox(s, LM, 6.3, CW, 0.6, [P(runs=[("60", {"bold": True, "color": INK}), (" Singapore articles a day", {"color": INK}),
                                       ("     * There is more international news.", {"color": GREY, "size": 15})], size=22)], anchor="m", inset=(0.02, 0.02))


def s_record(s):
    tbox(s, LM, 1.45, 6.4, 3.6, [P("A record is the library’s one agreed entry for a person, organization or place.", 40, True, INK)], inset=(0.02, 0.02))
    tbox(s, LM, 5.2, 6.4, 1.5, [P("Name, dates, posts, a short description. Other systems copy it.", 24, False, GREY)], inset=(0.02, 0.02))
    card = block(s, 7.9, 1.45, 4.53, 5.0, WHITE, radius=0.12, line=LINE, line_w=1.25)
    shadow(card)
    tbox(s, 8.15, 1.6, 4.1, 0.4, [P("PERSON  ·  no. 18567994", 11, True, GREY)], anchor="m", inset=(0.02, 0.02))
    tbox(s, 8.15, 2.0, 4.1, 0.7, [P("Ee, Gerard", 28, True, INK)], anchor="m", inset=(0.02, 0.02))
    rows = [("OCCUPATION", "Accountant · Auditor · Member of Parliament"), ("BORN", "1949"), ("AWARDS", "Public Service Medal (1993) and three more")]
    y = 2.85
    for k, v in rows:
        tbox(s, 8.15, y, 4.1, 0.75, [P(k, 11, True, GREY, after=1), P(v, 15, False, INK)], inset=(0.02, 0.02))
        y += 0.78
    tbox(s, 8.15, 5.2, 4.1, 1.1, [P("A practicing accountant for almost 30 years, he is well known in the corporate and charity arenas.", 14, False, GREY)], inset=(0.02, 0.02))


def s_labour(s):
    tbox(s, LM, 1.4, CW, 2.4, [P("To find the five or six, a person reads all sixty. Every day.", 50, True, INK)], inset=(0.02, 0.02))
    tbox(s, LM, 3.85, CW, 0.9, [P("And that is only the Singapore feeds. Another outlet or language means more.", 24, False, GREY)], inset=(0.02, 0.02))
    rule(s, LM, 5.0, 1.2, 0.06, RED)
    tbox(s, LM, 5.2, CW, 1.6, [P(runs=[("Can an AI do the ", {"color": INK}), ("reading", {"color": RED}), (", and leave people the ", {"color": INK}), ("deciding", {"color": RED}), ("?", {"color": INK})],
                                 size=40, bold=True)], inset=(0.02, 0.02))


def s_how(s):
    tbox(s, LM, 1.3, CW, 1.4, [P("Six stages. Five run on their own. One is a person.", 38, True, INK)], inset=(0.02, 0.02))
    stages = [("Ingest", "Titles and summaries", "no AI"), ("Relevance", "Does this change a record?", "AI"), ("Extraction", "People, places, facts, one quote", "AI"),
              ("Retrieval", "Candidate records", "no AI"), ("Resolution", "Same entity? What is missing?", "AI"), ("A person", "Decides, then edits TTE by hand", "")]
    colw = CW / 6
    rule(s, LM + colw / 2, 3.28, colw * 5, 0.04, LINE)
    for i, (name, desc, tag) in enumerate(stages):
        cx = LM + colw * i + colw / 2
        human = i == 5
        disc(s, cx, 3.3, 0.72, RED if human else NAVY, str(i + 1), 18)
        tbox(s, cx - colw / 2 + 0.05, 3.75, colw - 0.1, 0.45, [P(name, 18, True, RED if human else INK, "c")], anchor="m", inset=(0.02, 0.02))
        tbox(s, cx - colw / 2 + 0.05, 4.2, colw - 0.1, 0.8, [P(desc, 13, False, GREY, "c")], inset=(0.02, 0.02))
        if tag:
            tbox(s, cx - colw / 2 + 0.05, 4.95, colw - 0.1, 0.3, [P(tag, 12, True, TEAL if tag == "AI" else GREY, "c")], anchor="m", inset=(0.02, 0.02))
    rule(s, LM, 5.45, CW, 0.015, LINE)
    stats = [("298,790", "Articles from 2015 - 2026"), ("28,090", "Relevant articles"), ("48,696", "Entities extracted"), ("9,844", "Changes proposed")]
    for i, (big, lab) in enumerate(stats):
        tbox(s, LM + i * (CW / 4), 5.6, CW / 4 - 0.1, 1.3, [P(big, 36, True, NAVY, after=1), P(lab, 14, False, GREY)], inset=(0.02, 0.02))


def s_split(s):
    rule(s, LM, 1.5, 0.06, 2.4, TEAL)
    tbox(s, LM + 0.2, 1.45, 3.7, 2.55, [P("THE STRAITS TIMES  ·  31 AUG", 12, True, GREY, after=6),
                                         P("Social service veteran Gerard Ee steps down as chairperson of Agency for Integrated Care", 19, True, INK)], inset=(0.02, 0.02))
    arrow(s, 4.95, 2.7, 5.5, 2.7, GREY, 3)
    for i, (name, sub) in enumerate([("Gerard Ee", "stepping down"), ("Anita Fam", "taking over")]):
        tbox(s, 5.7, 1.5 + i * 1.35, 2.9, 1.2, [P(name, 24, True, INK, after=1), P(sub, 16, False, GREY)], anchor="m", inset=(0.02, 0.02))
        arrow(s, 8.75, 2.1 + i * 1.35, 9.3, 2.1 + i * 1.35, GREY, 3)
    for i, (name, sub) in enumerate([("Card 1: Ee, Gerard", "3 changes proposed"), ("Card 2: Fam, Anita", "2 changes proposed")]):
        rule(s, 9.45, 1.65 + i * 1.35, 0.05, 0.95, TEAL)
        tbox(s, 9.65, 1.5 + i * 1.35, 2.8, 1.2, [P(name, 18, True, INK, after=1), P(sub, 15, False, GREY)], anchor="m", inset=(0.02, 0.02))
    rule(s, LM, 4.35, CW, 0.015, LINE)
    tbox(s, LM, 4.5, CW, 0.9, [P(runs=[("AI reads", {"color": INK}), ("  →  ", {"color": GREY}), ("AI proposes", {"color": INK}), ("  →  ", {"color": GREY}),
                                       ("A person decides", {"color": RED})], size=34, bold=True)], anchor="m", inset=(0.02, 0.02))
    tbox(s, LM, 5.5, CW, 0.5, [P("Nothing is written without them.", 22, False, GREY)], anchor="m", inset=(0.02, 0.02))
    tbox(s, LM, 6.2, CW, 0.6, [P("Both cards go to a cataloguer. Only a person can change the file.", 22, True, NAVY)], anchor="m", inset=(0.02, 0.02))


def s_test(s):
    tbox(s, LM, 1.3, CW, 0.5, [P("This is everything the first version of our screen showed.", 20, True, GREY)], anchor="m", inset=(0.02, 0.02))
    card = block(s, LM, 1.9, CW, 4.5, WHITE, radius=0.08, line=LINE, line_w=1.25)
    shadow(card)
    tbox(s, LM + 0.2, 2.05, CW - 0.4, 1.5, [P("IN THE NEWS   ·   Lianhe Zaobao, 13 August 2026 (translated)", 12, True, GREY, after=4), P("“" + bt.LIM_QUOTE + "”", 16, False, INK)],
         fill=BEIGE, radius=0.06, inset=(0.2, 0.1))
    tbox(s, LM + 0.2, 3.7, CW - 0.4, 1.95, [P("THE AI PROPOSES THIS DESCRIPTION FOR THE RECORD “Lim, Chuan Poh”", 12, True, TEAL, after=4), P(bt.LIM_AFTER, 22, False, INK)],
         inset=(0.2, 0.06))
    tbox(s, LM + 0.2, 5.7, 3.0, 0.55, [P("Accept", 18, True, WHITE, "c")], anchor="m", fill=GREEN, radius=0.08)
    tbox(s, LM + 3.4, 5.7, 3.0, 0.55, [P("No change", 18, True, INK, "c")], anchor="m", fill=WHITE, line=LINE, radius=0.08, line_w=2)
    tbox(s, LM, 6.5, CW, 0.5, [P("Hold on to your answer. We will come back to it.", 22, True, TEAL, "c")], anchor="m", inset=(0.02, 0.02))


def s_reveal(s):
    pic, pw, ph = float_picture(s, "desk-new-lim-diff.png", 7.75, 1.3, h=5.6)
    wl = 6.55
    label(s, LM, 1.3, wl, "BEFORE: what the record said", RED, 12, 0.3)
    tbox(s, LM, 1.6, wl, 1.85, [P(runs=[(bt.LIM_BEFORE_KEPT, {"bold": True, "color": INK}), (bt.LIM_BEFORE_GONE, {"color": RED, "strike": True})], size=17)], inset=(0.02, 0.02))
    label(s, LM, 3.55, wl, "AFTER: what the AI proposed", GREEN, 12, 0.3)
    tbox(s, LM, 3.85, wl, 1.7, [P(bt.LIM_AFTER, 17, False, INK)], inset=(0.02, 0.02))
    tbox(s, LM, 5.65, wl, 1.3, [P("Information loss from asymmetry:", 20, False, GREY, after=0), P("Only 9% survives!", 36, True, RED)], inset=(0.02, 0.02))


def s_pp(s):
    h = 3.3
    tbox(s, LM, 1.3, 4.0, 0.85, [P("Version 2: two documents, one question, a stamp. Inspired by the videogame Papers, Please and Tinder.", 13, True, GREY)], anchor="m", inset=(0.02, 0.02))
    p1, w1, h1 = float_picture(s, "desk-v3-identity.png", LM, 2.25, h=h)
    x2 = LM + w1 + 0.45
    tbox(s, x2, 1.3, 4.6, 0.85, [P("Version 3 Redesign: one card, one question", 14, True, TEAL)], anchor="m", inset=(0.02, 0.02))
    p2, w2, h2 = float_picture(s, "desk-new-identity.png", x2, 2.25, h=h)
    x3 = x2 + w2 + 0.45
    label(s, x3, 1.3, RM - x3, "WHAT CHANGED", TEAL, 13, 0.85)
    items = ["One card per question", "The news always on top", "“In TTE now”, then “After you accept”", "Ticks and crosses, not paragraphs", "“No thanks” means discard"]
    tbox(s, x3, 2.25, RM - x3, h, [P(t, 15, True, INK, after=9, bullet=True) for t in items], inset=(0.02, 0.02))
    tbox(s, LM, 5.75, CW, 1.2, [P("“It feels like Tinder.”", 32, True, INK, italic=True, after=2), P("A first-time user, outside the library", 18, False, GREY)],
         anchor="m", inset=(0.02, 0.02))


def s_wrong(s):
    pic, pw, ph = float_picture(s, "desk-new-lee-identity.png", LM, 1.3, h=5.55)
    x0 = LM + pw + 0.5
    w = RM - x0
    half = w / 2
    for i, (big, lab) in enumerate([("71", "the age in the article"), ("1888", "the birth year of the record offered")]):
        tbox(s, x0 + i * half, 1.3, half - 0.15, 1.9, [P(big, 66, True, NAVY, after=1), P(lab, 14, False, GREY)], inset=(0.02, 0.02))
    tbox(s, x0, 3.3, w, 1.15, [P("71 and 1888 cannot be one person.", 30, True, RED)], anchor="m", inset=(0.02, 0.02))
    tbox(s, x0, 4.5, w, 2.4, [P("The model flagged it, and a reviewer found the right record, an engineer, by search.", 17, True, INK, after=8),
                              P("In the English article, the same man matched correctly. Of 66 Chinese-named people in our feed, TTE holds the Chinese name for 17.", 15, False, GREY)],
         inset=(0.02, 0.02))


def s_sources(s):
    pic, pw, ph = float_picture(s, "desk-new-tang-death.png", LM, 1.4, w=6.15)
    x0 = LM + pw + 0.5
    w = RM - x0
    blocks = [("THE CHANGE", GREY, "Replace the day of death, 15, with 16"), ("THE SENTENCE ON SCREEN", AMBER, "“…has passed away at the age of 94.” There is no date in it."),
              ("BEHIND IT, NOT SHOWN", RED, "CNA and The Straits Times, as we recorded them: the 15th. Zaobao, the one source on screen: the 16th.")]
    y = 1.4
    for k, (lab, col, text) in enumerate(blocks):
        hh = 1.15 if k == 0 else (1.4 if k == 1 else 1.7)
        rule(s, x0, y + 0.05, 0.06, hh - 0.2, col)
        tbox(s, x0 + 0.2, y, w - 0.2, hh, [P(lab, 12, True, col, after=3), P(text, 19, False, INK)], inset=(0.02, 0.02))
        y += hh + 0.12
    tbox(s, LM, 6.4, CW, 0.55, [P("I cannot tell you which date is right. Neither can the screen.", 24, True, NAVY)], anchor="m", inset=(0.02, 0.02))


def s_leftout(s):
    pic, pw, ph = float_picture(s, "desk-new-fam-change.png", LM, 1.3, h=4.45)
    sx = pw / 1502
    block(s, LM + 18 * sx, 1.3 + 262 * sx, 1466 * sx, 138 * sx, None, radius=0.05, line=RED, line_w=3)
    ghost = tbox(s, LM, 1.3 + ph + 0.15, pw, 0.8, [P("NOT PROPOSED:  “Chairperson of the Agency for Integrated Care, from 2026”", 15, True, AMBER, "c")], anchor="m",
                 fill=RGBColor.from_string("FBF1DC"), radius=0.08, line=AMBER, line_w=2.25)
    ghost.line.dash_style = MSO_LINE.DASH
    x0 = LM + pw + 0.5
    w = RM - x0
    rule(s, x0, 1.35, 0.06, 1.1, RED)
    tbox(s, x0 + 0.2, 1.3, w - 0.2, 1.25, [P("The quote is about her awards", 20, True, RED, after=2), P("Nothing on screen says she is the new chairperson.", 16, False, INK)], inset=(0.02, 0.02))
    rule(s, x0, 2.8, 0.06, 0.8, AMBER)
    tbox(s, x0 + 0.2, 2.75, w - 0.2, 0.95, [P("Her description got no edit", 20, True, AMBER, after=2), P("His did.", 16, False, INK)], inset=(0.02, 0.02))
    tbox(s, x0, 3.95, w, 1.7, [P(runs=[("A reviewer can check what was proposed. They ", {"color": INK}), ("cannot see what was left out.", {"color": RED})], size=27, bold=True)], inset=(0.02, 0.02))
    tbox(s, x0, 5.85, w, 1.1, [P("Not solved. We changed the prompts so an appointment is recorded when announced: written and code-tested, not yet re-run on the model.", 13, False, GREY)],
         inset=(0.02, 0.02))


def s_four(s):
    qs = ["Is it the same entity?", "What did it remove or add?", "Is there evidence for this change?", "What was left out?"]
    for i, q in enumerate(qs):
        x, y = LM + (i % 2) * 5.9, 1.45 + (i // 2) * 2.05
        rule(s, x, y, 5.3, 0.05, RED if i == 3 else TEAL)
        tbox(s, x, y + 0.1, 5.3, 1.8, [P(str(i + 1), 40, True, RED if i == 3 else TEAL, after=0), P(q, 30, True, INK)], inset=(0.02, 0.02))
    tbox(s, LM, 5.75, CW, 1.2, [P(runs=[("If the screen cannot answer these, the human in the loop is a ", {"color": INK}), ("formality.", {"color": RED})], size=30, bold=True)],
         anchor="m", inset=(0.02, 0.02))


def s_unknown(s):
    cols = [("Not measured yet", TEAL, ["Whether each proposal is correct", "Whether it saves time", "Next: labelled sheets, then cataloguers swapping between the tool and reading the news"]),
            ("What it took", TEAL, ["One person, on free tiers", "Paid access: under SGD $15 / ZAR 195 a month (estimated)", "The hard part was the screen, not the model"]),
            ("Before you start", RED, ["Check your copyright exception (ours: Singapore’s computational data analysis provision)", "Nothing reaches the file without a named person’s decision"])]
    colw = CW / 3
    for i, (head, col, lines) in enumerate(cols):
        x = LM + i * colw
        if i:
            rule(s, x - 0.18, 1.5, 0.015, 5.0, LINE)
        tbox(s, x, 1.4, colw - 0.35, 5.5, [P(head, 28, True, col, after=16)] + [P(t, 19, False, INK, after=14, bullet=True) for t in lines], inset=(0.02, 0.02))


# ---- the talk: slide builders, header labels and spoken notes -------------------------------

NOTES = {
    "idea": "Here is what you will leave with: one idea, and four questions.\n\n"
            "The idea: “human in the loop” is only true if the human can see enough to disagree. You will hear that phrase in every AI policy discussion, and very few people say what it takes. In this talk it comes down to one screen.\n\n"
            "The four questions are ones you can ask of any AI-suggested change to a catalogue record, whether it comes from a vendor, a colleague, or your own pipeline. Each one comes from a real card in our live system. "
            "I will show you the card, you will see what the screen hid, and by the end you will have all four.",
    "problem": "Start with the problem. Every morning, someone at our library reads the news. About sixty Singapore articles a day. The outlets publish more, but these are their Singapore feeds.\n\n"
               "Among those sixty, roughly five or six, a bit under one in ten, report something that changes a record: someone appointed, someone died, an organization renamed. The rest is noise. "
               "Finding the five or six means reading all sixty.",
    "record": "What is a record? It is the library's one agreed entry for a person, organization or place: the name, dates, posts, a short description. This one is for Gerard Ee.\n\n"
              "Other systems copy it: our discovery systems, the national archives, other government agencies, and VIAF. So when the news changes something, the record has to change too. If it does not, the mistake travels.",
    "labour": "So to find the five or six, a person reads all sixty. Every day. And that is only the Singapore feeds. Add an outlet or a language, and it grows. That is the labour.\n\n"
              "So we asked one question: can an AI do the reading, and leave people the deciding?",
    "how": "Here is how it works. Six stages. The first five run on their own, on a schedule.\n\n"
           "Ingest collects titles and summaries from three news feeds. Relevance reads only the title: does this change a record? Extraction pulls out the people, places and facts, with one quoted sentence. Retrieval finds candidate records by character similarity, and uses no AI. "
           "Resolution asks: is this the same entity, and what does the record lack?\n\n"
           "The sixth stage is a person. Run over our archive back to 2015 and the live feed, it has read almost three hundred thousand articles, judged about twenty-eight thousand relevant, and proposed 9,844 changes to existing records. None of those has been through a formal evaluation yet.",
    "split": "Here is that, on one article. The Straits Times, 31 August: a social service veteran, Gerard Ee, steps down as chairperson of the Agency for Integrated Care. Anita Fam takes over.\n\n"
             "The AI reads the article and finds two people. It finds each one's record and proposes changes. Gerard Ee's card has three. Anita Fam's has two. Those cards go to a cataloguer.\n\n"
             "The AI reads, the AI proposes, a person decides. Nothing is written to the file by the AI, ever. Everything else I am going to say is about what that person is shown when they decide.",
    "test": "Now you are the cataloguer. This is everything the first version of our screen showed. At the top, a sentence from a news article: a man aged sixty-four, a military background, "
            "forty years in public service, awarded a national medal. Below it, the description our AI proposes for his record. It draws on the article, and it reads well.\n\n"
            "Would you approve it? Take ten seconds. [PAUSE, and let them read.] Hold on to your answer. I will come back to it.",
    "reveal": "Now back to the description you were asked to approve. On the right is the real screen as it looks today. On the left, what the record said, and what the AI replaced it with.\n\n"
              "The record said: Chairman of A*STAR; Permanent Secretary at the Ministry of Education; Chief of Defence Force; Chief of Army. Every post, with dates. The AI replaced all of it with a sentence saying he dedicated over four decades to public service. Only nine per cent of the original survives. It replaced a career with a compliment.\n\n"
              "That is the asymmetry. The first screen showed what was added, and nothing of what was lost. There was no error message. To be clear: the error is the pipeline's, not his.",
    "pp": "So we changed the screen. Let me tell you what the first one was like. If you have played Papers, Please, you know the feeling: you are a border inspector, you have two documents, you compare them against the rules, and you stamp approved or denied. "
          "Our earlier desk was inspired by that, and by Tinder. The article on one side, the record on the other, one question, a stamp.\n\n"
          "Two cataloguers used it and found problems, and helped redesign it. Then a first-time user, someone outside the library, looked at it and said: it feels like Tinder.\n\n"
          "That is the opposite of what we want. Papers, Please makes you slow down and look. Tinder makes you swipe. The same screen can be either, and the design decides which. So the redesign has one card and one question. The news is always on top, then what the record says now, then what it will say after you accept. Ticks and crosses for the identity checks. And 'No thanks' means discard.",
    "wrong": "Now three things the old screens hid. First, the wrong person.\n\n"
             "This is a Chinese-language article about a man aged seventy-one who won a national science medal. We match Chinese names a second time through an English spelling, which raised our match rate from forty to seventy-seven per cent. But the spelling is the model's guess. "
             "This guess landed on Lee Choon Seng: a banker, born in 1888. A man of seventy-one and a man born in 1888 cannot be the same person.\n\n"
             "The model flagged it itself, and the reviewer found the right record, an engineer, by search. In the English article, the same man matched correctly. The screen has to put the facts side by side, and it has to say when a record was found through a guess.",
    "sources": "Second: what supports a change. A reviewer is shown the sources that back a change. Not the ones that disagree with it.\n\n"
               "This record has a day of death: the fifteenth. The AI proposes the sixteenth. Look at the sentence on the screen. It says he died aged ninety-four. There is no date in it at all.\n\n"
               "What the screen does not show: CNA and The Straits Times, as we recorded them, say he died on the fifteenth. Zaobao, which supplied the proposal, said the sixteenth. I cannot tell you which is right, and the screen cannot either. A death date goes into a file that other agencies and VIAF draw on. A change shown with only its own supporters invites you to approve it.",
    "leftout": "Third, and this is the one we have not solved. Back to the article from the start: Gerard Ee steps down, Anita Fam takes over. This is her card. It asks: add Agency for Integrated Care to her affiliations?\n\n"
               "That is fine. Now look at the quote. It is about her awards. Nothing on the screen says she is the new chairperson. And her description got no edit, though his did.\n\n"
               "The AI had caught the fact. The last step left it out, probably because her post starts the next day, and nothing told it what to do with an announced appointment. A reviewer can check what was proposed. They cannot see what was left out. In this case the only way to know is to have read the article.\n\n"
               "We have changed the prompts so that an appointment is recorded when it is announced, and each change now quotes its own sentence. We have tested the code, but we have not yet re-run the model on this article. What we have not solved is showing a reviewer what the article says that no change covers.",
    "four": "These are the four I promised. Is it the same entity? We saw a record born in 1888 offered for a man of seventy-one. What did it remove or add? A Chief of Army, replaced by a compliment. "
            "Is there evidence for this change? A death date changed, with a quote that has no date. And the hard one: what was left out? A new post, and nothing on the screen shows it.\n\n"
            "If the screen in front of you cannot answer these, the human in the loop is a formality.",
    "unknown": "What do we know? Less than I would like. Can a person decide each proposal? Yes: two cataloguers used the first version and helped redesign it. Is each proposal correct? We have not measured that. Does it save time? Not yet either. "
               "Next come labelled sheets from one month of the feed, with labellers who cannot see the AI's answer, and then a field test where cataloguers swap between the tool and reading the news.\n\n"
               "What would it take for you? One person built this, on free tiers. Paid access is estimated at under fifteen Singapore dollars a month, about a hundred and ninety-five rand. The hard part was never the model. It was the screen.\n\n"
               "And before you start, check your copyright position. Ours is Singapore's computational data analysis provision, and the article is read, not stored. Nothing reaches our file without a named person's decision. That is the safeguard.",
    "thanks": "So: Papers, Please, not Tinder. A human in the loop is only real if the human can see enough to disagree. Build the screen so that a person can look, and so that they can see what was left out.\n\n"
              "Thank you. I would be glad to take your questions. The next slides are backup, if they help: the numbers, the evaluation plan, cost and law, the schema lesson, whether a small model could do the first filter, more cards, and an earlier deletion.",
    "title": "Good afternoon. I am Ashwin Nair, from the National Library and Archives Board in Singapore. I want to talk about a screen: the one that sits between an AI and a catalogue record.",
}


# ---- v3: the talk rebuilt on one thread, "most of what went wrong was a missing step between the AI and the person" -------------------
# Each failure slide now ends in what we changed and what is still open. Same screenshots, same template.

def s_idea(s):
    tbox(s, LM, 1.3, CW, 2.1, [P(runs=[("An AI proposes. A person approves. That only works if the person can tell when the ", {"color": INK}), ("AI is wrong.", {"color": RED})], size=38, bold=True)],
         inset=(0.02, 0.02))
    tbox(s, LM, 3.3, CW, 0.6, [P("Most of what went wrong in our system was a missing step between the two.", 22, False, GREY)], anchor="m", inset=(0.02, 0.02))
    label(s, LM, 4.05, 6, "FOUR CHECKS TO TAKE HOME")
    qs = ["Is it the right record?", "What does it change, and what does it lose?", "What backs it, and does anything disagree?", "What did it miss?"]
    for i, q in enumerate(qs):
        x = LM + i * 2.9
        rule(s, x, 4.5, 2.7, 0.05, RED if i == 3 else TEAL)
        tbox(s, x, 4.6, 2.7, 1.7, [P(str(i + 1), 30, True, RED if i == 3 else TEAL, after=2), P(q, 19, True, INK)], inset=(0.02, 0.04))
    tbox(s, LM, 6.4, CW, 0.5, [P("Each one is a real failure from our live system, and each is now a step.", 17, False, GREY)], anchor="m", inset=(0.02, 0.02))


def s_record(s):
    tbox(s, LM, 1.45, 6.4, 3.4, [P("An authority record fixes one preferred form of a name, lists its variants, and holds a few facts.", 34, True, INK)], inset=(0.02, 0.02))
    tbox(s, LM, 4.9, 6.4, 1.9, [P("Catalogue records link to it. Discovery systems, Archives Online, other agencies and VIAF draw on it, so a mistake travels.", 20, False, GREY)], inset=(0.02, 0.02))
    card = block(s, 7.9, 1.45, 4.53, 5.0, WHITE, radius=0.12, line=LINE, line_w=1.25)
    shadow(card)
    tbox(s, 8.15, 1.6, 4.1, 0.4, [P("PERSON  ·  no. 18567994", 11, True, GREY)], anchor="m", inset=(0.02, 0.02))
    tbox(s, 8.15, 2.0, 4.1, 0.7, [P("Ee, Gerard", 28, True, INK)], anchor="m", inset=(0.02, 0.02))
    rows = [("OCCUPATION", "Accountant · Auditor · Member of Parliament"), ("BORN", "1949"), ("AWARDS", "Public Service Medal (1993) and three more")]
    y = 2.85
    for k, v in rows:
        tbox(s, 8.15, y, 4.1, 0.75, [P(k, 11, True, GREY, after=1), P(v, 15, False, INK)], inset=(0.02, 0.02))
        y += 0.78
    tbox(s, 8.15, 5.2, 4.1, 1.1, [P("A practicing accountant for almost 30 years, he is well known in the corporate and charity arenas.", 14, False, GREY)], inset=(0.02, 0.02))


def s_reveal(s):
    pic, pw, ph = float_picture(s, "desk-new-lim-diff.png", 7.75, 1.3, h=5.6)
    wl = 6.55
    label(s, LM, 1.25, wl, "BEFORE: what the record said", RED, 12, 0.3)
    tbox(s, LM, 1.52, wl, 1.75, [P(runs=[(bt.LIM_BEFORE_KEPT, {"bold": True, "color": INK}), (bt.LIM_BEFORE_GONE, {"color": RED, "strike": True})], size=15)], inset=(0.02, 0.02))
    label(s, LM, 3.3, wl, "AFTER: what the AI proposed", GREEN, 12, 0.3)
    tbox(s, LM, 3.57, wl, 1.55, [P(bt.LIM_AFTER, 15, False, INK)], inset=(0.02, 0.02))
    tbox(s, LM, 5.15, wl, 0.95, [P("Only 9% of the record survives.", 30, True, RED)], anchor="m", inset=(0.02, 0.02))
    tbox(s, LM, 6.1, wl, 0.85, [P(runs=[("The missing step: ", {"bold": True, "color": TEAL}), ("a change should only add. If it removes anything, the screen says so and says how much. We now measure what survives and warn when it drops.", {"color": INK})], size=14)],
         inset=(0.02, 0.02))


def s_wrong(s):
    pic, pw, ph = float_picture(s, "desk-new-lee-identity.png", LM, 1.3, h=5.55)
    x0 = LM + pw + 0.5
    w = RM - x0
    steps = [("1", "The article names him in Chinese: 李全盛."), ("2", "The AI guesses an English spelling: “Lee Choon Seng”."),
             ("3", "Our search finds that exact string: a banker, born 1888. A perfect-score match."), ("4", "But the article says he is 71. A man of 71 and a man born in 1888 cannot be one person.")]
    y = 1.3
    for n, text in steps:
        disc(s, x0 + 0.22, y + 0.27, 0.44, RED if n == "4" else NAVY, n, 14)
        tbox(s, x0 + 0.6, y, w - 0.6, 0.85, [P(text, 15, n == "4", RED if n == "4" else INK)], anchor="m", inset=(0.02, 0.02))
        y += 0.92
    tbox(s, x0, 5.1, w, 1.85, [P(runs=[("The missing step: ", {"bold": True, "color": TEAL}), ("search the original-language name first, treat any guessed spelling as weak evidence, and mark it on screen. "
                                    "The pipeline flagged this one itself; a reviewer found the right record by search. Of 66 Chinese-named people in our feed, TTE holds the Chinese name for 17.", {"color": INK})], size=13)],
         inset=(0.02, 0.02))


def s_sources(s):
    pic, pw, ph = float_picture(s, "desk-new-tang-death.png", LM, 1.4, w=6.15)
    x0 = LM + pw + 0.5
    w = RM - x0
    blocks = [("THE CHANGE", GREY, "Replace the day of death, 15, with 16"), ("THE SENTENCE ON SCREEN", AMBER, "“…has passed away at the age of 94.” There is no date in it."),
              ("BEHIND IT, NOT SHOWN", RED, "CNA and The Straits Times, as we recorded them: the 15th. Zaobao, the one source on screen: the 16th.")]
    y = 1.4
    for k, (lab, col, text) in enumerate(blocks):
        hh = 1.15 if k == 0 else (1.4 if k == 1 else 1.7)
        rule(s, x0, y + 0.05, 0.06, hh - 0.2, col)
        tbox(s, x0 + 0.2, y, w - 0.2, hh, [P(lab, 12, True, col, after=3), P(text, 19, False, INK)], inset=(0.02, 0.02))
        y += hh + 0.12
    tbox(s, LM, 6.0, CW, 0.95, [P(runs=[("Still open: ", {"bold": True, "color": RED}), ("the two articles that agree with the record produce no proposal, so the screen never shows them. "
                                   "The next step is to show every article that states the current value beside the change.", {"color": INK})], size=17)], anchor="m", inset=(0.02, 0.02))


def s_leftout(s):
    pic, pw, ph = float_picture(s, "desk-new-fam-change.png", LM, 1.3, h=4.45)
    sx = pw / 1502
    block(s, LM + 18 * sx, 1.3 + 262 * sx, 1466 * sx, 138 * sx, None, radius=0.05, line=RED, line_w=3)
    ghost = tbox(s, LM, 1.3 + ph + 0.15, pw, 0.8, [P("NOT PROPOSED:  “Chairperson of the Agency for Integrated Care, from 2026”", 15, True, AMBER, "c")], anchor="m",
                 fill=RGBColor.from_string("FBF1DC"), radius=0.08, line=AMBER, line_w=2.25)
    ghost.line.dash_style = MSO_LINE.DASH
    x0 = LM + pw + 0.5
    w = RM - x0
    rule(s, x0, 1.35, 0.06, 1.1, RED)
    tbox(s, x0 + 0.2, 1.3, w - 0.2, 1.25, [P("The quote is about her awards", 20, True, RED, after=2), P("Nothing on screen says she is the new chairperson.", 16, False, INK)], inset=(0.02, 0.02))
    rule(s, x0, 2.8, 0.06, 0.8, AMBER)
    tbox(s, x0 + 0.2, 2.75, w - 0.2, 0.95, [P("Her description got no edit", 20, True, AMBER, after=2), P("His did.", 16, False, INK)], inset=(0.02, 0.02))
    tbox(s, x0, 3.9, w, 1.5, [P(runs=[("A reviewer can check what was proposed. They ", {"color": INK}), ("cannot see what was left out.", {"color": RED})], size=24, bold=True)], inset=(0.02, 0.02))
    tbox(s, x0, 5.5, w, 1.45, [P(runs=[("What we changed: ", {"bold": True, "color": TEAL}), ("an announced appointment is now recorded when announced (code-tested, not yet re-run on the model), and the desk offers facts the article states that no change covers. ", {"color": INK}),
                                      ("Still open: ", {"bold": True, "color": RED}), ("a full second pass of the article against the record.", {"color": INK})], size=13)], inset=(0.02, 0.02))


def s_four(s):
    rows = [("Is it the right record?", "A guessed spelling matched a different man", "Facts side by side. Guessed spellings are marked."),
            ("What does it change, and what does it lose?", "A career became a compliment", "Shows what is removed and how much survives. Descriptions held to the guide’s 5 sentences."),
            ("What backs it, and does anything disagree?", "A death date whose quote had no date", "Each change quotes its own sentence. Next: show the articles that disagree."),
            ("What did it miss?", "A new chairperson was never proposed", "Offers facts the article states that no change covers.")]
    cx = [LM, LM + 3.7, LM + 7.4]
    cw = [3.5, 3.5, CW - 7.4]
    for x, wd, head in zip(cx, cw, ("THE CHECK", "WHAT WENT WRONG", "WHAT OUR SCREEN DOES")):
        label(s, x, 1.25, wd, head, TEAL, 12, 0.35)
    for i, (q, bad, fix) in enumerate(rows):
        y = 1.75 + i * 1.3
        rule(s, LM, y, CW, 0.02, LINE)
        tbox(s, cx[0], y + 0.08, cw[0], 1.15, [P(q, 19, True, INK)], anchor="m", inset=(0.02, 0.02))
        tbox(s, cx[1], y + 0.08, cw[1], 1.15, [P(bad, 16, False, RED)], anchor="m", inset=(0.02, 0.02))
        tbox(s, cx[2], y + 0.08, cw[2], 1.15, [P(fix, 16, False, INK)], anchor="m", inset=(0.02, 0.02))


def s_unknown(s):
    cols = [("Not measured yet", TEAL, ["Whether each proposal is correct", "Whether it saves time", "Whether a second model could replace the person: untested",
                                       "A first pilot: one non-cataloguer decided 48 cards in 55 minutes. The records built from many articles took 76% of the time.",
                                       "Next: labelled sheets, then cataloguers swapping between the tool and reading the news"]),
            ("What it took", TEAL, ["One person, relying on a team for feedback, on free tiers", "Paid access: under SGD $15 / ZAR 195 a month (estimated)", "The hard part was the screen, not the model"]),
            ("Before you start", RED, ["Check your copyright exception (ours: Singapore’s computational data analysis provision)", "Nothing reaches the file without a named person’s decision"])]
    colw = CW / 3
    for i, (head, col, lines) in enumerate(cols):
        x = LM + i * colw
        if i:
            rule(s, x - 0.18, 1.5, 0.015, 5.0, LINE)
        tbox(s, x, 1.4, colw - 0.35, 5.5, [P(head, 28, True, col, after=16)] + [P(t, 16 if i == 0 else 19, False, INK, after=12, bullet=True) for t in lines], inset=(0.02, 0.02))


def b_timing(s):
    stats = [("55 min", "for 48 records, one reviewer, median 33 seconds each"), ("76%", "of the time went on the 29 records built from two or more articles"),
             ("13", "sentences to add to Lawrence Wong’s description, from 83 articles"), ("90 → 36", "description sentences to read after capping at the guide’s five")]
    colw = CW / 4
    for i, (big, lab) in enumerate(stats):
        tbox(s, LM + i * colw, 1.6, colw - 0.2, 2.6, [P(big, 44, True, RED if i == 1 else NAVY, after=4), P(lab, 16, False, GREY)], inset=(0.02, 0.02))
    rule(s, LM, 4.4, CW, 0.015, LINE)
    tbox(s, LM, 4.55, CW, 1.2, [P(runs=[("The missing step: ", {"bold": True, "color": TEAL}), ("a famous record collects sentences from dozens of articles, and the reviewer was left to curate them. Now a note carries only what fits the guide’s five sentences, best supported first, and shows the rest as held back.", {"color": INK})], size=20)],
         inset=(0.02, 0.02))
    tbox(s, LM, 6.1, CW, 0.8, [P("A replay on the 48 cards, judged by one non-cataloguer: a pilot, not a measurement of correctness. The cap is code-tested; it has not run on a live deck.", 13, False, GREY)],
         anchor="m", inset=(0.02, 0.02))


NOTES.update({
    "idea": "Here is what you will leave with: one thread and four checks.\n\n"
            "In our system an AI proposes changes to a library record, and a person approves them. That only works if the person can tell when the AI is wrong. Most of what went wrong for us was not a bad AI or a careless person. It was a missing step between the two.\n\n"
            "The four checks are things you can ask of any AI-suggested change to a catalogue record, whether it comes from a vendor, a colleague or your own pipeline. Each came from a real failure in our live system, and each is now a step.",
    "record": "What is an authority record? It fixes one preferred form of a name, lists its variants, and holds a few facts: the dates, the posts, a short description. This one is for Gerard Ee.\n\n"
              "Catalogue records link to it. Our discovery systems, Archives Online, other government agencies and VIAF draw on it. So when the news changes something, the record has to change too, and if it is wrong, the mistake travels.",
    "reveal": "Now back to the description you were asked to approve. On the right is the real screen as it looks today. On the left, what the record said, and what the AI replaced it with.\n\n"
              "The record said: Chairman of A*STAR; Permanent Secretary at the Ministry of Education; Chief of Defence Force; Chief of Army. Every post, with dates. The AI replaced all of it with a sentence saying he dedicated over four decades to public service. Only nine per cent of the original survives.\n\n"
              "The first screen showed what was added, and nothing of what was lost. There was no error message. The error is the pipeline's, not his. The missing step: a change should only add. If it removes anything, the screen has to say so and say how much. We now measure what survives and warn when it drops.",
    "wrong": "A chain of four steps. A Chinese-language article names a man, 李全盛. The AI guesses an English spelling, Lee Choon Seng. Our search finds that exact string: a banker, born in 1888. It scores a perfect match, because the spelling was a guess that happened to land on a real record.\n\n"
             "But the article says he is seventy-one. A man of seventy-one and a man born in 1888 cannot be one person. This happens with any language written in a non-Latin script.\n\n"
             "The missing step: search the original-language name first, treat any guessed spelling as weak evidence, and mark it on the screen. The pipeline flagged this one itself, and the reviewer found the right record, an engineer, by search.",
    "sources": "A reviewer is shown the source that backs a change. Not the ones that agree with the record.\n\n"
               "This record has a day of death: the fifteenth. The AI proposes the sixteenth. The sentence on the screen says he died aged ninety-four. There is no date in it at all. CNA and The Straits Times, as we recorded them, said the fifteenth. Zaobao, the one source on screen, said the sixteenth. I cannot tell you which is right.\n\n"
               "Why the screen never showed the other two: articles that agree with the record produce no proposal, so they never reach the screen. That is still open. The next step is to show every article that states the current value beside the change.",
    "leftout": "Back to the article from the start: Gerard Ee steps down, Anita Fam takes over. This is her card. It asks: add Agency for Integrated Care to her affiliations? That is fine. Now look at the quote. It is about her awards. Nothing on the screen says she is the new chairperson, and her description got no edit, though his did.\n\n"
                "A reviewer can check what was proposed. They cannot see what was left out. We changed the prompts so an appointment is recorded when it is announced. That is written and code-tested, but not yet re-run on the model. The desk also now offers facts the article states that no change covers, to accept only if you agree. Still open: a full second pass of the article against the record.",
    "four": "These are the four checks, and what our screen does about each. Is it the right record? Facts side by side, and guessed spellings marked. What does it change and lose? It shows what is removed and how much survives, and holds descriptions to the guide's five sentences. What backs it, and does anything disagree? Each change quotes its own sentence; next, the articles that disagree. And what did it miss? It offers facts the article states that no change covers.\n\n"
            "If you ask these of your own pipeline and cannot answer, add the step.",
    "unknown": "What do we know? Less than I would like. Can a person decide each proposal? Yes. Is each proposal correct? We have not measured that. Does it save time? Not yet. We also have a first pilot: one person who is not a cataloguer decided forty-eight cards in fifty-five minutes, and the records built from many articles took three quarters of the time, which is why description notes are now capped. Whether a second model could replace the person is untested.\n\n"
               "What would it take for you? One person built this, relying on a team for feedback, on free tiers. Paid access is estimated at under fifteen Singapore dollars a month, about a hundred and ninety-five rand. The hard part was never the model. It was the screen and the steps around it.\n\n"
               "And before you start, check your copyright position. Ours is Singapore's computational data analysis provision, and the article is read, not stored. Nothing reaches our file without a named person's decision.",
    "thanks": "So: an AI proposes, a person approves, and the steps in between decide whether that approval means anything. Build the screen so a person can see the evidence, and add the step each failure teaches you.\n\n"
              "Thank you. I would be glad to take your questions. The next slides are backup, if they help: the numbers, the evaluation plan, cost and law, the schema lesson, whether a small model could do the first filter, more cards, an earlier deletion, and a missing step we found by timing a reviewer.",
})
NOTES["timing"] = ("A pilot, not a measurement of correctness. One person who is not a cataloguer decided forty-eight cards in fifty-five minutes. The twenty-nine records built from two or more articles took seventy-six per cent of the time. "
                   "Lawrence Wong's description note carried thirteen sentences, from eighty-three articles, which also breaks the style guide's limit of five. Capping a note at what fits the guide takes the description sentences to read from ninety to thirty-six. "
                   "The cap is code-tested but has not yet run on a live deck.")

# (key, builder, header label or None to keep the user's, minutes)
MAIN = [("idea", s_idea, "One thread, four checks", 0.75), ("problem", s_problem, "The problem", 0.75), ("record", s_record, "What is an authority record?", 0.5), ("labour", s_labour, "The labour", 0.75),
        ("how", s_how, "How it works", 1.0), ("split", s_split, None, 1.0), ("test", s_test, None, 1.25), ("reveal", s_reveal, "A change should only add", 1.0), ("pp", s_pp, None, 1.0),
        ("wrong", s_wrong, "A guessed translation can look like a perfect match", 1.0), ("sources", s_sources, "Does anything disagree with this change?", 1.0),
        ("leftout", s_leftout, "What was left out", 1.5), ("four", s_four, "Four checks, and what our screen does", 0.75), ("unknown", s_unknown, None, 1.0)]


def b_small_model_v2(s):
    """The backup chart of the first-filter models, with jev (TypeSafe's decision model, no training) added: measured on a random 6,000 of the test articles."""
    rows = [("Flag everything", 0.19, "100", "base"), ("mmBERT-small, frozen", 0.53, "50", "base"), ("e5-small + logistic regression", 0.58, "45", "base"),
            ("e5-small + gradient boosting", 0.61, "43", "base"), ("Word counts + logistic regression", 0.66, "40", "base"), ("e5-small + small neural net", 0.66, "35", "base"),
            ("jev: a decision model, no training", 0.66, "30", "jev"), ("mmBERT-small, fine-tuned", 0.75, "25", "best")]
    bt.tbox(s, bt.L, 1.35, 4.2, 0.4, [bt.P("Approach", 14, True, bt.GREY)], anchor="m")
    bt.tbox(s, 4.8, 1.35, 4.9, 0.4, [bt.P("F1 on the test year (higher is better)", 14, True, bt.GREY)], anchor="m")
    bt.tbox(s, 10.1, 1.35, 2.63, 0.4, [bt.P("Passed on, per 100", 14, True, bt.GREY, "r")], anchor="m", inset=(0.02, 0.06))
    for i, (name, f1, passed, kind) in enumerate(rows):
        y = 1.8 + i * 0.52
        col = {"base": RGBColor.from_string("7FA9BC"), "jev": bt.RED, "best": bt.TEAL}[kind] if i else bt.LINE
        bt.tbox(s, bt.L, y, 4.2, 0.46, [bt.P(name, 16, kind != "base", bt.RED if kind == "jev" else bt.INK)], anchor="m", inset=(0.02, 0.02))
        bt.block(s, 4.8, y + 0.06, 4.2 * f1 / 0.8, 0.34, col, radius=0.05)
        bt.tbox(s, 4.8 + 4.2 * f1 / 0.8 + 0.08, y, 0.8, 0.46, [bt.P(f"{f1:.2f}", 16, True, bt.INK)], anchor="m", inset=(0.02, 0.02))
        bt.tbox(s, 10.1, y, 2.63, 0.46, [bt.P(passed, 18, True, bt.NAVY, "r")], anchor="m", inset=(0.02, 0.02))
    bt.tbox(s, bt.L, 6.1, bt.W, 0.85, [bt.P("Scored against the internal model’s labels, not people’s. jev was never trained on them: a random 6,000 of the test articles. On 69 hard cases a person judged, "
                                           "the fine-tuned model scores 0.22 (it copies the labeller’s mistakes) and jev 0.23. “Passed on” is the share of articles sent to the next stage to keep 95% of the relevant ones.", 13, False, bt.GREY)],
            anchor="m", inset=(0.02, 0.02))


def main():
    prs = Presentation(SRC)
    slides = list(prs.slides)
    # the user's slides 2 to 13 map to: idea, problem, how, split, test, reveal, pp, wrong, sources, leftout, four, unknown
    user_order = ["idea", "problem", "how", "split", "test", "reveal", "pp", "wrong", "sources", "leftout", "four", "unknown"]
    by_key = dict(zip(user_order, slides[1:13]))
    builders = {k: (b, h, m) for k, b, h, m in MAIN}
    notes = {}
    for key, slide in by_key.items():
        keep_chrome(slide)
        builder, head, _m = builders[key]
        bt.TAG[0] = key
        if head:
            header(slide, head)
        builder(slide)
    # two new slides, cloned from the problem slide's chrome, then moved to follow it
    new = {}
    for key in ("record", "labour"):
        sl = clone(prs, by_key["problem"])
        keep_chrome(sl)
        builder, head, _m = builders[key]
        bt.TAG[0] = key
        header(sl, head)
        builder(sl)
        new[key] = sl
    ids = prs.slides._sldIdLst
    entries = list(ids)
    for k, el in zip(("record", "labour"), entries[-2:]):
        ids.remove(el)
    ids.insert(3, entries[-2])
    ids.insert(4, entries[-1])
    # footer numbers: the user moved slides in PowerPoint, so the printed numbers are stale
    import re
    all_slides = list(prs.slides)
    for i, sl in enumerate(all_slides, 1):
        shape = sl.shapes[5] if len(sl.shapes) > 5 else None
        if shape is not None and shape.has_text_frame and re.fullmatch(r"\d\d", shape.text_frame.text.strip()):
            set_text(shape, f"{i:02d}")
    # notes
    order = {"title": all_slides[0], **{k: by_key[k] for k in by_key}, **new}
    for key, sl in order.items():
        if key in NOTES:
            sl.notes_slide.notes_text_frame.text = NOTES[key]
    thanks = next(sl for sl in all_slides if any(sh.has_text_frame and sh.text_frame.text.strip() == "Thank you" for sh in sl.shapes))
    thanks.notes_slide.notes_text_frame.text = NOTES["thanks"]
    for sh in thanks.shapes:                                         # no more "Papers, Please" on the closing slide
        if sh.has_text_frame and sh.text_frame.text.strip().startswith("Papers, Please"):
            set_text(sh, "Questions welcome.")
    # the backup chart of first-filter models, rebuilt with jev's row added; the notes keep what was said and add one sentence
    small = next(sl for sl in all_slides if any(sh.has_text_frame and sh.text_frame.text.startswith("Backup: could a small model") for sh in sl.shapes))
    keep_chrome(small)
    bt.pill(small, 11.25, 0.27, 1.5, 0.4, "BACKUP", bt.RED, size=13)
    bt.TAG[0] = "small-model"
    b_small_model_v2(small)
    note = small.notes_slide.notes_text_frame
    if "jev" not in note.text:
        note.text = (note.text.rstrip() + " We also tried jev, a decision model from TypeSafe that answers yes or no questions and writes no text, with no training at all: "
                     "F1 0.66 on a random 6,000 test articles, and to keep 95 in 100 relevant articles it passes on 30 in 100, where the fine-tuned model passes 25. "
                     "On the 69 hard cases a person judged it scores 0.23, about the same.")
    nb = clone(prs, small)                                           # one more backup, at the end: the missing step found by timing a reviewer
    keep_chrome(nb)
    bt.pill(nb, 11.25, 0.27, 1.5, 0.4, "BACKUP", bt.RED, size=13)
    set_text(nb.shapes[2], "Backup: a missing step, found by timing a reviewer")
    set_text(nb.shapes[5], f"{len(prs.slides):02d}")
    b_timing(nb)
    nb.notes_slide.notes_text_frame.text = NOTES["timing"]
    prs.save(OUT)
    return all_slides, order


def script_docx(prs_path, seq=None, extra_minutes=None, out=None, version="v3"):
    import docx
    from docx.shared import Pt as DPt
    prs = Presentation(prs_path)
    d = docx.Document()
    d.styles["Normal"].font.name = "Arial"
    d.styles["Normal"].font.size = DPt(11)
    d.add_heading(f"Designing for the Reviewer: speaking script ({version})", 0)
    d.add_paragraph("IFLA AI symposium, 20-minute slot: about 15 minutes of talking, then 5 for questions. The times are a running clock. "
                    "Slides after the thank-you slide are backup, for questions only.")
    minutes = {"title": 0.25, **{k: m for k, _b, _h, m in MAIN}, **(extra_minutes or {}), "thanks": 0.5}
    seq = seq or ["title", "idea", "problem", "record", "labour", "how", "split", "test", "reveal", "pp", "wrong", "sources", "leftout", "four", "unknown", "thanks"]
    clock = 0.0
    slides = list(prs.slides)
    for i, sl in enumerate(slides, 1):
        titles = [sh.text_frame.text for sh in sl.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
        title = (titles[0] if titles else "")[:70].replace("\n", " ")
        text = sl.notes_slide.notes_text_frame.text if sl.has_notes_slide else ""
        if i <= len(seq):
            stamp = f"[{int(clock)}:{int(round((clock % 1) * 60)):02d}]"
            clock += minutes[seq[i - 1]]
        else:
            stamp = "[backup]"
        d.add_heading(f"Slide {i}: {title}  {stamp}", level=2)
        for chunk in text.split("\n\n"):
            if chunk.strip():
                d.add_paragraph(chunk)
    d.save(out or SCRIPT)
    return clock


if __name__ == "__main__":
    slides, order = main()
    bt.preview(OUT, PREVIEW)
    for problem in bt.PROBLEMS:
        print("OVERFLOW", problem)
    end = script_docx(OUT)
    print(f"{OUT.name}: {len(slides)} slides; the clock ends at {int(end)}:{int(round((end % 1) * 60)):02d}")
    sys.exit(1 if bt.PROBLEMS else 0)
