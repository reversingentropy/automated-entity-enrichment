# KOS Pipeline — Automated Knowledge Base Population for NLB

A semi-automated pipeline that reads Singapore news articles and proposes
structured, evidence-backed updates to NLB's Knowledge Organisation System (TTE).

---

## What it does

```
Articles (already classified + NER'd)
        ↓
01_build_index.py   — Build BM25 alias index from TTE CSVs  (run once)
        ↓
pipeline.py         — Link entities, extract facts via LLM, build review queue
        ↓
review_app.py       — Web UI: approve / reject / flag / export
```

`pipeline.py` does everything in one pass:

1. Filter articles to relevant only
2. Parse and filter entities (high/medium confidence, skip COUNTRY)
3. BM25 entity linking → high_match / low_match / no_match
4. Build LLM prompts for high-match rows
5. Call LLM to extract TTE field values with evidence sentences *(skipped with `--dry-run`)*
6. Look up current TTE field values from source CSVs
7. Write `outputs/review_queue.csv` — one row per proposed field change
8. Write `outputs/new_entity_candidates.csv` — entities not found in TTE

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure your LLM provider

Open `config.py` and set `PROVIDER` to `"openrouter"` or `"anthropic"`, then set the matching API key:

```bash
# OpenRouter (default)
export OPENROUTER_API_KEY="your-key-here"

# or Anthropic direct
export ANTHROPIC_API_KEY="your-key-here"
```

### 3. Put your data files in place

```
data/
├── cna_articles.csv          ← scraped + classified + NER'd articles
└── tte/
    ├── TTE-PEOPLE_FULL_20251001.csv
    ├── TTE-ORGANISATIONS_FULL_20251001.csv
    ├── TTE-GEOBUILDINGS_FULL_20251001.csv
    ├── TTE-GEOGRAPHICS_FULL_20251001.csv
    ├── TTE-EVENTS_FULL_20251001.csv
    ├── TTE-LEGALACTS_FULL_20251001.csv
    ├── TTE-PROGRAMMES_FULL_20251001.csv
    ├── TTE-AWARDS_FULL_20251001.csv
    └── TTE-COUNTRIES_FULL_20251001.csv
```

---

## Running the pipeline

### Step 1 — Build the BM25 index (once)

```bash
python 01_build_index.py
```

Reads all TTE CSVs and serialises the index to `outputs/bm25_index.pkl`.
Only needs to be re-run when TTE data is updated.

### Step 2 — Run the pipeline

```bash
python pipeline.py
```

Outputs:
- `outputs/review_queue.csv` — one row per proposed field change
- `outputs/new_entity_candidates.csv` — entities not found in TTE

**Dry run** (entity linking + prompt building, no LLM calls):

```bash
python pipeline.py --dry-run
```

Use this to inspect matching quality before spending on API calls.

### Step 3 — Review in the web UI

```bash
streamlit run review_app.py
```

Opens in your browser. Four pages:
- **Dashboard** — overview metrics and event type breakdown
- **Event Updates** — proposed field changes with current → new value, evidence, article link
- **New Entities** — no-match entities with near-duplicate warning
- **History & Export** — download approved changes as TTE-format CSV

---

## Outputs

| File | Description |
|------|-------------|
| `outputs/bm25_index.pkl` | Serialised BM25 index (built once, reused) |
| `outputs/review_queue.csv` | One row per proposed field change, pending review |
| `outputs/new_entity_candidates.csv` | Entities with no TTE match |
| `outputs/decisions.json` | All review decisions with reviewer + timestamp |
| `outputs/approved_changes.csv` | Downloaded from review UI — TTE-format import file |

---

## Approved changes export format

Downloaded from the **History & Export** page. Columns map directly to TTE import:

| Column | TTE field |
|--------|-----------|
| Key UID | Entity identifier |
| Key Descriptor | Authorised name |
| Key Vocabulary | Vocabulary (PEOPLE, ORGANISATIONS, etc.) |
| Relationship Type | Field being updated (e.g. Death Year, Affiliations) |
| Related Descriptor | Proposed new value |
| Evidence | Exact sentence from article |
| Article URL | Source |
| Reviewer | Who approved |
| Timestamp | When approved |

---

## Tuning

Open `config.py` to adjust:

- `HIGH_MATCH_THRESHOLD` — BM25 score above which a match is treated as confident.
  Default is `1.0`. Inspect `outputs/review_queue.csv` after a dry run and raise if
  you're seeing too many false positives.

- `BM25_TOP_K` — number of candidate matches returned per entity search.

- `OPENROUTER_MODEL` / `ANTHROPIC_MODEL` — swap to a stronger model for better
  fact extraction quality (at higher cost).

---

## Project structure

```
automated-entity-enrichment/
├── README.md
├── requirements.txt
├── config.py              ← all settings, thresholds, field mappings
├── utils.py               ← shared helpers (BM25, LLM call, entity parsing)
├── 01_build_index.py      ← build BM25 index from TTE CSVs (run once)
├── pipeline.py            ← end-to-end pipeline (link → extract → queue)
├── review_app.py          ← Streamlit review UI
├── data/
│   ├── cna_articles.csv
│   └── tte/
├── outputs/               ← created automatically
└── prompts/
    ├── classifier_prompt.txt
    ├── ner_prompt.txt
    └── fact_extraction_prompt.txt
```

---

## For the demo

Open `demo/demo.ipynb` in Jupyter for a step-by-step walkthrough.

```bash
jupyter notebook demo/demo.ipynb
```
