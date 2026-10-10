"""
Flatten resolution proposals into review rows.

One row per proposed field change, plus one row for any resolution that
proposes no change (a flag). That shape suits a spreadsheet: a reviewer reads
across a single line to see the article's claim, the record it targets, the
current value and the proposed one, and writes a verdict in the last column.
"""

import html

from src.shared.pagination import fetch_all
from src.shared.supabase_client import column_exists, get_client

# What a reviewer needs to answer "should this go into TTE?", in reading
# order, with their two columns at the end. Everything diagnostic -- uids,
# similarity scores, the model's reasoning -- lives in the full format instead,
# because it does not help the decision and slows the scan.
# The decision is always the same comparison: what the article says about this
# entity, against who TTE thinks the record is. Both sides must be on the row,
# or the reviewer is guessing.
REVIEW_COLUMNS = [
    "entity", "article_says",
    "tte_record", "tte_says",
    "change", "current_value",
    "verdict", "note",
    "quote", "link",
]

# The two columns a reviewer fills in carry their instructions in the header,
# so the rule stays on screen instead of in a separate document.
REVIEW_HEADERS = {
    "entity": "entity in the news",
    "article_says": "what the news says about them",
    "tte_record": "existing TTE record",
    "tte_says": "who TTE thinks that is",
    "change": "proposed change",
    "current_value": "what that field says now",
    "verdict": "verdict -> yes / no / edit",
    "note": "note (only if no or edit)",
    "quote": "quote from the article",
    "link": "read the article",
}

# Fields that say who a record is, in the order a person would want them.
IDENTIFYING = ("Description", "Occupation", "Title", "Country", "Feature Type")


def identify(fields: dict | None) -> str:
    """A short 'who is this' line for a TTE record, for comparison."""
    fields = fields or {}
    parts = [f"{k}: {fields[k]}" for k in IDENTIFYING if fields.get(k)]
    return " | ".join(parts[:3])

# Everything, for debugging a decision after the fact.
FULL_COLUMNS = REVIEW_COLUMNS + [
    "proposal_id", "article_id", "article_url", "entity_name_en",
    "action", "confidence", "reasoning", "evidence", "article_summary",
    "matched_uid", "field", "strategy", "proposed_value",
    "top_candidate", "top_similarity",
]

COLUMNS = FULL_COLUMNS  # kept for callers that want the whole set

# How each merge strategy reads as an instruction rather than a keyword.
CHANGE_PHRASING = {
    "APPEND": "Add to {field}: {value}",
    "MERGE": "Rewrite {field} keeping what is there, as: {value}",
    "REPLACE": "Replace {field} with: {value}",
    "INSERT_RELATION": "Link {field}: {value}",
}

FLAG_PHRASING = {
    "FLAG_AMBIGUOUS": "Cannot tell if this is the same entity - needs a human",
    "FLAG_DB_DUPLICATE": "Two or more TTE records look like the same entity",
    "RE_QUERY_REQUIRED": "Probably exists under another name - search suggested",
}


def describe(action: str, update: dict | None) -> str:
    """One readable sentence saying what is being proposed."""
    if update is None:
        return FLAG_PHRASING.get(action, action)
    template = CHANGE_PHRASING.get(update["strategy"], "{field}: {value}")
    return template.format(field=update["field"], value=update["value"])


def alternatives(proposal: dict, records: dict[str, dict]) -> str:
    """
    The records a flag is actually about.

    A flag that says "two records look the same" without naming them gives the
    reviewer nothing to decide with. Both flag types are about competing
    records, so those records go on the row.
    """
    uids = proposal.get("duplicate_uids") or []
    if not uids:
        uids = [c["canonical_uid"] for c in (proposal.get("candidates") or [])[:3]]

    lines = []
    for uid in uids:
        record = records.get(uid)
        if record is None:
            continue
        who = identify(record.get("fields"))
        lines.append(f"{record['name']} - {who}" if who else record["name"])
    return "  //  ".join(lines)


def _articles_by_id(ids: list[int]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for start in range(0, len(ids), 200):
        rows = (
            get_client().from_("article").select("id, title, url")
            .in_("id", ids[start:start + 200]).execute().data or []
        )
        out.update({r["id"]: r for r in rows})
    return out


def _entities_by_uid(uids: list[str]) -> dict[str, dict]:
    uids = [u for u in uids if u]
    out: dict[str, dict] = {}
    for start in range(0, len(uids), 200):
        rows = (
            get_client().from_("entities").select("uid, name, fields")
            .in_("uid", uids[start:start + 200]).execute().data or []
        )
        out.update({r["uid"]: r for r in rows})
    return out


def build_rows(backfill: bool = False) -> list[dict]:
    """Every proposal, flattened one row per proposed field change."""
    client = get_client()
    proposals = fetch_all(lambda: client.from_("candidate_matches").select("*"))
    if not proposals:
        return []

    flagged = column_exists("extracted_entities", "backfill")
    columns = "id, article_id, entity_name, entity_name_en, entity_type, summary, evidence"
    extracted = {
        r["id"]: r
        for r in fetch_all(lambda: client.from_("extracted_entities").select(
            columns + (", backfill" if flagged else "")))
    }
    # Nightly proposals or the historical backfill's, never both in one file.
    if flagged:
        extracted = {k: v for k, v in extracted.items() if bool(v.get("backfill")) == backfill}
        proposals = [p for p in proposals if p["extracted_id"] in extracted]
    articles = _articles_by_id(sorted({e["article_id"] for e in extracted.values()}))
    referenced = [p["matched_uid"] for p in proposals]
    for p in proposals:
        referenced += p.get("duplicate_uids") or []
        referenced += [c["canonical_uid"] for c in (p.get("candidates") or [])[:3]]
    targets = _entities_by_uid(referenced)

    rows = []
    for p in proposals:
        entity = extracted.get(p["extracted_id"])
        if entity is None:
            continue
        article = articles.get(entity["article_id"], {})
        target = targets.get(p["matched_uid"] or "", {})
        current = target.get("fields") or {}
        candidates = p.get("candidates") or []

        is_flag = p["resolution_action"] != "MATCH_AND_UPDATE"
        name = entity["entity_name"]
        if entity.get("entity_name_en"):
            name = f'{name}  ({entity["entity_name_en"]})'

        base = {
            "entity": name,
            "article_says": entity.get("summary") or "",
            # For a flag, the competing records are the decision.
            "tte_record": target.get("name", "") or ("see alternatives" if is_flag else ""),
            "tte_says": alternatives(p, targets) if is_flag else identify(current),
            "quote": entity.get("evidence") or "",
            "link": article.get("url", ""),
            "type": entity["entity_type"],
            "article": html.unescape(article.get("title") or ""),
            "verdict": "",
            "note": "",
            "proposal_id": p["id"],
            "article_id": entity["article_id"],
            "article_url": article.get("url", ""),
            "entity_name_en": entity.get("entity_name_en") or "",
            "action": p["resolution_action"],
            "confidence": p.get("confidence") or "",
            "reasoning": p.get("reasoning") or "",
            "evidence": entity.get("evidence") or "",
            "article_summary": entity.get("summary") or "",
            "matched_uid": p.get("matched_uid") or "",
            "top_candidate": candidates[0]["canonical_name"] if candidates else "",
            "top_similarity": round(candidates[0]["similarity"], 3) if candidates else "",
        }

        updates = p.get("field_updates") or []
        if not updates:
            # A flag, or a match proposing nothing. Still needs a verdict.
            rows.append({**base, "change": describe(p["resolution_action"], None),
                         "current_value": "", "field": "", "strategy": "",
                         "proposed_value": ""})
            continue

        for update in updates:
            rows.append({
                **base,
                "change": describe(p["resolution_action"], update),
                # What the record says today, so the reviewer can see exactly
                # what an addition extends or a replacement would discard.
                "current_value": current.get(update["field"], ""),
                "field": update["field"],
                "strategy": update["strategy"],
                "proposed_value": update["value"],
            })

    # Flags first: they are rare and need a person, so they should not be
    # buried under a hundred routine additions.
    rows.sort(key=lambda r: (r["action"] == "MATCH_AND_UPDATE",
                             r["article_id"], r["entity"], r.get("field", "")))
    return rows
