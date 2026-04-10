"""
04_build_proposals.py — Assemble structured update proposals.

What this does:
  - Combines linked entities + extracted facts into final proposals
  - Each proposal is a structured JSON object ready for human review
  - Proposals are classified by review priority:
      HIGH   — high match + facts extracted + entity confirmed
      MEDIUM — high match but entity not confirmed, or low match
      FLAG   — no match (potential new entity candidate)
  - Saves to proposals.json

Usage:
    python 04_build_proposals.py
"""

import json
import os

import pandas as pd

import config
import utils

utils.print_header("Step 4: Building Update Proposals")

# ─────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────

utils.print_step(f"Loading extracted facts from {config.FACTS_CSV}")
facts_df = pd.read_csv(config.FACTS_CSV, dtype=str).fillna("")
print(f"  Rows loaded: {len(facts_df):,}")

utils.print_step(f"Loading linked entities from {config.LINKED_CSV}")
linked_df = pd.read_csv(config.LINKED_CSV, dtype=str).fillna("")

# Get the non-high-match rows (low_match, no_match, no_entity_found)
# These still need to be surfaced for human review
other_df = linked_df[linked_df["match_type"] != "high_match"].copy()
print(f"  Non-high-match rows to include: {len(other_df):,}")

# ─────────────────────────────────────────────
# BUILD PROPOSALS
# ─────────────────────────────────────────────

utils.print_step("Assembling proposals")

proposals = []
proposal_id = 1


def make_proposal_from_facts(row: pd.Series) -> dict:
    """Build a proposal from a fact-extracted high-match row."""
    extracted_fields = {}
    raw_fields = row.get("extracted_fields", "{}")
    try:
        extracted_fields = json.loads(raw_fields) if raw_fields else {}
    except json.JSONDecodeError:
        pass

    # Build proposed changes list
    proposed_changes = []
    for field_name, field_data in extracted_fields.items():
        if not field_data or not field_data.get("value"):
            continue
        proposed_changes.append({
            "field":    field_name,
            "new_value": field_data.get("value"),
            "evidence": field_data.get("evidence", ""),
        })

    # Top candidates for UI display
    top_candidates = []
    raw_candidates = row.get("top_candidates", "[]")
    try:
        top_candidates = json.loads(raw_candidates) if raw_candidates else []
    except json.JSONDecodeError:
        pass

    entity_confirmed = str(row.get("entity_confirmed", "True")).lower() == "true"
    priority = "HIGH" if (proposed_changes and entity_confirmed) else "MEDIUM"

    return {
        "id":                 proposal_id,
        "status":             "pending",
        "priority":           priority,
        "article_title":      row.get("article_title", ""),
        "article_url":        row.get("article_url", ""),
        "event_type":         row.get("event_type", ""),
        "entity": {
            "name":            row.get("entity_name", ""),
            "type":            row.get("entity_type", ""),
            "tte_uid":         row.get("tte_uid", ""),
            "authorised_name": row.get("tte_authorised_name", ""),
            "display_name":    row.get("tte_display_name", ""),
            "vocabulary":      row.get("tte_vocabulary", ""),
            "match_score":     float(row.get("match_score", 0)),
            "match_type":      row.get("match_type", ""),
            "record_richness": int(row.get("record_richness", 0)),
        },
        "proposed_changes":   proposed_changes,
        "top_candidates":     top_candidates,
        "llm_confidence":     row.get("llm_confidence", ""),
        "entity_confirmed":   entity_confirmed,
        "fact_status":        row.get("fact_status", ""),
        "created_at":         utils.now_str(),
        "pipeline_version":   "0.1.0",
        "model_used":         config.MODEL,
    }


def make_proposal_from_linked(row: pd.Series, priority: str) -> dict:
    """Build a proposal from a non-high-match linked entity row."""
    top_candidates = []
    raw_candidates = row.get("top_candidates", "[]")
    try:
        top_candidates = json.loads(raw_candidates) if raw_candidates else []
    except json.JSONDecodeError:
        pass

    match_type = row.get("match_type", "")
    note = {
        "low_match":       "Low confidence match — review candidates carefully",
        "no_match":        "No TTE match found — potential new entity candidate",
        "no_entity_found": "No entity of expected type found in article NER output",
    }.get(match_type, "")

    return {
        "id":                 proposal_id,
        "status":             "pending",
        "priority":           priority,
        "article_title":      row.get("article_title", ""),
        "article_url":        row.get("article_url", ""),
        "event_type":         row.get("event_type", ""),
        "entity": {
            "name":            row.get("entity_name", ""),
            "type":            row.get("entity_type", ""),
            "tte_uid":         row.get("tte_uid", ""),
            "authorised_name": row.get("tte_authorised_name", ""),
            "display_name":    row.get("tte_display_name", ""),
            "vocabulary":      row.get("tte_vocabulary", ""),
            "match_score":     float(row.get("match_score", 0)),
            "match_type":      match_type,
            "record_richness": int(row.get("record_richness", 0)),
        },
        "proposed_changes":   [],
        "top_candidates":     top_candidates,
        "llm_confidence":     "",
        "entity_confirmed":   False,
        "fact_status":        match_type,
        "note":               note,
        "created_at":         utils.now_str(),
        "pipeline_version":   "0.1.0",
        "model_used":         config.MODEL,
    }


# Process fact-extracted rows
for _, row in facts_df.iterrows():
    proposal = make_proposal_from_facts(row)
    proposals.append(proposal)
    proposal_id += 1

# Process other rows (low match, no match)
for _, row in other_df.iterrows():
    match_type = row.get("match_type", "")
    priority = "FLAG" if match_type in ("no_match",) else "MEDIUM"
    proposal = make_proposal_from_linked(row, priority)
    proposals.append(proposal)
    proposal_id += 1

# ─────────────────────────────────────────────
# SAVE
# ─────────────────────────────────────────────

utils.ensure_outputs_dir()
with open(config.PROPOSALS_JSON, "w", encoding="utf-8") as f:
    json.dump(proposals, f, indent=2, ensure_ascii=False)

# Summary
priority_counts = {}
for p in proposals:
    priority_counts[p["priority"]] = priority_counts.get(p["priority"], 0) + 1

print("\n" + "─" * 40)
print("Proposals built.")
print(f"  Total proposals : {len(proposals):,}")
for priority in ["HIGH", "MEDIUM", "FLAG"]:
    count = priority_counts.get(priority, 0)
    print(f"  {priority:<8}        : {count:,}")
print(f"\n  Saved to: {config.PROPOSALS_JSON}")
print("\nNext step: python 05_review_queue.py")
