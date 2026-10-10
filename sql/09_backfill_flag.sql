-- Keep the historical backfill out of the nightly queues.
--
-- The archive collected from the outlets (about 295,000 articles back to
-- 2015) is extracted and resolved on an internal model, by export and
-- import, because Gemini's free tier cannot. Its rows live in the same
-- tables as the nightly pipeline's -- extracted_entities.article_id is a
-- NOT NULL foreign key into article, so they have to -- but Jobs 1, 2 and 3
-- must never pick them up: 31,000 entities on a 500-request-a-day quota is
-- two months of nightly runs doing nothing else.

alter table public.article            add column if not exists backfill boolean not null default false;
alter table public.extracted_entities add column if not exists backfill boolean not null default false;

create index if not exists article_backfill            on public.article (backfill) where backfill;
create index if not exists extracted_entities_backfill on public.extracted_entities (backfill) where backfill;
