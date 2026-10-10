"""The labelled sheets and the scoring that reads them back."""

import json

import pandas as pd
import pytest


def test_a_proportion_carries_its_interval_and_a_small_n_shows_it():
    from src.eval.score import interval, prf

    assert interval(8, 10).startswith("0.80 [")
    # The same proportion on a tenth of the data is reported far less certainly.
    wide = interval(8, 10)
    narrow = interval(80, 100)
    span = lambda s: float(s.split("[")[1].split(",")[1].strip(" ]")) - float(s.split("[")[1].split(",")[0])
    assert span(wide) > span(narrow) * 2
    assert interval(0, 0) == "n/a"
    assert "F1 0.80" in prf(8, 2, 2)


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
    sheets._write(tmp_path, "1-relevance", sheet, k, "a note")
    back = pd.read_excel(tmp_path / "1-relevance.xlsx", sheet_name="rows",
                         dtype=str, keep_default_na=False)
    assert (back["relevant"] == "").all() and "app_said" not in back.columns
    start = pd.read_excel(tmp_path / "1-relevance.xlsx", sheet_name="start here")
    assert "minutes" in start.columns[0]
    assert json.loads((tmp_path / "1-relevance-key.json").read_text(encoding="utf-8"))[0]["app_said"] is True


def test_the_strata_cover_the_month_and_their_weights_put_it_back():
    """
    A weighted estimate is only unbiased if every article sat in exactly one
    stratum and each stratum's weight is its population over its sample. The
    three strata are: what the app kept, and the two halves of what it
    rejected, split by a rule applied to every rejected article.
    """
    from src.eval import sheets

    month, kept = 2135, 236
    named_pop, other_pop = 442, 1457
    assert kept + named_pop + other_pop == month, "the strata must partition the month"

    named_n = min(sheets.N_NAMED_REJECT, named_pop)
    other_n = min(sheets.N_OTHER_REJECT, other_pop)
    weights = {"kept": 1.0, "named": named_pop / named_n, "other": other_pop / other_n}
    # Weighting the sample back reconstructs the month, which is the property
    # that makes recall an estimate of the month rather than of the sheet.
    back = kept * weights["kept"] + named_n * weights["named"] + other_n * weights["other"]
    assert back == pytest.approx(month, abs=1)
    # Misses hide where names are, so that stratum is sampled harder: a row
    # drawn from it stands for fewer articles than one drawn from the other.
    assert weights["named"] < weights["other"]


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
