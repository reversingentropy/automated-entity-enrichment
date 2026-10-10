"""Pull the articles that still need a relevance verdict."""

from src.shared.pagination import fetch_all
from src.shared.supabase_client import column_exists, get_client

TABLE = "article"

# `relevant IS NULL` is the work queue: NULL means "not yet scored". Once a row
# is written as True or False it drops out of this query permanently.
UNSCORED_COLUMNS = "id, url, title, description"


def fetch_unscored_articles(limit: int | None = None) -> list[dict]:
    """
    Return articles awaiting a relevance verdict, oldest id first.

    `limit` caps how many are returned, for testing against a small batch
    without spending the day's request budget on the whole backlog.

    Both `title` and `description` are sent to the model: the relevance
    prompt is written around a headline, and the description alone often
    omits the change being reported.
    """
    query = (
        get_client()
        .from_(TABLE)
        .select(UNSCORED_COLUMNS)
        .is_("relevant", None)
    )
    # The historical backfill is scored elsewhere; see sql/09.
    if column_exists(TABLE, "backfill"):
        query = query.eq("backfill", False)
    query = (
        query
        .order("id")  # ordered server-side so `limit` is deterministic
    )

    if limit is not None:
        query = query.limit(limit)

    return query.execute().data or []
