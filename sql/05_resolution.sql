-- Job 3 (entity resolution).

-- Queue column, same pattern as article.processed_extraction: nothing is
-- marked resolved until the write succeeds, so a failed run is simply retried.
alter table public.extracted_entities
  add column if not exists resolved boolean not null default false;

create index if not exists extracted_entities_unresolved
  on public.extracted_entities (id) where resolved = false;

-- Resolution decisions. CREATE_NEW is the implicit default and is never
-- written by the model -- an extracted entity with no row here, once resolved,
-- is understood to be new.
create table if not exists public.candidate_matches (
  id                bigint generated always as identity primary key,
  extracted_id      bigint not null references public.extracted_entities(id) on delete cascade,
  resolution_action text not null check (resolution_action in (
                      'MATCH_AND_UPDATE','RE_QUERY_REQUIRED',
                      'FLAG_DB_DUPLICATE','FLAG_AMBIGUOUS')),
  matched_uid       text references public.entities(uid),
  confidence        text,
  reasoning         text,
  field_updates     jsonb not null default '[]'::jsonb,
  inverse_updates   jsonb not null default '[]'::jsonb,
  re_query_term     text,
  duplicate_uids    jsonb not null default '[]'::jsonb,
  -- What retrieval offered, kept for auditing a decision after the fact.
  candidates        jsonb not null default '[]'::jsonb,
  applied           boolean not null default false,
  created_at        timestamptz not null default now()
);

create index if not exists candidate_matches_extracted on public.candidate_matches (extracted_id);
create index if not exists candidate_matches_pending
  on public.candidate_matches (id) where applied = false;

grant select, insert, update, delete on public.candidate_matches to service_role;
