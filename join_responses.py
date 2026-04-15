"""
join_responses.py

Step 2 of 2.

Takes prompts_for_batch.csv after you have added LLM responses,
links extracted entities to TTE via BM25, looks up current TTE
field values, determines merge state, and produces review_queue.csv.

Input:  outputs/prompts_for_batch.csv  (must have llm_response column)
Output: outputs/review_queue.csv
        outputs/new_entity_candidates.csv

Columns in review_queue.csv:
    row_id, article_url, article_title, event_type,
    entity_name, entity_type,
    tte_uid, tte_authorised_name, tte_vocabulary,
    match_score, record_richness,
    field, current_value, new_value, merge_state, evidence,
    llm_confidence

merge_state values:
    ADD      — field does not exist in TTE record, will be added
    APPEND   — field is pipe-delimited list, new value will be appended
    REPLACE  — field exists with single value, will be replaced
    DUPLICATE — value already exists in TTE, no change needed

Usage:
    python join_responses.py

Requires:
    outputs/prompts_for_batch.csv  with llm_response column filled in
    outputs/bm25_index.pkl         run 01_build_index.py first
    data/tte/                      TTE CSV files
"""

import json
import os
import pickle
import re

import pandas as pd

# ─────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────

BATCH_CSV      = "outputs/prompts_for_batch.csv"
BM25_INDEX     = "outputs/bm25_index.pkl"
TTE_DIR        = "data/tte"
REVIEW_CSV     = "outputs/review_queue.csv"
NEW_ENTITY_CSV = "outputs/new_entity_candidates.csv"
OUTPUT_DIR     = "outputs"

HIGH_MATCH_THRESHOLD = 1.0

TTE_FILES = {
    "PERSON":       "TTE-PEOPLE_FULL_20251001.csv",
    "ORGANISATION": "TTE-ORGANISATIONS_FULL_20251001.csv",
    "FACILITY":     "TTE-GEOBUILDINGS_FULL_20251001.csv",
    "LOCATION":     "TTE-GEOGRAPHICS_FULL_20251001.csv",
    "EVENT":        "TTE-EVENTS_FULL_20251001.csv",
    "LEGAL_ACT":    "TTE-LEGALACTS_FULL_20251001.csv",
    "PROGRAMME":    "TTE-PROGRAMMES_FULL_20251001.csv",
    "AWARD":        "TTE-AWARDS_FULL_20251001.csv",
    "COUNTRY":      "TTE-COUNTRIES_FULL_20251001.csv",
}

# Fields that are pipe-delimited lists in TTE (append, not replace)
# Edit this list as you learn more about TTE field types
PIPE_DELIMITED_FIELDS = {
    "Awards", "Achievements", "Affiliations(groupName)",
    "Occupation", "Education", "UF", "RT", "Source",
    "Organiser", "Successor", "Predecessor",
}

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def tokenize(text):
    text = text.lower().strip()
    tokens = []
    current = []
    for char in text:
        if "\u4e00" <= char <= "\u9fff":
            if current:
                tokens.append("".join(current))
                current = []
            tokens.append(char)
        elif char.isalnum() or char in ("'", "-"):
            current.append(char)
        else:
            if current:
                tokens.append("".join(current))
                current = []
    if current:
        tokens.append("".join(current))
    return [t for t in tokens if len(t) >= 2]


def bm25_search(index, entity_name, vocab, top_k=5):
    if vocab not in index:
        return []
    vi = index[vocab]
    tokens = tokenize(entity_name)
    if not tokens:
        return []
    scores = vi["bm25"].get_scores(tokens)
    top_indices = scores.argsort()[::-1][:top_k]
    results = []
    for idx in top_indices:
        score = float(scores[idx])
        if score <= 0:
            continue
        meta = vi["metadata"][idx]
        results.append({
            "uid":             meta["uid"],
            "authorised_name": meta["authorised_name"],
            "vocabulary":      meta["vocabulary"],
            "record_richness": meta["record_richness"],
            "score":           round(score, 4),
        })
    return results


def parse_llm_response(raw):
    if not raw or str(raw).strip() in ("", "nan"):
        return None
    text = str(raw).strip()
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("```").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return None
        return None


def get_current_value(tte_dfs, vocab, uid, field_name):
    """Look up current value of a field for a TTE entity."""
    if vocab not in tte_dfs:
        return None
    df = tte_dfs[vocab]
    uid = str(uid).strip()

    rows = df[
        (df["Key UID"].astype(str).str.strip() == uid) &
        (df["Relationship Type"].str.strip() == field_name.strip())
    ]
    if rows.empty:
        return None
    return rows.iloc[0]["Related Descriptor"]


def get_merge_state(field_name, current_value, new_value):
    """
    Determine how new_value relates to current_value.

    Returns (merge_state, final_value) where:
      ADD       — field doesn't exist, add it
      APPEND    — pipe-delimited field, append new value
      REPLACE   — single value field, replace it
      DUPLICATE — value already present, no change needed
    """
    new_value = str(new_value).strip()

    if not current_value or str(current_value).strip() == "":
        return "ADD", new_value

    current_value = str(current_value).strip()

    if field_name in PIPE_DELIMITED_FIELDS:
        existing = [v.strip() for v in current_value.split("|")]
        if new_value in existing:
            return "DUPLICATE", current_value
        final = current_value + " | " + new_value
        return "APPEND", final

    if current_value == new_value:
        return "DUPLICATE", current_value

    return "REPLACE", new_value


def load_tte_dfs():
    dfs = {}
    for vocab, filename in TTE_FILES.items():
        path = os.path.join(TTE_DIR, filename)
        if os.path.exists(path):
            dfs[vocab] = pd.read_csv(path, dtype=str).fillna("")
        else:
            print(f"  WARNING: {filename} not found")
    return dfs


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

os.makedirs(OUTPUT_DIR, exist_ok=True)

print("=" * 60)
print("  join_responses.py")
print("  BM25 link → TTE lookup → review_queue.csv")
print("=" * 60)

# Load batch CSV
print(f"\n→ Loading {BATCH_CSV}")
if not os.path.exists(BATCH_CSV):
    print("  ERROR: File not found. Run build_prompts.py first.")
    exit(1)

df = pd.read_csv(BATCH_CSV, dtype=str).fillna("")
print(f"  Total rows: {len(df):,}")

if "llm_response" not in df.columns:
    print("  ERROR: No `llm_response` column found.")
    print("  Add LLM responses as column `llm_response` then rerun.")
    exit(1)

has_response = df["llm_response"].str.strip().ne("").sum()
print(f"  Rows with response: {has_response:,}")

# Load BM25 index
print(f"\n→ Loading BM25 index")
if not os.path.exists(BM25_INDEX):
    print("  ERROR: Index not found. Run 01_build_index.py first.")
    exit(1)
with open(BM25_INDEX, "rb") as f:
    index = pickle.load(f)

# Load TTE CSVs
print(f"\n→ Loading TTE CSVs")
tte_dfs = load_tte_dfs()
print(f"  Loaded: {list(tte_dfs.keys())}")

# Process
print(f"\n→ Processing")

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
    article_url   = row.get("article_url", "")
    article_title = row.get("article_title", "")
    event_type    = row.get("event_type", "")
    expected_type = row.get("expected_entity_type", "")
    row_id        = row.get("row_id", "")
    raw_response  = row.get("llm_response", "")

    if not raw_response or str(raw_response).strip() in ("", "nan"):
        continue

    parsed = parse_llm_response(raw_response)
    if not parsed:
        stats["parse_failed"] += 1
        continue

    stats["parsed"] += 1

    if not parsed.get("entity_confirmed", True):
        stats["not_confirmed"] += 1
        continue

    entity_name = parsed.get("entity_name", "").strip()
    entity_type = parsed.get("entity_type", expected_type).strip()
    fields      = parsed.get("fields", {})
    confidence  = parsed.get("confidence", "low")

    if not entity_name or not fields:
        stats["no_fields"] += 1
        continue

    # BM25 link
    vocab   = entity_type if entity_type else expected_type
    matches = bm25_search(index, entity_name, vocab)

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
    match_type = "high_match" if score >= HIGH_MATCH_THRESHOLD else "low_match"

    if match_type == "high_match":
        stats["high_match"] += 1
    else:
        stats["low_match"] += 1

    tte_uid        = top["uid"]
    tte_authorised = top["authorised_name"]
    tte_vocabulary = top["vocabulary"]
    record_richness = top["record_richness"]

    # One row per extracted field
    for field_name, field_data in fields.items():
        if not field_data:
            continue

        new_value = field_data.get("value")
        evidence  = field_data.get("evidence", "")

        if not new_value or str(new_value).strip().lower() in ("null", "none", ""):
            continue

        # Current TTE value
        current_value = get_current_value(tte_dfs, tte_vocabulary, tte_uid, field_name)

        # Merge state
        merge_state, final_value = get_merge_state(
            field_name, current_value, new_value
        )

        if merge_state == "DUPLICATE":
            stats["duplicate"] += 1
            continue  # No change needed, skip

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

# Save
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
print(f"  review_queue.csv       : {len(review_rows):,} rows → {REVIEW_CSV}")
print(f"  new_entity_candidates  : {len(new_entity_rows):,} rows → {NEW_ENTITY_CSV}")
print()
print("  NEXT STEP: Feed review_queue.csv into the Streamlit review app.")
print()
print("  KEY COLUMNS:")
print("    field         — TTE field being changed")
print("    current_value — what is in TTE right now")
print("    new_value     — what the LLM extracted")
print("    final_value   — what will be written if approved")
print("                    (new_value for ADD/REPLACE,")
print("                     appended string for APPEND)")
print("    merge_state   — ADD / APPEND / REPLACE")
print("    evidence      — exact sentence from article")
