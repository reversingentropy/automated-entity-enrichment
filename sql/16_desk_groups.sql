-- The desk's four groups: updating a record and creating one are kept apart.
-- Run after 15_desk_queue.sql. Re-runnable.
--
-- Updating asks "is this the same record, and are these changes right?"; creating
-- asks "is this worth a record?". The reviewers asked for the two not to be mixed,
-- so every new record, whatever its type, is one group, and records already in TTE
-- are grouped by type. Only people and organisations are big enough to be a group
-- of their own: of 100 decisions on existing records over five weeks (8 Sep to
-- 14 Oct), 44 were people, 43 organisations, 5 buildings, and programmes, legal
-- acts, events, awards and places 1 to 3 each, which share "other changes".
--
-- The keys are the page's (GROUPS in prototype/desk.template.html); take_next()
-- and decide() take one of them, or 'all'.

create or replace function public.card_group(type text, is_new boolean) returns text
language sql immutable as $$
  select case when is_new then 'new records'
              when type = 'PERSON' then 'people'
              when type = 'ORGANISATION' then 'organisations'
              else 'other changes' end;
$$;

-- grp was worked out from the type alone. A generated column's expression cannot
-- be changed in place, so it is dropped and added again; Postgres fills it for
-- every row as it is added. No index or policy uses it.
do $$
begin
  if exists (select 1 from information_schema.columns
             where table_schema = 'public' and table_name = 'deck' and column_name = 'grp'
               and coalesce(generation_expression, '') not like '%isNew%') then
    alter table public.deck drop column grp;
  end if;
end $$;
alter table public.deck add column if not exists grp text
  generated always as (public.card_group(type, coalesce((card->>'isNew')::boolean, false))) stored;

drop function if exists public.card_group(text);
grant execute on function public.card_group(text, boolean) to authenticated, service_role;

-- The queue's order (take_next in sql/15): changes to records TTE has before
-- records to create, each newest news first. Built here, after grp is final: an
-- index on the column would go with it when the column is dropped above.
create index if not exists deck_queue_updates_first on public.deck
  ((grp = 'new records'), newest desc nulls last, ord, key) where not settled;
