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

Three labelled sheets, drawn from everything the AI has handled, 2015 to
now, each year in proportion to its size: 700 headlines, 300 matching
decisions and 100 articles, about ten hours in all, so five each for two
labellers. Out of them: precision, recall and F1 per stage, each with its
95% range, by language. English and Chinese only; Malay and Tamil are a
round of their own. The sizes and the maths are in `src/eval/plan.py`, and
the page explains them under **How this works**
([evaluation-how.md](evaluation-how.md)).

Common rules, all three sheets:

- The sheet given to labellers has **no model verdict column**. The
  verdict is joined after the labels are frozen.
- **The first rows of each sheet are labelled by everyone**: 50 for
  relevance and matching, 20 articles for extraction. Agreement (Cohen's
  κ) is reported; below 0.6, that sheet's rules are tightened and its
  shared rows labelled again. Where two labellers split, they settle it
  between them, or a third person does, and the agreed answer counts. It
  needs two labellers at least.
- Labels are frozen before scoring. Nothing is relabelled after seeing a
  score.
- The sampling is recorded before anyone labels, by the draw itself
  (`data/eval/0-sampling.md`: every group's size, the rows drawn from each
  year, the seed), and the labelling rule here and in the paper.
- **Every score carries its 95% range**, worked out for what it is:
  Jeffreys' interval for a share, each group scaled to its size for recall,
  whole articles redrawn for extraction. `python -m src.eval check` draws
  the sheets 2,000 times from made-up populations with known answers and
  scores them: each score within 0.2 points of the truth on average, the
  ranges holding it 94 to 98 times in 100. A test runs it on every push.
- **The labels are a fixed test set.** Labellers judge the item, never the
  AI's answer, so the labels stay true when the model or a prompt changes:
  the new version is run on the same rows (with the API calls approved) and
  scored again. Only the names a new extraction finds need labelling.
- **The labelling rules are the AI's own instructions**, in plain words:
  [labelling-guide.md](labelling-guide.md), written from each stage's
  prompt and recording which version of it. A labeller judges whether the
  AI did what it was told, so a disagreement is the AI's error, not a
  difference over what the task is. The tests stop when a prompt changes
  until the guide has been checked against it.

### Labelling on the desk

The three sheets can be labelled on the desk's **Evaluation** page instead
of in Excel. The rows and the rules are the same; only the place changes.

- **Who sees it.** Only accounts marked as evaluators
  (`python -m src.export --mark-evaluator EMAIL`, then sign out and in
  again). Reviewers never see the page, and the database refuses them its
  rows (`sql/19_evaluation.sql`).
- **No answers on the page.** For relevance and matching, the page holds
  what the labeller is shown and nothing of the model's answer: those stay
  in the key files (`data/eval/*-key.json`) on the PC that scores.
  Extraction shows the names the model found, since those are what is
  graded.
- **Relevance:** one click, Yes or No (keys Y and N). **Matching:** Same,
  Different or Can't tell (Y, N, ?). **Extraction:** per name, OK, Wrong
  or Not worth a record; for an OK name, tap any detail that is wrong;
  then select a name in the article it missed and add it, or press Nothing
  missed. Back goes to the last row and replaces its label.
- **Shared out by the database.** Rows 1 to 50 of each sheet go to every
  labeller, for the agreement. The rest are dealt one at a time, like the
  desk's records: a row nobody has labelled and nobody else holds, held
  for an hour. Nobody splits the sheet by hand, and no row is done twice.
  For extraction, where a row is a whole article, the shared rows are the
  first 20.
  Rows go only to someone who reads their language.
- **Private labels.** Labels save as they are given, into `eval_labels`,
  which no account can read. The page learns only how far along each
  sheet is.
- **A test account** marked as an evaluator can try the page; nothing it
  labels is saved.

The page also shows the last scored report and, from the desk's own
decisions, the share of changes accepted by field, by language and by
week.

```bash
python -m src.eval online publish   # the sheets' rows to the page, with the extraction articles' text the draw kept
python -m src.eval online pull      # the labels back as data/eval/returned/<sheet>-<name>.xlsx
python -m src.eval online results   # score them, and put the report on the page
```

`pull` writes the same returned sheets the Excel route produces, so
`python -m src.eval score` reads either. Test accounts' labels are left
out.

### Q1. Relevance (Job 1)

**Purpose.** Does the model say yes to the articles worth a look, and no to
the rest? It sees title and description only; so does the labeller.

**Rows given.** One per headline: link, outlet, date, title, description,
and `relevant` to fill (TRUE or FALSE). Nothing else.

**Sampling.** Every English and Chinese headline in the archive sits in one
of three groups, and each is drawn at random, each year in proportion to
its size:

| group | headlines (2026-10-22) | drawn | each row stands for |
|---|---:|---:|---:|
| the AI called it relevant | 27,941 | 200 | about 140 |
| rejected, names a TTE record | 91,182 | 200 | about 456 |
| rejected, names none | 176,146 | 300 | about 587 |

*Names a TTE record* is mechanical: the title or description holds the
name of an active TTE record of at least seven characters. Misses hide
there, so it is drawn harder, and its weight puts it back in proportion.

**Labelling rule** (from `prompts/relevance.txt`; in full in the
[guide](labelling-guide.md#relevance)). Yes when the headline and summary
report a concrete change, made or announced, to a specific named Singapore
person, organisation, building, place, event, programme or law: a death,
an appointment or departure (announced counts), a named award, a founding,
merger, closure or rename, an opening, a law passed. No for commentary,
people only mentioned or quoted, reactions, routine operations, pop-ups,
court cases, foreign brands and branches, and plans not yet in effect.

**Test.** Precision = the share of the AI's yeses a labeller also calls
relevant, with Jeffreys' 95% range. Recall = found ÷ (found + missed), each
group's share scaled up to the group's size; its range combines each
group's own Jeffreys range. By language.

**Required n.** 200 yeses give precision to about ±5.5 points at 80%.
Recall rests on the misses found, which are few, so its range is wider:
about ±8 points in the check.

### Q2. Matching (Job 3, the identity decision)

**Purpose.** Given a name from an article and a TTE record, did the model
decide "same" correctly? This is where the real errors live (romanised
Chinese names, namesakes), and where the desk's design comes from.

**Rows given.** One per (name, record) pair: the name as extracted and in
English, the sentence it came from, the article, the TTE record's name and
identifying fields, and `same` to fill (Y, N or ?).

**Sampling.** 150 pairs the AI matched (of 2,831) and 150 it turned down
(of 643: a new record made though a plausible candidate was shown, the best
of them), each year in proportion to its size. A matched pair stands for
about 19 of its kind, a turned-down one for about 4.

**Labelling rule** (from `prompts/resolution.txt`; in full in the
[guide](labelling-guide.md#matching)). `y` when the evidence and the record
describe one person or thing: the name fits, something beyond the name
agrees (employer, post, profession, field) and nothing contradicts it; `n`
when the details point elsewhere, since a shared name alone proves nothing;
`?` when the sheet does not carry enough to say. `?` is an honest answer
and is counted, not dropped. Only identity is judged, not whether the record
needs updating.

**Test.** Precision = matched pairs labelled `y` ÷ matched pairs labelled
`y` or `n`. Recall = matches found ÷ all `y`, each side scaled to its size.
The `?` rate is reported on its own and left out of both: it is the share
of decisions the desk must ask a person about. By script (Latin, Chinese).

**Required n.** 150 + 150 give precision to about ±4.8 points at 90%.

### Q3. Extraction (Job 2)

**Purpose.** Of the names an article carries, did the model pull out the
right ones with the right fields, and which did it miss? The only stage
whose recall needs someone to read the article.

**Rows given.** Per article: its text (fetched once for the page, since the
pipeline does not keep it), each name the AI found with its type, fields
and evidence, a verdict to give per name, wrong fields to tap, and the
names it missed.

**Sampling.** 50 Chinese articles (of 2,875) and 50 English (of 9,818)
that the AI found names in, each year in proportion to its size. An English
article stands for about 196, a Chinese one for about 58. About 350 names.
A missed name cannot be spotted without the text, so the draw fetches each
article's page, 10 s apart, and one that will not give its text is passed
over for the next drawn from its year; `0-sampling.md` counts them.

**Labelling rule** (from `prompts/extraction.txt`, `fields_brief.txt` and
`notability.txt`; in full in the [guide](labelling-guide.md#extraction)).
`ok` when the entity is a specific named Singapore entity of the right type
that the article gives a new fact about; `wrong` when it is not in the
article, not Singaporean, has nothing new of its own, is unnamed or has the
wrong type; `not_worth` when it has a new fact but is not notable enough
for a record. A field is wrong when the article does not support it, it is
in the wrong field (a post as Occupation, a designation as an Award), its
date is wrong, or it is not in English. *Missed* means a named Singapore
entity with a new fact of its own and no extracted row.

**Test.** Precision = `ok` ÷ marked; recall = `ok` ÷ (`ok` + missed), the
articles weighted by what they stand for. The range comes from redrawing
whole articles 2,000 times within each language (Efron's BCa), since the
names in one article are right or wrong together. Field error rate per
field. By language.

**Required n.** 100 articles give about ±6 points, the check finds.
Articles where the AI found no names are not drawn, so recall may read a
little high.

### Commands

```bash
python -m src.eval sheets           # the three sheets and their keys into data/eval/, and 0-sampling.md; fetches the extraction pages, 10 s apart (about 20 minutes)
python -m src.eval online publish   # or label them in Excel and put the returned files in data/eval/returned/
python -m src.eval score data/eval/returned   # P, R and F1 with 95% ranges, per sheet, by language; agreement
python -m src.eval check            # the method tried on made-up data with known answers
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
