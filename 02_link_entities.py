"""
02_link_entities.py — Link extracted entities from articles to TTE records.

What this does:
  - Loads your existing cna_articles.csv (already classified + NER'd)
  - For each relevant article, identifies the primary entity based on event type
  - Searches the BM25 index to find matching TTE records
  - Classifies each match as: high_match, low_match, or no_match
  - Saves results to linked_entities.csv

Usage:
    python 02_link_entities.py
"""

import json

import pandas as pd

import config
import utils

utils.print_header("Step 2: Linking Entities to TTE Records")

# ─────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────

utils.print_step(f"Loading articles from {config.ARTICLES_CSV}")
df = pd.read_csv(config.ARTICLES_CSV, dtype=str).fillna("")

total = len(df)
relevant = df[
    (df["Event_Type"] != "not relevant") &
    (df["Event_Type"] != "") &
    (df["Singapore_Context"].str.lower() == "true")
]
print(f"  Total articles       : {total:,}")
print(f"  Relevant articles    : {len(relevant):,}")

utils.print_step("Loading BM25 index")
index = utils.load_index()
print(f"  Vocabularies loaded  : {list(index.keys())}")

# ─────────────────────────────────────────────
# LINK ENTITIES
# ─────────────────────────────────────────────

utils.print_step("Linking entities to TTE records")

results = []
stats = {"high_match": 0, "low_match": 0, "no_match": 0, "no_entity_found": 0, "skipped_vocab": 0}

for _, row in relevant.iterrows():
    article_url    = row.get("URL", "")
    article_title  = row.get("Title", "")
    article_text   = row.get("text", "")
    raw_event_type = row.get("Event_Type", "")

    # Parse event types (handles compound types like "a,b")
    event_types = utils.parse_event_types(raw_event_type)
    if not event_types:
        continue

    # Parse extracted entities from NER step
    entities = utils.parse_entities(row.get("extracted_entities", ""))

    for event_type in event_types:
        expected_vocab = utils.get_expected_entity_type(event_type)

        if not expected_vocab:
            stats["skipped_vocab"] += 1
            continue

        if expected_vocab not in index:
            stats["skipped_vocab"] += 1
            continue

        # Find entities matching the expected type
        primary_candidates = utils.find_primary_entities(entities, expected_vocab)

        if not primary_candidates:
            # No entity of expected type found in NER output
            stats["no_entity_found"] += 1
            results.append({
                "article_url":       article_url,
                "article_title":     article_title,
                "event_type":        event_type,
                "entity_name":       "",
                "entity_type":       expected_vocab,
                "entity_confidence": "",
                "tte_uid":           "",
                "tte_authorised_name": "",
                "tte_display_name":  "",
                "tte_vocabulary":    expected_vocab,
                "match_score":       0.0,
                "match_type":        "no_entity_found",
                "record_richness":   0,
                "top_candidates":    "[]",
            })
            continue

        # Link each primary entity candidate
        for entity in primary_candidates:
            entity_name = entity.get("entity_name", "").strip()
            if not entity_name:
                continue

            # BM25 search scoped to expected vocabulary
            candidates = utils.search_index(index, entity_name, expected_vocab, top_k=config.BM25_TOP_K)

            if not candidates:
                match_type = "no_match"
                top = {}
                stats["no_match"] += 1
            else:
                top = candidates[0]
                score = top["score"]
                if score >= config.HIGH_MATCH_THRESHOLD:
                    match_type = "high_match"
                    stats["high_match"] += 1
                else:
                    match_type = "low_match"
                    stats["low_match"] += 1

            results.append({
                "article_url":         article_url,
                "article_title":       article_title,
                "event_type":          event_type,
                "entity_name":         entity_name,
                "entity_type":         expected_vocab,
                "entity_confidence":   entity.get("confidence", ""),
                "tte_uid":             top.get("uid", ""),
                "tte_authorised_name": top.get("authorised_name", ""),
                "tte_display_name":    top.get("display_name", ""),
                "tte_vocabulary":      expected_vocab,
                "match_score":         top.get("score", 0.0),
                "match_type":          match_type,
                "record_richness":     top.get("record_richness", 0),
                "top_candidates":      json.dumps(candidates[:3]),  # top-3 for review UI
            })

# ─────────────────────────────────────────────
# SAVE
# ─────────────────────────────────────────────

utils.ensure_outputs_dir()
linked_df = pd.DataFrame(results)
linked_df.to_csv(config.LINKED_CSV, index=False)

# Summary
print("\n" + "─" * 40)
print(f"Entity linking complete.")
print(f"  High matches (→ fact extraction) : {stats['high_match']:,}")
print(f"  Low matches  (→ human review)    : {stats['low_match']:,}")
print(f"  No match     (→ new entity flag) : {stats['no_match']:,}")
print(f"  No entity found in NER           : {stats['no_entity_found']:,}")
print(f"  Skipped (vocab not in index)     : {stats['skipped_vocab']:,}")
print(f"\n  Results saved to: {config.LINKED_CSV}")
print(f"  Total rows: {len(results):,}")
print(f"\nTIP: Open {config.LINKED_CSV} and inspect high_match rows.")
print("     Adjust HIGH_MATCH_THRESHOLD in config.py if needed.")
print("\nNext step: python 03_extract_facts.py")
