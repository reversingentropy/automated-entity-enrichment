-- The article and rss_feeds tables are the pipeline's alone. Run after 16_desk_groups.sql. Re-runnable.
--
-- Both existed before this repository's SQL (01_article.sql only adds to article;
-- nothing here creates rss_feeds). The public key baked into the desk's page could
-- read all of article: 18,426 rows on 15 Oct 2026, the scraped text of every
-- article included, though it could not write to it. Row level security was on
-- (11_desk_online.sql), so a policy from before let it through, along with a grant.
-- Nothing outside the pipeline reads either table (the desk reads `deck` and the
-- `desk` bucket), and the jobs use the secret key, which row level security does
-- not apply to. So every policy goes, and the grants with them: the page's key and
-- a signed-in reviewer see nothing.
alter table public.article   enable row level security;
alter table public.rss_feeds enable row level security;

do $$
declare p record;
begin
  for p in select tablename, policyname from pg_policies
           where schemaname = 'public' and tablename in ('article', 'rss_feeds') loop
    execute format('drop policy %I on public.%I', p.policyname, p.tablename);
  end loop;
end $$;

revoke all on public.article, public.rss_feeds from anon, authenticated;
