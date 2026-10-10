# Gotchas

Each of these cost at least an evening.

- Use the `sb_secret_` Supabase key. The publishable key reads fine and fails
  only on write.
- `create table if not exists` silently skips a table that already exists, so a
  corrected column definition will not apply; use `alter table`.
- Supabase may not grant privileges on new tables; grant to `service_role`
  explicitly.
- `create or replace function` with a changed parameter list creates an
  *overload*, not a replacement, and PostgREST then refuses to call either.
  Drop the old signature explicitly.
- A PostgREST upsert is `INSERT ... ON CONFLICT`, so a partial row is rejected
  against NOT NULL columns rather than treated as an update. Send whole rows.
- Environment secrets need `environment:` in the workflow.
- **GitHub Actions does not read `.env`.** Anything the scheduled runs need
  must be in the workflow's `env:` block or a code default; a local override
  changes nothing about CI. This silently ran the nightly jobs on models with
  a 20/day cap while local runs used the 500/day one.
- Scheduled workflows fire hours late under load, observed 3 to 5 hours past
  the cron time. Ordering between jobs still holds, because each stage's queue
  is a column rather than a schedule.
- Extraction is non-deterministic; re-running an article yields slightly
  different entities. Re-runs replace rather than accumulate.
- The guidelines and the data disagree on one field name: the document writes
  `Affiliations (groupName)`, TTE stores `Affiliations(groupName)`. The data
  wins: the stored string is what an update has to match.
- A longer prompt is not a better one. Injecting all 34 kB of field rules made
  the model skim them, use short field names anyway, and extract one entity
  where it had found five.
- Never patch JavaScript through an unquoted bash heredoc: the shell expands
  `${...}` inside template literals, and a syntax error early in a script means
  the page renders nothing at all.
- `Node.append()` returns `undefined`, so chaining another `.append()` off it
  throws. That, and a variable shadowed into its temporal dead zone, each left
  the review page blank. Both were found by running the script under a DOM
  shim; neither was visible by reading it.
- A global keyboard shortcut must stand down while the caret is in a field.
  The review app exempted `TEXTAREA` but not `INPUT`, so typing an "s" into
  the name box skipped a card and re-rendered the screen, erasing what had
  been typed. Check `isContentEditable` and `INPUT`/`SELECT` too.
- Supabase's free tier closes an HTTP/2 connection after 20,000 requests on
  it. A long loop of small calls through one client dies at exactly that
  point; retry per item, and prefer one paged pull plus local work.
- The dashboard CSV importer stops silently at about 10 MB, and a duplicate
  key anywhere in a file aborts the whole file. Split at a few MB and check
  every row against the table first.
- `pkill -f <pattern>` matches the shell that runs it. Kill by pid.
- Extraction is noisy enough that a single run proves nothing: the same article
  and prompt produced between one and four entities across repeated runs. Any
  comparison of prompt versions needs several runs of each.
- The resolution prompt's contract is that an entity the model leaves out of
  its answer is new, and `build_rows` writes it CREATE_NEW so the decision is
  on record. Every CREATE_NEW row in the table is that fallback; none was the
  model saying "new". The card layer must not turn the fallback into an
  assertion: Tommy Koh was dealt as "not in TTE" with Koh, Tommy in the
  candidates at similarity 1. An omission with an exact own-spelling hit is
  built as the identity question (`omitted_exact` in `src/export/cards.py`);
  the row keeps its reasoning, which is the truth of what happened.
