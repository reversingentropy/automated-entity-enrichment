-- Trigram retrieval plus canonical resolution.
--
-- Canonical resolution happens at load time, not query time: the loader walks
-- Use and the *toENG links once and stores the result in entities.canonical_uid.
-- That is safe because those links never cross authority-file boundaries, so a
-- partial import still resolves correctly. It removes the entity_links table
-- (83,754 rows, 63% of which nothing ever queried) and reduces this function
-- from three CTEs to a single join.
--
-- The floor defaults to 0.30 (pg_trgm's own default) deliberately. Retrieval's
-- job is to get the correct candidate INTO the set; the resolution prompt is
-- the precision filter and is instructed to omit rather than match a
-- near-miss. Measured over 146 extracted entities, raising it from 0.30 to
-- 0.60 dropped the hit rate from 80% to 43%.

-- Drop the earlier three-argument signature first. `create or replace` with a
-- new parameter creates an overload rather than replacing, and PostgREST then
-- refuses to choose between them.
drop function if exists public.match_entities(text, int, text);

create or replace function public.match_entities(
  query_name     text,
  match_count    int   default 5,
  want_type      text  default null,
  min_similarity real  default 0.30
)
returns table (
  matched_uid text, matched_name text, matched_language text, similarity real,
  canonical_uid text, canonical_name text, canonical_type text,
  canonical_language text, canonical_fields jsonb
)
language sql stable
as $$
  with hits as (
    select e.uid, e.name, e.language, e.canonical_uid,
           similarity(e.name, query_name) as sim
    from public.entities e
    where e.is_active
      and (want_type is null or e.entity_type = want_type)
      and e.name % query_name
      and similarity(e.name, query_name) >= min_similarity
    order by similarity(e.name, query_name) desc
    limit match_count
  )
  select h.uid, h.name, h.language, h.sim,
         c.uid, c.name, c.entity_type, c.language, c.fields
  from hits h
  join public.entities c on c.uid = coalesce(h.canonical_uid, h.uid)
  order by h.sim desc, c.name;
$$;

grant execute on function public.match_entities(text,int,text,real) to service_role;
