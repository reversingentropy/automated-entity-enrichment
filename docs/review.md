# Review: cards, the desk, and what comes back

## The cards

```bash
python -c "from src.export.cards import write_cards; write_cards('data/cards.json')"
```

`src/export/cards.py` builds one card per **decision** straight from
`candidate_matches`, `extracted_entities`, `article` and `entities`. The data is
embedded in a published Artifact that presents them one at a time.

A card asks two questions in the order a reviewer answers them: which record is
this, then what should change on it. Proposals resolving to the same record are
merged, so four articles about one person are one identity decision rather than
four, which reduced 76 cards to 55 on the first corpus. Only *plausible*
candidates are offered: trigram always returns its best five, but at 1.00
against 0.33 there is one candidate, not three.

Rejecting every candidate asks why, because the answers mean different things
downstream. A **homonym** says retrieval worked and the entity is genuinely
absent; **not in TTE yet** says nothing about the records offered; **can't tell**
is an honest answer that should not be forced into either.

Every candidate record carries its own **delta**: what the article says, set
against what that record already holds, field by field: *not on the record*,
*adds to what is there*, *different wording*, *already recorded*. It re-computes
when the reviewer picks a different record, because "which record is this?" and
"what would that change?" are the same question asked twice.

This exists because 16 of 49 cards proposed no change at all. The authority
record already held the fact. Bob Tan's Distinguished Service Order was
catalogued before the article announcing it was read. Without the delta those
cards showed a *Confirm match* button over an empty space, which reads as a
broken page rather than as an answer.

The first reviewer then said what those cards were: a waste of attention,
eighteen of fifty-three. So a card is dealt only when there is something to
decide, and the deck is ordered by article with the article's **subject**
first. The extraction model now says which entity an article is about
(`role`, sql/10); for rows written before it did, the name in the headline is
the subject and a new law, event, award or programme is the news. The rules:

- The subject is dealt whenever there is anything to decide, including "this
  is not in TTE yet: create a record?", which the old deck never asked and
  which is where the Bill, the new chairman and the new commissioner went.
- Any other entity is dealt only if the model proposed a change to it or
  flagged it.
- Everything else the article named is one line under the documents, "Also
  in this article: ...", with what became of each: its own card, on record
  with nothing to add, or not in TTE and only mentioned.
- An article whose subject is on record and up to date is not dealt at all;
  it is listed at the end so the reviewer can see it was read.

On the first deck that turned 53 cards, 18 of them empty, into 116 with
something to decide (63 of them "create a record?") and 80 entities noted.

A rewrite is shown as a **diff** rather than two paragraphs: unchanged text
muted, additions highlighted, removals struck. Nobody can compare two
400-character descriptions by eye, so a MERGE was effectively unreviewable
without it. Building it surfaced a real defect: 7 of 22 prose rewrites keep
under 70% of the existing text, and one keeps 8%, cutting Teo Chee Hean's
636-character description to 405 and deleting his Navy career, his years as
Deputy Prime Minister and every constituency he held, while still labelled
MERGE. Those now carry a warning saying how much survives.

The warning had to be measured correctly to be worth anything.
`difflib.SequenceMatcher.ratio()` is `2*matched/(len(old)+len(new))`, so
*adding* text lowers it: six rewrites that deleted nothing at all scored below
0.70 purely by growing, and Tommy Koh scored 0.47 while keeping every word.
`kept_ratio()` therefore measures matched characters over the length of the old
text alone. Deletion is the only thing a reviewer needs warning about.

The reviewer can edit the proposed wording in place, so "right fact, wrong
phrasing" is a correction rather than a rejection, and can search all 20,800
canonical records when the retriever offered none that fit. A choice made that
way records `foundBySearch`, which is worth more than the match itself: it
marks a case retrieval should have found.

Decisions are written to the artifact's own database, so they can be read back
without passing a file around.

## Sending it to reviewers

```bash
python -m src.export --package data/dist/tte-desk.zip
```

Builds the review desk as one standalone HTML file, with `pipeline.html`
and a README beside it. Reviewers open it from disk with no account, no
install and no network, work through the cards, and download two sheets,
from *Your sheet* at any time or at the end: every decision
(`review-decisions-<name>.csv`, what the pipeline needs back) and the
approved changes (`approved-changes-<name>.csv`: one row
per attribute with TTE_UUID, Attribute, Current_Value, Proposed_Value,
Article_URL, Article_Title, Article_Summary, Person Who Approved, the
columns the first reviewer asked for). The published artifact needs a Claude
account and organisation membership, which rules out sending it to a team; a
local file also has an advantage the artifact does not, in that it may start
a download.

A Chinese name confirmed against an English record adds a row to the
approved-changes sheet, "Variant name", because TTE holds the Chinese name for
only one in four of the people the news mentions and the review is where the
missing ones are found. A "create a record?" for a non-Latin name says the
English spelling was the model's guess and opens the search first, which
matches the opening of each record's description as well as its name.

The proposal is stated on the article's side: the attribute, the value in
pencil, and what the field would read afterwards. The TTE record on the right
is shown as it is and never drawn on; when the pencilled value sat on the
record, the first reviewer could not tell the proposal from the record. An
award value carries a badge, *in TTE* or *not in TTE yet*, because an award
must have its own record before it can go on a person's, and a reviewer who
has to notice that unaided will forget to. The labels are plain: *Same* /
*Not this record* / *Keep for review*, then *Accept* / *No change* / *Edit the
wording*; the desk metaphor's own words ("pencil it in", "pending tray",
"look further back") cost the first reviewer time and are gone.

When the CSVs come back:

```bash
python -m src.export --reviews data/reviews/ --out data/decisions.csv
```

One row per reviewer per proposal, from the desk's own CSVs or from documents
saved out of the artifact's database (stored per reviewer at
`labels/<proposal>/reviews/<name>`, because a single document per proposal
means the second verdict silently replaces the first, and disagreement between
reviewers is the most useful signal in the file).

What the first reviewer's sheet said, 15 September 2026, 14 cards of 53:
identity confirmed 14 of 14, one by search after the extractor romanised
李全盛 as "Lee, Choon Seng", a real record for a different man; 13 of 16
field changes accepted, the three rejected being two description rewrites
and one affiliation; one card unsure. The 39 undecided cards were mostly
the identity-only kind, set aside as waste, which is what the rules above
answer.

The second reviewer's sheet, 17 September 2026, 38 records, was operational
rather than about the cards, which is the sign the cards had settled. What
it asked and what each became:

| Asked | On the desk |
|---|---|
| A count per verdict as you go | A tally by outcome under the masthead count: *same*, *amended*, *to create*, *not worth*, *not sure*. Not on the buttons, which change with the screen |
| What happens after the last record; a consolidation | *Your sheet*, at the top at any time: every decision listed, filtered by outcome, type or name, reopened with a click, the two downloads at the bottom. The end sheet counts in the same words |
| Accept only part of an amendment | *Leave out* on each value of a list field and each sentence added to a description; the rest is accepted with nothing to type, and the sheets carry what was kept |
| A lighter background | *Light desk*, beside the sound toggle, remembered |
| Start from an entity type, for allocating staff | *Work on* at sign-in, the deck's own groups with counts. In the file version it is also how two reviewers divide the deck |
| Show NPT matches, labelled | A candidate reached through a non-preferred term shows it (`Koh, Tommy · NPT 许通美`), on the chip and on the record; search finds records by their NPTs and says so. Most candidates arrive this way: 1,714 of 2,899 in a sample. A variant that is the record's own words in another order is not shown |
| "Not worth" and "Skip": the same? | *Skip* became *Next*, then went altogether at the team meeting (below): no skipping; *Keep for review* is the way to set a record aside |
| Use age to confirm identity | Already so: the resolution prompt carries the evidence sentence and the candidate's birth year, and the model does the arithmetic. No rule was added |
| If I stop at 20 and a colleague signs in, what do they see? | In the file version, everything, from record 1. Online, the deck is shared: a record on someone's desk or already decided is not dealt to anyone else, and the count says what the others have done. See `docs/online.md` |

His screenshot of *Tommy Koh is not in TTE* with Koh, Tommy in the
candidates exposed a wording fault, not a matching one: an entity the model
leaves out of its answer is CREATE_NEW by the prompt's contract, and the card
asserted what the model never judged. An omission whose best candidate is an
exact hit through the article's own spelling is now the identity question,
folded into the card another article's match produced where there is one.
Four cards in that deck; see `docs/gotchas.md`.

The team meeting of 21 September 2026 (Glenn, Yaw Huah, Min Hoon) set how
five people will run the desk for a three-to-six-month parallel test against
their manual reading. On the desk itself:

| Asked | On the desk |
|---|---|
| Rename "Not sure" to "Keep for review"; remove redundant choices | *Keep for review* (key K), for records the team should discuss. *Next* and *Previous record* are gone: the tray is *Back one step* and nothing else, and any record is reopened from *Your sheet* |
| No arbitrary skipping | No skip. A record not settled is kept for review, which is a recorded decision |
| Move "How this works" away from the action buttons | In the masthead, beside *Your sheet* |
| "Back one step" does not work | It undid within a record correctly; on a record's first screen it went to the previous record's last screen with no word of the decision, and on the very first record did nothing. Now disabled with a reason when there is nothing to undo, and a line says *Decided: amended, stamp again to change it* when it lands on a decided record |
| Time savings against the manual reading | Every decision records the seconds the card was on the desk; the sheet's tally shows the median, and the decisions CSV carries the column |

The rest of the meeting (one reviewer per card enforced, languages
filtering online, the team's own TTE updates, the log of misses and the
evaluation design) is in `docs/online.md` and `docs/evaluation.md`.

A screen-by-screen review on 28 September 2026, at 1440x900 and at a
1280x720 laptop's size, changed the desk before the field test:

| Found | Changed |
|---|---|
| On a 1280x720 screen the three stamps were below the fold on every screen; each decision needed a scroll | The stamps and *Back one step* sit in a bar held at the foot of the window |
| Text on the brown desk measured 1.8:1 (masthead links) to 3.7:1 (the question) against it | A darker brown; all text on the desk at 4.5:1 or better, in every theme |
| Headlines showed `&#039;` | Feed titles are unescaped when the cards are built |
| Stamp faces such as "Same. 1 attribute to edit (the article adds these; nothing was proposed)" | Short faces, with what comes next in a line under each ("then 5 changes, one at a time") |
| "name similarity 0.62" on the record | Removed; the score still orders the candidates |
| Accept in red, which reads as stop | Accept, Same record and Create in green |
| Seven equal links in the masthead | *Your sheet* and *The team* as buttons, *How this works* as a link, the rest in a menu under the reviewer's name |
| "attribute 1 of 5" in faint type at the foot | A line above the question: "Record 1 of 170 · Goh, Yihan · change 1 of 5" |
| Five tutorial sheets before any practice | One sheet of five points, then the practice records |
| "Create a record?" showed an empty card | The record a create would make, drawn from the article's facts, on a card with a dashed edge; the nearest names are labelled as ones the model matched none of |
| Two sources' wordings of one sentence were both added to a description | Near-identical sentences from different sources are one addition; the other wording is offered as a swap |
| Searching "Lee" listed Jubilee Church first | Names with a word starting with the search come before names containing it |

## Proposals as a spreadsheet

```bash
python -m src.export                       # writes proposals.csv
python -m src.export --action MATCH_AND_UPDATE
```

Flattens `candidate_matches` to one row per proposed field change, with the
record's **current** value beside the proposed one so a reviewer can see what an
`APPEND` extends or a `REPLACE` would discard. Two empty columns, `verdict` and
`reviewer_note`, are theirs to fill in.

This is stage 6 in miniature: `entities` is a read-only mirror, so approved
changes leave as a spreadsheet rather than being written back, where the next
authority import would overwrite them.

A labelled file also seeds an **evaluation set**. The unit tests cover code, not
model behaviour, and the two worst bugs found so far were behavioural: field
updates silently absent from every match, and a name collision being matched
rather than flagged. Neither could fail a unit test. Frozen labelled cases turn
each future prompt change into a measurement instead of a guess.

## Explaining it to someone else

`docs/pipeline.html` is a standalone page for people who know nothing about the
project: what an authority file is, why records go stale, and one real article
followed from the morning it was published to the edit a librarian is asked to
approve (article 2197, Gerard Ee, 31 August 2026). Every figure in it was read
from the live database rather than transcribed, so it goes stale the same way
the README does -- re-read the counts before sharing it.

It ends with the known failure modes, worst first, because a page that only
describes the happy path is not much use to a reader deciding whether to trust
the output.
