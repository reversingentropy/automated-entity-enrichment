-- The evaluation's three labelled sheets, labelled on the desk's Evaluation page instead of in Excel.
-- Run after 18_malay_tamil_feeds.sql. Re-runnable.
--
-- The sheets are the ones `python -m src.eval sheets` built (docs/evaluation-method.md): relevance,
-- matching and extraction, drawn from one month of the feed. `python -m src.eval online publish` puts
-- their rows here; `python -m src.eval online pull` writes the labels back out as the returned sheets
-- `python -m src.eval score` has always read, so the scoring is unchanged.
--
-- Only an evaluator can read a row or save a label: an account whose app_metadata carries
-- "evaluator": true, which only the secret key can set (`python -m src.export --mark-evaluator EMAIL`).
-- Reviewers see none of it. The app's own answers are not here at all: they stay in the key files on the
-- PC that scores (data/eval/*-key.json), so a labeller cannot see what they are grading.
--
-- Labellers do not see each other's labels either: nobody can read eval_labels except through the
-- secret key. The page learns only how far along each sheet is, from eval_progress().
--
-- Rows 1 to 50 of each sheet go to every labeller, which is what agreement between them is measured on.
-- The rest are dealt one at a time, as the desk deals records: a row nobody has labelled and nobody
-- else holds, held for an hour (hold_minutes() in 15_desk_queue.sql), so no row is labelled twice.

create or replace function public.is_evaluator()
returns boolean
language sql stable as $$
  select coalesce((auth.jwt() -> 'app_metadata' ->> 'evaluator')::boolean, false);
$$;
grant execute on function public.is_evaluator() to anon, authenticated, service_role;

-- Rows every labeller is given, for agreement (SHARED in src/eval/sheets.py).
create or replace function public.eval_shared() returns int
language sql immutable as $$ select 50 $$;

create table if not exists public.eval_items (
  task text not null check (task in ('relevance', 'matching', 'extraction')),
  item text not null,             -- the sheet's own key: an article's link, a proposal id
  ord int not null,               -- its row on the sheet, which is in random order
  lang text not null,             -- the language it has to be read in, as the desk's langs
  body jsonb not null,            -- what the labeller is shown, and nothing of the app's answer
  primary key (task, item)
);

create table if not exists public.eval_labels (
  task text not null,
  item text not null,
  labeller uuid not null,
  label jsonb not null check (jsonb_typeof(label) = 'object'),
  seconds int,
  at timestamptz not null default now(),
  primary key (task, item, labeller),
  foreign key (task, item) references public.eval_items (task, item) on delete cascade
);

create table if not exists public.eval_holds (
  task text not null,
  item text not null,
  labeller uuid not null,
  held_at timestamptz not null default now(),
  primary key (task, item),
  foreign key (task, item) references public.eval_items (task, item) on delete cascade
);

alter table public.eval_items  enable row level security;
alter table public.eval_labels enable row level security;
alter table public.eval_holds  enable row level security;

do $$
declare p record;
begin
  for p in select tablename, policyname from pg_policies
           where schemaname = 'public' and tablename in ('eval_items', 'eval_labels', 'eval_holds') loop
    execute format('drop policy %I on public.%I', p.policyname, p.tablename);
  end loop;
end $$;

-- Evaluators read the rows to label. Labels and holds have no policy: only the functions below and the
-- secret key reach them.
create policy "evaluators read the rows" on public.eval_items
  for select to authenticated using (public.is_evaluator());

revoke all on public.eval_items, public.eval_labels, public.eval_holds from anon, authenticated;
grant select on public.eval_items to authenticated;
grant all on public.eval_items, public.eval_labels, public.eval_holds to service_role;


-- eval_take: the next row of a sheet for this labeller, in a language they read. First the shared rows,
-- in sheet order, that they have not labelled; then the first row nobody has labelled and nobody else
-- holds, which they then hold. Gives back any other row they held on that sheet. Null when nothing is
-- left for them. A test account is given nothing: the page walks the rows itself and saves nothing.
create or replace function public.eval_take(task text, langs text[] default null)
returns text
language plpgsql security definer set search_path = public as $$
declare
  me uuid := auth.uid();
  k text;
  n int;
  tried text[] := '{}';
begin
  if me is null or not public.is_evaluator() or public.is_test_account() then
    return null;
  end if;
  select i.item into k
  from public.eval_items i
  where i.task = eval_take.task and i.ord <= public.eval_shared()
    and i.lang = any(coalesce(eval_take.langs, array['en', 'zh', 'ms', 'ta']))
    and not exists (select 1 from public.eval_labels l
                    where l.task = i.task and l.item = i.item and l.labeller = me)
  order by i.ord
  limit 1;
  if k is not null then
    return k;           -- everyone labels these, so nobody holds them
  end if;
  delete from public.eval_holds h where h.labeller = me and h.task = eval_take.task;
  loop
    select i.item into k
    from public.eval_items i
    where i.task = eval_take.task and i.ord > public.eval_shared()
      and i.lang = any(coalesce(eval_take.langs, array['en', 'zh', 'ms', 'ta']))
      and not exists (select 1 from public.eval_labels l where l.task = i.task and l.item = i.item)
      and not exists (select 1 from public.eval_holds h
                      where h.task = i.task and h.item = i.item and public.hold_live(h.held_at))
      and not (i.item = any(tried))
    order by i.ord
    limit 1
    for update of i skip locked;
    if k is null then
      return null;
    end if;
    insert into public.eval_holds (task, item, labeller, held_at) values (eval_take.task, k, me, now())
    on conflict on constraint eval_holds_pkey do update set labeller = excluded.labeller, held_at = excluded.held_at
      where not public.hold_live(public.eval_holds.held_at) or public.eval_holds.labeller = excluded.labeller;
    get diagnostics n = row_count;
    if n > 0 then
      return k;
    end if;
    tried := tried || k;
  end loop;
end;
$$;

-- eval_save: keep this labeller's label on a row, or replace their earlier one. A row past the shared
-- ones is refused when a colleague has labelled it or holds it: it was theirs to label.
create or replace function public.eval_save(task text, item text, label jsonb, seconds int default null)
returns boolean
language plpgsql security definer set search_path = public as $$
declare
  me uuid := auth.uid();
  o int;
begin
  if me is null or not public.is_evaluator() or public.is_test_account() or jsonb_typeof(label) <> 'object' then
    return false;
  end if;
  select i.ord into o from public.eval_items i where i.task = eval_save.task and i.item = eval_save.item;
  if o is null then
    return false;
  end if;
  if o > public.eval_shared() and (
       exists (select 1 from public.eval_labels l
               where l.task = eval_save.task and l.item = eval_save.item and l.labeller <> me)
       or exists (select 1 from public.eval_holds h
                  where h.task = eval_save.task and h.item = eval_save.item and h.labeller <> me
                    and public.hold_live(h.held_at))) then
    return false;
  end if;
  insert into public.eval_labels (task, item, labeller, label, seconds, at)
  values (eval_save.task, eval_save.item, me, eval_save.label, eval_save.seconds, now())
  on conflict on constraint eval_labels_pkey do update
    set label = excluded.label, seconds = excluded.seconds, at = excluded.at;
  delete from public.eval_holds h where h.task = eval_save.task and h.item = eval_save.item and h.labeller = me;
  return true;
end;
$$;

-- eval_release: give back the rows this labeller holds, on stopping.
create or replace function public.eval_release()
returns void
language sql security definer set search_path = public as $$
  delete from public.eval_holds where labeller = auth.uid();
$$;

-- eval_progress: how far along each sheet is, per language, for the page. Counts only: never whose label
-- says what. `mine` and `shared_mine` are this labeller's; `labelled` counts rows past the shared ones that
-- anyone has labelled; `held` those a colleague holds now.
create or replace function public.eval_progress()
returns table (task text, lang text, total int, shared int, shared_mine int, mine int, labelled int, held int,
               labellers int)
language sql stable security definer set search_path = public as $$
  select i.task, i.lang,
         count(*)::int,
         count(*) filter (where i.ord <= public.eval_shared())::int,
         count(*) filter (where i.ord <= public.eval_shared() and exists (
           select 1 from public.eval_labels l where l.task = i.task and l.item = i.item and l.labeller = auth.uid()))::int,
         count(*) filter (where exists (
           select 1 from public.eval_labels l where l.task = i.task and l.item = i.item and l.labeller = auth.uid()))::int,
         count(*) filter (where i.ord > public.eval_shared() and exists (
           select 1 from public.eval_labels l where l.task = i.task and l.item = i.item))::int,
         count(*) filter (where exists (
           select 1 from public.eval_holds h where h.task = i.task and h.item = i.item
                                             and h.labeller <> auth.uid() and public.hold_live(h.held_at)))::int,
         (select count(distinct l.labeller) from public.eval_labels l where l.task = i.task)::int
  from public.eval_items i
  where public.is_evaluator()
  group by i.task, i.lang;
$$;

-- The scored report, put here by `python -m src.eval online results` for the page to show. Scoring needs
-- the key files, so it happens on the PC that holds them, never in the page.
create table if not exists public.eval_results (
  id bigserial primary key,
  at timestamptz not null default now(),
  report text not null
);
alter table public.eval_results enable row level security;
drop policy if exists "evaluators read the results" on public.eval_results;
create policy "evaluators read the results" on public.eval_results
  for select to authenticated using (public.is_evaluator());
revoke all on public.eval_results from anon, authenticated;
grant select on public.eval_results to authenticated;
grant all on public.eval_results to service_role;
grant usage, select on sequence public.eval_results_id_seq to service_role;

revoke all on function public.eval_take(text, text[]) from public;
revoke all on function public.eval_save(text, text, jsonb, int) from public;
revoke all on function public.eval_release() from public;
revoke all on function public.eval_progress() from public;
grant execute on function public.eval_take(text, text[]) to authenticated;
grant execute on function public.eval_save(text, text, jsonb, int) to authenticated;
grant execute on function public.eval_release() to authenticated;
grant execute on function public.eval_progress() to authenticated;
