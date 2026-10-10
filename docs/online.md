# The desk online

Since October 2026 the online page is the second desk (`prototype/desk.template.html`), which the reviewers chose; the zip still carries the first. Either way it is the same database behind it: the deck comes from a
table after sign-in, every decision goes to a table as it is made, and a
record is one reviewer's while it is on their desk. Up to a handful of
reviewers work the same deck without doing anything twice. Nothing here
depends on where the page is served from; it runs from a folder on a
laptop, and would run unchanged from a static host later.

## Once

1. **Run `sql/11_desk_online.sql`** in the SQL editor. It turns on row level
   security on every table (the page carries the public anon key, and RLS is
   what keeps that key from reading anything), creates `deck`, `reviews`,
   `claims` and `access_requests`, the two claim functions, and the private
   `desk` bucket.

   Before running it, check what key the **news feed** writes `article`
   with. The feed is not this repository's code. If it uses the anon key,
   RLS on `article` will stop it; give it the service role key first.

   Then **run `sql/12_field_test.sql`**: the columns that record which model
   answered, and the evaluation's two logs. Then **`sql/13_desk_record.sql`**:
   the function the desk calls for the properties of a record a reviewer
   finds by search. All three files are safe to re-run.

2. **Turn sign-ups off**: Authentication > Providers > Email > "Allow new
   users to sign up" off. Accounts are made by hand.

3. **Create the accounts**, one line each, with the service role key
   already in `.env`:

   ```bash
   python -m src.export --account glenn@nlb.gov.sg "Glenn Hong"
   python -m src.export --account test@nlb.gov.sg "Test account" --test
   python -m src.export --accounts
   ```

   The password is generated and printed once; pass it on in person or by
   message, and keep no copy. Supabase stores only a hash of it, so a
   forgotten password is replaced rather than looked up:
   `python -m src.export --reset-password glenn@nlb.gov.sg` prints a new one
   and the old one stops working. (Supabase's own "forgot password" email
   needs a reset link back to the page, which a page opened from a folder or
   `localhost` cannot give it.) Supabase signs
   people in by email and password; a "username" is the part before the
   `@`, and the name on the desk is the one given here (the user's metadata
   `name`). The dashboard does the same by hand (Authentication > Users >
   Add user, "Auto confirm user" ticked).

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

`.github/workflows/publish_deck.yml` runs after Job 3 and writes the deck:

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
explainer. It is built once and again only when the template changes; the
data is fetched each time someone signs in. Opening `index.html` straight
from the folder also works in Chrome and Edge; serving it is the safer
habit, since some browsers keep a `file://` page from remembering the
session.

To put it on a host later, the folder is the whole site. Nothing in it needs
a build step.

## What a reviewer sees

Sign in, then once per browser: the languages they read and which groups to
work on (people, organisations, legal acts, everything else), changeable
under **settings** in the masthead. Then the desk, as in the zip: three
practice records the first time, **How this works** in the tray, **Your
sheet** at the top with every decision, the filters and the two downloads.

Nothing is pre-assigned: there is one pile, latest news first, and the
next card that matches your groups and languages, that nobody has decided
and nobody holds, is checked out to you as it is dealt. It is yours until
you stamp it, with no time limit: sign out or close the laptop and it is
the first card you see next time. Nobody else is ever dealt it, so no
record is ever worked twice. The count in the masthead says how many the
others have done.

Someone away with a card on their desk keeps it until they return. To put
it back in the pile:

```bash
python -m src.export --holds                    # who has which card
python -m src.export --release glenn@nlb.gov.sg # back in the pile
```

Someone without an account sees **No account? Ask for one** on the sign-in
screen. The request lands in `access_requests`:

```bash
python -m src.export --requests
```

lists the open ones with the SQL to mark them handled once the account is
made. There is no email from the system; the person making the account
writes to them.

## The week's changes, for the reviewers

```bash
python -m src.export --weekly                     # the last seven days
python -m src.export --weekly --since 2026-09-21  # from a date
```

writes `data/changes/approved-changes-<date>.xlsx`, the template agreed with
Yaw Huah: two sheets (existing entities, new entities), one row per change
with UID, Descriptor, Vocab Class, Attribute, Current Value, Suggested Value,
Article URL, Reviewer and Timestamp, grouped by reviewer. Each reviewer
applies their own rows in TTE by hand and sets **Status** to Done. A record
reported by several articles is one card, so each change appears once. Test
accounts are left out.

## Your sheet: done in TTE, and the evaluation's logs

Each approved record on **Your sheet** has a **mark done in TTE** button: press
it once the change is made in TTE. It is saved with the decision, so the
weekly file's Status column comes out already saying Done, and the team page
counts it.

Below the sheet are the evaluation's two logs (`docs/evaluation.md`): **This
week**, the minutes spent and changes found, by the way you worked; and **A
change you found**, one row per change or new record. The sheet shows no
cards, so someone working by hand can use it without seeing the app's
proposals. Only the reviewer and the evaluation see these; collect them with

```bash
python -m src.export --logs            # data/evaluation/change-log.csv and weekly-log.csv
```

## The team page

**the team** in the masthead: every card by group (decided, kept for review,
on someone's desk, waiting), what waits by language, this week's approvals
and how many are done in TTE, and how the pipeline's last run went (when the
cards were published, the newest news, the TTE dump loaded, each step's
outcome). No one's individual numbers are shown. It also downloads the whole
team's decisions.

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
| `reviews` | one decision per proposal, the whole label | reviewers read all, write their own |
| `claims` | who has which card open | reviewers read; written only through `claim_card` / `release_card` |
| `access_requests` | who asked for an account | anyone may insert; only the service role reads |
| `change_log`, `weekly_log` | the evaluation's two logs | each reviewer their own; the service role all |
| bucket `desk/desk.json` | search index, NPT map, noted list, the pipeline's status | reviewers read |

The browser keeps a copy of a reviewer's own decisions under their account,
so a dropped connection loses nothing: anything the table lacks on the next
sign-in is written up then.
