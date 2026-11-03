"""
The combine step's checks (src/combine), on the trial of 3 Nov 2026 (docs/descriptions.md): Pang Kin Keong's four
articles as recorded, and the answer AI Studio gave for them.
"""

from src.combine import Combined, checked, draft_key, records_from_cards, room

TTE = ("Permanent Secretary, Ministry of Law (2010-2012); Permanent Secretary, Ministry of Transport (2012-2017); "
       "Permanent Secretary, Ministry of Home Affairs (since 2017). He is also one of the board of directors of Mediacorp.")
PANG = {"key": "uid:1|11,12,13,14", "name": "Pang Kin Keong", "tte": TTE, "sources": [
    {"n": 1, "link": "cna", "outlet": "cna", "date": "2026-08-31", "title": "Land Transport Authority to get new chairman",
     "quote": "Former Ministry of Home Affairs (MHA) permanent secretary Pang Kin Keong has been appointed chairman of the "
              "Land Transport Authority (LTA), succeeding Mr Alan Chan, who has held the post for more than a decade.",
     "new_sentences": ["A distinguished public administrator, he was appointed chairman of the Land Transport Authority "
                       "to guide national transport systems."]},
    {"n": 2, "link": "st", "outlet": "st", "date": "2026-08-31", "title": "Retired civil servant Pang Kin Keong to succeed Alan Chan as LTA chairman on Sept 1",
     "quote": "Retired civil servant Pang Kin Keong will take over from Alan Chan Heng Loon as chairman of the Land Transport "
              "Authority (LTA) on Sept 1.",
     "new_sentences": ["Permanent Secretary, Ministry of Home Affairs (2017-2024); and chairman of the Land Transport Authority Board."]},
    {"n": 3, "link": "zb1", "outlet": "zb", "date": "2026-09-28", "title": "",
     "quote": "Former Permanent Secretary for Home Affairs Pang Kin Keong will succeed Seah Chin Siong as board chairman of the "
              "National Volunteer & Philanthropy Centre from the 1st of next month.",
     "new_sentences": ["In October 2026, he was appointed board chairman of the National Volunteer & Philanthropy Centre."]},
    {"n": 4, "link": "zb2", "outlet": "zb", "date": "2026-08-31", "title": "",
     "quote": "Former Permanent Secretary for Home Affairs Pang Kin Keong, 59, who retired from the administrative service on "
              "1 June this year after a 35-year public service career, will succeed 73-year-old Alan Chan as Chairman of the "
              "Land Transport Authority board on Tuesday (1 September).",
     "new_sentences": ["Permanent Secretary, Ministry of Home Affairs (2017-2026).",
                       "He serves as Chairman of the Land Transport Authority from 2026."]},
]}

ANSWER = {
    "add": [
        {"text": "He stepped down as Permanent Secretary, Ministry of Home Affairs.", "sources": [2, 4]},
        {"text": "He was appointed Chairman of the Land Transport Authority on 1 September, succeeding Alan Chan Heng Loon.", "sources": [1, 2, 4]},
        {"text": "In October 2026, he was appointed board chairman of the National Volunteer & Philanthropy Centre, succeeding Seah Chin Siong.", "sources": [3]},
    ],
    "disagreements": [{"about": "end year as Permanent Secretary, Ministry of Home Affairs",
                       "values": [{"value": "2024", "sources": [2]}, {"value": "2026", "sources": [4]}]}],
    "corrections": [{"quote": "Ministry of Home Affairs (since 2017)", "replace_with": "Ministry of Home Affairs (from 2017)", "sources": [2, 4]},
                    {"quote": "words not in the description", "replace_with": "x", "sources": [2]}],
    "left_out": [{"text": "He retired from the administrative service on 1 June after a 35-year public service career.", "sources": [4]}],
}


def test_the_checks_keep_what_the_articles_state_and_drop_the_rest():
    got = checked(PANG, Combined.model_validate(ANSWER))
    assert got["ok"]
    texts = [s["text"] for s in got["add"]]
    assert texts == ["He stepped down as Permanent Secretary, Ministry of Home Affairs.",
                     "In October 2026, he was appointed board chairman of the National Volunteer & Philanthropy Centre, succeeding Seah Chin Siong."]
    assert any("no year" in d and "1 September" in d for d in got["dropped"])     # "on 1 September", which year?
    assert got["add"][1]["sources"] == ["zb1"]
    assert got["left_out"] == []                                                    # "1 June", no year either
    # "2024" is only in Job 3's sentence for The Straits Times; the article never printed it, so there is no dispute
    assert got["disagreements"] == []
    assert [c["quote"] for c in got["corrections"]] == ["Ministry of Home Affairs (since 2017)"]


def test_an_article_is_taken_off_a_sentence_whose_date_it_does_not_give():
    """Khaw Boon Wan's sentence cited all five papers; the first gives neither date."""
    record = {"key": "k", "name": "Khaw Boon Wan", "tte": "Minister.", "sources": [
        {"n": 1, "link": "a", "outlet": "", "title": "Khaw Boon Wan to step down as SPH Media Trust chairman",
         "quote": "Khaw Boon Wan will step down as chairman of SPH Media Trust.", "new_sentences": []},
        {"n": 2, "link": "b", "outlet": "", "title": "",
         "quote": "Khaw Boon Wan, chairman of SPH Media Trust and SPH Media Holdings since May 2021, retires on 1 October 2026.",
         "new_sentences": []}]}
    got = checked(record, Combined.model_validate({"add": [{"text": "He was chairman of SPH Media Trust and SPH Media Holdings from May 2021 until 1 October 2026.", "sources": [1, 2]}],
                                                   "disagreements": [], "corrections": [], "left_out": []}))
    assert got["add"][0]["sources"] == ["b"]


def test_filler_and_repeats_are_dropped_and_nothing_left_falls_back():
    got = checked(PANG, Combined.model_validate({"add": [
        {"text": "A distinguished public administrator, he chaired the Land Transport Authority from 2026.", "sources": [4]},
        {"text": "He is also one of the board of directors of Mediacorp.", "sources": [2]}],
        "disagreements": [], "corrections": [], "left_out": []}))
    assert got["ok"] is False and got["add"] == [] and len(got["dropped"]) == 2


def test_the_room_left_under_five_sentences():
    assert room(TTE) == 3 and room("One. Two. Three. Four. Five. Six.") == 1


def test_records_come_from_description_notes_two_articles_wrote_to():
    card = {"key": "uid:9", "entity": "X", "sources": [{"link": "a", "pid": 5, "article": "A", "quote": "qa"},
                                                      {"link": "b", "pid": 3, "article": "B", "quote": "qb"},
                                                      {"link": "c", "pid": 7, "article": "C", "quote": "qc"}],
            "changes": [{"field": "Description", "existing": ["Old."], "said": {"S1.": ["a"], "S2.": ["b", "a"]}},
                        {"field": "Description", "existing": ["Old."], "said": {"S3.": ["c"]}}]}
    (record,) = records_from_cards([card])
    assert record["key"] == "uid:9|3,5" == draft_key(card, card["changes"][0])
    assert [(s["n"], s["new_sentences"]) for s in record["sources"]] == [(1, ["S1.", "S2."]), (2, ["S2."])]


def test_an_articles_date_without_a_year_is_in_the_year_it_was_published():
    """The Straits Times wrote "on Sept 1"; the year comes from the article's own date, not from the model."""
    record = {"key": "k", "name": "Pang Kin Keong", "tte": "Permanent Secretary.", "sources": [
        {"n": 1, "link": "st", "outlet": "", "date": "2026-08-31", "title": "",
         "quote": "Retired civil servant Pang Kin Keong will take over from Alan Chan Heng Loon as chairman of the "
                  "land transport authority on Sept 1.", "new_sentences": []},
        {"n": 2, "link": "old", "outlet": "", "date": "2025-01-02", "title": "", "quote": "Land Transport Authority, Sept 1.",
         "new_sentences": []}]}
    got = checked(record, Combined.model_validate({"add": [
        {"text": "He became chairman of the Land Transport Authority on 1 September 2026.", "sources": [1, 2]}],
        "disagreements": [], "corrections": [], "left_out": []}))
    assert got["add"] == [{"text": "He became chairman of the Land Transport Authority on 1 September 2026.", "sources": ["st"]}]


def test_overlap_the_model_left_is_removed_and_a_new_verb_is_kept():
    record = {"key": "k", "name": "Pang Kin Keong", "tte": TTE, "sources": [
        {"n": 1, "link": "a", "outlet": "", "date": "2026-08-31", "title": "",
         "quote": "He stepped down from the Ministry of Home Affairs and became chairman of the Land Transport Authority, "
                  "succeeding Alan Chan. "
                  "He is a board member of Mediacorp.", "new_sentences": []},
        {"n": 2, "link": "b", "outlet": "", "date": "2026-08-31", "title": "",
         "quote": "He became chairman of the Land Transport Authority.", "new_sentences": []}]}
    got = checked(record, Combined.model_validate({"add": [
        {"text": "He stepped down as Permanent Secretary, Ministry of Home Affairs.", "sources": [1]},
        {"text": "He is also one of the board of directors of Mediacorp.", "sources": [1]},
        {"text": "He became chairman of the Land Transport Authority.", "sources": [2]},
        {"text": "In 2026 he became chairman of the Land Transport Authority, succeeding Alan Chan.", "sources": [1]}],
        "disagreements": [], "corrections": [], "left_out": []}))
    assert [s["text"] for s in got["add"]] == ["He stepped down as Permanent Secretary, Ministry of Home Affairs.",
                                               "In 2026 he became chairman of the Land Transport Authority, succeeding Alan Chan."]
    assert got["add"][1]["sources"] == ["a", "b"]                 # the shorter one's article moves to it
