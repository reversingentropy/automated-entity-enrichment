"""
The conference deck, built on the symposium's own template.

    python -m src.export --slides data/dist/slides.pptx

The template is a .potx whose five slides are plain rectangles rather than
placeholders, so new slides are made by copying one of those five wholesale
and replacing the text in the shapes by name. That keeps the branding, the
footer and the type exactly as the organisers set them.

Twenty minutes, so fourteen slides at about eighty-five seconds each. The
content lives in SLIDES below, each with the speaker notes for it. The
counts are from docs/numbers.md (python -m src.export --numbers), dated;
the findings from docs/design.md; the delta finding from docs/evaluation.md.
"""

import copy
import zipfile
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

TEMPLATE = Path("data/template_for_presentation/6th IFLA AI PowerPoint Template 2.potx")
SHOTS = Path("data/slides")           # screenshots to drop in, if present

TITLE = "Designing for the Reviewer"
SUBTITLE = "A human-in-the-loop AI pipeline for news-driven authority file maintenance"
PRESENTER = "Ashwin Nair"
INSTITUTION = "National Library Board, Singapore"
EMAIL = "nair.ashwin1994@gmail.com"

INK = RGBColor(0x0E, 0x28, 0x41)      # the template's dark blue
ACCENT = RGBColor(0x15, 0x60, 0x82)   # the template's accent
MUTED = RGBColor(0x5A, 0x63, 0x70)

# Each content slide: heading, then lines. A line is (text, level, style):
# level 0 is a statement, level 1 a supporting point; style "big" is a figure,
# "quote" an italic aside, None ordinary text.
SLIDES = [
    dict(kind="title"),
    dict(heading="A record is written once. Its subject keeps acting.",
         lines=[("TTE, NLB's Thesaurus and Taxonomy Editor, holds about 1.8 million records; "
                 "52,437 of them name people, organisations, places, events, awards, programmes "
                 "and legal acts.", 0, None),
                ("It is the data dictionary behind NLB's discovery systems, the National "
                 "Archives, other agencies, and VIAF.", 1, None),
                ("People take up posts, receive honours, die. Organisations merge and are "
                 "renamed.", 0, None),
                ("Keeping up is routine: specialists monitor the major Singapore outlets, in "
                 "English and Chinese, and update by hand.", 0, None),
                ("The practice is sound; the volume has outgrown it. One outlet publishes "
                 "hundreds of articles a day.", 1, None)],
         notes="Open on the problem, not the technology. The audience are librarians: they know "
               "what an authority file is, so spend ten seconds on it and move. The point to land "
               "is that the work is routine and done well; what has changed is how much news it "
               "has to keep up with."),
    dict(heading="The question, and the answer that surprised us",
         lines=[("Can a language model do the reading?", 0, None),
                ("Yes, cheaply. That turned out to be the easy part.", 1, None),
                ("The quality of a human-in-the-loop system is set less by the model than by "
                 "what the model is asked to hand a person at the end.", 0, "quote"),
                ("And building the review interface carefully is what tells you whether the "
                 "pipeline works: several failures only became visible once a reviewer could "
                 "see the output clearly enough to notice them.", 0, None)],
         notes="This is the thesis of the paper. Say it slowly. Everything after this slide is "
               "evidence for these two sentences."),
    dict(kind="section", heading="The pipeline",
         sub="Four stages, twice a day, on free tiers: a queue is a column in a table"),
    dict(kind="diagram", heading="Everything so far",
         notes="Walk top to bottom once. Two sources: the three outlets' own archives since 2015, "
               "read once through an internal model, and the live feeds twice a day since August. "
               "Of 298,790 articles, 28,090 were worth reading; they held 48,696 entities, which "
               "became 9,844 proposed changes to existing records and 22,331 proposed new records. "
               "The live ones are 170 cards on the desk; the archive's come out as a list. The "
               "design property is the last line: each stage's queue is a column, so a failed run "
               "leaves rows queued and the next run picks them up. No orchestration."),
    dict(heading="What the machine hands over",
         lines=[("Retrieval is trigram similarity over every name and variant in the file, "
                 "not embeddings: 52,437 records, and a name is a short string.", 0, None),
                ("The model adjudicates a shortlist of five, and every proposal keeps the "
                 "sentence it came from.", 0, None),
                ("Nothing is written to TTE. The output is a proposal for a person to judge.", 0, None),
                ("Cost: nothing. Gemini free tier, Supabase free tier, GitHub Actions.", 0, "big")],
         notes="Pre-empt the question about embeddings. Names are short strings and the file "
               "is small, so trigram indexing in Postgres is fast and free. A spot-check of name "
               "embeddings scored two different people higher than the same person written in two "
               "scripts, so it was not pursued; vectors for 52,437 records would also have cost "
               "about 160 MB of a 500 MB database."),
    dict(kind="section", heading="Designing for the reviewer",
         sub="The part that decided whether any of it worked"),
    dict(kind="shot", heading="Two documents, one question at a time",
         shot="desk-identity.png",
         lines=[("Left: what the article said, with the sentence and a link. "
                 "Right: the TTE record as it stands, never drawn on.", 0, None),
                ("Both list the same attributes in the same order. A tick where they agree, "
                 "a dash where the record has nothing.", 0, None),
                ("Is this the same organisation? Then, one attribute at a time: should this "
                 "go on the record?", 0, None)],
         notes="Let them read the screen for a beat before you talk. The design rule: a reviewer "
               "answers one question per screen, and the record is never altered on screen, "
               "because the first reviewer could not tell the proposal from the record when it was."),
    dict(heading="Four failures the interface exposed",
         lines=[("A proposal drawn onto the record card: the reviewer could not tell what was "
                 "proposed from what was held.", 0, None),
                ("Eighteen of fifty-three cards asked to confirm an identity with nothing to "
                 "change. Attention spent on nothing.", 0, None),
                ("An award proposed for a person, with no record of its own: unapplicable, and "
                 "invisible until a badge said so.", 0, None),
                ("李全盛 read as \"Lee, Choon Seng\": a real record, a different man, "
                 "dead since 1966. The model matched its own guess at the spelling.", 0, None)],
         notes="These are the failures that only a working interface reveals. None of them would "
               "fail a unit test; none is a model accuracy problem. The last one is the case worth "
               "dwelling on: it is not a hallucination, it is a correct match to a wrong query."),
    dict(heading="李全盛, and what it cost to fix",
         lines=[("Of 66 Chinese-named people in the nightly feed, TTE held the Chinese name "
                 "for 17. The other 49 are reachable only through a romanisation.", 0, None),
                ("Fix, in three parts: retrieve on the original script first; cap any candidate "
                 "reached only through a guessed spelling at 0.9; show the reviewer that the "
                 "record was found through a guess.", 0, None),
                ("Deeper retrieval sized by measurement, not intuition: over 73 confirmed "
                 "matches the right record was never deeper than sixth, so eight suffice.", 0, None),
                ("about 350 extra tokens a night", 0, "big"),
                ("And the by-product: a confirmed Chinese name is a variant the file lacks. "
                 "The reviewer's decision writes it back.", 0, None)],
         notes="The general lesson: the failure was in the query, not the match, and no amount of "
               "model quality would have fixed it. Measuring recall@k over confirmed matches is "
               "how the candidate budget was set; it cost 350 tokens a night, not a rebuild."),
    dict(kind="section", heading="What the librarians did",
         sub="Two rounds of review, and what each round asked for"),
    dict(heading="Two reviewers, 52 records, and a redesign",
         lines=[("Round one, 14 cards: 14 of 14 identities confirmed; 13 of 16 proposed field "
                 "changes accepted; one card kept for discussion.", 0, None),
                ("It asked for plain words. \"Pencil it in\", \"pending tray\", \"look further "
                 "back\" cost the reviewer time, and went.", 1, None),
                ("Round two, 38 records, asked nothing about the cards and everything about "
                 "working: a tally as you go, accepting part of a proposal, splitting the deck, "
                 "showing which variant name a record was found through.", 0, None),
                ("That the questions changed kind is the signal the cards had settled.", 0, "quote")],
         notes="The shift between the two rounds is the finding here. Round one was about whether "
               "the output could be read; round two was about running it with five people. You do "
               "not get operational questions about something nobody believes in."),
    dict(kind="chart", heading="The honest surprise",
         notes="This is the number I would most like the audience to take away, and it is the one "
               "that cost the least to get: it came from dumps the team already had. It says the "
               "app is a supplement to authority work, not a replacement for it, and it means any "
               "recall target must be set against news-driven changes only."),
    dict(heading="What transfers",
         lines=[("Measure the interface, not only the model. The failures that mattered were "
                 "failures of presentation.", 0, None),
                ("Ask the reviewer one question per screen, and never redraw the record.", 0, None),
                ("Retrieve in the script the source used. A romanisation is a guess, and a "
                 "confident match to a guess is worse than no match.", 0, None),
                ("Measure what share of the work the system can even see before setting a "
                 "target for it.", 0, None),
                ("A queue that is a column in a table needs no orchestration, and runs for "
                 "nothing.", 0, None)],
         notes="Keep this slide tight: five transferable things, one line each. This is what a "
               "librarian in another national library can act on next week."),
    dict(kind="thanks"),
]

FUNNEL = [("Articles read", "298,790 · three outlets, 2015 to today"),
          ("1 · Relevance", "28,090 worth reading"),
          ("2 · Extraction", "48,696 entities, with evidence"),
          ("3 · Resolution", "9,844 changes · 22,331 new"),
          ("4 · The desk", "a person decides each one")]
FUNNEL_AS_OF = "28 September 2026"   # the date of docs/numbers.md these came from

CEILING = [("2024-09–2025-04", 14.6), ("2025-05–07", 21.7), ("2025-08–09", 3.5),
           ("2025-10–2026-03", 10.4), ("2026-04–05", 7.4), ("2026-06–08", 11.4)]


def as_pptx(potx: Path, out: Path) -> Path:
    """A .potx is a .pptx with one content type changed; python-pptx wants the latter."""
    with zipfile.ZipFile(potx) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = data.replace(b"presentationml.template.main+xml",
                                    b"presentationml.presentation.main+xml")
            zout.writestr(item, data)
    return out


R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def clone(prs, source):
    """
    A new slide carrying every shape of `source`, chrome and all.

    A copied picture still names its image by the source slide's relationship
    id, which the new slide does not have, and PowerPoint shows "the picture
    can't be displayed"; each such reference is re-linked to the same image.
    """
    slide = prs.slides.add_slide(source.slide_layout)
    for shape in list(slide.shapes):
        shape._element.getparent().remove(shape._element)
    for shape in source.shapes:
        element = copy.deepcopy(shape._element)
        for node in element.iter():
            for attr in (R_NS + "embed", R_NS + "link", R_NS + "id"):
                rid = node.get(attr)
                if rid and rid in source.part.rels:
                    rel = source.part.rels[rid]
                    node.set(attr, slide.part.relate_to(rel.target_ref, rel.reltype, is_external=True)
                             if rel.is_external else slide.part.relate_to(rel.target_part, rel.reltype))
        slide.shapes._spTree.append(element)
    return slide


def named(slide, name):
    return next((s for s in slide.shapes if s.name == name), None)


def set_text(shape, text, size=None, bold=None, color=None):
    """Replace a shape's text, keeping the run's formatting where it has some."""
    if shape is None:
        return
    frame = shape.text_frame
    para = frame.paragraphs[0]
    run = para.runs[0] if para.runs else para.add_run()
    run.text = text
    for extra in para.runs[1:]:
        extra._r.getparent().remove(extra._r)
    for extra in list(frame.paragraphs[1:]):
        extra._p.getparent().remove(extra._p)
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color


def body(slide, lines, top=1.35, left=0.72, width=11.9, height=5.5):
    """
    The lines of a content slide, indented by level, with the figures set large.

    PowerPoint will not shrink text that overruns a box, and a slide that
    overruns is worse than one set a little smaller, so the type steps down
    once when the estimated line count will not fit the height given.
    """
    per_line = max(int(width * 92 / 10), 20)      # characters that fit a line at 20pt
    visual = sum(max(1, len(text) // per_line + 1) for text, _, _ in lines)
    scale = 1.0 if visual * 0.42 + len(lines) * 0.22 <= height else 0.82
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    frame = box.text_frame
    frame.word_wrap = True
    first = True
    for text, level, style in lines:
        para = frame.paragraphs[0] if first else frame.add_paragraph()
        first = False
        run = para.add_run()
        run.text = ("—  " if style == "quote" else "") + text
        font = run.font
        font.name = "Calibri"
        if style == "big":
            font.size, font.bold, font.color.rgb = Pt(round(30 * scale)), True, ACCENT
        elif style == "quote":
            font.size, font.italic, font.color.rgb = Pt(round(20 * scale)), True, ACCENT
        elif level:
            font.size, font.color.rgb = Pt(round(17 * scale)), MUTED
        else:
            font.size, font.color.rgb = Pt(round(20 * scale)), INK
        para.level = min(level, 4)
        para.space_after = Pt(round((16 if not level else 12) * scale))
        para.line_spacing = 1.15
    return box


def diagram(slide):
    """The funnel as five boxes, each narrower than the last."""
    from pptx.enum.shapes import MSO_SHAPE
    top, left, height = 1.75, 0.72, 0.82
    widest, narrowest = 11.0, 5.4
    for i, (stage, note) in enumerate(FUNNEL):
        width = widest - (widest - narrowest) * i / (len(FUNNEL) - 1)
        box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left),
                                     Inches(top + i * (height + 0.22)), Inches(width), Inches(height))
        box.fill.solid()
        box.fill.fore_color.rgb = ACCENT if i else RGBColor(0x0E, 0x28, 0x41)
        box.line.fill.background()
        box.shadow.inherit = False
        frame = box.text_frame
        frame.word_wrap = True
        para = frame.paragraphs[0]
        para.alignment = PP_ALIGN.LEFT
        run = para.add_run()
        run.text = f"  {stage}"
        run.font.size, run.font.bold, run.font.color.rgb = Pt(18), True, RGBColor(0xFF, 0xFF, 0xFF)
        tail = para.add_run()
        tail.text = f"     {note}"
        tail.font.size, tail.font.color.rgb = Pt(15), RGBColor(0xE8, 0xE8, 0xE8)
    note = slide.shapes.add_textbox(Inches(left), Inches(6.45), Inches(11.9), Inches(0.7))
    frame = note.text_frame
    frame.word_wrap = True
    run = frame.paragraphs[0].add_run()
    run.text = (f"As of {FUNNEL_AS_OF}: the outlets' archives since 2015, read once, and the live "
                "feeds since August. Each stage's queue is a column in a table, so a failed run "
                "leaves its rows queued for the next. No orchestration.")
    run.font.size, run.font.color.rgb, run.font.italic = Pt(16), MUTED, True


def chart(slide):
    """The share of the team's record changes our three sources could have reached."""
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
    data = CategoryChartData()
    data.categories = [p for p, _ in CEILING]
    data.add_series("share of the team's changes our sources printed", [v / 100 for _, v in CEILING])
    frame = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.72), Inches(1.5),
                                   Inches(7.6), Inches(4.4), data)
    ch = frame.chart
    ch.has_legend = False
    ch.font.size = Pt(12)
    plot = ch.plots[0]
    plot.has_data_labels = True
    plot.data_labels.number_format = "0.0%"
    plot.data_labels.number_format_is_linked = False
    plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    plot.data_labels.font.size = Pt(12)
    series = plot.series[0]
    series.format.fill.solid()
    series.format.fill.fore_color.rgb = ACCENT
    ch.value_axis.maximum_scale = 0.25
    ch.value_axis.tick_labels.number_format = "0%"
    ch.value_axis.tick_labels.number_format_is_linked = False
    lines = [("Seven TTE dumps, six periods, 3,357 records changed.", 0, None),
             ("12%", 0, "big"),
             ("of the team's record changes involve a name our three sources printed. "
              "Correcting for names that appear in an article's body but not its headline "
              "(measured at 1.6x) puts it near 19%.", 0, None),
             ("The rest is cataloguing: records touched because a book was catalogued, "
              "historical figures corrected, bulk projects.", 0, None),
             ("So this is a supplement to authority work, not a replacement, and a recall "
              "target has to be set against news-driven changes alone.", 0, "quote")]
    body(slide, lines, top=1.5, left=8.6, width=4.1, height=5.0)


def build(out: Path = Path("data/dist/slides.pptx"), template: Path = TEMPLATE) -> Path:
    if not template.exists():
        raise SystemExit(f"Need the symposium template at {template}")
    out.parent.mkdir(parents=True, exist_ok=True)
    work = out.with_suffix(".template.pptx")
    prs = Presentation(as_pptx(template, work))
    title_slide, content, spare, section, thanks = list(prs.slides)[:5]

    made = []
    for i, spec in enumerate(SLIDES):
        kind = spec.get("kind", "content")
        if kind == "title":
            set_text(named(title_slide, "Rectangle 4"), TITLE)
            frame = named(title_slide, "Rectangle 5").text_frame
            set_text(named(title_slide, "Rectangle 5"), f"{PRESENTER}\n{INSTITUTION}")
            run = frame.paragraphs[0].runs[0]
            run.text = PRESENTER
            second = frame.paragraphs[0].add_run()
            second.text = f"\n{INSTITUTION}"
            second.font.size = Pt(16)
            made.append(title_slide)
            continue
        if kind == "thanks":
            set_text(named(thanks, "Rectangle 4"), "Questions and discussion")
            set_text(named(thanks, "Rectangle 5"), f"{PRESENTER}\n{EMAIL}")
            frame = named(thanks, "Rectangle 5").text_frame
            frame.paragraphs[0].runs[0].text = PRESENTER
            tail = frame.paragraphs[0].add_run()
            tail.text = f"\n{EMAIL}"
            tail.font.size = Pt(16)
            made.append(thanks)
            continue
        if kind == "section":
            slide = clone(prs, section)
            set_text(named(slide, "Rectangle 4"), spec["heading"])
            set_text(named(slide, "Rectangle 5"), spec.get("sub", ""), size=18)
            made.append(slide)
            continue

        slide = clone(prs, content)
        set_text(named(slide, "Rectangle 2"), spec["heading"])
        if kind == "diagram":
            diagram(slide)
        elif kind == "chart":
            chart(slide)
        elif kind == "shot":
            shot = SHOTS / spec["shot"]
            if shot.exists():
                slide.shapes.add_picture(str(shot), Inches(0.72), Inches(1.35), width=Inches(7.5))
                body(slide, spec["lines"], top=1.5, left=8.5, width=4.2, height=5.2)
            else:
                hint = [("[ screenshot: " + spec["shot"] + " goes here, from data/slides/ ]", 0, "quote")]
                body(slide, hint + spec["lines"])
        else:
            body(slide, spec["lines"])
        made.append(slide)

    # Order the deck as SLIDES lists it, and drop the template's spare slide.
    # Slides are related to the presentation by rId, so that is what the list
    # of slide ids is sorted by; relate_to returns the existing rId rather
    # than making a second one.
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    ids = prs.slides._sldIdLst
    entries = {el.rId: el for el in list(ids)}
    wanted = [prs.part.relate_to(slide.part, RT.SLIDE) for slide in made]
    for el in list(ids):
        ids.remove(el)
    for rid in wanted:
        ids.append(entries[rid])
    spare_rid = prs.part.relate_to(spare.part, RT.SLIDE)
    prs.part.drop_rel(spare_rid)

    # The footer number, which every cloned slide inherited from the one it
    # was copied from, and the notes, so the deck can be rehearsed from itself.
    for i, (slide, spec) in enumerate(zip(made, SLIDES), 1):
        for name in ("Rectangle 11", "Rectangle 17"):
            set_text(named(slide, name), f"{i:02d}")
        if spec.get("notes"):
            slide.notes_slide.notes_text_frame.text = spec["notes"]

    prs.save(out)
    work.unlink(missing_ok=True)
    return out
