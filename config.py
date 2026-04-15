"""
config.py — All settings in one place.
Change things here. Nothing else needs to be touched for basic configuration.
"""

import os

# ─────────────────────────────────────────────
# API PROVIDER
# Set PROVIDER to "openrouter" or "anthropic"
# ─────────────────────────────────────────────
PROVIDER = "openrouter"

# OpenRouter (https://openrouter.ai/models — find model IDs there)
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL   = "openrouter/free"  # cheap + fast default

# Anthropic direct
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL    = "claude-haiku-4-5-20251001"

# Convenience alias used in proposal metadata
MODEL = OPENROUTER_MODEL if PROVIDER == "openrouter" else ANTHROPIC_MODEL

# ─────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────
DATA_DIR        = "data"
TTE_DIR         = os.path.join(DATA_DIR, "tte")
OUTPUTS_DIR     = "outputs"
PROMPTS_DIR     = "prompts"

# Input — your existing scraped + classified articles
ARTICLES_CSV    = os.path.join(DATA_DIR, "cna_articles.csv")

# Outputs — each script writes here, next script reads from here
BM25_INDEX_PATH      = os.path.join(OUTPUTS_DIR, "bm25_index.pkl")
LINKED_CSV           = os.path.join(OUTPUTS_DIR, "linked_entities.csv")
FACTS_CSV            = os.path.join(OUTPUTS_DIR, "extracted_facts.csv")
PROPOSALS_JSON       = os.path.join(OUTPUTS_DIR, "proposals.json")
DECISIONS_JSON       = os.path.join(OUTPUTS_DIR, "decisions.json")
APPROVED_CSV         = os.path.join(OUTPUTS_DIR, "approved_changes.csv")
DECISION_LOG_CSV     = os.path.join(OUTPUTS_DIR, "decision_log.csv")

# ─────────────────────────────────────────────
# TTE FILES
# Maps NER entity label → TTE CSV filename
# ─────────────────────────────────────────────
TTE_FILES = {
    "PERSON":       "TTE-PEOPLE_FULL_20260401.csv",
    "ORGANISATION": "TTE-ORGANISATIONS_FULL_20260401.csv",
    "FACILITY":     "TTE-GEOBUILDINGS_FULL_20260401.csv",
    "LOCATION":     "TTE-GEOGRAPHICS_FULL_20260401.csv",
    "EVENT":        "TTE-EVENTS_FULL_20260401.csv",
    "LEGAL_ACT":    "TTE-LEGALACTS_FULL_20260401.csv",
    "PROGRAMME":    "TTE-PROGRAMMES_FULL_20260401.csv",
    "AWARD":        "TTE-AWARDS_FULL_20260401.csv",
    "COUNTRY":      "TTE-COUNTRIES_FULL_20260401.csv",
}

# ─────────────────────────────────────────────
# BM25 SETTINGS
# ─────────────────────────────────────────────
BM25_TOP_K            = 5      # Return top-k candidates
HIGH_MATCH_THRESHOLD  = 1.0    # BM25 score above this = confident match. Tune empirically.
MIN_SURFACE_LENGTH    = 3      # Skip alias surfaces shorter than this (avoids noisy short strings)

# Relationship types in TTE that represent name surfaces worth indexing
ALIAS_RELATIONSHIP_TYPES = {
    "Name", "Name ",           # trailing space variant exists in some TTE files
    "Name (DisplayName)",
    "UF",                      # Used For — non-preferred variants, aliases, acronyms
    "ENGtoCHI", "CHItoENG",
    "ENGtoMAL", "MALtoENG",
    "ENGtoTAM", "TAMtoENG",
}

# ─────────────────────────────────────────────
# EVENT TYPE → EXPECTED ENTITY TYPE
# Used to scope BM25 search to the right TTE vocabulary
# ─────────────────────────────────────────────
EVENT_TYPE_TO_ENTITY = {
    "person died":                                          "PERSON",
    "person appointed or elected":                          "PERSON",
    "person resigned or retired":                           "PERSON",
    "person changed affiliation or party":                  "PERSON",
    "person received award":                                "PERSON",
    "person received honour or title":                      "PERSON",
    "person got married":                                   "PERSON",
    "person renamed":                                       "PERSON",
    "organisation received award":                          "ORGANISATION",
    "organisation renamed":                                 "ORGANISATION",
    "organisation merged or acquired":                      "ORGANISATION",
    "organisation merged or acquired, when organisation split": "ORGANISATION",
    "organisation dissolved or closed":                     "ORGANISATION",
    "organisation relocated":                               "ORGANISATION",
    "organisation ownership changed":                       "ORGANISATION",
    "organisation restructured or rebranded":               "ORGANISATION",
    "building demolished":                                  "FACILITY",
    "building destroyed by fire":                           "FACILITY",
    "building opened":                                      "FACILITY",
    "building given heritage or conservation status":       "FACILITY",
    "building given heritage or conservation status/national monument": "FACILITY",
    "building repurposed or converted":                     "FACILITY",
    "building closed or ceased operations":                 "FACILITY",
    "building renamed":                                     "FACILITY",
    "building ownership changed or en bloc sale":           "FACILITY",
    "building ownership changed or en bloc sale,building renamed": "FACILITY",
    "Year/Month/Day building completed":                    "FACILITY",
    "place or area renamed":                                "LOCATION",
    "place closed or removed":                              "LOCATION",
    "place closed or removed, street name expunged":        "LOCATION",
    "award criteria or format changed":                     "AWARD",
    "award discontinued":                                   "AWARD",
    "award renamed":                                        "AWARD",
    "award replaced by another":                            "AWARD",
    "event cancelled or discontinued":                      "EVENT",
    "event renamed":                                        "EVENT",
    "event postponed or rescheduled":                       "EVENT",
    "event relocated":                                      "EVENT",
    "programme launched":                                   "PROGRAMME",
    "programme ended or discontinued":                      "PROGRAMME",
    "law enacted or amended":                               "LEGAL_ACT",
    "law repealed":                                         "LEGAL_ACT",
}

# ─────────────────────────────────────────────
# EVENT TYPE → TTE FIELDS TO EXTRACT
# Tells the fact extractor exactly what to look for
# ─────────────────────────────────────────────
FIELD_MAPPING = {
    # PEOPLE
    "person died": [
        "Death Year (yyyy)", "Death Month (mm)", "Death Day (dd)"
    ],
    "person appointed or elected": [
        "Affiliations(groupName)", "Occupation", "Active Years", "Description"
    ],
    "person resigned or retired": [
        "Active Years", "Affiliations(groupName)", "Occupation", "Description"
    ],
    "person changed affiliation or party": [
        "Affiliations(groupName)"
    ],
    "person received award": [
        "Awards"
    ],
    "person received honour or title": [
        "Achievements"
    ],
    "person got married": [
        "Spouse"
    ],
    "person renamed": [
        "Name"
    ],
    # ORGANISATIONS
    "organisation received award": [
        "Awards"
    ],
    "organisation renamed": [
        "Name", "Successor"
    ],
    "organisation merged or acquired": [
        "Successor", "Predecessor", "Year Ended (yyyy)", "Month Ended (mm)", "Day Ended (dd)",
        "Year Started (yyyy)", "Month Started (mm)", "Day Started (dd)", "Parent Organisation"
    ],
    "organisation merged or acquired, when organisation split": [
        "Successor", "Predecessor", "Year Ended (yyyy)", "Month Ended (mm)", "Day Ended (dd)",
        "Year Started (yyyy)", "Month Started (mm)", "Day Started (dd)", "Parent Organisation"
    ],
    "organisation dissolved or closed": [
        "Year Ended (yyyy)", "Month Ended (mm)", "Day Ended (dd)"
    ],
    "organisation relocated": [
        "Street Address", "Postal Code", "Description"
    ],
    "organisation ownership changed": [
        "Description", "Parent Organisation"
    ],
    "organisation restructured or rebranded": [
        "Parent Organisation", "Description", "Successor", "Predecessor"
    ],
    # GEOBUILDINGS
    "building demolished": ["Description"],
    "building destroyed by fire": ["Description"],
    "building opened": ["Description"],
    "building given heritage or conservation status": ["Description"],
    "building given heritage or conservation status/national monument": ["Description"],
    "building repurposed or converted": [
        "Feature Type", "Feature Code", "Feature Class", "Description"
    ],
    "building closed or ceased operations": ["Description"],
    "building renamed": ["Name"],
    "building ownership changed or en bloc sale": ["Description"],
    "building ownership changed or en bloc sale,building renamed": ["Name", "Description"],
    "Year/Month/Day building completed": [
        "Year Completed (yyyy)", "Month Completed (mm)", "Day Completed (dd)"
    ],
    # GEOGRAPHICS
    "place or area renamed": ["Name"],
    "place closed or removed": ["Description"],
    "place closed or removed, street name expunged": ["Description"],
    # AWARDS
    "award criteria or format changed": ["SN"],
    "award discontinued": ["SN"],
    "award renamed": ["Name", "Successor"],
    "award replaced by another": ["SN", "Successor", "Predecessor"],
    # EVENTS
    "event cancelled or discontinued": ["SN"],
    "event renamed": ["Name"],
    "event postponed or rescheduled": ["SN"],
    "event relocated": ["Description"],
    # PROGRAMMES
    "programme launched": ["Description", "Successor", "Predecessor"],
    "programme ended or discontinued": ["Description", "Successor", "Predecessor"],
    # LEGAL ACTS
    "law enacted or amended": ["SN"],
    "law repealed": ["SN"],
}
