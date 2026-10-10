-- Articles that are a story already stored at another address.
-- Run after 13_desk_record.sql. Re-runnable.
--
-- The url is unique, but it is not the story: The Straits Times moves an article
-- between sections, CNA rewrites the headline in its address, Zaobao is on two
-- domains, and the ingest runs twice a day, so it met articles 19312 and 19420
-- (one story) as two. The ingest now stores a copy as already judged
-- (relevant = false, the reason naming the first) and points it here at the first
-- one; scripts/mark_duplicate_articles.py does the same for the copies stored
-- before. A copy is kept, not deleted: the feed lists its url for a day or two,
-- and a deleted row would be inserted again by the next run. Deleting would also
-- cascade to the entities extracted from it.
alter table public.article add column if not exists duplicate_of bigint references public.article(id);

create index if not exists article_duplicate_of
  on public.article (duplicate_of) where duplicate_of is not null;
