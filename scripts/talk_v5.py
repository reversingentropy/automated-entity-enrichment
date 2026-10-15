"""
Deck v5: the talking-points deck with a reviewer's comments of 15 October applied.

    uv run python scripts/talk_v5.py

Reads data/dist/designing-for-the-reviewer-v2-talking-points.pptx and never writes it. Writes
designing-for-the-reviewer-v5.pptx and talking-points-v5.docx (every slide's notes, with a running clock).

What changes:
  - slide 7: "a missing step between the AI and the person"; "each of these four checks was a missing step"
  - the four checks are numbered in the order the talk tells their stories (the career-to-compliment card comes
    first), on slides 7, 15 and 18, and slides 11 to 14 each carry a "CHECK n OF 4" label and open their notes with it
  - slide 9's notes explain Papers, Please and Tinder for people who know neither
  - TTE gets a footnote wherever a slide names it; the news outlets are explained where a slide names them
  - USD beside SGD and ZAR
  - "the archive" becomes "the news archive" or "the internal AI platform", so it is not read as the National Archives
  - to keep the talk inside 15 minutes, notes that repeat what the slide shows are shortened (slides 6, 7, 11 to 14, 16, 17)
"""

import copy
import sys
from pathlib import Path

import docx
from docx.shared import Pt
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu, Pt as PPt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import talking_points as tp  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "dist" / "designing-for-the-reviewer-v2-talking-points.pptx"
OUT_DECK = ROOT / "data" / "dist" / "designing-for-the-reviewer-v5.pptx"
OUT_DOC = ROOT / "data" / "dist" / "talking-points-v5.docx"

NAVY, ACCENT = RGBColor.from_string("0E2841"), RGBColor.from_string("156082")
BODY_L, BODY_W = 822960, 10543032
TTE_NOTE = "* TTE: Thesaurus and Taxonomy Editor, the system that holds our name authority records."

CHECKS = {11: "CHECK 1 OF 4   ·   WHAT DOES IT CHANGE, AND WHAT DOES IT LOSE?",
          12: "CHECK 2 OF 4   ·   IS IT THE RIGHT RECORD?",
          13: "CHECK 3 OF 4   ·   WHAT BACKS IT, AND DOES ANYTHING DISAGREE?",
          14: "CHECK 4 OF 4   ·   WHAT DID IT MISS?"}

# (slide, shape id, paragraph, old text, new text): the old text is asserted, so a hand edit in the source stops the build
TEXT = [
    (7, 15, 0, "Most of what went wrong in our system was a missing step between the two.",
     "Most of what went wrong was a missing step between the AI and the person."),
    (7, 16, 0, "FOUR CHECKS TO TAKE HOME", "EACH OF THESE FOUR CHECKS WAS A MISSING STEP"),
    (18, 3, 0, "The four questions, again", "The four checks, again"),
    (6, 38, 0, "Decides, then edits TTE by hand", "Decides, then edits TTE* by hand"),
    (8, 15, 0, "THE STRAITS TIMES  ·  31 AUG", "THE STRAITS TIMES*  ·  31 AUG"),
    (10, 16, 0, "IN THE NEWS   ·   Lianhe Zaobao, 13 August 2026 (translated)",
     "IN THE NEWS   ·   Lianhe Zaobao, Singapore’s main Chinese-language newspaper, 13 August 2026 (translated)"),
    (13, 20, 1, "CNA and The Straits Times, as we recorded them: the 15th. Zaobao, the one source on screen: the 16th.",
     "CNA and The Straits Times (English), as we recorded them: the 15th. Zaobao (Chinese), the one source on screen: the 16th."),
    (17, 16, 2, "Paid access: under SGD $15 / ZAR 195 a month (estimated)",
     "Paid access: under SGD $15 / USD $12 / ZAR 195 a month (estimated)"),
    (17, 18, 1, "We’re planning to open sourcing the code on GitHub!", "We’re planning to open source the code on GitHub!"),
    (22, 39, 0, "Not in TTE yet", "Not in TTE* yet"),
    (24, 15, 3, "Paid access: under SGD 15 a month at today’s volume (an estimate, excluding staff time)",
     "Paid access: under SGD 15 / USD 12 / ZAR 195 a month at today’s volume (an estimate, excluding staff time)"),
    (25, 16, 1, "archive articles came back in the requested structure, on a platform that cannot enforce one. The rest came back as prose.",
     "news-archive articles came back in the requested structure, on the internal AI platform we used for the archive, which "
     "cannot enforce one. The rest came back as prose."),
    (25, 17, 1, "in TTE’s guidelines, with exact names. The live pipeline’s model API enforces them, and has not failed this way.",
     "in TTE’s* guidelines, with exact names. The live pipeline’s model API enforces them, and has not failed this way."),
    (28, 15, 0, "A description in TTE, before: 636 characters", "A description in TTE*, before: 636 characters"),
]

# footnotes: slide -> (top, text)
FOOTNOTES = {6: (6156960, TTE_NOTE), 22: (6156960, TTE_NOTE), 25: (6156960, TTE_NOTE), 28: (6245352, TTE_NOTE),
             8: (6245352, "* The Straits Times: Singapore’s main English-language newspaper.")}

# swap the numbered checks 1 and 2 so the numbers follow the order of the stories
SWAP_BODIES = {15: [(18, 22), (19, 23), (20, 24)]}          # the whole text box: check, what went wrong, what the screen does
SWAP_PARAS = {7: [(18, 20, 1)], 18: [(15, 17, 1)]}          # only the question, the number stays where it is

# notes: (slide, old, new) replacements, each asserted to match once; whole new notes where most of it changes
NOTE_EDITS = [
    (6, "Ingest collects titles and summaries from three news feeds every two hours. Relevance reads only the title and "
        "summary: does this change a record? Extraction pulls out the people, places and facts, with one quoted sentence. "
        "Retrieval finds candidate records by character similarity, and uses no AI. Resolution asks: is this the same "
        "entity, and what does the record lack?",
     "Ingest collects titles and summaries every two hours from three Singapore news outlets: The Straits Times and CNA "
     "in English, and Lianhe Zaobao in Chinese. Then the AI judges whether an article changes a record, pulls out the "
     "people and facts, and decides which record each one is. Finding the candidate records uses no AI."),
    (6, "The sixth stage is a person. Run over our archive back to 2015 and the live feed, it has read almost three hundred "
        "thousand articles, judged about twenty-eight thousand relevant, and proposed 9,844 changes to existing records. "
        "None of those has been through a formal evaluation yet.",
     "The sixth stage is a person, who decides, then makes the change by hand in TTE, the Thesaurus and Taxonomy Editor, "
     "which holds our authority records. Over the news archives since 2015 and the live feed, the pipeline has proposed "
     "9,844 changes to existing records, none yet formally evaluated."),
    (11, "Now back to the description you were asked to approve.",
     "Now back to the description you were asked to approve. This is the first check: what does it change, and what "
     "does it lose?"),
    (11, "There was no error message. The error is the pipeline's, not his.", "There was no error message."),
    (12, "A chain of four steps.", "The second check: is it the right record?"),
    (13, "A reviewer is shown the source that backs a change.",
     "The third check: what backs this change, and does anything disagree? A reviewer is shown the source that backs a change."),
    (13, "Why the screen never showed the other two: articles that agree with the record produce no proposal, so they never "
         "reach the screen. That is still open. The next step is to show every article that states the current value "
         "beside the change.",
     "The other two never reached the screen, because articles that agree with the record produce no proposal. Showing "
     "them beside the change is our next step."),
    (14, "Back to the article from the start:", "The fourth check: what did it miss? Back to the article from the start:"),
    (14, "We changed the prompts so an appointment is recorded when it is announced. That is written and code-tested, but "
         "not yet re-run on the model. The desk also now offers facts the article states that no change covers, to accept "
         "only if you agree.",
     "We changed the prompts so an appointment is recorded when it is announced, though the model has not been re-run "
     "yet. The desk also now offers facts the article states that no change covers."),
    (16, "But had the stored proposals simply been accepted unreviewed, they would have matched the reviewer on forty-three "
         "of the forty-eight. Those proposals came mostly from the archive's internal model. So most",
     "Had the stored proposals simply been accepted unreviewed, they would have matched the reviewer on forty-three. So most"),
    (17, "In the pilot, records built from many articles took three quarters of the reviewer's time, so description notes "
         "are now capped. ", ""),
    (17, "about a hundred and ninety-five rand.", "about twelve US dollars, or a hundred and ninety-five rand."),
    (20, "Forty-one of those forty-eight proposals came from the archive's internal model.",
     "Forty-one of those forty-eight proposals came from the internal model we ran over the news archive."),
    (20, "nine in ten came from the archive's internal model", "nine in ten came from the internal model we ran over the news archive"),
    (21, "came from the archive's internal model, not Gemini.", "came from the internal model we ran over the news archive, not Gemini."),
    (22, "The archive is the three outlets' own archives since 2015", "The news archive is the three outlets' own archives since 2015"),
    (24, "excluding staff time and the platform used for the archive.",
     "excluding staff time and the internal AI platform we used for the news archive."),
    (25, "On the archive platform, which cannot hold output to a schema,",
     "On the internal AI platform we used for the news archive, which cannot hold output to a schema,"),
    (26, "against the archive's labels", "against the news archive's labels"),
]

NOTES = {
    7: """Here is what you will leave with: one thread and four checks.

In our system an AI proposes changes to a library record, and a person approves them. That only works if the person can tell when the AI is wrong. Most of what went wrong for us was not a bad AI or a careless person. It was a missing step between the AI and the person.

Each of these four checks was one of those missing steps. You can ask them of any AI-suggested change to a record, from a vendor or from your own pipeline. I will take them in this order, each with the real failure that taught it to us.""",
    9: """So we changed the screen. First, two references. Papers, Please is a video game. You play a border officer: each traveller hands you a passport and papers, you check them against each other and against the day's rules, and you stamp approved or denied. Miss a mismatch and your pay is docked. Tinder is a dating app. It shows you one person at a time, and you swipe right for yes or left for no.

Our earlier desk was inspired by both: the article on one side, the record on the other, one question, a stamp. Two cataloguers used it, found problems, and helped redesign it. Then a first-time user, someone outside the library, looked at it and said: it feels like Tinder.

That is the opposite of what we want. Papers, Please makes you slow down and look. Tinder makes you swipe. The same screen can be either, and the design decides which. So the redesign has one card and one question: the news on top, then what the record says now, then what it will say after you accept. In October, five cataloguers tried both versions side by side, and chose the redesign.""",
    15: """These are the four checks, and what our screen does about each. What does it change and lose? It shows what is removed and how much survives, and holds descriptions to the guide's five sentences. Is it the right record? Facts side by side, and guessed spellings marked. What backs it, and does anything disagree? Each change quotes its own sentence; next, the articles that disagree. And what did it miss? It offers facts the article states that no change covers.

If you ask these of your own pipeline and cannot answer, add the step.""",
    18: """These are the four I promised. What did it remove or add? A Chief of Army, replaced by a compliment. Is it the same entity? We saw a record born in 1888 offered for a man of seventy-one. Is there evidence for this change? A death date changed, with a quote that has no date. And the hard one: what was left out? A new post, and nothing on the screen shows it.

If the screen in front of you cannot answer these, the human in the loop is a formality.""",
}

TITLES = {**tp.TITLES, 18: "The four checks, again"}


def shape(slide, sid):
    found = [s for s in slide.shapes if s.shape_id == sid]
    assert len(found) == 1, f"shape {sid} not found once"
    return found[0]


def set_para(p, text):
    """Put text in the paragraph's first run and drop the others, so the first run's formatting carries."""
    runs = p.runs
    runs[0].text = text
    for r in runs[1:]:
        r._r.getparent().remove(r._r)


def add_text(slide, top, height, text, size, bold=False, italic=False, color=NAVY):
    box = slide.shapes.add_textbox(Emu(BODY_L), Emu(top), Emu(BODY_W), Emu(height))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Emu(18288)
    tf.margin_top = tf.margin_bottom = Emu(0)
    run = tf.paragraphs[0].add_run()
    run.text = text
    f = run.font
    f.name, f.size, f.bold, f.italic = "Arial", PPt(size), bold, italic
    f.color.rgb = color
    return box


def notes_of(prs):
    return {i: (s.notes_slide.notes_text_frame.text if s.has_notes_slide else "") for i, s in enumerate(prs.slides, 1)}


def main() -> int:
    prs = Presentation(str(SRC))
    slides = prs.slides
    assert len(slides) == 29, f"expected the 29-slide deck, found {len(slides)}"
    before = notes_of(prs)

    for n, sid, pi, old, new in TEXT:
        p = shape(slides[n - 1], sid).text_frame.paragraphs[pi]
        assert p.text == old, f"slide {n} shape {sid}: expected {old!r}, found {p.text!r}"
        set_para(p, new)
    widen = shape(slides[6], 16)                                   # the longer label on slide 7 needs the full width
    widen.width = Emu(BODY_W)

    for n, pairs in SWAP_BODIES.items():
        for a, b in pairs:
            ea, eb = shape(slides[n - 1], a)._element, shape(slides[n - 1], b)._element
            ta, tb = ea.txBody, eb.txBody
            ca, cb = copy.deepcopy(ta), copy.deepcopy(tb)
            ea.replace(ta, cb)
            eb.replace(tb, ca)
    for n, triples in SWAP_PARAS.items():
        for a, b, pi in triples:
            pa = shape(slides[n - 1], a).text_frame.paragraphs[pi]
            pb = shape(slides[n - 1], b).text_frame.paragraphs[pi]
            ta, tb = pa.text, pb.text
            set_para(pa, tb)
            set_para(pb, ta)

    for n, label in CHECKS.items():
        add_text(slides[n - 1], 950976, 201168, label, 12, bold=True, color=ACCENT)
    for sid in (15, 16):                                           # slide 11's BEFORE block sat right under the label
        s = shape(slides[10], sid)
        s.top = Emu(s.top + 91440)
    for n, (top, text) in FOOTNOTES.items():
        add_text(slides[n - 1], top, 228600, text, 12, italic=True)

    for n, old, new in NOTE_EDITS:
        tf = slides[n - 1].notes_slide.notes_text_frame
        assert tf.text.count(old) == 1, f"slide {n} notes: {old!r} found {tf.text.count(old)} times"
        tf.text = tf.text.replace(old, new)
    for n, text in NOTES.items():
        slides[n - 1].notes_slide.notes_text_frame.text = text

    prs.save(str(OUT_DECK))
    after = notes_of(Presentation(str(OUT_DECK)))
    changed = sorted({n for n, *_ in NOTE_EDITS} | set(NOTES))
    assert all(after[i] == before[i] for i in after if i not in changed), "a slide's notes changed that should not have"

    d = docx.Document()
    d.styles["Normal"].font.name = "Arial"
    d.styles["Normal"].font.size = Pt(11)
    d.add_heading("Designing for the Reviewer: talking points (v5)", 0)
    d.add_paragraph(f"IFLA AI symposium: about 15 minutes of talking, then 5 for questions. The clock is a running time at "
                    f"{tp.WPM} words a minute. Slides after the thank-you slide are backup, for questions only.")
    clock, talk_words, old_words = 0.0, 0, 0
    for i in range(1, len(after) + 1):
        text = after[i].strip()
        if i <= tp.TALK_SLIDES:
            stamp = f"[{int(clock // 60)}:{int(clock % 60):02d}]"
            clock += tp.words(text) / tp.WPM * 60 + tp.PAUSES.get(i, 0)
            talk_words += tp.words(text)
            old_words += tp.words(before[i])
        else:
            stamp = "[backup]"
        d.add_heading(f"Slide {i}: {TITLES[i]}  {stamp}", level=2)
        for chunk in text.split("\n\n"):
            if chunk.strip():
                d.add_paragraph(chunk.strip())
    d.add_paragraph(f"Talk: {talk_words} words, about {int(clock // 60)} min {int(clock % 60):02d} s at {tp.WPM} words a minute.")
    d.save(str(OUT_DOC))
    print(f"Wrote {OUT_DECK.relative_to(ROOT)} and {OUT_DOC.relative_to(ROOT)}")
    print(f"Notes changed on slides {', '.join(map(str, changed))}")
    print(f"Talk (slides 1-{tp.TALK_SLIDES}): {old_words} words before, {talk_words} now; "
          f"about {int(clock // 60)} min {int(clock % 60):02d} s at {tp.WPM} words a minute")
    return 0


if __name__ == "__main__":
    sys.exit(main())
