"""
Load parsed TTE authority data into Supabase.

Each dump replaces the previous snapshot in `entities`: records the dump
holds are written only if new or changed, and records it has dropped (or
lists for deletion) are deleted. The one exception is a dropped record a
proposal still points at (`candidate_matches.matched_uid`, or another
record's canonical_uid): the database refuses to delete it, since nothing
cascades, so it is kept and marked inactive instead. Writing only what
changed matters on the free tier: rewriting every record left the whole
table's old versions as dead space, 30-45 MB per load until compacted.
"""

import hashlib
import re
from datetime import date, datetime, timezone

from src.load_tte.parse import LANGUAGE_BY_SUFFIX, Entity
from src.shared.pagination import fetch_all
from src.shared.supabase_client import get_client

ENTITY_TABLE = "entities"
IMPORT_TABLE = "tte_imports"

# PostgREST rejects very large payloads; this keeps each request modest.
ENTITY_CHUNK = 500

# A snapshot missing more than this share of the vocabularies it covers is
# treated as truncated or malformed. Removing that much of the reference data
# is never a legitimate update, so the run aborts before writing anything.
MAX_MISSING_FRACTION = 0.10

COLUMNS = "uid, name, vocabulary, entity_type, language, fields, canonical_uid, is_active"


class SuspectSnapshotError(RuntimeError):
    """Raised when a snapshot would remove an implausible share of entities."""


def checksum(content: str | bytes) -> str:
    return hashlib.sha256(content if isinstance(content, bytes) else content.encode("utf-8")).hexdigest()


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def loaded_names() -> set[str]:
    """Every export filename the ledger has recorded."""
    return {r["filename"] for r in get_client().from_(IMPORT_TABLE).select("filename").execute().data}


def already_loaded(filename: str, digest: str) -> bool:
    """True if this exact file content has been ingested before."""
    rows = get_client().from_(IMPORT_TABLE).select("checksum").eq("filename", filename).execute().data
    return bool(rows) and rows[0]["checksum"] == digest


def load_existing() -> dict[str, dict]:
    """Every stored record, by uid."""
    rows = fetch_all(lambda: get_client().from_(ENTITY_TABLE).select(COLUMNS), order="uid")
    return {r["uid"]: r for r in rows}


def stored_canonical(entity: Entity) -> str | None:
    """canonical_uid as stored: empty when the record is its own preferred form."""
    return entity.canonical_uid if entity.canonical_uid and entity.canonical_uid != entity.uid else None


def changed(entities: list[Entity], existing: dict[str, dict]) -> list[Entity]:
    """Records the dump holds that are new, or differ from what is stored."""
    out = []
    for e in entities:
        row = existing.get(e.uid)
        if (row is None or not row["is_active"] or row["name"] != e.name
                or row["vocabulary"] != e.vocabulary or row["entity_type"] != e.entity_type
                or row["language"] != e.language or (row["fields"] or {}) != e.fields
                or row["canonical_uid"] != stored_canonical(e)):
            out.append(e)
    return out


def family(vocabulary: str) -> str:
    """A vocabulary without its language suffix: _People_CN belongs to _People."""
    head, _, suffix = vocabulary.rpartition("_")
    return head if head and suffix.upper() in LANGUAGE_BY_SUFFIX else vocabulary


def dropped(entities: list[Entity], deletes: set[str], existing: dict[str, dict]) -> set[str]:
    """
    Stored records the dump has dropped, or lists for deletion.

    Scoped by vocabulary family, not by the vocabularies the dump happens to
    contain: a language variant whose last record was dropped would otherwise
    vanish from the dump and take its records out of scope with it.
    """
    families = {family(e.vocabulary) for e in entities}
    present = {e.uid for e in entities}
    return {uid for uid, r in existing.items()
            if uid not in present and (family(r["vocabulary"]) in families or uid in deletes)}


def check_plausible(entities: list[Entity], gone: set[str], deletes: set[str], existing: dict[str, dict]) -> None:
    """Refuse a dump that drops more than MAX_MISSING_FRACTION of what it covers without saying so."""
    families = {family(e.vocabulary) for e in entities}
    active = sum(1 for r in existing.values() if r["is_active"] and family(r["vocabulary"]) in families)
    silent = [u for u in gone if u not in deletes and existing[u]["is_active"]]
    if active and len(silent) / active > MAX_MISSING_FRACTION:
        raise SuspectSnapshotError(
            f"the dump omits {len(silent):,} of {active:,} active records ({len(silent)/active:.0%}) "
            f"without listing them for deletion, above the {MAX_MISSING_FRACTION:.0%} threshold. "
            "Nothing was written; check the export is complete.")


def write(entities: list[Entity], existing: dict[str, dict]) -> int:
    """
    Insert or overwrite these records whole, fields included.

    canonical_uid points at another record, so a pointer to a record that is
    itself new in this load waits for a second pass, when its target exists.
    Rows are always complete: a PostgREST upsert is INSERT ... ON CONFLICT and
    rejects a partial row against the NOT NULL columns.
    """
    now = datetime.now(timezone.utc).isoformat()
    client = get_client()
    new = {e.uid for e in entities if e.uid not in existing}

    def row(e: Entity, canonical: str | None) -> dict:
        return {"uid": e.uid, "name": e.name, "vocabulary": e.vocabulary, "entity_type": e.entity_type,
                "language": e.language, "fields": e.fields, "canonical_uid": canonical,
                "is_active": True, "last_seen": now}

    first = [row(e, None if stored_canonical(e) in new else stored_canonical(e)) for e in entities]
    for chunk in _chunks(first, ENTITY_CHUNK):
        client.from_(ENTITY_TABLE).upsert(chunk, on_conflict="uid").execute()
    later = [row(e, stored_canonical(e)) for e in entities if stored_canonical(e) in new]
    for chunk in _chunks(later, ENTITY_CHUNK):
        client.from_(ENTITY_TABLE).upsert(chunk, on_conflict="uid").execute()
    return len(entities)


def removable(gone: set[str], matched: set[str], entities: list[Entity],
              existing: dict[str, dict]) -> tuple[set[str], set[str]]:
    """
    Which dropped records can be deleted, and which must be kept as inactive.

    A record is kept while a proposal matched it, or while a record that stays
    points at it as its canonical form; deleting it would break that link, and
    the database would refuse.
    """
    in_dump = {e.uid for e in entities}
    pointed = ({stored_canonical(e) for e in entities}
               | {r["canonical_uid"] for u, r in existing.items() if u not in in_dump and u not in gone})
    keep = gone & (matched | pointed)
    return gone - keep, keep


def matched_uids() -> set[str]:
    """Every record a proposal points at."""
    return {r["matched_uid"] for r in fetch_all(
        lambda: get_client().from_("candidate_matches").select("matched_uid").not_.is_("matched_uid", "null"),
        order="id")}


def remove(gone: set[str], entities: list[Entity], existing: dict[str, dict],
           matched: set[str]) -> tuple[int, int]:
    """Delete the dropped records nothing points at; mark the rest inactive. Returns (deleted, kept)."""
    client = get_client()
    delete, keep = removable(gone, matched, entities, existing)
    # A record being deleted may point at another being deleted; clearing its
    # pointer first means the order of the deletes cannot matter.
    pointing = sorted(u for u in delete if existing[u]["canonical_uid"])
    for chunk in _chunks(pointing, ENTITY_CHUNK):
        client.from_(ENTITY_TABLE).update({"canonical_uid": None}).in_("uid", chunk).execute()
    for chunk in _chunks(sorted(delete), ENTITY_CHUNK):
        client.from_(ENTITY_TABLE).delete().in_("uid", chunk).execute()
    for chunk in _chunks(sorted(u for u in keep if existing[u]["is_active"]), ENTITY_CHUNK):
        client.from_(ENTITY_TABLE).update({"is_active": False}).in_("uid", chunk).execute()
    return len(delete), len(keep)


def record_import(filename: str, entity_type: str, snapshot: date, digest: str, rows: int) -> None:
    get_client().from_(IMPORT_TABLE).upsert(
        {"filename": filename, "entity_type": entity_type, "snapshot": snapshot.isoformat(),
         "checksum": digest, "rows_loaded": rows},
        on_conflict="filename",
    ).execute()


def dump_date(filename: str) -> date:
    """The snapshot date in a dump's name (TTE-DELTA_20260901.zip), or today."""
    m = re.search(r"(\d{4})(\d{2})(\d{2})", filename)
    return date(int(m[1]), int(m[2]), int(m[3])) if m else date.today()


def forget_older(keep: set[str]) -> list[str]:
    """Drop every ledger row but these filenames, so the ledger shows only the latest dump."""
    client = get_client()
    old = [r["filename"] for r in client.from_(IMPORT_TABLE).select("filename").execute().data
           if r["filename"] not in keep]
    for chunk in _chunks(old, 100):
        client.from_(IMPORT_TABLE).delete().in_("filename", chunk).execute()
    return old
