"""Pull unresolved extracted entities, grouped by the article they came from."""

from collections import defaultdict

from src.shared.pagination import fetch_all
from src.shared.supabase_client import column_exists, get_client

TABLE = "extracted_entities"
ARTICLE_TABLE = "article"

QUEUE_COLUMNS = (
    "id, article_id, entity_name, entity_name_en, entity_type, "
    "summary, evidence, fields"
)


def fetch_unresolved(limit_articles: int | None = None) -> list[dict]:
    """
    Return unresolved entities grouped by article.

    Job 3 resolves a whole article at once: entities from the same article are
    mutually informative, and one call is far cheaper than one per entity.
    """
    flagged = column_exists(TABLE, "backfill")

    def build():
        q = get_client().from_(TABLE).select(QUEUE_COLUMNS).eq("resolved", False)
        if flagged:  # the historical backfill is resolved elsewhere; sql/09
            q = q.eq("backfill", False)
        return q.order("article_id")

    rows = fetch_all(build)

    grouped: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["article_id"]].append(row)

    article_ids = sorted(grouped)
    if limit_articles is not None:
        article_ids = article_ids[:limit_articles]

    titles = _titles_for(article_ids)
    return [
        {"article_id": aid, "title": titles.get(aid, ("", None))[0],
         "year": titles.get(aid, ("", None))[1], "entities": grouped[aid]}
        for aid in article_ids
    ]


def _titles_for(article_ids: list[int]) -> dict[int, tuple[str, int | None]]:
    """
    Title and year per article. The title gives the model context; the year
    lets retrieval drop candidates who died before the story happened.
    """
    if not article_ids:
        return {}
    titles: dict[int, tuple[str, int | None]] = {}
    for start in range(0, len(article_ids), 200):
        chunk = article_ids[start:start + 200]
        rows = (
            get_client()
            .from_(ARTICLE_TABLE)
            .select("id, title, pubDate")
            .in_("id", chunk)
            .execute()
            .data
            or []
        )
        for r in rows:
            year = str(r.get("pubDate") or "")[:4]
            titles[r["id"]] = (r["title"] or "", int(year) if year.isdigit() else None)
    return titles
