-- The desk's queue: which record each reviewer is given, for how long, and who may decide it.
-- Run after 14_article_duplicates.sql. Re-runnable. docs/load-balancing.md explains it for the team.
--
-- One shared pile, nothing split between people in advance. A reviewer asks for
-- the next record and the database gives them one: the newest news first, in a
-- language they read, of the type they chose, that nobody else holds and that
-- has something left to decide. They hold that one record, and only that one,
-- until they decide it, stop, or leave it alone for an hour. A fast reviewer
-- takes more, a slow one fewer; someone joining or leaving changes nothing for
-- anyone else, and there is nothing to redistribute, because nothing was ever
-- anyone's but the one record on their screen.
--
-- Before this file the page chose the record and only asked the database to
-- confirm it; a hold never ended; switching the type on the page left one person
-- holding three records; a record once decided never came back, even when new
-- news about it arrived; and a decision could be saved by someone whose record
-- had gone to a colleague. Each is closed here, in the database, so no page,
-- however old or wrong, can undo it.
--
-- Reviewers no longer write `reviews` directly: every decision goes through
-- decide(), which checks the record is theirs. (The first desk's online mode,
-- src/export/desk_template.html, wrote the table directly and no longer can;
-- the second desk is the online desk.)


-- How long a hold lasts without being renewed. The page renews it every three
-- minutes while the reviewer is clicking or typing, so someone working, however
-- slowly, never loses their record; a laptop closed, or a desk left for an hour,
-- lets it lapse and the record goes back to the pile.
create or replace function public.hold_minutes() returns int
language sql immutable as $$ select 60 $$;

-- The languages a record can be read in: one per article, by the outlet, as the
-- page reads them (langOf in prototype/desk.template.html).
create or replace function public.card_langs(card jsonb) returns text[]
language sql immutable as $$
  select coalesce(array_agg(distinct case
           when s->>'link' ~ 'zaobao' then 'zh'
           when s->>'link' ~ 'beritaharian' then 'ms'
           when s->>'link' ~ 'tamilmurasu' then 'ta'
           else 'en' end), '{}')
  from jsonb_array_elements(coalesce(card->'sources', '[]'::jsonb)) s;
$$;

-- The page's four types (GROUPS in the page).
create or replace function public.card_group(type text) returns text
language sql immutable as $$
  select case type when 'PERSON' then 'people' when 'ORGANISATION' then 'organisations'
                   when 'LEGAL_ACT' then 'legal acts' else 'everything else' end;
$$;

-- The date of a record's newest article: the queue's order, newest first.
create or replace function public.card_newest(card jsonb) returns text
language sql immutable as $$
  select max(s->>'date') from jsonb_array_elements(coalesce(card->'sources', '[]'::jsonb)) s;
$$;

-- Whether a record has something left for this reviewer to decide: a proposal
-- nobody has decided (a record decided before that has new news since), or one
-- a colleague kept for review that this reviewer has not kept themselves. A
-- record kept for review goes to a second pair of eyes, never back to the first.
create or replace function public.open_for(card jsonb, who uuid) returns boolean
language sql stable set search_path = public as $$
  select exists (
    select 1
    from jsonb_array_elements_text(coalesce(card->'pids', '[]'::jsonb)) p(pid)
    left join public.reviews r on r.pid = p.pid::bigint
    where r.pid is null
       or (r.verdict = 'unsure' and r.reviewer <> who
           and not coalesce(r.decision->'kept_by', '[]'::jsonb) ? who::text)
  );
$$;

-- What the queue sorts and filters on, kept on each row by the database itself
-- (the nightly publish writes key, type, entity and card as before). Worked out
-- from the card's JSON on every request instead, taking the next record from
-- 10,000 took up to 5 seconds (measured, Postgres 16).
alter table public.deck add column if not exists newest text generated always as (public.card_newest(card)) stored;
alter table public.deck add column if not exists langs text[] generated always as (public.card_langs(card)) stored;
alter table public.deck add column if not exists grp text generated always as (public.card_group(type)) stored;
alter table public.deck add column if not exists ord int generated always as ((card->>'i')::int) stored;

-- settled: every proposal on the record has a final decision (not "unsure").
-- Decided records stay in the deck for good, so the sheets can reopen them, and
-- in a year they will far outnumber the open ones; the queue's index leaves them
-- out. With the 9,500 newest of 10,000 records decided, taking the next record
-- walked past all of them and took 5.5 seconds; indexed on the open ones only,
-- 1 to 7 ms. Kept right by the database: a decision saved, changed or removed
-- settles its record again, and the nightly publish changing a card (a new
-- proposal from new news) unsettles it.
alter table public.deck add column if not exists settled boolean not null default false;

create or replace function public.card_settled(card jsonb) returns boolean
language sql stable as $$
  select not exists (
    select 1 from jsonb_array_elements_text(coalesce(card->'pids', '[]'::jsonb)) p(pid)
    where not exists (select 1 from public.reviews r where r.pid = p.pid::bigint and r.verdict <> 'unsure'));
$$;

create or replace function public.deck_settle_row() returns trigger
language plpgsql as $$
begin
  new.settled := public.card_settled(new.card);
  return new;
end;
$$;
drop trigger if exists deck_settle on public.deck;
create trigger deck_settle before insert or update of card on public.deck
  for each row execute function public.deck_settle_row();

create or replace function public.reviews_settle() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  update public.deck d set settled = public.card_settled(d.card)
  where d.key in (coalesce(new.card_key, old.card_key), coalesce(old.card_key, new.card_key));
  return null;
end;
$$;
drop trigger if exists reviews_settle on public.reviews;
create trigger reviews_settle after insert or update or delete on public.reviews
  for each row execute function public.reviews_settle();

update public.deck d set settled = public.card_settled(d.card) where d.settled is distinct from public.card_settled(d.card);
drop index if exists public.deck_queue;
create index if not exists deck_queue_open on public.deck (newest desc nulls last, ord, key) where not settled;

-- A hold that has not been renewed within the hour has lapsed.
create or replace function public.hold_live(claimed_at timestamptz) returns boolean
language sql stable as $$
  select claimed_at > now() - make_interval(mins => public.hold_minutes());
$$;


-- take_next: give back the record this reviewer holds and give them the next one.
-- One statement decides who gets a record: the candidate rows are locked as they
-- are read (FOR UPDATE SKIP LOCKED), so two reviewers asking at the same instant
-- are handed two different records, never the same one, and the hold itself is
-- a row keyed by the record, which can have only one holder. Returns the
-- record's key, or null when nothing is left for them.
create or replace function public.take_next(langs text[] default null, grp text default 'all')
returns text
language plpgsql security definer set search_path = public as $$
declare
  me uuid := auth.uid();
  k text;
  n int;
  tried text[] := '{}';
begin
  if me is null or public.is_test_account() then
    return null;
  end if;
  -- One record at a time: however fast someone clicks, they hold at most one.
  delete from public.claims where reviewer = me;
  loop
    -- One row per look, LIMIT 1: a loop over the whole query would read, and
    -- lock, ten rows at a time, and with twelve reviewers asking at once the
    -- first three locked the pile between them and nine were given nothing.
    -- Walked in news order down the index, it stops at the first record that
    -- fits, past only records still open (the index leaves settled ones out).
    -- The open check is open_for() written out, so the planner can use it.
    select d.key into k
    from public.deck d
    where (take_next.grp is null or take_next.grp = 'all' or d.grp = take_next.grp)
      and not d.settled
      and d.langs && coalesce(take_next.langs, array['en', 'zh', 'ms', 'ta'])
      -- something left for me: a proposal with no decision that closes it for me
      -- (a final one, or my own, or one I kept for review), each a lookup by pid
      and exists (select 1
                  from jsonb_array_elements_text(coalesce(d.card->'pids', '[]'::jsonb)) p(pid)
                  where not exists (select 1 from public.reviews r
                                    where r.pid = p.pid::bigint
                                      and (r.verdict <> 'unsure' or r.reviewer = me
                                           or coalesce(r.decision->'kept_by', '[]'::jsonb) ? me::text)))
      and not (d.key = any(tried))
      and not exists (select 1 from public.claims c
                      where c.card_key = d.key and public.hold_live(c.claimed_at))
    order by d.newest desc nulls last, d.ord, d.key
    limit 1
    for update of d skip locked;
    if k is null then
      return null;
    end if;
    insert into public.claims (card_key, reviewer, claimed_at) values (k, me, now())
    on conflict (card_key) do update set reviewer = excluded.reviewer, claimed_at = excluded.claimed_at
      where not public.hold_live(public.claims.claimed_at) or public.claims.reviewer = excluded.reviewer;
    get diagnostics n = row_count;
    if n > 0 then
      return k;
    end if;
    tried := tried || k;
  end loop;
end;
$$;

-- claim_card: take one named record, to come back to it or to change a decision
-- on it. Allowed when nobody else holds it (or their hold has lapsed) and it
-- has something left for this reviewer to decide, or this reviewer decided it
-- and wants to change that. Gives back any other record they hold.
create or replace function public.claim_card(key text)
returns boolean
language plpgsql security definer set search_path = public as $$
declare
  me uuid := auth.uid();
begin
  if me is null or public.is_test_account() then
    return false;
  end if;
  if not exists (
    select 1 from public.deck d
    where d.key = claim_card.key
      and (public.open_for(d.card, me)
           or exists (select 1 from public.reviews r where r.card_key = d.key and r.reviewer = me))
  ) then
    return false;
  end if;
  delete from public.claims where reviewer = me and card_key <> claim_card.key;
  insert into public.claims (card_key, reviewer, claimed_at) values (claim_card.key, me, now())
  on conflict (card_key) do update set reviewer = excluded.reviewer, claimed_at = excluded.claimed_at
    where not public.hold_live(public.claims.claimed_at) or public.claims.reviewer = excluded.reviewer;
  return exists (select 1 from public.claims c where c.card_key = claim_card.key and c.reviewer = me);
end;
$$;

-- renew_card: the page says the reviewer is still working. False if the record
-- is no longer theirs (their hold lapsed and a colleague took it).
create or replace function public.renew_card(key text)
returns boolean
language plpgsql security definer set search_path = public as $$
begin
  update public.claims set claimed_at = now() where card_key = renew_card.key and reviewer = auth.uid();
  return found;
end;
$$;

-- release_card (unchanged): give a record back without deciding it.
create or replace function public.release_card(key text)
returns void
language sql security definer set search_path = public as $$
  delete from public.claims where card_key = release_card.key and reviewer = auth.uid();
$$;


-- decide: save this reviewer's decision on the record they hold, give the record
-- back, and, when `langs` is given, hand them the next one, all in one step.
-- `rows` is one entry per proposal: {"pid": 123, "verdict": "approve", "decision": {...}}.
-- Refused when the record is not theirs: someone whose hold lapsed and went to a
-- colleague cannot save over the colleague's work. On a proposal, a reviewer may
-- write a new decision, change their own (until it is marked done in TTE), or
-- take over one a colleague kept for review; never replace a colleague's
-- decision. `kept_by` in the decision lists everyone who kept it for review.
create or replace function public.decide(key text, rows jsonb, langs text[] default null, grp text default 'all')
returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  me uuid := auth.uid();
  v_card jsonb;
  r jsonb;
  v_pid bigint;
  v_verdict text;
  saved int := 0;
  n int;
  refused jsonb := '[]'::jsonb;
  nxt text;
begin
  if me is null or public.is_test_account() then
    return jsonb_build_object('saved', 0, 'reason', 'not allowed');
  end if;
  if not exists (select 1 from public.claims c where c.card_key = decide.key and c.reviewer = me) then
    return jsonb_build_object('saved', 0, 'reason', 'not held');
  end if;
  select d.card into v_card from public.deck d where d.key = decide.key;
  for r in select * from jsonb_array_elements(coalesce(rows, '[]'::jsonb)) loop
    v_pid := (r->>'pid')::bigint;
    v_verdict := r->>'verdict';
    -- only the record's own proposals
    if v_card is null or not (v_card->'pids') @> to_jsonb(v_pid) or v_verdict is null or v_verdict not in ('approve', 'reject', 'unsure') then
      refused := refused || to_jsonb(v_pid);
      continue;
    end if;
    insert into public.reviews (pid, card_key, reviewer, verdict, decision, at)
    values (v_pid, decide.key, me, v_verdict,
            coalesce(r->'decision', '{}'::jsonb)
              || jsonb_build_object('kept_by', case when v_verdict = 'unsure' then jsonb_build_array(me::text) else '[]'::jsonb end),
            now())
    on conflict (pid) do update
      set reviewer = excluded.reviewer, verdict = excluded.verdict, at = excluded.at,
          decision = excluded.decision || jsonb_build_object('kept_by',
            coalesce(public.reviews.decision->'kept_by', '[]'::jsonb)
            || case when excluded.verdict = 'unsure'
                     and not coalesce(public.reviews.decision->'kept_by', '[]'::jsonb) ? me::text
                    then jsonb_build_array(me::text) else '[]'::jsonb end)
      where (public.reviews.reviewer = me
             and not coalesce((public.reviews.decision->>'done')::boolean, false))
         or (public.reviews.verdict = 'unsure'
             and not coalesce(public.reviews.decision->'kept_by', '[]'::jsonb) ? me::text);
    get diagnostics n = row_count;
    if n > 0 then
      saved := saved + 1;
    else
      refused := refused || to_jsonb(v_pid);
    end if;
  end loop;
  delete from public.claims c where c.card_key = decide.key and c.reviewer = me;
  if langs is not null then
    nxt := public.take_next(langs, grp);
  end if;
  return jsonb_build_object('saved', saved, 'refused', refused, 'next', nxt);
end;
$$;

-- mark_done: the reviewer has made their approved changes in TTE. After this
-- their decision is fixed: a correction is a new edit in TTE, not an undo here.
create or replace function public.mark_done(pids bigint[], done boolean)
returns int
language plpgsql security definer set search_path = public as $$
declare
  n int;
begin
  if auth.uid() is null or public.is_test_account() then
    return 0;
  end if;
  update public.reviews r set decision = r.decision || jsonb_build_object('done', mark_done.done)
  where r.pid = any(mark_done.pids) and r.reviewer = auth.uid();
  get diagnostics n = row_count;
  return n;
end;
$$;


-- Decisions are written only through decide() and mark_done(): no direct writes.
drop policy if exists "reviewers write their own" on public.reviews;
drop policy if exists "reviewers change their own" on public.reviews;
revoke insert, update, delete on public.reviews from authenticated;

revoke all on function public.take_next(text[], text) from public;
revoke all on function public.claim_card(text) from public;
revoke all on function public.renew_card(text) from public;
revoke all on function public.release_card(text) from public;
revoke all on function public.decide(text, jsonb, text[], text) from public;
revoke all on function public.mark_done(bigint[], boolean) from public;
grant execute on function public.take_next(text[], text) to authenticated;
grant execute on function public.claim_card(text) to authenticated;
grant execute on function public.renew_card(text) to authenticated;
grant execute on function public.release_card(text) to authenticated;
grant execute on function public.decide(text, jsonb, text[], text) to authenticated;
grant execute on function public.mark_done(bigint[], boolean) to authenticated;
grant execute on function public.hold_minutes(), public.card_langs(jsonb), public.card_group(text),
  public.card_newest(jsonb), public.open_for(jsonb, uuid), public.hold_live(timestamptz),
  public.card_settled(jsonb) to authenticated, service_role;
