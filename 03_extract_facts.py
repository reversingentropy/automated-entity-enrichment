"""
03_extract_facts.py — Extract specific field values using LLM (Call 2).

What this does:
  - Loads linked_entities.csv (output of step 2)
  - For each high-confidence entity match, calls the LLM to extract
    specific TTE field values from the article text
  - Uses the field mapping from config.py to tell the LLM exactly what to look for
  - Saves results to extracted_facts.csv

Only processes high_match rows. Low matches and no_match rows
are passed straight to proposals as human-review candidates.

Usage:
    python 03_extract_facts.py

Note: This makes one LLM API call per high_match entity. Watch your API costs.
      With ~100 high matches, expect ~$0.05-0.10 at Haiku pricing.
"""

import json
import os
import time

import pandas as pd

import config
import utils

utils.print_header("Step 3: Extracting Facts via LLM")

# ─────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────

utils.print_step(f"Loading linked entities from {config.LINKED_CSV}")
linked_df = pd.read_csv(config.LINKED_CSV, dtype=str).fillna("")

# Only extract facts for high matches
high_matches = linked_df[linked_df["match_type"] == "high_match"]
print(f"  Total linked rows : {len(linked_df):,}")
print(f"  High matches      : {len(high_matches):,} (will call LLM for these)")
print(f"  Others            : {len(linked_df) - len(high_matches):,} (passed through as-is)")

# Load original articles to get full text
utils.print_step(f"Loading article text from {config.ARTICLES_CSV}")
articles_df = pd.read_csv(config.ARTICLES_CSV, dtype=str).fillna("")
article_text_map = dict(zip(articles_df["URL"], articles_df["text"]))

# Load fact extraction prompt template
prompt_path = os.path.join(config.PROMPTS_DIR, "fact_extraction_prompt.txt")
with open(prompt_path, "r") as f:
    prompt_template = f.read()

# ─────────────────────────────────────────────
# EXTRACT FACTS
# ─────────────────────────────────────────────

utils.print_step("Extracting facts (LLM calls)")
print(f"  Model: {config.MODEL}")
print("  This may take a few minutes...\n")

results = []
success_count = 0
fail_count = 0

for i, (_, row) in enumerate(high_matches.iterrows()):
    entity_name  = row["entity_name"]
    entity_type  = row["entity_type"]
    event_type   = row["event_type"]
    article_url  = row["article_url"]
    article_title = row["article_title"]

    # Get article text
    article_text = article_text_map.get(article_url, "")
    if not article_text:
        print(f"  [{i+1}/{len(high_matches)}] SKIP — no article text: {article_title[:60]}")
        fail_count += 1
        continue

    # Get fields to extract for this event type
    fields = utils.get_fields_for_event(event_type)
    if not fields:
        print(f"  [{i+1}/{len(high_matches)}] SKIP — no field mapping for: {event_type}")
        fail_count += 1
        continue

    # Build prompt
    fields_list = "\n".join(f"- {f}" for f in fields)
    # Use first 2000 chars of article to control costs; most facts are in early paragraphs
    article_excerpt = article_text[:3000]

    prompt = prompt_template.format(
        entity_name=entity_name,
        entity_type=entity_type,
        event_type=event_type,
        fields_list=fields_list,
        article_text=article_excerpt,
    )

    print(f"  [{i+1}/{len(high_matches)}] {entity_name} | {event_type[:40]}")

    try:
        response_text = utils.call_llm(prompt)
        parsed = utils.parse_json_response(response_text)

        if parsed and parsed.get("entity_confirmed", True):
            extracted_fields = parsed.get("fields", {})
            confidence = parsed.get("confidence", "low")
            entity_confirmed = parsed.get("entity_confirmed", True)

            results.append({
                **row.to_dict(),
                "llm_confidence":    confidence,
                "entity_confirmed":  entity_confirmed,
                "extracted_fields":  json.dumps(extracted_fields),
                "fact_status":       "extracted",
            })
            success_count += 1

            # Show what was extracted
            non_null = {k: v["value"] for k, v in extracted_fields.items() if v and v.get("value")}
            if non_null:
                print(f"         → {non_null}")
            else:
                print(f"         → No field values found in article")

        else:
            # LLM says article isn't about this entity — flag as false match
            results.append({
                **row.to_dict(),
                "llm_confidence":    "low",
                "entity_confirmed":  False,
                "extracted_fields":  "{}",
                "fact_status":       "entity_not_confirmed",
            })
            print(f"         → Entity not confirmed in article")
            fail_count += 1

    except Exception as e:
        print(f"         → ERROR: {e}")
        results.append({
            **row.to_dict(),
            "llm_confidence":    "",
            "entity_confirmed":  False,
            "extracted_fields":  "{}",
            "fact_status":       f"error: {str(e)[:100]}",
        })
        fail_count += 1

    # Small delay to avoid rate limiting
    time.sleep(0.2)

# ─────────────────────────────────────────────
# SAVE
# ─────────────────────────────────────────────

utils.ensure_outputs_dir()
facts_df = pd.DataFrame(results)
facts_df.to_csv(config.FACTS_CSV, index=False)

print("\n" + "─" * 40)
print("Fact extraction complete.")
print(f"  Successful extractions : {success_count:,}")
print(f"  Failed / skipped       : {fail_count:,}")
print(f"  Results saved to       : {config.FACTS_CSV}")
print("\nNext step: python 04_build_proposals.py")
