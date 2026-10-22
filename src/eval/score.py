"""
Score the labelled sheets against the key held back from them.

    python -m src.eval score data/eval/returned

Each sheet gives precision, recall and F1, each with a 95% range worked out as src/eval/plan.py sets
down: relevance and matching with each group scaled up to its size by the rows' weights, extraction
article by article, since the names in one article are right or wrong together. Then the figures the
evaluation doc promises: relevance by language, matching by script with the "cannot tell" rate,
extraction by language with the per-field error count. Where two people labelled the same row,
agreement (Cohen's kappa) is reported; where they disagree, the row is listed rather than averaged away.
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from src.eval.online import lang_of
from src.eval.plan import by_article, recall, share

TRUE = {"TRUE", "T", "Y", "YES", "1"}
FALSE = {"FALSE", "F", "N", "NO", "0"}
UNSURE = {"?", "UNSURE", "NOT SURE", "MAYBE"}


def ranged(t: tuple[float, float, float]) -> str:
    """A score and its 95% range, as 0.80 [0.74, 0.85]."""
    v, lo, hi = t
    return "n/a" if v != v else f"{v:.2f} [{lo:.2f}, {hi:.2f}]"


def pr(p: tuple, r: tuple) -> str:
    """Precision and recall, each with its range, and F1."""
    f1 = 2 * p[0] * r[0] / (p[0] + r[0]) if p[0] == p[0] and r[0] == r[0] and p[0] + r[0] else 0.0
    return f"P {ranged(p)}   R {ranged(r)}   F1 {f1:.2f}"


def kappa(a: list, b: list) -> float:
    """Cohen's kappa over the rows two people both labelled."""
    if not a:
        return float("nan")
    n = len(a)
    agree = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    chance = sum((ca[k] / n) * (cb[k] / n) for k in set(ca) | set(cb))
    return (agree - chance) / (1 - chance) if chance < 1 else float("nan")


def _mark(value: str) -> str | None:
    v = str(value).strip().upper()
    if v in TRUE:
        return "Y"
    if v in FALSE:
        return "N"
    if v in UNSURE:
        return "?"
    return None


def _returned(folder: Path, stem: str) -> list[tuple[str, pd.DataFrame]]:
    """Every copy of one sheet that came back, by whoever's name is on the file."""
    out = []
    for path in sorted(folder.glob(f"{stem}*.xlsx")):
        try:
            df = pd.read_excel(path, sheet_name="rows", dtype=str, keep_default_na=False)
        except ValueError:
            continue
        who = re.sub(rf"^{stem}[-_ ]*", "", path.stem) or path.stem
        out.append((who, df))
    return out


def _agreement(sheets, join, column, label):
    """Kappa over rows more than one person marked, and the rows they split on."""
    marks = defaultdict(dict)
    for who, df in sheets:
        for row in df.itertuples():
            m = _mark(getattr(row, column, ""))
            if m:
                marks[getattr(row, join)][who] = m
    shared = {k: v for k, v in marks.items() if len(v) > 1}
    if not shared:
        return
    people = sorted({w for v in shared.values() for w in v})
    pairs = [(x, y) for i, x in enumerate(people) for y in people[i + 1:]]
    for x, y in pairs:
        both = [(v[x], v[y]) for v in shared.values() if x in v and y in v]
        if len(both) < 5:
            continue
        k = kappa([a for a, _ in both], [b for _, b in both])
        split = sum(1 for a, b in both if a != b)
        print(f"  agreement {x} vs {y}: kappa {k:.2f} over {len(both)} shared rows, {split} disagreed")
    for key, v in shared.items():
        if len({*v.values()}) > 1:
            print(f"    split on {label} {key}: " + ", ".join(f"{w}={m}" for w, m in v.items()))


def _groups(key: dict, label: dict, keep, said, yes) -> tuple[list, list[list]]:
    """
    What the app said yes to, and each group of what it said no to, as recall() takes them: [size, rows
    labelled, rows labelled yes]. A group's size is its rows' weights added up: each row stands for that many.
    """
    kept, dropped = [0.0, 0, 0], defaultdict(lambda: [0.0, 0, 0])
    for k, row in key.items():
        if not keep(k):
            continue
        t = kept if said(row) else dropped[row.get("stratum") or row.get("side") or "rejected"]
        t[0] += row.get("weight") or 1.0
        if k in label and label[k] is not None:
            t[1] += 1
            t[2] += yes(label[k])
    return kept, list(dropped.values())


def relevance(folder: Path, key_dir: Path) -> None:
    sheets = _returned(folder, "1-relevance")
    if not sheets:
        return
    key = {r["url"]: r for r in json.loads((key_dir / "1-relevance-key.json").read_text(encoding="utf-8"))}
    print("\nRELEVANCE")
    # One label per row: the first person to mark it. Disagreements are listed
    # by _agreement rather than resolved here.
    label = {}
    for _, df in sheets:
        for row in df.itertuples():
            m = _mark(getattr(row, "relevant", ""))
            if m and row.url not in label:
                label[row.url] = m == "Y"
    done = [u for u in label if u in key]
    print(f"  labelled {len(done)} of {len(key)} rows")
    # What each group contributed, printed so the weighting can be checked.
    drawn, size, seen = Counter(), Counter(), defaultdict(lambda: [0, 0])
    for u, k in key.items():
        drawn[k["stratum"]] += 1
        size[k["stratum"]] += k.get("weight") or 1.0
    for u in done:
        seen[key[u]["stratum"]][0] += 1
        seen[key[u]["stratum"]][1] += bool(label[u] and not key[u]["app_said"])
    for stratum, (rows, misses) in sorted(seen.items()):
        print(f"    {stratum:30} {rows:4} rows, each standing for about {size[stratum] / drawn[stratum]:,.0f}; "
              f"{misses} the app should have kept")

    for name, keep in (("overall", lambda u: True), ("english", lambda u: lang_of(u) == "en"),
                       ("chinese", lambda u: lang_of(u) == "zh")):
        kept, dropped = _groups(key, label, keep, lambda k: k["app_said"], bool)
        if not kept[1]:
            continue
        print(f"  {name:8} {pr(share(kept[2], kept[1]), recall(tuple(kept), [tuple(g) for g in dropped]))}"
              f"   (misses labelled {sum(g[2] for g in dropped)})")

    examples = [u for u in done if label[u] and not key[u]["app_said"]]
    if examples:
        print(f"  articles the app rejected and a labeller kept: {len(examples)}")
        for u in examples[:10]:
            print(f"    {u}")
    _agreement(sheets, "url", "relevant", "url")


def matching(folder: Path, key_dir: Path) -> None:
    sheets = _returned(folder, "2-matching")
    if not sheets:
        return
    key = {int(r["id"]): r for r in json.loads((key_dir / "2-matching-key.json").read_text(encoding="utf-8"))}
    print("\nMATCHING")
    label = {}
    for _, df in sheets:
        for row in df.itertuples():
            m = _mark(getattr(row, "same", ""))
            pid = int(row.id)
            if m and pid not in label:
                label[pid] = m
    done = [p for p in label if p in key]
    unsure = sum(1 for p in done if label[p] == "?")
    print(f"  labelled {len(done)} of {len(key)} rows; cannot tell: {unsure} "
          f"({100 * unsure / max(len(done), 1):.0f}%)")
    # "Cannot tell" is reported above and left out of precision and recall.
    sure = {p: m for p, m in label.items() if m != "?"}
    for name, keep in (("overall", lambda p: True), ("latin", lambda p: key[p]["script"] == "latin"),
                       ("chinese", lambda p: key[p]["script"] == "chinese")):
        kept, dropped = _groups(key, sure, keep, lambda k: k["app_said_same"], lambda m: m == "Y")
        if not kept[1]:
            continue
        print(f"  {name:8} {pr(share(kept[2], kept[1]), recall(tuple(kept), [tuple(g) for g in dropped]))}")
    _agreement(sheets, "id", "same", "proposal")


def extraction(folder: Path, key_dir: Path) -> None:
    sheets = _returned(folder, "3-extraction")
    if not sheets:
        return
    print("\nEXTRACTION")
    path = key_dir / "3-extraction-key.json"
    weight = {r["article_url"]: r.get("weight") or 1.0
              for r in (json.loads(path.read_text(encoding="utf-8")) if path.exists() else []) if r.get("article_url")}
    # Each article as its first labeller marked it: their verdicts and their missed names.
    owner = {}
    for who, df in sheets:
        for row in df.itertuples():
            if (getattr(row, "verdict", "") or "").strip() or (getattr(row, "missed", "") or "").strip():
                owner.setdefault(getattr(row, "article_url", ""), who)
    verdicts, missed, fielderr, arts = {}, defaultdict(set), Counter(), {}
    for who, df in sheets:
        for row in df.itertuples():
            art = getattr(row, "article_url", "")
            if owner.get(art) != who:
                continue
            a = arts.setdefault(art, {"group": getattr(row, "language", "en") or "en", "weight": weight.get(art, 1.0),
                                      "ok": 0, "bad": 0, "missed": 0})
            ent = (getattr(row, "entity", "") or "").strip()
            v = (getattr(row, "verdict", "") or "").strip().lower()
            if ent and v and (art, ent) not in verdicts:
                verdicts[(art, ent)] = v
                a["ok" if v == "ok" else "bad"] += 1
                for f in (getattr(row, "field_errors", "") or "").replace(";", ",").split(","):
                    if f.strip():
                        fielderr[f.strip()] += 1
            for m in (getattr(row, "missed", "") or "").splitlines():
                if m.strip() and m.strip() not in missed[art]:
                    missed[art].add(m.strip())
                    a["missed"] += 1
    n_missed = sum(len(v) for v in missed.values())
    print(f"  entities marked {len(verdicts)}, names reported missing {n_missed}")
    for name, keep in (("overall", lambda a: True), ("english", lambda a: a["group"] == "en"),
                       ("chinese", lambda a: a["group"] == "zh")):
        rows = [a for a in arts.values() if keep(a)]
        if not rows:
            continue
        got = by_article(rows)
        print(f"  {name:8} {pr(got['precision'], got['recall'])}   ({len(rows)} articles)")
    kinds = Counter(v for v in verdicts.values())
    print(f"  verdicts: " + ", ".join(f"{k} {n}" for k, n in kinds.most_common()))
    if fielderr:
        print("  wrong field values: " + " · ".join(f"{f} {n}" for f, n in fielderr.most_common(8)))
    _agreement(sheets, "entity", "verdict", "entity")


def report(folder: str | Path, key_dir: str | Path | None = None) -> int:
    folder = Path(folder)
    key_dir = Path(key_dir) if key_dir else folder.parent
    if not folder.exists():
        print(f"Nothing at {folder}. Put the returned .xlsx files there.")
        return 1
    print(f"Scoring the sheets in {folder} against the key in {key_dir}")
    relevance(folder, key_dir)
    matching(folder, key_dir)
    extraction(folder, key_dir)
    print("\nRanges are 95%: the true value lies inside about 95 times in 100 "
          "(python -m src.eval check). A wide one means few rows, not an unsure system.")
    return 0
