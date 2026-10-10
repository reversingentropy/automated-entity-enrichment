-- The properties of one record, for the review desk.
-- Run after 12_field_test.sql. Re-runnable.
--
-- The search index the page carries holds a name and one identity line per
-- record, so a record a reviewer finds by search arrived with nothing to read.
-- The page now asks for the rest when the record is chosen. It gets the same
-- fields a candidate card carries, in the same order, as key/value pairs.
-- Signed-in reviewers only; the table itself stays closed to them.
create or replace function public.desk_record(record_uid text)
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
  select coalesce(jsonb_agg(jsonb_build_object('key', t.k, 'value', e.fields ->> t.k) order by t.ord), '[]'::jsonb)
  from public.entities e
  cross join lateral unnest(array[
    'Title', 'Occupation', 'Feature Type', 'Affiliations(groupName)', 'Parent Organisation', 'Awards',
    'Nationality', 'Country', 'Street Address', 'Birth Year (yyyy)', 'Death Year (yyyy)', 'Description', 'SN'
  ]) with ordinality as t(k, ord)
  where e.uid = record_uid
    and auth.uid() is not null
    and coalesce(e.fields ->> t.k, '') <> '';
$$;

revoke all on function public.desk_record(text) from public;
grant execute on function public.desk_record(text) to authenticated;
