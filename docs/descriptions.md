# Descriptions: one addition from many articles

Status: built 3 Nov 2026, not yet run. Before the first run: `sql/22_description_drafts.sql` in Supabase. Until a
record is combined, its card shows each article's own sentences, one row each, as before. Decided: Flash only (Flash
Lite was not good enough); corrections as a row the reviewer ticks; new sentences at the end of TTE's text;
Achievements left as they are.

## The problem

A description screen takes longer to read than the articles behind it. Reviewers said it is too complex: it does
not cut the decision or the reading time.

What the screen shows today, on real cards:

- **Pang Kin Keong** (four articles): his existing sentence struck out and rewritten, the Land Transport Authority
  chairmanship added three times, and "a distinguished public administrator", which is praise, not a fact.
- **Chan Yeng Kit** (five articles): one fact, his SPH Media appointment, in five wordings to compare.
- **Anita Fam** (two articles): two different facts offered as either/or, so choosing one strikes out the other.
- **Khaw Boon Wan** (five articles): one fact in four wordings, and a fifth held back by the sentence limit.

## Why

The screen is right about what the pipeline produced: [merging-values.md](merging-values.md) made sure nothing a
source said is hidden. The fault is earlier, in what the pipeline asks for.

1. **Each article is read alone.** Job 3 proposes a description from one article and TTE's text. It never sees the
   other articles about the same record, so each one adds the same fact in its own words.
2. **It asks for a rewrite.** The model rewrites TTE's description rather than listing what is new, so TTE's own
   sentences come back reworded (struck out on screen) and some gain praise.
3. **Code combines the rewrites afterwards.** Code cannot write. It can only set the rewrites side by side, which is
   the screen the reviewers saw.

## The fix

### 1. Job 3: new facts, not a rewrite

The resolution prompt (`prompts/resolution.txt`) asks for the description's **new sentences only**: facts the
article adds that TTE's text lacks, each a sentence on its own, facts only, every date in full with its year. TTE's
text is not rewritten at this step.

Code then drops a sentence whose numbers or names are not in the article, or that uses a filler word (list below).

New articles only. The stored proposals already hold their new sentences (`sentence_edits` in
`src/shared/description.py` finds them), so nothing is re-read.

### 2. A combine step: one addition per record

After Job 3 and before the deck is built, for each record:

- **One article proposing description text:** no model call. Its new sentences go to the card as they are.
- **Two or more:** one model call (prompt below). It is given TTE's description and every article's new sentences,
  numbered by source, and returns:
  - `add`: at most as many sentences as fit the style guide's five, each with the articles that state it;
  - `disagreements`: a fact the articles give different values for, each value with its articles; the sentence
    is written without the value;
  - `corrections`: words in TTE's description the articles contradict ("since 2017" for a post he has left), each
    with its articles;
  - `left_out`: further facts that did not fit, least important first.

Code checks the answer against what the extraction step recorded from each article: its headline, quote, summary
and fields, and the year it was published (an article's "Sept 1" is in that year). Not against Job 3's proposed
sentences, which are model output: a year Job 3 made up would pass. Article text is not kept (since sql/21), so
nothing is checked against the full text.

| Check | If it fails |
|---|---|
| The sentence is not in TTE's description already | the sentence is dropped |
| It has a word, number or name TTE's description lacks | the sentence is dropped |
| Every number and name in it is in each article it cites | the article is taken off that sentence; a sentence left with none is dropped |
| A day and month always have a year | the sentence is dropped |
| No filler word ("distinguished", "renowned", "prominent", "veteran", "well-known", "respected", "leading", "esteemed", "illustrious", "celebrated", "notable") | the sentence is dropped |
| It is not inside another added sentence (all its words in the other) | it is dropped and its articles move to the other |
| Each value in a disagreement is in the articles given for it | the article is taken off; one value left means no disagreement |
| A correction quotes TTE's words exactly | the correction is dropped |

If the call fails or too much is dropped, the card falls back to each article's own new sentences, one row each.
The reviewer never sees unchecked text.

The result is stored in its own table (one row per record and set of proposals), so the deck build only reads it.

**Run by hand** (`src/manual`, for days the API is busy): one more pair after matching, before publishing.

```
uv run python -m src.manual combine export    # every record with description sentences from 2+ articles, not yet combined
uv run python -m src.manual combine import    # the same checks as the nightly run, then stored
```

The export says when there is nothing to combine. Skipping the pair is safe: those cards fall back to each
article's own sentences, and are combined on the next run that does it. The Job 3 prompt change adds no step.

### 3. The desk

```
Add this to the description?                                  [In the news 1 2 3 4]

  TTE now   Permanent Secretary, Ministry of Law (2010–2012); … Mediacorp.     ▸ show all

  + Adds    He was appointed Chairman of the Land Transport Authority on 1 September 2026 ²⁴.
            In October 2026, he was appointed board chairman of the National Volunteer &
            Philanthropy Centre ³.

  ⚠ The sources disagree: left the Ministry of Home Affairs in 2024 ² · 2026 ⁴      [2024] [2026]
  ✎ TTE says "(since 2017)" for the Ministry of Home Affairs; sources 2 and 4 say he has left.  [Fix]

  1 more fact left out ▸

                                      [ Accept ]   [ ✎ Edit ]   [ No change ]
```

- One question: add this?
- TTE's text is one grey line, folded, never struck through.
- Only the new sentences are in full colour, each with its source numbers. A number opens that article's quote.
- A disagreement or a correction shows only when there is one, with a button for each answer.
- Edit opens the whole description with the new sentences in place.
- Other wordings are not on screen. They remain in the data behind the source numbers, as on the awards screen.

The decision is recorded as accepted, edited or rejected, which gives a measure of the combine step for the
evaluation ([evaluation.md](evaluation.md)).

## The trial (3 Nov 2026)

The combine prompt was run by hand in AI Studio on `gemini-3.8-flash` for the four cards above, from the stored
proposals. All four passed the code checks for filler, repeats, and numbers and names traced to a source (checked
against each article's headline, quote and proposed sentences, not yet the full text).

| Card | Result |
|---|---|
| Pang Kin Keong | 3 sentences; the LTA chairmanship once; the Home Affairs end year reported as 2024 ² against 2026 ⁴, not chosen |
| Chan Yeng Kit | 2 sentences from five wordings: CEO of SPH Media in July 2024; executive chairman on 1 October 2026 |
| Anita Fam | Both facts: the Agency for Integrated Care chair, and the Sector Nominations Committee |
| Khaw Boon Wan | 1 sentence: chairman from May 2021 until 1 October 2026 |

Three faults, each with its fix in the design above:

1. **Sources credited too widely.** A sentence cited every article that gave its main fact, including ones without
   its dates: Khaw Boon Wan's cited all five, though article 1 gives neither "May 2021" nor "1 October 2026". The
   check takes an article off a sentence when it lacks the sentence's numbers.
2. **A date without its year.** "Appointed Chairman of the Land Transport Authority on 1 September". The prompt asks
   for every date in full, and the check drops a day and month with no year.
3. **TTE's text left stale.** Adding at the end leaves Pang Kin Keong's "(since 2017)" in place above "He stepped
   down". Hence `corrections`.

## The prompt

```
You are helping a librarian update one record in a national authority file.

Below is the record's current description, and new sentences that {n} news articles proposed for it. Each article
was read on its own, so they repeat each other in different words, and some repeat what the description already says.

Write the sentences to ADD to the end of the current description. Rules:
1. Add only facts that the current description does not already state. Never repeat or reword it.
2. Each fact once, however many articles gave it. Use the most specific wording: dates, posts, names in full.
   Every date in full, with its year.
3. Facts only: a post, a date, an appointment, an award, an event. No praise or characterisation ("distinguished",
   "renowned", "prominent", "veteran", "well-known", "respected", "leading").
4. Use only what the articles say. No fact, date or name that is not in the articles below.
5. After each sentence, list the article numbers that state its facts, including its dates and numbers. List an
   article only if it states them.
6. If articles give different values for the same fact (a different year, date or post), do not choose: write the
   sentence without that value, and report it under disagreements with each value and its articles.
7. If the articles contradict words in the current description (a post it says he still holds), quote those words
   under corrections with the articles that contradict them. Do not change the description.
8. At most {room} sentences. Put any further facts, least important first, under left_out.
9. Write in the style of the current description: plain, third person, past or present tense as it uses.

Current description:
{tte}

Articles:
{articles}
```

## Cost

Only records with two or more articles proposing description text make a call: one per record, once. Of the 79
description notes on the 3 Nov deck, 21 have two or more articles, so the first run over the stored proposals is
21 calls; after that a night adds a few. The full Flash model allows 20 requests a day, shared with Job 3, so the
first run would be spread over two or more nights or use Flash Lite (to be tested the same way).

## Open questions

1. **Which model for the combine step.** `gemini-3.8-flash` did well on four cards, but its 20 a day are shared with
   Job 3. Options: Flash, once a night after Job 3; Flash Lite, if it does as well on the same four; or MiMo v2.6 Pro,
   if its cost trial goes ahead.
2. **Corrections.** Offer them as a separate row the reviewer accepts (as drawn), or leave TTE's text alone and
   only show the contradiction as a note?
3. **Where the sentences go.** At the end of TTE's description (as designed: easy to review, TTE's words untouched),
   or worked in where they fit (reads better, but rewrites TTE's sentences again)?
4. **Achievements.** The same prose problem on a smaller scale. Same step, or leave as it is?
5. **Review by the team.** Whether the reviewers see this screen before it is built.

## Order

1. Checks against full article text, and the trial rerun on the same four with the fixed prompt.
2. The combine step and its table, run on the stored proposals.
3. The desk screen.
4. The Job 3 prompt change, for new articles.
5. Accept / edit / reject counts after a week of reviewing.
