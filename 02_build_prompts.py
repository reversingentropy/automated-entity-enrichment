"""
02_build_prompts.py — Build fact-extraction prompts from classified articles.

Reads cna_articles.csv, filters to relevant rows, and builds one self-contained
LLM prompt per article × event type.

No entity name is fed to the LLM — it finds the primary entity from the article
text, guided only by the event type and expected entity type. Fields to extract
are defined in config.py (FIELD_MAPPING).

Input:  data/cna_articles.csv
Output: outputs/prompts_for_batch.csv

Columns in output:
    row_id               — unique ID to join responses back
    article_url
    article_title
    event_type
    expected_entity_type — PERSON / ORGANISATION / FACILITY / etc.
    fields_to_extract    — comma-separated TTE fields
    prompt               — send this string to an LLM; save response as llm_response

Next step:
    Add LLM responses as column `llm_response`, then run 03_join_responses.py

Usage:
    python 02_build_prompts.py
"""

import os

import pandas as pd

import config
import utils

PROMPTS_CSV = os.path.join(config.OUTPUTS_DIR, "prompts_for_batch.csv")

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


def build_prompt(event_type, entity_type, fields, article_text):
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

utils.ensure_outputs_dir()
utils.print_header("Step 2: Building Fact-Extraction Prompts")

utils.print_step(f"Loading {config.ARTICLES_CSV}")
df = pd.read_csv(config.ARTICLES_CSV, dtype=str).fillna("")
print(f"  Total rows          : {len(df):,}")

relevant = df[
    df["Event_Type"].str.strip().str.lower().ne("not relevant") &
    df["Event_Type"].str.strip().ne("") &
    df["Singapore_Context"].str.strip().str.lower().eq("true")
].copy()
print(f"  Relevant rows       : {len(relevant):,}")

utils.print_step("Building prompts")

rows = []
skipped_no_text    = 0
skipped_no_entity  = 0
skipped_no_mapping = 0

for idx, article in relevant.iterrows():
    article_url   = article.get("URL", "")
    article_title = article.get("Title", "")
    article_text  = article.get("text", "")
    raw_event     = article.get("Event_Type", "")

    if not article_text.strip():
        skipped_no_text += 1
        continue

    for event_type in utils.parse_event_types(raw_event):
        entity_type = config.EVENT_TYPE_TO_ENTITY.get(event_type)
        fields      = config.FIELD_MAPPING.get(event_type, [])

        if not entity_type:
            skipped_no_entity += 1
            continue
        if not fields:
            skipped_no_mapping += 1
            continue

        rows.append({
            "row_id":               f"{idx}_{event_type[:25].replace(' ', '_').replace('/', '_')}",
            "article_url":          article_url,
            "article_title":        article_title,
            "event_type":           event_type,
            "expected_entity_type": entity_type,
            "fields_to_extract":    ", ".join(fields),
            "prompt":               build_prompt(event_type, entity_type, fields, article_text),
        })

pd.DataFrame(rows).to_csv(PROMPTS_CSV, index=False)

print(f"  Prompts built        : {len(rows):,}")
print(f"  Skipped — no text    : {skipped_no_text:,}")
print(f"  Skipped — no entity  : {skipped_no_entity:,}")
print(f"  Skipped — no mapping : {skipped_no_mapping:,}")
print(f"\n  Saved to: {PROMPTS_CSV}")
print()
print("NEXT STEPS:")
print("  1. Open outputs/prompts_for_batch.csv")
print("  2. For each row, send the `prompt` column to an LLM")
print("  3. Save each LLM response as column `llm_response`")
print("  4. Run: python 03_join_responses.py")
