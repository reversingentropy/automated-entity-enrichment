# Evaluation

The one plan for evaluating the system: what is measured, how, by whom,
and when. The last part, **On the Evaluation page**, is the text the desk's
Evaluation page shows, word for word: the site build reads it from here.

| Part | The question | How | The team's time | Status |
|---|---|---|---|---|
| 1. Accuracy | Is each AI step right: relevance, extraction, matching? | Three labelled sheets, on the Evaluation page | About 5 hours each for two people, once | Built |
| 2. Satisfaction | Is it good to use? | The standard ten-statement usability survey | 2 minutes, twice | Statements written |
| 3. Reliability | Does it just run? | The nightly run history | None | Nothing to build |
| 4. Efficiency | Is it faster than reading the news by hand? | To discuss with the team | | Not decided |

Effectiveness (how much of the team's own news-driven work the AI finds)
is not measured; the reason is under **Not measured**.

## 1. Accuracy: is each step right?

The AI does three things, and each gets a sheet:

- **Relevance:** 700 headlines. Is each one worth a look for TTE? Yes or
  No, from the headline and summary alone, as the AI judges it.
- **Extraction:** 100 articles. For each name the AI found: OK, Wrong, or
  Not worth a record; any wrong detail tapped; and any name it missed added.
- **Matching:** 300 pairs. Is the one in the news the same as the TTE
  record? Same, Different, or Can't tell.

### How the rows are drawn

From everything the AI has handled, 2015 to now, in English and Chinese.
Every item sits in one group, and each group is drawn at random, each year
given rows in proportion to its size. Nothing is chosen by hand.

| Sheet | Group | Items | Drawn | Each row stands for |
|---|---|---:|---:|---:|
| Relevance | the AI kept it | 27,941 | 200 | about 140 |
| | the AI dropped it, and it names a TTE record | 91,182 | 200 | about 456 |
| | the AI dropped it, and it names none | 176,146 | 300 | about 587 |
| Matching | the AI matched it | 2,831 | 150 | about 19 |
| | the AI turned down the best record it was shown | 643 | 150 | about 4 |
| Extraction | English articles the AI found names in | 9,818 | 50 | about 196 |
| | Chinese articles the AI found names in | 2,875 | 50 | about 58 |

Counts as of the draw on 22 October 2026. The AI's misses are rare and hide
where a TTE name appears, so dropped headlines naming a TTE record are drawn
harder ("names" is mechanical: the title or summary holds an active TTE
record's name of seven characters or more). Each row's weight puts its
group back in proportion when the scores are added up. An extraction
article whose page will not load is passed over for the next one drawn from
its year. The draw writes all of this down, with the random seed, in
`data/eval/0-sampling.md` before anyone labels.

### The rules

- Labellers never see the AI's answer for relevance or matching. The
  answers stay in key files on the PC that scores.
- The rules are the AI's own instructions in plain words (**On the
  Evaluation page**, below), each recording the version of the prompt it
  was written from. When a prompt changes, the tests stop until the rules
  have been checked against it.
- Everyone labels the same first rows: 50 headlines, 50 pairs and 20
  articles. Agreement between labellers (Cohen's kappa) is measured on
  them, so it needs two labellers at least. Below 0.6, that sheet's rules
  are tightened and its shared rows labelled again. A row two people split
  on is settled between them, or by a third, and the agreed answer counts.
- The rest are dealt out by the database, one person each, held for an
  hour. Only accounts marked as evaluators see the page.
- Labels are frozen before scoring. Nothing is relabelled after seeing a
  score.
- The labels are a fixed test set. They judge the item, not the AI's
  answer, so when the model or a prompt changes, the new version is run on
  the same rows and scored again; only names a new extraction finds need
  labelling.

### What comes out

For each step: precision, recall and F1, each with its 95% range, by
language. Matching also by Latin and Chinese names, with the share marked
Can't tell. Extraction also with the wrong details per field.

How sure: about ±5.5 points on relevance precision, ±4.8 on matching
precision, ±6 on extraction. Recall rests on rare misses, so its range is
wider (about ±8 on relevance). Drawn 2,000 times from made-up populations
with known answers, each score was within 0.2 points of the truth on
average, and its range held the truth 94 to 98 times in 100
(`python -m src.eval check`, run with the tests on every push).

Alongside, the Evaluation page shows, from the desk's own decisions, the
share of suggested changes reviewers accepted, by field, language and week.

### Time

About 10 hours in all, counting the shared rows twice: roughly 1¾ hours on
relevance (about 8 seconds a row), 2 on matching (about 20 seconds), 6 on
extraction (about 3 minutes an article). Five hours each for two labellers.

### What it cannot tell you

- Nearly every row comes from the archive run on the internal model. The
  nightly pipeline adds about 1 in 100; scoring it means running it on the
  same rows.
- Articles where the AI found no names are not on the extraction sheet, so
  extraction recall may read a little high.
- Which prompt made each older answer was not recorded.
- Malay and Tamil are not in it; they get a round of their own.

## 2. Satisfaction: is it good to use?

At month one and month three, everyone using the desk completes the
standard usability survey (SUS) on Form.gov.sg: ten statements, each scored
1 (strongly disagree) to 5 (strongly agree). Two minutes.
`python -m src.eval sheets --only sus` writes the statements.

Scoring: odd statements score the answer minus 1, even ones 5 minus the
answer; the ten added and multiplied by 2.5 give a score out of 100. About
68 is average; above 80 is good. Read beside what the desk records: how
often a suggestion was edited before it was accepted, how often a record
was kept for review, how often a reviewer searched for a record the AI
should have offered, and the notes left on cards.

## 3. Reliability: does it just run?

From the run history of the **Nightly** workflow on GitHub: nights it ran,
nights it failed and at which step (relevance, extraction, resolution,
publishing, loading a new TTE export). Nobody logs anything.

```bash
gh run list --workflow nightly.yml --limit 100
```

## 4. Efficiency: to discuss with the team

Not decided. The question: is the desk faster than reading the news by
hand? The desk already times every decision; the open question is how to
get the by-hand figure.

- **Option A, a parallel run with a swap.** Two months. Month one, half the
  team uses the desk and half works by hand; month two they swap, so each
  person is compared with themselves (with two on each side and no swap,
  the result would mostly show who is faster). Everyone writes down two
  numbers a week: hours on news-driven TTE work, and changes made. In a
  by-hand month, nobody opens the desk. Out comes minutes per change, desk
  against by hand, per person. Too few people and weeks for a statistical
  test, but a large difference will show. The risk: the weekly numbers get
  forgotten (the desk's weekly boxes were removed for that reason).
- **Option B, one question in the survey.** "Before the desk, how many
  hours a week did you spend reading news for TTE, and how many changes
  came of it?" Rougher, and costs nothing.

To settle: which option; if A, who is on which side, for how long, and
where the weekly numbers go.

## Not measured: effectiveness

How much of the team's own news-driven work the AI finds. The TTE dumps
answer most of it already, and measuring it again during use would cost
three months of everyone logging every change for numbers too small to
read.

Comparing seven TTE dumps from September 2024 to August 2026, only **12%
of the team's record changes involve a name our three news sources
printed** in that period or the two months before; correcting for names in
an article's body but not its headline (1.6 times, measured where full
text was extracted) puts it near **19%**. The rest is cataloguing work. So
two people reading the news by hand make perhaps 20 to 30 news-driven
changes a quarter, and a recall measured on 25 changes carries a margin of
about ±19 points. Of the 280 additions whose name the news printed, the archive run
had found 82 (29%; 65% for deaths), a floor while about 15,500 relevant
articles are still unextracted (`scripts/news_reach.py`).

## When

| When | What |
|---|---|
| Week 1 | Label the three sheets |
| Month 1 | First survey; read the desk's numbers |
| Month 3 | Second survey; the one-page result |

Efficiency fits in once it is decided.

## What comes out

One page that fills in: *relevance, extraction and matching are X, Y and Z%
right; reviewers accept N% of what the desk suggests; users score it S out
of 100; it ran on M of P nights.*

## Commands

```bash
python -m src.eval sheets                       # draw the three sheets (fetches the extraction pages, 10 s apart, about 20 minutes)
python -m src.eval online publish --no-fetch    # put them on the Evaluation page
python -m src.export --mark-evaluator EMAIL     # let someone label (they sign out and in again)
python -m src.eval online pull                  # the labels back
python -m src.eval online results               # score them, and show the report on the page
python -m src.eval check                        # the scoring tried on made-up data with known answers
```

Before the first publish, `sql/19_evaluation.sql` is run in Supabase. The
sizes and the maths are in `src/eval/plan.py`, the drawing in
`src/eval/sheets.py`, the scoring in `src/eval/score.py`.

## Status

Built: the three sheets and their scoring, the check, the Evaluation page
with its rules and **How this works**, the desk's timing and acceptance
figures, and the survey's statements. Not built: a single command for the
one-page result, and whatever efficiency needs once it is decided.

## On the Evaluation page

Each section below is one piece of the page: **How this works** and its
maths, then each sheet's rules, shown before its rows and a click away on
every row. Each sheet's rules are written from the prompt the AI runs on,
so a labeller checks the AI by the rules it was given, and record the
version of the prompts they were written from; when a prompt changes, the
tests stop until the section has been checked against it
(`tests/test_eval_online.py`).

## How the evaluation works {#how}

We check the AI's three steps against people. Its answers are on file for
everything it has handled since 2015; a fair sample of them is drawn, and
you label it.

- **Relevance:** 700 headlines. Is each one worth a look for TTE?
- **Extraction:** 100 articles. Did the AI find the right names, and miss
  any?
- **Matching:** 300 pairs. Is the one in the news the same as the TTE
  record?

Rows come from every year, each year in proportion to its size. English
and Chinese only: Malay and Tamil get a round of their own.

For relevance and matching you never see the AI's answer. Your labels are
compared with its answers on the PC that holds them, and only the scores
come back here.

Everyone labels the same first rows: 50 headlines, 50 pairs and 20
articles. That shows how far labellers agree. The rest are dealt out, one
person each.

## The maths, and how we checked it {#maths}

### How sure a score is

A share counted on *n* random rows is within this margin of the truth 95
times in 100: `margin = 1.96 × √(p × (1 − p) ÷ n)`, where *p* is the share.

- 200 headlines the AI kept, 80% right: ±5.5 points
- 150 pairs it matched, 90% right: ±4.8 points
- 100 articles: about ±6 points, since the names in one article are right
  or wrong together

### Why some rows count for more

The AI kept 1 headline in 10. Extra rows are drawn from those it dropped,
so its rare misses turn up. Each row then stands for the headlines like it:
a kept one for about 140, a dropped one naming a TTE record for about 460,
any other dropped one for about 590. Scores add rows up by what they stand
for, so the extra rows do not tilt the result. Extraction does the same
with its 50 Chinese and 50 English articles.

### Recall

Recall is the share of the real yeses the AI caught, so it rests on the
misses, which are rare. Each group's range is worked out on its own, by
Jeffreys' method, which stays honest even when a group shows no misses at
all; the groups are then added up by size.

### Extraction

Its range comes from redrawing the 100 articles 2,000 times, whole
articles at a time, corrected for the few articles that miss many names
(Efron's BCa).

### Agreement

On the shared rows: `kappa = (agreement seen − agreement by chance) ÷
(1 − agreement by chance)`. 1 is perfect; 0 is no better than chance.
Below 0.6, the rules are tightened and those rows labelled again.

### How we checked it

We made up populations the size of ours, with known answers, drew each
sheet from them 2,000 times exactly as here, and scored every draw.

- On average, each score was within 0.2 points of the true value.
- The 95% ranges held the true value 94 to 98 times in 100.

The check runs with the tests on every change (`python -m src.eval check`).

### What it cannot tell you

- Nearly every row comes from the archive run on the internal model. The
  nightly pipeline adds about 1 in 100; scoring it means running it on
  these same rows, with no new labelling.
- Articles where the AI found no names are not on the extraction sheet, so
  extraction recall may read a little high.
- An old article whose page no longer loads is passed over for the next
  one from the same year.
- Which prompt made each older answer was not recorded.

## Relevance {#relevance}

Written from `prompts/relevance.txt` (version 0ad40ab9).

**Relevant** if the headline or summary reports a real change to a named
Singapore person, organisation, building, place, event, programme or law:

- someone died, was appointed or left a post (announced counts), retired,
  married, or received a named award
- an organisation was set up, merged, closed, renamed or moved
- a building opened, closed, was demolished, renamed or given heritage status
- an event was cancelled, postponed or moved; a programme began or ended;
  a law was passed or changed

**Not relevant:** opinion pieces, people only quoted or mentioned,
reactions, court cases, routine updates, pop-ups, foreign brands, and plans
not yet in effect.

## Extraction {#extraction}

Written from `prompts/extraction.txt` (version b44367f8), `prompts/tte/fields_brief.txt` (version a3f7f141) and `prompts/tte/notability.txt` (version 5ee3450f).

For each name the AI found:

- **OK:** a named Singapore entity the article says something new about.
- **Wrong:** not in the article, not Singaporean, only mentioned or quoted,
  or not a real name ("the ministry").
- **Not worth a record:** real and new, but too minor for TTE.

For an OK name, tap any detail that is wrong: not in the article, in the
wrong field (a post like "CEO" as Occupation), a wrong date, or not in
English.

Then select anyone it missed in the article and add them, or press
**Nothing missed**.

## Matching {#matching}

Written from `prompts/resolution.txt` (version 87536818).

- **Same:** the name fits and something else agrees (job, employer,
  field), with nothing contradicting it.
- **Different:** the details point to someone else. A matching name alone
  is not enough.
- **Can't tell:** not enough to decide either way.

Judge who it is, not whether the record needs updating. A Chinese name the
AI wrote in English can be wrong: go by the details.

## For every sheet {#general}

Not sure? Make your best call. Work on your own: do not compare answers
until everyone has finished.
