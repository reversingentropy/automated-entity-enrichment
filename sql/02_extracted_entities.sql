-- Job 2 output: one row per entity found in an article.

create table if not exists public.extracted_entities (
  id             bigint generated always as identity primary key,
  article_id     bigint not null references public.article(id) on delete cascade,
  entity_name    text not null,
  -- English / romanised form when entity_name is not English. Institutional
  -- names translate consistently and match far better than the source form.
  entity_name_en text,
  entity_type    text not null check (entity_type in (
                   'PERSON','ORGANISATION','FACILITY','LOCATION',
                   'EVENT','AWARD','PROGRAMME','LEGAL_ACT')),
  summary        text,
  evidence       text,
  fields         jsonb not null default '{}'::jsonb,
  confidence     text,
  created_at     timestamptz not null default now()
);

create index if not exists extracted_entities_article on public.extracted_entities (article_id);
create index if not exists extracted_entities_type    on public.extracted_entities (entity_type);

grant select, insert, update, delete on public.extracted_entities to service_role;
