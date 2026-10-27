# How the review desk shares out the work

**One shared pile. The database hands each reviewer one record at a time: changes to existing records before
records to create, each the newest news first. Nothing is split between people in advance, so nothing ever needs
to be redistributed.**

This page describes exactly what the online desk does. The rules live in the database
(`sql/15_desk_queue.sql`), not in the page, so an old or faulty page cannot break them. They are tested against a
real Postgres database (`tests/test_desk_queue.py`) and in the page itself (`tests/test_desk2.py`).

## What is being shared

The work is divided into **records**. A record is one TTE record, or one name that is not in TTE yet. Every
proposal about that record, from every article, is on the same card. So two people never work on the same record
at the same time, and the changes to one record are decided together.

## The rules

1. **One pile, changes first.** Every record with something left to decide is in one pile. Changes to records
   TTE already has come before records to create, as the team asked. Within each, the record whose newest
   article is most recent comes first. Choosing "Create new records" still gives you records to create.
2. **Filtered for you.** You are only given records with at least one article in a language you read, and only
   of the group you chose: "All records", "People", "Organisations", "Other vocab changes" (changes to any other
   existing record) or "Create new records" (every new record, whatever its type). Updating a record and creating
   one are kept apart because they are different decisions; only people and organisations have a group of their
   own, because over five weeks they were 87 of every 100 decisions on existing records.
3. **The database chooses, not the page.** When you press Start, or finish a record, the page asks the database
   for your next record. The database takes the first record in the pile that:
   - you can read and is in your group,
   - has something left for you to decide, and
   - nobody else holds.

   It marks that record as yours and gives it to you.
4. **You hold one record, and only one.** Taking a new record gives back the one you held, in the same step.
   However fast you click or switch types and languages, you never hold more than one.
5. **Nobody else can be given your record.** While you hold it, the database will not give it to anyone. The
   hold is one row per record in the database, which can only ever have one holder. Two people asking at the
   same instant are given two different records.
6. **Your hold lasts while you work.** While you click or type, the page renews your hold every **3 minutes**.
   However slowly you work, the record stays yours. If there is **no clicking or typing for 60 minutes** (a
   closed laptop, a meeting, home time), the hold lapses and the record goes back into the pile for someone else.
7. **Deciding is one step.** When you decide, the database saves your decision, takes back the record and gives
   you the next one, all in one call. Your decision is saved only if you still hold the record.
8. **Coming back after an hour away.** The first sign that you are back (the mouse moving, the window or tab
   coming back, a key) makes the page check your hold at once:
   - **Nobody took the record:** it is still yours. The hold is renewed and you carry on as if nothing happened.
   - **A colleague took it:** the screen moves you to your next record, with a note saying the record went back to
     the pile while you were away and a colleague has it now. This usually happens before you can click anything.

   If you click Accept before that check answers, the database still decides correctly: it keeps your decision if
   the record is still yours, and refuses it, telling you why, if a colleague has it. Nobody overwrites anybody.
9. **Stop for now** gives your record back to the pile straight away. Your decisions are already saved.
10. **"Not sure? Keep for review"** saves your doubt and sends the record to **someone else**. It is never given
    back to you. If the second person is also unsure, it goes to a third. The decision records everyone who kept it.
11. **New news about a decided record.** If tomorrow's news brings a new proposal for a record already decided,
    the record comes back into the pile with **only the new proposal** to decide. The card shows who decided it
    before, when, and what they decided. The earlier decision is not touched.
12. **Changing your own decision.** On Results, each of your decisions has a **Change** button. It takes the
    record back (if no colleague holds it) and your new decision replaces the old one. Once you mark it **Done in
    TTE**, it is fixed: a correction is then a new edit in TTE. You can never change a colleague's decision.
13. **New records every night.** The nightly run adds new records to the same pile, in the same order, so the
    newest news is on top the next morning. Records not yet decided stay in the pile. Nothing is redistributed,
    because nothing was ever anyone's except the one record on their screen.
14. **Fairness.** Results, under "Everyone's", shows how many records each reviewer has decided today, in the
    last 7 days and in all, and how many they kept for review. The pile balances the work by itself; the counts
    show who did how much of it.

## The questions asked

**If there are 500 records, can two people ever see the same card?** No. A record is given to one person at a
time, and the database enforces it (rules 3 to 5).

**Someone is slow, or idle. What happens to their records?** They only ever hold one: the record on their screen.
The other 499 stay in the pile for everyone else. If they stop clicking and typing for an hour, that one record
goes back too (rule 6).

**The first person to log in: do they get all 500?** No. They get one. The other 499 stay in the shared pile.

**A second or third person joins. Is anything taken from the first?** No. The newcomer takes the next record from
the pile. Nobody had a share, so nothing has to be divided again.

**Someone does only 5 records today.** Then the others take the rest from the pile. Nothing waits for them. Their
count on Results shows they did 5 (rule 14).

**New records at the end of the day. And the old ones?** New records join the pile in the same order, newest on top
(rule 13). Undecided older ones stay where they are. Nothing is redistributed.

**Can anyone overwrite someone else's decision?** No. The database saves a decision only from the person holding
the record, refuses to replace a colleague's decision, and lets you change only your own (rules 7, 8, 12).

**Does clicking the languages or types over and over break anything?** No. Each click gives back the record
held before taking the next, so one record at most is held. The page waits for the database's answer to the
last click (rule 4). A record you hold that is not in your new languages is given back, even from home, so home
never offers it. A group with nothing in your languages cannot be picked. Home's **Continue** is for every group,
as its number counts every group; to work on one group, press its chip.

**Is it slower?** No. Moving to the next record is one call to the database (rule 7). From Singapore that call
takes about 0.3 seconds. The records themselves are already loaded when you sign in.

**A screen left on one record for 3 hours, then Accept.** See rule 8. Either the record is still yours and your
Accept counts, or a colleague took it, and the screen has usually moved you on before the click. If not, your
Accept is refused and you are told why.

## An example day

500 records in the pile, changes first, newest first.

| Time | What happens |
|---|---|
| 9:00 | Reviewer A signs in and presses Start. A is given the newest record. 499 stay in the pile. |
| 9:30 | Reviewer B joins and is given the newest record nobody holds. A is unaffected. |
| 10:00 | Reviewer C joins, the same way. Three people, three different records, never the same one. |
| 11:00 | B has decided 5 records and goes to a meeting with one on screen. |
| 12:00 | B has not clicked or typed for an hour, so that record goes back to the pile. |
| 12:05 | A finishes a record and is given B's old one, if it is now the newest in the pile. |
| 17:00 | 150 decided between the three; 350 still in the pile. Nothing to redistribute. |
| 00:00 | The nightly run adds 40 new records, on top of the pile for the morning. |

## Asking the database for every record: the limits

Measured, not assumed:

| What | Measured |
|---|---|
| One call from Singapore to the database and back | about 0.3 s (0.1 s of it inside Supabase) |
| The database choosing the next record, 252 records (today) | a few milliseconds |
| The same with 10,000 records, the newest 9,500 all decided | 1 to 7 ms |
| Twelve people asking at the same instant | twelve different records |

- **Volume.** A reviewer makes one call per record, plus a hold renewal every 3 minutes while working. Five people
  working flat out make about a thousand small calls an hour. A database handles thousands a second.
- **Supabase's free plan** has no cap on the number of calls. Its limits are size (500 MB of data) and data sent
  out (5 GB a month).
- **What grows: the download when the desk is opened.** The page loads every record when it opens: today 2.4 MB of
  records (about 9.5 KB each) plus the 5 MB search file. Decided records are kept, so this grows. At five people
  opening the desk twice a working day, the 5 GB a month is reached at roughly 1,500 to 2,000 records. Before then
  the page should load only the records still open and the reviewer's own decisions, not everything. Not needed at
  today's size, but planned.
- **A first version was too slow at scale.** Checking each record's JSON on every call took up to 5.5 seconds at
  10,000 records. The database now keeps each record's news date, languages, type and whether it is settled (every
  proposal finally decided) as columns it maintains itself, and indexes only the open ones. That is the 1 to 7 ms
  above, and `tests/test_desk_queue.py` fails if it ever takes more than a second.

## Where the work can still be uneven

- **Effort.** The pile shares out the work; it does not make people work equally. The counts on Results show who
  did how much. Targets, if wanted, are a management decision.
- **Languages.** A record whose articles are all in Chinese can only go to someone who reads Chinese. If few
  reviewers read Chinese, those records wait longer. Results shows how many records are waiting in each language.
- **One person recorded as two.** If the AI took one real person to be two records (two spellings, say), there are
  two cards, and two people could be working on that person at once. That is a mistake about who someone is, not
  about sharing out, and the related-articles list on each card usually shows it.

## The settings

| Setting | Value | Where |
|---|---|---|
| A hold lapses after no clicking or typing for | 60 minutes | `hold_minutes()` in `sql/15_desk_queue.sql`, and `HOLD_MIN` in the page |
| The page renews the hold every | 3 minutes, if there was activity | `RENEW_MS` in `prototype/desk.template.html` |
| Order of the pile | newest article first | `take_next()` in `sql/15_desk_queue.sql` |
| The groups | People, Organisations, Other vocab changes, Create new records | `card_group()` in `sql/16_desk_groups.sql`, and `GROUPS` in the page |

## For the technically minded

Reviewers cannot write the decision or hold tables directly. Every action is a database function that checks
who is asking, through their own sign-in:

| Function | Does |
|---|---|
| `take_next(languages, type)` | gives back your record and gives you the next one |
| `claim_card(record)` | takes a named record: your own to come back to, or one you decided, to change it |
| `renew_card(record)` | keeps your hold alive while you work |
| `release_card(record)` | gives your record back (Stop for now) |
| `decide(record, decisions, languages, type)` | saves your decision if you hold the record, gives it back, and gives you the next |
| `mark_done(proposals, done)` | marks your approved changes as made in TTE |

Each record row also carries columns the database fills in itself (`newest`, `langs`, `grp`, `ord`) and a
`settled` flag kept right by triggers: a decision saved, changed or removed settles or unsettles its record, and
the nightly publish changing a card unsettles it. The queue's index covers only unsettled records.

`take_next` picks one record at a time with `FOR UPDATE SKIP LOCKED`. Each candidate record is locked as it is
read, so two people asking at the same instant skip each other's record and are given different ones. The test
that has 12 reviewers ask at the same moment checks that 12 different records come back. A first version locked
ten records per person, and nine of the twelve got nothing; that test found it.
