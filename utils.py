"""
utils.py — Shared helper functions used across all scripts.
"""

import json
import os
import pickle
import re
import time
from datetime import datetime

import anthropic
import pandas as pd

import config


# ─────────────────────────────────────────────
# TOKENIZER
# ─────────────────────────────────────────────

def tokenize(text: str) -> list[str]:
    """
    Simple tokenizer for BM25.
    Lowercases, splits English on whitespace/punctuation,
    and splits Chinese/CJK into individual characters.
    """
    text = text.lower().strip()
    tokens = []
    current = []

    for char in text:
        if "\u4e00" <= char <= "\u9fff" or "\u3400" <= char <= "\u4dbf":
            # CJK character — flush current English token, add CJK char as its own token
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

    # Remove very short tokens (single chars except CJK already handled)
    tokens = [t for t in tokens if len(t) >= 2 or "\u4e00" <= t <= "\u9fff"]
    return tokens


# ─────────────────────────────────────────────
# BM25 INDEX
# ─────────────────────────────────────────────

def load_index() -> dict:
    """Load the saved BM25 index from disk."""
    if not os.path.exists(config.BM25_INDEX_PATH):
        raise FileNotFoundError(
            f"Index not found at {config.BM25_INDEX_PATH}. "
            "Run 01_build_index.py first."
        )
    with open(config.BM25_INDEX_PATH, "rb") as f:
        return pickle.load(f)


def search_index(index: dict, entity_name: str, vocab: str, top_k: int = None) -> list[dict]:
    """
    Search the BM25 index for an entity name within a specific TTE vocabulary.

    Returns a list of candidate dicts sorted by score descending:
    [{"uid", "authorised_name", "display_name", "vocabulary", "record_richness", "score"}]
    """
    top_k = top_k or config.BM25_TOP_K

    if vocab not in index:
        return []

    vocab_index = index[vocab]
    query_tokens = tokenize(entity_name)

    if not query_tokens:
        return []

    scores = vocab_index["bm25"].get_scores(query_tokens)
    top_indices = scores.argsort()[::-1][:top_k]

    results = []
    for idx in top_indices:
        score = float(scores[idx])
        if score <= 0:
            continue
        meta = vocab_index["metadata"][idx]
        results.append({
            "uid":            meta["uid"],
            "authorised_name": meta["authorised_name"],
            "display_name":   meta.get("display_name", meta["authorised_name"]),
            "vocabulary":     meta["vocabulary"],
            "record_richness": meta["record_richness"],
            "matched_surface": vocab_index["surfaces"][idx],
            "score":          round(score, 4),
        })

    return results


# ─────────────────────────────────────────────
# EVENT TYPE HELPERS
# ─────────────────────────────────────────────

def parse_event_types(event_type_str: str) -> list[str]:
    """
    Parse event type string. Handles compound types separated by comma.
    Returns list of individual event type strings, stripped.
    """
    if not event_type_str or event_type_str.strip().lower() == "not relevant":
        return []
    # Split on comma but be careful — some event types contain commas
    # Known compound separator pattern: event_type,event_type (no space after comma)
    parts = [p.strip() for p in event_type_str.split(",") if p.strip()]
    # Rejoin pairs that belong together (e.g. "building ownership changed or en bloc sale,building renamed")
    result = []
    i = 0
    while i < len(parts):
        combined = parts[i]
        # Check if combined form exists in mapping
        if i + 1 < len(parts):
            candidate = combined + "," + parts[i + 1]
            if candidate in config.EVENT_TYPE_TO_ENTITY or candidate in config.FIELD_MAPPING:
                result.append(candidate)
                i += 2
                continue
        result.append(combined)
        i += 1
    return result


def get_expected_entity_type(event_type: str) -> str | None:
    """Return the expected NER entity type for a given event type."""
    return config.EVENT_TYPE_TO_ENTITY.get(event_type.strip())


def get_fields_for_event(event_type: str) -> list[str]:
    """Return TTE fields to extract for a given event type."""
    return config.FIELD_MAPPING.get(event_type.strip(), [])


# ─────────────────────────────────────────────
# ENTITY PARSING
# ─────────────────────────────────────────────

def parse_entities(entities_json: str) -> list[dict]:
    """
    Parse the extracted_entities JSON column from cna_articles.csv.
    Returns list of entity dicts or empty list on failure.
    """
    if not entities_json or pd.isna(entities_json):
        return []
    try:
        entities = json.loads(entities_json)
        return entities if isinstance(entities, list) else []
    except json.JSONDecodeError:
        return []


def find_primary_entities(entities: list[dict], expected_type: str) -> list[dict]:
    """
    Filter entities to those matching the expected type.
    Returns sorted by confidence: high > medium > low.
    Excludes COUNTRY type (countries aren't updated via this pipeline).
    """
    confidence_order = {"high": 0, "medium": 1, "low": 2}
    filtered = [
        e for e in entities
        if e.get("entity_label") == expected_type
        and e.get("entity_label") != "COUNTRY"
    ]
    return sorted(filtered, key=lambda e: confidence_order.get(e.get("confidence", "low"), 3))


# ─────────────────────────────────────────────
# ANTHROPIC API CALL
# ─────────────────────────────────────────────

def call_llm(user_message: str, system_message: str = None, retries: int = 3) -> str:
    """
    Call the Anthropic API. Returns the response text.
    Retries on rate limit errors with exponential backoff.
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    messages = [{"role": "user", "content": user_message}]

    for attempt in range(retries):
        try:
            kwargs = {
                "model": config.MODEL,
                "max_tokens": 1024,
                "messages": messages,
            }
            if system_message:
                kwargs["system"] = system_message

            response = client.messages.create(**kwargs)
            return response.content[0].text

        except anthropic.RateLimitError:
            wait = 2 ** attempt
            print(f"  Rate limited. Waiting {wait}s...")
            time.sleep(wait)
        except anthropic.APIError as e:
            print(f"  API error: {e}")
            if attempt == retries - 1:
                raise

    raise RuntimeError("Max retries exceeded")


# ─────────────────────────────────────────────
# JSON PARSING (LLM OUTPUT)
# ─────────────────────────────────────────────

def parse_json_response(text: str) -> dict | None:
    """
    Parse JSON from LLM response. Handles markdown code blocks.
    Returns None on failure.
    """
    # Strip markdown code blocks if present
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("```").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return None
        return None


# ─────────────────────────────────────────────
# MISC
# ─────────────────────────────────────────────

def ensure_outputs_dir():
    """Create outputs directory if it doesn't exist."""
    os.makedirs(config.OUTPUTS_DIR, exist_ok=True)


def now_str() -> str:
    """Return current timestamp as ISO string."""
    return datetime.now().isoformat()


def print_header(title: str):
    """Print a section header."""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_step(step: str):
    """Print a step message."""
    print(f"\n→ {step}")
