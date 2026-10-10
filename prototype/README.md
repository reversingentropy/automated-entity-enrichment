# The desk redesign, as a standalone prototype

`desk.template.html` is the whole page. `build.py` fills in the current deck and writes
`data/dist/prototype.html`. It is a separate file from the real desk
(`src/export/desk_template.html`): nothing here reaches the live site.

It is the specification for porting the redesign into the real desk, one slice at a time.
Each behaviour below was agreed by looking at it, and has a check:

| Open `data/dist/prototype.html` with | It checks |
|---|---|
| `#selftest` | every card, every screen, in edit mode and per source: no errors |
| `#flow=shanti` | Shanti Pereira's awards come out as one row with the whole resulting value |
| `#flow=back2` | Back works after choosing a record or a search result |
| `#measure` | how tall each screen is, against a laptop viewport |

Run a check headless with Chrome's `--dump-dom` and read the `<pre id="selftest">` it fills.

## Behaviours to carry into the real desk

- One focal card per question; the news on top, then what TTE has, then what it will have.
- A list field is one question; one article naming two values is two additions, not a disagreement.
- Single-value fields default to Replace; every change has an Add / Replace switch.
- Achievements is prose (3 to 5 sentences, one value): a sentence added to the paragraph, never " | ".
- The sheet has one row per field with the whole resulting value (the real desk's rows can overwrite each other).
- The approved-changes CSV has exactly these columns: `TTE_UUID, Entity, Attribute, Current_Value, Proposed_Value, Article_URL, Person Who Approved, Timestamp`.
  The real desk's `changesCsv()` still writes `Article_Title` and `Article_Summary` and no timestamp: change it when porting.
- Search covers every record type; a same-name record of another type is offered; the type can be corrected when creating.
- No confirmation message; Back works within a card.
- Language is chosen once; the type to work on is a dropdown on the Review page.
- One reviewer per card (already in the real desk); a held card can be released.

## Builder bugs found by the prototype (fix in `src/export/cards.py`, not in the page)

- `derived_changes` marks every derived fact "APPEND", including single-value fields (267 in the current deck).
- `conflict` fires for one article naming two years of the same award (Shanti Pereira).
- Retrieval searches only the model's entity type (Snow City: an organisation to the model, a building in TTE).
- Prose fields (Achievements) are appended as list items.

## Online (October 2026)

The reviewers chose this desk, so it is now also the online desk: `python -m src.export --site DIR` builds it with
`window.__ONLINE__` set (the first desk stays for `--package`). Online it signs the reviewer in, takes the deck from the
`deck` table, holds each record through `claim_card` before showing it, writes every decision to `reviews` in the
first desk's format (so `src/export/reviews.py` and the reminders read it unchanged) and releases the hold, keeps a
decision it could not send and sends it with the next one, brings a held record back first, and lets a test account
look without holding or saving anything. The team pages use everyone's real decisions and the published pipeline
status instead of the sample. `tests/test_desk2.py` runs every screen and the whole online flow in headless Chromium.
