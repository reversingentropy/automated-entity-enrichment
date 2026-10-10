"""
The IFLA talk, v4: v3 plus one slide, "Take the person out", straight after "The AI does the reading. A person does the deciding."

    .venv/bin/python scripts/build_talk_v4.py

Runs build_talk_v2.main() with the output paths pointed at v4 (so v3 and the user's own files are never written), then adds the slide.
The slide shows the pipeline twice: as it runs now (a person at the end) and as the no-person replay on stored data
(scripts/jev_flow.py full2: jev decides, Gemini writes). Every number on it is measured and traced below; none of it is accuracy.

  30 in 100 / 6 in 100   entities whose article jev's relevance score puts under the cut-off 0.53 / 0.23   data/jev/flow-full2.csv (4,575 entities)
  10 of 2,778            Gemini MATCH_AND_UPDATE entities that the no-person flow makes into new records  data/jev/flow-full2.csv
  22 in 100              of the 100 changed cards in the 160-card audit (both models agreed), the reviewer said no (all description-only)
                         data/jev/audit-answers.csv (notes only, not on the slide)
  33 seconds             median per card on the 48-card desk audit                                       data/audit results/decisions.csv
  the two rows of counts the same 48 cards decided by the reviewer (decisions.csv) and by the replay (flow-full2.csv), see desk_counts()
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import build_talk as bt  # noqa: E402
import build_talk_v2 as v2  # noqa: E402
from build_talk import AMBER, GREY, INK, LINE, NAVY, P, PALE, RED, TEAL, block, tbox  # noqa: E402
from pptx import Presentation  # noqa: E402

import jev_same_entities as same_entities  # noqa: E402
from src.export.slides import clone, set_text  # noqa: E402

OUT = ROOT / "data/dist/designing-for-the-reviewer-v4-generated.pptx"   # v4.pptx is the user's own edited copy (slide 8, saved 2026-10-06 23:49): never written by this script
SCRIPT = ROOT / "data/dist/speaking-script-v4.docx"
PREVIEW = ROOT / "data/dist/talk-preview-v4"
# Times. jev's are from this replay's own logs; the model's only where the project ever timed it.
JEV_RELEVANCE = "55 s for 3,747"          # data/jev/relevance-run.log: the live set, 3,747 articles in 55 s
JEV_RESOLUTION = "3 s per 100 entities"   # data/jev/fair-listwise.log: 7,338 calls (3,669 entities, two option orders) in 113 s = 3.1 s per 100
MODEL_RESOLUTION = "9 min per 100 entities (22 s all at once)"  # docs/design.md: 166 entities, one call per article about 15 minutes = 9 min per 100; the same 166 in one request 36 s = 22 s per 100
AFTER = 6                                                   # zero-based index of "split"; the new slide goes straight after it

LM, CW = v2.LM, v2.CW

NOTE = ("Someone will ask: why keep the person at all? We tried leaving them out, on stored data, with a second model, jev from TypeSafe, which answers typed questions and writes no text, making the decisions while the pipeline's model only writes the sentences. "
        "The chart reads from the middle outwards: left is how it runs now, right is the same pipeline without the person.\n\n"
        "Relevance, counted on the live feed's articles: of three thousand seven hundred and forty-seven, the model kept two hundred and sixteen. jev, at the cut-off that catches ninety-five in a hundred on our validation articles, kept eight hundred and ninety, "
        "and caught two hundred and thirteen of those two hundred and sixteen. So the next stage would run on four times as many articles. At a stricter cut-off it keeps three hundred and eighty-three and catches only eighty-four in a hundred. The cut-off is a number somebody chooses, and nobody reviews it.\n\n"
        "Extraction and retrieval are the same model and the same code in both, because jev cannot write.\n\n"
        "Resolution, which record is it, on two thousand two hundred and eighty-one stored entities: the model says sixty-one the same record, thirty-one new, eight unsure. jev, with code for the entities that have no candidate, says sixty-one, thirty-eight, one.\n\n"
        "Time, stage by stage. jev: relevance on the three thousand seven hundred and forty-seven live articles took fifty-five seconds; resolution of three thousand six hundred and sixty-nine entities took a hundred and thirteen seconds, about three seconds per hundred entities. The model resolves all of an article's entities in one call. It was timed once, on a hundred and sixty-six entities: about fifteen minutes with one call per article on the free tier, nine minutes per hundred entities, and thirty-six seconds when all hundred and sixty-six went in one request, twenty-two seconds per hundred. Its relevance and extraction were never timed. My estimates, from the design notes and not measured: about ten seconds per hundred articles for relevance, and about thirty seconds an article for extraction, so four times the articles is about four times the extraction time. A person takes a median thirty-three seconds a card, fifty-five minutes for forty-eight cards.\n\n"
        "The last row is the only place a person's decisions exist: the same forty-eight cards. The person amended thirty-nine, made six new records and judged three not worth a record. Without a person: eight amended, eighteen with no change, twelve new records, two not worth a record, eight dropped unseen. "
        "The no-person version reaches the same kind of outcome as the person on sixteen of the forty-eight cards. Careful: those cards were chosen to include cases where the models disagreed, so this overstates how often they differ. So the answer to the title is: faster, and not as good on the only cases where we have a person to compare against. Whether jev would help as a second check beside the person, not instead of them, we have not tested.\n\n"
        "Two more numbers from the whole data set. In our first audit, of the changes both models agreed on, the reviewer rejected twenty-two in a hundred, all descriptions. And ten of the two thousand seven hundred and seventy-eight matched records would have become duplicate new records.\n\n"
        "A note on names: the live feed's answers are Gemini's. The stored resolutions came from Gemini for the live feed and from an internal model for the archive, nine in ten of them. This is a pilot on stored data, with one reviewer who is not a cataloguer. It measures agreement, not accuracy. "
        "What it shows is that taking the person out does not remove the decisions. It moves them into numbers.")

COLUMNS = ["Amended", "No change", "New record", "Not worth a record", "Dropped unseen"]


def desk_counts():
    """The same 48 cards, decided by the reviewer and by the no-person replay. A card takes its most active outcome across its entities;
    it is 'dropped' only when every entity on it was dropped. Returns (reviewer, replay), each in the order of COLUMNS."""
    import csv
    import json
    from collections import Counter
    jev = ROOT / "data/jev"
    rows = {r["extracted_id"]: r for r in csv.DictReader(open(jev / "flow-full2.csv", encoding="utf-8-sig"))}
    decisions = list(csv.DictReader(open(ROOT / "data/audit results/decisions.csv", encoding="utf-8-sig")))
    key = json.loads((jev / "desk-audit-key.json").read_text(encoding="utf-8"))
    page = (ROOT / "data/dist/prototype-audit.html").read_text(encoding="utf-8")
    tpl = (ROOT / "prototype/desk.template.html").read_text(encoding="utf-8")
    i = tpl.index("/*__CARDS__*/[]")
    pre = tpl[max(0, i - 60):i][-30:]
    cards, _ = json.JSONDecoder().raw_decode(page[page.index(pre) + len(pre):].replace("<\\/", "</"))
    entity_key = {c["entity"]: c["key"] for c in cards}
    order = ["amended", "to create", "not worth a record", "kept for review", "same", "dropped"]
    person, replay = Counter(), Counter()
    for r in decisions:
        person[r["Outcome"]] += 1
        k = next((k for e, k in entity_key.items() if r["Entity"].startswith(e) or e in r["Entity"]), None)
        outs = [next(b for b in order if rows[str(e)]["flow_outcome"].startswith(b)) for e in key[k]["extracted_ids"] if str(e) in rows]
        replay[min(outs, key=order.index)] += 1
    assert sum(person.values()) == sum(replay.values()) == 48
    return ([person["Amended"], 0, person["To create"], person["Not worth a record"], 0],
            [replay["amended"], replay["same"], replay["to create"], replay["not worth a record"] + replay["kept for review"], replay["dropped"]])


def desk_agreement():
    """On the 48 cards: in how many did the no-person replay reach the same kind of outcome as the reviewer? Amended with amended, new record with
    new record, not worth a record with not worth a record or dropped as not relevant. 'Kept for review' is not agreement."""
    import csv
    import json
    jev = ROOT / "data/jev"
    rows = {r["extracted_id"]: r for r in csv.DictReader(open(jev / "flow-full2.csv", encoding="utf-8-sig"))}
    decisions = list(csv.DictReader(open(ROOT / "data/audit results/decisions.csv", encoding="utf-8-sig")))
    key = json.loads((jev / "desk-audit-key.json").read_text(encoding="utf-8"))
    page = (ROOT / "data/dist/prototype-audit.html").read_text(encoding="utf-8")
    tpl = (ROOT / "prototype/desk.template.html").read_text(encoding="utf-8")
    i = tpl.index("/*__CARDS__*/[]")
    pre = tpl[max(0, i - 60):i][-30:]
    cards, _ = json.JSONDecoder().raw_decode(page[page.index(pre) + len(pre):].replace("<\\/", "</"))
    entity_key = {c["entity"]: c["key"] for c in cards}
    order = ["amended", "to create", "not worth a record", "kept for review", "same", "dropped"]
    agree = 0
    for r in decisions:
        k = next((k for e, k in entity_key.items() if r["Entity"].startswith(e) or e in r["Entity"]), None)
        outs = [next(b for b in order if rows[str(e)]["flow_outcome"].startswith(b)) for e in key[k]["extracted_ids"] if str(e) in rows]
        got = min(outs, key=order.index)
        want = {"Amended": ("amended",), "To create": ("to create",), "Not worth a record": ("not worth a record", "dropped")}[r["Outcome"]]
        agree += got in want
    return agree, len(decisions)


def s_person_out(s):
    """A mirrored bar chart: the spine is the stage, the left half is how it runs now, the right half is the same stage without the person."""
    nums = same_entities.numbers()
    rel = same_entities.live_relevance()
    now48, off48 = desk_counts()
    edge_l, edge_r, maxw = 5.645, 7.685, 4.75                 # bars grow outwards from the two edges of the centre column
    cx, cw = 5.75, 1.83
    WHITE_ = bt.WHITE
    grey_fill = LINE

    def centre(y, h, title, sub):
        tbox(s, cx, y, cw, h, [P(title, 15, True, INK, "c"), P(sub, 11, False, GREY, "c")], anchor="m", inset=(0.02, 0.02))

    def side_text(side, y, h, paras):
        x = edge_l - maxw if side == "L" else edge_r
        tbox(s, x, y, maxw, h, paras, anchor="m", inset=(0.02, 0.02))

    def track(side, y, h):
        block(s, edge_l - maxw if side == "L" else edge_r, y, maxw, h, PALE)

    def bar(side, y, h, segs, total, inside=True):
        """segs: (value, colour, word); labelled inside where it fits. Returns the words of the segments too narrow to carry their own."""
        track(side, y, h)
        pos, left_out = 0.0, []
        for v, col, word in segs:
            w = maxw * v / total
            if v <= 0:
                continue
            x = edge_l - pos - w if side == "L" else edge_r + pos
            block(s, x, y, w, h, col)
            ink = INK if col == LINE else bt.WHITE
            if not inside:
                pass
            elif w >= 1.0:
                tbox(s, x, y, w, h, [P(f"{v} {word}", 14, True, ink, "c")], anchor="m", inset=(0, 0))
            elif w >= 0.3:
                tbox(s, x, y, w, h, [P(str(v), 14, True, ink, "c")], anchor="m", inset=(0, 0))
                left_out.append(f"{v} {word}")
            else:
                left_out.append(f"{v} {word}")
            pos += w
        return left_out

    def rule_at(y):
        block(s, LM, y, CW, 0.012, LINE)

    # column heads
    tbox(s, edge_l - maxw, 1.1, maxw, 0.55, [P("NOW", 18, True, INK, "c"), P("the model decides, a person approves", 11, False, GREY, "c")], anchor="m", inset=(0.02, 0.02))
    tbox(s, edge_r, 1.1, maxw, 0.55, [P("PERSON REMOVED", 18, True, RED, "c"), P("jev decides, the model writes", 11, False, GREY, "c")], anchor="m", inset=(0.02, 0.02))

    # 1 relevance: articles, the live feed
    y = 1.72
    rule_at(y - 0.04)
    centre(y, 0.88, "Relevance", f"{rel['n']:,} live articles")
    for side, kept, colour, line1, line2 in (("L", rel["model_kept"], TEAL, f"{rel['model_kept']} kept", "by the model, in the nightly run · est. 10 s per 100 articles"),
                                             ("R", rel["jev_kept"], AMBER, f"{rel['jev_kept']} kept", f"by jev, catching {rel['jev_catches']} of the model's {rel['model_kept']} · {JEV_RELEVANCE} articles")):
        bar(side, y + 0.06, 0.26, [(kept, colour, "")], rel["n"], inside=False)
        side_text(side, y + 0.32, 0.56, [P(line1, 20, True, INK, "r" if side == "L" else "l"), P(line2, 11, False, GREY, "r" if side == "L" else "l")])

    # 2 extraction and retrieval: the same
    y = 2.68
    rule_at(y - 0.04)
    centre(y, 0.46, "Extraction", "and retrieval")
    for side, text in (("L", "same model, same code · est. 30 s an article"), ("R", f"the same, on {rel['jev_kept']} articles, not {rel['model_kept']} · est. 4× the time")):
        x = edge_l - maxw if side == "L" else edge_r
        tbox(s, x, y + 0.04, maxw, 0.38, [P(text, 13, False, GREY, "c")], anchor="m", fill=PALE, radius=0.06, inset=(0.1, 0.02))

    # 3 resolution: entities
    y = 3.22
    rule_at(y - 0.04)
    centre(y, 0.86, "Resolution", "2,281 stored entities")
    r_now, r_jev = nums["resolution_now"], nums["resolution_jev"]
    for side, vals in (("L", r_now), ("R", r_jev)):
        vals = [round(v) for v in vals]
        out = bar(side, y + 0.06, 0.34, [(vals[0], TEAL, "same record"), (vals[1], NAVY, "new"), (vals[2], AMBER, "unsure")], 100)
        side_text(side, y + 0.44, 0.36, [P(" · ".join(out + [MODEL_RESOLUTION if side == "L" else JEV_RESOLUTION]), 12, False, GREY, "r" if side == "L" else "l")])

    # 4 time
    y = 4.12
    rule_at(y - 0.04)
    centre(y, 0.78, "A person", "decides")
    side_text("L", y, 0.78, [P("33 s a card", 24, True, RED, "r"), P("a person · 55 minutes for 48 cards", 12, False, GREY, "r")])
    side_text("R", y, 0.78, [P("0 s", 24, True, AMBER, "l"), P("nobody · jev answers 41 to 70 decisions a second", 12, False, GREY, "l")])

    # 5 the 48 cards
    y = 5.0
    rule_at(y - 0.04)
    centre(y, 0.86, "48 cards", "the same cards, two ways")
    for side, vals in (("L", now48), ("R", off48)):
        out = bar(side, y + 0.06, 0.34, [(vals[0], TEAL, "amended"), (vals[1], grey_fill, "no change"), (vals[2], NAVY, "new"), (vals[3], AMBER, "not worth"), (vals[4], RED, "dropped")], 48)
        side_text(side, y + 0.44, 0.36, [P(" · ".join(out), 12, False, GREY, "r" if side == "L" else "l")])
    rule_at(5.9)

    agree, total = desk_agreement()
    tbox(s, LM, 5.9, CW, 0.42, [P(runs=[("Faster, but not as good: ", {"color": RED}), (f"it reaches the person's outcome on {agree} of {total} cards.", {"color": INK})], size=22, bold=True)],
         anchor="m", inset=(0.02, 0.02))
    tbox(s, LM, 6.3, CW, 0.32, [P("The decisions do not disappear. They move into cut-offs nobody reviews. Untested: jev as a second check beside the person.", 14, False, INK)],
         anchor="m", inset=(0.02, 0.02))
    tbox(s, LM, 6.62, CW, 0.54, [P("Relevance: live-feed articles, the nightly model against jev at the cut-off that keeps 95 in 100 relevant (validation set). Resolution: stored entities not used to set jev's cut-offs. "
                                 "Times: jev's measured here at 20 calls at once, one call not timed; the model's resolution from one test of 166 entities (free tier); \"est.\" is a guess from the design notes, never timed. "
                                 "Last row: 48 cards chosen to include disagreements; one reviewer, not a cataloguer; agreement, not accuracy.", 10, False, GREY)],
         anchor="m", inset=(0.02, 0.02))


def main():
    v2.OUT, v2.SCRIPT, v2.PREVIEW = OUT, SCRIPT, PREVIEW
    v2.main()                                              # builds v3's deck, saved as v4
    prs = Presentation(OUT)
    slides = list(prs.slides)
    sl = clone(prs, slides[2])                             # the problem slide: only its template chrome is kept
    v2.keep_chrome(sl)
    bt.TAG[0] = "person-out"
    v2.header(sl, "Could the person be removed?")
    s_person_out(sl)
    sl.notes_slide.notes_text_frame.text = NOTE
    ids = prs.slides._sldIdLst
    entry = list(ids)[-1]
    ids.remove(entry)
    ids.insert(AFTER + 1, entry)
    for i, s in enumerate(prs.slides, 1):                  # footer numbers follow the new order
        shape = s.shapes[5] if len(s.shapes) > 5 else None
        if shape is not None and shape.has_text_frame and re.fullmatch(r"\d\d", shape.text_frame.text.strip()):
            set_text(shape, f"{i:02d}")
    unknown = next(s for s in prs.slides if any(sh.has_text_frame and sh.text_frame.text.strip().startswith("What we do not know") for sh in s.shapes))
    t = unknown.notes_slide.notes_text_frame.text
    unknown.notes_slide.notes_text_frame.text = t.replace("Whether a second model could replace the person is untested.",
                                                           "Whether a second model could replace the person: we ran one pilot on stored data, which is slide eight, and it is thin evidence.")
    prs.save(OUT)


if __name__ == "__main__":
    main()
    bt.preview(OUT, PREVIEW)
    for problem in bt.PROBLEMS:
        print("OVERFLOW", problem)
    seq = ["title", "idea", "problem", "record", "labour", "how", "split", "person-out", "test", "reveal", "pp", "wrong", "sources", "leftout", "four", "unknown", "thanks"]
    end = v2.script_docx(OUT, seq=seq, extra_minutes={"person-out": 0.75}, out=SCRIPT, version="v4")
    n = len(Presentation(OUT).slides)
    print(f"{OUT.name}: {n} slides; the clock ends at {int(end)}:{int(round((end % 1) * 60)):02d}")
    sys.exit(1 if bt.PROBLEMS else 0)
