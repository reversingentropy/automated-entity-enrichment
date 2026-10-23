-- Accounts people make themselves, on the desk's sign-in screen, wait until an admin approves them.
-- Run after 19_evaluation.sql. Re-runnable.
--
-- Before this, every account was made by hand (`python -m src.export --account`) and its password passed on.
-- Now a colleague types their name, email and a password of their own, and the account is made at once; but
-- it can read and save nothing until an admin presses Approve on the Team page. Supabase's free email reaches
-- only the project's own team, so no confirmation link can prove who owns an address: the admin's check with
-- the person is that proof.
--
-- Waiting is decided here, not by the page: an account made after this file first ran is waiting until its
-- app_metadata says "approved" (or "test"). Accounts from before are approved as they are. app_metadata is
-- written only by the secret key and by these functions; a user cannot set it. The mark is read from the
-- accounts table on each call rather than from the sign-in token, so an approval counts at once.
-- (Not a trigger on auth.users: Supabase writes that row again during sign-up, from its own copy, and
-- would wipe a mark a trigger had added.)
--
-- An admin is an account whose app_metadata carries "admin": true (`python -m src.export --mark-admin EMAIL`).
--
-- Then, in the dashboard, Authentication > Sign In / Providers: turn "Allow new users to sign up" on, and
-- under Email turn "Confirm email" off (no confirmation email could reach a colleague).

create table if not exists public.account_gate (
  id    int primary key default 1 check (id = 1),
  since timestamptz not null default now()
);
insert into public.account_gate default values on conflict do nothing;
alter table public.account_gate enable row level security;
revoke all on public.account_gate from anon, authenticated;
grant select on public.account_gate to service_role;

-- Whether an account is waiting: made after the gate, and neither approved nor a test account.
create or replace function public.account_waiting(u auth.users)
returns boolean
language sql stable security definer set search_path = public as $$
  select u.created_at > (select since from public.account_gate)
         and coalesce(u.raw_app_meta_data ->> 'approved', '') <> 'true'
         and coalesce(u.raw_app_meta_data ->> 'test', '') <> 'true';
$$;
revoke all on function public.account_waiting(auth.users) from public, anon, authenticated;

-- Whether the signed-in account is waiting. The page asks it once, at sign-in. A sign-in whose account is gone,
-- declined or deleted, counts as waiting too: its token stays valid for up to an hour after, and the first version
-- of this let such a token read the deck (a declined test account, 23 Oct 2026).
create or replace function public.is_waiting()
returns boolean
language sql stable security definer set search_path = public as $$
  select auth.uid() is not null
         and coalesce((select public.account_waiting(u) from auth.users u where u.id = auth.uid()), true);
$$;
grant execute on function public.is_waiting() to anon, authenticated, service_role;

-- A waiting account writes nothing: every write already refuses a test account, so it is refused as one.
create or replace function public.is_test_account()
returns boolean
language sql
stable
as $$
  select coalesce((auth.jwt() -> 'app_metadata' ->> 'test')::boolean, false) or public.is_waiting();
$$;
grant execute on function public.is_test_account() to anon, authenticated, service_role;

-- And reads nothing: a restrictive policy is added to whatever each table already allows.
do $$
declare t text;
begin
  foreach t in array array['deck', 'reviews', 'claims', 'eval_items', 'eval_labels', 'eval_holds', 'eval_results'] loop
    if to_regclass('public.' || t) is not null then
      execute format('drop policy if exists "waiting accounts reach nothing" on public.%I', t);
      execute format('create policy "waiting accounts reach nothing" on public.%I as restrictive for all to authenticated '
                     'using ((select not public.is_waiting())) with check ((select not public.is_waiting()))', t);
    end if;
  end loop;
end $$;
drop policy if exists "waiting accounts read no desk file" on storage.objects;
create policy "waiting accounts read no desk file" on storage.objects as restrictive for select to authenticated
  using (bucket_id <> 'desk' or (select not public.is_waiting()));

-- 13_desk_record.sql's function, with the same check (it reads past row security, so the policies above do not
-- reach it). Rerun this file after rerunning that one.
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
    and not public.is_waiting()
    and coalesce(e.fields ->> t.k, '') <> '';
$$;
revoke all on function public.desk_record(text) from public;
grant execute on function public.desk_record(text) to authenticated;

create or replace function public.is_admin()
returns boolean
language sql stable as $$
  select coalesce((auth.jwt() -> 'app_metadata' ->> 'admin')::boolean, false);
$$;
grant execute on function public.is_admin() to anon, authenticated, service_role;

-- waiting_accounts: who is waiting, oldest first, for the admin's Team page. Nobody else is told anything.
create or replace function public.waiting_accounts()
returns jsonb
language sql stable security definer set search_path = public as $$
  select coalesce(jsonb_agg(jsonb_build_object('id', u.id, 'email', u.email,
                                               'name', coalesce(u.raw_user_meta_data ->> 'name', ''),
                                               'made', u.created_at) order by u.created_at), '[]'::jsonb)
  from auth.users u
  where public.is_admin() and public.account_waiting(u);
$$;

-- approve_account: the account can start at once. True if it was waiting.
create or replace function public.approve_account(account uuid)
returns boolean
language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then
    return false;
  end if;
  update auth.users u set raw_app_meta_data = coalesce(u.raw_app_meta_data, '{}'::jsonb) || '{"approved": true}'::jsonb
  where u.id = account and public.account_waiting(u);
  return found;
end $$;

-- decline_account: a waiting account removed, as if never made; the address can sign up again. Only a waiting
-- account: an approved reviewer, their decisions with them, is never removed from the page.
create or replace function public.decline_account(account uuid)
returns boolean
language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then
    return false;
  end if;
  delete from auth.users u where u.id = account and public.account_waiting(u);
  return found;
end $$;

revoke all on function public.waiting_accounts() from public;
revoke all on function public.approve_account(uuid) from public;
revoke all on function public.decline_account(uuid) from public;
grant execute on function public.waiting_accounts() to authenticated;
grant execute on function public.approve_account(uuid) to authenticated;
grant execute on function public.decline_account(uuid) to authenticated;
