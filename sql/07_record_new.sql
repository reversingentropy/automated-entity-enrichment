-- Record the decision that an entity is new, instead of implying it.
--
-- The resolution prompt never returns CREATE_NEW: an entity it omits is
-- understood to be new. That made two thirds of all resolutions unrecordable
-- -- 129 of 195 entities had no row, so nobody could review the decision that
-- they were not in TTE, and one of them was Aidha, which is. Job 3 now writes
-- a CREATE_NEW row for every entity the model left out, with the candidates
-- it was offered, and the check constraint has to admit it.

alter table public.candidate_matches
  drop constraint if exists candidate_matches_resolution_action_check;

alter table public.candidate_matches
  add constraint candidate_matches_resolution_action_check
  check (resolution_action in (
    'MATCH_AND_UPDATE', 'CREATE_NEW', 'FLAG_AMBIGUOUS',
    'FLAG_DB_DUPLICATE', 'RE_QUERY_REQUIRED'
  ));

-- The review deck excludes CREATE_NEW by default; this is what a count of
-- them costs.
create index if not exists candidate_matches_action
  on public.candidate_matches (resolution_action);
