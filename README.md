# KOS Pipeline — Automated Knowledge Base Population for NLB

A semi-automated pipeline that reads Singapore news articles and proposes
structured, evidence-backed updates to NLB's Knowledge Organisation System (TTE).

---

## What it does

```
Articles (already classified)
        ↓
01_build_index.py   — Build BM25 alias index from TTE CSVs  (run once)
        ↓
02_build_prompts.py — Build one fact-extraction prompt per article × event type
        ↓
[send prompts to LLM, save responses as column `llm_response`]
        ↓
03_join_responses.py — BM25 link + TTE lookup + merge state → review queue
        ↓
review_app.py       — Web UI: approve / reject / flag / export
```

Every proposed change traces to an exact sentence in the source article.
No TTE writes without human approval.

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure your LLM provider

Open `config.py` and set `PROVIDER` to `"openrouter"` or `"anthropic"`, then set the matching API key:

```bash
export OPENROUTER_API_KEY="your-key-here"
# or
export ANTHROPIC_API_KEY="your-key-here"
```

### 3. Put your data files in place

```
data/
├── cna_articles.csv          ← scraped + classified articles
└── tte/
    ├── TTE-PEOPLE_FULL_*.csv
    ├── TTE-ORGANISATIONS_FULL_*.csv
    ├── TTE-GEOBUILDINGS_FULL_*.csv
    ├── TTE-GEOGRAPHICS_FULL_*.csv
    ├── TTE-EVENTS_FULL_*.csv
    ├── TTE-LEGALACTS_FULL_*.csv
    ├── TTE-PROGRAMMES_FULL_*.csv
    ├── TTE-AWARDS_FULL_*.csv
    └── TTE-COUNTRIES_FULL_*.csv
```

Update `TTE_FILES` in `config.py` if your filenames differ.

---

## Running the pipeline

### Step 1 — Build the BM25 index (once per TTE update)

```bash
python 01_build_index.py
```

Reads all TTE CSVs and saves the index to `outputs/bm25_index.pkl`.

### Step 2 — Build fact-extraction prompts

```bash
python 02_build_prompts.py
```

Outputs `outputs/prompts_for_batch.csv` — one prompt per article × event type.

### Step 3 — Get LLM responses (manual)

Send each row's `prompt` column to an LLM. Save the responses as a new column
called `llm_response` in `outputs/prompts_for_batch.csv`.

### Step 4 — Build the review queue

```bash
python 03_join_responses.py
```

Outputs:
- `outputs/review_queue.csv` — one row per proposed field change
- `outputs/new_entity_candidates.csv` — entities not found in TTE

### Step 5 — Review in the web UI

```bash
streamlit run review_app.py
```

Opens in your browser. Four pages:
- **Dashboard** — overview metrics and event type breakdown
- **Event Updates** — proposed field changes with current → new value, evidence, article link
- **New Entities** — no-match entities with OneSearch verification link
- **History & Export** — download approved changes as TTE-format CSV

---

## Outputs

| File | Description |
|------|-------------|
| `outputs/bm25_index.pkl` | Serialised BM25 index (built once, reused) |
| `outputs/prompts_for_batch.csv` | LLM prompts (Step 2), then with responses added (Step 3) |
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
  Default is `1.0`. Inspect `outputs/review_queue.csv` after running Step 4 and raise
  if you're seeing too many false positives.

- `BM25_TOP_K` — number of candidate matches returned per entity search.

- `FIELD_MAPPING` — which TTE fields to extract per event type.

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
├── 02_build_prompts.py    ← build fact-extraction prompts
├── 03_join_responses.py   ← link entities, build review queue
├── review_app.py          ← Streamlit review UI
├── data/
│   ├── cna_articles.csv
│   └── tte/
├── outputs/               ← created automatically
└── demo/
    └── demo.ipynb         ← step-by-step walkthrough
```

---

## For the demo

```bash
jupyter notebook demo/demo.ipynb
```
