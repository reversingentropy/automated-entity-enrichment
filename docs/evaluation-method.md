# Evaluation: the method in full

The short version for the team is `docs/evaluation.md`; this is the
sampling, the labelling rules, the formulas, the commands and their
output, kept here so the numbers can be reproduced.

Two evaluations, because the system is three classifiers and a person.
The classifiers are judged on fixed labelled sheets, once, in a week
(**Quality**). The person's part is judged in use over three months
(**Quantity** and **Time**). Every number below is computed by a command
from a file or a table; nothing is typed in.

The sentence all of it exists to fill in: *the app finds X% of what the
team finds, at Y seconds per change against Z minutes, adds N changes they
would have missed, and fails mostly at [stage], on [kind of name].*

The design can say no. The measures and the target (60 to 70% recall
against the manual reading) were fixed at the team meeting of 21 September
2026, before the run; the misses are reported by stage; the manual arm's
own misses count; labellers never see the model's answer.

---

## Quality: how accurate each step is

Three labelled sheets, one fixed window (one calendar month of the feed),
about an hour per person, done in week one. Out of them: precision, recall
and F1 per stage, by language and type, in time for the paper.

Common rules, all three sheets:

- The sheet given to labellers has **no model verdict column**. The
  verdict is joined after the labels are frozen.
- **50 rows of each sheet are labelled by two people**; agreement (Cohen's
  κ) is reported. Seventeen minutes a person; it is the first thing a
  referee asks.
- Labels are frozen before scoring. Nothing is relabelled after seeing a
  score.
- The window, the sampling and the labelling rule are written down here
  and in the paper.

### Q1. Relevance (Job 1)

**Purpose.** Does the model say yes to the articles worth a look, and no to
the rest? It sees title and description only; so does the labeller.

**Files given.** `relevance-<window>.csv`, one row per article:

| column | holds |
|---|---|
| `id` | article id |
| `language` | en / zh / ms / ta |
| `title`, `description` | as the feed carried them |
| `worth_a_look` | **to fill**: `y` or `n` |

**Sampling** (positives are ~4% of the feed, so 150/150 would find two
misses and guess the rest):

- every article the model said **yes** to in the window (~100);
- **200 random** articles it said no to, for the unbiased miss rate;
- **200** "no" articles whose title or description contains a name from
  the TTE index, where misses hide; **examples only**, excluded from the
  recall estimate, and the report says so.

**Labelling rule.** *Worth a look* means: the article names a person,
organisation, place, event, award, programme or legal act that Singapore's
name authority file holds or should hold, **and** reports a fact that
would change or create its record: an appointment, an award, a death, a
rename, a merger, a founding. A mention alone is `n`.

**Test.** Against the model's verdict: precision = yeses the labeller also
marked `y` ÷ all model yeses; recall = model yeses among the labeller's
`y` ÷ all labeller `y`, computed on the yes set plus the random-no set
with inverse sampling weights (a random-no row stands for 2,700/200 ≈ 13
articles). F1 from those. Reported with 95% intervals; by language.

**Required n.** All model yeses (precision within about ±0.08); 200 random
noes (recall is bounded by misses found, ~4, so the interval is wide,
about ±0.10, and is printed rather than hidden).

**Commands.**

```bash
python -m src.eval sample relevance --window 2026-10 --out data/eval/relevance.csv
python -m src.eval score relevance data/eval/relevance-labelled.csv
```

**Output.**

```
RELEVANCE  window 2026-10  n=500 (yes 104 · random no 200 · name-hit no 196)
  P 0.81 [0.73, 0.88]   R 0.90 [0.79, 0.97]   F1 0.85
  en  P 0.85 R 0.93     zh  P 0.72 R 0.81
  agreement κ 0.78 (50 rows, 2 labellers)
  misses found in the name-hit sample: 9 (examples in data/eval/relevance-misses.csv)
```

### Q2. Matching (Job 3, the identity decision)

**Purpose.** Given a name from an article and a TTE record, did the model
decide "same" correctly? This is where the real errors live (romanised
Chinese names, namesakes), and where the desk's design comes from.

**Files given.** `matching-<window>.csv`, one row per (name, record) pair:

| column | holds |
|---|---|
| `id` | proposal id |
| `name`, `name_en` | as extracted, and the model's English rendering if any |
| `evidence` | the sentence the name was taken from |
| `tte_name`, `tte_fields` | the record's name and identifying fields (occupation, affiliations, birth year, description opening) |
| `same` | **to fill**: `y`, `n` or `?` (cannot tell from this) |

**Sampling.** 100 pairs the model matched, 100 pairs it rejected or left
out (the best candidate it was shown), random within the window.

**Labelling rule.** `y` when the evidence and the record describe one
person or thing; `n` when they describe two; `?` when the sheet does not
carry enough to say. `?` is an honest answer and is counted, not dropped.

**Test.** Precision = model matches labelled `y` ÷ model matches; recall =
model matches among all pairs labelled `y` ÷ all `y`. The `?` rate is
reported on its own: it is the share of decisions the desk must ask a
person about.

**Required n.** 100 + 100 gives about ±0.07 on each side.

**Commands.**

```bash
python -m src.eval sample matching --window 2026-10 --out data/eval/matching.csv
python -m src.eval score matching data/eval/matching-labelled.csv
```

**Output.**

```
MATCHING   window 2026-10  n=200 (matched 100 · rejected 100)
  P 0.93 [0.86, 0.97]   R 0.88 [0.80, 0.94]   F1 0.90
  cannot tell: 11 (5%)
  by script:  Latin names P 0.96 R 0.92   Chinese names P 0.84 R 0.71
  agreement κ 0.85
```

### Q3. Extraction (Job 2)

**Purpose.** Of the names an article carries, did the model pull out the
right ones with the right fields, and which did it miss? The only stage
whose recall needs someone to read the article.

**Files given.** `extraction-<window>.csv`, one row per extracted entity,
plus blank rows to add what was missed:

| column | holds |
|---|---|
| `article_id`, `language`, `url` | the article; the text is re-fetched once for this sheet, since the pipeline does not keep it |
| `entity`, `type` | as extracted |
| `fields` | the extracted fields, `Field: value` one per line |
| `verdict` | **to fill**: `ok`, `wrong` (not what the article says), `not_worth` (real, but no authority record would hold it) |
| `field_errors` | **to fill**: fields whose value is wrong, comma-separated |
| `missed` | **to fill** on the article's blank row: names the article carries that should have been extracted, one per line |

**Sampling.** 60 relevant articles in the window: 30 English, 30 Chinese,
random. About 150 to 200 entities.

**Labelling rule.** `ok` when the entity is what the article names and
would belong in the authority file; a field is wrong when the article
contradicts it or does not support it. *Missed* means a subject of the
article, or a named party to the reported fact, with no extracted row.

**Test.** Precision = `ok` ÷ extracted; recall = `ok` ÷ (`ok` + missed);
F1. Field error rate per field. By language and type.

**Required n.** 60 articles → about ±0.06 on precision; recall similar.

**Commands.**

```bash
python -m src.eval sample extraction --window 2026-10 --n 60 --out data/eval/extraction.csv   # fetches 60 articles once
python -m src.eval score extraction data/eval/extraction-labelled.csv
```

**Output.**

```
EXTRACTION window 2026-10  articles 60 (en 30 · zh 30)  entities 171  missed 38
  P 0.88 [0.82, 0.92]   R 0.71 [0.64, 0.78]   F1 0.79
  en  P 0.91 R 0.78     zh  P 0.82 R 0.59
  field errors: Affiliations 9 · Awards 4 · Birth Year 2 · Occupation 1
  agreement κ 0.81
```

### Q4. The desk's own precision (no labelling)

Of the cards dealt, the share that ended in an accepted change or a new
record; of the changes proposed, the share accepted. Computed from the
`reviews` table continuously. This is "how much of what it shows you is
worth your time", the number the team asked for under the word precision.

---

## Quantity: what it finds, against the manual reading

The parallel run: three months, or 100 manual changes, whichever first.
Everyone does both arms; no manual pair and app pair (n = 2 per arm
measures the people, not the methods).

**The one rule.** Reading before the desk, every day. Otherwise the manual
arm's recall is inflated by what the desk showed.

**The unit is the change**: which record, which field, from what to what,
because of which article. Both arms produce it.

**Files given.**

- By the team, once at the end (or at each VMS export):
  `data/vms-changes.csv` with columns `uid, field, old, new, date,
  article_url` (`article_url` optional). This is the manual arm's list. If
  changes made by hand do not all reach the VMS export, the full list is
  needed instead; otherwise they count as app misses that were not.
- By the desk, automatically: `reviews` (every decision, whole),
  `misses` (what the reading found that the app never showed: name,
  link, what should change, who, when).

**Measures.**

| measure | definition | from |
|---|---|---|
| Recall vs manual | manual changes the app proposed ÷ manual changes; and the share a reviewer accepted | VMS CSV × approved changes, matched on `uid` + `field` (values normalised) |
| Recall vs union | each arm's changes ÷ the union of both arms' changes. The fair comparison: the manual arm is not truth, it has its own misses | same join |
| Added value | accepted changes on the desk with no manual counterpart | same join, other direction |
| Misses by stage | each logged miss traced through the tables to the step that lost it | `misses` × `article`, `extracted_entities`, `candidate_matches`, `deck`, `reviews` |
| Volumes | per month: articles in feed, relevant, entities, proposals, dealt, decided, accepted | the tables |

**Miss attribution**, for each logged miss with a link:

| finding | stage |
|---|---|
| URL not in `article` | feed |
| `relevant = false` | relevance (the model's reason printed) |
| relevant, no entity with a near name (difflib ≥ 0.6 on name or English name) | extraction |
| entity `CREATE_NEW` while the TTE index returns a hit ≥ 0.9 | matching |
| matched, on the noted list | withheld by card rules |
| dealt, decided | reviewer: outcome |
| dealt, undecided | open |

**Required n.** 100 manual changes for recall within about ±0.09; the
misses table has no minimum, it is a list.

**Command.**

```bash
python -m src.export --metrics --manual data/vms-changes.csv --since 2026-10-01
```

---

## Time: what it costs to use

Front-end numbers, in use, over the same run. This is the meeting's "time
savings against human effort".

**Files given.**

- By the desk, automatically: `seconds` on every decision (from the card
  coming onto the desk to the stamp, across visits); `edits`, `dropped`,
  `foundBySearch`, `note` on every label; `at` timestamps.
- By each reviewer, weekly, in the box on the desk (`manual_log`):
  `week_start, minutes, changes`: minutes spent reading the news the old
  way, changes made by hand. Without this there is no manual time figure.
- Once at month one and once at the end: the **SUS** questionnaire (ten
  standard usability statements, 1 to 5). Five users is the classic n; the
  score is comparable across systems.

**Measures.**

| measure | definition |
|---|---|
| Seconds per decision | median, by outcome (same / amended / to create / not worth / kept) and by type |
| Time per accepted change, app | Σ seconds ÷ accepted changes |
| Time per change, manual | Σ weekly minutes ÷ Σ weekly changes |
| Latency | article date → decision date (app); article date → VMS export date (manual) |
| Friction | share of accepted changes edited or partly left out before acceptance; keep-for-review rate; records found by search |
| SUS | mean score, month one and month three |

**Required n.** Seconds stabilise after a few hundred cards, weeks not
months. The manual figure is as good as the weekly log is complete; the
report prints how many weeks are missing.

**Command.** The same `--metrics` run prints the Time section.

---

## The report

`python -m src.export --metrics` writes `data/metrics-<date>.csv` (one
row per number above) and `data/misses-<date>.csv`, and prints:

```
PARALLEL TEST · 1 Oct to 22 Dec 2026 · 83 days

PIPELINE      feed 7,412 · relevant 318 · entities 694 · proposals 412 · dealt 287 · noted 205
DESK          decided 271 by 4 · precision (card) 64% · precision (change) 79% · kept 5%
              median seconds 41 (same 22 · amended 58 · to create 35 · not worth 19) · found by search 9
VS MANUAL     manual changes 96 · app recall 68% (accepted 64%) · added value 57
              recall vs union: app 77% · manual 63%
TIME          desk 47 s per change · manual 11.2 min per change (weekly log: 4 of 12 weeks missing)
              latency: desk 1.8 days · manual 23 days
MISSES        31: feed 9 · relevance 11 · extraction 5 · matching 3 · withheld 2 · reviewer 1
QUALITY       relevance F1 0.85 · matching F1 0.90 · extraction F1 0.79 (window 2026-10)
```

Read at month one, month three, and any day in between.

---

## Schedule

| when | what |
|---|---|
| Week 1 | Three sheets sampled from one window and given out; labelled, 50 rows double; scored. Quality numbers into the paper. |
| Weeks 1 to 12 | The desk in use. Reading first. Weekly two numbers. Misses logged. |
| Month 1 | SUS. First `--metrics` read. Check the VMS list and the desk's changes line up on `uid`. |
| Month 3 (or 100 manual changes) | SUS. The report. The miss table decides what is fixed next; the next quarter's table shows whether it was. |

## Status

Built: the desk records seconds, edits, found-by-search and notes on every
decision; `reviews` and the collection command. To build: the three
`src.eval sample` / `score` sheets, the `misses` and `manual_log` tables
with their boxes on the desk, and `--metrics` with the manual-CSV join and
the miss attribution.
