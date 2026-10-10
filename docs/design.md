# How each stage works, and why

The measured decisions behind the pipeline, stage by stage. The README says
how to run it; this says what each part does and what was tried before it
settled. Figures are from the runs that decided them and go stale the way
any figure does.

## The prompts

Six files, but only three are ever sent to a model. The rest are injected into
those three, or kept as reference.

| File | Sent as | Template | Grows with |
|---|---|---|---|
| `relevance.txt` | Job 1 | 460 tok | ~56 tok per article, batched |
| `extraction.txt` | Job 2 | 3,000 tok | one article's text |
| `resolution.txt` | Job 3 | 3,030 tok | ~1,046 tok per entity |
| `tte/fields_brief.txt` | injected | ~520 tok | into Job 2 and Job 3 |
| `tte/description_style.txt` | injected | 245 tok | into Job 3 |
| `tte/notability.txt` | injected | ~230 tok | into Job 3 |
| `tte/occupations.txt` | **not sent** | 277 terms | enforced in code |
| `tte/vocabularies.txt` | **not sent** | 6 lists | enforced in code |
| `tte/field_rules.txt` | **not sent** | 35 kB | human reference |

Relevance is a tiny prompt over many items; extraction and resolution are large
prompts over one item each. That asymmetry is why batching transforms Job 1 and
barely helps the others.

Placeholders are filled at load by `src/shared/field_rules.py`, so both jobs
share one definition of what a field means.

Three of these files are never sent to a model. `tte/field_rules.txt` compiles
all 113 field definitions from the cataloguing guidelines and exists for people
to read. The term lists are enforced in `src/shared/field_names.py` instead:
they cost 1,550 tokens of instructions per call, and code rejects a bad value
more reliably than a prompt asks for a good one. The prompt keeps only the
semantics code cannot supply -- that a post belongs in Description rather than
Occupation -- because a rejected value is lost, while one filed correctly in
the first place is kept.

## Job 1: Relevance

Job 1 reads nothing but the title and description. Ingestion is Job 0
(`src/job0_ingest`), which inserts each feed's new articles unscored; Job 1 is
the first step that reads them.

```bash
python -m src.job1_relevance                      # full run
python -m src.job1_relevance --limit 5 --dry-run  # no writes
```

Selects articles where `relevant IS NULL`, sends title and description to
Gemini in batches, and writes a verdict for every article in the batch.

The prompt returns **only the relevant ids**, so absence means "not relevant".
`build_payload()` inverts that into an explicit verdict per article, which is
what makes a single idempotent write possible.

`batch_size` in `config/pipeline.toml` is 100. Larger batches trade recall for
precision. Measured on 548 articles, batch 100 found 16 relevant and batch 548
found 6; nothing between was measured. Articles cost ~56 tokens each, so
context is never the constraint.

## Job 2: Extraction

```bash
python -m src.job2_extraction
python -m src.job2_extraction --limit 3 --dry-run
```

For each relevant, unprocessed article, one at a time: read the page, extract
entities, write them, mark processed. The text lives in memory for the seconds
between the fetch and the write and is never stored: the table keeps what was
extracted, not what was read. Only the four or five articles a night that
passed relevance are fetched at all.

A page that cannot be read (paywall, dead link) is recorded on the row,
`fetch_error` and `fetch_attempts` from `sql/06_article_fetch.sql`, and after
three nights the queue leaves it alone; before the count existed such rows
failed again every night with nothing reporting them. A person can put text
on the row by hand for one of these, and the job will use it and clear it.

Writes are **delete-then-insert per article**, so a re-run replaces rather than
duplicates. `processed_extraction` is set last. An empty result is a success,
the model found nothing, and the article is still marked processed.

Each entity carries a **role**, `subject` or `mentioned`: whether the article
is about it or merely names it. The review deck deals the subject first and
footnotes the rest, because the first reviewer met a card for the university
that granted a degree before the man who received it. Required in the schema
so the API fills it; `sql/10_role.sql` stores it; rows from before are null
and the deck falls back to the headline.

Not storing text has one cost: re-extracting after a prompt change means
fetching the pages again, and a page that has rotted or gone behind a paywall
since is lost to the re-run. Text was stored for the first two months for
that reason; the space was judged not worth it against a 500 MB database.

The prompt also returns `entity_name_en`, an English or romanised form of any
non-English name. This is the single biggest lever on match quality: Chinese
entities went from a 40% to a 77% match rate against the authority file, and
`evidence_en`, an English translation of the verbatim quote, so a reviewer who
does not read the source language can still check a claim against its evidence.

**Field names come from the cataloguing guidelines, and are enforced in code.**
The lists in the prompts were originally written by hand and were wrong in ways
that corrupted output silently: every date field was missing its suffix
(`Year Started` where TTE stores `Year Started (yyyy)`), `Affiliations` was
missing `(groupName)`, and `Successor` and `Predecessor` were listed as
organisation fields though TTE holds those as relationships between records. A
value filed under a near-miss name creates a new field instead of extending the
real one, and nothing downstream reports it. `src/shared/field_names.py`
corrects near misses to the stored spelling and drops fields TTE does not have.

**Occupation is a closed vocabulary.** The guidelines require it to come from an
Occupations Thesaurus, which the pipeline did not have, so the model invented
terms, filing `Chairperson` as an occupation when the guidelines explicitly
exclude posts and designations. The authority file *is* the thesaurus: 253 terms
in use on two or more records, injected as `{occupations}`. Constraining to a
closed list removes the error by construction rather than by instruction.

## Job 3: Resolution

```bash
python -m src.job3_resolution
python -m src.job3_resolution --limit 2 --dry-run
```

Takes the entities from one article, retrieves candidates for each via
`match_entities`, and asks Gemini which correspond to existing records.

**Batched per article, not per entity.** Entities from the same article are
mutually informative, since a person who chairs an organisation that also matched
is evidence for both, and one combined call is far cheaper. Measured on a
10-entity article: one request at ~5.5k tokens versus ten requests at ~21k.

Resolving *everything* in a single request was measured too, since identity is
a sparse judgment that batches well in principle: 166 entities and their
candidates fit in one 154k-token prompt and came back in **36 seconds**, versus
about 15 minutes per-article. Agreement was total: 48 shared matches, zero
disagreements on which record. The two extra matches split evenly: one true
positive the per-article pass had missed, and one false positive, a name
collision it had correctly flagged.

So one-shot is roughly accuracy-neutral and 25x faster, on a sample too small
to separate the two. It stays a **backfill** option rather than the default,
because at 2-3 articles a night the per-article pass costs about 45 seconds and
the speed is worth nothing, while the per-article prompt keeps each decision in
a small context where the subtle ones are read carefully.

**Sparse output.** `CREATE_NEW` is the default and is never returned; the model
emits an entry only for entities that matched or need flagging. Absence means
new, exactly as absence from Job 1's output means not relevant. This keeps
output small enough that per-article batching stays cheap, while the three flag
actions still come back so they can be routed differently.

Candidates come from `match_entities`, searched under both `entity_name` and
`entity_name_en`, merged and de-duplicated on the canonical record. `N = 5`:
measured max similarity falls 1.00 → 0.78 → 0.68 by rank and then flattens at
0.62, so candidates beyond the fifth are no likelier to be correct.

Writes go to `candidate_matches` as *proposals*. Nothing mutates `entities`
automatically; the `applied` column is there for a later review step.

The adjudication does work that retrieval cannot. In testing it rejected an
exact-similarity 1.00 name match (a different Jacqueline Loh, affiliated with
MAS rather than the article's organisation) as `FLAG_AMBIGUOUS`, and threw out
a 0.35 near-miss that paired "Fuchun Community Club" with "Yishun Public
Library". Both decisions were made on fields, not names.

## The TTE loader

```bash
python -m src.load_tte                     # read the Storage bucket
python -m src.load_tte --source local      # read data/tte/
python -m src.load_tte --dry-run
```

Upload the dump zip exactly as TTE delivers it (`TTE-DELTA_<date>.zip`) to the
private `tte-imports` Storage bucket, or put it in `data/tte/`. Inside it,
`LDMS.zip` holds a `mod/` folder with one full export per vocabulary (21 of
them) and a `del/` folder with a list of uids to delete. Only the nine
vocabularies the pipeline holds are read; the rest, including 109 MB of
subject headings, are never unpacked. Loose `TTE-<VOCABULARY>_FULL_<date>.csv`
files work too.

The authority files are EAV: a row is an entity-to-entity **link** when
`Related UID` is set, and an **attribute** otherwise. Attributes pivot into
`entities.fields`; the links are walked once and stored as
`entities.canonical_uid`.

Each dump **replaces the previous snapshot**. Records are keyed on `Key UID`
(verified 1:1 with name, stable across snapshots), and only the new or changed
ones are written: rewriting all 52,000 left the old versions as dead space, 30
to 45 MB per load until compacted. A dry run of the September dump against
the table it had already loaded found 0 of 52,437 records to rewrite. Records
the dump dropped, or lists in `del/`, are **deleted**, scoped by vocabulary
family so a language variant whose last record went is still covered. The
exception is a record a proposal points at (`matched_uid`) or that a remaining
record uses as its canonical form: nothing cascades, so the database would
refuse the delete, and it is kept with `is_active = false` instead. If a dump
silently omits more than 10% of what it covers, the run **aborts before
writing anything**, since a truncated export should fail loudly. After a load,
the ledger and the bucket keep only that load's files.

### Canonical records

Reference data is multilingual: about 19% of entities are Chinese, Malay or
Tamil. Those records carry **no attribute fields**: they are name-only records
pointing at an English canonical that holds the data.

Resolution is at most two hops, and the two link types are mutually exclusive
(no entity has both). The loader walks them once at import and stores the
result in `entities.canonical_uid`, so query time is a single join:

```
matched entity
   ├─ has Use?  ──> follow (always same language) ──┐
   └─ no ───────────────────────────────────────────┤
                                                     ▼
                                        the PREFERRED entity
                                          ├─ English  ──> done
                                          └─ not      ──> follow CHItoENG /
                                                          MAYtoENG / TAMtoENG
                                                             ▼
                                                   English preferred record
```

`Use` never crosses languages, so a non-preferred Chinese entity must take both
hops. `ENGtoCHI` is deliberately never followed, since that would resolve an English
match *into* a field-less Chinese record.

Computing this at load rather than query time is safe because these links never
cross authority-file boundaries (verified across the full export), so a partial
import of one file still resolves correctly. It removed the `entity_links`
table: of its 83,754 rows, 63% were link types nothing queried, and the
remaining 37% answered the single question now held in a column.

`match_entities` does the trigram search and joins to the canonical record.

### Updating the authority data

TTE ships a new export every couple of months. The cycle is:

```bash
python -m src.load_tte                                   # read the bucket
python -m src.job3_resolution --requeue-stale --dry-run  # what did it change?
python -m src.job3_resolution --requeue-stale            # requeue only those
python -m src.job3_resolution                            # resolve them
```

The nightly workflow does this cycle itself: its first step loads any export in
the bucket the ledger has not seen, by filename and without downloading the
others, and requeues only if something was loaded. So the team uploads the
CSVs in the Supabase dashboard (Storage → `tte-imports`) and does nothing else.
The commands above are for doing it by hand. Leave loaded files there if you
like; the filename
is the version record, the loader checksums each file so a re-run is free, and
old snapshots cost nothing against the 1 GB allowance.

**Re-resolving everything after an update is the wrong instinct.** It is O(n)
work that grows with the corpus forever, it re-opens matches that were already
settled, and it destroys review decisions attached to them. Measured against
the September import (766 records added, 191 retired), 58 of 60 entities
sampled had a candidate set that had not changed at all.

`--requeue-stale` checks instead. Retrieval is plain SQL and costs nothing, so
every entity's candidates are compared and the model is called only where
something moved: the matched record has been retired, or a newly added record
is now a candidate so a decision of "no match" may no longer hold. On the
September import that was 7 entities rather than 188.

## Evaluation

```bash
python -m src.eval              # every case
python -m src.eval --case edge- # only the synthetic edge cases
```

Runs the resolution prompt against frozen cases in `src/eval/cases.json` and
reports what it decided. Candidates are frozen with each case, so a run needs no
database and is reproducible.

This exists because the unit suite covers code, not model behaviour, and the two
worst bugs so far were behavioural: `field_updates` absent from every match
because a Pydantic default kept it out of the schema's `required` list, and a
name collision matched rather than flagged because guidance meant for matches
leaked into the flag actions. Neither could have failed a unit test.

Cases marked `"confidence": "judgement call"` are reported rather than graded --
the right answer depends on policy you have not set yet.

## Database

| Table | Purpose |
|---|---|
| `article` | ingested articles; `relevant`, `reason`, `processed_extraction`, `text` |
| `extracted_entities` | one row per entity found in an article; `resolved` is Job 3's queue |
| `entities` | TTE authority records (~51,900), with `canonical_uid` |
| `tte_imports` | ingestion ledger, keyed by filename + checksum |
| `candidate_matches` | Job 3 resolution proposals; `applied` gates a review step |

## Design notes

**Why write once, after the model answers.** The original prototype marked
every fetched article `relevant = false` first, then flipped the relevant ones
to true. If the LLM call failed in between, those articles were permanently
false and dropped out of the `IS NULL` queue. Building the full payload first
and writing once means a failure costs nothing. This has already prevented two
data-loss incidents in practice (a quota error and a permissions error).

**Why pagination matters.** PostgREST caps every response at 1000 rows and does
so silently. An unbounded select on `entities` returns the first 1000 of 51,862
and looks complete. Anything that must see every row uses `fetch_all()`.

**The cataloguing guidelines are the schema.** `data/KOS Guidelines for Name
Construction in TTE_ver5.1.pdf` defines all 113 fields across the vocabulary
classes, and the pipeline was inventing its own until that was read.
`prompts/tte/field_rules.txt` compiles it; `prompts/tte/fields_brief.txt` is the
curated version the prompts carry. Two rules settle most misfiling:

- **Occupation** is a durable profession and explicitly EXCLUDES designations.
  `Minister for Defence`, `CEO` and `Chairperson` are posts, and belong in
  Description.
- **Title** means royalty, nobility, religious rank, honour or office
  (`Sir`, `Dr`, `Prof`, `Venerable`, `Haji`), and excludes professions.

Two more that shape work still to come: the guidelines want **at least two
sources** for a change, which makes an entity reported by two articles stronger
evidence than one; and TTE has **zero name collisions** across 24,046 people,
because catalogers append a Qualifier. A `CREATE_NEW` for a name that already
exists is therefore invalid without one.

**Recall early, precision late.** The two error types are not symmetric. A
false negative in Job 1 is permanent and silent: the article is written
`relevant = false`, leaves the queue, and nothing downstream can recover it. A
false positive in Job 3 is visible and cheap: it surfaces as a proposal a
reviewer rejects. So errors belong downstream, where they are catchable, and
each stage should be permissive relative to the one after it.

This is why `match_entities` keeps a low similarity floor. Retrieval's job is
to get the correct candidate into the set; the resolution prompt is the
precision filter. Raising the floor from 0.30 to 0.60 drops the hit rate from
80% to 43%, discarding correct candidates to prevent errors the next stage
already handles.

**Only redo what actually changed.** A TTE import is not a reason to
re-resolve everything. `src/job3_resolution/requeue.py` asks a narrower
question: which entities would a new authority file have answered differently?
Only two cases qualify: the record an entity matched has been retired, or a
newly added record is now a plausible candidate for something previously
unmatched. On the September import that turned 188 candidate re-resolutions
into 7; of 60 entities checked, 58 would have produced the identical proposal
at full LLM cost. The resolution prompt is the expensive stage, so the cheap
question is worth asking first.

**Retrieval ranks on more than the name.** Trigram similarity finds records
whose names look alike and knows nothing else. Measured over every candidate
the resolver had been shown: 32 of 211 had died before the article was
written, and for "Alan Chan" the right record sat fourth at 0.47 behind three
living strangers at 0.58. `src/job3_resolution/rank.py` applies two rules
after the SQL, both general. A person recorded as dead more than a year before
the article is dropped, unless the article is itself about a death. A candidate
sharing a distinguishing field value with the extracted entity (an affiliation,
an award, a birth year; not a nationality, which nearly everyone shares) ranks
above one that does not. Absence never demotes, only presence promotes, which
is what makes it safe for every entity type. Re-run over the 68 existing
proposals: 30 dead candidates removed, Alan Chan's record moved from fourth to
first in both his articles, nothing moved down, nothing the model had matched
was lost.

**Names do not discriminate people; fields do.** Chinese personal names are
three characters with very common surnames, so two unrelated people share a
trigram similarity of ~0.33. Every Chinese match below 0.70 in an early test
was wrong.

Embeddings were evaluated as a replacement and **rejected on measurement**.
`gemini-embedding-001` scores two *different* people (王振胡 / 王振春) at 0.800
and (萧振强 / 萧振祥) at 0.880, while the *same* person across languages
(王振胡 / "Wong, Chin Hu") scores only 0.683, so it would rank wrong people above
correct ones. A personal name carries almost no semantic content. Institutional
names do, and score well cross-language (新加坡国际调解中心 / "Singapore
International Mediation Centre" = 0.937), but people are ~62% of extracted
entities, and 768-dimension vectors for 51,862 entities would cost ~159 MB.
Not worth it.

**The romanisation is a guess, and TTE usually has nothing else to go on.**
Of the 66 Chinese-named people the nightly feed has extracted, TTE held the
Chinese name for 17. For 42 the only bridge to the file was the English form
the extractor invented, or nothing; 29 of those were resolved "create new".
The case that exposed it: 李全盛 was rendered "Lee, Choon Seng", a real record
for a banker who died in 1966, at similarity 1.00; the man is "Lee, Chuan
Seng", who scored 0.579 under the guessed spelling and sat sixth by name. The
resolver rejected the banker on his death year, as designed, and flagged; the
reviewer found the right record by search, because they had seen the Straits
Times card for the same story.

Three things follow, each measured before it was built. A candidate reached
only through the romanisation is capped at 0.90 and marked, so a guess can
never look like a certainty, and the resolver is told what the mark means.
The database function limits *name rows*, and a record with variant names
fills several, so eight rows had ended before the right record; the fetch is
now fifteen rows, deduplicated to records, then re-ranked and cut to five.
Over 73 confirmed matches the right record was first by name in 68, second in
2, fourth in 2, sixth in 1, never deeper, so fetching eight *records* finds
all 73 and the five sent to the resolver keep all 73 after the field re-rank;
replayed over every nightly entity the deeper fetch sends 2.73 → 3.11
candidates per entity, about 350 tokens a night. And the review closes the
gap: a Chinese name confirmed against an English record goes on the
approved-changes sheet as a variant name for the cataloguer to add, after
which the next Zaobao article matches on it directly. The desk also refuses a
blind create: for a non-Latin name it says the spelling was a guess and opens
a search that matches occupation and description as well as name, so
"Environment Agency" finds him whatever he was called.

Not built: offering a sibling article's matched record when it shares an
award or post (the Straits Times had "Lee Chuan Seng" with the same medal the
same day). It is the right next step if the sheets show cases the three above
miss; it costs two reads a run and no tokens.

The working approach is therefore fuzzy retrieval on both the source name and
`entity_name_en`, with the LLM discriminating on fields.

**Model settings are ordered chains**, strongest first, set in
`config/pipeline.toml` and nowhere else. A later entry is reached only when an earlier model's quota is exhausted; any
other failure surfaces immediately, since trying three models against the same
real bug just burns three models.

The order follows how many requests a job makes, not which model is best:

| Job | Requests | Chain |
|---|---|---|
| Relevance | one a night | `3.7-flash → 3.6-flash → flash-lite` |
| Extraction | one per article | `flash-lite → 3.6-flash → 3.7-flash` |
| Resolution | one per article | `3.7-flash → 3.6-flash → flash-lite` |

Relevance is a single call, so it leads with the strongest model and will never
reach the rest. Extraction leads with headroom instead. Flash Lite allows 500
requests a day against 20 for the full Flash models, keeping the others as a
reserve large enough to finish a nightly run after a backfill has drained it.
Resolution is per-article too, but it is the highest-stakes judgement here, so
it leads with strength and falls back to headroom.

They used to be overridable from `.env` and from GitHub variables, and the
three drifted: the nightly ran 3.7-flash first while a laptop `.env` ran every
job on flash-lite alone, so local results did not match the nightly's.
Changing a model is now a commit, which also records which model produced
which night.

When a model's daily allowance runs out, it is skipped for the rest of the
run. Before that, every item re-tried the spent models with waits of up to two
minutes each: Job 3 took about ten minutes an article and hit its hour limit
with nine entities left. A per-minute limit still gets the short wait Gemini
asks for.

**Batch size rarely matters at current volume.** At ~65 articles/day, a
`batch_size` of 100 and of 1000 both cost exactly one request per
day; they only diverge when the queue exceeds 100, i.e. after an outage. Larger
batches do measurably cost recall (batch 100 found 16 relevant articles where
batch 548 found 6), so the smaller value is free insurance, and 100 is what the
pipeline uses. The price shows only after a long outage: each 100 articles of
backlog is one request, against 20 a day on the full Flash models. The pipeline
uses roughly 8 of 500 daily requests; throughput has never been the constraint.
