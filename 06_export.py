"""
06_export.py — Export approved changes and full decision log.

What this does:
  - Loads proposals.json and decisions.json
  - Filters approved decisions
  - Exports approved_changes.csv for manual TTE import
  - Exports decision_log.csv for audit trail and future training data

Usage:
    python 06_export.py
"""

import json

import pandas as pd

import config
import utils

utils.print_header("Step 6: Exporting Approved Changes")

# ─────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────

utils.print_step("Loading proposals and decisions")

with open(config.PROPOSALS_JSON, "r", encoding="utf-8") as f:
    proposals = json.load(f)
proposals_map = {str(p["id"]): p for p in proposals}

with open(config.DECISIONS_JSON, "r", encoding="utf-8") as f:
    decisions = json.load(f)

print(f"  Proposals loaded  : {len(proposals):,}")
print(f"  Decisions loaded  : {len(decisions):,}")

# ─────────────────────────────────────────────
# BUILD APPROVED CHANGES CSV
# ─────────────────────────────────────────────

utils.print_step("Building approved changes export")

approved_rows = []
for decision in decisions:
    if decision["decision"] != "approved":
        continue

    proposal = proposals_map.get(str(decision["proposal_id"]))
    if not proposal:
        continue

    entity = proposal.get("entity", {})
    changes = proposal.get("proposed_changes", [])

    if not changes:
        # Approved but no specific field changes extracted
        # Include as a record for manual review
        approved_rows.append({
            "tte_uid":           entity.get("tte_uid", ""),
            "tte_authorised_name": entity.get("authorised_name", ""),
            "tte_vocabulary":    entity.get("vocabulary", ""),
            "event_type":        proposal.get("event_type", ""),
            "entity_name":       entity.get("name", ""),
            "field":             "",
            "new_value":         "",
            "evidence":          "",
            "article_title":     proposal.get("article_title", ""),
            "article_url":       proposal.get("article_url", ""),
            "reviewer":          decision.get("reviewer", ""),
            "decision_timestamp": decision.get("timestamp", ""),
            "match_score":       entity.get("match_score", ""),
            "note":              "Approved — no specific field changes extracted. Manual review of article recommended.",
        })
        continue

    # One row per proposed field change
    for change in changes:
        approved_rows.append({
            "tte_uid":           entity.get("tte_uid", ""),
            "tte_authorised_name": entity.get("authorised_name", ""),
            "tte_vocabulary":    entity.get("vocabulary", ""),
            "event_type":        proposal.get("event_type", ""),
            "entity_name":       entity.get("name", ""),
            "field":             change.get("field", ""),
            "new_value":         change.get("new_value", ""),
            "evidence":          change.get("evidence", ""),
            "article_title":     proposal.get("article_title", ""),
            "article_url":       proposal.get("article_url", ""),
            "reviewer":          decision.get("reviewer", ""),
            "decision_timestamp": decision.get("timestamp", ""),
            "match_score":       entity.get("match_score", ""),
            "note":              "",
        })

# ─────────────────────────────────────────────
# BUILD DECISION LOG CSV
# ─────────────────────────────────────────────

utils.print_step("Building full decision log")

log_rows = []
for decision in decisions:
    proposal = proposals_map.get(str(decision["proposal_id"]))
    if not proposal:
        continue

    entity = proposal.get("entity", {})
    log_rows.append({
        "proposal_id":        decision.get("proposal_id", ""),
        "decision":           decision.get("decision", ""),
        "reason":             decision.get("reason", ""),
        "reviewer":           decision.get("reviewer", ""),
        "decision_timestamp": decision.get("timestamp", ""),
        "article_url":        decision.get("article_url", ""),
        "article_title":      proposal.get("article_title", ""),
        "event_type":         decision.get("event_type", ""),
        "entity_name":        decision.get("entity_name", ""),
        "tte_uid":            decision.get("tte_uid", ""),
        "tte_authorised_name": entity.get("authorised_name", ""),
        "tte_vocabulary":     entity.get("vocabulary", ""),
        "match_score":        entity.get("match_score", ""),
        "match_type":         entity.get("match_type", ""),
        "record_richness":    entity.get("record_richness", ""),
        "llm_confidence":     proposal.get("llm_confidence", ""),
        "priority":           proposal.get("priority", ""),
        "pipeline_version":   proposal.get("pipeline_version", ""),
        "model_used":         proposal.get("model_used", ""),
        "created_at":         proposal.get("created_at", ""),
    })

# ─────────────────────────────────────────────
# SAVE
# ─────────────────────────────────────────────

utils.ensure_outputs_dir()

approved_df = pd.DataFrame(approved_rows)
approved_df.to_csv(config.APPROVED_CSV, index=False)

log_df = pd.DataFrame(log_rows)
log_df.to_csv(config.DECISION_LOG_CSV, index=False)

# Summary
decision_counts = {}
for d in decisions:
    decision_counts[d["decision"]] = decision_counts.get(d["decision"], 0) + 1

print("\n" + "─" * 40)
print("Export complete.")
print(f"\n  Decision summary:")
for decision_type, count in decision_counts.items():
    print(f"    {decision_type:<20} : {count:,}")

print(f"\n  Approved changes   : {len(approved_rows):,} field updates")
print(f"  Saved to           : {config.APPROVED_CSV}")
print(f"\n  Decision log       : {len(log_rows):,} entries")
print(f"  Saved to           : {config.DECISION_LOG_CSV}")
print(f"\n  The approved_changes.csv is ready for manual TTE import.")
print(f"  The decision_log.csv is your audit trail and future training data.")
