# The archives, for a backfill

*Frozen, 17 September 2026. This did one job and is kept as the record of
how; it is not developed further. What it returned is in the table below.*

The nightly feed sees about 70 articles a day. The outlets' own archives
hold roughly 240,000 Singapore articles back to 2015, and `src/backfill`
collects them into CSV files of 50,000 rows for relevance and extraction on
an internal model:

```bash
python -m src.backfill collect all        # everything, ~240,000 rows, under twenty minutes
python -m src.backfill count              # by outlet and year, writes nothing
python -m src.backfill collect zb --from 2024-01 --to 2024-12   # one source, one span
```

`collect all` runs the three archives at once, each from its own first
month with its own progress bar: about forty minutes for everything, the
Straits Times being the long pole at 130,000 pages. ST and Zaobao are
fetched sixteen pages at a time on one connection, about a hundred a second,
backing off on a 429 or 503; `collect st --slugs` skips the fetch and takes
the headline from the URL in minutes, at the cost of the description. CNA's
`brief` is empty on most articles before 2022, so the description is the
opening of the body where the index has no brief. A sustained run tripped
Zaobao's limiter on about a quarter of one percent of pages; `repair zb`
re-fetches those gently and rewrites the files, and what remains failed
after that is articles the site has removed.

None of the three search pages yields a result without JavaScript, so none
is used. CNA's search box is Algolia, and the site publishes the search-only
key every visitor's browser uses; querying the index directly returns title,
description, date, URL and the article body, one month per request, since a
query stops at 3,000 hits however it is paged. The Straits Times and Zaobao
publish a sitemap per month for Google, back to January 2015 and January
2016; a sitemap gives URLs and dates, never titles. The section is in the
path, which is the Singapore filter the search pages could not offer. ST
caps each month at 5,000 URLs, so busy months are truncated.

Output is `url, source, title, description, category, published, month`.
The collector writes 50,000 rows a file; if the system the files are for
takes fewer, `python -m src.backfill.split --limit 49999` re-splits the
whole archive per source into `data/backfill/archive/`, plain UTF-8, one URL once.
A run resumes: every URL already in a CSV in the output directory is
skipped, and the open file is appended to. The Supabase free tier is 500
MB, which is why bodies are not collected; CNA's are a re-query away for
the few that pass relevance, and the other two are one fetch each.

## Bringing the internal model's answers back

The backfill's extraction and resolution run on an internal model, by export
and import, because Gemini's free tier was sized for four articles a night
and the archive is a hundred times that. Its rows live in the same tables as
the nightly pipeline's (`extracted_entities.article_id` is a foreign key into
`article`) behind a `backfill` flag from `sql/09_backfill_flag.sql`, which
every nightly queue and the TTE requeue exclude. Until the migration is
applied the jobs run unchanged.

```bash
python -m src.backfill prompts                          # relevance, extraction, resolution + schemas
python -m src.backfill ingest data/backfill/answers/extraction-1.csv --dry-run
python -m src.backfill resolve-export                   # one CSV row per article, candidates in one cell
python -m src.backfill resolve-import data/backfill/answers/resolution-2.csv --dry-run
python -m src.backfill dashboard articles|entities|resolutions data/backfill/answers/*.csv   # files for the console importer instead
python -m src.export --package data/dist/backfill.zip --backfill  # the backfill's own review deck
```

Everything lives under `data/backfill/`, which is ignored:

| folder | holds | keep? |
|---|---|---|
| `collected/` | what the collector writes, 50,000 rows a file | until split |
| `archive/` | the 295,279 rows as the internal system took them, 49,999 a file | yes |
| `prompts/` | the system prompts as sent, with the schemas | yes |
| `sent/` | what an export produced for the internal model | until the answers are back |
| `answers/` | what the internal model returned, its input echoed beside each answer, and `resolution-candidates.jsonl`, what each entity was offered | yes |
| `import/` | files for the console's CSV importer | until imported |
| `labels/` | the human labels | always |

The answers echo their inputs, so nothing sent needs keeping once it has
come back; the first clean-up removed 930 MB of files that were inside other
files.

The internal system reads a CSV, applies the model to one cell per row
under a system prompt, and writes the answer beside it. So every export has
an `input` cell holding everything the model needs for that row, and every
import reads the answer cell back. Every answer is validated against the
schema the nightly path enforces at the API, then written through the same
`build_rows` and `save`, so a row that arrived by CSV is indistinguishable
from one that arrived by API. What fails is counted by kind, never repaired.

What the first round trips returned, so the next ones are not a surprise:

| pass | rows | outcome |
|---|---|---|
| relevance | 295,269 of 295,279 | 27,941 relevant (9.5%). Against 69 human-labelled disagreements with the nightly model, 42% precise and 96% recall: a verdict-per-row contract says yes more than a name-the-positives one. |
| extraction | 22,996 | **8,149 in the schema** (31,477 entities); 10,281 prose instead of JSON; 3,532 the input handed back; 1,026 without the summary or evidence a reviewer needs. 80% of Zaobao articles failed. |
| ingest | 8,105 articles, 31,255 entities | into `article` and `extracted_entities` behind the flag; 44 articles were already nightly rows and stay that way |
| extraction, round 2 | 4,819 fresh + 14,843 re-run | with the anchored prompt: **3,276 (68%)** of the fresh articles in the schema against 55% for the same outlet in round 1; **1,077 (7%)** of the re-run. An article that drew prose once drew prose again (68%), and an echo drew an echo (80%): the failure is per input, and a second roll does not help. 2,549 answers were cut off mid-JSON. |
| ingest, round 2 | 4,342 articles, 17,132 entities | 12,447 backfill articles and 48,387 entities in total |
| resolution | 8,071 articles | **1,032 (13%) usable**: none followed the `{"resolutions":` anchor, but 1,032 returned the bare list, which is read as the answer it is. 6,657 returned their reasoning and never reached the JSON; 373 echoed or broke the schema. 4,128 proposals recorded (2,634 match, 1,123 new, 262 ambiguous, 107 re-query), 44,259 entities still unresolved. |

The prompts end on a hard anchor for where the answer starts and stops
(`{"entities":` ... `}`), and ship with a JSON schema for any system that can
enforce one. The internal system cannot, and the second round is the
measure of what an anchor alone buys: something on fresh input, nothing on
input that already failed, and nothing at all for the longer resolution
task. The nightly Gemini path never has this problem because the API
enforces the schema; the model does not get a vote.

Two lessons about the free tier, both paid for. Bulk writes do not go
through the API: a 30,000-request ingest ran at one article a second and
died when Supabase closed the connection, so the article and entity rows
went in as CSVs through the dashboard importer, which stops at about 10 MB
a file and aborts a file on the first duplicate key (`article.url` is unique;
44 archive articles were already nightly rows). And bulk reads do not go
through RPC: retrieval for 31,000 entities is 60,000 calls, so the authority
file is pulled once into `data/backfill/entities-cache.pkl` and matched in memory
by `src/backfill/local_match.py`, which reproduces pg_trgm's measure (37 of
40 shortlists identical, 38 of 40 top candidates) at 287 entities a second.
