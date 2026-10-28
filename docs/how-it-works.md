# How the system works, from the news to the desk

This is the whole journey of one news article. It covers every step, every
value a step produces, and every rule a step follows. Each rule says where
it is written down, so it can be checked or changed.

The other docs say why things are the way they are ([design.md](design.md)),
how the parts fit ([architecture.md](architecture.md)) and how to run them
(the [README](../README.md)). This one says what happens.

## The journey at a glance

| Step | When | What happens | Rules are in | What is kept |
|---|---|---|---|---|
| 0. Collect | every two hours | Read five outlets' feeds; store each new article's headline, short description, link and date | `src/job0_ingest`, `src/shared/stories.py` | `article` |
| 1. Relevance | nightly, midnight | A model reads each headline and description and picks the ones that may change a TTE record | `prompts/relevance.txt` | `article.relevant`, `article.reason` |
| 2. Extraction | after step 1 | Read each picked article in full; a model lists the people, organisations and so on whose records it changes, with the new facts as TTE fields | `prompts/extraction.txt`, `prompts/tte/fields_brief.txt`, `src/shared/field_names.py` | `extracted_entities` |
| 3. Matching | after step 2 | Search TTE for each one; a model decides which record it is, if any, and writes each change | `prompts/resolution.txt`, the three files it takes in, `src/job3_resolution` | `candidate_matches` |
| 4. Cards | after step 3 | Gather everything about one record into one card | `src/export/cards.py` | `deck` |
| 5. Desk | any time | A reviewer answers each card: same record? which changes? create one? | `prototype/desk.template.html` | `reviews` |
| 6. Sheets | when asked | Approved changes go out as a spreadsheet for a cataloguer to make in TTE | `src/export/weekly.py`, the desk's Downloads page | files |

Nothing in this list writes to TTE. A person makes every change in TTE by
hand, from the sheet.

Beside the steps, TTE's own records are loaded into the database whenever
TTE sends a new export (see [TTE's records](#ttes-records)).

## Words used here

- **TTE**: the authority file the system proposes changes to.
- **Record**: one entry in TTE, such as a person or an organisation. Each has a **UID**, its number in TTE.
- **Key Vocabulary**: the TTE file a record sits in, such as `_People` or `_GeoBuildings`. There are nine.
- **Type**: what the system calls the same thing inside its own steps, such as PERSON or FACILITY. Eight types cover the nine vocabularies, because `_Events` and `_Historical_Events` are both EVENT.
- **Field**: one attribute of a record, such as Occupation or Awards. Field names are written exactly as TTE stores them, brackets and all: `Year Started (yyyy)`, `Affiliations(groupName)`.
- **List field**: a field holding several values, joined by ` | `. Awards is one.
- **Entity**: something an article names that may need a record: a person, an organisation, a building, a place, an event, an award, a programme or a law.
- **Proposal**: what step 3 decided for one entity from one article.
- **Card**: everything about one record, from every article, put in front of a reviewer once.
- **English record and variant names**: TTE keeps a Chinese, Malay or Tamil name as a separate small record, linked to the English record that holds all the fields. The system always proposes changes to the English record.

## 0. Collecting the news

**When.** Every two hours, at 17 minutes past.

**From where.** The feeds listed in the database's `rss_feeds` table: CNA, The
Straits Times, Lianhe Zaobao, and, since 18 October 2026, Berita Harian and
Tamil Murasu.

**What is kept for each article.** The link, the headline, the outlet's short
description from the feed, its category and its publication date. The full
text is never stored, here or later.

**Rules.**

- An article whose link is already stored is skipped.
- An article can come back at a new link: outlets move stories between
  sections and rewrite headlines. Two articles are the same story when they
  share the outlet's story number, or when the same outlet used the same
  headline within two days. Headlines an outlet reuses every day, such as
  "Must-reads" or 速读狮城, don't count. A copy is stored but marked already
  judged, so no later step works on it twice. (`src/shared/stories.py`)
- Two outlets reporting the same event are two sources, never a copy.

## 1. Relevance

**When.** Every night at midnight, Singapore time.

**What the model sees.** Only each article's headline and short description,
100 articles to a request. Never the full text.

**What it is asked.** Would this article change a record in TTE? The rules
are in `prompts/relevance.txt`:

Yes, when a named Singapore person, organisation, building, place, event,
programme or law has a concrete change that has happened or is about to:

- a person died, was appointed, retired, married, or received a named award;
  an announced appointment or departure counts even if it starts later;
- an organisation was created, merged, closed, renamed, moved or given an award;
- a building opened, closed, was demolished, renamed, given heritage status or sold;
- a place was renamed or removed;
- an event was cancelled, postponed, renamed or moved;
- a programme started or ended;
- a law was passed, amended or repealed.

No, for commentary and opinion; a person only quoted or commenting; pop-ups
and one-off events; reactions to an announcement; routine operations; court
cases; foreign entities; and plans that have not taken effect (except an
announced appointment, as above). The entity must be Singaporean: a foreign
brand with a Singapore shop is not.

**What comes back.** Only the relevant articles, each with a one-line reason.
An article left out is not relevant. The system writes a verdict for every
article in the batch at once: `relevant` true or false, and the reason.

**Why it is generous.** An article judged not relevant is never looked at
again, so a mistake here is lost for good. A mistake later shows up on a card
and costs a reviewer a click. So this step lets doubtful articles through.

## 2. Extraction

**When.** After step 1, one article at a time.

**What the model sees.** The article's full text, read from its page that
night, with its headline and publication date. A page that can't be read
(paywall, dead link) is tried on three nights, then left alone.

**What it is asked.** Five things, in `prompts/extraction.txt`:

1. List every Singapore entity whose TTE record the article changes. Leave
   out anyone mentioned only for background, or quoted without a new fact
   about them.
2. Give the new facts for each, as TTE fields.
3. Write one English sentence saying what changed (the **summary**).
4. Copy the one sentence from the article that best supports it (the **evidence**).
5. Give the English name, if the name is not in English.

**What comes back for each entity.**

| Value | What it is | Rules |
|---|---|---|
| `entity_name` | The name as the article wrote it | The most specific official name |
| `entity_name_en` | The English or romanised name | Only when the name is not English. A person is "Surname, Given name" (王振胡 → "Wong, Chin Hu"). A name the article gives in brackets comes first. Left empty rather than invented. |
| `entity_type` | PERSON, ORGANISATION, FACILITY, LOCATION, EVENT, AWARD, PROGRAMME or LEGAL_ACT | |
| `role` | `subject` or `mentioned` | The subject is what the article is about (the person appointed, the law passed); usually one or two. Everyone else is mentioned. The desk shows the subject first. |
| `summary` | One English sentence: what changed | Says who the entity is as well as what changed, so a reader can tell two people with one name apart. Always English. |
| `evidence` | One sentence copied from the article, word for word | In the article's own language. It is the proof the reviewer checks. |
| `evidence_en` | That sentence in English | Only when the article is not in English |
| `fields` | The new facts, one value per field | See [The fields](#the-fields) |
| `confidence` | high, medium or low | The model's own sense of it |

**Rules for the values.** All in `prompts/extraction.txt`:

- **English.** Every value is written in English, whatever the article's
  language. 主席 as a title is written "Chairman". Only the name keeps the
  article's form.
- **Names inside a value.** An award, organisation or person named in
  Awards, Affiliations, Parent Organisation or Founder must be findable in
  TTE. From a non-English article it is written as the article gives it,
  then the English in brackets: "博理中学 (Bendemeer Secondary School)". The
  model never coins an English name on its own.
- **Dates.** "On Tuesday", "last month" and "in March" are counted from the
  publication date, never from today. An award is "Award Name (YYYY)" with
  the year it was given. A year that can't be worked out is left out.
- **Started and ended.** These are when the entity itself began or ended
  (was founded, opened, dissolved, repealed). The date of something it did,
  such as a course it launched, is neither.
- **Announced appointments.** A person named to a post that starts later is
  extracted now, and so is the person leaving it. The post goes in
  Description and the organisation in Affiliations, with the year: "Chairperson
  of the Agency for Integrated Care from 2026". The words "will", "is set to"
  and "incoming" are never written into a field.
- **Same entity twice.** Several mentions of one entity are combined into one.

**What the code checks afterwards.** The model is asked to follow the rules.
The code then makes sure of the ones it can check (`src/shared/field_names.py`):

- A field name that is close to a real one is corrected to TTE's spelling:
  "Year Started" becomes `Year Started (yyyy)`, "Affiliations" becomes
  `Affiliations(groupName)`.
- A field the type does not have is dropped.
- A value in a field with a fixed list (Occupation, Nationality, Title,
  Feature Type, Category) is kept only if it is on the list. In a list field
  each value is checked on its own: "Lawyer | Chief Executive Officer" keeps
  "Lawyer".

An article where the model found nothing is still marked done.

## The fields

### Which fields each type has

From `prompts/tte/fields_brief.txt`, which both models are given. The code
holds the same list (`src/shared/field_names.py`).

| Type | Vocabulary | Fields |
|---|---|---|
| PERSON | `_People` | Name, Title, Description, Occupation, Nationality, Place of Birth, Birth Year (yyyy), Birth Month (mm), Birth Day (dd), Death Year (yyyy), Death Month (mm), Death Day (dd), Active Years, Achievements, Education, Awards, Affiliations(groupName), Spouse, Child, Parent |
| ORGANISATION | `_Organisations` | Name, Description, Country, Street Address, Postal Code, Founder, Year Started (yyyy), Month Started (mm), Day Started (dd), Year Ended (yyyy), Month Ended (mm), Day Ended (dd), Parent Organisation, Group Members, Awards |
| FACILITY | `_GeoBuildings` | Name, Description, Street Address, Country, Postal Code, Feature Type, Year Completed (yyyy), Month Completed (mm), Day Completed (dd) |
| LOCATION | `_Geographics` | Name, Description, Country, Feature Type, Street Address, Postal Code |
| EVENT | `_Events`, `_Historical_Events` | Name, SN, Organiser, Year, Month, Day, Category, Topic, Locality, Description |
| AWARD | `_Awards` | Name, SN, Awarding Entity, Year First Awarded |
| PROGRAMME | `_Programmes` | Name, Description |
| LEGAL_ACT | `_LegalActs` | Name, SN |

TTE has more fields than these (113 in all). The rest can't come from a news
article: links to other databases, images, sources, map coordinates and
names used only by cataloguers.

### What goes in each field

The full guideline text for every field is in `prompts/tte/field_rules.txt`,
compiled from NLB's *KOS Guidelines for Name Construction in TTE*, version
5.1. That file is for people to read; it is not sent to a model. The short
version below is what the models are given, plus the guideline's own words
where they matter.

| Field | What goes in it |
|---|---|
| Description | A short paragraph about the entity. See [Description](#description). |
| SN | A scope note: a short note on what the record covers. Used where a type has no Description (awards, laws). |
| Occupation | A lasting profession, from NLB's Occupations Thesaurus only: Engineer, Teacher, Lawyer. **A post is not an occupation.** "Chairperson", "CEO" and "Minister for Defence" go in Description. Several are joined by ` \| `. |
| Title | Royalty, nobility, religious rank, honour or office: Sir, Dr, Prof., Venerable, Haji, Dato. Never a profession or a post. The short form where there is one. |
| Nationality | The word for the people, not the country: "Singaporean", not "Singapore". Left blank if in doubt. |
| Place of Birth | "City or Town, Country"; the country alone if the town is not known. |
| Birth / Death Year, Month, Day | Each part is its own field: `Birth Year (yyyy)`, `Birth Month (mm)`, `Birth Day (dd)`. |
| Active Years | The years the person was active in their main occupation. |
| Achievements | Up to three key achievements, in three to five full sentences. **Not** awards (they have their own field), not a repeat of the description, not a list of posts, not relationships, not wrongdoing. |
| Education | The institutions the person studied at, as TTE names them. |
| Awards | An honour or prize given to the person or organisation, as "Award Name (YYYY)". **A designation is not an award**: "Senior Counsel" goes in Description. |
| Affiliations(groupName) | Every organisation the person is linked to, other than where they studied. |
| Spouse | "Name (m. YYYY)", or "Name (m. YYYY-YYYY)" once the marriage has ended. "Name (div.)" or "Name (deceased)" when only that is known. In date order. |
| Child, Parent | The person's name as TTE writes it. |
| Country | For an organisation: "Singapore", even if it no longer exists. |
| Street Address | "street number street name, #unit building name", with the street spelt in full (Road, not Rd). |
| Postal Code | The postal code. |
| Founder | The founder's name as TTE writes it. |
| Year / Month / Day Started, Ended, Completed | When the entity began, ended or (a building) was completed. Not when it did something else. |
| Parent Organisation | The organisation that controls this one. |
| Group Members | Members of a small group, such as a band. |
| Feature Type | What kind of building or place, from GeoNames, in lower case and American spelling: "hospital", "theater", "park". |
| Organiser, Year, Month, Day, Locality | For an event: who ran it, when, and where. |
| Category | For an event: a subject from SingHeritage Events. |
| Topic | For an event: a Library of Congress Subject Heading. |
| Awarding Entity, Year First Awarded | For an award: who gives it, and since when. |

### Fields with a fixed list

Five fields take only values from a list. The lists are not sent to the
models, because they cost many words and a model follows a long list
badly. The code checks the value afterwards instead and drops what is not on
the list (see step 2).

| Field | The list | Where it came from |
|---|---|---|
| Occupation | 277 terms, `prompts/tte/occupations.txt` | NLB's Occupations Thesaurus (the *Occupations Scope Notes* spreadsheet) |
| Nationality | 28 terms, `prompts/tte/vocabularies.txt` | Values already used on two or more TTE records |
| Title | 27 terms, same file | The same |
| Feature Type | 55 for buildings, 56 for places, same file | The same |
| Category | 9 terms, same file | The same |

An organisation's Country also has a list in that file (7 terms) but is not
checked by the code.

### Description

A description may be shown to the public, so it has its own rules
(`prompts/tte/description_style.txt`, from section 7 of the guidelines).
There are two sets, and which applies depends on whether the record already
has a description.

**Writing one from nothing** (a new record, or a record with none):

- Three to five sentences. Open with what best sums up the entity; this can
  be a single word ("Philanthropist.").
- Paraphrase; never copy the article.
- British spelling: organisation, colour, programme.
- No "current", "former", "then" or "now": they date the text.
- Don't list someone's posts like a CV. Give the one or two that matter most.
- Objective: no "attractive", no "best in Asia".
- No figures that change, such as staff numbers.
- Numbers under ten in words, 10 and up in figures.
- About the entity, not its relatives or associates.

**Editing one that exists:**

- Keep the wording. Make the smallest edit that carries the new fact,
  usually one clause or one sentence.
- Write it the way the description already writes things: the same dates,
  the same way of naming posts.
- Never delete a fact, however long the description is. The length and CV
  rules are for writing, not editing.
- Never swap a specific fact for a general one.
- If the article adds nothing the description lacks, propose no change.

The code checks every edit the model makes to a description
(`src/shared/description.py`):

- An edit that adds no new fact (only rewording) is dropped.
- An edit that keeps less than 70% of the old text is kept but flagged: the
  desk warns the reviewer how much survives.
- An edit that takes the description past five sentences, and makes it
  longer than it was, is flagged too.

### Is it worth a record?

When the model is deciding about a new entity, it is also given
`prompts/tte/notability.txt`, from the guidelines' appendix. A new record is
for an entity that is notable: covered seriously by sources other than
itself, not just famous and not just in one article.

- A person: a well-known award, an enduring contribution, national or
  international office, academic influence, a widely regarded creative
  career, top-level sport, or a part in a well-documented historic event.
- An organisation: cultural, heritage or national importance, significant
  awards, or an enduring contribution.
- A place: historical or architectural significance, heritage protection,
  or a named natural feature.

Someone quoted in passing, a company named only as an employer, or an
official named only for making an announcement is usually not notable. On
the desk, the reviewer makes this call ("Not worth a record").

## Four things called a summary

The word turns up in four places, and they are different things.

| What | Written by | Rules | Where it shows |
|---|---|---|---|
| The outlet's description | The outlet, in its feed | none of ours | Step 1 reads it to judge relevance |
| The extraction summary | The extraction model, one English sentence per entity | Says who the entity is and what changed; always English (step 2) | Step 3 checks it against the record. It is kept with each decision, but not shown on the desk. |
| The evidence sentence | Copied from the article, plus its English | Word for word, in the article's language (step 2) | "In the news" on every card: the original first, the English under it |
| The record's Description | The model, as a change to TTE | [Description](#description) | A change to accept, or the new record's draft |

## TTE's records

TTE sends a new export every couple of months, as a zip. Someone uploads it
to the `tte-imports` storage bucket, and the next nightly run loads it
(`src/load_tte`).

- Only the nine vocabularies above are read: 52,437 records in the
  1 September 2026 export.
- Each record keeps its UID, name, vocabulary, type, language and fields.
- Each variant name (a Chinese, Malay or Tamil record, or an older name) is
  linked to the English record that holds the fields. The system always
  works on that English record.
- A record the new export no longer has is deleted, unless a proposal points
  at it; then it is kept and marked retired.
- If an export is missing more than one in ten of the records it should
  cover, the load stops before writing anything.
- After a load, only the proposals the new records could change are worked
  out again: those whose record was retired, or where a new record is now a
  close match.

The desk's search covers the 20,852 English records that can take a change.

## 3. Matching

**When.** After step 2, one article at a time, so that entities from the
same article can inform each other.

### Finding the records it could be

For each entity, the database searches TTE's names for ones that look like
it (`sql/04_match_entities.sql`, `src/job3_resolution/candidates.py`):

- It searches under the article's name, and again under the English name if
  there is one.
- It compares spelling, letter by letter. A score of 1.00 is the same
  string. Names scoring under 0.30 are not returned.
- A variant name found is replaced by its English record.
- A record found only through the English name the model guessed is capped
  at 0.90 and marked, because the guess can be wrong.

Then the shortlist is put in order by more than the name
(`src/job3_resolution/rank.py`):

- A person recorded as dead before the article is dropped, unless the
  article is about a death.
- A record that shares a fact with the article moves up. A strong fact
  (an affiliation, an award, a birth year, an address, a school, a parent
  organisation, a family member) adds 0.20; a weak one (an occupation,
  title, feature type or category) adds 0.08; at most 0.45 in all. A record
  sharing nothing is not moved down.

The top five go to the model.

### What the model decides

The model is given the entities from one article, each with its five
records and their fields, and the rules in `prompts/resolution.txt`. Into
that prompt go three more files: the fields
(`prompts/tte/fields_brief.txt`), the description rules
(`prompts/tte/description_style.txt`) and the notability rules
(`prompts/tte/notability.txt`).

The key rules:

- **A name match is not the same person.** Compare occupation, affiliation,
  title and description. Singapore names are widely shared, so a score of
  1.00 proves only that two names are spelt the same. If the fields point
  elsewhere, it is a different entity.
- **Never fix a mismatch by overwriting.** Rewriting another person's record
  with the article's facts destroys a correct record.
- **Weigh the score.** Middling scores mean little alone. Short Chinese
  names score about 0.33 for two strangers, so the fields must agree.
- **When unsure, don't match.** A wrong match corrupts a record; leaving it
  out only means a new record is proposed.
- **Use the other entities.** If a person chairs an organisation that
  matched confidently, that supports the person's match too. Entities from
  different articles never inform each other.
- **Values in English**, since every record changed is an English record.

It gives one of these answers for each entity:

| Answer | Means | On the desk |
|---|---|---|
| (nothing) | Not in TTE. This is the default and is never written out. | "Create a record?" |
| MATCH_AND_UPDATE | This is the record; here are the changes | "Same record?", then each change |
| FLAG_AMBIGUOUS | Two records could be it, or the evidence conflicts | "Same record?", marked "Two records could be this entity" |
| FLAG_DB_DUPLICATE | Two of the records look like the same entity | Marked "The knowledge base may hold duplicates" |
| RE_QUERY_REQUIRED | Probably in TTE under another name, with a name to try | Marked "May exist under another name" |

A match can come with no changes. That means the record already holds what
the article says, which is common and correct.

### How a change is written

Each change says how it joins what the record holds:

| How | For | Rule |
|---|---|---|
| APPEND (add) | List fields: Awards, Affiliations, Education, Group Members, Achievements | Only the new items, never a repeat. In the record's own style: if its awards read "Name (YYYY)", the new one does too. |
| MERGE (rewrite) | Description | The whole edited paragraph, following the editing rules |
| REPLACE | A value the news makes wrong: Occupation, Title, Death Year, Street Address | The old value does not survive |
| INSERT_RELATION (link) | Links to other records: Parent, Child, Spouse, Founder, Parent Organisation | |

Announced appointments are written as in step 2: the organisation added to
Affiliations, the post worked into Description with its year, never "will".

### What the code checks afterwards

(`src/job3_resolution/update.py`, `src/shared/names.py`)

- An answer for a name the article did not produce is dropped.
- A value naming another record (an award, an organisation, a founder) is
  rewritten as TTE names that record, when TTE has it. "Housing and
  Development Board" becomes "Singapore. Housing and Development Board", so
  the sheet carries what the cataloguer will type. What the article wrote is
  kept beside it. TTE's house style is set aside when comparing: "Singapore."
  in front, "(Singapore)" behind, "The", "'s", "Award" or "Awards", and "&"
  or "and".
- A description edit gets the checks in [Description](#description).

Nothing here changes TTE. The answers are stored as proposals.

## 4. Cards

**When.** Every night, after step 3 (`python -m src.export --publish`). The
cards go to the `deck` table, which the desk reads. All of this is in
`src/export/cards.py`.

**One card per record.** Every proposal about the same TTE record, from every
article, becomes one card, so the reviewer answers "is this the same
record?" once. Where nothing matched, proposals with the same name share a
card.

**Which entities get a card.**

- The article's subject gets one whenever there is anything to decide,
  including "not in TTE yet".
- Any other entity gets one only if the model proposed a change or raised a
  flag.
- An entity the model left out, though a record has its name almost
  exactly (a score of 0.95 or more, under the article's own spelling, not a
  guessed English one), gets a card asking "same record?" rather than
  "create?".
- Everything else is a line under the article, "Also in this article".

**Which records are offered.** Only records whose score is within 0.25 of
the best one. At 1.00 against 0.33 there is one real answer, not three.
These are the **Possible TTE records** tabs on the desk.

**What each change shows.** For each record offered, the card works out what
the article would change on it, field by field: not on the record, adds to
what is there, worded differently, or already recorded. Choosing another
record works this out again.

**Joining what several articles said.**

- Two articles giving the same fact are one change, with both as sources.
- If they give different years for it, the card says so and offers both.
  The reviewer picks.
- Two articles rewriting one description are put together into one
  rewrite, sentence by sentence.

**Changes the model did not propose.** If the article gave a fact the record
lacks and the model did not propose it, the card offers it as well, marked
as such. Description is never offered this way.

**The right quote for each change.** Each change shows the sentence that
backs it. If the entity's own evidence sentence doesn't mention the fact,
the card looks for a sentence from the same article that names this entity
and does.

**Non-English names.** When an article's Chinese, Malay or Tamil name is
confirmed against an English record that doesn't hold that name, it is
asked as one more change, "Non-English name". It goes on the sheet as TTE's
link: ENGtoCHI, ENGtoMAY or ENGtoTAM. It is asked only where TTE keeps
that language: Chinese and Tamil for people; Chinese, Malay and Tamil for
organisations, buildings, places, events and awards; never for programmes,
laws or historical events, which TTE keeps in English only.

**Order.** Newest news first, by the card's newest article. Within one
article, the subject first.

## 5. The desk

The reviewer signs in. The database deals one card at a time, from one
shared pile: newest news first, only cards with an article in a language
the reviewer reads, and one card held per person for up to an hour
([load-balancing.md](load-balancing.md)).

### What a card shows

- **In the news**: each article, numbered. For each: the outlet, the date,
  the headline, a link to the article, and the evidence sentence (the
  original first, the English under it). An article in a language the
  reviewer reads comes first.
- **The TTE record**, set against what the article says: name, then the
  facts that tell people apart (born, died, role, title, affiliation,
  awards, and so on). "Role" is TTE's Occupation.
- **Possible TTE records**: the other records it could be, as tabs.

### The questions, and what each button records

**Same record?** (a card with records offered)

- **Same record** goes on to the changes, or, if there are none, records
  "Nothing to change".
- **Discard** drops the card: nothing from it goes on the sheet.
- Another tab, **Search TTE**, or **+ New record**, if the record shown is
  the wrong one.

**Each change** (one field at a time)

- Grey is what TTE holds now; green is what would be added; red and struck
  through is what a rewrite removes. A field TTE holds nothing for says
  "nothing in TTE yet".
- **Add / Replace**: whether the value joins the list or takes the place of
  what is there.
- **×** leaves one value out; **Edit** corrects the wording.
- **Accept** puts the change on the sheet; **No change** leaves the field
  as it is. After the last change the card is recorded as "Amended", or
  "Nothing to change" if no change was accepted.

**Create a record?** (a card with no match)

- The draft record: its name, its Key Vocabulary (which can be changed) and
  its fields. Values naming another record say whether TTE has it ("IN TTE"
  or "NOT IN TTE"). **OneSearch** looks the name up in NLB's collections.
- **Create a new record** records "To create"; **Not worth a record** records
  that.
- The Possible TTE records and **Search TTE** are there in case the matching
  missed it.

**On every card**

- **Not sure? Keep for review** passes the card to a colleague.
- **Stop for now** goes back to Home; the card returns to the pile.

### Rules the desk applies

These are on the desk itself, in `prototype/desk.template.html`:

- A field that holds one value (a date part, a postal code, an address, a
  place of birth, a feature type) defaults to Replace, since adding a
  second value would write "12 | 05".
- Achievements is a paragraph, not a list: an addition is a sentence added
  to the end.
- A date's day, month and year are one change ("Date started"). On the
  sheet, each part that changes is its own row.
- A card decided before comes back only if new news arrives, and then asks
  only what the new articles add.
- A reviewer can change their own decision until it is marked done in TTE.

## 6. The sheets

Nothing is applied to TTE automatically. The desk's decisions come out as
spreadsheets, and a person makes each change in TTE.

- **The weekly file** (`python -m src.export --weekly`): one Excel file a
  week, with two sheets, changes to existing records and new records. One row
  per change, grouped by reviewer. Columns: UID, Descriptor, Key Vocabulary,
  Attribute, Current Value, Suggested Value, Article URL, Reviewer,
  Timestamp, Status. The reviewer sets Status to Done once the change is in
  TTE. Test accounts are left out.
- **The Downloads page** on the desk: the approved changes (one row per
  accepted change, plus the records to create) and every decision, each as
  the reviewer's own or everyone's.

A non-English name goes on the sheet with the Attribute ENGtoCHI, ENGtoMAY
or ENGtoTAM, on the English record.

## Every rule, and where it lives

To change a rule, change the file. A prompt file takes effect on the next
nightly run. A rule in code needs its tests run (`pytest`).

| Rule | Told to the model in | Checked by code in |
|---|---|---|
| What makes an article relevant | `prompts/relevance.txt` | |
| Which entities to extract; summary; evidence; English name | `prompts/extraction.txt` | |
| Values in English; names with the original beside them | `prompts/extraction.txt`, `prompts/resolution.txt` | `src/export/cards.py` (an English-only field keeps the English) |
| Dates counted from the publication date | `prompts/extraction.txt` | |
| Announced appointments, no "will" | `prompts/extraction.txt`, `prompts/resolution.txt` | |
| Which fields each type has, and their names | `prompts/tte/fields_brief.txt` | `src/shared/field_names.py` |
| What goes in each field (full guidelines) | not sent: `prompts/tte/field_rules.txt` is for people | |
| Occupation from the thesaurus | `prompts/tte/fields_brief.txt` (that posts are not occupations) | `src/shared/field_names.py`, against `prompts/tte/occupations.txt` |
| Nationality, Title, Feature Type, Category from lists | | `src/shared/field_names.py`, against `prompts/tte/vocabularies.txt` |
| Writing and editing a Description | `prompts/tte/description_style.txt` | `src/shared/description.py` |
| Whether an entity is worth a record | `prompts/tte/notability.txt` | the reviewer |
| A name match is not an identity match | `prompts/resolution.txt` | the reviewer |
| Dead people dropped; shared facts rank higher | | `src/job3_resolution/rank.py` |
| Add, rewrite, replace, link | `prompts/resolution.txt` | the desk (single-value fields replace) |
| Linked values named as TTE names them | `prompts/extraction.txt` (original plus English) | `src/shared/names.py`, `src/job3_resolution/update.py` |
| One card per record; who gets a card; order | | `src/export/cards.py` |
| Non-English names as ENGto links | | `src/export/weekly.py` and the desk (`VOCABS` in both) |
| Which model answers each step | | `config/pipeline.toml` |

## What the system does not do

- It never changes TTE. Every change goes through a reviewer and then a
  cataloguer.
- It never stores an article's text. A change to the extraction prompt
  means reading the pages again, and a page that has since gone is lost.
- It never decides a new record is notable, or that two records are
  duplicates. It raises the question; a person answers it.
- It does not handle a rename between organisations (Successor and
  Predecessor are links in TTE, not fields), or an article that contradicts
  the record, such as a different birth year. Both are open questions.
