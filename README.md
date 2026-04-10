# KOS Pipeline — Automated Knowledge Base Population for NLB

A semi-automated pipeline that reads Singapore news articles and proposes
structured, evidence-backed updates to NLB's Knowledge Organisation System (TTE).

---

## What it does

```
Articles (already classified + NER'd)
        ↓
01_build_index.py    — Build BM25 alias index from TTE CSVs
        ↓
02_link_entities.py  — Match extracted entities to TTE records
        ↓
03_extract_facts.py  — Extract specific TTE field values via LLM
        ↓
04_build_proposals.py — Assemble structured update proposals
        ↓
05_review_queue.py   — Human review: approve / reject / flag
        ↓
06_export.py         — Export approved changes as CSV for TTE import
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set your Anthropic API key

```bash
export ANTHROPIC_API_KEY="your-key-here"
```

### 3. Put your data files in place

```
data/
├── cna_articles.csv          ← your scraped + classified articles
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

Run each script in order:

```bash
python 01_build_index.py
python 02_link_entities.py
python 03_extract_facts.py
python 04_build_proposals.py
python 05_review_queue.py
python 06_export.py
```

Each script prints what it's doing and saves output to the `outputs/` folder.
The next script reads from where the previous one left off.

---

## Tuning

Open `config.py` to adjust:

- `HIGH_MATCH_THRESHOLD` — BM25 score above which a match is considered confident.
  Start at 1.0, inspect `outputs/linked_entities.csv`, and tune up or down.
  
- `BM25_TOP_K` — number of candidate matches to return per entity.

- `MODEL` — swap `claude-haiku-4-5-20251001` for `claude-sonnet-4-6` for better
  fact extraction quality at higher cost.

---

## Outputs

| File | Description |
|------|-------------|
| `outputs/bm25_index.pkl` | Serialised BM25 index (built once) |
| `outputs/linked_entities.csv` | Entity → TTE UID matches with scores |
| `outputs/extracted_facts.csv` | LLM-extracted field values with evidence |
| `outputs/proposals.json` | Structured update proposals for review |
| `outputs/decisions.json` | All review decisions (raw) |
| `outputs/approved_changes.csv` | Approved field changes ready for TTE import |
| `outputs/decision_log.csv` | Full audit trail — also your future training data |

---

## Review queue controls

When running `05_review_queue.py`:

| Key | Action |
|-----|--------|
| `a` | Approve — add to approved_changes.csv |
| `r` | Reject — log with optional reason |
| `n` | No KB update needed — entity real, not significant enough |
| `f` | Flag for team discussion |
| `s` | Skip — come back later |
| `q` | Quit and save progress |

Progress is saved automatically. Run the script again to continue where you left off.

---

## For the demo

Open `demo/demo.ipynb` in Jupyter for a walkthrough of the pipeline
with sample outputs at each step.

```bash
jupyter notebook demo/demo.ipynb
```

---

## Project structure

```
kos_pipeline/
├── README.md
├── requirements.txt
├── config.py              ← all settings here
├── utils.py               ← shared helpers
├── 01_build_index.py
├── 02_link_entities.py
├── 03_extract_facts.py
├── 04_build_proposals.py
├── 05_review_queue.py
├── 06_export.py
├── data/
│   ├── cna_articles.csv
│   └── tte/
├── outputs/               ← created automatically
├── prompts/
│   ├── classifier_prompt.txt
│   ├── ner_prompt.txt
│   └── fact_extraction_prompt.txt
└── demo/
    └── demo.ipynb
```
