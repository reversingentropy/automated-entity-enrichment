"""Job 3: sparse-output handling and candidate assembly."""

from src.job3_resolution.prompt import build_entity_block, render
from src.job3_resolution.update import build_rows
from src.shared.models import ResolutionResponse

ENTITIES = [
    {"id": 1, "entity_name": "Aidha", "entity_name_en": None,
     "entity_type": "ORGANISATION", "summary": "s", "evidence": "e", "fields": {}},
    {"id": 2, "entity_name": "王振胡", "entity_name_en": "Wong, Chin Hu",
     "entity_type": "PERSON", "summary": "s", "evidence": "e", "fields": {}},
    {"id": 3, "entity_name": "MoneyStart", "entity_name_en": None,
     "entity_type": "PROGRAMME", "summary": "s", "evidence": "e", "fields": {}},
]


def _response(*results):
    return ResolutionResponse.model_validate({"resolutions": list(results)})


# What the retriever offered for each entity, keyed by extracted id. A match
# must name one of these.
OFFERED = {1: [{"canonical_uid": "18606295"}], 2: [{"canonical_uid": "18606295"}]}

MATCH = {
    "article_entity_name": "Aidha", "entity_type": "ORGANISATION",
    "resolution_action": "MATCH_AND_UPDATE", "matched_id": "18606295",
    "confidence": "high", "reasoning": "exact match",
    "field_updates": [{"field": "Description", "strategy": "REPLACE", "value": "x"}],
    "inverse_updates": [], "re_query_term": None, "duplicate_db_ids": [],
}


def test_omitted_entities_are_recorded_as_new():
    # Absence from the model's output still means new, but the meaning is now
    # written down: the match first, then a CREATE_NEW row per omitted entity.
    rows = build_rows(_response(MATCH), ENTITIES, OFFERED)
    assert [(r["extracted_id"], r["resolution_action"]) for r in rows] == [
        (1, "MATCH_AND_UPDATE"), (2, "CREATE_NEW"), (3, "CREATE_NEW")]


def test_empty_response_records_every_entity_as_new():
    # The model matched nothing. That used to write nothing; it now writes the
    # decision, once per entity, with the candidates each was offered.
    rows = build_rows(_response(), ENTITIES, OFFERED)
    assert {r["extracted_id"] for r in rows} == {e["id"] for e in ENTITIES}
    assert all(r["resolution_action"] == "CREATE_NEW" for r in rows)
    assert rows[0]["candidates"] == OFFERED.get(rows[0]["extracted_id"], [])


def test_explicit_create_new_is_recorded_like_an_omission():
    # The prompt says never to emit it; don't fail the article if it does.
    created = {**MATCH, "article_entity_name": "MoneyStart",
               "resolution_action": "CREATE_NEW", "matched_id": None}
    rows = build_rows(_response(created), ENTITIES, OFFERED)
    # Whether the model says CREATE_NEW or says nothing, the outcome is the
    # same row: the decision that this entity is new, recorded.
    money = [r for r in rows if r["extracted_id"] == 3]
    assert [r["resolution_action"] for r in money] == ["CREATE_NEW"]


def test_results_can_be_matched_back_by_the_english_name():
    r = {**MATCH, "article_entity_name": "Wong, Chin Hu", "entity_type": "PERSON"}
    rows = build_rows(_response(r), ENTITIES, OFFERED)
    assert rows[0]["extracted_id"] == 2


def test_entities_not_in_this_article_are_dropped():
    # Same protection Job 1 applies to invented ids.
    r = {**MATCH, "article_entity_name": "Some Other Entity"}
    rows = build_rows(_response(r), ENTITIES, OFFERED)
    # The uninvited name is dropped; the article's own entities are still
    # recorded, as CREATE_NEW, rather than left in silence.
    assert {row["extracted_id"] for row in rows} == {e["id"] for e in ENTITIES}
    assert all(row["resolution_action"] == "CREATE_NEW" for row in rows)


def test_flags_are_written_with_their_action_preserved():
    flag = {**MATCH, "resolution_action": "FLAG_AMBIGUOUS", "matched_id": None,
            "confidence": "low", "reasoning": "homonym"}
    rows = build_rows(_response(flag), ENTITIES, OFFERED)
    assert rows[0]["resolution_action"] == "FLAG_AMBIGUOUS"
    assert rows[0]["matched_uid"] is None


def test_candidates_are_stored_for_auditing():
    cands = {1: [{"canonical_uid": "18606295", "similarity": 1.0}]}
    rows = build_rows(_response(MATCH), ENTITIES, cands)
    assert rows[0]["candidates"] == cands[1]


def test_entity_block_carries_both_names_and_its_candidates():
    block = build_entity_block(ENTITIES[1], [{"canonical_uid": "1", "similarity": 0.9}])
    assert block["entity_name"] == "王振胡"
    assert block["entity_name_en"] == "Wong, Chin Hu"
    assert len(block["candidates"]) == 1


def test_render_fills_both_placeholders():
    out = render([build_entity_block(ENTITIES[0], [], "A headline")])
    assert "{article_entities}" not in out
    assert "A headline" in out and "Aidha" in out


def test_field_updates_and_matched_id_are_required_by_the_schema():
    # A field with a default is absent from the JSON schema's `required` list,
    # and a model generating against that schema will omit it. That silently
    # produced MATCH_AND_UPDATE with no updates on every article.
    required = ResolutionResponse.model_json_schema()["$defs"]["ResolutionResult"]["required"]
    assert "field_updates" in required
    assert "matched_id" in required


def test_matched_id_may_be_null_but_must_be_present():
    from src.shared.models import ResolutionResult
    import pytest as _pytest

    ok = {**MATCH, "matched_id": None, "resolution_action": "FLAG_AMBIGUOUS"}
    assert ResolutionResult.model_validate(ok).matched_id is None

    with _pytest.raises(Exception):
        ResolutionResult.model_validate({k: v for k, v in MATCH.items() if k != "field_updates"})


def test_a_match_naming_an_uninvited_uid_is_dropped():
    # candidate_matches.matched_uid is a foreign key; an invented value fails
    # the insert and takes the whole article's resolutions with it.
    rows = build_rows(_response(MATCH), ENTITIES, {1: [{"canonical_uid": "99999"}]})
    # The invented match is dropped, and what remains is a recorded CREATE_NEW
    # for every entity rather than silence.
    assert all(r["resolution_action"] == "CREATE_NEW" for r in rows)
    assert all(r["matched_uid"] is None for r in rows)


def test_a_match_naming_an_offered_uid_is_kept():
    rows = build_rows(_response(MATCH), ENTITIES, {1: [{"canonical_uid": "18606295"}]})
    assert rows[0]["matched_uid"] == "18606295"


def test_flags_are_not_required_to_name_a_candidate():
    flag = {**MATCH, "resolution_action": "FLAG_AMBIGUOUS", "matched_id": None}
    rows = build_rows(_response(flag), ENTITIES, {1: []})
    # One flag, and a CREATE_NEW row for each entity the model left out: the
    # decision that they were new is recorded rather than implied by silence.
    assert [r["resolution_action"] for r in rows] == ["FLAG_AMBIGUOUS", "CREATE_NEW", "CREATE_NEW"]


def test_a_flag_carrying_no_field_updates_is_valid():
    # The prompt tells the model that a MATCH_AND_UPDATE without field updates
    # usually means the change went unexpressed. That guidance must not leak
    # into the flag actions, or it biases the model away from flagging a
    # name-collision and toward overwriting a different person's record.
    flag = {**MATCH, "resolution_action": "FLAG_AMBIGUOUS",
            "matched_id": None, "field_updates": []}
    rows = build_rows(_response(flag), ENTITIES, OFFERED)
    assert rows[0]["resolution_action"] == "FLAG_AMBIGUOUS"
    assert rows[0]["field_updates"] == []


def test_merge_is_an_accepted_strategy():
    merged = {**MATCH, "field_updates": [
        {"field": "Description", "strategy": "MERGE", "value": "combined text"}]}
    rows = build_rows(_response(merged), ENTITIES, OFFERED)
    assert rows[0]["field_updates"][0]["strategy"] == "MERGE"


def test_the_review_sheet_holds_only_what_a_decision_needs():
    from src.export.proposals import FULL_COLUMNS, REVIEW_COLUMNS, REVIEW_HEADERS

    # The decision is a comparison, so both sides must be on the row.
    assert "article_says" in REVIEW_COLUMNS and "tte_says" in REVIEW_COLUMNS
    assert REVIEW_COLUMNS.index("verdict") > REVIEW_COLUMNS.index("tte_says")
    # Diagnostics belong in the full sheet, not in front of a librarian.
    for noise in ("matched_uid", "top_similarity", "reasoning", "proposal_id"):
        assert noise not in REVIEW_COLUMNS
        assert noise in FULL_COLUMNS
    # Every review column carries its instructions in the header.
    assert set(REVIEW_HEADERS) == set(REVIEW_COLUMNS)
    assert "yes" in REVIEW_HEADERS["verdict"]


def test_a_change_reads_as_an_instruction_not_a_keyword():
    from src.export.proposals import describe

    assert describe("MATCH_AND_UPDATE", {
        "field": "Awards", "strategy": "APPEND", "value": "Medal (2026)"
    }) == "Add to Awards: Medal (2026)"
    # A flag has no field update, and must still say what the reviewer is for.
    assert "needs a human" in describe("FLAG_AMBIGUOUS", None)


def test_a_flag_names_the_records_it_is_about():
    from src.export.proposals import alternatives

    records = {
        "1": {"name": "Loh, Jacqueline", "fields": {"Description": "Deputy MD at MAS"}},
        "2": {"name": "Loh, Jacqueline", "fields": {"Occupation": "Charity executive"}},
    }
    out = alternatives({"duplicate_uids": ["1", "2"]}, records)
    # "Two records look the same" without naming them is not a decision a
    # reviewer can make.
    assert "Deputy MD at MAS" in out and "Charity executive" in out


def test_who_tte_thinks_a_record_is_prefers_the_description():
    from src.export.proposals import identify

    assert identify({"Description": "A charity", "Occupation": "x"}).startswith("Description:")
    assert identify({}) == ""


def test_identity_facts_keep_their_real_field_names():
    from src.export.cards import identifying

    # Shown under the names the authority file uses, exactly as stored:
    # "Affiliations" matched nothing, and no card ever showed one.
    got = identifying({"Title": "Chief Executive Officer", "Affiliations(groupName)": "Aidha",
                       "Affiliations": "never stored under this name", "Image Link": "x"})
    assert [f["key"] for f in got] == ["Title", "Affiliations(groupName)"]
    assert got[0]["value"] == "Chief Executive Officer"


def test_identity_facts_are_ordered_most_identifying_first():
    from src.export.cards import identifying

    got = identifying({"Description": "A charity", "Occupation": "Engineer",
                       "Country": "Singapore"})
    assert [f["key"] for f in got] == ["Occupation", "Country", "Description"]
    assert identifying({}) == []
    assert identifying(None) == []


def test_proposals_resolving_to_one_record_become_one_card():
    from src.export.cards import _group_key

    # Four articles reporting on the same person is one identity decision, not
    # four. Asking a reviewer to confirm it once per article wastes their time
    # and invites them to answer inconsistently.
    a = _group_key({"matched_uid": "18567994"}, {"entity_name": "Alan Chan",
                                                 "entity_type": "PERSON"})
    b = _group_key({"matched_uid": "18567994"}, {"entity_name": "Alan Chan Heng Loon",
                                                 "entity_type": "PERSON"})
    assert a == b


def test_unmatched_entities_group_by_name_so_new_ones_still_merge():
    from src.export.cards import _group_key

    same = [_group_key({"matched_uid": None},
                       {"entity_name": n, "entity_name_en": "Kopi Near Me",
                        "entity_type": "ORGANISATION"})
            for n in ("Kopi Near Me", "KOPI NEAR ME")]
    assert same[0] == same[1]
    # A different type is a different entity even under the same name.
    other = _group_key({"matched_uid": None},
                       {"entity_name": "Kopi Near Me", "entity_name_en": "Kopi Near Me",
                        "entity_type": "FACILITY"})
    assert other != same[0]


def test_only_plausible_candidates_are_offered_as_choices():
    from src.export.cards import plausible

    # Trigram always returns its best five. At 1.00 against 0.33 there is one
    # candidate, not three, and offering the rest makes an easy call look hard.
    got = plausible([{"similarity": 1.0}, {"similarity": 0.85}, {"similarity": 0.33}])
    assert [c["similarity"] for c in got] == [1.0, 0.85]
    assert plausible([]) == []


def test_a_rewrite_is_shown_as_what_changed():
    from src.export.cards import diff_parts

    parts = diff_parts("He was a lawyer.", "He was a lawyer. He later chaired the board.")
    kinds = {p["op"] for p in parts}
    # Unchanged text is marked so it can be muted; the addition is what the
    # reviewer actually has to judge.
    assert "same" in kinds and "in" in kinds
    added = " ".join(p["text"] for p in parts if p["op"] == "in")
    assert "chaired the board" in added


def test_a_rewrite_reports_how_much_it_keeps():
    from src.export.cards import kept_ratio, REWRITE_WARN_BELOW

    old = "A practicing accountant for almost 30 years, well known in charity."
    # An addition keeps nearly everything.
    assert kept_ratio(old, old + " He chaired the council.") > REWRITE_WARN_BELOW
    # A replacement does not, and must be flagged: one observed MERGE cut a
    # 789-character description to 303, deleting a whole career history.
    assert kept_ratio(old, "An accountant.") < REWRITE_WARN_BELOW


def test_only_canonical_active_records_are_searchable():
    from src.export.cards import index_row

    canonical = {"uid": "1", "name": "Lee, Chuan Seng", "entity_type": "PERSON",
                 "is_active": True, "canonical_uid": "1",
                 "fields": {"Occupation": "Engineer",
                            "Description": "Founding president of the Singapore Green Building Council. "
                                           "He was appointed chair of the National Environment Agency in 2019."}}
    row = index_row(canonical)
    assert row[:4] == ["1", "Lee, Chuan Seng", "PERSON", "Engineer"]
    # The opening of the description ships too, so a reviewer who knows the
    # man chaired the NEA finds him whatever the extractor called him.
    assert "National Environment Agency" in row[4] and len(row[4]) <= 120

    # A non-preferred term points elsewhere and cannot receive an update, so
    # offering it would let a reviewer pick a target that takes no change.
    assert index_row({**canonical, "uid": "2", "canonical_uid": "1"}) is None
    # A retired record is not a valid target either.
    assert index_row({**canonical, "is_active": False}) is None
    # A record with no canonical pointer is itself canonical.
    assert index_row({**canonical, "canonical_uid": None})[0] == "1"


def test_a_search_result_says_who_the_record_is():
    from src.export.cards import index_row

    base = {"uid": "1", "name": "X", "entity_type": "PERSON",
            "is_active": True, "canonical_uid": "1"}
    # Occupation outranks Description as the one-line identity.
    assert index_row({**base, "fields": {"Occupation": "Engineer",
                                         "Description": "long text"}})[3] == "Engineer"
    assert index_row({**base, "fields": {"Description": "A charity."}})[3] == "A charity."
    assert index_row({**base, "fields": {}})[3] == ""


def test_two_reviewers_produce_two_rows_not_one():
    import json
    import tempfile
    from pathlib import Path

    from src.export.reviews import disagreements

    # The review app writes one document per reviewer per proposal. A single
    # document per proposal would mean the second verdict replaced the first,
    # and the disagreement -- the most useful signal there is -- would vanish.
    rows = [
        {"proposal_id": "7", "reviewer": "ash", "verdict": "approve", "entity": "X"},
        {"proposal_id": "7", "reviewer": "mei", "verdict": "reject", "entity": "X"},
        {"proposal_id": "8", "reviewer": "ash", "verdict": "approve", "entity": "Y"},
    ]
    split = disagreements(rows)
    assert {r["proposal_id"] for r in split} == {"7"}
    assert len(split) == 2


def test_only_entities_a_snapshot_affects_are_requeued():
    from src.job3_resolution import requeue as R

    # A new authority snapshot invalidates almost nothing. Measured against the
    # September import -- 766 added, 191 retired -- 58 of 60 entities sampled
    # had an unchanged candidate set. Re-resolving all of them pays an LLM call
    # per entity, re-opens settled matches, and destroys review decisions.
    assert hasattr(R, "stale_entities") and hasattr(R, "requeue")
    assert R.IMPORT_WINDOW.total_seconds() > 0


def test_the_offline_package_is_a_complete_document_with_its_own_downloads():
    from pathlib import Path
    from src.export.package import build

    template = (Path(__file__).resolve().parents[1] / "src/export/desk_template.html").read_text(encoding="utf-8")
    page = build(template)
    # A reviewer opens this from a zip, possibly with no network: the sheets
    # download as blobs, which a local file may start, and the document
    # carries its own charset, without which a local file shows mojibake.
    assert "URL.createObjectURL" in page and "\\ufeff" in page
    assert page.lstrip().lower().startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in page
    assert "claude.use" not in page and "__ONLINE__ = " not in page


def test_a_fact_already_in_a_multi_valued_field_is_not_new():
    """
    Two in five matches propose no change because the record has the fact
    already -- the award was catalogued before the article reporting it was
    read. The card has to say that, or "Confirm match" sits over a blank.
    """
    from src.export.cards import delta

    got = {d["field"]: d for d in delta(
        {"Awards": "Distinguished Service Order (2026)",
         "Occupation": "Executive",
         "Nationality": "Singaporean",
         "Name": "Bob Tan"},
        {"Awards": "Public Service Star (2010) | Distinguished Service Order (2026)",
         "Occupation": "Executive"},
    )}
    assert got["Awards"]["state"] == "same"
    assert got["Occupation"]["state"] == "same"
    assert got["Nationality"]["state"] == "new"
    # The name is the identity question the card already asked.
    assert "Name" not in got


def test_delta_separates_an_addition_from_a_rewrite():
    from src.export.cards import delta

    got = {d["field"]: d for d in delta(
        {"Occupation": "Engineer", "Description": "A newer account."},
        {"Occupation": "Banker | Philanthropist", "Description": "The held account."},
    )}
    # A list gains a value; prose is replaced, which is a different question.
    assert got["Occupation"]["state"] == "extra"
    assert got["Occupation"]["fresh"] == "Engineer"
    assert got["Description"]["state"] == "differs"


def test_a_street_the_record_already_holds_is_no_change_even_in_chinese():
    """
    Reviewer feedback, Snow City: "Jurong Town Hall Road" matches the address already held,
    and nothing in Chinese should be offered for an address. Only the street, or the street
    with its Chinese, is covered by the full address; a new street is still offered, in English.
    """
    from src.export.cards import delta

    held = {"Street Address": "21 Jurong Town Hall Road, Snow City Building"}
    assert delta({"Street Address": "裕廊大会堂路 (Jurong Town Hall Road)"}, held)[0]["state"] == "same"
    assert delta({"Street Address": "Jurong Town Hall Road"}, held)[0]["state"] == "same"
    new = delta({"Street Address": "裕廊东街 (Jurong East Street 21)"}, held)[0]
    assert new["state"] == "extra" and new["fresh"] == "Jurong East Street 21"
    # no English to offer: nothing is offered
    assert delta({"Street Address": "裕廊东街"}, held) == []


def test_a_new_record_takes_only_the_english_of_a_street_address():
    from src.export.cards import news_facts
    got = news_facts({"Country": "Singapore", "Street Address": "裕廊大会堂路 (Jurong Town Hall Road)"})
    assert {"key": "Street Address", "value": "Jurong Town Hall Road"} in got
    assert {"key": "Country", "value": "Singapore"} in got
    assert all(f["key"] != "Street Address" for f in news_facts({"Street Address": "裕廊东街"}))


def test_a_bilingual_value_already_held_in_english_is_not_offered_again():
    from src.export.cards import delta

    row = delta({"Affiliations(groupName)": "塔塔咨询公司 (Tata Consultancy Services)"},
                {"Affiliations(groupName)": "Roses of Peace | Tata Consultancy Services"})[0]
    assert row["state"] == "same"


def test_a_list_the_model_joined_with_commas_is_split_after_a_closing_bracket():
    """
    Reviewer feedback, Tan Liguo: four hospitals came as one comma-joined value, so the desk looked
    the whole string up and called all four "not in TTE yet". A comma inside a name is left alone.
    """
    from src.export.cards import news_values

    four = ("KK Women's and Children's Hospital (竹脚妇幼医院), Singapore General Hospital (新加坡中央医院), "
            "Tan Tock Seng Hospital (陈笃生医院), Sengkang General Hospital (盛港综合医院)")
    assert news_values(four) == ["KK Women's and Children's Hospital (竹脚妇幼医院)", "Singapore General Hospital (新加坡中央医院)",
                                 "Tan Tock Seng Hospital (陈笃生医院)", "Sengkang General Hospital (盛港综合医院)"]
    assert news_values("Tan, Tony | Lee, Kuan Yew") == ["Tan, Tony", "Lee, Kuan Yew"]
    assert news_values("Singapore. Ministry of Finance") == ["Singapore. Ministry of Finance"]


def test_delta_puts_what_is_new_first():
    from src.export.cards import delta

    order = [d["state"] for d in delta(
        {"Occupation": "Executive", "Nationality": "Singaporean"},
        {"Occupation": "Executive"},
    )]
    assert order == ["new", "same"]


def test_a_description_rewrite_that_adds_nothing_is_dropped():
    """
    The style guide's "do not list positions like a resume" is advice for
    writing a description. Applied to editing one it deleted a career, so the
    result is checked rather than trusted.
    """
    from src.shared.description import judge

    verdict, _, _ = judge("He was a lawyer and later a judge.",
                          "He was a lawyer, and later a judge.")
    assert verdict == "drop"


def test_a_description_is_counted_in_sentences_and_held_when_a_change_takes_it_past_five():
    """
    The style guide limits a description to 3 to 5 sentences, but editing is
    told to keep every fact, so descriptions only grow: in the stored rewrites 12
    in 100 records were over the limit already and 25 in 100 after the rewrite.
    A change that takes one past the limit is flagged for a person, not dropped.
    """
    from src.shared.description import over_limit, sentence_count

    assert sentence_count("") == 0 and sentence_count("Philanthropist.") == 1
    # a title's full stop does not end a sentence
    assert sentence_count("Mr. Lee founded the party. He was Prime Minister. Dr. Tan succeeded him.") == 3

    four, five = "One. Two. Three. Four.", "One. Two. Three. Four. Five."
    seven = five + " Six. Seven."
    assert not over_limit(four, five)                 # five is the limit, not over it
    assert over_limit(five, five + " Six.")           # the change makes it six
    assert not over_limit(seven, seven)               # already over, and this change adds nothing
    assert over_limit(seven, seven + " Eight.")       # already over, and this change adds to it
    assert over_limit("", five + " Six.")             # a description written from nothing counts too


def test_a_description_rewrite_that_deletes_a_career_is_flagged():
    from src.shared.description import judge

    verdict, left, gained = judge(
        "Chief of Navy with the rank Rear Admiral. He was Deputy Prime Minister "
        "from 2009 to 2019, and Member of Parliament for Pasir Ris-Punggol.",
        "Senior statesman who held leadership responsibilities across multiple "
        "ministerial portfolios.")
    assert verdict == "flag"
    assert left < 0.7
    assert gained


def test_an_appended_sentence_is_kept():
    from src.shared.description import judge

    verdict, left, gained = judge(
        "A practicing accountant, he was Nominated Member of Parliament, 1997-2002.",
        "A practicing accountant, he was Nominated Member of Parliament, 1997-2002. "
        "He chaired the Agency for Integrated Care from 2018 to 2026.")
    assert verdict == "keep"
    assert left == 1.0
    assert "Agency for Integrated Care" in " ".join(gained)


def test_a_first_description_is_never_flagged():
    from src.shared.description import judge

    assert judge("", "Philanthropist and community leader.")[0] == "keep"


# --- retrieval ranking ------------------------------------------------------

def _cand(uid, sim, **fields):
    return {"canonical_uid": uid, "canonical_name": uid, "similarity": sim,
            "canonical_fields": fields}


def test_a_person_dead_before_the_article_is_not_offered():
    """
    Lee, Choon Seng (d. 1966) scored 1.00 against a 2026 medal winner and
    produced a card a person had to look at. A seventh of every shortlist
    the resolver saw was already dead.
    """
    from src.job3_resolution.rank import rank

    entity = {"entity_type": "PERSON", "fields": {"Occupation": "Engineer"},
              "summary": "awarded a medal"}
    got = rank([_cand("banker", 1.0, **{"Death Year (yyyy)": "1966"}),
                _cand("living", 0.6)], entity, 2026, keep=5)
    assert [c["canonical_uid"] for c in got] == ["living"]


def test_an_article_about_a_death_may_name_the_dead():
    from src.job3_resolution.rank import rank

    obituary = {"entity_type": "PERSON", "fields": {},
                "summary": "The late philanthropist was remembered at a memorial."}
    got = rank([_cand("dead", 0.9, **{"Death Year (yyyy)": "1966"})], obituary, 2026, keep=5)
    assert got and got[0]["canonical_uid"] == "dead"

    reported = {"entity_type": "PERSON", "fields": {"Death Year (yyyy)": "2026"},
                "summary": "died on Tuesday"}
    got = rank([_cand("dead", 0.9, **{"Death Year (yyyy)": "2025"})], reported, 2026, keep=5)
    assert got


def test_a_recent_death_is_within_the_window():
    from src.job3_resolution.rank import rank

    entity = {"entity_type": "PERSON", "fields": {}, "summary": "..."}
    # Died last year: a follow-up story is plausible, so still offered.
    assert rank([_cand("x", 0.9, **{"Death Year (yyyy)": "2025"})], entity, 2026, keep=5)


def test_shared_facts_outrank_a_closer_name():
    """
    "Alan Chan": the right record sat fourth at 0.47 behind three strangers at
    0.58. It shares an affiliation with the article; they share nothing.
    """
    from src.job3_resolution.rank import rank

    entity = {"entity_type": "PERSON",
              "fields": {"Affiliations(groupName)": "Land Transport Authority",
                         "Nationality": "Singaporean"}}
    got = rank([
        _cand("stranger1", 0.58, Nationality="Singaporean"),
        _cand("stranger2", 0.58),
        _cand("right", 0.47, **{"Affiliations(groupName)":
                               "Land Transport Authority | Singapore Press Holdings"}),
    ], entity, 2026, keep=5)
    assert got[0]["canonical_uid"] == "right"
    assert got[0]["overlap"] == ["Affiliations(groupName)"]
    # Nationality is shared by nearly everyone and counts for nothing.
    assert got[1]["overlap"] == []


def test_nothing_shared_leaves_the_name_order_alone():
    from src.job3_resolution.rank import rank

    entity = {"entity_type": "ORGANISATION", "fields": {"Country": "Singapore"}}
    got = rank([_cand("a", 0.9), _cand("b", 0.7), _cand("c", 0.5)], entity, 2026, keep=2)
    assert [c["canonical_uid"] for c in got] == ["a", "b"]


def test_near_names_count_as_shared():
    from src.job3_resolution.rank import overlap

    got = overlap({"Affiliations(groupName)": "National Council of Social Service"},
                  {"Affiliations(groupName)": "National Council of Social Services"})
    assert got == ["Affiliations(groupName)"]


def test_one_proposal_per_entity_even_if_the_model_repeats_itself():
    """
    Four entities carried two identical proposals, written in the same
    minute: the model listed them twice in one answer, and delete-then-insert
    only guards against a second run.
    """
    from src.job3_resolution.update import build_rows
    from src.shared.models import ResolutionResponse

    response = ResolutionResponse.model_validate({"resolutions": [
        {"article_entity_name": "Aidha", "entity_type": "ORGANISATION",
         "resolution_action": "MATCH_AND_UPDATE", "matched_id": "1",
         "confidence": "high", "reasoning": "x", "field_updates": []},
        {"article_entity_name": "Aidha", "entity_type": "ORGANISATION",
         "resolution_action": "MATCH_AND_UPDATE", "matched_id": "1",
         "confidence": "high", "reasoning": "x again", "field_updates": []},
    ]})
    entities = [{"id": 7, "entity_name": "Aidha", "entity_type": "ORGANISATION"}]
    rows = build_rows(response, entities, {7: [{"canonical_uid": "1", "canonical_fields": {}}]})
    assert len(rows) == 1


def test_two_wordings_of_one_fact_become_one_corroborated_note():
    from src.export.cards import collapse

    got = collapse([
        {"field": "Awards", "strategy": "APPEND", "adding": "Ramon Magsaysay Award",
         "from": "ST", "existing": []},
        {"field": "Awards", "strategy": "APPEND", "adding": "Ramon Magsaysay Award (2026)",
         "from": "Zaobao", "existing": []},
    ])
    assert len(got) == 1
    assert got[0]["adding"] == "Ramon Magsaysay Award (2026)"   # the more specific wording
    assert got[0]["supporters"] == ["ST", "Zaobao"]
    assert got[0]["variants"] == ["Ramon Magsaysay Award"]
    assert got[0]["conflict"] is False


def test_sources_disagreeing_on_a_year_are_flagged_not_resolved():
    """One outlet said 2026, another 2025. The code never picks."""
    from src.export.cards import collapse

    got = collapse([
        {"field": "Awards", "strategy": "APPEND", "adding": "Doctor of Letters (2026)", "from": "ST", "existing": []},
        {"field": "Awards", "strategy": "APPEND", "adding": "Doctor of Letters (2025)", "from": "ZB", "existing": []},
    ])
    assert len(got) == 1 and got[0]["conflict"] is True
    assert set(got[0]["variants"] + [got[0]["adding"]]) == {"Doctor of Letters (2026)", "Doctor of Letters (2025)"}


def test_different_facts_on_one_list_field_are_one_note_with_both():
    """Two awards from one article: one screen, both values, each kept."""
    from src.export.cards import collapse

    got = collapse([
        {"field": "Awards", "strategy": "APPEND", "adding": "Public Service Star (2010)", "from": "A", "existing": []},
        {"field": "Awards", "strategy": "APPEND", "adding": "Meritorious Service Medal (2017)", "from": "A", "existing": []},
    ])
    assert len(got) == 1
    assert got[0]["adding"] == "Public Service Star (2010) | Meritorious Service Medal (2017)"


def test_an_entity_the_model_left_out_still_gets_a_row():
    """
    "Omitted means new" made two thirds of resolutions unrecordable. The
    decision is now written, with the candidates it was made against.
    """
    from src.job3_resolution.update import build_rows
    from src.shared.models import ResolutionResponse

    response = ResolutionResponse.model_validate({"resolutions": [
        {"article_entity_name": "Matched One", "entity_type": "PERSON",
         "resolution_action": "MATCH_AND_UPDATE", "matched_id": "9",
         "confidence": "high", "reasoning": "x", "field_updates": []},
    ]})
    entities = [{"id": 1, "entity_name": "Matched One", "entity_type": "PERSON"},
                {"id": 2, "entity_name": "Left Out", "entity_type": "FACILITY"}]
    cands = {1: [{"canonical_uid": "9", "canonical_fields": {}}],
             2: [{"canonical_uid": "5", "canonical_fields": {}, "similarity": 0.4}]}
    rows = {r["extracted_id"]: r for r in build_rows(response, entities, cands)}
    assert rows[1]["resolution_action"] == "MATCH_AND_UPDATE"
    assert rows[2]["resolution_action"] == "CREATE_NEW"
    assert rows[2]["matched_uid"] is None
    assert rows[2]["candidates"] == cands[2]          # what it was offered and declined


def test_a_record_reached_only_through_the_romanisation_is_held_below_exact():
    """
    李全盛 was romanised "Lee, Choon Seng", a real record for another man, at
    1.00. The romanisation is the extractor's guess, so a candidate it alone
    reaches is capped and marked; one the original name reached is not.
    """
    from src.job3_resolution.candidates import ROMANISED_CEILING, candidates_for

    def lookup(name, count, want_type):
        if name == "Lee, Choon Seng":
            return [{"canonical_uid": "1", "canonical_name": "Lee, Choon Seng", "similarity": 1.0,
                     "canonical_fields": {}}]
        if name == "李全盛":
            return [{"canonical_uid": "2", "canonical_name": "Lee, Chuan Seng", "similarity": 1.0,
                     "canonical_fields": {}}]
        return []

    got = candidates_for({"entity_name": "李全盛", "entity_name_en": "Lee, Choon Seng",
                          "entity_type": "PERSON", "fields": {}}, lookup=lookup)
    by = {c["canonical_uid"]: c for c in got}
    assert by["2"]["similarity"] == 1.0 and not by["2"].get("romanised")
    assert by["1"]["similarity"] == ROMANISED_CEILING and by["1"]["romanised"]
    assert got[0]["canonical_uid"] == "2"

    # An English name with a null or Latin entity_name_en is not a guess.
    got = candidates_for({"entity_name": "Lee Chuan Seng", "entity_name_en": None,
                          "entity_type": "PERSON", "fields": {}},
                         lookup=lambda n, c, t: [{"canonical_uid": "2", "canonical_name": "Lee, Chuan Seng",
                                                   "similarity": 1.0, "canonical_fields": {}}])
    assert got[0]["similarity"] == 1.0 and not got[0].get("romanised")


def test_two_articles_rewriting_one_description_become_one_note():
    """Two rewrites are two sets of sentences to add, not two rewrites to pick between."""
    from src.export.cards import collapse
    before = ["Founding president of the Singapore Green Building Council."]
    a = {"field": "Description", "strategy": "MERGE", "existing": before, "from": "ST",
         "adding": before[0] + " He was appointed chair of the National Environment Agency in 2019."}
    b = {"field": "Description", "strategy": "MERGE", "existing": before, "from": "ZB",
         "adding": before[0] + " He received the President's Science and Technology Medal in 2026."}
    out = collapse([a, b])
    assert len(out) == 1 and out[0]["supporters"] == ["ST", "ZB"]
    assert out[0]["result"].startswith(before[0]) and len(out[0]["adds"]) == 2
    assert out[0]["kept"] == 1.0 and not out[0]["conflict"]
    assert out[0]["overLimit"] is False and out[0]["sentences"] == 3
    # the same two additions to a description that already has five sentences: one is offered, still flagged as past the limit, and the other held back
    full = ["One. Two. Three. Four. Five."]
    out = collapse([{**a, "existing": full, "adding": full[0] + a["adding"][len(before[0]):]},
                    {**b, "existing": full, "adding": full[0] + b["adding"][len(before[0]):]}])
    assert out[0]["overLimit"] is True and out[0]["sentences"] == 6 and len(out[0]["held"]) == 1
    # a scalar field with two values is one question with two answers
    y1 = {"field": "Birth Year (yyyy)", "strategy": "REPLACE", "adding": "1954", "existing": [], "from": "ST"}
    y2 = {"field": "Birth Year (yyyy)", "strategy": "REPLACE", "adding": "1955", "existing": [], "from": "ZB"}
    out = collapse([y1, y2])
    assert len(out) == 1 and out[0]["conflict"] and set(out[0]["variants"]) | {out[0]["adding"]} == {"1954", "1955"}


def test_a_description_note_holds_back_sentences_beyond_the_guides_five_best_supported_first():
    """
    A famous record collected thirteen new sentences from eighty-three articles
    in one note. The guide allows three to five sentences, so the note carries
    what fits, the sentences more than one article carried first, and shows the
    rest as held back rather than dropping them.
    """
    from src.export.cards import collapse

    before = ["Politician. Prime Minister."]                      # two sentences, so room for three

    def ch(src, *adds, existing=before):
        return {"field": "Description", "strategy": "MERGE", "adding": " ".join(existing + list(adds)), "existing": existing, "from": src}

    a = ch("ST", "He won the Alpha Prize in 2019 for services to trade.", "He chaired the Beta Council from 2020 to 2023.")
    b = ch("CNA", "He won the Alpha Prize in 2019 for his services to trade.")      # the same fact, reworded
    c = ch("ZB", "He opened the Gamma Centre on 3 May 2024.", "He was awarded the Delta Medal in 2025.")
    note = collapse([a, b, c])[0]
    assert note["sentences"] == 5 and note["overLimit"] is False
    assert note["held"] == ["He was awarded the Delta Medal in 2025."]
    assert len(note["adds"]) == 3 and note["adds"][0].startswith("He won the Alpha Prize")   # best supported first kept
    assert note["alts"] and len(note["alts"][0]["wordings"]) == 2                          # the reworded fact is offered, not asked twice

    # a record already at the limit still gets one sentence to decide on, and the rest are held
    full = ["One. Two. Three. Four. Five."]
    crowded = collapse([ch("ST", "He won the Alpha Prize in 2019 for services to trade.", "He chaired the Beta Council from 2020 to 2023.", existing=full),
                        ch("ZB", "He opened the Gamma Centre on 3 May 2024.", "He was awarded the Delta Medal in 2025.", existing=full)])[0]
    assert len(crowded["adds"]) == 1 and len(crowded["held"]) >= 3


def test_a_sentence_one_article_lengthened_is_replaced_where_it_stands():
    """
    Chee Hong Tat: one article worked an action team into his last sentence, another added a sentence. The note read
    "from May 2025. 2025, and chairs an action team...", and the second article's sentence was held back.
    """
    from src.export.cards import collapse
    before = ["Member of Parliament for Bishan-Toa Payoh GRC since 2015. He was promoted to full minister in Jan 2024. "
              "He is Minister for National Development from May 2025. He chairs the Housing Board. He sits on two committees. "
              "He is married with two children."]
    last = "He is married with two children."
    longer = before[0].replace("from May 2025.", "from May 2025, and chairs an action team set up in February 2026 for construction firms.")
    added = before[0] + " In October 2026, he announced a S$30.4 million construction research initiative."
    note = collapse([{"field": "Description", "strategy": "MERGE", "existing": before, "adding": longer, "from": "ST"},
                     {"field": "Description", "strategy": "MERGE", "existing": before, "adding": added, "from": "ZB"}])[0]
    assert note["result"] == longer + " In October 2026, he announced a S$30.4 million construction research initiative."
    assert note["held"] == [] and note["adds"][0].startswith("He is Minister for National Development")
    assert note["subs"] and note["result"].endswith("initiative.") and last in note["result"]


def test_a_rewrite_is_read_as_whole_sentences():
    from src.shared.description import sentence_edits
    old = "He is a lawyer. He is Minister for Law from May 2025. He has two children."
    # lengthened in place, a sentence added after it, one reworded with no new fact
    new = "He is a lawyer. He is Minister for Law from May 2025, and chairs the Bar Council since 2026. He opened a school in Bedok on 2 May. He has 2 children."
    assert sentence_edits(old, new) == [
        {"at": 1, "to": 2, "text": "He is Minister for Law from May 2025, and chairs the Bar Council since 2026."},
        {"at": 2, "to": 2, "text": "He opened a school in Bedok on 2 May."}]
    # a sentence that keeps little of the old one does not replace it: the old one stays and the new one goes in after it
    assert sentence_edits("He sits on the board of Mediacorp.", "In October 2026 he was appointed chairman of the NVPC board.") == [
        {"at": 1, "to": 1, "text": "In October 2026 he was appointed chairman of the NVPC board."}]


def test_near_identical_list_values_from_different_articles_are_one_value():
    """Five Achievements rows for one swimmer were one achievement worded five ways."""
    from src.export.cards import collapse

    a = {"field": "Achievements", "strategy": "APPEND", "existing": [], "from": "ST",
         "adding": "She is the first Singaporean to win a gold medal at the Paralympic Games in Beijing in 2008."}
    b = {"field": "Achievements", "strategy": "APPEND", "existing": [], "from": "CNA",
         "adding": "She became the first Singaporean to win a Paralympic gold medal at the 2008 Games in Beijing."}
    out = collapse([a, b])
    assert len(out) == 1 and "|" not in out[0]["adding"] and len(out[0]["variants"]) == 1
    assert out[0]["supporters"] == ["CNA", "ST"]


def test_the_shortlist_counts_records_not_name_rows():
    """
    The database returns a row per matching name, and a record with variant
    names fills several. Eight rows ended before "Lee, Chuan Seng" at 0.579;
    fetched deeper and re-ranked on the Engineer overlap, he outranks the
    0.611 librarian, and the resolver still sees at most five.
    """
    from src.job3_resolution.candidates import MATCH_COUNT, candidates_for

    def names(query, count, want_type):
        rows = [("1", "Lee, Choon Seng", 1.0, {"Occupation": "Banker", "Death Year (yyyy)": "1966"})] * 2
        rows += [("2", "Wee, Choon Seng", 0.667, {"Occupation": "Badminton player"})] * 2
        rows += [("3", "Lee, Ching Seng", 0.611, {"Occupation": "Librarian"})] * 2
        rows += [("4", "Huai, Ying", 0.611, {}), ("5", "Koh, Seng Choon", 0.579, {}),
                 ("6", "Lee, Chuan Seng", 0.579, {"Occupation": "Engineer"}),
                 ("7", "Lee, Choon Kee", 0.556, {})]
        return [{"canonical_uid": u, "canonical_name": n, "similarity": s, "canonical_fields": f}
                for u, n, s, f in rows[:count]]

    got = candidates_for({"entity_name": "李全盛", "entity_name_en": "Lee, Choon Seng",
                          "entity_type": "PERSON", "fields": {"Occupation": "Engineer"}},
                         article_year=2026, lookup=lambda q, k, t: names(q, k, t) if q != "李全盛" else [])
    uids = [c["canonical_uid"] for c in got]
    assert "6" in uids and "1" not in uids            # fetched; the dead banker gone
    assert uids.index("6") < uids.index("3")          # Engineer overlap beats a nearer name
    assert len(got) <= MATCH_COUNT


def test_one_source_is_never_a_disagreement():
    """A description with several years in it is one proposal, not a conflict."""
    from src.export.cards import collapse
    one = {"field": "Description", "strategy": "MERGE", "existing": ["x"],
           "adding": "Appointed in 1995, judge in 2003, president in 2004.", "adds": ["president in 2004."], "from": "ST"}
    assert collapse([one])[0]["conflict"] is False
    two = {"field": "Awards", "strategy": "APPEND", "existing": [],
           "adding": "Meritorious Service Award (1993) | CC Tan Award (2011)", "from": "ST"}
    assert collapse([two])[0]["conflict"] is False
    # two sources, two years for the same award: that is one
    a = {"field": "Awards", "strategy": "APPEND", "existing": [], "adding": "Doctor of Letters (2026)", "from": "ST"}
    b = {"field": "Awards", "strategy": "APPEND", "existing": [], "adding": "Doctor of Letters (2025)", "from": "ZB"}
    got = collapse([a, b])[0]
    assert got["conflict"] and {(x["value"], x["from"]) for x in got["saidBy"]} == {
        ("Doctor of Letters (2026)", "ST"), ("Doctor of Letters (2025)", "ZB")}


def test_two_sources_adding_to_one_list_field_are_one_note():
    """
    "SPH Media Trust | SPH Media Holdings" from one article and "SPH Media
    Trust" from another were two screens and two sheet rows. One note, every
    value once, each value knowing which sources named it.
    """
    from src.export.cards import collapse
    held = ["People's Action Party (Singapore)"]
    a = {"field": "Affiliations(groupName)", "strategy": "APPEND", "existing": held,
         "adding": "SPH Media Trust | SPH Media Holdings", "from": "ST"}
    b = {"field": "Affiliations(groupName)", "strategy": "APPEND", "existing": held,
         "adding": "SPH Media Trust", "from": "CNA"}
    out = collapse([a, b])
    assert len(out) == 1
    note = out[0]
    assert note["adding"] == "SPH Media Trust | SPH Media Holdings"
    assert note["result"] == "People's Action Party (Singapore) | SPH Media Trust | SPH Media Holdings"
    assert note["supporters"] == ["CNA", "ST"] and not note["conflict"]
    assert {v["value"]: v["sources"] for v in note["perValue"]} == {
        "SPH Media Trust": ["CNA", "ST"], "SPH Media Holdings": ["ST"]}
    # a value the sources date differently stays its own question
    c = {"field": "Awards", "strategy": "APPEND", "existing": [], "adding": "Doctor of Letters (2026) | Public Service Star (2018)", "from": "ST"}
    d = {"field": "Awards", "strategy": "APPEND", "existing": [], "adding": "Doctor of Letters (2025)", "from": "ZB"}
    out = collapse([c, d])
    assert [(n["adding"], n["conflict"]) for n in out] == [
        ("Public Service Star (2018)", False), ("Doctor of Letters (2026)", True)]


def test_one_sentence_worded_by_two_sources_is_added_once():
    """
    The Straits Times and Lianhe Zaobao each gave Goh Yihan's appointment as
    a sentence for the description, and both were added: the same fact twice.
    The fuller wording is added and the other is offered in its place.
    """
    from src.export.cards import collapse
    before = ("Lawyer and law professor. Associate Professor of Law at the Singapore "
              "Management University, with research interests in contract law.")
    st = ("He was appointed a Judge of the Appellate Division of the Supreme Court effective "
          "1 October 2026, having served as Deputy Attorney-General.")
    zb = "He has served as Deputy Attorney-General and as a Judge of the Appellate Division."
    note = lambda adds, src: {"field": "Description", "strategy": "MERGE", "existing": [before],
                              "adding": before + " " + adds, "adds": [adds], "from": src}
    got = collapse([note(st, "ST"), note(zb, "ZB")])[0]
    assert got["adds"] == [st] and got["alts"] == [{"wordings": [st, zb]}]
    assert got["result"].count("Deputy Attorney-General") == 1
    # two different facts, one from each source, are both added
    got = collapse([note("She was appointed Minister for Trade in 2024.", "ST"),
                    note("She was appointed Minister for Health in 2026.", "ZB")])[0]
    assert len(got["adds"]) == 2 and got["alts"] == []


def test_a_rewrite_lists_every_change_to_the_existing_text():
    """A joined sentence and a changed year are shown as was → now, not hidden."""
    from src.export.cards import diff_parts, edits_in
    before = "He served on the Charity Council from 2015. He lives in Singapore."
    after = "He served on the Charity Council from 2015, and chaired it from 2026. He lives in Singapore."
    drops, subs = edits_in(diff_parts(before, after))
    assert drops == [] and subs == [{"was": "2015.", "now": "2015, and chaired it from 2026."}]
    drops, subs = edits_in(diff_parts("Born in 1954 in Malacca.", "Born in 1955 in Malacca."))
    assert subs == [{"was": "1954", "now": "1955"}]
    drops, subs = edits_in(diff_parts("A long sentence about a Navy career. Another one.", "Another one."))
    assert drops == ["A long sentence about a Navy career."] and subs == []


def test_linked_values_are_looked_up_exactly_then_nearly():
    """An organisation TTE spells "Singapore. Civil Defence Force" is in TTE, and the badge says under what name."""
    from src.export.cards import Lookup, record_flags
    index = [["1", "Singapore. Civil Defence Force", "ORGANISATION", "", ""],
             ["2", "SPH Media Trust", "ORGANISATION", "", ""],
             ["3", "President's Science and Technology Medal", "AWARD", "", ""]]
    orgs = Lookup(index, "ORGANISATION")
    got = record_flags("SPH Media Trust | Singapore Civil Defence Force | SPH Media Holdings", orgs)
    assert got[0] == {"name": "SPH Media Trust", "uid": "2"}
    assert got[1]["uid"] == "1" and got[1]["as"] == "Singapore. Civil Defence Force"   # house style
    assert got[2]["uid"] is None
    # merely near is not a match: a different award that shares three words
    awards2 = Lookup([["9", "Inspiring Teacher of English Award", "AWARD", "", ""]], "AWARD")
    near = record_flags("Inspiring Teacher Award", awards2)[0]
    assert near["uid"] is None and near["nearest"] == "Inspiring Teacher of English Award"
    awards = Lookup(index, "AWARD")
    assert record_flags("President’s Science and Technology Medal (2026)", awards)[0]["uid"] == "3"


def test_an_original_name_with_its_gloss_is_looked_up_both_ways():
    """"博理中学 (Bendemeer Secondary School)": the original reaches the record through
    a variant name TTE holds; failing that, the gloss is tried."""
    from src.export.cards import Lookup, record_flags
    index = [["1", "Bendemeer Secondary School", "ORGANISATION", "", ""],
             ["2", "Singapore Hokkien Huay Kuan", "ORGANISATION", "", ""]]
    variants = [["博理中学", "1", "ORGANISATION"], ["福建会馆", "2", "ORGANISATION"]]
    orgs = Lookup(index, "ORGANISATION", variants)
    got = record_flags("博理中学 (Bendemeer Secondary School) | 福建会馆 (Hokkien Huay Kuan) | 武吉巴督中学 (Bukit Batok Secondary School)", orgs)
    assert got[0]["uid"] == "1" and got[0]["as"] == "Bendemeer Secondary School"   # via the variant
    assert got[1]["uid"] == "2"                                                     # via the variant
    assert got[2]["uid"] is None                                                    # neither known
    # the gloss alone is enough when TTE has no Chinese name
    got = record_flags("明智中学 (Bendemeer Secondary School)", Lookup(index, "ORGANISATION"))
    assert got[0]["uid"] == "1"


def test_a_link_value_is_proposed_as_the_record_is_named():
    """"Housing and Development Board" is proposed as "Singapore. Housing and Development Board",
    with what the article wrote kept beside it; a merely nearest record is left as written."""
    from src.export.cards import named_as_tte
    ch = {"field": "Affiliations(groupName)", "strategy": "APPEND", "existing": ["People's Action Party (Singapore)"],
          "adding": "Housing and Development Board | SPH Media Holdings",
          "inTTE": [{"name": "Housing and Development Board", "uid": "1", "as": "Singapore. Housing and Development Board"},
                    {"name": "SPH Media Holdings", "uid": None, "nearest": "SPH Media", "nearest_uid": "2"}],
          "perValue": [{"value": "Housing and Development Board", "sources": []}, {"value": "SPH Media Holdings", "sources": []}]}
    named_as_tte(ch)
    assert ch["adding"] == "Singapore. Housing and Development Board | SPH Media Holdings"
    assert ch["result"].startswith("People's Action Party (Singapore) | Singapore. Housing")
    assert ch["inTTE"][0]["name"] == "Singapore. Housing and Development Board" and ch["inTTE"][0]["wrote"] == "Housing and Development Board"
    assert ch["perValue"][0]["value"] == "Singapore. Housing and Development Board"
    assert ch["inTTE"][1]["name"] == "SPH Media Holdings"
    # an award keeps its year through the renaming
    aw = {"field": "Awards", "strategy": "APPEND", "existing": [], "adding": "President's Volunteerism & Philanthropy Award (2025)",
          "inTTE": [{"name": "President's Volunteerism & Philanthropy Award (2025)", "uid": "3", "as": "President's Volunteerism & Philanthropy Awards"}]}
    named_as_tte(aw)
    assert aw["adding"] == "President's Volunteerism & Philanthropy Awards (2025)"


def test_job3_stores_a_link_value_as_tte_names_the_record():
    """The proposal already holds the value a cataloguer will type, with what the article wrote beside it."""
    from src.shared.names import name_link_values

    def search(name, entity_type):
        table = {"Housing and Development Board": [{"canonical_name": "Singapore. Housing and Development Board", "canonical_uid": "1"}],
                 "Public Service Star": [{"canonical_name": "Public Service Star", "canonical_uid": "2"}],
                 "博理中学": [{"matched_name": "博理中学", "canonical_name": "Bendemeer Secondary School", "canonical_uid": "3"}]}
        return table.get(name, [{"canonical_name": "Something Else", "canonical_uid": "9"}])

    u = {"field": "Affiliations(groupName)", "strategy": "APPEND",
         "value": "Housing and Development Board | 博理中学 (Bendemeer Secondary) | Unknown Society"}
    name_link_values(u, search)
    assert u["value"] == "Singapore. Housing and Development Board | Bendemeer Secondary School | Unknown Society"
    assert u["wrote"] == {"Singapore. Housing and Development Board": "Housing and Development Board",
                          "Bendemeer Secondary School": "博理中学 (Bendemeer Secondary)"}
    a = {"field": "Awards", "strategy": "APPEND", "value": "Public Service Star (2010)"}
    name_link_values(a, search)
    assert a["value"] == "Public Service Star (2010)" and "wrote" not in a     # already TTE's name
    d = {"field": "Description", "strategy": "MERGE", "value": "prose"}
    name_link_values(d, search)
    assert d["value"] == "prose"                                            # not a link field

    # and through build_rows
    ents = [{"id": 1, "entity_name": "Tan Mei Ling", "entity_name_en": None, "entity_type": "PERSON", "fields": {}}]
    r = {**MATCH, "article_entity_name": "Tan Mei Ling", "entity_type": "PERSON",
         "field_updates": [{"field": "Affiliations(groupName)", "strategy": "APPEND", "value": "Housing and Development Board"}]}
    rows = build_rows(_response(r), ents, {1: [{"canonical_uid": "18606295"}]}, search=search)
    assert rows[0]["field_updates"][0]["value"] == "Singapore. Housing and Development Board"


def test_an_omission_with_an_exact_own_spelling_hit_is_an_identity_question():
    """
    Tommy Koh, left out of the model's answer, was written CREATE_NEW by the
    prompt's contract and dealt as "not in TTE. Create a record?" with Koh,
    Tommy in the candidates at similarity 1. The card asks the identity
    question instead; a hit through a romanised guess still does not.
    """
    from src.export.cards import omitted_exact

    omitted = {"reasoning": "Not returned by the model: no offered candidate was judged to be this entity.",
               "candidates": [{"canonical_uid": "18338504", "canonical_name": "Koh, Tommy", "similarity": 1,
                               "matched_via": "Tommy Koh"},
                              {"canonical_uid": "2", "canonical_name": "Goh, Tommie", "similarity": 0.31,
                               "matched_via": "Tommy Koh"}]}
    top = omitted_exact(omitted, {"entity_name": "Tommy Koh"})
    assert top and top["canonical_uid"] == "18338504"
    # 李全盛's exact hit was "Lee, Choon Seng" through the model's guessed
    # spelling: that is the case the card must go on calling "create?".
    guessed = {"reasoning": omitted["reasoning"],
               "candidates": [{"canonical_uid": "1", "similarity": 1, "matched_via": "Lee, Choon Seng", "romanised": True}]}
    assert omitted_exact(guessed, {"entity_name": "李全盛", "entity_name_en": "Lee, Choon Seng"}) is None
    # A near name is not an exact one, and a decision the model did make is not an omission.
    near = {"reasoning": omitted["reasoning"], "candidates": [{"canonical_uid": "1", "similarity": 0.8, "matched_via": "X"}]}
    assert omitted_exact(near, {"entity_name": "X"}) is None
    assert omitted_exact({**omitted, "reasoning": "Exact name match."}, {"entity_name": "Tommy Koh"}) is None


def test_an_omission_is_folded_into_the_record_another_article_matched(monkeypatch):
    """
    Hsieh Fu Hua was matched in one article and left out in another, and the
    deck dealt him twice: once as a match, once as "not in TTE". Both
    proposals now sit on one card, decided once, and the match's reason
    stands rather than the omission's.
    """
    from src.export import cards

    koh = {"uid": "18338504", "name": "Koh, Tommy", "entity_type": "PERSON",
           "fields": {"Occupation": "Diplomat", "Birth Year (yyyy)": "1937", "Description": "Ambassador-at-Large."}}
    hit = {"canonical_uid": "18338504", "canonical_name": "Koh, Tommy", "similarity": 1,
           "matched_via": "Tommy Koh", "matched_name": "Prof. Tommy Koh", "canonical_fields": koh["fields"]}
    entities = [
        {"id": 545, "article_id": 1, "entity_name": "Tommy Koh", "entity_name_en": None, "entity_type": "PERSON",
         "summary": "Won the Ramon Magsaysay Award.", "evidence": "Tommy Koh, 88, has won the Ramon Magsaysay Award.",
         "fields": {"Occupation": "Diplomat"}, "backfill": False, "role": "subject"},
        {"id": 553, "article_id": 2, "entity_name": "Tommy Koh", "entity_name_en": None, "entity_type": "PERSON",
         "summary": "Career spanned five decades.", "evidence": "Koh's career has spanned more than five decades.",
         "fields": {"Occupation": "Diplomat"}, "backfill": False, "role": "subject"},
    ]
    proposals = [
        {"id": 277, "extracted_id": 545, "resolution_action": "CREATE_NEW", "matched_uid": None,
         "reasoning": "Not returned by the model: no offered candidate was judged to be this entity.",
         "field_updates": [], "candidates": [hit], "duplicate_uids": []},
        {"id": 208, "extracted_id": 553, "resolution_action": "MATCH_AND_UPDATE", "matched_uid": "18338504",
         "reasoning": "Exact name match.", "candidates": [hit], "duplicate_uids": [],
         "field_updates": [{"field": "Awards", "strategy": "APPEND", "value": "Ramon Magsaysay Award (2026)"}]},
    ]
    articles = {1: {"id": 1, "title": "Tommy Koh wins Ramon Magsaysay Award", "url": "https://cna/1", "pubDate": "2026-09-01"},
                2: {"id": 2, "title": "Tommy Koh at 88", "url": "https://st/2", "pubDate": "2026-09-02"}}
    tables = {"candidate_matches": proposals, "extracted_entities": entities}

    class Query:
        def __init__(self, table): self.table = table
        def select(self, *_): return self
    class Client:
        def from_(self, table): return Query(table)
    monkeypatch.setattr(cards, "get_client", lambda: Client())
    monkeypatch.setattr(cards, "fetch_all", lambda build, **kw: tables[build().table])
    monkeypatch.setattr(cards, "column_exists", lambda *a: True)
    monkeypatch.setattr(cards, "_by_id", lambda table, column, ids, select:
                        articles if table == "article" else {koh["uid"]: koh})

    dealt, noted = cards.build_cards(index=[], variants=[])
    assert len(dealt) == 1 and dealt[0]["key"] == "uid:18338504"
    card = dealt[0]
    assert sorted(card["pids"]) == [208, 277] and len(card["sources"]) == 2
    assert card["picked"] == "18338504" and not card["isNew"]
    # The match settles the identity; the omission's reason is not carried.
    assert not card["isFlag"] and card["flagWhy"] == ""
    # The way in is shown: the candidate was reached through a non-preferred term.
    assert card["options"][0]["npt"] == "Prof. Tommy Koh"

    # Alone, the omission is the identity question, not "create?".
    tables["candidate_matches"] = proposals[:1]
    tables["extracted_entities"] = entities[:1]
    dealt, _ = cards.build_cards(index=[], variants=[])
    assert len(dealt) == 1 and dealt[0]["isFlag"] and not dealt[0]["isNew"]
    assert dealt[0]["picked"] == "18338504" and dealt[0]["flagWhy"].startswith("The model gave no answer")


GERARD_SAYS = ("Gerard Ee, 77, is stepping down as chairperson of the Agency for Integrated Care (AIC), "
               "with social service veteran Anita Fam taking over the helm from Sept 1.")
FAM_SAYS = ("In recognition of her contributions, Fam was awarded the Ministry of Social and Family Development's "
            "Lifetime Achievement Award and the President's Volunteerism & Philanthropy Award in 2025.")


def test_a_change_is_quoted_with_the_sentence_that_backs_it_not_the_one_the_person_was_given():
    """
    Anita Fam had two facts in two sentences. Extraction gave her the awards
    sentence and filed the one about her taking over under Gerard Ee, so her
    card quoted the awards under her new chairmanship as well.
    """
    from src.export.cards import quote_for

    own = {"quote": FAM_SAYS, "original": ""}
    others = [{"id": 550, "quote": GERARD_SAYS, "original": ""}]
    names = ["Anita Fam", "", "Anita Fam"]
    post = {"field": "Affiliations(groupName)", "adding": "Agency for Integrated Care"}
    awards = {"field": "Awards", "adding": "Ministry of Social and Family Development's Lifetime Achievement Award (2025)"}
    assert quote_for(post, names, own, others) == {"quote": GERARD_SAYS, "original": ""}
    assert quote_for(awards, names, own, others) is None                  # her own sentence already backs it
    # A sentence that does not name her proves nothing about her.
    stranger = [{"id": 9, "quote": "The Agency for Integrated Care was set up in 2009.", "original": ""}]
    assert quote_for(post, names, own, stranger) is None
    # A description rewrite is judged on the sentence it adds, not on the whole passage.
    rewrite = {"field": "Description", "adding": "A long passage that is mostly the old text. " * 6 + "Chairperson of the Agency for Integrated Care from 2026.",
               "adds": ["Chairperson of the Agency for Integrated Care from 2026."]}
    assert quote_for(rewrite, names, own, others)["quote"] == GERARD_SAYS
    # Chinese: matched on characters, and the name may be in the original or the translation.
    zh = {"field": "Affiliations(groupName)", "adding": "老年护理局"}
    sentence = [{"id": 1, "quote": "Anita Fam will chair the agency.", "original": "范雅娟将出任老年护理局主席。"}]
    assert quote_for(zh, ["范雅娟", "Anita Fam"], {"quote": "x", "original": ""}, sentence)["original"].startswith("范雅娟")


def test_her_card_quotes_the_succession_sentence_under_the_new_post_and_the_awards_under_the_awards(monkeypatch):
    from src.export import cards

    fam = {"uid": "18704109", "name": "Fam, Anita", "entity_type": "PERSON", "fields": {"Occupation": "Lawyer"}}
    ee = {"uid": "18567994", "name": "Ee, Gerard", "entity_type": "PERSON", "fields": {"Occupation": "Accountant"}}

    def hit(record):
        return {"canonical_uid": record["uid"], "canonical_name": record["name"], "similarity": 1, "matched_via": record["name"],
                "matched_name": record["name"], "canonical_fields": record["fields"]}
    entities = [
        {"id": 550, "article_id": 2197, "entity_name": "Gerard Ee", "entity_name_en": None, "entity_type": "PERSON",
         "summary": "Stepped down as chairperson.", "evidence": GERARD_SAYS, "fields": {"Occupation": "Accountant"}, "backfill": False, "role": "subject"},
        {"id": 551, "article_id": 2197, "entity_name": "Anita Fam", "entity_name_en": None, "entity_type": "PERSON",
         "summary": "Won two awards and is set to become chairperson.", "evidence": FAM_SAYS, "fields": {"Occupation": "Lawyer"},
         "backfill": False, "role": "subject"},
    ]
    proposals = [
        {"id": 1, "extracted_id": 550, "resolution_action": "MATCH_AND_UPDATE", "matched_uid": "18567994", "reasoning": "Exact.",
         "candidates": [hit(ee)], "duplicate_uids": [],
         "field_updates": [{"field": "Affiliations(groupName)", "strategy": "APPEND", "value": "Agency for Integrated Care"}]},
        {"id": 2, "extracted_id": 551, "resolution_action": "MATCH_AND_UPDATE", "matched_uid": "18704109", "reasoning": "Exact.",
         "candidates": [hit(fam)], "duplicate_uids": [],
         "field_updates": [{"field": "Awards", "strategy": "APPEND", "value": "Lifetime Achievement Award (2025)"},
                           {"field": "Affiliations(groupName)", "strategy": "APPEND", "value": "Agency for Integrated Care"}]},
    ]
    articles = {2197: {"id": 2197, "title": "Gerard Ee steps down", "url": "https://st/2197", "pubDate": "2026-08-31"}}
    tables = {"candidate_matches": proposals, "extracted_entities": entities}

    class Query:
        def __init__(self, table): self.table = table
        def select(self, *_): return self
    class Client:
        def from_(self, table): return Query(table)
    monkeypatch.setattr(cards, "get_client", lambda: Client())
    monkeypatch.setattr(cards, "fetch_all", lambda build, **kw: tables[build().table])
    monkeypatch.setattr(cards, "column_exists", lambda *a: True)
    monkeypatch.setattr(cards, "_by_id", lambda table, column, ids, select: articles if table == "article" else {fam["uid"]: fam, ee["uid"]: ee})

    dealt, _ = cards.build_cards(index=[], variants=[])
    card = next(c for c in dealt if c["key"] == "uid:18704109")
    post = next(ch for ch in card["changes"] if ch["field"] == "Affiliations(groupName)")
    awards = next(ch for ch in card["changes"] if ch["field"] == "Awards")
    assert post["quotes"] == {"https://st/2197": {"quote": GERARD_SAYS, "original": ""}}
    assert "quotes" not in awards                                         # her own sentence backs the awards
    # His own sentence backs his own change; nothing is borrowed.
    his = next(c for c in dealt if c["key"] == "uid:18567994")
    assert all("quotes" not in ch for ch in his["changes"])


def test_every_non_preferred_term_is_listed_under_its_record():
    from src.export.cards import npt_map

    variants = [["许通美", "18338504", "PERSON"], ["Prof. Tommy Koh", "18338504", "PERSON"],
                ["许通美", "18338504", "PERSON"], ["", "1", "PERSON"], ["X", None, "PERSON"],
                # the record's own words in another order say nothing
                ["Tommy Koh", "18338504", "PERSON"], ["Singapore Civil Defence Force", "9", "ORGANISATION"]]
    index = [["18338504", "Koh, Tommy", "PERSON", "", ""], ["9", "Singapore. Civil Defence Force", "ORGANISATION", "", ""]]
    assert npt_map(variants, index) == {"18338504": ["许通美", "Prof. Tommy Koh"]}
