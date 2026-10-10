-- Job 1 + Job 2 columns on the existing `article` table.
-- `update_article_relevance_batch(rows jsonb)` already exists in the project
-- and is what Job 1 writes through.

alter table public.article add column if not exists relevant             boolean;
alter table public.article add column if not exists reason               text;
alter table public.article add column if not exists processed_extraction boolean not null default false;

-- Scraped article body. Lets extraction be re-run offline after a prompt
-- change, and survives the source URL rotting. ~5 KB per relevant article.
alter table public.article add column if not exists text text;

-- Job queues.
create index if not exists article_unscored
  on public.article (id) where relevant is null;
create index if not exists article_unextracted
  on public.article (id) where relevant = true and processed_extraction = false;
