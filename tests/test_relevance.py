"""Job 1: the sparse-to-full verdict inversion, and prompt assembly."""

import json

from src.job1_relevance.prompt import build_article_payload, render
from src.job1_relevance.update import build_payload
from src.job1_relevance.__main__ import chunked
from src.shared.models import RelevanceResponse

ARTICLES = [
    {"id": 1, "title": "Judges to retire", "description": "Two judges retire in September."},
    {"id": 3, "title": "Commentary", "description": "What the reshuffle means."},
    {"id": 7, "title": "Firm winds up", "description": "My Community is closing."},
]


def test_every_fetched_article_gets_exactly_one_verdict():
    # The safety property: the prompt names only the relevant ids, so anything
    # it omits must still be written false rather than left NULL.
    payload = build_payload(ARTICLES, {1: "retired", 7: "closed"})
    assert payload == [
        {"id": 1, "relevant": True, "reason": "retired"},
        {"id": 3, "relevant": False, "reason": None},
        {"id": 7, "relevant": True, "reason": "closed"},
    ]


def test_no_relevant_articles_still_writes_a_verdict_for_each():
    payload = build_payload(ARTICLES, {})
    assert [row["relevant"] for row in payload] == [False, False, False]
    assert all(row["reason"] is None for row in payload)


def test_payload_never_invents_or_drops_articles():
    payload = build_payload(ARTICLES, {1: "x"})
    assert {row["id"] for row in payload} == {a["id"] for a in ARTICLES}


def test_prompt_carries_title_and_description():
    # The prompt is written around a headline, so the title must be sent.
    payload = json.loads(build_article_payload(ARTICLES))
    assert payload[0]["title"] == "Judges to retire"
    assert payload[0]["description"].startswith("Two judges")


def test_html_entities_are_decoded_before_the_model_sees_them():
    payload = json.loads(build_article_payload(
        [{"id": 1, "title": "a &amp; b", "description": "movement&#039;s wing"}]))
    assert payload[0]["description"] == "movement's wing"
    assert payload[0]["title"] == "a & b"


def test_render_includes_template_and_batch():
    out = render(ARTICLES)
    assert "relevance filter" in out
    assert '"id": 1' in out


def test_schema_accepts_the_documented_shapes():
    assert RelevanceResponse.model_validate_json('{"results":[]}').results == []
    parsed = RelevanceResponse.model_validate_json(
        '{"results":[{"id":1,"reason":"because"}]}')
    assert parsed.results[0].id == 1


def test_chunked_covers_every_item_without_overlap():
    items = list(range(450))
    chunks = list(chunked(items, 200))
    assert [len(c) for c in chunks] == [200, 200, 50]
    assert [x for c in chunks for x in c] == items


def test_a_page_that_failed_three_times_is_not_extraction_work():
    """
    An unreadable page used to be retried every night forever. The failure
    is counted on the row by Job 2, and after three the queue skips it; a row
    someone gave text by hand is always work.
    """
    from src.job2_extraction.fetch import MAX_ATTEMPTS
    import inspect
    from src.job2_extraction import fetch
    src = inspect.getsource(fetch)
    assert MAX_ATTEMPTS == 3 and "fetch_attempts" in src
    readable = [l for l in src.splitlines() if "return [r for r in rows if" in l][0]
    assert "text" in readable and "MAX_ATTEMPTS" in readable


def test_relevance_reads_no_page_and_keeps_no_text():
    """Job 1 judges from the title and description; the body is Job 2's, and
    is never written to the table."""
    import inspect
    from src.job1_relevance import fetch as f1, __main__ as m1
    from src.job2_extraction import update as u2
    assert "text" not in f1.UNSCORED_COLUMNS
    assert "prefetch" not in inspect.getsource(m1) and "scrape" not in inspect.getsource(m1)
    assert '"text": None' in inspect.getsource(u2.save)


def test_extraction_prompt_carries_the_publication_date():
    """
    Every dated TTE field asks for a year, and an article from 2016 saying
    "on Tuesday" gives the model nothing to count from without this.
    """
    from src.job2_extraction.prompt import render

    out = render("Headline", "Body text.", "2016-03-04T07:00:00+08:00")
    assert "Published: 2016-03-04\nHeadline\n\nBody text." in out
    assert "DATES." in out and "never from today" in out
    # and nothing is emitted when the date is unknown
    assert "Published:" not in render("Headline", "Body text.", None)
