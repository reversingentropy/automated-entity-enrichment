"""Pull the relevant articles that still need entity extraction."""

from src.shared.pagination import fetch_all
from src.shared.supabase_client import column_exists, get_client

TABLE = "article"

# Job 2's work queue: Job 1 judged the article relevant, and extraction has not
# been done yet. `processed_extraction` only flips to True once entities are
# safely inserted, so a failed run leaves the article here for the next one.
# `text` is only ever present on a row someone filled by hand; the job fetches
# the page itself and does not keep it.
QUEUE_COLUMNS = "id, url, title, text, pubDate"
FETCH_COLUMNS = ", fetch_error, fetch_attempts"   # sql/06
MAX_ATTEMPTS = 3


def fetch_unextracted_articles(limit: int | None = None) -> list[dict]:
    """Return relevant articles awaiting extraction, oldest id first."""
    tracked = column_exists(TABLE, "fetch_attempts")
    columns = QUEUE_COLUMNS + (FETCH_COLUMNS if tracked else "")

    flagged = column_exists(TABLE, "backfill")

    def build():
        q = (
            get_client()
            .from_(TABLE)
            .select(columns)
            .eq("relevant", True)
            .eq("processed_extraction", False)
        )
        if flagged:  # the historical backfill is extracted elsewhere; sql/09
            q = q.eq("backfill", False)
        return q.order("id")

    def readable(rows: list[dict]) -> list[dict]:
        # A page that could not be fetched three times is not work for this
        # job. Before the count existed such rows failed again every night.
        # Filtered here rather than in the query so the job still runs before
        # sql/06 has been applied.
        return [r for r in rows if r.get("text") or (r.get("fetch_attempts") or 0) < MAX_ATTEMPTS]

    if limit is not None:
        return readable(build().limit(limit).execute().data or [])
    return readable(fetch_all(build))
