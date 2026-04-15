"""
build_prompts.py

Reads cna_articles.csv, skips "not relevant" rows, and builds
one self-contained LLM prompt per event type per article.

No NER used. No prior entity knowledge. The LLM finds the entity
itself from the article text given the event type as context.

Input:
    data/cna_articles.csv
    field_mappings.json

Columns used from CSV:
    Title, URL, text, Event_Type, Singapore_Context

Output:
    outputs/prompts_for_batch.csv

    Columns:
        row_id               — unique ID to join responses back
        article_url
        article_title
        event_type           — the specific event type for this prompt
        expected_entity_type — what type of entity the LLM should find
        fields_to_extract    — TTE fields the LLM will look for
        prompt               — send this to LLM, save response as llm_response

Usage:
    python build_prompts.py

Next step:
    Add LLM responses as column `llm_response` then run join_responses.py
"""

import json
import os
import pandas as pd

# ─────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────

ARTICLES_CSV        = "data/cna_articles.csv"
FIELD_MAPPINGS_PATH = "event_type_to_field_mappings.json"
ENTITY_MAPPINGS_PATH = "event_type_to_entity_mappings.json"
OUTPUT_CSV          = "outputs/prompts_for_batch.csv"
OUTPUT_DIR          = "outputs"

# ─────────────────────────────────────────────
# LOAD FIELD MAPPINGS FROM JSON
# Edit field_mappings.json to change — no code changes needed
# ─────────────────────────────────────────────

if not os.path.exists(FIELD_MAPPINGS_PATH):
    print(f"ERROR: {FIELD_MAPPINGS_PATH} not found.")
    exit(1)

with open(FIELD_MAPPINGS_PATH, encoding="utf-8") as f:
    FIELD_MAPPING = json.load(f)

print(f"Loaded {len(FIELD_MAPPING)} event type mappings from {FIELD_MAPPINGS_PATH}")

# ─────────────────────────────────────────────
# EVENT TYPE → EXPECTED ENTITY TYPE
# ─────────────────────────────────────────────

if not os.path.exists(ENTITY_MAPPINGS_PATH):
    print(f"ERROR: {ENTITY_MAPPINGS_PATH} not found.")
    exit(1)

with open(ENTITY_MAPPINGS_PATH, encoding="utf-8") as f:
    EVENT_TYPE_TO_ENTITY = json.load(f)

print(f"Loaded {len(EVENT_TYPE_TO_ENTITY)} event type mappings from {ENTITY_MAPPINGS_PATH}")

# ─────────────────────────────────────────────
# PROMPT TEMPLATE
# Placeholders replaced with str.replace()
# No entity name fed in — LLM finds it from article text
# ─────────────────────────────────────────────

PROMPT_TEMPLATE = """You are a fact extraction tool for a Singapore library knowledge base.

This article has been classified as: EVENT_TYPE

From the article below:

1. Identify the PRIMARY entities this event happened to.
   - Must be a specific named Singapore ENTITY_TYPE
   - Must be the subject of EVENT_TYPE, not a bystander or commenter
   - Return the most specific official name as written in the article
     e.g. prefer "DBS Bank" over "DBS", "National University of Singapore" over "NUS"
   - If you cannot identify a clear primary Singapore entity, set entity_confirmed to false

2. Extract these specific fields for these entities if mentioned in the article:
FIELDS_LIST

3. For each field extracted, copy the exact sentence from the article as evidence.
   Do not paraphrase. Verbatim only.

4. Return null for any field not found in the article.

5. Keep values concise — a name, a date, or a short phrase. Not a paragraph.

Article:
ARTICLE_TEXT

Return valid JSON only. No preamble, no markdown:
{
  "entity_confirmed": true,
  "entity_name": "exact official name from article",
  "entity_type": "ENTITY_TYPE",
  "fields": {
    "Field Name": {
      "value": "extracted value or null",
      "evidence": "exact sentence from article"
    }
  },
  "confidence": "low or medium or high"
}"""

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def parse_event_types(raw):
    """
    Parse Event_Type column value into a list of individual event types.
    Handles:
      - Single: "person died"
      - Compound known: "organisation merged or acquired / split"
      - Multi-event: "person appointed or elected,person resigned or retired"
    """
    if not raw or str(raw).strip().lower() in ("not relevant", "nan", ""):
        return []

    raw = str(raw).strip()

    # First check if the whole string is a known event type
    if raw in FIELD_MAPPING or raw in EVENT_TYPE_TO_ENTITY:
        return [raw]

    # Try splitting on comma and recombining known compound types
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    result = []
    i = 0
    while i < len(parts):
        # Try combining with next part (handles "a / b" split across comma)
        if i + 1 < len(parts):
            combined = parts[i] + "," + parts[i + 1]
            if combined in EVENT_TYPE_TO_ENTITY or combined in FIELD_MAPPING:
                result.append(combined)
                i += 2
                continue
        result.append(parts[i])
        i += 1

    return result


def build_prompt(event_type, entity_type, fields, article_text):
    """Build self-contained prompt string. No entity name included."""
    fields_list = "\n".join(f"- {f}" for f in fields)
    return (PROMPT_TEMPLATE
        .replace("EVENT_TYPE",   event_type)
        .replace("ENTITY_TYPE",  entity_type)
        .replace("FIELDS_LIST",  fields_list)
        .replace("ARTICLE_TEXT", article_text[:3000])
    )


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

os.makedirs(OUTPUT_DIR, exist_ok=True)

print("=" * 60)
print("  build_prompts.py")
print("=" * 60)

# Load CSV
print(f"\n→ Loading {ARTICLES_CSV}")
df = pd.read_csv(ARTICLES_CSV, dtype=str).fillna("")
print(f"  Total rows in CSV  : {len(df):,}")

# Filter relevant rows
relevant = df[
    df["Event_Type"].str.strip().str.lower().ne("not relevant") &
    df["Event_Type"].str.strip().ne("") &
    df["Singapore_Context"].str.strip().str.lower().eq("true")
].copy()
print(f"  Relevant rows      : {len(relevant):,}")

# Build prompts
print(f"\n→ Building prompts")

rows = []
skipped_no_mapping  = 0
skipped_no_text     = 0
skipped_no_entity   = 0

for idx, article in relevant.iterrows():
    article_url   = article.get("URL", "")
    article_title = article.get("Title", "")
    article_text  = article.get("text", "")
    raw_event     = article.get("Event_Type", "")

    if not article_text.strip():
        skipped_no_text += 1
        continue

    event_types = parse_event_types(raw_event)

    for event_type in event_types:
        entity_type = EVENT_TYPE_TO_ENTITY.get(event_type)
        fields      = FIELD_MAPPING.get(event_type, [])

        if not entity_type:
            skipped_no_entity += 1
            continue

        if not fields:
            skipped_no_mapping += 1
            continue

        prompt = build_prompt(event_type, entity_type, fields, article_text)

        rows.append({
            "row_id":               f"{idx}_{event_type[:25].replace(' ', '_').replace('/', '_')}",
            "article_url":          article_url,
            "article_title":        article_title,
            "event_type":           event_type,
            "expected_entity_type": entity_type,
            "fields_to_extract":    ", ".join(fields),
            "prompt":               prompt,
        })

# Save
out_df = pd.DataFrame(rows)
out_df.to_csv(OUTPUT_CSV, index=False)

print(f"  Prompts built          : {len(rows):,}")
print(f"  Skipped — no text      : {skipped_no_text:,}")
print(f"  Skipped — no entity    : {skipped_no_entity:,}")
print(f"  Skipped — no mapping   : {skipped_no_mapping:,}")
print(f"\n  Saved to: {OUTPUT_CSV}")
print()
print("NEXT STEPS:")
print("  1. Open outputs/prompts_for_batch.csv")
print("  2. For each row, send the `prompt` column to an LLM")
print("  3. Save each LLM response in a new column called `llm_response`")
print("  4. Run: python join_responses.py")