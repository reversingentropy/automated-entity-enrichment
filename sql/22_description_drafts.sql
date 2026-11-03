-- One description addition per record, from every article about it (docs/descriptions.md, src/combine).
-- Written by the combine step after Job 3, with the service role; read by the deck build, which puts each on its
-- card. Reviewers never read the table: the addition reaches them inside the card. Re-runnable.
--
--   key       the card's key and the proposals whose sentences were combined ("uid:18338504|4588,4590"):
--             a new article about the record makes a new key, so it is combined again with the new sentences
--   record    the card's key alone, to find a record's drafts
--   combined  what passed the code checks: add, left_out, disagreements, corrections, with sources as links;
--             and what the checks dropped, with the reason
--   model     the model that wrote it, or "<model> (AI Studio, by hand)"

create table if not exists public.description_drafts (
  key       text primary key,
  record    text not null,
  combined  jsonb not null,
  model     text not null,
  made_at   timestamptz not null default now()
);
create index if not exists description_drafts_record on public.description_drafts (record);

alter table public.description_drafts enable row level security;
revoke all on public.description_drafts from anon, authenticated;
grant all on public.description_drafts to service_role;
