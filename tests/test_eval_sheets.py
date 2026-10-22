"""The labelled sheets and the scoring that reads them back."""

import json

import pandas as pd
import pytest


def test_a_score_carries_its_range_and_a_small_n_shows_it():
    from src.eval.plan import share
    from src.eval.score import pr, ranged

    assert ranged(share(8, 10)).startswith("0.80 [")
    # The same share on a tenth of the rows is reported far less certainly.
    span = lambda t: t[2] - t[1]
    assert span(share(8, 10)) > span(share(80, 100)) * 2
    assert ranged(share(0, 0)) == "n/a"
    assert "F1 0.80" in pr(share(8, 10), share(8, 10))


def test_agreement_is_chance_corrected():
    from src.eval.score import kappa

    assert kappa(["Y"] * 5 + ["N"] * 5, ["Y"] * 5 + ["N"] * 5) == pytest.approx(1.0)
    # Two labellers who both say Y to everything agree completely and say nothing.
    import math
    assert math.isnan(kappa(["Y"] * 6, ["Y"] * 6))
    some = kappa(["Y", "Y", "N", "N"], ["Y", "N", "N", "N"])
    assert 0 < some < 1


def test_a_marked_sheet_scores_against_the_key(tmp_path):
    from src.eval.score import report

    key = tmp_path / "2-matching-key.json"
    key.write_text(json.dumps([
        {"id": 1, "app_said_same": True, "tte_id": "a", "script": "latin"},
        {"id": 2, "app_said_same": True, "tte_id": "b", "script": "chinese"},
        {"id": 3, "app_said_same": False, "tte_id": "c", "script": "latin"},
        {"id": 4, "app_said_same": False, "tte_id": "d", "script": "chinese"},
    ]), encoding="utf-8")
    back = tmp_path / "returned"
    back.mkdir()
    rows = pd.DataFrame([{"id": 1, "same": "Y"}, {"id": 2, "same": "N"},
                         {"id": 3, "same": "Y"}, {"id": 4, "same": "?"}])
    with pd.ExcelWriter(back / "2-matching-glenn.xlsx", engine="openpyxl") as w:
        rows.to_excel(w, sheet_name="rows", index=False)
    assert report(back, tmp_path) == 0


def test_the_unsure_answer_is_counted_not_dropped():
    from src.eval.score import _mark

    assert _mark("?") == "?" and _mark("Not sure") == "?"
    assert _mark("TRUE") == "Y" and _mark("y") == "Y" and _mark(" no ") == "N"
    # Anything else is an unfilled or unreadable cell, not a verdict.
    assert _mark("") is None and _mark("maybe later") is None


def test_the_sheet_holds_no_answer_and_the_key_holds_it(tmp_path):
    from src.eval import sheets

    sheet = pd.DataFrame({"url": ["u1", "u2"], "relevant": ["", ""]})
    k = pd.DataFrame({"url": ["u1", "u2"], "app_said": [True, False]})
    sheets._write(tmp_path, "1-relevance", sheet, k, "a note", "50 rows")
    back = pd.read_excel(tmp_path / "1-relevance.xlsx", sheet_name="rows",
                         dtype=str, keep_default_na=False)
    assert (back["relevant"] == "").all() and "app_said" not in back.columns
    start = pd.read_excel(tmp_path / "1-relevance.xlsx", sheet_name="start here")
    assert "minutes" in start.columns[0]
    assert json.loads((tmp_path / "1-relevance-key.json").read_text(encoding="utf-8"))[0]["app_said"] is True


def test_each_year_gets_its_share_and_the_weights_put_the_group_back():
    """
    A weighted estimate is only unbiased if every item had a known chance of being drawn and each row's
    weight is its year's items over its year's rows: then the weights of the rows drawn add up to the group.
    """
    import random

    from src.eval import sheets

    items = [("2015", i) for i in range(3000)] + [("2022", i) for i in range(6000)] + [("2026", i) for i in range(1000)]
    got, years, passed = sheets.by_year(items, lambda x: x[0], 200, random.Random(1))
    assert len(got) == 200 and years == {"2015": [3000, 60], "2022": [6000, 120], "2026": [1000, 20]} and passed == 0
    assert sum(w for _, w in got) == pytest.approx(len(items))
    assert {w for (y, _), w in got if y == "2026"} == {50.0}
    assert len({x for x, _ in got}) == 200                      # drawn without replacement
    # a group smaller than its rows is taken whole, each row standing for itself
    small, _, _ = sheets.by_year(items[:30], lambda x: x[0], 200, random.Random(1))
    assert len(small) == 30 and {w for _, w in small} == {1.0}


def test_an_article_whose_page_gives_no_text_is_passed_over_for_the_next_of_its_year(tmp_path):
    import random

    from src.eval import sheets

    asked = []

    def fetch(url):
        asked.append(url)
        if url.endswith("dead"):
            raise RuntimeError("404")
        return "" if url.endswith("empty") else "Some text."

    check = sheets.readable(tmp_path, fetch, pause=0)
    items = ([("2015", f"https://www.straitstimes.com/a{i}-dead") for i in range(5)]
             + [("2015", f"https://www.straitstimes.com/b{i}") for i in range(5)]
             + [("2016", "https://www.straitstimes.com/c-empty"), ("2016", "https://www.straitstimes.com/d")])
    got, years, passed = sheets.by_year(items, lambda x: x[0], 6, random.Random(3), lambda x: check(x[1]))
    assert not any(u.endswith(("dead", "empty")) for (_, u), _ in got)
    assert years == {"2015": [10, 5], "2016": [2, 1]} and passed == len(asked) - 6
    # each one drawn still stands for its year's whole group
    assert sum(w for _, w in got) == pytest.approx(12)
    # the text is kept for the page, and a page that gave it is not fetched again
    kept = json.loads((tmp_path / "3-extraction-texts.json").read_text(encoding="utf-8"))
    assert kept["https://www.straitstimes.com/d"] == "Some text."
    n = len(asked)
    assert check("https://www.straitstimes.com/d") and len(asked) == n


def test_named_is_found_fast_and_as_a_plain_search_would():
    from src.eval import sheets

    names = {"tan kah kee", "national library board", "esplanade"}
    named = sheets._namer(names)
    for text in ("Tan Kah Kee's old house reopens", "The NATIONAL LIBRARY BOARD said", "Esplanade's new hall",
                 "Tan Kah", "a library board", "", "Esplanad"):
        assert named(text) == any(n in text.lower() for n in names), text


def test_a_weighted_miss_counts_for_more_than_one(tmp_path):
    """One labelled miss in a stratum sampled at one in five stands for five."""
    import json

    from src.eval.score import report

    (tmp_path / "1-relevance-key.json").write_text(json.dumps([
        {"url": "a", "app_said": True, "stratum": "the app called it relevant", "weight": 1.0},
        {"url": "b", "app_said": True, "stratum": "the app called it relevant", "weight": 1.0},
        {"url": "c", "app_said": False, "stratum": "rejected, names none", "weight": 5.0},
    ]), encoding="utf-8")
    back = tmp_path / "returned"
    back.mkdir()
    rows = pd.DataFrame([{"url": "a", "source": "cna", "relevant": "TRUE"},
                         {"url": "b", "source": "cna", "relevant": "TRUE"},
                         {"url": "c", "source": "cna", "relevant": "TRUE"}])
    with pd.ExcelWriter(back / "1-relevance-glenn.xlsx", engine="openpyxl") as w:
        rows.to_excel(w, sheet_name="rows", index=False)
    assert report(back, tmp_path) == 0
