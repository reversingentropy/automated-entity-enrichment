"""Persist extracted entities and close out the article."""

from src.shared.field_names import clean_fields
from src.shared.models import ExtractionResponse
from src.shared.supabase_client import column_exists, get_client

ARTICLE_TABLE = "article"
ENTITY_TABLE = "extracted_entities"


def record_fetch_failure(article_id: int, attempts: int, error: str) -> None:
    """
    The page could not be read: say so on the row, and count it.

    Three failures and the queue leaves the article alone (fetch.py), so a
    paywalled or vanished page is not retried every night forever. The text
    itself is never stored: the pipeline keeps what it extracts, not what it
    read, and a re-extraction after a prompt change fetches the page again.
    """
    if not column_exists(ARTICLE_TABLE, "fetch_attempts"):
        return   # before sql/06: nothing to record it in
    get_client().from_(ARTICLE_TABLE).update(
        {"fetch_error": error[:500], "fetch_attempts": attempts + 1}
    ).eq("id", article_id).execute()


def build_rows(article_id: int, response: ExtractionResponse) -> list[dict]:
    """
    Flatten the model's entities into extracted_entities rows.

    Field names are corrected to the ones TTE stores. The prompt asks for exact
    names, but a near miss -- "Year Started" for "Year Started (yyyy)" -- would
    create a new field downstream rather than extend the real one, and nothing
    would report it.
    """
    rows = []
    for entity in response.entities:
        fields, dropped = clean_fields(entity.entity_type, entity.fields)
        if dropped:
            print(f"    dropped {entity.entity_name}: no such field {dropped}")
        rows.append({
            "article_id": article_id,
            "entity_name": entity.entity_name,
            "entity_name_en": entity.entity_name_en,
            "entity_type": entity.entity_type,
            "summary": entity.summary,
            "evidence": entity.evidence,
            "evidence_en": entity.evidence_en,
            "fields": fields,
            "confidence": entity.confidence,
        })
        if getattr(entity, "role", None) and column_exists(ENTITY_TABLE, "role"):
            rows[-1]["role"] = entity.role
    return rows


def save(article_id: int, rows: list[dict]) -> None:
    """
    Write one article's extraction result, then mark it processed.

    Ordering matters. Entities are deleted-then-inserted so a re-run replaces
    rather than duplicates, and `processed_extraction` is only set last -- if
    anything above fails the article stays in the queue and is redone cleanly.

    An empty `rows` is a valid outcome: the model found nothing to extract, so
    the article is still marked processed. Text a person put on the row by
    hand is cleared with it: once extracted, the article is done with.
    """
    client = get_client()

    # Clear any rows from a previous attempt that did not reach the flag update.
    client.from_(ENTITY_TABLE).delete().eq("article_id", article_id).execute()

    if rows:
        client.from_(ENTITY_TABLE).insert(rows).execute()

    client.from_(ARTICLE_TABLE).update(
        {"processed_extraction": True, "text": None}
    ).eq("id", article_id).execute()
