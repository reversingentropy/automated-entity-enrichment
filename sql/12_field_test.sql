-- What the field test needs that the desk did not record.
-- Run after 11_desk_online.sql. Re-runnable.

-- Which model answered. Each job's model chain falls back to a weaker model
-- when a stronger one's daily allowance is spent, so the same night can mix
-- models; the evaluation has to be able to tell them apart.
alter table public.article            add column if not exists relevance_model  text;
alter table public.extracted_entities add column if not exists extraction_model text;
alter table public.candidate_matches  add column if not exists resolution_model text;

-- The evaluation's two logs, change_log and weekly_log, were here; never used, they were dropped by
-- 21_drop_unused.sql. The evaluation keeps them in its logs spreadsheet (python -m src.eval sheets logs).
