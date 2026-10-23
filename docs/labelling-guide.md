# Labelling guide

The rules labellers follow on the desk's Evaluation page, one short set per
sheet. Each is written from the prompt the AI runs on, so a labeller checks
the AI by the rules it was given. Each section records the version of the
prompts it was written from; when a prompt changes, the tests stop until
the section has been checked against it (`tests/test_eval_online.py`).

## Relevance {#relevance}

Written from `prompts/relevance.txt` (version 0ad40ab9).

**Relevant** if the headline or summary reports a real change to a named
Singapore person, organisation, building, place, event, programme or law:

- someone died, was appointed or left a post (announced counts), retired,
  married, or received a named award
- an organisation was set up, merged, closed, renamed or moved
- a building opened, closed, was demolished, renamed or given heritage status
- an event was cancelled, postponed or moved; a programme began or ended;
  a law was passed or changed

**Not relevant:** opinion pieces, people only quoted or mentioned,
reactions, court cases, routine updates, pop-ups, foreign brands, and plans
not yet in effect.

## Extraction {#extraction}

Written from `prompts/extraction.txt` (version b44367f8), `prompts/tte/fields_brief.txt` (version a3f7f141) and `prompts/tte/notability.txt` (version 5ee3450f).

For each name the AI found:

- **OK:** a named Singapore entity the article says something new about.
- **Wrong:** not in the article, not Singaporean, only mentioned or quoted,
  or not a real name ("the ministry").
- **Not worth a record:** real and new, but too minor for TTE.

For an OK name, tap any detail that is wrong: not in the article, in the
wrong field (a post like "CEO" as Occupation), a wrong date, or not in
English.

Then select anyone it missed in the article and add them, or press
**Nothing missed**.

## Matching {#matching}

Written from `prompts/resolution.txt` (version 87536818).

- **Same:** the name fits and something else agrees (job, employer,
  field), with nothing contradicting it.
- **Different:** the details point to someone else. A matching name alone
  is not enough.
- **Can't tell:** not enough to decide either way.

Judge who it is, not whether the record needs updating. A Chinese name the
AI wrote in English can be wrong: go by the details.

## For every sheet {#general}

Not sure? Make your best call. Work on your own: do not compare answers
until everyone has finished.
