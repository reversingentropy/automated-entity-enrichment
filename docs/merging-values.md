# Merging values on a card: what went wrong, and the fix plan

Status: built 3 Nov 2026 (changes 1–8 and 6a), not yet published. Results under [Built](#built).

## What went wrong

The Singapore Airlines card offered four awards, three of them credited to all four articles. The articles
named eight different awards between them: four Skytrax awards in CNA, The Straits Times, Lianhe Zaobao and
Tamil Murasu, and four Business Traveller awards in Tamil Murasu only. Four awards never reached the reviewer
(Business Traveller's Best Cabin Crew and Best Asia-Pacific Airline, Skytrax's Best Airline in Asia and Best
Economy Class), two Business Traveller awards were credited to three papers that never mentioned them, and
Skytrax's World's Best Airline was credited to two of the four papers that named it.

The articles were read correctly. Each article's extraction and each proposal in the database say exactly
what the article says. The fault is in the card builder (`src/export/cards.py`), the code that turns
proposals into cards. It is code, not model output: it does the same thing every time, so it can be fixed
once and tested.

### The audit (2 Nov 2026, read only, all 383 cards)

| Checked | Count | Result |
|---|---|---|
| Fields on new-record cards | 1,017 | All trace to the article credited: 954 exact, 43 renamed to TTE's form, 20 linked to a TTE record |
| Values proposed for existing records | 252 | 14 hidden from the reviewer, on 4 cards |
| Value-to-source credits | 245 | 15 credit an article for a value it did not give in those words, on 3 cards |

The audit counts each article's wording separately, so one award named by three papers counts three times,
and a credit is flagged when the article's wording differs ("World's Best Airline" against "Skytrax World's
Best Airline"). Read as awards, not wordings:

Cards that are wrong:

- Singapore Airlines: 4 of 8 awards hidden; 2 awards credited to 3 papers each that never mentioned them.
- Shanti Pereira: "Asian Games 200m gold (2023)" hidden behind the 2026 gold.
- Iskandar Jalil: "Colombo Plan Scholarship (1972)" hidden behind 1966.
- Goh Yihan: "Singapore Management University" folded into its law school, and the law school credited to an
  article that named only the university.

Merges that look right but were made out of sight: Anita Fam's two awards worded two ways, and Tommy Koh's
Ramon Magsaysay Award with and without a year.

Handled correctly: Teo Chee Hean's Doctor of Letters, 2026 in one paper and 2025 in another, shows as "The
sources disagree" with both offered.

Not covered: whether the model read each article right (that is the extraction sheet in
[evaluation.md](evaluation.md)).

### Descriptions (3 Nov 2026, read only, 79 description notes)

| Checked | Count | Result |
|---|---|---|
| New sentences proposed | 134 | None lost by the card builder: 105 kept, 20 set aside as "other wordings", 9 held back over the five-sentence limit |
| Other wordings and held-back sentences | 29 | **None reach the reviewer.** The card carries them (`alts`, `held`), but the desk has never shown either |
| Groups of "other wordings" | 12 | 6 give different numbers or dates, so some are disagreements, not rewordings |
| Article credits | — | 23 articles credited on a note where none of their sentences is on screen |

Examples:

- Changi Air Base East: three papers on the new runway. The card shows "operational on September 17, 2026";
  hidden are "September 2026" and "a new 3,660-metre military runway was commissioned on September 28, 2026".
  The note says three sources, though only one gave the date shown.
- Khaw Boon Wan: "retirement on 1 October 2026" shown; three wordings ending "2026" or "October 2026" and one
  held-back sentence hidden. These agree, so this is the harmless kind.
- Shanti Pereira: "she defended her 200-metre title" held back, the same fact as the list award hidden above.

Same pattern as list fields: similar sentences grouped by word overlap (`near_same`), one kept, the rest out
of sight, every article in the group credited. The difference is that nothing is lost in the data, only on
the screen.

## Why it happened

The card builder decides whether two values are the same by throwing information away, then keeps one value
for each group it judges the same, without telling the reviewer.

1. **Similar wording is merged** (`_combined_additions`, the "pooled" step). Two list values count as one when
   75% of the shorter one's words are in the longer (`near_same`). Awards from one body share most of their
   words ("Business Traveller Global Awards World's Best ..."), and the year counts as a shared word, which
   tips three-word names over the line. Each value is compared with the group's longest so far, so merges
   chain: Cabin Crew joined Business Class, which had joined Economy Class. The rule was written for long
   achievement sentences that two papers word differently, and then applied to every list field.
2. **The same name with different years is merged** (`_same_fact`). The key used to group values drops every
   digit and year. Two articles giving different years is rightly shown as a dispute. One article giving
   two years (a gold in 2023 and again in 2026) is rightly not a dispute, but then only one value is kept
   and the other hidden. That breaks the project's own rule: "one article naming two values is two
   additions, not a disagreement" (`prototype/README.md`).
3. **Sources are counted per group.** The value that survives a merge is credited with every article in the
   group, so the source numbers on screen can name papers that never gave it.
4. **Digits are dropped for single-value fields too.** For a single-value field, a 14th and a 15th of a month
   reduce to the same key, so a day or month disagreement is not flagged and the card says "2 sources say
   this" (found 29 Oct; same function, same fault).
5. **Nothing checks the result.** No test or check compares what was proposed with what the card shows, so
   none of this was visible.

## The rules the fix follows

1. **Merge only values that are the same.** Same after safe cleanup only: letter case, spacing, punctuation,
   and the TTE renames the code already makes (`wrote`). Digits and years are never dropped.
2. **Similar values are shown, not merged.** If two values may be one thing, both stay on the card, marked
   "may be the same as ...", and the reviewer leaves one out with ×.
3. **Each value carries its own sources:** the articles whose proposal contained that value. A source number
   on screen always means "this article said this".
4. **Every proposed value is accounted for.** Each one is shown, already in TTE, or renamed to TTE's form, and
   a check says so.

## Changes

| # | Change | Where |
|---|---|---|
| 1 | A new `same_value(a, b)`: equal after safe cleanup (rule 1). Used for grouping list values and for comparing single-value fields. `_same_fact` is kept only to *notice* the same name with different years. | `cards.py` |
| 2 | Remove the pooled step from `_combined_additions`. Pairs `near_same` would have merged are recorded as `maybeSame` links instead. | `cards.py` |
| 3 | Same name, different years: from one article, both values are additions; from two articles, a dispute (as now). | `cards.py` |
| 4 | `perValue[].sources` built from exact values only; the change's supporters are the union of its values' sources; "N sources say this" counted per value. | `cards.py`, desk |
| 5 | Single-value fields: values that differ after safe cleanup are a dispute, so a 14th and a 15th show "The sources disagree". | `cards.py` (`collapse`) |
| 6 | Desk: a "may be the same as ..." hint on linked values; nothing goes into `variants` that is not on screen. | `prototype/desk.template.html` |
| 6a | Descriptions: show each sentence's other wordings beside it, with their sources, to swap in; show held-back sentences below the note, to add. Wordings that give different numbers or dates are marked "The sources disagree". Each sentence credited to the articles that wrote it. | `cards.py`, desk |
| 7 | A check, `account_for(proposals, card)`, listing every proposed value not on its card and every credit not backed by its article. It runs in the tests and at `--publish`. | new, in `src/export/` |
| 8 | Tests from the real cases, below. | `tests/` |

### Tests (real inputs, from the database)

| Case | Expected |
|---|---|
| Singapore Airlines, four articles | All 8 awards on the card, wordings of one award linked as "may be the same"; each Business Traveller award credited to Tamil Murasu only; each Skytrax award to the articles that named it |
| Shanti Pereira, one article | Both "Asian Games 200m gold (2023)" and "(2026)" offered as additions |
| Iskandar Jalil, one article | Both Colombo Plan years offered |
| Teo Chee Hean, two articles | Still "The sources disagree", 2025 and 2026 |
| Death day 14 and 15, two articles | "The sources disagree", both dates |
| Anita Fam, two wordings | Both shown, linked as "may be the same" |
| Goh Yihan | Both SMU and its law school shown, each credited correctly |
| Changi Air Base East | Three runway wordings on screen, marked as disagreeing on the date, each with its own source |
| Every card in the deck | `account_for` finds nothing, descriptions included |

## Rolling it out

1. Code and tests. No model calls, nothing rerun.
2. You rebuild the deck (`python -m src.export --publish`). Stored proposals are correct, so a rebuild repairs
   every card.
3. Run the audit again: hidden values and wrong credits should both be zero.

No reviewer decision has been saved yet, so no sheet needs correcting.

## Decisions (3 Nov 2026)

1. **When the check finds a problem at `--publish`:** publish the rest of the deck, leave out the cards that
   fail, and print them. One bad card does not hold back the others, and does not reach a reviewer.
2. **Long achievement sentences:** shown, not merged, linked as "may be the same", shown side by side so the
   reviewer leaves one out with ×. No field keeps a merge out of sight.
3. **Naming awards at extraction:** add a prompt rule to name the awarding body the same way each time
   ("Skytrax World Airline Awards: World's Best Airline"), after the fix, checked on a normal nightly run. It
   helps new articles only, so the card builder must be right without it.
4. **A quote for each value:** later, after the fix has settled. Today a card quotes one sentence per
   article, so seven of Tamil Murasu's eight awards have no quote on screen. It changes the extraction output,
   so it is a larger piece of work.
5. **Descriptions:** audited (above). Same fault, so they are fixed in the same pass (change 6a).

## Order

1. Description audit (done).
2. Build changes 1–8 and 6a, with tests (done).
3. You run `--publish`; the audit is run again.
4. The award naming prompt rule.
5. Quotes per value, later.

## Built

Where each change lives:

- `value_key` / `same_value`, `maybe_same`, the new `_combined_additions`, the single-value dispute in `collapse`,
  and per-sentence sources (`said`) and marked wordings (`differ`) in `_combined_rewrite`: `src/export/cards.py`.
- `account_for`: `src/export/accounting.py`. The card builder runs it on every card that changes a record; a card
  with a problem is left out of the deck and printed (`Left out of the deck, <name>: ...`).
- Desk: "may be the same as ..." under linked values; "N sources say this" only when every source says every value
  shown; a single-value dispute offers each value, without "Keep both"; under a description, its other wordings to
  swap in (marked when the numbers or dates differ) and its held-back sentences to add.
- Tests: the real cases in `tests/test_resolution.py`, and the desk screens in `tests/test_desk2.py`.

Rules worth knowing:

- "Safe cleanup" is TTE's house style (`house` in `src/shared/names.py`): case, spacing, punctuation, "&" for "and",
  a possessive "'s". So "Ministry of Social and Family Development's Lifetime Achievement Award" and the same without
  "'s" are one value.
- Two values are linked as "may be the same" when the shorter one's words are all in the longer one and both end
  the same way ("World's Best Economy Class" and "Skytrax World's Best Economy Class"), or when both are sentences of
  10 words or more that mostly share their words. Two values with different years are never linked.

Checked on a build of the deck from the database (3 Nov, in memory, nothing published):

- 383 cards built, none left out by `account_for`.
- Singapore Airlines: all 8 awards on the card, in 13 wordings; the Business Traveller awards credited to Tamil
  Murasu only; "Economy Class" not linked to "Economy Class Onboard Catering", nor "Cabin Crew" to "Business Class".
- Shanti Pereira and Iskandar Jalil: both years offered. Teo Chee Hean: still a disagreement.
- Changi Air Base East: the three runway wordings offered, marked as giving different dates.
- The 2 Nov audit, rerun: no value hidden, no credit wrong.
