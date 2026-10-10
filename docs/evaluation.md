# Custom system evaluation

We evaluate the system on five dimensions: accuracy, effectiveness,
efficiency, satisfaction and reliability.

**Target sentence:** the app finds X% of the news-driven changes the team
finds, at Y seconds per change against Z minutes, adds N changes they would
have missed, and fails mostly at [stage], on [kind of name].

## What we already know, before anyone starts

Comparing seven TTE dumps from September 2024 to August 2026 (six periods,
3,357 records changed, 4,046 field changes), only **12% of the team's record
changes involve a name our three news sources printed** in that period or the
two months before. Correcting for names that appear in an article's body but
not its headline (measured at 1.6x on articles where we have full-text
extractions) puts the true figure near **19%**. The rest is cataloguing work:
records touched because a book was catalogued, historical figures corrected,
bulk projects.

Two consequences, and they shape everything below.

1. **Recall is measured against news-driven changes, not all changes.** A
   change counts in the denominator when the record's name appears in our
   three sources within the period or the two months before it. Measured
   against *all* TTE changes the number would read about 12%, which says
   more about what cataloguing is than about the app.
2. **The numbers will be small.** The whole team makes roughly 400 record
   changes a quarter, of which perhaps 20 to 30 are news-driven and made by
   the two people on the manual arm at any time. Recall on 25 changes carries
   an interval of about ±19 points. We will report the interval, not a bare
   percentage, and no target is met or missed on a number that wide.

## 1. Accuracy: is each step right?

Three labelled sheets, drawn from **August 2026** (2,135 articles, 236 of
them judged relevant by the app), in week one. Between four people, about
**two and a half hours each**: roughly 75 minutes on relevance, 20 on
matching, 75 on extraction. The first draft said an hour; that was wrong,
and extraction is what costs.

Rules for all three sheets:

- The sheet does not show the app's answer. The answer key is held
  separately and joined after labels are frozen.
- Everyone marks the **first 50 rows**; the rest are divided between you.
  The rows are shuffled, so any block is a fair share, and the shared 50 are
  what agreement between labellers (Cohen's κ) is measured on.
- Nothing is relabelled after seeing a score.
- Put the time taken in the `minutes` cell at the top of the sheet.

### Relevance

Fill in `relevant` with TRUE or FALSE.

TRUE means: the article names a person, organisation, place, event, award,
programme or legal act that the authority file holds or should hold, **and**
reports a fact that would change or create its record: an appointment, an
award, a death, a rename, a merger, a founding. A mention alone is FALSE.

| url | source | title | description | relevant |
|---|---|---|---|---|
| …/tommy-koh-ramon-magsaysay-award | cna | Veteran diplomat Tommy Koh wins Ramon Magsaysay Award | Tommy Koh, 88, has won the Ramon Magsaysay Award, regarded as Asia's version of the Nobel Prize. | TRUE |
| …/nus-bizad-charity-run-140000 | cna | NUS Bizad Charity Run raises over S$140,000 | More than 1,300 NUS staff, students and alumni took part in the run, raising over S$140,000. | FALSE |

**Sampling.** 736 rows in three strata that between them cover every article
the feed carried in August, so nothing was chosen by hand and every article
had a known chance of being drawn:

| stratum | in the month | sampled | each row stands for |
|---|---|---|---|
| the app called it relevant | 236 | 236 | 1.0 |
| rejected, names a TTE record | 442 | 200 | 2.21 |
| rejected, names none | 1,457 | 300 | 4.86 |

The split between the two rejected strata is mechanical: an article is
*named* when its title or description contains the name of an active TTE
record of at least seven characters. Misses concentrate there, which is why
it is sampled harder; the weight puts it back in proportion. Precision is a
census of the first stratum and needs no weighting; recall is weighted, and
one labelled miss stands for two or five articles depending on where it was
found. `data/eval/0-sampling.md` records this, with the random seed, before
anyone labels anything.

Sampling the whole month at random instead would need about 1,400 rows to
reach the same precision on recall, because nine articles in ten are
rejects that name nobody.

**TL;DR:** fill in `relevant` for every row.
**Produces:** precision, recall, F1, by language.

### Matching

Fill in `same` with Y, N or `?`. `?` means the row does not carry enough to
decide; it is a real answer and is counted, not dropped.

| name | evidence | url | tte_id | tte_name | tte_fields | same |
|---|---|---|---|---|---|---|
| Alan Chan | Former CPA chairman Alan Chan received the Order of Temasek. | …/lta-chairman-new-board-members | 18593383 | Chan, Alan Heng Loon | Occupation: Civil servant · Affiliations: Singapore Press Holdings · Born: 1952 | |

**Sampling.** 300 rows: 150 pairs the app matched, 150 it did not (with the
best record it was shown), drawn at random. The evidence sentence is in the
sheet, so a row can be judged without opening the article. At 150 a side,
precision and recall each land within about ±0.06.

**TL;DR:** fill in `same` for every row.
**Produces:** precision, recall, F1; the `?` rate; results split by Latin and
Chinese names.

### Extraction

For each name the app pulled out, fill in `verdict`: `ok`, `wrong` (not what
the article says, or not something an authority record would hold) or
`not_worth` (real, but no record would be created for it). Put any field
whose value is wrong in `field_errors`. On the article's blank last row, put
in `missed` any name the article carries that the app should have pulled out
and did not, one per line.

| article_url | language | entity | type | fields | verdict | field_errors | missed |
|---|---|---|---|---|---|---|---|
| …/khaw-boon-wan-sph-media-trust | en | Khaw Boon Wan | PERSON | Occupation: Cabinet Minister · Affiliations: SPH Media Trust | | | |
| …/khaw-boon-wan-sph-media-trust | en | SPH Media Trust | ORGANISATION | Founder: Khaw Boon Wan | | | |
| …/khaw-boon-wan-sph-media-trust | en | | | | | | Teo Chee Hean |

**Sampling.** 60 articles from August 2026 that the app processed, English
and Chinese, with the names it found already filled in. You are checking and
adding, not extracting from scratch.

**TL;DR:** mark each row `ok` / `wrong` / `not_worth`; add what was missed.
**Produces:** precision, recall, F1 by language and type; error rate per
field.

## 2. Effectiveness: does it find what you find, and more?

**Design: crossover.** Two people use the app while two work the old way;
at six weeks they swap. Nobody on the manual arm opens the desk during their
manual stretch, so nothing they find is contaminated by what the app showed
them, and by the end each person has worked both ways, which is what lets us
compare times without blaming the difference on who is faster.

Three months. Decide every card you are dealt; a record you cannot settle is
*Keep for review*; there is no skipping.

**The log.** One row every time you identify a change or a new entity, either
way of working, entered on the desk under *Your sheet → A change you found*.
The sheet page shows no cards, so it is safe to use on the manual arm.

| method | article_url | tte_entity | tte_uuid | kind | field | old | new | date |
|---|---|---|---|---|---|---|---|---|
| manual | …/khaw-boon-wan-sph-media-trust | Khaw Boon Wan | 18533710 | amend | Affiliations | People's Action Party | People's Action Party \| SPH Media Trust | 2026-10-14 |
| app | …/tommy-koh-ramon-magsaysay-award | Tommy Koh | 18338504 | amend | Awards | … Order of Nila Utama (2008) | … \| Ramon Magsaysay Award (2026) | 2026-10-02 |
| manual | …/new-charity-council-chair | Tan Kim Peng | | new | | | | 2026-10-20 |

`kind` is `new` for a record that does not exist yet, `amend` otherwise; a
`new` row needs no field, old or new.

**TL;DR:** fill in a row every time you identify a change or a new entity
while reading.

**Produces:** of the news-driven changes made on the manual arm, the share
the app also proposed and the share a reviewer accepted, each with its
interval; changes the app produced that the manual arm did not; and for
everything the app missed, which step lost it (feed, relevance, extraction,
matching, withheld, reviewer).

## 3. Efficiency: what does it cost?

The desk records how long each card was on it. For the manual side, two
numbers a week on the desk (*Your sheet → This week*).

| week_start | minutes | changes | method | user |
|---|---|---|---|---|
| 2026-10-05 | 140 | 6 | manual | Yaw Huah |
| 2026-10-12 | 95 | 3 | app | Yaw Huah |

**TL;DR:** log it once a week, for whichever arm you are on.

**Produces:** seconds per change on the desk against minutes per change by
hand, for the same people in both arms; days from article to change, both
ways; running cost, which is nil.

## 4. Satisfaction: is it good to use?

At **month one and month three**, complete the usability survey on
Form.gov.sg: ten statements, each scored 1 (strongly disagree) to 5
(strongly agree). Two minutes.

| statement | score |
|---|---|
| I think that I would like to use this system frequently. | |
| I found the system unnecessarily complex. | |
| I thought the system was easy to use. | |
| … ten in all, the standard set | |

**TL;DR:** complete the survey at month 1 and month 3.

**Produces:** the SUS score (0 to 100), read beside what the desk records:
how often a proposal was reworded before it was accepted, how often a record
was kept for review, how often a reviewer had to search for a record the app
should have offered, and the notes left on cards.

## 5. Reliability: does it just run?

Log errors, issues, bottlenecks and feedback as they arise, in the shared
issues sheet (one row: date, what happened, what you were doing, whether it
blocked you).

**TL;DR:** log any issue as it comes up.

**Produces:** nights the pipeline ran against nights it failed and why; a
running list of issues by type; how each TTE re-import went.

## What comes out

One page of numbers under the five headings, computed from the sheets, the
logs and the desk. Read at month one and month three. The miss table says
what to fix first; the next quarter's table shows whether it was fixed.

## Decisions to confirm

1. Crossover at six weeks: two on the app, two manual, then swap.
2. Recall is measured against news-driven changes, with the definition
   above, and reported with its interval.
3. Every change gets a row in the log, either arm.
4. The weekly two numbers get logged.
5. The three sheets are labelled in week one, before the run starts.
6. The sheets and your desk decisions are the evaluation; nobody marks
   anything else.
