-- Just enough of Supabase for the desk's SQL to run in a plain Postgres (tests/test_desk_queue.py):
-- the roles, auth.uid() and auth.jwt() read from the request settings as Supabase's do, auth.users,
-- the storage bucket tables, and the pipeline tables sql/11 turns row security on for.
create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;
grant usage on schema public to anon, authenticated, service_role;
create schema auth;
grant usage on schema auth to anon, authenticated, service_role;
create table auth.users (id uuid primary key, email text);
create function auth.jwt() returns jsonb language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claims', true), ''), '{}')::jsonb $$;
create function auth.uid() returns uuid language sql stable as $$
  select nullif(auth.jwt() ->> 'sub', '')::uuid $$;
grant execute on function auth.jwt(), auth.uid() to anon, authenticated, service_role;
create schema storage;
create table storage.buckets (id text primary key, name text, public boolean);
create table storage.objects (id bigserial primary key, bucket_id text, name text);
create table public.article (id bigint primary key);
create table public.extracted_entities (id bigint primary key);
create table public.entities (uid text primary key);
create table public.tte_imports (id bigint primary key);
create table public.candidate_matches (id bigint primary key);
create table public.rss_feeds (id bigint primary key);
