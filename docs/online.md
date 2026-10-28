# The desk online

Since October 2026 the online page is the second desk (`prototype/desk.template.html`), which the reviewers chose; the zip still carries the first. Either way it is the same database behind it: the deck comes from a
table after sign-in, every decision goes to a table as it is made, and a
record is one reviewer's while it is on their desk. Up to a handful of
reviewers work the same deck without doing anything twice. The page is
served by Cloudflare Workers and rebuilt on every push to `main`; nothing in
it depends on where it is served from, so it also runs from a folder on a
laptop.

## Once

1. **Run `sql/11_desk_online.sql`** in the SQL editor. It turns on row level
   security on every table (the page carries the public anon key, and RLS is
   what keeps that key from reading anything), creates `deck`, `reviews`
   and `claims`, the two claim functions, and the private `desk` bucket.

   The news feed is Job 0 in this repository and writes `article` with the
   service role key, which RLS does not apply to.

   Then **run `sql/12_field_test.sql`**: the columns that record which model
   answered (the two log tables it also made were never used, and `sql/21`
   drops them). Then **`sql/13_desk_record.sql`**:
   the function the desk calls for the properties of a record a reviewer
   finds by search. Then `sql/14` to `sql/17`: duplicate articles, the
   desk's queue, its four groups, and `article` and `rss_feeds` closed to
   the page's key (they had a policy and a grant from before this
   repository). Then `sql/18`: the Malay and Tamil feeds; `sql/19`: the
   evaluation's labelling; `sql/20`: accounts made on the page wait for
   approval; `sql/21`: columns that never held anything, dropped. Every
   file is safe to re-run.

2. **Sign-ups stay off until `sql/20` has run**: Authentication > Sign In /
   Providers > "Allow new users to sign up". Without `sql/20`, every
   signed-in account is treated as a reviewer, so with sign-ups on, anyone
   with an email address could read the deck and save decisions (it was
   found on on 15 Oct 2026, before `sql/20` existed). With it, a new
   account reaches nothing until approved, and sign-ups can go on (step 3).

3. **Accounts.** Colleagues make their own on the sign-in screen ("No
   account yet? Make one"): name, email, and a password they choose. The
   account is made at once but waits, reaching nothing, until an admin
   approves it (`sql/20_self_signup.sql`). Supabase's free email reaches
   only the project's own team, so no confirmation link can prove who owns
   an address: check with the person before approving. Once signed in, a
   reviewer can change their own password from the line at the top of the
   page.

   To set it up, once: run `sql/20_self_signup.sql`; in the dashboard,
   Authentication > Sign In / Providers, turn "Allow new users to sign up"
   on, and under Email turn "Confirm email" off; then make your own account
   the admin and sign in again:

   ```bash
   python -m src.export --mark-admin you@example.com
   ```

   Waiting accounts then show on the admin's home page and Team page, each
   with Approve and Decline. Decline removes the account, and that email can
   sign up again. `python -m src.export --approve EMAIL` approves from the
   command line, and `--accounts` marks who is waiting.

   Accounts can still be made directly, approved as they are made:

   ```bash
   python -m src.export --account someone@nlb.gov.sg "Their Name"
   python -m src.export --account test@nlb.gov.sg "Test account" --test
   ```

   The password is generated and printed once; pass it on in person or by
   message, and keep no copy. Add `--password` to type one yourself instead:
   it is asked twice at a hidden prompt and never printed. Supabase stores
   only a hash, so a forgotten password is replaced rather than looked up:
   `python -m src.export --reset-password EMAIL` prints a new one (with
   `--password`, you type it) and the old one stops working. The person can
   then change it on the page. (Supabase's own "forgot password" email
   cannot reach colleagues, for the reason above.)

   The Supabase dashboard works too (Authentication > Users > Add user,
   "Auto Confirm User" ticked), but such an account waits for approval like
   one made on the page, and has no name until one is set; the desk shows
   the part of the email before the @ until then. To set it, or to mark a
   test account, in the SQL editor:

   ```sql
   update auth.users set raw_user_meta_data = coalesce(raw_user_meta_data, '{}') || '{"name": "Their Name"}'
   where email = 'someone@nlb.gov.sg';
   update auth.users set raw_app_meta_data = coalesce(raw_app_meta_data, '{}') || '{"test": true}'
   where email = 'test@nlb.gov.sg';
   ```

   A **test account** (`--test`) can look but not touch: it sees the real
   deck and can try the stamps, but holds no card and saves nothing, and
   the desk says so on every screen. The database refuses its writes too,
   so a colleague trying the desk can never take a record from a real
   reviewer. The mark is in the account's `app_metadata`, which only the
   service role can set; `python -m src.export --mark-test EMAIL` marks an
   existing account.

4. **`.env`** gains `SUPABASE_ANON_KEY` (Project Settings > API > anon
   public). The service role key the jobs already use stays as it is.

5. **GitHub**: the environment `automated-tte-enrichment` gains nothing new;
   the nightly publish uses the service role key already there.

## Every night

The publish step of `.github/workflows/nightly.yml` runs after Job 3 and
writes the deck (`publish_deck.yml` does the same step alone, run by hand):

```bash
python -m src.export --publish
```

One `deck` row per card, keyed by the card's own key, so a card that gains
an article overnight keeps its row and its decisions; the search index, the
NPT map and the noted list go to the bucket as `desk.json`. A card no longer
built is removed unless a review names it.

## The page

```bash
python -m src.export --site data/dist/site
python -m http.server -d data/dist/site 8000
```

then open `http://localhost:8000`. The folder holds `index.html` and the
explainer. It changes only when the template changes; the data is fetched
each time someone signs in. Opening `index.html` straight from the folder
also works in Chrome and Edge; serving it is the safer habit, since some
browsers keep a `file://` page from remembering the session.

The live copy is the same folder: `wrangler.jsonc` serves `dist/` on
Cloudflare Workers, rebuilt on every push to `main`. Nothing in it needs a
build step beyond `--site`.

## What a reviewer sees

Sign in, and the first time, **How this works** and then the languages they
read: English, Chinese, Malay and Tamil, by the outlet of each article.
Both can be opened again from the foot of the side rail (**How this works**,
**Languages**). The rail holds the pages:

- **Home**: how many records wait, by group (all records, people,
  organisations, other vocab changes, create new records), and a button to
  start or continue.
- **Review**: one record at a time, as the database deals it.
- **Results**: under **Mine**, every decision with **Change** and **Mark
  done in TTE**; under **Everyone's**, the team's view (below).
- **Analytics**: your outcomes and time per record beside everyone's.
- **Downloads**: the approved changes and every decision, yours or the
  team's, as CSV.

Evaluators also see an **Evaluation** page (`docs/evaluation.md`).

On a record to create, each value the model found can be left out with ×,
and **Edit** opens the names, every value and the description for correcting.
The **Key Vocabulary** (the TTE file it goes into, such as _People or
_Organisations) is picked by the desk and can be changed. The record goes on
the sheets under its English name. A name the article gives in Chinese, Tamil
or Malay, such as 陈劲龙 for Chen, Jinlong, goes on as its own row, TTE's link
from the English record (ENGtoCHI, ENGtoTAM or ENGtoMAY), but only where TTE
keeps that language: _People has Chinese and Tamil, and _Programmes,
_LegalActs and _Historical_Events have none. Emptied in Edit, it stays off. The sheets carry the record as the reviewer
left it, and the decision keeps what was left out and what was edited.

Nothing is pre-assigned: there is one pile, changes to existing records
before records to create and each latest news first, and the
database deals the next card that matches your groups and languages, that
has something left to decide and that nobody holds (`take_next` in
`sql/15_desk_queue.sql`). You hold one card at a time. It stays yours while
you work: the page renews the hold every 3 minutes while you click or type,
and after 60 minutes with neither it goes back to the pile. Nobody else is
ever dealt a card you hold, a decision is saved only by the person holding
the card, and a colleague's decision is never replaced. The whole of it, for
the team: `docs/load-balancing.md`.

A hold left behind lapses by itself after the hour. To put one back sooner:

```bash
python -m src.export --holds                    # who has which card
python -m src.export --release someone@nlb.gov.sg # back in the pile
```

Someone without an account makes one on the sign-in screen, and it waits
for approval (step 3 above). There is no email from the system.

The usability survey shows on everyone's home screen only while it is
switched on. The link goes into the desk file in the private bucket, not
into this public repository, and the nightly publish keeps it as it is. A
reviewer who opens it stops seeing it; switched on again for the next round,
it shows to everyone again.

```bash
python -m src.export --survey https://form.gov.sg/...  # on
python -m src.export --survey off                      # off
```

## The week's changes, for the reviewers

```bash
python -m src.export --weekly                     # the last seven days
python -m src.export --weekly --since 2026-09-21  # from a date
```

writes `data/changes/approved-changes-<date>.xlsx`, the template agreed with
the reviewers: two sheets (existing entities, new entities), one row per change
with UID, Descriptor, Key Vocabulary, Attribute, Current Value, Suggested Value,
Article URL, Reviewer, Timestamp and Status, grouped by reviewer. A record
to create carries the Key Vocabulary and the values the reviewer chose on the desk. Each reviewer
applies their own rows in TTE by hand and sets **Status** to Done. A record
reported by several articles is one card, so each change appears once. Test
accounts are left out.

## Results: done in TTE

Each approved record under **Results > Mine** has a **Mark done in TTE**
button: press it once the change is made in TTE. After that the decision is
fixed; a correction is a new edit in TTE. It is saved with the decision, so the
weekly file's Status column comes out already saying Done, and the team page
counts it. (The evaluation's weekly minutes and hand-found changes are kept in
its logs spreadsheet, `python -m src.eval sheets logs`, not on the desk.)

## The team's view

**Results > Everyone's**: every card by group (decided, kept for review, on
someone's desk, waiting), what waits by language, this week's approvals and
how many are done in TTE, how the pipeline's last run went (when the cards
were published, the newest news, the TTE dump loaded, each step's outcome),
and **who decided how many**: each reviewer's records decided today, in the
last 7 days and in all, and how many they kept for review. The admin also
sees accounts waiting for approval there. **Downloads** has the whole team's
decisions.

## The daily email

After the midnight run, each reviewer gets an email only if there is
something for them: a card on their desk, approved changes not yet marked
done in TTE, cards waiting in their part of the pile (their groups and
languages, which the desk saves to their account), or something new since
yesterday (new cards, a new TTE dump, a step that failed). Otherwise nothing.
It carries their own list and the team's totals, never anyone else's.

To turn it on, add these to the GitHub environment's **secrets**:
`MAIL_SERVER`, `MAIL_PORT` (587), `MAIL_USERNAME`, `MAIL_PASSWORD`,
`MAIL_FROM`. Without them the run prints the emails in its log instead. Put
the desk's address in `config/pipeline.toml` (`[notify] desk_url`) for the
link at the bottom. To see today's emails without sending:

```bash
python -m src.export --notify --print-only
```

## Collecting decisions

```bash
python -m src.export --reviews table --out data/decisions.csv
```

One row per proposal, joined against the cards, test accounts left out. The desk's own CSVs (from a zip round) still collect from a
folder, as before.

## What is stored where

| Table or file | Holds | Who may |
|---|---|---|
| `deck` | one row per card | reviewers read; the nightly job writes |
| `reviews` | one decision per proposal, the whole label | reviewers read all; written only through `decide` / `mark_done` (sql/15) |
| `claims` | who has which card open, and since when | reviewers read; written only through `take_next` / `claim_card` / `renew_card` / `release_card` / `decide` |
| bucket `desk/desk.json` | search index, NPT map, noted list, the pipeline's status | reviewers read |

The browser keeps a copy of a reviewer's own decisions under their account,
so a dropped connection loses nothing: anything the table lacks on the next
sign-in is written up then.
