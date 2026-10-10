"""Persist resolution decisions and close out the article's entities."""

from src.shared.description import judge
from src.shared.field_names import canonical
from src.shared.models import ResolutionResponse
from src.shared.names import name_link_values
from src.shared.supabase_client import get_client

ENTITY_TABLE = "extracted_entities"
MATCH_TABLE = "candidate_matches"

# CREATE_NEW is the omitted default in the prompt, but tolerate the model
# emitting it explicitly rather than failing the whole article.
IMPLICIT_ACTIONS = {"CREATE_NEW"}


def search_names(name: str, entity_type: str) -> list[dict]:
    """The name search, for naming a link value as TTE names the record."""
    from src.job3_resolution.candidates import RPC
    return (get_client().rpc(RPC, {"query_name": name, "match_count": 3, "want_type": entity_type})
            .execute().data or [])


def build_rows(response: ResolutionResponse, entities: list[dict],
               candidates_by_id: dict[int, list[dict]], search=search_names) -> list[dict]:
    """
    Turn resolutions into candidate_matches rows.

    Results are matched back to entities by name. A name the article did not
    produce is dropped rather than guessed at -- the same protection Job 1
    applies to invented ids.

    A value naming another record (an award, an organisation, a founder) is
    stored as TTE names that record, with what the article wrote beside it,
    so the proposal already holds the value a cataloguer will type. `search`
    is the name search; the backfill passes its local copy.
    """
    by_name: dict[str, dict] = {}
    for entity in entities:
        by_name.setdefault(entity["entity_name"], entity)
        if entity.get("entity_name_en"):
            by_name.setdefault(entity["entity_name_en"], entity)

    rows = []
    seen: set[int] = set()
    for result in response.resolutions:
        if result.resolution_action in IMPLICIT_ACTIONS:
            continue

        entity = by_name.get(result.article_entity_name)
        if entity is None:
            print(f"    ignoring '{result.article_entity_name}': not in this article")
            continue
        # The model has returned the same entity twice in one answer. Delete-
        # then-insert protects against a re-run, not against a duplicate that
        # arrives inside a single response; four entities carried two
        # identical proposals each before this check.
        if entity["id"] in seen:
            print(f"    ignoring repeat resolution for '{result.article_entity_name}'")
            continue
        seen.add(entity["id"])
        # An invalid match below falls through to a CREATE_NEW row rather than
        # to silence, so the fact that the model tried is still recorded.

        # A matched_uid must be one the retriever actually offered. Anything
        # else is invented, and candidate_matches.matched_uid is a foreign key
        # into entities -- a bad value fails the insert and takes the whole
        # article's resolutions with it.
        offered = {c["canonical_uid"] for c in candidates_by_id.get(entity["id"], [])}
        if result.matched_uid_is_invalid(offered):
            print(f"    ignoring match for '{result.article_entity_name}': "
                  f"uid {result.matched_id} was not among its candidates")
            seen.discard(entity["id"])
            continue

        # A proposal naming a field TTE does not have would create one rather
        # than update anything, so correct the near misses and drop the rest.
        held = next((c.get("canonical_fields") or {}
                     for c in candidates_by_id.get(entity["id"], [])
                     if c["canonical_uid"] == result.matched_id), {})
        updates, bad = [], []
        for u in result.field_updates:
            real = canonical(entity["entity_type"], u.field)
            if real is None:
                bad.append(u.field)
                continue
            update = {**u.model_dump(), "field": real}
            name_link_values(update, search)

            # A description rewrite is the one update that can destroy curated
            # work, so it is checked rather than trusted. One that adds no fact
            # is dropped -- it can only be restyling. One that deletes heavily
            # is kept and marked, because a description is sometimes genuinely
            # wrong and that is a person's judgement, not a threshold's.
            if real == "Description" and update["strategy"] in ("MERGE", "REPLACE"):
                verdict, left, _ = judge(held.get("Description", ""), update["value"])
                if verdict == "drop":
                    print(f"    dropped description rewrite for "
                          f"'{result.article_entity_name}': adds nothing new")
                    continue
                update["survives"] = round(left, 2)
                if verdict == "flag":
                    update["over_edit"] = True
                    print(f"    description rewrite for '{result.article_entity_name}' "
                          f"keeps only {left:.0%} of the record's text")
            updates.append(update)
        if bad:
            print(f"    dropped updates for '{result.article_entity_name}': "
                  f"no such field {bad}")

        rows.append({
            "extracted_id": entity["id"],
            "resolution_action": result.resolution_action,
            "matched_uid": result.matched_id,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "field_updates": updates,
            "inverse_updates": [u.model_dump() for u in result.inverse_updates],
            "re_query_term": result.re_query_term,
            "duplicate_uids": result.duplicate_db_ids,
            "candidates": candidates_by_id.get(entity["id"], []),
        })

    # Every entity the model was shown gets a row, including the ones it left
    # out. The prompt's contract is that an omitted entity is new, and that
    # contract made two thirds of all resolutions unrecordable: 129 of 195
    # entities had no row, so nobody could review the decision that they were
    # not in TTE, and one of them was Aidha, which is. The decision is now
    # written down with the candidates it was made against.
    for entity in entities:
        if entity["id"] in seen:
            continue
        rows.append({
            "extracted_id": entity["id"],
            "resolution_action": "CREATE_NEW",
            "matched_uid": None,
            "confidence": None,
            "reasoning": "Not returned by the model: no offered candidate was judged "
                         "to be this entity.",
            "field_updates": [],
            "inverse_updates": [],
            "re_query_term": None,
            "duplicate_uids": [],
            "candidates": candidates_by_id.get(entity["id"], []),
        })
    return rows


def save(entity_ids: list[int], rows: list[dict]) -> None:
    """
    Write one article's resolutions, then mark its entities resolved.

    Delete-then-insert so a re-run replaces rather than duplicates, and the
    resolved flag is set last: any failure above leaves the entities queued.
    An empty `rows` is valid -- every entity was simply new.
    """
    client = get_client()

    for start in range(0, len(entity_ids), 200):
        chunk = entity_ids[start:start + 200]
        client.from_(MATCH_TABLE).delete().in_("extracted_id", chunk).execute()

    if rows:
        client.from_(MATCH_TABLE).insert(rows).execute()

    for start in range(0, len(entity_ids), 200):
        chunk = entity_ids[start:start + 200]
        client.from_(ENTITY_TABLE).update({"resolved": True}).in_("id", chunk).execute()
