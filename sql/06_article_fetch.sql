-- Fetch outcome, recorded by extraction.
--
-- Until now an article whose page could not be read (paywall, dead link,
-- consent wall) passed relevance on its headline, failed to scrape in Job 2,
-- and was left in Job 2's queue to fail again every night. Nothing counted
-- them and nothing reported them. These columns make the failure a fact in
-- the row rather than a line in a log.

alter table public.article add column if not exists fetch_error    text;
alter table public.article add column if not exists fetch_attempts integer not null default 0;

-- Job 2 gives up on a row after three failed reads, so "relevant but
-- unreadable" is a count on the row rather than a nightly retry.
create index if not exists article_unfetched
  on public.article (id) where text is null and fetch_attempts < 3;
