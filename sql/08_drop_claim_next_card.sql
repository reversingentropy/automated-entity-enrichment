-- A card-claiming function from the Streamlit prototype's review app.
-- Referenced by nothing in this repository or its history; the review app
-- that replaced it keeps its state in the browser and the artifact database.
--
-- Dropped by looking its signature up rather than guessing it: `drop function
-- if exists claim_next_card()` is a no-op when the real function takes
-- different arguments, and says nothing.
do $$
declare
  f record;
begin
  for f in
    select oid::regprocedure as sig
    from pg_proc
    where proname = 'claim_next_card'
      and pronamespace = 'public'::regnamespace
  loop
    execute 'drop function ' || f.sig;
    raise notice 'dropped %', f.sig;
  end loop;
end $$;

-- PostgREST caches the schema; tell it to look again.
notify pgrst, 'reload schema';
