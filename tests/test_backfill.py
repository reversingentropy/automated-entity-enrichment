"""Offline tests for the archive collectors: parsing only, no network."""

from src.backfill import cna, sitemaps
from src.backfill.months import bounds, label, span


def test_month_span_is_inclusive_and_crosses_years():
    assert span("2024-11", "2025-02") == [(2024, 11), (2024, 12), (2025, 1), (2025, 2)]
    assert label(2015, 1) == "2015-01"
    a, b = bounds(2024, 2)
    assert b - a == 29 * 86400 - 1          # leap February, last second inclusive


def test_sitemap_parse_keeps_only_the_singapore_section():
    xml = """<urlset>
      <url><loc>https://www.straitstimes.com/singapore/some-story</loc><lastmod>2024-06-03T01:02:03+08:00</lastmod></url>
      <url><loc>https://www.straitstimes.com/world/other-story</loc></url>
      <url><loc>https://www.straitstimes.com/singapore/politics/third</loc></url>
    </urlset>"""
    rows = sitemaps.parse(xml, "st", 2024, 6)
    assert [r["url"].rsplit("/", 1)[1] for r in rows] == ["some-story", "third"]
    assert rows[0]["published"] == "2024-06-03" and rows[0]["month"] == "2024-06"
    assert rows[0]["title"] is None            # a sitemap never carries one


def test_zaobao_parse_uses_its_own_section_path():
    xml = """<urlset>
      <url><loc>https://www.zaobao.com.sg/news/singapore/story20240701-3979431</loc></url>
      <url><loc>https://www.zaobao.com.sg/entertainment/story20240701-1</loc></url>
    </urlset>"""
    assert len(sitemaps.parse(xml, "zb", 2024, 7)) == 1


def test_page_metadata_prefers_open_graph_and_unescapes():
    html = """<html><head>
      <title>Fallback &amp; ignored</title>
      <meta property="og:title" content="Court taps AI &amp; helps litigants">
      <meta name="description" content="Plain description">
      <script>{"datePublished": "2024-07-01T07:00:00+08:00"}</script>
    </head></html>"""
    m = sitemaps.meta_from(html)
    assert m == {"title": "Court taps AI & helps litigants",
                 "description": "Plain description",
                 "published": "2024-07-01"}


def test_cna_hit_becomes_a_row_without_its_body():
    hit = {"title": " True Fitness to close ", "brief": "Parent cites costs",
           "link_absolute": "https://www.channelnewsasia.com/singapore/true-fitness-6377486",
           "field_release_date": 1789091040,
           "paragraph_text": ["SINGAPORE: True Fitness...", "It said..."]}
    r = cna.row(hit, 2026, 9)
    assert r["title"] == "True Fitness to close"
    assert r["published"] == "2026-09-11" and r["month"] == "2026-09"
    assert "paragraph_text" not in r and "text" not in r
    assert cna.body(hit).startswith("SINGAPORE: True Fitness")
    assert cna.row({"title": "no link"}, 2026, 9) is None


def test_csv_writer_rolls_files_and_resumes(tmp_path):
    from src.backfill import csvout
    from src.backfill.csvout import Writer

    csvout.ROWS_PER_FILE = 3        # small, for the test
    row = lambda i: {"url": f"https://x/{i}", "source": "st", "title": f"t{i}",
                     "description": None, "category": "singapore", "published": None, "month": "2024-06"}
    w = Writer(tmp_path, "st")
    assert all(w.write(row(i)) for i in range(5))
    w.close()
    assert sorted(p.name for p in tmp_path.glob("*.csv")) == ["st-001.csv", "st-002.csv"]

    # A second run skips what is on disk and continues the open file.
    w2 = Writer(tmp_path, "st")
    assert w2.written == 5
    assert w2.write(row(2)) is False
    assert w2.write(row(5)) is True
    w2.close()
    text = (tmp_path / "st-002.csv").read_text(encoding="utf-8-sig")
    assert text.count("\n") == 4             # header + 3 rows, not a second header
    csvout.ROWS_PER_FILE = 50_000


def test_section_comes_from_the_url_path():
    from src.backfill.sitemaps import section
    assert section("https://www.straitstimes.com/singapore/politics/some-slug") == "singapore/politics"
    assert section("https://www.zaobao.com.sg/news/singapore/story20240701-3979431") == "news/singapore"
    assert section("https://www.straitstimes.com/singapore/slug-only") == "singapore"


def test_the_straits_times_slug_is_the_headline():
    from src.backfill.sitemaps import slug_title
    assert slug_title("https://www.straitstimes.com/singapore/singaporean-man-arrested-in-vietnam?ai-allowed=1") \
        == "Singaporean man arrested in vietnam"
    assert slug_title("https://www.straitstimes.com/singapore/") == "Singapore"


def test_internal_prompts_stand_alone():
    """Nothing injected at call time, nothing enforced afterwards: it all has to be in the text."""
    from src.backfill.prompts import extraction, relevance

    r = relevance()
    assert '"relevant": false' in r and "Every input id appears exactly once" in r
    assert "A knowledge base update is needed" in r          # the pipeline's own criteria
    assert "{" not in r.replace("{{", "").replace("}}", "").split("OUTPUT")[0]  # no leftover placeholders

    e = extraction()
    assert "{field_rules}" not in e and "ALLOWED FIELDS" in e   # brief injected
    assert "OCCUPATIONS THESAURUS" in e and "CONTROLLED VOCABULARIES" in e
    assert "Affiliations(groupName)" in e                       # the exact stored name
    assert e.rstrip().endswith("Article:")


def test_cna_body_survives_the_character_list_encoding():
    from src.backfill.cna import body, opening, row
    chars = {"paragraph_text": list("SINGAPORE: A taxi driver found a wallet. He returned it the same day.")}
    assert body(chars).startswith("SINGAPORE: A taxi driver")
    paras = {"paragraph_text": ["First paragraph.", "Second."]}
    assert body(paras) == "First paragraph.\n\nSecond."
    # a description is cut at a sentence end, not mid-word
    long = "One sentence here. " * 30
    d = opening(long, limit=60)
    assert d.endswith(".") and len(d) <= 60
    # and used when the index has no brief
    r = row({"link_absolute": "https://www.channelnewsasia.com/singapore/x-1",
             "field_release_date": 1789091040, **chars}, 2026, 9)
    assert r["description"].startswith("SINGAPORE: A taxi driver")


def test_scraper_extraction_is_reusable_without_the_length_check():
    from src.job2_extraction.scraper import text_from
    html = "<html><nav>menu</nav><p>One.</p><script>x()</script><p>Two  words.</p></html>"
    assert text_from(html) == "One. Two words."


def test_ingest_parser_names_each_failure():
    """
    The internal model answered in four shapes. Only the schema's own is
    written; the rest are counted by kind so the re-run list can be built
    from the counts rather than the guesses.
    """
    from src.backfill.ingest import parse
    good = '{"entities": [{"entity_name": "Ee, Gerard", "entity_type": "PERSON", "summary": "s", "evidence": "e", "fields": {"Occupation": "Accountant"}}]}'
    assert parse(good)[0].entities[0].entity_name == "Ee, Gerard"
    assert parse("```json\n" + good + "\n```")[0] is not None            # fences stripped
    assert parse("Article published 23/2/2015. Key entities: 1. T")[1] == "prose, not JSON"
    assert parse('{"article_id": "x", "title": "t", "text": "..."}')[1] == "echoed the input, no entities list"
    assert parse('{"entities": [{"entity_name": "A", "entity_type": "PERSON"}]}')[1] == "entities lack summary or evidence"
    assert parse("")[1] == "empty"
    # the list without its wrapper is the same answer; an answer cut off by an
    # output limit is named as such, since it is not the model's prose
    bare = good[len('{"entities": '):-1]
    assert parse(bare)[0].entities[0].entity_name == "Ee, Gerard"
    assert parse(good[:40])[1] == "JSON cut off"


def test_resolution_prompt_for_the_internal_model_stands_alone():
    from src.backfill.prompts import resolution
    r = resolution()
    assert "{field_rules}" not in r and "{description_style}" not in r and "{notability}" not in r
    assert "{article_entities}" not in r
    assert '{"resolutions":' in r and r.rstrip().endswith("ENTITIES:")


def test_resolution_answers_are_parsed_or_named():
    from src.backfill.resolve import parse
    ok = '{"resolutions": []}'
    assert parse(ok)[0] is not None and parse("```json\n" + ok + "\n```")[0] is not None
    assert parse("Let me analyse each entity.")[1] == "prose, not JSON"
    assert parse('{"entities": []}')[1].startswith("schema:")
    one = ('{"article_entity_name": "A", "entity_type": "PERSON", "resolution_action": "CREATE_NEW", '
           '"matched_id": null, "confidence": "high", "reasoning": "r", "field_updates": []}')
    assert parse("[" + one + "]")[0].resolutions[0].resolution_action == "CREATE_NEW"   # bare array
    assert parse('{"resolutions": [' + one[:30])[1] == "JSON cut off"


def test_local_trigram_matching_reproduces_pg_trgm():
    """
    pg_trgm: lower-case, split on non-word characters, pad each word with
    two spaces before and one after, three-grams, shared over union.
    """
    from src.backfill.local_match import Index, trigrams
    assert trigrams("ab") == {"  a", " ab", "ab "}
    ents = [
        {"uid": "1", "name": "Ee, Gerard", "entity_type": "PERSON", "is_active": True, "canonical_uid": None, "fields": {"Occupation": "Accountant"}},
        {"uid": "2", "name": "Clarke, Gerard", "entity_type": "PERSON", "is_active": True, "canonical_uid": None, "fields": {}},
        {"uid": "3", "name": "Gerard Ee", "entity_type": "PERSON", "is_active": True, "canonical_uid": "1", "fields": {}},  # a variant pointing at 1
        {"uid": "4", "name": "Ee, Gerard", "entity_type": "ORGANISATION", "is_active": True, "canonical_uid": None, "fields": {}},
        {"uid": "5", "name": "Ee, Gerard", "entity_type": "PERSON", "is_active": False, "canonical_uid": None, "fields": {}},
    ]
    idx = Index(ents)
    got = idx.match("Gerard Ee", 5, "PERSON")
    assert got[0]["canonical_uid"] == "1"                       # the variant resolves to its canonical
    assert got[0]["canonical_fields"] == {"Occupation": "Accountant"}
    assert all(r["canonical_type"] == "PERSON" for r in got)    # type filter
    assert "5" not in {r["matched_uid"] for r in got}           # retired records never offered
    assert 0 < got[-1]["similarity"] < got[0]["similarity"] <= 1


def test_dashboard_files_roll_under_the_size_cap_and_null_is_empty(tmp_path):
    """The importer stops at about 10 MB and reads an empty cell as NULL."""
    from src.backfill import dashboard
    dashboard_max = dashboard.MAX_BYTES
    dashboard.MAX_BYTES = 400
    try:
        rows = [{"a": i, "b": None, "c": {"k": "v" * 50}, "d": True} for i in range(10)]
        files = dashboard.write_parts(tmp_path, "x", ["a", "b", "c", "d"], rows)
    finally:
        dashboard.MAX_BYTES = dashboard_max
    assert len(files) > 1 and sum(n for _, n in files) == 10
    for path, _ in files:
        assert path.stat().st_size <= 400 + 100                      # one row may overhang
        text = path.read_text(encoding="utf-8")
        assert text.startswith("a,b,c,d\n") and ",,\"{\"\"k\"\"" in text and ",True" in text


def test_the_archive_file_uses_the_reviewers_template_with_nobody_named():
    from src.backfill.proposals import rows_from

    entities = {1: {"id": 1, "entity_name": "Kenneth Jeyaretnam", "entity_type": "PERSON"},
                2: {"id": 2, "entity_name": "Amos Yee", "entity_type": "PERSON",
                    "fields": {"Name": "Amos Yee", "Birth Year (yyyy)": "1998"}},
                3: {"id": 3, "entity_name": "Tan Wei", "entity_type": "PERSON"}}
    records = {"18518926": {"uid": "18518926", "name": "Jeyaretnam, Kenneth", "entity_type": "PERSON",
                            "fields": {"Awards": "A (2001)"}}}
    rows = [{"extracted_id": 1, "resolution_action": "MATCH_AND_UPDATE", "matched_uid": "18518926",
             "field_updates": [{"field": "Death Year (yyyy)", "strategy": "REPLACE", "value": "2026"},
                               {"field": "Awards", "strategy": "APPEND", "value": "B (2026)"}]},
            {"extracted_id": 2, "resolution_action": "CREATE_NEW", "matched_uid": None, "field_updates": []},
            {"extracted_id": 3, "resolution_action": "FLAG_AMBIGUOUS", "matched_uid": None, "field_updates": []}]
    import datetime as dt

    day = dt.date(2026, 9, 28)
    existing, new, skipped = rows_from(rows, entities, "https://x", day, records, {"PERSON": "_People"})
    assert existing == [
        ["18518926", "Jeyaretnam, Kenneth", "_People", "Death Year (yyyy)", "", "2026", "https://x", day, "", "", ""],
        ["18518926", "Jeyaretnam, Kenneth", "_People", "Awards", "A (2001)", "A (2001) | B (2026)", "https://x", day, "", "", ""]]
    assert new == [["", "Amos Yee", "_People", "Birth Year (yyyy)", "", "1998", "https://x", day, "", "", ""]]
    assert skipped == {"FLAG_AMBIGUOUS": 1}
