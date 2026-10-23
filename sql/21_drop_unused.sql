-- Columns and tables that never held anything, dropped (23 Oct 2026, checked against the live project that day).
-- Run after 20_self_signup.sql, and only once the code that stopped using them is pushed: the nightly jobs
-- before that commit still write article.text and candidate_matches.inverse_updates. Re-runnable.
--
--   candidate_matches.inverse_updates  empty in all 4,754 answers: optional in the answer's schema, so Gemini
--                                      left it out every time. Gone from the prompt and the model too.
--   candidate_matches.applied          false in all 4,754 rows; nothing ever set it. Its index goes with it.
--   article.text                       empty in all 19,248 rows: the page is read and never kept, and the
--                                      by-hand path for a paywalled page was never used.
--   access_requests                    one request, from 2 Oct, never handled: the old desk's form, replaced by
--                                      making one's own account (20_self_signup.sql). It was the one table the
--                                      page's key could write to.
--   change_log, weekly_log             no rows: only the old desk had screens for them. The evaluation keeps
--                                      these logs in its spreadsheet (python -m src.eval sheets logs).
--
-- The rows dropped are in data/backups/dropped-tables-20261023.json on the PC that ran the check.

-- Stop, changing nothing, if a function in the project still names one of them: dropping a column does not
-- check function bodies, and the function would only fail when next called.
do $$
declare users text;
begin
  select string_agg(p.oid::regprocedure::text, ', ') into users
  from pg_proc p join pg_namespace n on n.oid = p.pronamespace
  where n.nspname = 'public'
    and (p.prosrc ~* '(inverse_updates|access_requests|change_log|weekly_log)'
         or (p.prosrc ~* 'candidate_matches' and p.prosrc ~* '\mapplied\M')
         or (p.prosrc ~* '\marticle\M' and p.prosrc ~* '(\.text\M|\mtext\s*=|\mtext\s+is\s)'));
  if users is not null then
    raise exception 'Not dropped: still named by %', users;
  end if;
end $$;

alter table public.candidate_matches drop column if exists inverse_updates;
alter table public.candidate_matches drop column if exists applied;
alter table public.article drop column if exists text;
drop table if exists public.access_requests;
drop table if exists public.change_log;
drop table if exists public.weekly_log;
