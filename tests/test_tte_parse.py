"""
TTE authority parsing.

The highest-risk code in the repo: a format change here loads the reference
database wrong, silently. The fixture mirrors the real export's structure.
"""

from datetime import date

import pytest

from src.load_tte.parse import VALUE_DELIMITER, language_of, parse, parse_filename

FIXTURE = "tests/fixtures/TTE-ORGANISATIONS_FULL_20260603.csv"


@pytest.fixture(scope="module")
def parsed():
    return parse(FIXTURE)


def test_filename_gives_entity_type_and_snapshot():
    assert parse_filename("TTE-PEOPLE_FULL_20260603.csv") == ("PERSON", date(2026, 6, 3))
    assert parse_filename("TTE-GEOBUILDINGS_FULL_20260603.csv")[0] == "FACILITY"
    assert parse_filename("TTE-LEGALACTS_FULL_20260603.csv")[0] == "LEGAL_ACT"


def test_unknown_filenames_are_rejected_rather_than_guessed():
    with pytest.raises(ValueError):
        parse_filename("TTE-SOMETHING_FULL_20260603.csv")
    with pytest.raises(ValueError):
        parse_filename("random.csv")


def test_historical_events_share_the_event_type():
    # Nine authority files map onto eight prompt types.
    assert parse_filename("TTE-EVENTS_FULL_20260603.csv")[0] == "EVENT"
    assert parse_filename("TTE-HISTORICAL_EVENTS_FULL_20260603.csv")[0] == "EVENT"


@pytest.mark.parametrize("vocab,expected", [
    ("_Organisations", "en"), ("_Organisations_CN", "zh"),
    ("_Organisations_MY", "ms"), ("_Organisations_TM", "ta"),
    ("_People", "en"), ("_Geographics_CN", "zh"),
])
def test_language_comes_from_the_vocabulary_suffix(vocab, expected):
    assert language_of(vocab) == expected


def test_rows_with_a_related_uid_are_links_not_attributes(parsed):
    assert ("101", "100", "Use") in parsed.links
    assert ("200", "300", "CHItoENG") in parsed.links
    assert "Use" not in parsed.entities["101"].fields


def test_only_the_link_types_resolution_walks_are_stored(parsed):
    # The export also carries UF, ENGtoCHI, BT, NT, RT, Successor and
    # Predecessor -- 63% of all links -- which nothing queries.
    from src.load_tte.parse import STORED_LINK_TYPES
    assert {t for _, _, t in parsed.links} <= STORED_LINK_TYPES
    # ENGtoCHI in particular must never be stored: following it would resolve
    # an English match into a field-less Chinese record.
    assert "ENGtoCHI" not in {t for _, _, t in parsed.links}


def test_self_references_are_dropped(parsed):
    # "600 RT 600" would violate nothing but carries no information.
    assert not any(f == t for f, t, _ in parsed.links)


def test_repeated_attributes_accumulate_with_the_shared_delimiter(parsed):
    awards = parsed.entities["100"].fields["Awards"]
    assert awards == f"First prize{VALUE_DELIMITER}Second prize"


def test_uris_and_sources_are_not_stored(parsed):
    fields = parsed.entities["100"].fields
    assert "LDMS URI" not in fields
    assert "Source" not in fields


def test_non_english_records_carry_names_but_no_fields(parsed):
    # They are pointers to an English canonical, which holds the data.
    for uid in ("200", "400", "500"):
        assert parsed.entities[uid].name
        assert parsed.entities[uid].fields == {}


def test_every_key_uid_becomes_exactly_one_entity(parsed):
    assert len(parsed.entities) == 7
    assert parsed.entities["100"].name == "AWARE Awards"


def test_parsing_from_memory_matches_parsing_from_disk():
    # The bucket path supplies content as a string rather than a path.
    with open(FIXTURE, encoding="utf-8-sig") as fh:
        from_memory = parse(FIXTURE, content=fh.read())
    assert from_memory.entities.keys() == parse(FIXTURE).entities.keys()
