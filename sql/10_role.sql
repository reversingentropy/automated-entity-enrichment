-- Which entity an article is about.
--
-- The first reviewer saw a card for Nanyang Technological University under
-- "Teo Chee Hean receives NTU honorary degree" and called it the wrong
-- focus. The extraction model now says, per entity, whether the article is
-- about it ("subject") or merely names it ("mentioned"); the review deck
-- deals the subject and footnotes the rest. Rows written before this are
-- null, and the deck falls back to the headline for them.

alter table public.extracted_entities
  add column if not exists role text check (role in ('subject', 'mentioned'));
