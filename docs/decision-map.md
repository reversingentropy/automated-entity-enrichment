# Decision map: every decision from the news to the file (draft, for correction)

Purpose: lay out each point where something is decided, its possible answers, and who or what answers it. If every decision is a label,
the whole flow can be replayed with the human removed and compared with what people decide. Only the writing is free text.

| # | Stage | Decision | Options | Answered by | Free text kept by Gemini |
|---|---|---|---|---|---|
| 1 | Relevance | Does this article change a record? | relevant / not | jev (headline and description) | not required |
| 2 | Extraction | Which entities, and what kind? | entity type (8); subject / mentioned | Gemini | entity names and English names, summary, evidence sentence and translation |
| 2b | Extraction | What does the article say about each? | field names (46 in use); controlled values (Occupation, Title, Nationality, Feature Type) | Gemini | field values, Description prose (22% of values) |
| 3 | Retrieval | Which records might it be? | up to 5 candidates | SQL, no model | none |
| 4 | Identity | Which record is it? | record 1 to 5 / none / unsure | jev | none |
| 4b | Identity | Search again? Duplicates? | search again / duplicate | Gemini (jev cannot invent a search term) | search term |
| 5 | New record | Create a record? Three gates, not "notability" (from your decisions on 2026-10-06): (a) Singapore-centric? (b) is its parent organisation already the record (a brand or publication)? (c) was the article relevant to begin with (not a legal or regulatory story)? | create / not worth | (a) jev (tested: Tokyo 2020 scores 0.16), (b) code from the Parent Organisation field (not tested), (c) upstream relevance (jev scored the Sun Quan article 0.19) | none |
| 6 | Changes | Which fields change, and how? | add / replace / link / rewrite / skip | code from the field's kind (matches Gemini 96%) | the new value |
| 7 | Description | Is the new fact lasting? Within 5 sentences? | yes / no / hold | jev for "lasting", code for the sentence count | the new sentence |
| 8 | Check | Does the article's quote back the change? | supports / says nothing / contradicts | jev | none |
| 9 | Review | Same record? Accept each change? | same / new record / not worth a record / keep for review; accept / leave out / edit wording / no change; reject reason: homonym / absent / unsure | a person today; jev or rules in the replay | optional note, edited wording |

## Rules used in the replay (`scripts/jev_flow.py`)
- Identity is settled alone only when jev picks the same record Gemini chose (or "none") at 90% or more in both option orders.
- A new record is always handed to a person (row 5 has no rule).
- Each change, in order: broken text -> person; quote contradicts (>= 0.5) -> leave out; quote says nothing or missing -> person; description past 5 sentences -> person; description a passing detail -> leave out at 0.9, person at 0.7.

## Please correct
1. **New records (row 5).** What makes an entity worth a record? This is the biggest block.
2. **Hold or leave out?** When a gate fails, should the flow leave the change out or ask a person?
3. **Never automate.** Which cases should always reach a person whatever the models say (for example deaths, living people)?
4. **Anything missing** from the options above, or a free-text part that is really a label.
