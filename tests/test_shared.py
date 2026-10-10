"""Shared helpers: paged reads, retry logic, extraction schemas."""

import pytest

from src.shared.gemini_client import _is_retryable, _retry_after
from src.shared.models import ExtractionResponse, ResolutionResponse
from src.shared.pagination import fetch_all


class FakeQuery:
    """Minimal stand-in for a PostgREST builder, capped like the real one."""

    def __init__(self, rows, cap=1000):
        self.rows, self.cap = rows, cap
        self.ordered_by = None

    def order(self, column):
        self.ordered_by = column
        return self

    def range(self, start, end):
        self._slice = self.rows[start:min(end + 1, start + self.cap)]
        return self

    def execute(self):
        return type("R", (), {"data": self._slice})


@pytest.mark.parametrize("total", [0, 1, 999, 1000, 1001, 2500])
def test_fetch_all_reads_past_the_1000_row_cap(total):
    rows = [{"uid": str(i)} for i in range(total)]
    assert fetch_all(lambda: FakeQuery(rows)) == rows


def test_fetch_all_orders_every_page_by_the_key():
    """Unordered pages drift once the heap has been rewritten: 349 rows came
    back twice in place of 349 that never came at all."""
    seen = []

    def build():
        q = FakeQuery([{"uid": "1"}])
        seen.append(q)
        return q

    fetch_all(build)
    assert seen[0].ordered_by == "id"
    fetch_all(build, order="uid")
    assert seen[1].ordered_by == "uid"


def test_fetch_all_stops_on_a_short_page():
    calls = []

    def build():
        calls.append(1)
        return FakeQuery([{"uid": "1"}])

    fetch_all(build)
    assert len(calls) == 1


def test_server_retry_hint_is_honoured():
    # A shorter backoff just burns another request against the same quota.
    assert _retry_after(Exception("429 ... Please retry in 20.3s.")) == 20.3
    assert _retry_after(Exception("retryDelay: 7s")) == 7.0
    assert _retry_after(Exception("no hint here")) is None


@pytest.mark.parametrize("message,expected", [
    ("Error code: 429 too many requests", True),
    ("503 Service Unavailable", True),
    ("RESOURCE_EXHAUSTED", True),
    ("400 invalid argument", False),
])
def test_only_transient_failures_are_retried(message, expected):
    assert _is_retryable(Exception(message)) is expected


def test_extraction_schema_accepts_a_null_english_name():
    r = ExtractionResponse.model_validate_json(
        '{"entities":[{"entity_name":"Aidha","entity_name_en":null,'
        '"entity_type":"ORGANISATION","summary":"s","evidence":"e",'
        '"fields":{},"confidence":"high","role":"subject"}]}')
    assert r.entities[0].entity_name_en is None


def test_extraction_schema_carries_the_english_name_when_present():
    r = ExtractionResponse.model_validate_json(
        '{"entities":[{"entity_name":"\\u738b\\u632f\\u80e1",'
        '"entity_name_en":"Wong, Chin Hu","entity_type":"PERSON","summary":"s",'
        '"evidence":"e","fields":{},"confidence":"high","role":"mentioned"}]}')
    assert r.entities[0].entity_name_en == "Wong, Chin Hu"


def test_extraction_schema_requires_the_role_and_allows_it_null():
    """
    Required, so the API has to fill it: a default would keep it out of the
    schema's required list, which is how field_updates once vanished. Nullable,
    so an answer from a model that was never asked still reads (the backfill
    sets it to null before validating) and the deck falls back to the headline.
    """
    schema = ExtractionResponse.model_json_schema()["$defs"]["ExtractedEntity"]
    assert "role" in schema["required"]
    import pytest
    with pytest.raises(Exception):
        ExtractionResponse.model_validate_json(
            '{"entities":[{"entity_name":"A","entity_type":"PERSON","summary":"s",'
            '"evidence":"e","fields":{}}]}')
    r = ExtractionResponse.model_validate_json(
        '{"entities":[{"entity_name":"A","entity_type":"PERSON","summary":"s",'
        '"evidence":"e","fields":{},"role":null}]}')
    assert r.entities[0].role is None


def test_resolution_schema_treats_an_empty_list_as_valid():
    # CREATE_NEW is the omitted default, so no resolutions is a normal answer.
    assert ResolutionResponse.model_validate_json('{"resolutions":[]}').resolutions == []


def test_a_model_chain_falls_through_on_quota_only():
    import src.shared.gemini_client as g
    from pydantic import BaseModel

    class Out(BaseModel):
        ok: str

    original = g._generate_one
    try:
        tried = []

        def quota_until_last(model, prompt, schema, thinking_level, retries):
            tried.append(model)
            if model != "last":
                raise RuntimeError("429 RESOURCE_EXHAUSTED")
            return Out(ok="yes")

        g._generate_one = quota_until_last
        assert g.generate_json(["first", "second", "last"], "p", Out).ok == "yes"
        assert tried == ["first", "second", "last"]

        # Anything that is not a quota refusal must surface immediately.
        # Walking the chain there would burn every model on the same real bug.
        tried.clear()

        def bad_request(model, prompt, schema, thinking_level, retries):
            tried.append(model)
            raise RuntimeError("400 invalid argument")

        g._generate_one = bad_request
        try:
            g.generate_json(["first", "second"], "p", Out)
        except RuntimeError:
            pass
        assert tried == ["first"]
    finally:
        g._generate_one = original


def test_the_settings_file_loads_and_a_misspelt_setting_stops_the_run(tmp_path):
    import pytest
    from pydantic import ValidationError

    from src.shared.config import PATH, load

    s = load()
    assert s.resolution.models and s.relevance.batch_size > 0 and s.extraction.thinking
    for broken in (PATH.read_text().replace("batch_size", "batchsize"),       # misspelt
                   PATH.read_text().replace("articles_per_request = 1", ""),  # missing
                   PATH.read_text().replace('thinking = "high"', 'thinking = "hihg"', 1)):
        bad = tmp_path / "pipeline.toml"
        bad.write_text(broken)
        with pytest.raises(ValidationError):
            load(bad)


def test_near_miss_field_names_resolve_to_what_tte_stores():
    from src.shared.field_names import canonical

    # These are the exact mistakes the hand-written prompt lists produced. Each
    # would create a new field rather than extend the real one, and nothing
    # downstream would notice.
    assert canonical("ORGANISATION", "Year Started") == "Year Started (yyyy)"
    assert canonical("PERSON", "Affiliations") == "Affiliations(groupName)"
    assert canonical("PERSON", "Birth Year") == "Birth Year (yyyy)"
    assert canonical("FACILITY", "Year Completed") == "Year Completed (yyyy)"
    # Case and spacing are forgiven; the stored spelling is what comes back.
    assert canonical("PERSON", "affiliations(groupname)") == "Affiliations(groupName)"


def test_fields_tte_does_not_have_are_rejected():
    from src.shared.field_names import canonical, clean_fields

    # Successor and Predecessor are relationships between records in TTE, not
    # fields, though the earlier prompt listed them as fields.
    assert canonical("ORGANISATION", "Successor") is None
    assert canonical("ORGANISATION", "Predecessor") is None
    assert canonical("PERSON", "Portfolio") is None
    # A field belonging to another type is not silently accepted either.
    assert canonical("LEGAL_ACT", "Occupation") is None

    kept, dropped = clean_fields("PERSON", {"Birth Year": "1961", "Invented": "x"})
    assert kept == {"Birth Year (yyyy)": "1961"}
    assert dropped == ["Invented"]


def test_no_two_real_fields_normalise_to_the_same_key():
    import collections
    from src.shared.field_names import FIELDS, _normalise

    for entity_type, fields in FIELDS.items():
        counts = collections.Counter(_normalise(f) for f in fields)
        assert not [k for k, n in counts.items() if n > 1], entity_type


def test_occupation_vocabulary_is_a_closed_list():
    from src.shared.field_rules import occupations

    terms = set(occupations().splitlines())
    # Real occupations from the authority file.
    assert "Politician" in terms and "Engineer" in terms and "Teacher" in terms
    # Posts are not occupations. The guidelines say so and the vocabulary,
    # derived from the authority file itself, simply does not contain them.
    for post in ("Chairperson", "CEO", "Minister for Defence", "Acting Minister"):
        assert post not in terms


def test_prompts_carry_the_field_names_and_the_distinctions():
    from src.job2_extraction.prompt import load_prompt as extraction
    from src.job3_resolution.prompt import load_prompt as resolution

    ex = extraction()
    assert "{field_rules}" not in ex
    # Exact stored names, so a value lands on the field that exists.
    assert "Affiliations(groupName)" in ex and "Birth Year (yyyy)" in ex
    # The semantics code cannot supply: a rejected value is lost, but a value
    # the model files correctly in the first place is kept.
    assert "A POST IS NOT AN OCCUPATION" in ex
    # The term lists themselves are enforced in code, not spent on tokens.
    assert "Zoologist" not in ex
    assert "{field_rules}" not in resolution()


def test_every_derived_vocabulary_is_a_closed_list():
    from src.shared.field_rules import vocabularies

    v = vocabularies()
    # Derived from the authority file, not invented: these are terms actually
    # in use on two or more records.
    assert "PERSON.Nationality" in v and "PERSON.Title" in v
    assert "FACILITY.Feature Type" in v and "EVENT.Category" in v
    # Title is honorifics, so the posts the guidelines exclude are absent.
    titles = v[v.index("PERSON.Title"):v.index("FACILITY.Feature Type")]
    for post in ("Chairperson", "Chief Executive Officer", "Acting Minister"):
        assert post not in titles


def test_the_description_style_rules_are_carried_into_both_prompts():
    from src.job2_extraction.prompt import load_prompt as extraction
    from src.job3_resolution.prompt import load_prompt as resolution

    # Section 7 of the guidelines. A description outlives the news that
    # prompted it, so time-relative words date it immediately.
    for prompt in (extraction(), resolution()):
        assert '"current", "former", "then" and "now"' in prompt
        assert "like a resume" in prompt


def test_resolution_carries_the_notability_test():
    from src.job3_resolution.prompt import load_prompt

    # 106 of 166 entities came back as CREATE_NEW with no notability test at
    # all. The appendix defines one.
    p = load_prompt()
    assert "NOTABLE" in p and "quoted in passing" in p


def test_a_controlled_value_keeps_its_valid_parts():
    from src.shared.field_names import clean_value

    # A multi-valued field should not be lost entirely because one term is bad.
    assert clean_value("Occupation", "Lawyer | Chief Executive Officer") == "Lawyer"
    assert clean_value("Occupation", "Lawyer | Politician") == "Lawyer | Politician"
    # Nothing valid left means the field is dropped, not stored empty.
    assert clean_value("Occupation", "Chief Executive Officer") is None
    # Unconstrained fields pass through untouched.
    assert clean_value("Description", "anything at all") == "anything at all"


def test_a_post_is_rejected_as_a_title():
    from src.shared.field_names import clean_fields

    kept, dropped = clean_fields("PERSON", {"Title": "Chairperson", "Occupation": "Lawyer"})
    assert kept == {"Occupation": "Lawyer"}
    assert dropped == ["Title='Chairperson'"]


def test_every_nightly_queue_excludes_the_backfill():
    """
    Backfill rows live in the nightly tables (extracted_entities.article_id
    is a foreign key into article) and must never wake Jobs 1-3 or a
    requeue: 31,000 entities on a 500-a-day quota is two months of nights.
    """
    import inspect
    from src.job1_relevance import fetch as f1
    from src.job2_extraction import fetch as f2
    from src.job3_resolution import fetch as f3, requeue
    for mod in (f1, f2, f3, requeue):
        src = inspect.getsource(mod)
        assert 'eq("backfill", False)' in src, mod.__name__
        assert "column_exists" in src, mod.__name__       # and still runs before sql/09


def test_a_spent_daily_quota_is_neither_waited_on_nor_asked_again(monkeypatch):
    import src.shared.gemini_client as g
    from pydantic import BaseModel

    class Out(BaseModel):
        ok: str

    calls, waits = [], []

    def raw(model, prompt, schema, thinking_level):
        calls.append(model)
        if model == "strong":
            raise RuntimeError("429 RESOURCE_EXHAUSTED. quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier. "
                               "Please retry in 40.2s.")
        if model == "busy" and calls.count("busy") == 1:
            raise RuntimeError("429 RESOURCE_EXHAUSTED. quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier. "
                               "Please retry in 3s.")
        return '{"ok": "yes"}'

    monkeypatch.setattr(g, "_raw_call", raw)
    monkeypatch.setattr(g.time, "sleep", waits.append)
    monkeypatch.setattr(g, "_SPENT", set())
    # A daily cap moves straight down the chain, and later calls skip the model.
    assert g.generate_json(["strong", "light"], "p", Out).ok == "yes"
    assert g.generate_json(["strong", "light"], "p", Out).ok == "yes"
    assert calls == ["strong", "light", "light"] and waits == []
    # A per-minute limit is worth the wait the server asks for.
    calls.clear()
    assert g.generate_json(["busy", "light"], "p", Out).ok == "yes"
    assert calls == ["busy", "busy"] and waits == [4.0]


def test_the_model_that_answered_is_remembered_for_the_jobs_to_store(monkeypatch):
    import src.shared.gemini_client as g
    from pydantic import BaseModel

    class Out(BaseModel):
        ok: str

    def raw(model, prompt, schema, thinking_level):
        if model == "strong":
            raise RuntimeError("429 RESOURCE_EXHAUSTED quotaId: GenerateRequestsPerDayPerProjectPerModel")
        return '{"ok": "yes"}'

    monkeypatch.setattr(g, "_raw_call", raw)
    monkeypatch.setattr(g, "_SPENT", set())
    g.generate_json(["strong", "light"], "p", Out)
    # The chain fell through, so the answer came from the weaker model.
    assert g.LAST_MODEL == "light"
