"""Write relevance verdicts back to Supabase."""

from src.shared.supabase_client import get_client

RPC = "update_article_relevance_batch"


def build_payload(articles: list[dict], relevant: dict[int, str]) -> list[dict]:
    """
    Turn an inclusion-only LLM result into a full verdict for every article.

    The prompt returns only the articles it judged relevant. Everything else in
    the batch is therefore not relevant, which is what makes a single write
    possible: `relevant` maps id -> reason for the ones that made the cut.
    """
    return [
        {
            "id": article["id"],
            "relevant": article["id"] in relevant,
            "reason": relevant.get(article["id"]),
        }
        for article in articles
    ]


def write_verdicts(payload: list[dict]) -> None:
    """Send one batch of verdicts through the update RPC."""
    if not payload:
        return
    get_client().rpc(RPC, {"rows": payload}).execute()
