# Architecture

The shape of the system: components, data model, state machine, contracts,
trust boundaries. [design.md](design.md) has the reasoning and the
measurements behind each decision; this is the result, without the story.
Where the two could drift, the code is correct and this file is wrong --
file an issue against it.

## Components

| Component | What it is | Talks to |
|---|---|---|
| GitHub Actions | ingestion every two hours (`job0_ingest.yml`); one nightly workflow at midnight SGT: the TTE load, the three jobs, the publish and the reviewers' email in sequence (the single-job workflows run by hand) | Supabase (`service_role`), Gemini |
| Supabase Postgres | 12 tables, RLS on all of them; until `sql/17`, a policy and a grant from before this repository let the page's key read `article` | everything |
| Supabase Storage | 2 private buckets. `desk` is created by `sql/11`; `tte-imports` is **not provisioned by any script here** -- it's a bare constant in `src/load_tte/source.py` and has to be created by hand in the dashboard | load_tte (write), desk page (read) |
| Supabase Auth | reviewer accounts, created by hand, no self-signup. Sign-up is a dashboard switch (Authentication, "Allow new users to sign up"), not something the SQL can set; every signed-in account is a reviewer, so it must be off | the desk page |
| Gemini API | 3 independent prompts: relevance, extraction, resolution | Jobs 1-3 |
| The desk page | two templates: the first desk (`src/export/desk_template.html`), still built as a zip, and the second (`prototype/desk.template.html`), the online desk: a static page with the anon key baked in, served by Cloudflare Workers from `dist/` on every push | Postgres + Storage, direct from the browser |
| RSS ingestion | `src/job0_ingest`, Job 0: reads every feed in `rss_feeds` (CNA, the Straits Times, Zaobao, and from `sql/18` Berita Harian and Tamil Murasu, whose all-section feeds are cut to their Singapore sections by `rss_feeds.keep`) and inserts the articles it has not stored; a story already stored at another address is kept as a copy marked judged (`duplicate_of`). Replaces the Supabase Edge Function `rss-ingest-v5`, whose cron job has to be switched off by hand | the feeds (HTTP), Postgres, before Job 1 runs |

## System diagram

```
 RSS feeds
 read by job0_ingest, every two hours (job0_ingest.yml)
       │
       ▼
 ┌────────────────────────────────────────────────────────────────────┐
 │ GitHub Actions -- cron (UTC), secrets from the                      │
 │ "automated-tte-enrichment" Environment                              │
 │                                                                      │
 │  nightly.yml, 16:00 UTC (midnight SGT), one after another:           │
 │  load_tte ──▶ (then, below:)                                         │
 │  job1_relevance ──▶ job2_extraction ──▶ job3_resolution ──▶ publish  │
 │        │                        │                        │          │
 │        └────────── each calls Gemini directly ───────────┘          │
 │          (relevance / extraction / resolution -- 3 separate prompts)│
 │                                                                      │
 └──────────────────────────────┬───────────────────────────────────────┘
                                 │ service_role key -- bypasses RLS entirely
                                 ▼
 ┌───────────────────────────────────────────────────────────────────┐
 │ Supabase Postgres                                                  │
 │  article ──▶ extracted_entities ──▶ candidate_matches               │
 │  entities (TTE mirror) ◀── load_tte (nightly, new uploads only)    │
 │  deck ──▶ claims / reviews                                          │
 └───────────────────┬─────────────────────────────┬───────────────────┘
                      │ anon key (RLS-gated)        │ authenticated (Auth session + RLS)
                      ▼                              ▼
        ┌──────────────────────────┐    ┌─────────────────────────────┐
        │ desk page, signed out      │    │ desk page, signed in         │
        │ - sign in, or make an      │    │ - read deck / reviews / claims│
        │   account that waits for   │    │ - take_next, decide and the   │
        │   approval (sql/20)        │    │   other queue functions only  │
        └──────────────────────────┘    └───────────────┬─────────────┘
                                                          │ authenticated (Storage RLS)
                                                          ▼
                                            ┌───────────────────────────┐
                                            │ Storage: `desk` bucket      │
                                            │ search index + NPT map, JSON│
                                            └───────────────────────────┘

        ┌──────────────────────────┐
        │ Storage: `tte-imports`     │ ◀── a person drags CSVs in, by hand
        │ bucket                     │
        └──────────────────────────┘
```

Two keys and one session type, and nothing else grants access: `service_role`
(nightly jobs, full access, never reaches a browser), `anon` (baked into the
static page like any Supabase front end -- only as powerful as the RLS
policies below make it), and `authenticated` (an `anon`-key request carrying
a signed-in reviewer's JWT, unlocked by Supabase Auth). A table with no
policy for a role is unreadable and unwritable by it, full stop. A **test
account** is marked in `app_metadata`, which only the service role can set;
`is_test_account()` makes every write policy and every desk function refuse
it, and the desk shows it the deck read-only.

## Data model

| Table | Key | Written by | Notable columns |
|---|---|---|---|
| `article` | `id` | Job 0 inserts rows; Job 1, Job 2 update them | `relevant` (null/true/false), `reason`, `duplicate_of` (a copy of a story already stored, `sql/14`), `processed_extraction`, `fetch_error`/`fetch_attempts` (gives up at 3), `backfill`, `relevance_model` |
| `extracted_entities` | `id`, `article_id → article` | Job 2 (delete-then-insert per article) | `entity_name`, `entity_name_en`, `entity_type` (8-way check), `fields` jsonb, `role` (subject/mentioned, null before `sql/10`), `resolved`, `backfill`, `extraction_model` |
| `entities` | `uid` (TTE's own Key UID) | `load_tte`, nightly when a new export is uploaded | `fields` jsonb (pivoted from TTE's EAV export), `canonical_uid → entities.uid` (precomputed at load), `is_active` (false only for a removed record something still points at), `language`, `vocabulary` |
| `tte_imports` | `filename` | `load_tte` | `checksum`, `snapshot` date, `rows_loaded` -- the ingestion ledger |
| `candidate_matches` | `id`, `extracted_id → extracted_entities` | Job 3 | `resolution_action` (5-way check, `CREATE_NEW` written explicitly since `sql/07`), `matched_uid → entities`, `field_updates` jsonb, `candidates` jsonb (what retrieval offered, kept for audit), `resolution_model` |
| `deck` | `key` (`uid:<record>` or `new:<type>:<name>`) | `publish`, full rebuild nightly | `card` jsonb -- keyed so a card that gains a new article keeps its row and its history; kept by the database for the queue: `newest`, `langs`, `grp`, `ord` (generated from the card) and `settled` (every proposal finally decided, kept by triggers) |
| `reviews` | `id`; `unique(pid)` -- one decision per proposal | `decide()` and `mark_done()` only (`sql/15`) | `card_key`, `reviewer → auth.users`, `verdict`, `decision` jsonb |
| `claims` | `card_key` | `take_next()`, `claim_card()`, `renew_card()`, `release_card()`, `decide()` | `reviewer → auth.users`, `claimed_at`; a hold not renewed for 60 minutes has lapsed, and one reviewer holds at most one record |

`entities.fields` is the one deliberate denormalisation: TTE ships EAV (one
row per attribute), and the loader pivots each entity's rows into a single
JSONB object at import time rather than joining them back together on every
read. `canonical_uid` is the same move applied to identity: TTE's
non-preferred-term and non-English links are walked once at load and stored
as a column, turning "which record actually gets the update" from a
multi-hop query into `coalesce(canonical_uid, uid)`.

## The state machine

One article's path, top to bottom. Nothing here loops; each row is a
one-way gate.

```
article.relevant              NULL ──Job 1──▶ false                (permanent, silent, unrecoverable)
                                     └───────▶ true
                                                 │
article.processed_extraction                  false ──Job 2──▶ true
                                                                  │
extracted_entities row(s)              (zero or more -- one per entity Job 2 kept)
  .resolved                                    false ──Job 3──▶ true
                                                                     │
candidate_matches row                  (one per entity that needs one -- CREATE_NEW
                                         is written explicitly, not implied by absence)

deck row                               rebuilt from scratch every night by `publish`,
                                        from every candidate_matches + entities row
     │
     ▼ a reviewer opens the card
claims row                             take_next() deals it; one per reviewer; lapses after
                                        an hour without the page renewing it
     │
     ▼ the reviewer decides, through decide()
reviews row                            one per pid; verdict + full decision json
     │
     ▼ `python -m src.export --reviews`
CSV, or a read of the `reviews` table  nothing writes back to TTE; a human applies it
```

Two things worth being exact about, because prose elsewhere in this repo
states them more gently: a false negative in `article.relevant` is not
"usually fine", it is **permanent** -- the row leaves the `IS NULL` queue and
no later stage ever sees it again. Nothing marks a proposal as having
reached TTE either: an `applied` column meant for that was never written,
and `sql/21` dropped it.

## Stage contracts

| Stage | Trigger | Reads | Writes | Idempotency | External call |
|---|---|---|---|---|---|
| Job 0 (ingest) | `job0_ingest.yml`, every two hours | `rss_feeds`, then each feed's RSS/Atom over HTTP | `article`: new urls only, with `relevant` NULL and `processed_extraction` false; a story already stored (same story key, or same outlet and title within two days) as a copy with `relevant` false and `duplicate_of` set; a stored article is never rewritten | insert-or-ignore on `url`, so an item still in the feed keeps its verdict | none to Gemini; a feed that fails is skipped, the rest still load, and the run is marked failed |
| Job 1 (relevance) | `nightly.yml`, after the TTE load | `article` where `relevant IS NULL`, batched ≤100 | `article.relevant`, `.reason`, via `update_article_relevance_batch()` | one write after the full batch returns; absence from the model's list means "not relevant" | Gemini, 1 call/night, ~460 tok + ~56 tok/article |
| Job 2 (extraction) | `nightly.yml`, after Job 1 | `article` where `relevant=true, processed_extraction=false, fetch_attempts<3` | `extracted_entities` (delete-then-insert per article), `article.fetch_error`/`.fetch_attempts`/`.processed_extraction` | `processed_extraction` set last; an empty result is still a success | Gemini, 1 call/article (~3-5/night), ~3,000 tok + page text |
| Job 3 (resolution) | `nightly.yml`, after Job 2 | `extracted_entities` where `resolved=false`, grouped by article; `match_entities()` per entity (pg_trgm, floor 0.30, top 5, re-ranked by `rank.py`) | `candidate_matches` (one row per entity needing one), `extracted_entities.resolved` | `resolved` set last | Gemini, 1 call/article, ~3,000 tok + ~1,046 tok/entity |
| `publish` | `nightly.yml`, after Job 3 | `candidate_matches` + `entities` + `extracted_entities` + `article` | `deck` (upsert on `key`), the `desk` bucket (search index + NPT map + the pipeline's status, one JSON file) | full rebuild every run; card identity is the key, not the run | none |
| `--notify` | `nightly.yml`, after the midnight run's publish | accounts (not test), `deck`, `reviews`, `claims`, `tte_imports`, the run's step outcomes | email, only to a reviewer with something to act on | the same day's state gives the same emails | SMTP, from environment secrets; printed if absent |
| `load_tte` | first step of `nightly.yml`, loading only exports not in the ledger (`--new-only`); or by hand | the `tte-imports` bucket (or `data/tte/` locally) | `entities`: only new or changed records written; records the dump dropped or lists for deletion deleted, unless a proposal or record points at them (then marked inactive); **aborts before writing** if a dump silently omits >10% of what it covers. `tte_imports` and the bucket keep only the latest load | reloading the same dump writes nothing | none |
| `--requeue-stale` | straight after a nightly load that loaded something; or by hand | diffs the new `entities` state against every unresolved match | `extracted_entities.resolved = false`, only for entities whose matched record was retired or whose candidate set gained a plausible new member | -- | none (the next Job 3 run does the work) |

## Concurrency: one reviewer per record

The database deals the records, not the page: `take_next()` hands a reviewer
the newest record in their languages and group that nobody holds and that has
something left for them, and locks it as it reads (`for update skip locked`),
so two reviewers asking at the same instant are given two records. A reviewer
holds one record at a time; the page renews the hold every three minutes
while they click or type, and a hold not renewed for an hour lapses, so a
record left on an idle screen goes back to the pile. `decide()` saves only on
a record the reviewer holds, and hands over the next one in the same call.
Reviewers have no write grant on `reviews` or `claims`: every change goes
through these `security definer` functions, which read `auth.uid()`
server-side. The whole design, for the team, is in
[load-balancing.md](load-balancing.md); `--holds` lists who has what.

## Deployment topology

Every workflow declares `environment: automated-tte-enrichment` -- secrets
are scoped to that GitHub Environment, not the repo, and without that line
`secrets.*` resolve to empty strings and the run fails at auth, not before.
Every pipeline workflow sets `concurrency: {group: pipeline,
cancel-in-progress: false}`: a second run queues behind the first rather than
racing it for the same rows -- a correctness guard (two runs would both see
`relevant IS NULL` and burn the daily Gemini quota scoring the same articles
twice), not a performance one.

The Gemini models are set in `config/pipeline.toml` only; nothing in
the environment or the workflows overrides them. Each job has a chain,
strongest first; a later model is used only when an earlier one's daily
allowance is spent, and a spent model is skipped for the rest of the run. Any
other failure surfaces immediately instead of being retried against three
models in turn.

The jobs run as steps of one workflow, `nightly.yml`, not on separate
clocks; only ingestion runs on its own, every two hours, since a feed lists
only its newest items. GitHub starts scheduled runs hours late and unpredictably; on
separate schedules a late Job 2 overlapped Job 3 and a night's entities waited
a day. Each step still runs if an earlier one failed, since each works its
own queue, and every pipeline workflow shares one concurrency group, so a
manual run waits for the night's.

The desk page is a static file on Cloudflare Workers (`wrangler.jsonc`
serves `dist/`, rebuilt on every push to `main`), with the Supabase URL and
anon key baked in. Cloudflare only hands out the page; every request after
that goes from the browser straight to Supabase, so what protects the data
is the database's grants and policies, not the host.

## Known gaps

Everything in this section is a real, current limitation, not a hedge:

- Nothing marks a proposal as having reached TTE, because nothing writes to
  TTE automatically at all.
- The zip still carries the first desk and the online page is the second;
  reviewers on a zip cannot see or collide with reviewers online, because
  the zip has no holds at all.
- `Successor` and `Predecessor`, used in `resolution.txt`'s worked examples,
  are not TTE fields -- they're modelled as relationships, and how an
  organisation rename should actually be expressed is an open policy
  question (see the README's "Known and unfinished" list).
- RSS ingestion is now Job 0, in this repository. The `rss_feeds` table it
  reads is created by no script in `sql/` (`sql/18` only adds a column and
  two rows), and the Supabase Edge Function it
  replaces has to be switched off by hand: left running, it resets `relevant`
  and `processed_extraction` on every article still in a feed.
- The live schema differs from `sql/` (checked 2026-09-30). `article.relevant`
  defaults to `false`, not NULL, so any writer must set it explicitly or the
  row is filed as already judged. `extracted_entities.evidence_en` is in no
  migration, and neither is `rss_feeds`.
- A fresh environment built from `sql/` alone will not have a `tte-imports`
  bucket -- unlike `desk`, nothing in this repo creates it.
