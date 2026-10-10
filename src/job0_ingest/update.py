"""Read `rss_feeds`, write `article`."""

from datetime import datetime, timedelta, timezone

from src.shared.pagination import fetch_all
from src.shared.stories import find_copies
from src.shared.supabase_client import column_exists, get_client

# How far back a copy arriving now is looked for. The copies the twice-daily
# ingest has made arrived within a day of the first; a week is room to spare.
RECENT = timedelta(days=7)


def fetch_feeds() -> list[dict]:
    """Every configured feed, in the order `rss_feeds.id` gives them."""
    return (get_client().from_("rss_feeds").select("id, source, url")
            .order("id").execute().data or [])


def recent_articles() -> list[dict]:
    """The articles stored in the last week: what an article arriving now could be a copy of."""
    since = (datetime.now(timezone.utc) - RECENT).isoformat()
    columns = "id,url,title,pubDate,created_at" + (",duplicate_of" if column_exists("article", "duplicate_of") else "")
    return fetch_all(lambda: get_client().from_("article").select(columns).gte("created_at", since))


def title_uses(_outlet: str, title: str) -> int:
    """On how many different days stored articles carry this title: a column's title comes back day after day."""
    if not title:
        return 0
    rows = get_client().from_("article").select("pubDate").eq("title", title).limit(1000).execute().data or []
    return len({(r.get("pubDate") or "")[:10] for r in rows})


def _row(a: dict) -> dict:
    return {
        "url": a["url"],
        "title": a.get("title") or a["url"],
        "description": a.get("description"),
        "category": a.get("category"),
        "pubDate": a.get("pubDate"),
        "relevant": None,
        "reason": None,
        "processed_extraction": False,
    }


def insert_new_articles(articles: list[dict], known: list[dict] | None = None) -> dict:
    """
    Insert the articles whose url is not in `article` yet; leave the rest alone.

    A new row must say it is unscored: the live `article.relevant` defaults to
    false, not NULL, and Job 1's queue is `relevant IS NULL`. Leaving the
    column out (an earlier version did) files every new article as already
    judged not relevant, and Job 1 never sees it. Sending the values only on
    insert is what `ignore_duplicates` gives: an article already seen keeps
    whatever Job 1 or Job 2 has done to it, and is not rewritten at all.

    An article that is a story already stored at another address
    (`src/shared/stories.py`) is stored too, so the next run knows its url, but
    as already judged: `relevant` false and the reason naming the first one, so
    no job works on it twice. `known` are the stored articles to check against;
    the last week's are read when it is not given.
    """
    if not articles:
        return {"attempted": 0, "inserted": 0, "copies": 0, "error": None}
    try:
        if known is None:
            known = recent_articles()
        copies = find_copies(articles, known, uses=title_uses)
    except Exception as exc:
        # The check failing must not stop the news coming in: store everything, as before, and say so.
        print(f"    could not check for copies, storing every article as new -- {exc}")
        known, copies = known or [], {}
    linked = column_exists("article", "duplicate_of")

    try:
        table = get_client().from_("article")
        result = table.upsert([_row(a) for a in articles if a["url"] not in copies],
                              on_conflict="url", ignore_duplicates=True).execute()
        written = result.data or []
        ids = {a["url"]: a["id"] for a in known} | {r["url"]: r.get("id") for r in written}
        later = []
        for a in articles:
            if a["url"] not in copies:
                continue
            original, why = copies[a["url"]]
            first = original if isinstance(original, int) else ids.get(original)
            if first is None:
                # The first one arrived in this run but was not written now (already stored by url): store this as itself.
                later.append(_row(a))
                continue
            row = _row(a) | {"relevant": False, "reason": f"Same story as article {first}: {why}."}
            if linked:
                row["duplicate_of"] = first
            later.append(row)
        if later:
            written += get_client().from_("article").upsert(later, on_conflict="url", ignore_duplicates=True).execute().data or []
        marked = {r["url"] for r in later if r["relevant"] is False}
        return {"attempted": len(articles), "inserted": len(written),
                "copies": sum(1 for r in written if r["url"] in marked), "error": None}
    except Exception as exc:
        return {"attempted": len(articles), "inserted": 0, "copies": 0, "error": str(exc)}
