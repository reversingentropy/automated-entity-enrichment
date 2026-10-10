"""The conference deck: built on the symposium's template, in its slot's length."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "data/template_for_presentation/6th IFLA AI PowerPoint Template 2.potx"


def test_the_deck_fits_the_slot_and_says_what_to_say():
    """Twenty minutes is about fourteen slides; every one carries its own notes."""
    from src.export.slides import SLIDES

    content = [s for s in SLIDES if s.get("kind", "content") not in ("title", "thanks", "section")]
    assert 12 <= len(SLIDES) <= 16, "20 minutes is 14 slides give or take"
    assert all(s.get("notes") for s in content), "a content slide without speaker notes"
    assert all(s.get("heading") for s in content)
    # Figures on the deck are the ones the docs carry; a stray placeholder is a bug.
    flat = " ".join(t for s in SLIDES for t, _, _ in s.get("lines", []))
    assert "TODO" not in flat and "Lorem" not in flat and "XXX" not in flat


@pytest.mark.skipif(not TEMPLATE.exists(), reason="needs the symposium template under data/")
def test_the_deck_builds_on_the_template_and_keeps_its_chrome(tmp_path):
    from pptx import Presentation

    from src.export.slides import SLIDES, build

    out = build(tmp_path / "slides.pptx")
    prs = Presentation(out)
    slides = list(prs.slides)
    assert len(slides) == len(SLIDES)
    assert prs.slide_width / 914400 == pytest.approx(13.333, abs=0.01)

    # The template's footer survives on content slides, numbered in order.
    numbers = []
    for slide in slides:
        for shape in slide.shapes:
            if shape.name in ("Rectangle 11", "Rectangle 17") and shape.has_text_frame:
                numbers.append(shape.text_frame.text)
    assert numbers == [f"{i:02d}" for i in (2, 3, 5, 6, 8, 9, 10, 12, 13, 14)]

    # Nothing of the template's own dummy text is left anywhere.
    everything = " ".join(shape.text_frame.text for slide in slides for shape in slide.shapes
                          if shape.has_text_frame)
    for dummy in ("PRESENTATION TITLE", "[TEXT]", "Lorem Ipsum", "Presenter name", "Section title"):
        assert dummy not in everything, f"template placeholder left in: {dummy}"
    assert "6th IFLA Symposium" in everything, "the symposium's own footer should stay"

    # The one chart is the delta finding, and it is drawn to a scale.
    charts = [sh.chart for slide in slides for sh in slide.shapes if sh.has_chart]
    assert len(charts) == 1
    assert charts[0].value_axis.maximum_scale == pytest.approx(0.25)


@pytest.mark.skipif(not TEMPLATE.exists(), reason="needs the symposium template under data/")
def test_every_picture_on_every_slide_can_be_displayed(tmp_path):
    """A copied picture must point at an image its own slide holds."""
    from pptx import Presentation

    from src.export.slides import R_NS, build

    prs = Presentation(build(tmp_path / "slides.pptx"))
    broken = []
    for number, slide in enumerate(prs.slides, start=1):
        for node in slide.shapes._spTree.iter():
            rid = node.get(R_NS + "embed")
            if rid and rid not in slide.part.rels:
                broken.append(number)
    assert broken == []


def test_the_proposal_says_what_the_dumps_showed(tmp_path):
    """The denominator, the interval and the crossover are the three fixes; none may drop out."""
    import zipfile
    from xml.etree import ElementTree as ET

    from src.export.proposal import build

    out = build(tmp_path / "proposal.docx")
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    doc = ET.fromstring(zipfile.ZipFile(out).read("word/document.xml"))
    text = " ".join(t.text or "" for t in doc.iter(f"{{{W}}}t"))

    assert "news-driven changes" in text and "12%" in text
    assert "interval" in text and "crossover" in text.lower()
    # The five dimensions and a task under each.
    for heading in ("1. Accuracy", "2. Effectiveness", "3. Efficiency",
                    "4. Satisfaction", "5. Reliability"):
        assert heading in text
    # One instruction line per task: three sheets and one log under each of
    # effectiveness, efficiency, satisfaction and reliability.
    assert text.count("TL;DR") == 7
    # The first draft's contradictions are gone.
    assert "Yes/No/Not Sure" not in text
    assert "add a row for each entity, entity type" not in text
