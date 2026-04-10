"""
01_build_index.py — Build the BM25 index from TTE CSV files.

What this does:
  - Loads all TTE vocabulary CSVs
  - For each entity (unique Key UID), collects all alias surfaces
    (authorised name, display name, UF variants, cross-language forms)
  - Builds one BM25 index per entity type (PERSON, ORGANISATION, etc.)
  - Saves the indexes to disk as a pickle file

Run this once before anything else. Only needs to be re-run if TTE data changes.

Usage:
    python 01_build_index.py
"""

import os
import pickle
from collections import defaultdict

import pandas as pd
from rank_bm25 import BM25Okapi

import config
import utils

utils.print_header("Step 1: Building BM25 Index from TTE")


def load_tte_file(vocab_label: str, filename: str) -> pd.DataFrame:
    """Load a single TTE CSV file. Returns empty DataFrame if not found."""
    path = os.path.join(config.TTE_DIR, filename)
    if not os.path.exists(path):
        print(f"  WARNING: {filename} not found in {config.TTE_DIR}. Skipping.")
        return pd.DataFrame()
    df = pd.read_csv(path, dtype=str).fillna("")
    print(f"  Loaded {filename}: {len(df):,} rows, {df['Key UID'].nunique():,} entities")
    return df


def build_entity_surfaces(df: pd.DataFrame) -> dict:
    """
    For each unique Key UID in a TTE dataframe, collect all alias surfaces.

    Returns a dict:
    {
        uid: {
            "authorised_name": str,
            "display_name": str,
            "surfaces": [str, ...],   # all alias strings to index
            "record_richness": int,    # total number of rows for this UID
        }
    }
    """
    # Count rows per UID for record richness
    richness = df.groupby("Key UID").size().to_dict()

    entities = {}

    for uid, group in df.groupby("Key UID"):
        uid = str(uid).strip()
        authorised_name = group["Key Descriptor"].iloc[0].strip()
        display_name = authorised_name
        surfaces = set()

        # Always include the Key Descriptor (authorised form)
        if len(authorised_name) >= config.MIN_SURFACE_LENGTH:
            surfaces.add(authorised_name)

        for _, row in group.iterrows():
            rel_type = row["Relationship Type"].strip()
            related = row["Related Descriptor"].strip()

            if not related or len(related) < config.MIN_SURFACE_LENGTH:
                continue

            # Collect display name
            if rel_type == "Name (DisplayName)":
                display_name = related
                surfaces.add(related)

            # Collect alias surfaces
            elif rel_type in config.ALIAS_RELATIONSHIP_TYPES:
                surfaces.add(related)

        entities[uid] = {
            "authorised_name": authorised_name,
            "display_name": display_name,
            "surfaces": list(surfaces),
            "record_richness": richness.get(uid, 1),
        }

    return entities


def build_vocab_index(vocab_label: str, entities: dict) -> dict:
    """
    Build a BM25 index for a single vocabulary.

    Returns a dict with:
    - "bm25": BM25Okapi object
    - "surfaces": list of surface strings (one per document in index)
    - "metadata": list of entity metadata dicts (parallel to surfaces)
    """
    all_surfaces = []
    all_metadata = []

    for uid, entity in entities.items():
        for surface in entity["surfaces"]:
            all_surfaces.append(surface)
            all_metadata.append({
                "uid":            uid,
                "authorised_name": entity["authorised_name"],
                "display_name":   entity["display_name"],
                "vocabulary":     vocab_label,
                "record_richness": entity["record_richness"],
            })

    if not all_surfaces:
        print(f"  WARNING: No surfaces found for {vocab_label}")
        return {}

    # Tokenize all surfaces
    tokenized = [utils.tokenize(s) for s in all_surfaces]

    # Remove entries where tokenization produces nothing
    valid = [(s, t, m) for s, t, m in zip(all_surfaces, tokenized, all_metadata) if t]
    if not valid:
        return {}

    all_surfaces, tokenized, all_metadata = zip(*valid)

    bm25 = BM25Okapi(list(tokenized))

    return {
        "bm25":     bm25,
        "surfaces": list(all_surfaces),
        "metadata": list(all_metadata),
    }


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

utils.ensure_outputs_dir()
utils.print_step("Loading TTE files and building alias surfaces")

full_index = {}

for vocab_label, filename in config.TTE_FILES.items():
    df = load_tte_file(vocab_label, filename)
    if df.empty:
        continue

    entities = build_entity_surfaces(df)
    vocab_index = build_vocab_index(vocab_label, entities)

    if vocab_index:
        full_index[vocab_label] = vocab_index
        total_surfaces = len(vocab_index["surfaces"])
        total_entities = len(entities)
        print(f"  {vocab_label}: {total_entities:,} entities, {total_surfaces:,} alias surfaces indexed")


utils.print_step(f"Saving index to {config.BM25_INDEX_PATH}")
with open(config.BM25_INDEX_PATH, "wb") as f:
    pickle.dump(full_index, f)

# Summary
print("\n" + "─" * 40)
print("Index built successfully.")
total_surfaces = sum(len(v["surfaces"]) for v in full_index.values())
total_entities = sum(len(set(m["uid"] for m in v["metadata"])) for v in full_index.values())
print(f"  Vocabularies indexed : {len(full_index)}")
print(f"  Total entities       : {total_entities:,}")
print(f"  Total alias surfaces : {total_surfaces:,}")
print(f"  Saved to             : {config.BM25_INDEX_PATH}")
print("\nNext step: python 02_link_entities.py")
