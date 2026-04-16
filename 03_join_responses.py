"""
03_join_responses.py — Link entities to TTE and build the review queue.

Takes prompts_for_batch.csv after LLM responses have been added,
BM25-links each extracted entity to TTE, looks up current field values,
determines merge state, and writes the review queue.

Input:  outputs/prompts_for_batch.csv  (must have `llm_response` column)
        outputs/bm25_index.pkl         (run 01_build_index.py first)
        data/tte/                      (TTE CSV files)

Output: outputs/review_queue.csv
        outputs/new_entity_candidates.csv

Merge state values:
    ADD       — field does not exist in TTE record, will be added
    APPEND    — pipe-delimited field, new value appended
    REPLACE   — single value field, existing value replaced
    DUPLICATE — value already in TTE, no change needed (skipped)

Usage:
    python 03_join_responses.py

Next step:
    streamlit run review_app.py
"""

import os

import pandas as pd

import config
import utils

_PROMPTS_PRIMARY  = os.path.join(config.OUTPUTS_DIR, "prompts_for_batch.csv")
_PROMPTS_FALLBACK = os.path.join(config.OUTPUTS_DIR, "fact_extraction.csv")
PROMPTS_CSV    = _PROMPTS_PRIMARY if os.path.exists(_PROMPTS_PRIMARY) else _PROMPTS_FALLBACK
REVIEW_CSV     = os.path.join(config.OUTPUTS_DIR, "review_queue.csv")
NEW_ENTITY_CSV = os.path.join(config.OUTPUTS_DIR, "new_entity_candidates.csv")

# Fields that are pipe-delimited lists in TTE — append instead of replace
PIPE_DELIMITED_FIELDS = {
    "Awards", "Achievements", "Affiliations(groupName)",
    "Occupation", "Education", "UF", "RT", "Source",
    "Organiser", "Successor", "Predecessor",
}


def get_current_value(tte_dfs, vocab, uid, field_name):
    """Look up the current value of a field for a TTE entity."""
    if vocab not in tte_dfs:
        return None
    df = tte_dfs[vocab]
    rows = df[
        (df["Key UID"].astype(str).str.strip() == str(uid).strip()) &
        (df["Relationship Type"].str.strip() == field_name.strip())
    ]
    return rows.iloc[0]["Related Descriptor"] if not rows.empty else None


def get_merge_state(field_name, current_value, new_value):
    """
    Determine how new_value relates to current_value.
    Returns (merge_state, final_value).
    """
    new_value = str(new_value).strip()
    if not current_value or str(current_value).strip() == "":
        return "ADD", new_value

    current_value = str(current_value).strip()
    if field_name in PIPE_DELIMITED_FIELDS:
        existing = [v.strip() for v in current_value.split("|")]
        if new_value in existing:
            return "DUPLICATE", current_value
        return "APPEND", current_value + " | " + new_value

    if current_value == new_value:
        return "DUPLICATE", current_value
    return "REPLACE", new_value


def load_tte_dfs():
    dfs = {}
    for vocab, filename in config.TTE_FILES.items():
        path = os.path.join(config.TTE_DIR, filename)
        if os.path.exists(path):
            dfs[vocab] = pd.read_csv(path, dtype=str).fillna("")
        else:
            print(f"  WARNING: {filename} not found")
    return dfs


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

utils.ensure_outputs_dir()
utils.print_header("Step 3: BM25 Link → TTE Lookup → Review Queue")

utils.print_step(f"Loading {PROMPTS_CSV}")
if not os.path.exists(PROMPTS_CSV):
    print("  ERROR: File not found. Run 02_build_prompts.py first.")
    exit(1)

df = pd.read_csv(PROMPTS_CSV, dtype=str).fillna("")
print(f"  Total rows        : {len(df):,}")

if "llm_response" not in df.columns:
    print("  ERROR: No `llm_response` column found.")
    print("  Add LLM responses as column `llm_response` then rerun.")
    exit(1)

has_response = df["llm_response"].str.strip().ne("").sum()
print(f"  Rows with response: {has_response:,}")

utils.print_step("Loading BM25 index")
index = utils.load_index()

utils.print_step("Loading TTE CSVs")
tte_dfs = load_tte_dfs()
print(f"  Loaded: {list(tte_dfs.keys())}")

utils.print_step("Processing")

review_rows     = []
new_entity_rows = []
stats = {
    "parsed":        0,
    "parse_failed":  0,
    "not_confirmed": 0,
    "no_fields":     0,
    "high_match":    0,
    "low_match":     0,
    "no_match":      0,
    "duplicate":     0,
}

for _, row in df.iterrows():
    raw_response = row.get("llm_response", "")
    if not raw_response or str(raw_response).strip() in ("", "nan"):
        continue

    parsed = utils.parse_json_response(raw_response)
    if not parsed:
        stats["parse_failed"] += 1
        continue

    # Normalise: some responses are a list of entity objects, some are a single object
    parsed_items = parsed if isinstance(parsed, list) else [parsed]

    article_url   = row.get("article_url", "")
    article_title = row.get("article_title", "")
    event_type    = row.get("event_type", "")
    row_id        = row.get("row_id", "")

    for parsed in parsed_items:
        if not isinstance(parsed, dict):
            continue

        stats["parsed"] += 1

        if not parsed.get("entity_confirmed", True):
            stats["not_confirmed"] += 1
            continue

        entity_name   = parsed.get("entity_name", "").strip()
        entity_type   = parsed.get("entity_type", row.get("expected_entity_type", "")).strip()
        fields        = parsed.get("fields", {})
        confidence    = parsed.get("confidence", "low")

        if not entity_name or not fields:
            stats["no_fields"] += 1
            continue

        vocab   = entity_type or row.get("expected_entity_type", "")
        matches = utils.search_index(index, entity_name, vocab)

        if not matches:
            stats["no_match"] += 1
            new_entity_rows.append({
                "row_id":        row_id,
                "article_url":   article_url,
                "article_title": article_title,
                "event_type":    event_type,
                "entity_name":   entity_name,
                "entity_type":   entity_type,
                "confidence":    confidence,
            })
            continue

        top        = matches[0]
        score      = top["score"]
        match_type = "high_match" if score >= config.HIGH_MATCH_THRESHOLD else "low_match"
        stats[match_type] += 1

        tte_uid         = top["uid"]
        tte_authorised  = top["authorised_name"]
        tte_vocabulary  = top["vocabulary"]
        record_richness = top["record_richness"]

        for field_name, field_data in fields.items():
            if not field_data:
                continue
            new_value = field_data.get("value")
            evidence  = field_data.get("evidence", "")
            if not new_value or str(new_value).strip().lower() in ("null", "none", ""):
                continue

            current_value = get_current_value(tte_dfs, tte_vocabulary, tte_uid, field_name)
            merge_state, final_value = get_merge_state(field_name, current_value, new_value)

            if merge_state == "DUPLICATE":
                stats["duplicate"] += 1
                continue

            review_rows.append({
                "row_id":              row_id,
                "article_url":         article_url,
                "article_title":       article_title,
                "event_type":          event_type,
                "entity_name":         entity_name,
                "entity_type":         entity_type,
                "tte_uid":             tte_uid,
                "tte_authorised_name": tte_authorised,
                "tte_vocabulary":      tte_vocabulary,
                "match_score":         score,
                "match_type":          match_type,
                "record_richness":     record_richness,
                "field":               field_name,
                "current_value":       current_value if current_value else "",
                "new_value":           new_value,
                "final_value":         final_value,
                "merge_state":         merge_state,
                "evidence":            evidence,
                "llm_confidence":      confidence,
            })

pd.DataFrame(review_rows).to_csv(REVIEW_CSV, index=False)
pd.DataFrame(new_entity_rows).to_csv(NEW_ENTITY_CSV, index=False)

print("\n" + "─" * 60)
print(f"  Parsed ok          : {stats['parsed']:,}")
print(f"  Parse failed       : {stats['parse_failed']:,}")
print(f"  Not confirmed      : {stats['not_confirmed']:,}")
print(f"  No fields          : {stats['no_fields']:,}")
print(f"  High match         : {stats['high_match']:,}")
print(f"  Low match          : {stats['low_match']:,}")
print(f"  No match           : {stats['no_match']:,}")
print(f"  Duplicates skipped : {stats['duplicate']:,}")
print()
print(f"  review_queue.csv      : {len(review_rows):,} rows → {REVIEW_CSV}")
print(f"  new_entity_candidates : {len(new_entity_rows):,} rows → {NEW_ENTITY_CSV}")
print()
print("  NEXT STEP: streamlit run review_app.py")
