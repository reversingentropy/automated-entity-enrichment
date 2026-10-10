# Automated Entity Enrichment

A scheduled pipeline that reads Singapore news articles, decides which ones
imply a change to a knowledge base record, extracts the entities involved, and
resolves them against the TTE authority file. What it proposes goes to a
librarian, one card at a time, and nothing is written to the authority file
by a machine.

Built around Supabase (Postgres) and Gemini, running on GitHub Actions. The
historical archive runs the same code through an institutional model.

## How it works

```
RSS feeds ──> article   (Job 0, src/job0_ingest: the first step of every run,
                         reading the feed list from the rss_feeds table)
                  │
   ┌──────────────┴───────────────────┐
   │ 1  RELEVANCE            00:00 SGT│  queue: relevant IS NULL
   │    one batched call, title+desc  │  writes: relevant, reason
   └──────────────┬───────────────────┘
                  │ relevant = true
   ┌──────────────┴───────────────────┐
   │ 2  EXTRACTION            after 1 │  queue: NOT processed_extraction
   │    fetch, extract, keep entities │  writes: extracted_entities
   └──────────────┬───────────────────┘
                  │
   ┌──────────────┴───────────────────┐    ┌──────────────────────────┐
   │ 3  RESOLUTION            after 2 │◄───│ TTE LOADER    nightly    │
   │    trigram + canonical_uid       │    │ new CSVs in the bucket   │
   │    per article, sparse output    │    │ upsert by Key UID        │
   └──────────────┬───────────────────┘    │ replaces the last dump   │
                  │ candidate_matches      └────────────┬─────────────┘
                  │                                     ▼
   ┌──────────────┴───────────────────┐            entities
   │ 4  CARDS          src/export     │  one card per record, article order,
   └──────────────┬───────────────────┘  subject first; one note per field
                  │
   ┌──────────────┴───────────────────┐
   │ 5  REVIEW           the desk     │  a person: same record? then each change;
   └──────────────┬───────────────────┘  a zip, or online with one reviewer per card
                  │
   ┌──────────────┴───────────────────┐
   │ 6  SHEETS            two CSVs    │  every decision; approved changes for
   └──────────────────────────────────┘  a cataloguer, plus variant names
```

Stages 1-3 and the loader run nightly, and so does the deck publish for
stage 5. Stage 4 is `src/export/cards.py`; stage 5 is the review desk, the
same page built as a zip or served with the database behind it
([docs/online.md](docs/online.md)); stage 6 is what the desk hands back,
and nothing applies it. Ordering between the jobs is a convenience, not
a requirement: each stage's queue is a column, so a job run out of order
simply finds no work.

This diagram is the pipeline's shape, not the system's. It leaves out
GitHub Actions' scheduling and secrets, the desk's accounts and RLS, the
storage buckets, and what's actually guaranteed under concurrent reviewers.
[docs/architecture.md](docs/architecture.md) has the rest: components,
the full data model, an end-to-end state machine, a contract per stage
(reads/writes/idempotency), the trust boundaries, and what's still not
enforced. Read that first if you're meeting this system cold.

## Layout

```
src/
  shared/           the Supabase and Gemini clients, response schemas, paged
                    reads, the TTE field rules and field-name corrections
  job1_relevance/   fetch -> prompt -> update
  job2_extraction/  fetch -> scraper -> prompt -> update
  job3_resolution/  fetch -> candidates -> rank -> prompt -> update
                    requeue: what a TTE update invalidates
  load_tte/         the authority file from the Storage bucket into entities
  export/           cards (the review data), desk_template.html (the review
                    page), package (a zip for reviewers), proposals (CSV),
                    reviews (collect decisions)
  eval/             the resolution prompt against frozen cases (cases.json)
  backfill/         the outlets' archives: collect, split, bodies, prompts
                    for an internal model, ingest and resolve by CSV
config/             pipeline.toml: models, thinking, batching and pacing
prompts/            relevance, extraction, resolution; tte/ holds what the
                    code injects into them or enforces after
sql/                numbered setup scripts, run in order
tests/              offline unit tests, no network
docs/               design.md, gotchas.md, review.md, backfill.md, the
                    explainer page and the paper
data/               ignored: the archive, the model's answers, built packages
.github/workflows/  one workflow per job, plus tests
```

## Setup

### Install

```bash
uv sync
```

`pyproject.toml` says what the project depends on and `uv.lock` pins the
versions; CI installs with `uv sync --frozen`, which fails if the two drift.

```bash
uv run pytest
```

Every test runs offline against fixtures: no network, no credentials, no
Gemini calls. Integration behaviour is checked by running a job with
`--dry-run` and `--limit`.

### Environment

Copy `.env.example` to `.env` and fill in. `.env` is gitignored.

| Variable | Where | Notes |
|---|---|---|
| `SUPABASE_URL` | `.env` + GitHub secret | project URL |
| `SUPABASE_KEY` | `.env` + GitHub secret | **the `sb_secret_` key**: full access, used by the jobs and exports, never put in a page |
| `GEMINI_API_KEY` | `.env` + GitHub secret | from aistudio.google.com/apikey |
| `SUPABASE_ANON_KEY` | `.env` only | the public key; read only when building the online desk's page (`--site`) |

Everything that changes what the pipeline does (which model answers each
job, how hard it thinks, how work is batched and paced) is in one file,
`config/pipeline.toml`. Nothing in `.env` or GitHub overrides it, and it is
checked when a job starts, so a misspelt setting stops the run. Changing a
setting is a commit, so the history says which settings produced which
night's results.

### GitHub Actions

Secrets live in the `automated-tte-enrichment` **Environment**, so every
workflow declares `environment: automated-tte-enrichment`; without that line
`secrets.*` are empty strings. The environment needs no variables. Actions
does not read `.env`. Scheduled workflows fire from the
default branch only, hours late under load, and are disabled after 60 days of
inactivity. So the jobs run one after another in a single workflow,
`nightly.yml`: on separate clocks, a late Job 2 overlapped Job 3 and a
night's entities waited a day. Each single-job workflow remains, to run by
hand, and all of them share one queue so nothing runs alongside anything else.

### Database

Enable `pg_trgm` (Database, Extensions), then run `sql/` in order in the SQL
editor: `01` to `05` create the tables, the retrieval function and the
resolution queue; `06` to `10` are the later migrations (body fetch,
recorded CREATE_NEW, the dropped claim function, the backfill flag, the
article subject); `11` is the online desk (row level security everywhere,
the deck, reviews, claims and access-request tables, the bucket); `12` is
the field test (which model answered, the evaluation's two logs). Each ends
with an explicit `grant ... to service_role`, which Supabase does not always
do for you.

## Running it

```bash
python -m src.job0_ingest      [--dry-run]              # new feed items into article, unscored
python -m src.job1_relevance  [--limit N] [--dry-run]   # verdict per unscored article
python -m src.job2_extraction [--limit N] [--dry-run]   # entities per relevant article
python -m src.job3_resolution [--limit N] [--dry-run]   # proposals per article's entities
python -m src.job3_resolution --requeue-stale [--dry-run]   # after a TTE import
python -m src.load_tte [--source local] [--dry-run]     # the authority file, from the bucket
python -m src.eval [--case edge-] [--show]              # the resolution prompt on frozen cases
python -m src.export --package data/dist/tte-desk.zip   # the review desk, as a file
python -m src.export --publish                          # the deck to the database, nightly
python -m src.export --site data/dist/site              # the online desk's page, served locally
python -m src.export --requests                         # who has asked for an account
python -m src.export --reviews data/reviews/            # collect what they decided (or --reviews table)
python -m src.export --weekly                           # the week's approved changes, as the reviewers' Excel file
python -m src.export --notify [--print-only]            # the daily email, only to reviewers with something to do
python -m src.export --logs                             # the evaluation's change and weekly logs, as CSVs
python -m src.export                                    # proposals as a CSV
python -m src.backfill collect all                      # the archives, see docs/backfill.md
```

Every job follows one rule: **the queue is a column, and nothing is marked
done until the write succeeds.** A failed run leaves rows queued for the next.

## Where to read more

- [docs/architecture.md](docs/architecture.md): the system's shape -- components, data model, state machine, stage contracts, trust boundaries, known gaps
- [docs/design.md](docs/design.md): what each stage does and the measurements behind each decision
- [docs/review.md](docs/review.md): the cards, the desk, sending it out, what comes back
- [docs/online.md](docs/online.md): the desk with the database behind it: accounts, one reviewer per card, collecting
- [docs/evaluation.md](docs/evaluation.md): the evaluation for the team: accuracy, effectiveness, efficiency, satisfaction, reliability
- [docs/evaluation-method.md](docs/evaluation-method.md): the method in full: sampling, labelling rules, formulas, commands
- [docs/backfill.md](docs/backfill.md): the archives and the internal model, with what the round trips returned
- [docs/gotchas.md](docs/gotchas.md): what cost an evening
- [docs/pipeline.html](docs/pipeline.html): the explainer for someone who has never seen any of this
- [docs/paper.md](docs/paper.md): the paper for the IFLA Symposium on AI 2026

## Where it stands

Figures as of 28 September 2026; [docs/numbers.md](docs/numbers.md) has the full
funnel, regenerated with `python -m src.export --numbers`.

| Stage | State |
|---|---|
| 1. Relevance | twice a day (midnight and noon SGT), queue drained; 149 of 3,511 live articles relevant |
| 2. Extraction | twice a day; 309 entities from the live articles |
| 3. Resolution | twice a day; all 309 resolved (101 matched, 206 new, 2 unsure) |
| TTE loader | first step of each run, for any new dump uploaded; 52,437 records from TTE-DELTA_20260901 |
| 4. Consolidation | merged into the card layer; not a pipeline stage yet |
| 5. Review | the desk online (accounts, a card held by one reviewer until stamped) and as a zip; 170 cards, none decided yet; two trial rounds on the offline desk (14 and 38 records) |
| 6. Export | `--weekly`: the week's approved changes as the reviewers' Excel file; no automatic apply, by design |
| Archive | 295,279 articles (2015 on), 27,941 relevant, 12,447 through extraction (48,387 entities), all answered by the internal model. The answers are kept in files; the articles and entities are still in the database, about 100 MB, until moved out. `python -m src.backfill proposals` writes the unreviewed spreadsheet |

Two reviewers have been through the desk; the second's questions were about
working in parallel, which the online version answers once `sql/11` is run
and the accounts exist ([docs/online.md](docs/online.md)). Run
`sql/10_role.sql` so the extraction model's "subject" reaches the deck;
until then the headline stands in.

Known and unfinished:

- Two evaluation cases fail: `edge-homonym-same-profession` matches two
  namesakes who share a profession, and `edge-unnamed-role` matches "the
  Health Minister" to a person.
- Extraction has no evaluation set, so every Job 2 prompt change is unvalidated,
  and given the run-to-run variance above, validating one needs repeated runs.
- Two policy questions are open: what to do when an article contradicts the
  authority record (a different birth year), and how to express an
  organisation rename, since `Successor`/`Predecessor` are not TTE fields.
