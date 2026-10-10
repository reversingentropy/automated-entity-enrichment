-- TTE authority reference data, loaded by `python -m src.load_tte`.
-- Requires the pg_trgm extension (Database -> Extensions -> pg_trgm).

create table if not exists public.entities (
  uid         text primary key,            -- TTE Key UID, 1:1 with name, stable
  name        text not null,
  vocabulary  text not null,               -- _Organisations, _Organisations_CN, ...
  entity_type text not null,
  language    text not null default 'en',  -- en / zh / ms / ta
  -- The record that receives updates. Resolved by the loader by walking Use
  -- and the *toENG links; equals uid for the ~40% already canonical. Replaces
  -- a links table whose other 63% of rows nothing queried.
  canonical_uid text references public.entities(uid),
  fields      jsonb not null default '{}'::jsonb,
  is_active   boolean not null default true,
  first_seen  timestamptz not null default now(),
  last_seen   timestamptz not null default now()
);

-- Ingestion ledger. The checksum lets a corrected re-upload under the same
-- filename be detected rather than skipped as already-seen.
create table if not exists public.tte_imports (
  filename    text primary key,
  entity_type text not null,
  snapshot    date not null,
  checksum    text not null,
  rows_loaded integer not null,
  loaded_at   timestamptz not null default now()
);

create index if not exists entities_name_trgm on public.entities using gin (name gin_trgm_ops);
create index if not exists entities_canonical on public.entities (canonical_uid);

grant select, insert, update, delete
  on public.entities, public.tte_imports to service_role;
