"""The stages done by hand in AI Studio (src/manual): offline, with the database, clipboard and websites faked."""

import json

import pytest

import src.manual.__main__ as cli
from src.manual import clipboard, stages
from src.shared.models import RelevanceResponse

ENTITY = {"entity_name": "Masjid Al-Islah", "entity_name_en": "Al-Islah Mosque", "entity_type": "ORGANISATION",
          "summary": "The mosque reopened.", "evidence": "Masjid Al-Islah dibuka semula.", "evidence_en": "It reopened.",
          "fields": {}, "confidence": "high", "role": "subject"}


@pytest.fixture
def db(monkeypatch):
    """What is still waiting, what was written, and no model column to label."""
    state = {"waiting": set(), "written": []}
    monkeypatch.setattr(stages, "still", lambda table, ids, column, value: {i for i in ids if i in state["waiting"]})
    monkeypatch.setattr(stages, "column_exists", lambda table, column: False)
    return state


def test_an_answer_wrapped_in_markdown_or_a_preamble_is_read_as_the_json_inside():
    good = '{"results": [{"id": 7, "reason": "A mosque opened."}]}'
    for text in (good, f"```json\n{good}\n```", f"Here you are:\n\n{good}\n\nAnything else?"):
        assert clipboard.parse(text, RelevanceResponse).results[0].id == 7
    with pytest.raises(ValueError):
        clipboard.parse("Sorry, I cannot help with that.", RelevanceResponse)


def test_an_answer_copied_with_its_long_lines_broken_is_mended_as_it_was():
    # As the first answer by hand arrived (23 Oct 2026): broken every 80 or so characters, inside the values.
    wrapped = ('{ "results": [ { "id": 1, "reason": "Singapore Airlines was named the\n'
               'World\\"s Best {Airline} at the awards held in\nSingapore." },\n'
               '{ "id": 2, "reason": "国立大学医院\n凭借“绿色手术室”计划 and சிங்கப்பூரில்\nமுதன்முறையாக" } ] }')
    got = clipboard.parse(wrapped, RelevanceResponse).results
    assert got[0].reason == 'Singapore Airlines was named the World"s Best {Airline} at the awards held in Singapore.'
    assert got[1].reason == "国立大学医院凭借“绿色手术室”计划 and சிங்கப்பூரில் முதன்முறையாக"


def test_an_answer_that_stops_before_its_end_is_called_cut_short():
    with pytest.raises(ValueError, match="cut short"):
        clipboard.parse('{"results": [{"id": 1, "reason": "A } inside a value"}, {"id": 2, "reas', RelevanceResponse)


def test_relevance_sends_every_unscored_article_at_once_and_writes_only_those_still_unscored(db, monkeypatch):
    import src.job1_relevance.fetch as fetch
    import src.job1_relevance.update as update
    articles = [{"id": i, "title": f"Headline {i}", "description": "d"} for i in (1, 2, 3)]
    monkeypatch.setattr(fetch, "fetch_unscored_articles", lambda limit=None: articles)
    prompt, sent, what = stages.relevance_export(None)
    assert all(f"Headline {i}" in prompt for i in (1, 2, 3)) and "JSON schema" in prompt and sent == {"ids": [1, 2, 3]}
    monkeypatch.setattr(update, "write_verdicts", lambda payload: db["written"].extend(payload))
    db["waiting"] = {1, 2}                       # the nightly run scored 3 since the export
    answer = '{"results": [{"id": 1, "reason": "New chair."}, {"id": 99, "reason": "invented"}]}'
    summary = stages.relevance_import(answer, sent, "gemini-3.8-flash", False, clipboard.parse)
    assert {(r["id"], r["relevant"]) for r in db["written"]} == {(1, True), (2, False)}
    assert "left alone" in summary and "99" in summary


def test_a_relevance_prompt_of_more_than_a_hundred_says_the_nightly_job_would_split_it(db, monkeypatch):
    import src.job1_relevance.fetch as fetch
    monkeypatch.setattr(fetch, "fetch_unscored_articles", lambda limit=None: [{"id": i, "title": "t"} for i in range(150)])
    assert "--limit 100" in stages.relevance_export(None)[2]


def test_extraction_reads_each_page_politely_and_writes_each_answered_article(db, monkeypatch):
    import src.job2_extraction.fetch as fetch
    import src.job2_extraction.scraper as scraper
    import src.job2_extraction.update as update
    articles = [{"id": 1, "url": "https://www.beritaharian.sg/singapura/a", "title": "Masjid dibuka", "pubDate": "2026-10-18"},
                {"id": 2, "url": "https://www.beritaharian.sg/singapura/b", "title": "Lain", "pubDate": "2026-10-18"},
                {"id": 3, "url": "https://example.sg/gone", "title": "Gone", "fetch_attempts": 1}]
    monkeypatch.setattr(fetch, "fetch_unextracted_articles", lambda limit=None: articles)
    pauses = []
    monkeypatch.setattr(stages.time, "sleep", pauses.append)

    def scrape(url):
        if "gone" in url:
            raise scraper.ScrapeError("404")
        return f"text of {url}"
    monkeypatch.setattr(scraper, "scrape", scrape)
    failures = []
    monkeypatch.setattr(update, "record_fetch_failure", lambda i, attempts, err: failures.append((i, attempts)))
    prompt, sent, what = stages.extraction_export(None)
    assert sent == {"ids": [1, 2]} and failures == [(3, 1)]
    assert "=== ARTICLE 1 ===\nPublished: 2026-10-18\nMasjid dibuka" in prompt and "=== ARTICLE 2 ===" in prompt
    assert len(pauses) == 1                      # the second Berita Harian page waited for the first
    assert '"articles"' in prompt.split("JSON schema")[-1]

    saved = {}
    monkeypatch.setattr(update, "save", lambda article_id, rows: saved.__setitem__(article_id, rows))
    monkeypatch.setattr(update, "column_exists", lambda table, column: True)    # the role column; no database
    db["waiting"] = {1, 2}
    answer = json.dumps({"articles": [{"article_id": 1, "entities": [ENTITY]}]})   # article 2 left out
    summary = stages.extraction_import(answer, sent, "gemini-3.8-flash", False, clipboard.parse)
    assert list(saved) == [1] and saved[1][0]["entity_name_en"] == "Al-Islah Mosque"
    assert "not in the answer" in summary and "[2]" in summary


def test_matching_checks_each_match_against_the_records_that_entity_was_shown(db, monkeypatch):
    import src.job3_resolution.candidates as candidates
    import src.job3_resolution.fetch as fetch
    import src.job3_resolution.update as update
    e1 = {"id": 11, "article_id": 1, "entity_name": "Masjid Al-Islah", "entity_name_en": "Al-Islah Mosque",
          "entity_type": "ORGANISATION", "summary": "s", "evidence": "e", "fields": {}}
    e2 = {**e1, "id": 21, "article_id": 2, "entity_name": "Muis"}
    monkeypatch.setattr(fetch, "fetch_unresolved", lambda limit_articles=None: [
        {"article_id": 1, "title": "Masjid dibuka", "year": 2026, "entities": [e1]},
        {"article_id": 2, "title": "Muis", "year": 2026, "entities": [e2]}])
    offered = {11: [{"canonical_uid": "uid-mosque", "canonical_name": "Masjid Al-Islah", "canonical_fields": {}}], 21: []}
    monkeypatch.setattr(candidates, "candidates_for", lambda e, year=None: offered[e["id"]])
    prompt, sent, what = stages.matching_export(None)
    assert '"article_id": 1' in prompt and "uid-mosque" in prompt and "SEVERAL ARTICLES" in prompt

    saved = []
    monkeypatch.setattr(update, "save", lambda ids, rows: saved.append((ids, rows)))
    db["waiting"] = {11}                          # article 2's entity was resolved by the nightly run
    match = {"article_entity_name": "Masjid Al-Islah", "entity_type": "ORGANISATION", "resolution_action": "MATCH_AND_UPDATE",
             "matched_id": "uid-mosque", "confidence": "high", "reasoning": "Same mosque.", "field_updates": []}
    answer = json.dumps({"articles": [{"article_id": 1, "resolutions": [match]}, {"article_id": 2, "resolutions": []}]})
    summary = stages.matching_import(json.dumps(json.loads(answer)), json.loads(json.dumps(sent)), "m", False, clipboard.parse)
    assert len(saved) == 1 and saved[0][0] == [11]
    assert saved[0][1][0]["resolution_action"] == "MATCH_AND_UPDATE" and saved[0][1][0]["matched_uid"] == "uid-mosque"
    assert "1 matches" in summary and "left alone" in summary


@pytest.fixture
def desk(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DIR", tmp_path)
    clip = {"held": None}
    monkeypatch.setattr(clipboard, "copy", lambda path: clip.__setitem__("held", path.read_text(encoding="utf-8")) or True)
    monkeypatch.setattr(clipboard, "paste", lambda: clip["held"])
    calls = {}
    monkeypatch.setitem(cli.STAGES, "relevance", (
        lambda limit: ("PROMPT for 2 articles", {"ids": [1, 2]}, "2 unscored articles"),
        lambda text, sent, model, dry_run, parse: calls.update(text=text, model=model, dry_run=dry_run) or "2 verdicts",
        "relevance"))
    return {"dir": tmp_path, "clip": clip, "calls": calls}


def test_export_then_import_from_the_clipboard_and_the_work_is_filed_as_done(desk, capsys):
    assert cli.main(["relevance", "export"]) == 0
    assert desk["clip"]["held"] == "PROMPT for 2 articles" and (desk["dir"] / "relevance.json").exists()
    assert cli.main(["relevance", "import"]) == 1               # the prompt is still on the clipboard
    assert "still holds the prompt" in capsys.readouterr().out
    desk["clip"]["held"] = '{"results": []}'
    assert cli.main(["relevance", "import", "--model", "gemini-3.5-flash"]) == 0
    assert desk["calls"] == {"text": '{"results": []}', "model": "gemini-3.5-flash", "dry_run": False}
    assert not (desk["dir"] / "relevance.json").exists()
    assert sorted(p.name.split("-", 1)[0] for p in (desk["dir"] / "done").iterdir()) == ["relevance"] * 3
    assert cli.main(["relevance", "import"]) == 1                # nothing left to import


def test_a_dry_run_import_writes_nothing_and_keeps_the_export(desk, capsys):
    cli.main(["relevance", "export"])
    desk["clip"]["held"] = '{"results": []}'
    assert cli.main(["relevance", "import", "--dry-run"]) == 0
    assert desk["calls"]["dry_run"] is True and (desk["dir"] / "relevance.json").exists()


def test_an_answer_cut_short_says_to_export_fewer(desk, capsys, monkeypatch):
    monkeypatch.setitem(cli.STAGES, "relevance", (cli.STAGES["relevance"][0], stages.relevance_import, "relevance"))
    cli.main(["relevance", "export"])
    desk["clip"]["held"] = '{"results": [{"id": 1, "reason": "cut off'
    assert cli.main(["relevance", "import"]) == 1
    assert "nothing was written" in capsys.readouterr().out
