-- Berita Harian (Malay) and Tamil Murasu (Tamil) join the three feeds. Run after 17_article_private.sql. Re-runnable.
--
-- Neither paper publishes a feed for Singapore alone, only one for every section:
-- /rss.xml, the latest 50 articles, which on 18 Oct 2026 went back a day and a half
-- (Berita Harian) and most of a day (Tamil Murasu); Job 0 reads it every two hours.
-- `keep` is the pattern an article's link must contain to be stored
-- (src/job0_ingest/parse.py): Berita Harian's singapura section, and Tamil Murasu's
-- singapore and community sections, the second being Singapore's Indian community.
-- The three feeds before are Singapore-only already and have none, so they keep
-- everything, as they did. On 16-18 Oct 2026 that was about 40 articles a day
-- between the two, on top of about 160 from the three.
--
-- Nothing else needs to change for them: the desk already files these links under
-- Malay and Tamil (card_langs, 15_desk_queue.sql), and the extraction prompt already
-- writes English values and translates quotes for both languages.
alter table public.rss_feeds add column if not exists keep text;

insert into public.rss_feeds (id, source, url, category, keep)
select (select coalesce(max(id), 0) from public.rss_feeds) + row_number() over (order by v.ord),
       v.source, v.url, 'Singapore', v.keep
from (values (1, 'Berita Harian', 'https://www.beritaharian.sg/rss.xml',    '\.sg/singapura/'),
             (2, 'Tamil Murasu',  'https://www.tamilmurasu.com.sg/rss.xml', '\.sg/(singapore|community)/')
     ) v(ord, source, url, keep)
where not exists (select 1 from public.rss_feeds f where f.url = v.url);
