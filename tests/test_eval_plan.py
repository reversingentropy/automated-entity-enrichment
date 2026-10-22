"""The evaluation's maths (src/eval/plan.py): the sizes, the ranges, and the check that they hold the truth."""

import math

import pytest

from src.eval import plan


def test_rows_are_shared_between_years_in_proportion_and_add_up():
    got = plan.allocate({"2015": 1000, "2016": 2000, "2017": 7000}, 100)
    assert got == {"2015": 10, "2016": 20, "2017": 70}
    odd = plan.allocate({"a": 1, "b": 1, "c": 1}, 2)
    assert sum(odd.values()) == 2 and max(odd.values()) == 1
    # never more than a group holds; a small population is taken whole
    assert plan.allocate({"a": 3, "b": 4}, 50) == {"a": 3, "b": 4}


def test_the_usual_margin_is_the_textbook_one():
    assert plan.margin(0.5, 385) == pytest.approx(0.05, abs=0.0005)
    assert plan.margin(0.8, 200) == pytest.approx(0.0554, abs=0.0005)


def test_no_hits_still_leaves_a_range_above_nothing():
    """Zero misses in 300 rows does not prove the AI never misses: the range says how many it could be."""
    p, lo, hi = plan.share(0, 300)
    assert p == 0 and lo >= 0 and 0.005 < hi < 0.015


def test_a_miss_in_a_large_group_costs_more_recall_than_one_in_a_small_group():
    kept = (1000, 100, 80)
    small = plan.recall(kept, [(500, 100, 1)])
    large = plan.recall(kept, [(50_000, 100, 1)])
    assert large[0] < small[0]
    assert large[1] <= large[0] <= large[2] and small[1] <= small[0] <= small[2]
    # found 800, missed 5 or 500
    assert small[0] == pytest.approx(800 / 805) and large[0] == pytest.approx(800 / 1300)


def test_names_in_one_article_count_as_one_draw_not_many():
    """Ten articles, each all right or all wrong: the range is as wide as ten draws allow, not a hundred."""
    articles = [{"group": "en", "weight": 1.0, "ok": 10 if i % 2 else 0, "bad": 0 if i % 2 else 10, "missed": 0}
                for i in range(10)]
    p, lo, hi = plan.by_article(articles)["precision"]
    assert p == pytest.approx(0.5)
    as_if_names = plan.margin(0.5, 100)
    assert (hi - lo) / 2 > 2 * as_if_names


def test_each_article_counts_by_what_it_stands_for():
    articles = [{"group": "zh", "weight": 10.0, "ok": 1, "bad": 1, "missed": 0},
                {"group": "en", "weight": 30.0, "ok": 2, "bad": 0, "missed": 2}]
    got = plan.by_article(articles)
    assert got["precision"][0] == pytest.approx((10 + 60) / (20 + 60))
    assert got["recall"][0] == pytest.approx((10 + 60) / (10 + 60 + 60))
    assert all(math.isnan(x) for x in plan.by_article([])["precision"])


def test_the_ranges_hold_the_truth_about_95_times_in_100():
    """
    The sheets drawn again and again from a made-up population whose answers are known, the way sheets.py
    draws them, and scored the way score.py scores them: each score is right on average, and its 95% range
    holds the true value about 95 times in 100. This is the check the Evaluation page quotes.
    """
    for r in plan.check(sims=300, redraws=500):
        name = f"{r['sheet']} {r['measure']}"
        assert abs(r["off"]) < 0.01, name
        assert 0.90 <= r["inside"] <= 0.99, (name, r["inside"])


def test_the_shared_rows_fit_inside_each_sheet():
    for sheet, n in plan.SHARED.items():
        assert 0 < n < sum(plan.SIZES[sheet].values())
