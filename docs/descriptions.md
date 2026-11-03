# Descriptions: one addition from many articles

Status: built and first run 3 Nov 2026. 21 records combined by hand in AI Studio; 19 passed the checks, and all 21
pass after the check fixes below (stored by `python -m src.combine --recheck`). Flash only (Flash Lite was not good
enough). Corrections are made in place and can be undone. New sentences go at the end of TTE's text. Achievements
are left as they are.

## The problem

A description screen took longer to read than the articles behind it. Reviewers said it was too complex: it did
not cut the decision or the reading time.

What the screen showed, on real cards:

- **Pang Kin Keong** (four articles): his existing sentence struck out and rewritten, the Land Transport Authority
  chairmanship added three times, and "a distinguished public administrator", which is praise, not a fact.
- **Chan Yeng Kit** (five articles): one fact, his SPH Media appointment, in five wordings to compare.
- **Anita Fam** (two articles): two different facts offered as either/or, so choosing one struck out the other.
- **Khaw Boon Wan** (five articles): one fact in four wordings, and a fifth held back by the sentence limit.

## Why

The screen was right about what the pipeline produced: [merging-values.md](merging-values.md) made sure nothing a
source said is hidden. The fault was earlier, in what the pipeline asked for.

1. **Each article is read alone.** Job 3 proposes a description from one article and TTE's text. It never sees the
   other articles about the same record, which often arrive weeks apart, so each one adds the same fact in its own
   words.
2. **It asked for a rewrite.** The model rewrote TTE's description rather than listing what is new, so TTE's own
   sentences came back reworded (struck out on screen) and some gained praise.
3. **Code combined the rewrites afterwards.** Code cannot write. It could only set the rewrites side by side.

Lists (awards, affiliations) and single values (dates, titles) do not have this problem: code can tell two values
are the same, and merges them exactly. Only prose needs a model to combine. Achievements is prose too, but has one
change on the deck, from one article.

## The fix

### 1. Job 3: new facts, not a rewrite

The resolution prompt (`prompts/resolution.txt`) asks for TTE's description word for word, then the new facts as
new sentences: facts only, no praise, every date in full with its year. TTE's words change only where the article
shows they are now wrong. New articles only; stored proposals are not re-read.

### 2. A combine step: one addition per record

After Job 3 and before the deck is built, for each record whose description has sentences from two or more
articles, one Flash call (prompt below) is given TTE's description and every article's sentences, numbered as the
card numbers its sources, with each article's date, headline and quote. It returns:

- `add`: at most as many sentences as fit under the style guide's five, each with the articles that state it;
- `disagreements`: a fact the articles give different values for, each value with its articles;
- `corrections`: words in TTE's description the articles show are now wrong ("since 2017" for a post he has left),
  with the words to put in their place;
- `left_out`: further facts that did not fit, least important first.

A record with one article proposing sentences makes no call; its sentences go to the card as they are.

**The checks.** Code checks the answer against what the extraction step recorded from each article: headline,
quote, summary and fields, and the year it was published (an article's "Sept 1" is in that year). Not against Job
3's sentences: those are model output, and a year Job 3 made up would pass. Article text is not kept (since
sql/21), so nothing is checked against the full text.

| Check | If it fails |
|---|---|
| The sentence is not in TTE's description already | dropped |
| It has a word, number or name TTE's description lacks | dropped |
| No filler word ("distinguished", "renowned", "prominent", "veteran", "well-known", "respected", "esteemed", "illustrious", "celebrated", "notable", "eminent", "acclaimed", "stalwart"; "leading" only as "a/the leading") | dropped |
| A day and month always have a year | dropped |
| Each article cited gives every number and date in it, itself | that article is taken off the sentence |
| Every name in it is in one of its articles (a sentence may take the date from one and a successor's name from another). An article the model did not cite is added when it gives the dates and a missing name | dropped if a name is in none |
| It is not inside another added sentence (all its words in the other) | dropped; its articles move to the other |
| A fact left out for length | takes the place of a dropped sentence |
| Each value in a disagreement is in the articles given for it | that article is taken off; one value left means no disagreement |
| A correction quotes TTE's words exactly, and its new words pass the same trace as a sentence | the correction is dropped |

If the call fails or nothing passes, the card shows each article's own sentences instead. The reviewer never sees
unchecked text from this step.

**Stored** in `description_drafts` (`sql/22`), one row per record and set of articles: a new article about the
record makes a new key, and a new call. With the checked result are the model's input and answer, about 1 to 3 KB a
record, so a changed check is applied again with no model call:

```
uv run python -m src.combine --recheck --dry-run   # what would change
uv run python -m src.combine --recheck             # store it
```

### 3. The desk

The description is shown the way every other field shows its change: the box of what it reads after you accept.

- TTE's words in grey. Long ones fold to their last lines, with "Show all of TTE's text".
- The new sentences after them in green, each with circled source numbers (a number opens that article above) and
  × to leave it out (↺ puts it back).
- A correction in place: only the words that change are struck, the new ones in green, with its sources and ×.
- Under the box: a fact left out for length, with + Add; on a card not yet combined, another article's wording of
  a sentence ("also written"), and a warning where the wordings give different numbers or dates.
- Edit opens the whole description as text. Accept takes what the box shows.

## Running it

| When | How | Model calls |
|---|---|---|
| Every night | `python -m src.combine`, after Job 3 (`nightly.yml`): up to 5 records not yet combined, newest first | 1 a record, from the 20 Flash allows a day, shared with Job 3 |
| By hand | `python -m src.manual combine export`, paste into AI Studio, copy the answer, `python -m src.manual combine import` | none from the API |
| After a check changes | `python -m src.combine --recheck` | none |

Skipping a night is safe: those cards show each article's own sentences until the next run.

## First run (3 Nov 2026)

21 records, by hand in AI Studio on `gemini-3.8-flash`. 19 passed the checks as they were; 2 fell back to each
article's sentences. The faults were in the checks, not the answers, and four changes fixed them (in the table
above): names looked for across a sentence's articles, an uncited article credited when it gives the missing name,
"leading" as a verb not counted as praise, and curly and straight apostrophes matched. With them all 21 pass; 6
additions change (Khaw Boon Wan, Heng Swee Keat, Pang Kin Keong, Eugene Tan, Hsieh Fu Hua, Teo Chee Hean).

Heng Swee Keat's Honorary Patron sentence is still dropped: its article has no publication date stored, so its year
cannot be confirmed. His other fact, the National Research Foundation chairmanship, takes its place.

## Issues, fixes and what could go wrong

| Issue | Fix | What could go wrong |
|---|---|---|
| Each article rewrote TTE's description, so TTE's text came back struck out | Job 3 asks for TTE's text word for word, then new sentences | New articles only: a card from older proposals with one article still shows its rewrite, struck in place. The model can still reword; the old 70% check still flags it |
| One fact in many wordings across articles | The combine step: each fact once | One more Flash call per record from the 20 a day. A model can leave a fact out without saying so; no check catches that |
| Praise ("a distinguished public administrator") | Banned in both prompts; filler words dropped by the check | A fixed list: praise in other words ("extensive experience") passes. A listed word used plainly is dropped ("leading" as a verb was, until fixed) |
| Dates without a year ("on 1 September") | Prompt asks for the year; the article's publication year counts; a date with no year is dropped | An article with no stored date loses its dated sentences (Heng Swee Keat). An article from January about last December would be read as the new year |
| Every article credited on every sentence | An article stays on a sentence only if it gives its dates and numbers itself | Fewer source numbers: one that reports the fact without the date loses its number, so a sentence can look less supported than it is |
| A year Job 3 made up passed (Pang's "2024") | Traced against the extraction step's notes, not Job 3's sentences | The notes are model output too, from a separate call, not the article. A fact only in the full article is dropped (6 of 63 sentences when tested, most doubtful) |
| A sentence joining two articles' facts was dropped (Khaw) | Names looked for across its articles; an uncited article giving the missing name credited | A sentence could join a date from one article with a name from another wrongly. Each number must still be in each credited article |
| The model repeating TTE or itself | A sentence with nothing TTE lacks is dropped; one inside another added sentence is folded into it | A repeat with one new word stays (on purpose: "stepped down" can be the whole fact). Two sentences with the same words in a different sense would be folded |
| TTE's text left stale ("since 2017") | Corrections, quoted exactly and traced; made in place by default | Made by default, so a reviewer who does not look accepts it. The × undoes it |
| A dropped sentence left nothing to add (Heng Swee Keat) | A left-out fact takes its place | The model ranked that fact least important |
| The screen was too complex | One paragraph, in the desk's own box, with source numbers and × | The × and numbers are small to tap on a phone. A card not yet combined can still show "also written" lines and rewrites |
| A check changing after drafts are stored | The model's answer kept with each draft; `--recheck` | 1 to 3 KB more per record. Drafts stored before 3 Nov kept no answer, so they are rechecked from the manual import file in `data/manual/done` |
| Space on the free tier | One table, 14 KB for 21 records; the free tier limits size (500 MB), not the number of tables | Grows by a few KB a night |

## The prompt

`src/combine/__init__.py`, as run:

```
You are helping a librarian update one record in a national authority file.

Below is the record's current description, and new sentences that {n} news articles proposed for it. Each article
was read on its own, so they repeat each other in different words, and some repeat what the description already says.

Write the sentences to ADD to the end of the current description. Rules:
1. Add only facts that the current description does not already state. Never repeat or reword it.
2. Each fact once, however many articles gave it. Use the most specific wording: dates, posts, names in full.
   Every date in full, with its year. A date an article gives without a year, or "this year", is in the year the
   article was published.
3. Facts only: a post, a date, an appointment, an award, an event. No praise or characterisation ("distinguished",
   "renowned", "prominent", "veteran", "well-known", "respected", "leading").
4. Use only what the articles say. No fact, date or name that is not in the articles below.
5. After each sentence, list the article numbers that state its facts, including its dates and numbers. List an
   article only if it states them.
6. If articles give different values for the same fact (a different year, date or post), do not choose: write the
   sentence without that value, and report it under disagreements with each value and its articles.
7. If the articles show that words in the current description are now wrong (a post it says he still holds),
   give those words exactly as they appear under corrections, with the words to put in their place and the
   articles that show it. Do not change the description yourself.
8. At most {room} sentences. Put any further facts, least important first, under left_out.
9. Write in the style of the current description: plain, third person, past or present tense as it uses.

Current description:
{tte}

Articles:
{articles}
```

## The trial before the build (3 Nov 2026)

The prompt was first run by hand on four cards (Pang Kin Keong, Chan Yeng Kit, Anita Fam, Khaw Boon Wan). It found
three faults that shaped the checks: sources credited too widely (Khaw Boon Wan's sentence cited all five articles,
though one gives neither date), a date without its year ("on 1 September"), and TTE's text left stale (Pang Kin
Keong's "since 2017" above "He stepped down"), hence `corrections`.

## Still open

1. **Review by the team.** Whether the reviewers find the paragraph quicker than the old screen. The desk records
   accept, edit and reject for each description, which gives a measure after a week of reviewing
   ([evaluation.md](evaluation.md)).
2. **Undated articles.** Heng Swee Keat's article has no publication date stored. Worth finding why, as any dated
   sentence from such an article is dropped.
3. **Achievements.** The same step would take it if it starts getting one fact from several articles.
