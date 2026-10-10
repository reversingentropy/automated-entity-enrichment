"""Job 0: RSS/Atom parsing, pure and offline."""

from src.job0_ingest.parse import (
    detect_language, extract_description, parse_feed, parse_pubdate, strip_tags)
from src.job0_ingest.update import insert_new_articles

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>CNA Singapore</title>
    <item>
      <title>NCSS names new chair</title>
      <link>https://www.channelnewsasia.com/singapore/ncss-chair-123</link>
      <guid>https://www.channelnewsasia.com/singapore/ncss-chair-123</guid>
      <pubDate>Sat, 01 Aug 2026 09:00:00 GMT</pubDate>
      <description>&lt;p&gt;Gregory Vijayendran begins his term.&lt;/p&gt;</description>
      <category>Singapore</category>
      <category>Social Service</category>
    </item>
    <item>
      <title>No link item</title>
      <guid>https://www.channelnewsasia.com/singapore/no-link-456</guid>
      <pubDate>Sat, 01 Aug 2026 10:00:00 GMT</pubDate>
      <description>Falls back to guid.</description>
    </item>
    <item>
      <title>Empty item</title>
    </item>
  </channel>
</rss>
"""

ZAOBAO_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>移民与关卡局新措施</title>
      <link>https://rsshub.rss3.workers.dev/zaobao/znews/singapore/article-1</link>
      <pubDate>Mon, 22 Aug 2026 01:00:00 GMT</pubDate>
      <description>&lt;div&gt;boilerplate&lt;/div&gt;&lt;p&gt;新措施将统一自动化和非自动化通道的离境程序。&lt;/p&gt;&lt;div&gt;footer&lt;/div&gt;</description>
    </item>
  </channel>
</rss>
"""

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>An Atom entry</title>
    <link rel="alternate" href="https://example.com/atom-1"/>
    <id>urn:uuid:1</id>
    <published>2026-08-01T09:00:00Z</published>
  </entry>
</feed>
"""

UNKNOWN = "<not-a-feed><thing/></not-a-feed>"


def test_rss_items_become_article_rows():
    result = parse_feed(RSS, "https://www.channelnewsasia.com/api/v1/rss-outbound-feed")
    assert result["mode"] == "rss"
    assert result["items_found"] == 3
    urls = [a["url"] for a in result["articles"]]
    assert "https://www.channelnewsasia.com/singapore/ncss-chair-123" in urls
    first = result["articles"][0]
    assert first["title"] == "NCSS names new chair"
    assert first["description"] == "Gregory Vijayendran begins his term."
    assert first["category"] == "Singapore, Social Service"
    assert first["pubDate"] == "2026-08-01T09:00:00+00:00"


def test_missing_link_falls_back_to_guid():
    result = parse_feed(RSS, "https://www.channelnewsasia.com/api/v1/rss-outbound-feed")
    fallback = next(a for a in result["articles"] if "no-link-456" in a["url"])
    assert fallback["url"] == "https://www.channelnewsasia.com/singapore/no-link-456"


def test_item_with_no_url_is_dropped():
    result = parse_feed(RSS, "https://www.channelnewsasia.com/api/v1/rss-outbound-feed")
    # Three items in the feed, but the one with neither link nor guid has no
    # url and must not become an article row.
    assert result["items_found"] == 3
    assert result["after_filter"] == 2
    assert all(a["url"] for a in result["articles"])


def test_zaobao_feed_is_detected_as_chinese_and_unwrapped():
    feed_url = "https://rsshub.rss3.workers.dev/zaobao/znews/singapore"
    assert detect_language(feed_url) == "chinese"
    result = parse_feed(ZAOBAO_RSS, feed_url)
    # The boilerplate div before and after the real <p> must not survive.
    assert result["articles"][0]["description"] == "新措施将统一自动化和非自动化通道的离境程序。"


def test_english_feeds_are_not_flagged_chinese():
    assert detect_language("https://www.straitstimes.com/news/singapore/rss.xml") == "english"
    assert detect_language("https://www.channelnewsasia.com/api/v1/rss-outbound-feed") == "english"


def test_english_description_just_strips_tags():
    assert extract_description("<b>Bold</b> and plain", "english") == "Bold and plain"


def test_missing_description_is_none():
    assert extract_description(None, "english") is None
    assert extract_description("", "chinese") is None


def test_atom_feed_uses_link_href_and_id_fallback():
    result = parse_feed(ATOM, "https://example.com/feed.atom")
    assert result["mode"] == "atom"
    assert result["articles"] == [
        {"url": "https://example.com/atom-1", "title": "An Atom entry",
         "description": None, "category": None, "pubDate": "2026-08-01T09:00:00+00:00"}
    ]


def test_unrecognised_document_yields_no_articles():
    result = parse_feed(UNKNOWN, "https://example.com/whatever")
    assert result == {"mode": "unknown", "items_found": 0, "after_filter": 0, "articles": []}


def test_strip_tags_returns_none_for_tags_only():
    assert strip_tags("<div></div>") is None


def test_parse_pubdate_handles_rfc822_and_iso8601():
    assert parse_pubdate("Sat, 01 Aug 2026 09:00:00 GMT") == "2026-08-01T09:00:00+00:00"
    assert parse_pubdate("2026-08-01T09:00:00Z") == "2026-08-01T09:00:00+00:00"
    assert parse_pubdate(None) is None
    assert parse_pubdate("not a date") is None


class FakeTable:
    """Captures what an insert would have sent, without a network."""

    def __init__(self, captured):
        self.captured = captured

    def upsert(self, payload, on_conflict=None, ignore_duplicates=False):
        self.captured["payload"] = payload
        self.captured.setdefault("payloads", []).append(payload)
        self.captured["on_conflict"] = on_conflict
        self.captured["ignore_duplicates"] = ignore_duplicates
        return self

    def execute(self):
        # the database gives each new row its id
        n = len(self.captured["payloads"])
        return type("R", (), {"data": [dict(r, id=1000 * n + i) for i, r in enumerate(self.captured["payload"])]})


class FakeClient:
    def __init__(self, captured):
        self.captured = captured

    def from_(self, table):
        assert table == "article"
        return FakeTable(self.captured)


def test_a_new_article_is_explicitly_unscored(monkeypatch):
    # The live article.relevant defaults to false, not NULL, and Job 1's queue
    # is `relevant IS NULL`. A row inserted without saying so is filed as
    # already judged not relevant and is never scored. The values have to be
    # in the payload, not left to the column defaults.
    import src.job0_ingest.update as u
    captured: dict = {}
    monkeypatch.setattr(u, "get_client", lambda: FakeClient(captured))

    monkeypatch.setattr(u, "column_exists", lambda table, column: False)
    result = insert_new_articles([
        {"url": "https://example.com/a", "title": "A", "description": "d",
         "category": "Singapore", "pubDate": "2026-08-01T09:00:00+00:00"},
    ], known=[])

    assert result == {"attempted": 1, "inserted": 1, "copies": 0, "error": None}
    row = captured["payload"][0]
    assert row["url"] == "https://example.com/a"
    assert row["relevant"] is None
    assert row["reason"] is None
    assert row["processed_extraction"] is False


def test_an_article_already_stored_is_not_rewritten(monkeypatch):
    # The same feed item comes round again at the next run. It must keep the
    # verdict Job 1 gave it, and the entities Job 2 took from it: the write is
    # insert-or-ignore on url, never insert-or-overwrite.
    import src.job0_ingest.update as u
    captured: dict = {}
    monkeypatch.setattr(u, "get_client", lambda: FakeClient(captured))

    monkeypatch.setattr(u, "column_exists", lambda table, column: False)
    insert_new_articles([{"url": "https://example.com/a", "title": "A"}], known=[])

    assert captured["on_conflict"] == "url"
    assert captured["ignore_duplicates"] is True


def test_inserting_no_articles_touches_nothing(monkeypatch):
    import src.job0_ingest.update as u

    def boom():
        raise AssertionError("get_client() should not be called with no articles")

    monkeypatch.setattr(u, "get_client", boom)
    assert insert_new_articles([]) == {"attempted": 0, "inserted": 0, "copies": 0, "error": None}


ST_OLD = "https://www.straitstimes.com/singapore/courts-crime/retired-police-officer-with-distinguished-career-including-sq117-hijack-response-dies-at-86"
ST_NEW = "https://www.straitstimes.com/singapore/retired-police-officer-with-distinguished-career-including-sq117-hijack-response-dies-at-86"


def test_a_story_already_stored_at_another_address_is_stored_as_judged_so_no_job_takes_it(monkeypatch):
    # 19312 and 19420: The Straits Times moved the article between the evening and the morning run, and both were
    # queued for extraction. The copy is stored, so the next run knows its url, but already judged, naming the first.
    import src.job0_ingest.update as u
    captured: dict = {}
    monkeypatch.setattr(u, "get_client", lambda: FakeClient(captured))
    monkeypatch.setattr(u, "column_exists", lambda table, column: True)
    title = "Retired police officer with distinguished career, including SQ117 hijack response, dies at 86"
    known = [{"id": 19312, "url": ST_OLD, "title": title, "pubDate": "2026-10-09T12:40:00+00:00"}]
    result = insert_new_articles([{"url": ST_NEW, "title": title, "pubDate": "2026-10-09T12:40:00+00:00"},
                                  {"url": "https://www.straitstimes.com/singapore/something-else", "title": "Something else"}], known=known)
    first, copies = captured["payloads"]
    assert [r["url"] for r in first] == ["https://www.straitstimes.com/singapore/something-else"] and first[0]["relevant"] is None
    assert copies[0]["url"] == ST_NEW and copies[0]["relevant"] is False and copies[0]["duplicate_of"] == 19312
    assert copies[0]["reason"].startswith("Same story as article 19312")
    assert result == {"attempted": 2, "inserted": 2, "copies": 1, "error": None}


def test_a_copy_arriving_with_its_first_in_one_run_points_at_the_first_once_stored(monkeypatch):
    import src.job0_ingest.update as u
    captured: dict = {}
    monkeypatch.setattr(u, "get_client", lambda: FakeClient(captured))
    monkeypatch.setattr(u, "column_exists", lambda table, column: False)     # before the SQL is run: no duplicate_of yet
    insert_new_articles([{"url": ST_OLD, "title": "T"}, {"url": ST_NEW, "title": "T"}], known=[])
    first, copies = captured["payloads"]
    assert first[0]["url"] == ST_OLD and copies[0]["reason"].startswith("Same story as article 1000:")
    assert "duplicate_of" not in copies[0] and copies[0]["relevant"] is False


def test_the_check_failing_does_not_stop_the_news_coming_in(monkeypatch):
    import src.job0_ingest.update as u
    captured: dict = {}
    monkeypatch.setattr(u, "get_client", lambda: FakeClient(captured))
    monkeypatch.setattr(u, "column_exists", lambda table, column: False)

    def broken():
        raise RuntimeError("timeout")
    monkeypatch.setattr(u, "recent_articles", broken)
    result = insert_new_articles([{"url": ST_OLD, "title": "T"}, {"url": ST_NEW, "title": "T"}])
    assert result["inserted"] == 2 and all(r["relevant"] is None for r in captured["payloads"][0])


FEEDS = [
    {"id": 1, "source": "A", "url": "https://a.example/rss"},
    {"id": 2, "source": "B", "url": "https://b.example/rss"},
    {"id": 3, "source": "C", "url": "https://c.example/rss"},
]


def _run_main(monkeypatch, get, insert):
    import src.job0_ingest.__main__ as m
    monkeypatch.setattr(m, "fetch_feeds", lambda: FEEDS)
    monkeypatch.setattr(m.httpx, "get", get)
    monkeypatch.setattr(m, "insert_new_articles", insert)
    monkeypatch.setattr(m, "recent_articles", lambda: [])
    return m.main([])


def _ok(url, headers=None, timeout=None):
    return type("R", (), {"text": RSS, "raise_for_status": lambda self: None})()


def test_one_dead_feed_does_not_stop_the_feeds_after_it(monkeypatch):
    # The Edge Function this replaces threw on the first bad feed and never
    # reached the rest. The run is still marked failed, so it is not silent.
    written = []

    def get(url, headers=None, timeout=None):
        if "b.example" in url:
            raise RuntimeError("connection reset")
        return _ok(url)

    def insert(articles, known=None):
        written.append(len(articles))
        return {"attempted": len(articles), "inserted": len(articles), "copies": 0, "error": None}

    assert _run_main(monkeypatch, get, insert) == 1
    assert len(written) == 2


def test_one_failed_write_does_not_stop_the_feeds_after_it(monkeypatch):
    results = iter([{"attempted": 2, "inserted": 0, "copies": 0, "error": "insert failed"},
                    {"attempted": 2, "inserted": 2, "copies": 0, "error": None},
                    {"attempted": 2, "inserted": 2, "copies": 0, "error": None}])
    seen = []

    def insert(articles, known=None):
        seen.append(1)
        return next(results)

    assert _run_main(monkeypatch, _ok, insert) == 1
    assert len(seen) == 3


def test_all_feeds_ok_exits_clean(monkeypatch):
    insert = lambda articles, known=None: {"attempted": len(articles), "inserted": 0, "copies": 0, "error": None}
    assert _run_main(monkeypatch, _ok, insert) == 0
