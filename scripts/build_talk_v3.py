"""
The IFLA talk, third pass: the story is "most of what went wrong was a missing step between the AI and the person".

    .venv/bin/python scripts/build_talk_v3.py

Starts, like v2, from data/dist/designing-for-the-reviewer.YOUR-EDITS-backup-1938.pptx (the user's own edited deck, never written to) and writes
data/dist/designing-for-the-reviewer-v3.pptx, data/dist/speaking-script-v3.docx and data/dist/talk-preview-v3/.

The spine, one question every slide answers: could the person tell the AI was wrong, and what step did we add so they can?
  the problem and the design (3 to 7), the first failure and the redesigned screen (7, 8), four missing steps each from a real card (9 to 13),
  the four steps as a checklist (14), a second model as a decision gate (15), what nobody had written down (16), what we do not know (17).

Every number on a slide was measured (the sources are in docs/paper.md and data/jev/); anything not built is labelled "next" or "still open".
It reuses build_talk_v2's drawing helpers and build_talk's fit-checker, so every text box is measured before it is placed.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import build_talk as bt  # noqa: E402
import build_talk_v2 as v2  # noqa: E402
from build_talk import AMBER, GREEN, GREY, INK, LINE, NAVY, P, RED, TEAL, WHITE, MSO_LINE, MSO_SHAPE, RGBColor, arrow, block, disc, tbox  # noqa: E402
from build_talk_v2 import BEIGE, CW, LM, PINK, RM, float_picture, header, keep_chrome, label, rule, shadow  # noqa: E402
from pptx import Presentation  # noqa: E402

from src.export.slides import clone, set_text  # noqa: E402

SRC = v2.SRC
OUT = ROOT / "data/dist/designing-for-the-reviewer-v3.pptx"
SCRIPT = ROOT / "data/dist/speaking-script-v3.docx"
PREVIEW = ROOT / "data/dist/talk-preview-v3"

TEAL_BG = RGBColor.from_string("E6F2F3")
AMBER_BG = RGBColor.from_string("FBF1DC")


def callout(s, x, y, w, h, tag, text, color, size=15):
    """A labelled note: a thin coloured rule, a small tag, one or two sentences."""
    rule(s, x, y + 0.04, 0.06, h - 0.1, color)
    return tbox(s, x + 0.2, y, w - 0.2, h, [P(tag, 12, True, color, after=3), P(text, size, False, INK)], inset=(0.02, 0.02))


# ---- the slides -----------------------------------------------------------------------------

def s_thesis(s):
    tbox(s, LM, 1.3, CW, 2.8, [P(runs=[("An AI proposes. A person approves. Most of what went wrong was a ", {"color": INK}), ("missing step", {"color": RED}),
                                       (" between them.", {"color": INK})], size=44, bold=True)], inset=(0.02, 0.02))
    label(s, LM, 4.15, 9, "FOUR MISSING STEPS WE FOUND, EACH FROM A REAL CARD IN OUR LIVE SYSTEM")
    steps = [("1", "Check the entity", "Is it really the same person or body?"), ("2", "Only add", "A change should add information, never erase it."),
             ("3", "Show the evidence", "Including the sources that disagree."), ("4", "Look for gaps", "What did the article say that no change covers?")]
    for i, (n, h, d) in enumerate(steps):
        x = LM + i * 2.9
        rule(s, x, 4.65, 2.7, 0.05, RED if i == 3 else TEAL)
        tbox(s, x, 4.75, 2.7, 2.1, [P(n, 30, True, RED if i == 3 else TEAL, after=0), P(h, 20, True, INK, after=4), P(d, 15, False, GREY)], inset=(0.02, 0.04))


def s_problem(s):
    tbox(s, LM, 1.3, CW, 2.5, [P(runs=[("Every morning, someone reads the news to find the ", {"color": INK}), ("5 to 6", {"color": RED}), (" articles that matter.", {"color": INK})],
                                 size=46, bold=True)], inset=(0.02, 0.02))
    tbox(s, LM, 3.85, CW, 0.8, [P(runs=[("Can an AI do the ", {"color": INK}), ("reading", {"color": RED}), (", and leave people the ", {"color": INK}), ("deciding", {"color": RED}),
                                        ("?", {"color": INK})], size=30, bold=True)], inset=(0.02, 0.02))
    hot = {6, 21, 38, 51, 57}
    for k in range(60):
        r, c = divmod(k, 30)
        color = RED if k in hot else (PINK if k == 12 else LINE)
        block(s, 0.95 + c * 0.32, 5.1 + r * 0.32, 0.2, 0.2, color, shape=MSO_SHAPE.OVAL)
    tbox(s, LM, 6.15, CW, 0.7, [P(runs=[("60", {"bold": True, "color": INK}), (" Singapore articles a day", {"color": INK}),
                                        ("     * There is more international news.", {"color": GREY, "size": 15})], size=22)], anchor="m", inset=(0.02, 0.02))


def s_record(s):
    tbox(s, LM, 1.35, 6.5, 2.4, [P("An authority record fixes one preferred form of a name, lists its variants, and holds a few facts.", 32, True, INK)], inset=(0.02, 0.02))
    tbox(s, LM, 3.95, 6.5, 2.9, [P("It records the variants too: 李光耀, Lee Kuan Yew.", 20, False, INK, after=12),
                                  P("Catalogue records link to it. Discovery systems, Archives Online, other agencies and VIAF draw on it, so a wrong record travels.", 20, False, GREY)],
         inset=(0.02, 0.02))
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


def s_first(s):
    tbox(s, LM, 1.35, 5.4, 2.0, [P("9,000+", 88, True, NAVY, after=0)], anchor="m", inset=(0.02, 0.02))
    tbox(s, LM, 3.3, 5.4, 0.9, [P("candidate updates from the first version, in one flat list", 20, False, GREY)], inset=(0.02, 0.02))
    lines = [("No sentence from the article", "to check a change against."), ("No confirmation", "of whose record it was."), ("A librarian could not make", "a single decision from it.")]
    for i, (a, b) in enumerate(lines):
        y = 1.5 + i * 1.15
        rule(s, 6.7, y + 0.05, 0.06, 0.85, TEAL)
        tbox(s, 6.95, y, RM - 6.95, 1.0, [P(a, 22, True, INK, after=0), P(b, 20, False, GREY)], inset=(0.02, 0.02))
    rule(s, LM, 5.2, CW, 0.015, LINE)
    tbox(s, LM, 5.35, CW, 1.5, [P(runs=[("A proposal you cannot judge is not output. It is work ", {"color": INK}), ("moved from the machine to the person", {"color": RED}),
                                        (" and left there.", {"color": INK})], size=32, bold=True)], anchor="m", inset=(0.02, 0.02))


def s_wrong(s):
    pic, pw, ph = float_picture(s, "desk-new-lee-identity.png", LM, 1.3, h=4.6)
    x0 = LM + pw + 0.45
    w = RM - x0
    label(s, x0, 1.25, w, "WHAT HAPPENED", GREY, 12, 0.3)
    rows = [("1", "The article names him in Chinese: 李全盛.", INK), ("2", "The AI guesses an English spelling: “Lee Choon Seng”.", RED),
            ("3", "Our search finds that exact string: a banker, born 1888. A perfect score.", INK), ("4", "The article says he is 71. The name matched. The man did not.", INK)]
    y = 1.6
    for n, text, col in rows:
        disc(s, x0 + 0.2, y + 0.3, 0.4, RED if n == "2" else NAVY, n, 13)
        tbox(s, x0 + 0.55, y, w - 0.55, 0.62, [P(text, 15, n in ("2", "4"), col)], anchor="m", inset=(0.02, 0.02))
        y += 0.68
    callout(s, x0, 4.45, w, 1.0, "STEP ADDED", "Match on facts, not names. Search the original-language name first. Mark any guessed spelling on the card.", TEAL, 14)
    tbox(s, LM, 6.05, CW, 0.85, [P(runs=[("STILL OPEN  ", {"bold": True, "color": GREY, "size": 12}),
                                         ("Of 66 Chinese-named people in our feed, TTE holds the Chinese name for 17. For the rest, a guess is the only bridge. Any name that passes through an AI’s "
                                          "transliteration has this problem.", {"color": INK, "bold": False})], size=15)], anchor="m", inset=(0.02, 0.02))


def s_reveal(s):
    pic, pw, ph = float_picture(s, "desk-new-lim-diff.png", 7.75, 1.3, h=5.6)
    wl = 6.55
    label(s, LM, 1.25, wl, "BEFORE: what the record said", RED, 12, 0.3)
    tbox(s, LM, 1.55, wl, 1.75, [P(runs=[(bt.LIM_BEFORE_KEPT, {"bold": True, "color": INK}), (bt.LIM_BEFORE_GONE, {"color": RED, "strike": True})], size=16)], inset=(0.02, 0.02))
    label(s, LM, 3.35, wl, "AFTER: what the AI proposed", GREEN, 12, 0.3)
    tbox(s, LM, 3.65, wl, 1.55, [P(bt.LIM_AFTER, 16, False, INK)], inset=(0.02, 0.02))
    tbox(s, LM, 5.2, wl, 0.9, [P(runs=[("Only 9% survives!", {"bold": True, "color": RED, "size": 34})], size=34)], anchor="m", inset=(0.02, 0.02))
    callout(s, LM, 6.1, wl, 0.85, "STEP ADDED", "A change should only add. The screen shows what is lost and warns when under 70% survives.", TEAL, 14)


def s_evidence(s):
    pic, pw, ph = float_picture(s, "desk-new-tang-death.png", LM, 1.3, w=5.5)
    x0 = LM + pw + 0.5
    w = RM - x0
    blocks = [("THE CHANGE", GREY, "Replace the day of death, 15, with 16", 0.95),
              ("THE SENTENCE ON SCREEN", AMBER, "“…has passed away at the age of 94.” There is no date in it.", 1.25),
              ("BEHIND IT, NOT SHOWN", RED, "CNA and The Straits Times: the 15th. Zaobao, the one source on screen: the 16th. Two articles that agree with the record make no change, so they never reach the screen.", 2.1)]
    y = 1.3
    for lab, col, text, hh in blocks:
        rule(s, x0, y + 0.05, 0.06, hh - 0.2, col)
        tbox(s, x0 + 0.2, y, w - 0.2, hh, [P(lab, 12, True, col, after=3), P(text, 17, False, INK)], inset=(0.02, 0.02))
        y += hh + 0.1
    callout(s, LM, 5.95, 5.6, 1.0, "STEP ADDED", "Each change quotes its own sentence.", TEAL, 16)
    callout(s, x0, 5.95, w, 1.0, "NEXT, NOT BUILT", "Show the other articles that say something different.", AMBER, 16)


def s_gaps(s):
    pic, pw, ph = float_picture(s, "desk-new-fam-change.png", LM, 1.3, h=4.2)
    sx = pw / 1502
    block(s, LM + 18 * sx, 1.3 + 262 * sx, 1466 * sx, 138 * sx, None, radius=0.05, line=RED, line_w=3)
    ghost = tbox(s, LM, 1.3 + ph + 0.12, pw, 0.7, [P("NOT PROPOSED:  “Chairperson of the Agency for Integrated Care, from 2026”", 14, True, AMBER, "c")], anchor="m",
                 fill=AMBER_BG, radius=0.08, line=AMBER, line_w=2.25)
    ghost.line.dash_style = MSO_LINE.DASH
    x0 = LM + pw + 0.5
    w = RM - x0
    rule(s, x0, 1.35, 0.06, 0.95, RED)
    tbox(s, x0 + 0.2, 1.3, w - 0.2, 1.05, [P("The quote is about her awards", 19, True, RED, after=2), P("Nothing on screen says she is the new chairperson.", 15, False, INK)], inset=(0.02, 0.02))
    rule(s, x0, 2.55, 0.06, 0.7, AMBER)
    tbox(s, x0 + 0.2, 2.5, w - 0.2, 0.8, [P("Her description got no edit", 19, True, AMBER, after=2), P("His did.", 15, False, INK)], inset=(0.02, 0.02))
    tbox(s, x0, 3.5, w, 1.3, [P(runs=[("A reviewer can check what was proposed. They ", {"color": INK}), ("cannot see what was left out.", {"color": RED})], size=22, bold=True)], inset=(0.02, 0.02))
    callout(s, x0, 4.85, w, 1.15, "STEP ADDED", "Record an appointment when it is announced. Code-tested, not yet re-run on the model. In a test, a second model flagged this gap.", TEAL, 13)
    tbox(s, LM, 6.2, CW, 0.7, [P(runs=[("STILL OPEN  ", {"bold": True, "color": GREY, "size": 12}), ("Showing a reviewer what the article says that no change covers.", {"color": INK, "bold": False})], size=17)],
         anchor="m", inset=(0.02, 0.02))


def s_steps(s):
    cols = [(LM, 3.0, "Check"), (LM + 3.15, 4.0, "What went wrong"), (LM + 7.3, CW - 7.3, "Step we added")]
    for x, w, lab in cols:
        label(s, x, 1.25, w, lab.upper(), GREY, 12, 0.35)
    rule(s, LM, 1.65, CW, 0.02, LINE)
    rows = [("1  Is it the right entity?", "An AI-guessed spelling matched a different man, at a perfect score.", "Match on facts, search the original name first, mark guessed spellings.", TEAL),
            ("2  Does it only add?", "A career replaced by a compliment: 9% of the old text survived.", "Show what is lost, warn under 70% kept, flag past 5 sentences.", TEAL),
            ("3  Is the evidence shown?", "A death date backed by a quote with no date. Other articles said otherwise.", "Each change quotes its own sentence. Next: show the articles that disagree.", TEAL),
            ("4  What did it miss?", "A new chairperson never became a change.", "Record an appointment when announced. Still open: show what no change covers.", RED)]
    for i, (a, b, c, col) in enumerate(rows):
        y = 1.8 + i * 1.28
        tbox(s, cols[0][0], y, cols[0][1], 1.15, [P(a, 19, True, col)], anchor="m", inset=(0.02, 0.02))
        tbox(s, cols[1][0], y, cols[1][1], 1.15, [P(b, 15, False, INK)], anchor="m", inset=(0.02, 0.02))
        tbox(s, cols[2][0], y, cols[2][1], 1.15, [P(c, 15, False, INK)], anchor="m", inset=(0.02, 0.02))
        if i < 3:
            rule(s, LM, y + 1.22, CW, 0.012, LINE)


def s_gate(s):
    tbox(s, LM, 1.25, CW, 1.0, [P(runs=[("Where a step needs a yes or no, we tried a small ", {"color": INK}), ("decision model", {"color": RED}),
                                        (": jev, from TypeSafe. It answers yes or no and writes nothing.", {"color": INK})], size=24, bold=True)], inset=(0.02, 0.02))
    items = [("99 in 100", "Asked to pick the right record, it chose the same one as Gemini for 99 in 100 matches. That is agreement with another AI, not correctness."),
             ("2025 vs 2026", "Asked to check each change against the article’s quote, it caught a library said to have closed in August 2025, in an article dated August 2026."),
             ("87 in 100", "Asked whether a new sentence is lasting enough to describe the entity, it ranked one reviewer’s doubtful cards below the accepted ones 87 times in 100 pairs.")]
    colw = CW / 3
    for i, (big, text) in enumerate(items):
        x = LM + i * colw
        rule(s, x, 2.55, colw - 0.3, 0.05, TEAL)
        tbox(s, x, 2.65, colw - 0.3, 3.0, [P(big, 36, True, NAVY, after=6), P(text, 16, False, INK)], inset=(0.02, 0.02))
    tbox(s, LM, 5.85, CW, 1.05, [P(runs=[("It cannot write. It can flag doubtful additions, but it cannot say ", {"color": INK}), ("what belongs in a description.", {"color": RED}),
                                         (" Nobody has written that rule.", {"color": INK})], size=24, bold=True)], anchor="m", inset=(0.02, 0.02))


def s_policy(s):
    tbox(s, LM, 1.2, CW, 0.9, [P("Automating exposed two decisions nobody had written down.", 27, True, INK)], inset=(0.02, 0.02))
    colw = CW / 2
    cols = [("Which facts belong in a description?", "The style guide says how to write one: 3 to 5 sentences. Not which facts. In our audit of 160 cards, one reviewer doubted 22 of 82 description additions, "
                                                    "none because it was wrong. Our editing rule keeps every fact, so descriptions only grow: about a quarter of stored rewrites went past 5 sentences."),
            ("When does a new entity deserve a record?", "31 in 100 entities have no record yet. Neither model was tested on whether they deserve one.")]
    for i, (head, text) in enumerate(cols):
        x = LM + i * colw
        rule(s, x, 2.35, colw - 0.4, 0.05, RED)
        tbox(s, x, 2.45, colw - 0.4, 3.0, [P(head, 22, True, RED, after=8), P(text, 16, False, INK)], inset=(0.02, 0.02))
    rule(s, LM, 5.35, CW, 0.015, LINE)
    tbox(s, LM, 5.45, CW, 1.5, [P(runs=[("Can the person be removed? ", {"bold": True, "color": INK}),
                                        ("For 52 in 100 entities, both models agree on the record and the quote backs every change. That is not the same as correct, and we have almost no human "
                                         "answers to check against. For now the person stays, not because models cannot match records, but because these two decisions have no written rule.",
                                         {"color": INK, "bold": False})], size=17)], anchor="m", inset=(0.02, 0.02))


def s_unknown(s):
    cols = [("Not measured yet", TEAL, ["Whether each proposal is correct", "Whether it saves time", "Next: labelled sheets, then cataloguers swapping between the tool and reading the news"]),
            ("What it took", TEAL, ["One person, relying on a team for feedback, on free tiers", "Paid access: under SGD $15 / ZAR 195 a month (estimated)",
                                    "The hard part was the steps between the model and the person"]),
            ("Before you start", RED, ["Check your copyright exception (ours: Singapore’s computational data analysis provision)", "Nothing reaches the file without a named person’s decision",
                                       "Building an agent for this? Test it on these four cases first"])]
    colw = CW / 3
    for i, (head, col, lines) in enumerate(cols):
        x = LM + i * colw
        if i:
            rule(s, x - 0.18, 1.5, 0.015, 5.0, LINE)
        tbox(s, x, 1.4, colw - 0.35, 5.5, [P(head, 28, True, col, after=16)] + [P(t, 19, False, INK, after=14, bullet=True) for t in lines], inset=(0.02, 0.02))


# ---- notes, order and minutes ---------------------------------------------------------------

NOTES = {
    "title": v2.NOTES["title"],
    "thesis": "Here is the one idea. We built a system where an AI proposes changes to a library's records and a person approves them. Most of what went wrong was not a bad AI, and it was not a careless person. "
              "It was a missing step between them.\n\nWe found four. Each one comes from a real card in our live system. By the end you will have a checklist you can use on any AI-assisted catalogue change, "
              "whether it comes from a vendor, a colleague or your own pipeline.",
    "problem": "Start with the problem. Every morning, someone at our library reads the news. About sixty Singapore articles a day. The outlets publish more, but these are their Singapore feeds.\n\n"
               "Among those sixty, five or six, a bit under one in ten, report something that changes a record: someone appointed, someone died, an organization renamed. Finding them means reading all sixty, "
               "every day, and it grows with every outlet or language you add.\n\nSo we asked one question: can an AI do the reading, and leave people the deciding?",
    "record": "What is an authority record? It fixes one preferred form of a name, lists its variants, such as 李光耀 and Lee Kuan Yew, and holds a few facts: dates, posts, a short description. This one is for Gerard Ee.\n\n"
              "Catalogue records link to it. Our discovery systems, the national archives, other government agencies and VIAF draw on it. So when the news changes something, the record has to change, "
              "and when a record is wrong, the mistake travels.",
    "how": v2.NOTES["how"],
    "split": v2.NOTES["split"],
    "first": "Our first version ran over a backlog of articles and produced more than nine thousand candidate updates. It was a flat list: a name, and a proposed change. No sentence from the article to check a change against, "
             "and nothing to confirm whose record it was. A librarian could not make a single decision from it.\n\n"
             "A proposal you cannot judge is not output. It is work moved from the machine to the person and left there. So we redesigned the screen.",
    "pp": v2.NOTES["pp"],
    "wrong": "Step one: check the entity. This is a Chinese-language article about a man aged seventy-one who won a national science medal. We match Chinese names a second time through an English spelling, "
             "which raised our match rate from forty to seventy-seven per cent. But that English spelling is the AI's guess.\n\n"
             "Here the guess was Lee Choon Seng, and our search found exactly that string: a banker, born in 1888. A perfect match score. The name matched. The man did not. The system flagged it, and the reviewer "
             "found the right record, an engineer, by searching.\n\n"
             "What we changed: we search the original-language name first, treat a guessed spelling as weaker evidence, and mark it on the card. What is still open: of sixty-six Chinese-named people in our feed, "
             "our file holds the Chinese name for only seventeen, so for most of them a guess is the only bridge. And this is not only a Chinese problem. Any name that passes through an AI's transliteration has it.",
    "test": v2.NOTES["test"],
    "reveal": "Now back to the description you were asked to approve. On the right is the screen as it looks today. On the left, what the record said, and what the AI replaced it with.\n\n"
              "The record listed his posts: Chairman of A*STAR, Permanent Secretary at the Ministry of Education, Chief of Defence Force, Chief of Army, each with dates. The AI replaced all of it with a sentence saying he dedicated "
              "over four decades to public service. Only nine per cent of the original survives. It replaced a career with a compliment, and nothing on the first screen would have told you. The error is the pipeline's, not his.\n\n"
              "Step two: a change should only add information. If it removes any, the screen must say so. We now measure how much of the old text survives and warn when less than seventy per cent does. "
              "We also flag any change that pushes a description past the five sentences our style guide allows. In our stored rewrites, about a quarter went past that limit.",
    "evidence": "Step three: show the evidence. This record has a day of death: the fifteenth. The AI proposes the sixteenth. The sentence on screen says only that he died aged ninety-four. There is no date in it.\n\n"
                "What the screen does not show: CNA and The Straits Times, as we recorded them, say the fifteenth. Zaobao, which supplied the change, said the sixteenth. Why did the screen not show them? "
                "Because two articles that agree with the record produce no change, so they never reach the screen. The screen only shows a change's supporters, never what disagrees.\n\n"
                "We now quote each change's own sentence. What we have not built is showing the other articles that say something different. A death date goes into a file that other agencies and VIAF draw on, "
                "so that is the next step.",
    "gaps": "Step four: look for gaps. Back to the article from the start: Gerard Ee steps down, Anita Fam takes over. This is her card. It asks: add the Agency for Integrated Care to her affiliations? That is fine.\n\n"
            "Now look at the quote. It is about her awards. Nothing on the screen says she is the new chairperson, and her description got no edit, though his did. The AI had caught the fact. "
            "The last step left it out, probably because her post starts the next day and nothing told it what to do with an announced appointment. A reviewer can check what was proposed. They cannot see what was left out.\n\n"
            "What we changed: a rule that an appointment is recorded when it is announced. We have tested the code, but we have not yet re-run the model on this article. In a test, a second model, asked whether the article "
            "adds a fact the description lacks, flagged this card. What is still open is showing a reviewer what the article says that no change covers.",
    "steps": "Those are the four steps. Check the entity. Only add. Show the evidence. Look for gaps. For each one: what went wrong, and what we added.\n\n"
             "If you are looking at any AI-assisted change to a catalogue record, ask whether your workflow has these four steps.",
    "gate": "Where a step needs a yes or no, we tried a small decision model, jev, from TypeSafe. It answers yes or no questions and picks from lists. It writes nothing.\n\n"
            "Asked to pick the right record from the candidates, it chose the same one as Gemini for ninety-nine in a hundred matches. To be clear, that is agreement with another AI, not correctness. "
            "Asked to check each change against the article's quote, it caught a library said to have closed in August 2025, in an article dated August 2026. "
            "Asked whether a new sentence was lasting enough to describe the entity as a whole, it ranked one reviewer's doubtful cards below the accepted ones eighty-seven times in a hundred pairs.\n\n"
            "What it cannot do: write, or say what belongs in a description. It can flag doubtful additions, but nobody has written that rule.",
    "policy": "That brings us to what nobody had written down. Our style guide says how to write a description: three to five sentences, summarise the entity. It does not say which facts belong. "
              "In an audit of one hundred and sixty cards, one reviewer doubted twenty-two of eighty-two description additions, not one because it was wrong. The question was: what if there is another article next year? "
              "Do we keep adding? Our editing rule says keep every fact, so descriptions only grow: about a quarter of stored rewrites went past five sentences.\n\n"
              "The second decision: when does a new entity deserve a record? Thirty-one in a hundred entities have no record yet, and nobody has tested whether they deserve one.\n\n"
              "So can the person be removed? For fifty-two in a hundred entities, both models agree on the record and the quote backs every change. That is not the same as correct, and we have almost no human answers "
              "to check against. For now the person stays, not because models cannot match records, but because these two decisions have no written rule.",
    "unknown": "What do we know? Less than I would like. Can a person decide each proposal? Yes. Is each proposal correct? We have not measured that. Does it save time? Not yet. "
               "Next come labelled sheets from one month of the feed, with labellers who cannot see the AI's answer, and then a field test where cataloguers swap between the tool and reading the news.\n\n"
               "What would it take for you? One person built this, relying on a team for feedback, on free tiers. Paid access is estimated at under fifteen Singapore dollars a month, about a hundred and ninety-five rand. "
               "The hard part was the steps between the model and the person. And if you build an agent for this, test it on these four cases first.\n\n"
               "Before you start, check your copyright position. Ours is Singapore's computational data analysis provision, and the article is read, not stored. Nothing reaches our file without a named person's decision.",
    "thanks": "Thank you. Most of what went wrong was a missing step between the AI and the person. I would be glad to take your questions. The next slides are backup, if they help: the numbers, the evaluation plan, "
              "cost and law, the schema lesson, whether a small model could do the first filter, more cards, and an earlier deletion.",
}

HEADERS = {"thesis": "The idea", "problem": "The problem", "record": "What is an authority record?", "how": "How it works", "first": "The first version",
           "wrong": "Step 1: check the entity", "reveal": "Step 2: only add", "evidence": "Step 3: show the evidence", "gaps": "Step 4: look for gaps",
           "steps": "The four steps", "gate": "A second model as a decision gate", "policy": "What nobody had written down"}
# the user's own header text stays for: split, pp, test, unknown
BUILD = {"thesis": s_thesis, "problem": s_problem, "record": s_record, "how": v2.s_how, "split": v2.s_split, "first": s_first, "pp": v2.s_pp, "wrong": s_wrong, "test": v2.s_test,
         "reveal": s_reveal, "evidence": s_evidence, "gaps": s_gaps, "steps": s_steps, "gate": s_gate, "policy": s_policy, "unknown": s_unknown}
# the user's slides 2 to 13 carry these builders; the other four are cloned
FROM_USER = {"idea": "thesis", "problem": "problem", "how": "how", "split": "split", "test": "test", "reveal": "reveal", "pp": "pp", "wrong": "wrong",
             "sources": "evidence", "leftout": "gaps", "four": "steps", "unknown": "unknown"}
CLONED = ["record", "first", "gate", "policy"]
ORDER = ["title", "thesis", "problem", "record", "how", "split", "first", "pp", "wrong", "test", "reveal", "evidence", "gaps", "steps", "gate", "policy", "unknown", "thanks"]
MINUTES = {"title": 0.25, "thesis": 0.75, "problem": 0.75, "record": 0.5, "how": 0.75, "split": 0.75, "first": 0.5, "pp": 1.0, "wrong": 1.0, "test": 1.0, "reveal": 1.0,
           "evidence": 1.0, "gaps": 1.0, "steps": 0.75, "gate": 1.0, "policy": 1.0, "unknown": 0.75, "thanks": 0.5}


def main():
    prs = Presentation(SRC)
    slides = list(prs.slides)
    user_order = list(FROM_USER)
    by_user = dict(zip(user_order, slides[1:13]))
    thanks = next(sl for sl in slides if any(sh.has_text_frame and sh.text_frame.text.strip() == "Thank you" for sh in sl.shapes))
    backups = [sl for sl in slides[13:] if sl is not thanks]
    key_slide = {"title": slides[0], "thanks": thanks}
    for ukey, k in FROM_USER.items():
        sl = by_user[ukey]
        keep_chrome(sl)
        bt.TAG[0] = k
        if k in HEADERS:
            header(sl, HEADERS[k])
        BUILD[k](sl)
        key_slide[k] = sl
    for k in CLONED:
        sl = clone(prs, by_user["problem"])
        keep_chrome(sl)
        bt.TAG[0] = k
        header(sl, HEADERS[k])
        BUILD[k](sl)
        key_slide[k] = sl
    # the thank-you slide: the tagline that was only about the metaphor goes
    for sh in thanks.shapes:
        if sh.has_text_frame and "Papers, Please" in sh.text_frame.text:
            set_text(sh, "Check the steps between the AI and the person.")
    # the backup chart of first-filter models, with jev's row added
    small = next(sl for sl in backups if any(sh.has_text_frame and sh.text_frame.text.startswith("Backup: could a small model") for sh in sl.shapes))
    keep_chrome(small)
    bt.pill(small, 11.25, 0.27, 1.5, 0.4, "BACKUP", bt.RED, size=13)
    bt.TAG[0] = "small-model"
    v2.b_small_model_v2(small)
    if "jev" not in small.notes_slide.notes_text_frame.text:
        small.notes_slide.notes_text_frame.text = (small.notes_slide.notes_text_frame.text.rstrip() +
            " We also tried jev, a decision model from TypeSafe that answers yes or no questions and writes no text, with no training at all: F1 0.66 on a random 6,000 test articles, "
            "and to keep 95 in 100 relevant articles it passes on 30 in 100, where the fine-tuned model passes 25. On the 69 hard cases a person judged it scores 0.23, about the same.")
    # order: the new story, then the backups in the user's own order
    ids = prs.slides._sldIdLst
    by_id = {int(e.get("id")): e for e in list(ids)}
    want = [key_slide[k].slide_id for k in ORDER] + [sl.slide_id for sl in backups]     # read before the list is emptied: the lookup goes through it
    for e in list(ids):
        ids.remove(e)
    for sid in want:
        ids.append(by_id[sid])
    # footer numbers, then notes
    all_slides = list(prs.slides)
    for i, sl in enumerate(all_slides, 1):
        shape = sl.shapes[5] if len(sl.shapes) > 5 else None
        if shape is not None and shape.has_text_frame and re.fullmatch(r"\d\d", shape.text_frame.text.strip()):
            set_text(shape, f"{i:02d}")
    for k in ORDER:
        key_slide[k].notes_slide.notes_text_frame.text = NOTES[k]
    prs.save(OUT)
    return all_slides


def script_docx(prs_path):
    import docx
    from docx.shared import Pt as DPt
    prs = Presentation(prs_path)
    d = docx.Document()
    d.styles["Normal"].font.name = "Arial"
    d.styles["Normal"].font.size = DPt(11)
    d.add_heading("Designing for the Reviewer: speaking script (v3)", 0)
    d.add_paragraph("IFLA AI symposium, 20-minute slot: about 15 minutes of talking, then 5 for questions. The times are a running clock. Slides after the thank-you slide are backup, for questions only.")
    clock = 0.0
    for i, sl in enumerate(prs.slides, 1):
        titles = [sh.text_frame.text for sh in sl.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
        title = (titles[0] if titles else "")[:70].replace("\n", " ")
        text = sl.notes_slide.notes_text_frame.text if sl.has_notes_slide else ""
        if i <= len(ORDER):
            stamp = f"[{int(clock)}:{int(round((clock % 1) * 60)):02d}]"
            clock += MINUTES[ORDER[i - 1]]
        else:
            stamp = "[backup]"
        d.add_heading(f"Slide {i}: {title}  {stamp}", level=2)
        for chunk in text.split("\n\n"):
            if chunk.strip():
                d.add_paragraph(chunk)
    d.save(SCRIPT)
    return clock


if __name__ == "__main__":
    slides = main()
    bt.preview(OUT, PREVIEW)
    for problem in bt.PROBLEMS:
        print("OVERFLOW", problem)
    end = script_docx(OUT)
    print(f"{OUT.name}: {len(slides)} slides; the clock ends at {int(end)}:{int(round((end % 1) * 60)):02d}")
    sys.exit(1 if bt.PROBLEMS else 0)
