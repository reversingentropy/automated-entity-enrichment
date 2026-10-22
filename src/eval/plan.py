"""
The evaluation's design and its maths: how many rows each sheet draws and from where, how sure a score
drawn from them is, and the check that the two together give the right answer.

    python -m src.eval check          # the check the Evaluation page's "How this works" quotes

Rows come from every year the AI has handled, each year in proportion to its size (allocate), so no year
counts for more than its share. Where a group is drawn harder than its size, as relevance draws the
headlines the AI dropped, each row carries a weight: how many items like it it stands for.

How sure a score is depends on what it is:
- a share counted on rows, such as precision: Jeffreys' interval, which stays honest when the count is
  small or nil (share);
- recall, which adds up groups of different sizes: each group's share drawn from its own Jeffreys range,
  scaled to the group's size, and the groups combined (recall);
- extraction, where the names in one article are right or wrong together: whole articles redrawn 2,000
  times (by_article).

check() draws sheets from made-up populations whose answers are known, the way sheets.py draws them,
scores them the way score.py does, and counts how often the 95% range held the true value: it should be
about 95 times in 100. tests/test_eval_plan.py runs it on every push.
"""

import math
from statistics import NormalDist

import numpy as np

SEED = 20260824
# Rows drawn per group. Relevance draws harder from what the AI dropped, since what it wrongly dropped is
# rare and hides where a TTE name appears; matching draws as many of its no's as its yes's; extraction as
# many Chinese articles as English ones, so each language can be scored on its own.
SIZES = {
    "relevance": {"kept": 200, "named": 200, "other": 300},
    "matching": {"matched": 150, "rejected": 150},
    "extraction": {"zh": 50, "en": 50},
}
# Rows every labeller is given, for agreement between them (eval_shared() in sql/19_evaluation.sql). Fewer
# for extraction, where a row is a whole article: twenty of those take an hour.
SHARED = {"relevance": 50, "matching": 50, "extraction": 20}
Z = 1.96            # a 95% range
DRAWS = 20_000      # draws from each group's range when combining groups
REDRAWS = 2_000     # redraws of the articles for extraction's range


def margin(p: float, n: int) -> float:
    """Half the width of the usual 95% range on a share p counted on n random rows: 1.96 × √(p(1 − p) / n)."""
    return Z * math.sqrt(p * (1 - p) / n) if n else 1.0


def allocate(sizes: dict, n: int) -> dict:
    """n rows shared between groups in proportion to their sizes; what rounding leaves over goes to the largest fractions."""
    total = sum(sizes.values())
    if total <= n:
        return dict(sizes)
    exact = {k: n * v / total for k, v in sizes.items()}
    out = {k: math.floor(x) for k, x in exact.items()}
    for k in sorted(exact, key=lambda k: out[k] - exact[k])[:n - sum(out.values())]:
        out[k] += 1
    return out


def _jeffreys(hits: int, n: int, rng: np.random.Generator, draws: int = DRAWS) -> np.ndarray:
    """Shares the count could have come from: Beta(hits + ½, n − hits + ½)."""
    return rng.beta(hits + 0.5, n - hits + 0.5, draws)


def share(hits: int, n: int, seed: int = SEED) -> tuple[float, float, float]:
    """A share counted on n rows, and its 95% range."""
    if not n:
        return math.nan, math.nan, math.nan
    lo, hi = np.percentile(_jeffreys(hits, n, np.random.default_rng(seed)), [2.5, 97.5])
    return hits / n, float(lo), float(hi)


def recall(kept: tuple, dropped: list[tuple], seed: int = SEED) -> tuple[float, float, float]:
    """
    Of everything a labeller called a yes, the share the AI said yes to: found / (found + missed), and its
    95% range. Each group is (its size, rows labelled, rows labelled yes): `kept` the group the AI said yes
    to, `dropped` each it said no to. A group's count is scaled up to its size, so a miss found among rows
    that each stand for 600 headlines counts for 600.
    """
    size, n, hits = kept
    dropped = [g for g in dropped if g[1]]
    if not n:
        return math.nan, math.nan, math.nan
    found = size * hits / n
    missed = sum(s * h / k for s, k, h in dropped)
    rng = np.random.default_rng(seed)
    f = size * _jeffreys(hits, n, rng)
    m = sum((s * _jeffreys(h, k, rng) for s, k, h in dropped), np.zeros(DRAWS))
    lo, hi = np.percentile(f / (f + m), [2.5, 97.5])
    return (found / (found + missed) if found + missed else math.nan), float(lo), float(hi)


def by_article(articles: list[dict], seed: int = SEED, redraws: int = REDRAWS) -> dict[str, tuple[float, float, float]]:
    """
    Extraction's precision and recall, each with a 95% range from redrawing whole articles within each
    group. An article is {"group", "weight", "ok", "bad", "missed"}: its names marked OK, its names marked
    wrong or not worth a record, the names it should have had, and how many articles like it it stands for.

    The range is the redraws' middle 95%, corrected for the lean of a count like the missed names, where a
    few articles miss many (Efron's BCa: the bias from where the score falls among its redraws, the lean
    from leaving out one article at a time).
    """
    rng = np.random.default_rng(seed)
    keys = ("ok", "bad", "missed")
    groups: dict[str, list[dict]] = {}
    for a in articles:
        groups.setdefault(a["group"], []).append(a)
    vals = {g: {k: np.array([a["weight"] * a[k] for a in rows], float) for k in keys} for g, rows in groups.items()}
    total = {k: sum(v[k].sum() for v in vals.values()) for k in keys}
    drawn = {k: np.zeros(redraws) for k in keys}
    for g, v in vals.items():
        pick = rng.integers(0, len(groups[g]), (redraws, len(groups[g])))
        for k in keys:
            drawn[k] += v[k][pick].sum(axis=1)
    # each article left out in turn, the rest of its group standing for the whole group
    left = {k: [] for k in keys}
    for g, v in vals.items():
        n = len(groups[g])
        if n < 2:
            continue
        for i in range(n):
            for k in keys:
                left[k].append(total[k] - v[k].sum() + (v[k].sum() - v[k][i]) * n / (n - 1))
    left = {k: np.array(x) for k, x in left.items()}

    out = {}
    for name, rest in (("precision", "bad"), ("recall", "missed")):
        if not total["ok"] + total[rest]:
            out[name] = (math.nan, math.nan, math.nan)
            continue
        point = total["ok"] / (total["ok"] + total[rest])
        with np.errstate(invalid="ignore", divide="ignore"):
            spread = drawn["ok"] / (drawn["ok"] + drawn[rest])
            jack = left["ok"] / (left["ok"] + left[rest])
        spread, jack = spread[np.isfinite(spread)], jack[np.isfinite(jack)]
        out[name] = (point, *_bca(point, spread, jack))
    return out


def _bca(point: float, spread: np.ndarray, jack: np.ndarray) -> tuple[float, float]:
    """The 95% range from redraws, with Efron's bias and acceleration corrections."""
    if not len(spread):
        return math.nan, math.nan
    norm = NormalDist()
    below = np.clip(np.mean(spread < point) + np.mean(spread == point) / 2, 1 / len(spread), 1 - 1 / len(spread))
    z0 = norm.inv_cdf(below)
    d = jack.mean() - jack if len(jack) else np.zeros(1)
    a = (d ** 3).sum() / (6 * (d ** 2).sum() ** 1.5) if (d ** 2).sum() else 0.0
    ends = []
    for q in (0.025, 0.975):
        z = norm.inv_cdf(q)
        ends.append(100 * norm.cdf(z0 + (z0 + z) / (1 - a * (z0 + z))))
    lo, hi = np.percentile(spread, ends)
    return float(lo), float(hi)


# The made-up world check() runs in: groups the size of ours (data/eval/0-sampling.md, 2026-10-22), and
# rates chosen to be hard rather than flattering: misses rare and commoner in some years than others, and
# in extraction whole articles that go well or badly together. Each group: (items, share a labeller says yes).
WORLD = {
    "relevance": {"kept": (27_941, 0.80), "named": (91_182, 0.03), "other": (176_146, 0.005)},
    "matching": {"matched": (2_831, 0.90), "rejected": (643, 0.10)},
    "extraction": {"zh": (2_875, 0.70), "en": (9_818, 0.85)},     # articles; share of their names right
}
YEARS = 12
NAMES = 2.9         # names per article beyond the first, as the archive has them (49,004 in 12,696 articles)
MISSED = 0.6        # names missed per article, on average


def _years(rng, total: int) -> np.ndarray:
    """A group's items split between the years, unevenly."""
    return np.maximum(1, np.round(rng.dirichlet(np.full(YEARS, 8.0)) * total)).astype(int)


def _year_rates(rng, rate: float) -> np.ndarray:
    """The rate from year to year: the rarer side of it as much as 60% higher or lower."""
    swing = rng.uniform(0.4, 1.6, YEARS)
    return rate * swing if rate <= 0.5 else 1 - (1 - rate) * swing


def _cells(rng, total: int, rate: float) -> tuple[np.ndarray, np.ndarray]:
    """A group by year: how many items, and how many of them a labeller would say yes to."""
    sizes = _years(rng, total)
    return sizes, rng.binomial(sizes, _year_rates(rng, rate))


def _draw(rng, sizes: np.ndarray, yes: np.ndarray, n: int) -> tuple[int, int]:
    """Rows drawn from each year as allocate() shares them: how many, and how many of them are yes."""
    got = allocate(dict(enumerate(sizes.tolist())), n)
    return sum(got.values()), int(sum(rng.hypergeometric(yes[y], sizes[y] - yes[y], k) for y, k in got.items() if k))


def _articles(rng, total: int, rate: float) -> dict[str, np.ndarray]:
    """A group of made-up articles: its year, its names, how many are right, and how many it missed."""
    sizes = _years(rng, total)
    year = np.repeat(np.arange(YEARS), sizes)
    names = 1 + rng.poisson(NAMES, len(year))
    mean = np.clip(_year_rates(rng, rate)[year], 0.02, 0.98)
    right = rng.binomial(names, rng.beta(mean * 4, (1 - mean) * 4))
    missed = rng.poisson(rng.gamma(1.0, MISSED, len(year)))
    return {"year": year, "sizes": sizes, "ok": right, "bad": names - right, "missed": missed}


def _tally(sheet: str, measure: str, truth: float, got: list[tuple[float, float, float]]) -> dict:
    est = np.array([g[0] for g in got], float)
    inside = np.mean([lo <= truth <= hi for _, lo, hi in got])
    half = np.nanmean([(hi - lo) / 2 for _, lo, hi in got])
    return {"sheet": sheet, "measure": measure, "truth": truth, "average": float(np.nanmean(est)),
            "off": float(np.nanmean(est) - truth), "inside": float(inside), "margin": float(half), "draws": len(got)}


def check(sims: int = 2000, seed: int = SEED, redraws: int = 1000) -> list[dict]:
    """
    Each sheet drawn `sims` times from one made-up population whose true answers are known, and scored:
    per measure, the true value, the average score, and how often the 95% range held the true value.
    """
    rng = np.random.default_rng(seed)
    out = []

    for sheet, yes_group, no_groups in (("Relevance", "kept", ("named", "other")), ("Matching", "matched", ("rejected",))):
        world = {g: _cells(rng, *WORLD[sheet.lower()][g]) for g in (yes_group, *no_groups)}
        size = {g: int(s.sum()) for g, (s, _) in world.items()}
        yes = {g: int(y.sum()) for g, (_, y) in world.items()}
        truth_p = yes[yes_group] / size[yes_group]
        truth_r = yes[yes_group] / sum(yes.values())
        precision, rec = [], []
        for i in range(sims):
            drawn = {g: _draw(rng, *world[g], SIZES[sheet.lower()][g]) for g in world}
            precision.append(share(drawn[yes_group][1], drawn[yes_group][0], seed=i))
            rec.append(recall((size[yes_group], *drawn[yes_group]),
                              [(size[g], *drawn[g]) for g in no_groups], seed=i))
        out += [_tally(sheet, "precision", truth_p, precision), _tally(sheet, "recall", truth_r, rec)]

    world = {g: _articles(rng, *WORLD["extraction"][g]) for g in WORLD["extraction"]}
    ok = sum(int(w["ok"].sum()) for w in world.values())
    truth_p = ok / (ok + sum(int(w["bad"].sum()) for w in world.values()))
    truth_r = ok / (ok + sum(int(w["missed"].sum()) for w in world.values()))
    precision, rec = [], []
    for i in range(sims):
        articles = []
        for g, w in world.items():
            for y, k in allocate(dict(enumerate(w["sizes"].tolist())), SIZES["extraction"][g]).items():
                if not k:
                    continue
                pool = np.flatnonzero(w["year"] == y)
                for a in rng.choice(pool, k, replace=False):
                    articles.append({"group": g, "weight": len(pool) / k,
                                     "ok": w["ok"][a], "bad": w["bad"][a], "missed": w["missed"][a]})
        got = by_article(articles, seed=i, redraws=redraws)
        precision.append(got["precision"])
        rec.append(got["recall"])
    out += [_tally("Extraction", "precision", truth_p, precision), _tally("Extraction", "recall", truth_r, rec)]
    return out


def main(argv: list[str]) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="python -m src.eval check")
    parser.add_argument("--sims", type=int, default=2000, help="draws of each sheet")
    args = parser.parse_args(argv)
    print(f"Each sheet drawn {args.sims:,} times from a made-up population whose answers are known, and scored.")
    print(f"  {'sheet':10} {'measure':9} {'true':>5} {'average':>7} {'off by':>7} {'range':>7} {'range held the truth':>21}")
    for r in check(args.sims):
        print(f"  {r['sheet']:10} {r['measure']:9} {r['truth']:5.3f} {r['average']:7.3f} {100 * r['off']:+6.1f}pt "
              f"±{100 * r['margin']:4.1f}pt {100 * r['inside']:20.1f}%")
    print("A 95% range should hold the truth about 95 times in 100; 'off by' is the average error, in points.")
    return 0


