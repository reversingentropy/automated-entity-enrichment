# The same new record, created twice

## The problem

Most cards on the desk ask "create a record?". On 1 November 2026 that was 269 of
380.

When a reviewer creates a record, the system forgets it. It learns about the
record only when the next TTE dump arrives. Dumps come every two to eight months
(three and a half on average). Until then, a new article about the same thing
asks "create?" again, and someone may create it a second time.

Updates to existing records do not have this problem. Ten articles about one
person become one card, because they all point at the same TTE record.

## What happens today

- **Same name, one card.** Articles that name the same thing the same way land on
  one card. 26 new-record cards had two or more articles.
- **Different spelling, two cards.** "Kuah Boon Wee" and "Kuah, Boon Wee" were two
  cards. **Fixed on 1 November 2026** (below).
- **Already created, asked again.** A created record that is in the news again
  comes back as "create?". It carries a note saying it was decided before, but
  nothing stops a second create.
- **Two reviewers.** Each reviewer types their own new records into TTE from
  their own sheet. Neither sees the other's.

## How often it happens

| How | Example | Count |
|---|---|---|
| Same name, different spelling | "Kuah Boon Wee" and "Kuah, Boon Wee" | about 1 new entity in 10. Now fixed |
| Name differs by more than spelling | "Great Eastern Women's Run" and "… 2026" | about 6 pairs on the desk today |
| In the news again after it was created | created in November, back in December | live: 5 of 394 came back a week or more later. Archive: 6% came back, most a month or more later |
| Two reviewers create the same thing | | unknown until real decisions are made |

Some look-alikes are different things: "Garden Waterfront I" and "Garden
Waterfront II" are two buildings. So names alone can't decide.

A duplicate in TTE costs a cataloguer a few minutes to find and merge. Search
results are wrong until then.

## Done: one name, written two ways

New records are now grouped by their name without commas, full stops, quotes,
"The", capital letters or extra spaces. "Kuah Boon Wee" and "Kuah, Boon Wee" are
one card. Chinese and Tamil names keep all their letters.

On the desk on 1 November this joined four pairs of people, and new-record cards
went from 269 to 261.

## The bigger fix: remember what was created

**The idea.** When a reviewer creates a record, save it in the same table as the
TTE records, marked "made on the desk, not in TTE yet".

**Why that table.** Everything already looks there: the step that matches news to
records, the step that re-checks matches after a dump, and the desk's search. So
everything would find the new record without being taught to.

**What reviewers would see.** The next article about it shows up as "same
record?", like any existing record, with a label: "created on the desk by
Reviewer A, 3 Nov · not in TTE yet". A reviewer who searches before creating
finds it too. No new screens. No warnings.

**On the weekly sheet.** An update to a record still being created goes under that
record's name, with a note: "being created by Reviewer A: create it first".

**When the TTE dump arrives.** Each desk record is looked for in the dump. Found:
the desk copy goes, and the real record takes over. Not found after two dumps:
listed, so a person can check whether it was ever typed in.

**How it would be built.**

1. Mark each row in the records table as from TTE or from the desk.
2. Each night, before matching, add the day's created records as desk rows.
3. Tell the TTE loader to leave desk rows alone. Today it deletes any row the dump
   doesn't have, so it would delete them all.
4. Tell the re-check step to leave decided cards alone. Today it would wipe them.
5. Show the label on the desk, and the note on the weekly sheet.

To undo it, delete the desk rows.

## For and against

**For**
- It stops repeat creates in the months between dumps.
- It uses what the system already has. One table, one search, as now.
- Every created record can be followed: found in a dump, matched again, or never
  typed in. The evaluation can use that.

**Against**
- It happens a few times a month, as far as we can tell. The real number is
  unknown until reviewers make real decisions.
- A desk record has fewer details than a TTE record. Two people with the same name
  might be matched to it too easily. The reviewer's "same record?" check catches
  this, but it is one more thing to watch.
- Two existing steps must be told to leave desk rows alone. If either is missed,
  records are deleted or decisions wiped.

## Other ways, not recommended

- **A separate list of created records.** Does the same job, but every step would
  need to look in two places. More complicated for the same result.
- **Desk-only patches.** Stop "create?" being asked twice, or warn about look-alike
  names on the create screen. Cheaper, but they only cover the same spelling, add
  questions for reviewers, and the bigger fix would replace them.

## Is it worth it?

How sure I am the bigger fix is worth building: **65 out of 100.**

- +40: it stops repeat creates in the gap between dumps, which can be months.
- +25: it reuses what is there, with no new search and no new screens.
- −20: it seems rare today, and that isn't proven yet.
- −15: two existing steps must be changed carefully, or records are lost.

Two ways to go:

1. **Build it before the trial.** A few days of work and testing. No duplicates are
   made while we wait.
2. **Wait a month into the trial.** Count how many duplicates real reviewers make.
   Build it if it is more than a handful.

My lean is 2. If the team says duplicates in TTE are costly, 1.

## For the team to decide

1. Is a duplicate in TTE a serious problem, or routine clean-up?
2. Do cataloguers check for records colleagues created that are not in a dump yet?
   How?
3. Should reviewers see each other's new records before typing them into TTE?
4. Build before the trial, or wait a month?
