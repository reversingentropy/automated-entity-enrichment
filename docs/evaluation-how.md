# How the evaluation works

What the desk's Evaluation page shows under **How this works**: the first
time an evaluator opens the page, and from its button after. The sizes and
the maths are in `src/eval/plan.py`; the draw itself is recorded in
`data/eval/0-sampling.md` on the PC that holds the AI's answers.

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
