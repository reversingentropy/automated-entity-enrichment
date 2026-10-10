"""
Work out which resolutions a TTE update has actually invalidated.

A new authority snapshot does not change most decisions. Measured against the
September import -- 766 records added, 191 retired -- only 2 entities in 60 had
a candidate set that changed at all. Re-resolving everything therefore pays an
LLM call for each of the other 58, re-litigates matches that were already
settled, and destroys any review decision attached to them.

Retrieval is plain SQL and costs nothing, so the candidate set can be checked
for every entity and the model called only where it differs.
"""

import datetime as dt

from src.job3_resolution.candidates import candidates_for
from src.shared.pagination import fetch_all
from src.shared.supabase_client import column_exists, get_client

# How far back from the newest last_seen counts as "this import".
IMPORT_WINDOW = dt.timedelta(hours=6)


def _parse(stamp: str) -> dt.datetime:
    return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def changed_records() -> tuple[set[str], set[str]]:
    """The uids added by the most recent import, and those now retired."""
    rows = fetch_all(lambda: get_client().from_("entities")
                     .select("uid,first_seen,last_seen,is_active"), order="uid")
    if not rows:
        return set(), set()
    cutoff = max(_parse(r["last_seen"]) for r in rows) - IMPORT_WINDOW
    added = {r["uid"] for r in rows if _parse(r["first_seen"]) > cutoff}
    retired = {r["uid"] for r in rows if not r["is_active"]}
    return added, retired


def stale_entities() -> list[dict]:
    """
    Entities whose resolution the latest import may have changed.

    Two cases only: the record a proposal matched has been retired, so the
    proposal points at something that can no longer take an update; or a newly
    added record now appears among the entity's candidates, so a decision of
    "no match" may no longer hold.
    """
    added, retired = changed_records()
    client = get_client()
    def build():
        q = client.from_("extracted_entities").select("id,entity_name,entity_name_en,entity_type")
        # A TTE import must never requeue the historical backfill onto
        # Gemini's quota; those entities are resolved by export and import.
        if column_exists("extracted_entities", "backfill"):
            q = q.eq("backfill", False)
        return q

    entities = fetch_all(build)
    matched = {p["extracted_id"]: p["matched_uid"]
               for p in fetch_all(lambda: client.from_("candidate_matches")
                                  .select("extracted_id,matched_uid"))}

    stale = []
    for entity in entities:
        if matched.get(entity["id"]) in retired:
            stale.append({**entity, "why": "matched record retired"})
            continue
        candidates = {c["canonical_uid"] for c in candidates_for(entity)}
        if candidates & added:
            stale.append({**entity, "why": "a new record is now a candidate"})
    return stale


def requeue(entity_ids: list[int]) -> None:
    """Mark these entities unresolved and clear their proposals."""
    client = get_client()
    for start in range(0, len(entity_ids), 200):
        chunk = entity_ids[start:start + 200]
        client.from_("candidate_matches").delete().in_("extracted_id", chunk).execute()
        client.from_("extracted_entities").update({"resolved": False}).in_("id", chunk).execute()
