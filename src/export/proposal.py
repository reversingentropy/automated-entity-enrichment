"""
The evaluation proposal for the team, as a Word document.

    python -m src.export --proposal "data/Custom System Evaluation Proposal.docx"

Rebuilds the proposal in the shape its first draft had (a centred bold
title, bold section headings, a small bordered table under each task, a
TL;DR line and a "Produces" line), with what the TTE dumps showed folded
in: the denominator is news-driven changes, the numbers will be small and
carry intervals, and the arms cross over at six weeks. The text is the
same as docs/evaluation.md, which stays the copy under version control.
"""

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

MUTED = RGBColor(0x44, 0x4C, 0x56)

TITLE = "Custom System Evaluation"

# (kind, payload). Kinds: intro, h1, p, bullets, table, tldr, produces, note.
CONTENT = [
    ("intro", [("We evaluate the system on five dimensions: ", False),
               ("accuracy", True), (", ", False), ("effectiveness", True), (", ", False),
               ("efficiency", True), (", ", False), ("satisfaction", True), (" and ", False),
               ("reliability", True), (".", False)]),
    ("p", "Target sentence: the app finds X% of the news-driven changes the team finds, at Y "
          "seconds per change against Z minutes, adds N changes they would have missed, and "
          "fails mostly at [stage], on [kind of name]."),

    ("h1", "What we already know, before anyone starts"),
    ("p", "Comparing seven TTE dumps from September 2024 to August 2026 (six periods, 3,357 "
          "records changed, 4,046 field changes), only 12% of the team's record changes involve "
          "a name our three news sources printed in that period or the two months before. "
          "Correcting for names that appear in an article's body but not its headline (measured "
          "at 1.6x on articles where we have full-text extractions) puts the true figure near 19%. "
          "The rest is cataloguing work: records touched because a book was catalogued, "
          "historical figures corrected, bulk projects."),
    ("bullets", [
        "Recall is measured against news-driven changes, not all changes. A change counts in the "
        "denominator when the record's name appears in our three sources within the period or the "
        "two months before it. Measured against all TTE changes the number would read about 12%, "
        "which says more about what cataloguing is than about the app.",
        "The numbers will be small. The team makes roughly 400 record changes a quarter, of which "
        "perhaps 20 to 30 are news-driven and made by the two people on the manual arm at any "
        "time. Recall on 25 changes carries an interval of about ±19 points. We report the "
        "interval, not a bare percentage, and no target is met or missed on a number that wide.",
    ]),

    ("h1", "1. Accuracy: is each step right?"),
    ("p", "Three labelled sheets, drawn from August 2026 (2,135 articles, 236 of them judged "
          "relevant by the app), in week one. Between four people that is about two and a half "
          "hours each: roughly 75 minutes on relevance, 20 on matching, 75 on extraction. You "
          "never see the app's answer; it is held in a separate key file and joined after the "
          "labels are frozen. Everyone marks the first 50 rows of each sheet and the rest are "
          "divided between you, so agreement between labellers (Cohen's κ) can be reported. "
          "Put the time it took in the minutes cell at the top of the sheet."),

    ("sub", [("Relevance", True),
             (" — fill in ", False), ("relevant", True), (" TRUE or FALSE. TRUE = the article "
              "names a person, organisation, place, event, award, programme or legal act that the "
              "authority file holds or should hold, AND reports a fact that would change or create "
              "its record: an appointment, an award, a death, a rename, a merger, a founding. A "
              "mention alone is FALSE.", False)]),
    ("table", [["url", "source", "title", "description", "relevant"],
               ["…/tommy-koh-ramon-magsaysay-award", "cna",
                "Veteran diplomat Tommy Koh wins Ramon Magsaysay Award",
                "Tommy Koh, 88, has won the Ramon Magsaysay Award, regarded as Asia's version of "
                "the Nobel Prize.", "TRUE"],
               ["…/nus-bizad-charity-run-140000", "cna",
                "NUS Bizad Charity Run raises over S$140,000",
                "More than 1,300 NUS staff, students and alumni took part in the run, raising over "
                "S$140,000.", "FALSE"]]),
    ("note", "736 rows in three strata that between them cover every article the feed carried in "
             "August, so nothing was picked by hand and every article had a known chance of being "
             "drawn."),
    ("table", [["stratum", "in the month", "sampled", "each row stands for"],
               ["the app called it relevant", "236", "236", "1.0"],
               ["rejected, names a TTE record", "442", "200", "2.21"],
               ["rejected, names none", "1,457", "300", "4.86"]]),
    ("note", "An article is named when its title or description contains the name of an active "
             "TTE record of at least seven characters: a mechanical rule, applied to every "
             "rejected article. Misses concentrate there, which is why it is sampled harder; the "
             "weight puts it back in proportion. Precision is a census of the first stratum and "
             "needs no weighting; recall is weighted. Sampling the month at random instead would "
             "need about 1,400 rows for the same precision, because nine articles in ten are "
             "rejects that name nobody."),
    ("tldr", "TL;DR: fill in the relevant column with TRUE or FALSE for all rows."),
    ("produces", "Produces: precision, recall, F1 by language."),

    ("sub", [("Matching", True),
             (" — fill in ", False), ("same", True), (" with Y, N or ?. ? means the row does "
              "not carry enough to decide; it is a real answer and is counted, not dropped.", False)]),
    ("table", [["name", "evidence", "tte_id", "tte_name", "tte_fields", "same"],
               ["Alan Chan", "Former CPA chairman Alan Chan received the Order of Temasek.",
                "18593383", "Chan, Alan Heng Loon",
                "Occupation: Civil servant · Affiliations: Singapore Press Holdings · Born: 1952",
                ""]]),
    ("note", "300 rows: 150 pairs the app matched, 150 it did not, with the best record it was "
             "shown, drawn at random. The evidence sentence is in the sheet, so a row can be "
             "judged without opening the article. At 150 a side, precision and recall each land "
             "within about ±0.06."),
    ("tldr", "TL;DR: fill in the same column with Y, N or ? for all rows."),
    ("produces", "Produces: precision, recall, F1; the ? rate; results split by Latin and Chinese names."),

    ("sub", [("Extraction", True),
             (" — for each name the app pulled out, fill in ", False), ("verdict", True),
             (": ok, wrong (not what the article says, or not something an authority record would "
              "hold) or not_worth (real, but no record would be created for it). Put any field "
              "whose value is wrong in ", False), ("field_errors", True),
             (". On the article's blank last row, put in ", False), ("missed", True),
             (" any name the article carries that the app should have pulled out and did not, one "
              "per line.", False)]),
    ("table", [["article_url", "language", "entity", "type", "fields", "verdict", "field_errors", "missed"],
               ["…/khaw-boon-wan-sph-media-trust", "en", "Khaw Boon Wan", "PERSON",
                "Occupation: Cabinet Minister · Affiliations: SPH Media Trust", "", "", ""],
               ["…/khaw-boon-wan-sph-media-trust", "en", "SPH Media Trust", "ORGANISATION",
                "Founder: Khaw Boon Wan", "", "", ""],
               ["…/khaw-boon-wan-sph-media-trust", "en", "", "", "", "", "", "Teo Chee Hean"]]),
    ("note", "60 articles from August 2026 that the app processed, English and Chinese, with the "
             "names it found already filled in. You are checking and adding, not extracting from "
             "scratch."),
    ("tldr", "TL;DR: mark each row ok / wrong / not_worth, and add what was missed."),
    ("produces", "Produces: precision, recall, F1 by language and type; error rate per field."),

    ("h1", "2. Effectiveness: does it find what you find, and more?"),
    ("p", "Design: crossover. Two people use the app while two work the old way; at six weeks they "
          "swap. Nobody on the manual arm opens the desk during their manual stretch, so nothing "
          "they find is contaminated by what the app showed them, and by the end each person has "
          "worked both ways, which is what lets us compare times without blaming the difference on "
          "who is faster."),
    ("p", "Three months. Decide every card you are dealt; a record you cannot settle is Keep for "
          "review; there is no skipping. One row in the log every time you identify a change or a "
          "new entity, either way of working."),
    ("table", [["method", "article_url", "tte_entity", "tte_uuid", "kind", "field", "old", "new", "date"],
               ["manual", "…/khaw-boon-wan-sph-media-trust", "Khaw Boon Wan", "18533710",
                "amend", "Affiliations", "People's Action Party",
                "People's Action Party | SPH Media Trust", "2026-10-14"],
               ["app", "…/tommy-koh-ramon-magsaysay-award", "Tommy Koh", "18338504", "amend",
                "Awards", "… Order of Nila Utama (2008)",
                "… | Ramon Magsaysay Award (2026)", "2026-10-02"],
               ["manual", "…/new-charity-council-chair", "Tan Kim Peng", "", "new", "", "", "",
                "2026-10-20"]]),
    ("note", "kind is new for a record that does not exist yet, amend otherwise; a new row needs "
             "no field, old or new."),
    ("tldr", "TL;DR: fill in a row every time you identify a change or a new entity while reading."),
    ("produces", "Produces: of the news-driven changes made on the manual arm, the share the app "
                 "also proposed and the share a reviewer accepted, each with its interval; changes "
                 "the app produced that the manual arm did not; and for everything the app missed, "
                 "which step lost it (feed, relevance, extraction, matching, withheld, reviewer)."),

    ("h1", "3. Efficiency: what does it cost?"),
    ("p", "The desk records how long each card was on it. For the manual side, two numbers a week "
          "on the desk (Your sheet → This week)."),
    ("table", [["week_start", "minutes", "changes", "method", "user"],
               ["2026-10-05", "140", "6", "manual", "Yaw Huah"],
               ["2026-10-12", "95", "3", "app", "Yaw Huah"]]),
    ("tldr", "TL;DR: log it once a week, for whichever arm you are on."),
    ("produces", "Produces: seconds per change on the desk against minutes per change by hand, for "
                 "the same people in both arms; days from article to change, both ways; running "
                 "cost, which is nil."),

    ("h1", "4. Satisfaction: is it good to use?"),
    ("p", "At month one and month three, complete the usability survey on Form.gov.sg: ten "
          "statements, each scored 1 (strongly disagree) to 5 (strongly agree). Two minutes."),
    ("table", [["statement", "score"],
               ["I think that I would like to use this system frequently.", ""],
               ["I found the system unnecessarily complex.", ""],
               ["I thought the system was easy to use.", ""],
               ["… ten in all, the standard set", ""]]),
    ("tldr", "TL;DR: complete the survey at month 1 and month 3."),
    ("produces", "Produces: the SUS score (0–100), read beside what the desk records: how often "
                 "a proposal was reworded before it was accepted, how often a record was kept for "
                 "review, how often a reviewer had to search for a record the app should have "
                 "offered, and the notes left on cards."),

    ("h1", "5. Reliability: does it just run?"),
    ("p", "Log errors, issues, bottlenecks and feedback as they arise, in the shared issues sheet."),
    ("table", [["date", "what happened", "what you were doing", "blocked you"],
               ["2026-10-06", "The deck was empty this morning", "signed in at 9am", "yes"]]),
    ("tldr", "TL;DR: log any issue as it comes up."),
    ("produces", "Produces: nights the pipeline ran against nights it failed and why; a running "
                 "list of issues by type; how each TTE re-import went."),

    ("h1", "Decisions to confirm"),
    ("bullets", [
        "Crossover at six weeks: two on the app, two manual, then swap.",
        "Recall is measured against news-driven changes, with the definition above, and reported "
        "with its interval.",
        "Every change gets a row in the log, either arm.",
        "The weekly two numbers get logged.",
        "The three sheets are labelled in week one, before the run starts.",
        "The sheets and your desk decisions are the evaluation; nobody marks anything else.",
    ]),
]


def _runs(para, parts):
    for text, bold in parts:
        run = para.add_run(text)
        run.bold = bold


def _table(doc, rows):
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.autofit = True
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            cell = table.cell(r, c)
            cell.text = ""
            para = cell.paragraphs[0]
            run = para.add_run(str(value))
            run.font.size = Pt(8)
            run.bold = r == 0
    return table


def build(out: Path) -> Path:
    doc = Document()
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Pt(72)
        section.left_margin = section.right_margin = Pt(72)
    normal = doc.styles["Normal"].font
    normal.name = "Calibri"
    normal.size = Pt(11)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run(TITLE)
    run.bold = True
    run.underline = True

    for kind, payload in CONTENT:
        if kind == "intro" or kind == "sub":
            para = doc.add_paragraph()
            _runs(para, payload)
        elif kind == "h1":
            para = doc.add_paragraph()
            para.paragraph_format.space_before = Pt(14)
            run = para.add_run(payload)
            run.bold = True
        elif kind == "p":
            doc.add_paragraph(payload)
        elif kind == "bullets":
            for item in payload:
                doc.add_paragraph(item, style="List Paragraph").paragraph_format.left_indent = Pt(24)
        elif kind == "table":
            _table(doc, payload)
        elif kind == "note":
            para = doc.add_paragraph()
            run = para.add_run(payload)
            run.italic = True
            run.font.size = Pt(9)
            run.font.color.rgb = MUTED
        elif kind == "tldr":
            para = doc.add_paragraph()
            run = para.add_run(payload)
            run.bold = True
        elif kind == "produces":
            doc.add_paragraph(payload)

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return out
