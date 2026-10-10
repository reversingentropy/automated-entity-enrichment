"""
Score the labelled sheets against the key held back from them.

    python -m src.eval score data/eval/returned

Each sheet gives precision, recall and F1 with a 95% interval, and the
figures the evaluation doc promises: relevance by language with the
sampling weights applied, matching by script with the "cannot tell" rate,
extraction by language and type with the per-field error count. Where two
people labelled the same row, agreement (Cohen's kappa) is reported; where
they disagree, the row is listed rather than averaged away.
"""

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

TRUE = {"TRUE", "T", "Y", "YES", "1"}
FALSE = {"FALSE", "F", "N", "NO", "0"}
UNSURE = {"?", "UNSURE", "NOT SURE", "MAYBE"}


def interval(hits: float, total: float) -> str:
    """A 95% interval on a proportion, wide when the count is small, and said so."""
    if not total:
        return "n/a"
    p = hits / total
    half = 1.96 * math.sqrt(max(p * (1 - p), 1e-9) / total)
    return f"{p:.2f} [{max(p - half, 0):.2f}, {min(p + half, 1):.2f}]"


def prf(tp: float, fp: float, fn: float) -> str:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return (f"P {interval(tp, tp + fp)}   R {interval(tp, tp + fn)}   F1 {f:.2f}"
            f"   (tp {tp:.0f} fp {fp:.0f} fn {fn:.0f})")


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


def relevance(folder: Path, key_dir: Path) -> None:
    sheets = _returned(folder, "1-relevance")
    if not sheets:
        return
    key = {r["url"]: r for r in json.loads((key_dir / "1-relevance-key.json").read_text(encoding="utf-8"))}
    print("\nRELEVANCE")
    # One label per row: the first person to mark it. Disagreements are listed
    # by _agreement rather than resolved here.
    label, lang = {}, {}
    for _, df in sheets:
        for row in df.itertuples():
            m = _mark(getattr(row, "relevant", ""))
            if m and row.url not in label:
                label[row.url] = m == "Y"
                lang[row.url] = "zh" if row.source == "zb" else "en"
    done = [u for u in label if u in key]
    print(f"  labelled {len(done)} of {len(key)} rows")
    # What each stratum contributed, printed so the weighting can be checked.
    from collections import defaultdict as _dd
    counted = _dd(lambda: [0, 0, 0.0])          # rows, misses found, weight
    for u in done:
        k = key[u]
        seen = counted[k["stratum"]]
        seen[0] += 1
        seen[1] += bool(label[u] and not k["app_said"])
        seen[2] = k["weight"]
    for stratum, (rows, misses, w) in sorted(counted.items()):
        print(f"    {stratum:30} {rows:4} rows, each standing for {w:5.2f}; "
              f"{misses} the app should have kept")

    for name, keep in (("overall", lambda u: True), ("english", lambda u: lang[u] == "en"),
                       ("chinese", lambda u: lang[u] == "zh")):
        tp = fp = fn = 0.0
        found = 0
        for u in done:
            k = key[u]
            w = k["weight"] or 0.0
            if not keep(u):
                continue
            app, human = k["app_said"], label[u]
            if app and human:
                tp += w
            elif app and not human:
                fp += w
            elif human and not app:
                fn += w
                found += 1
        # Precision is a census of what the app called relevant, so its
        # interval is the plain one. Recall is weighted, and a single labelled
        # miss stands for several articles, so its interval is computed on the
        # rows actually labelled rather than on the weighted total, which
        # would claim a precision the sample does not have.
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        n_p = sum(1 for u in done if key[u]["app_said"] and keep(u))
        n_r = n_p + found
        print(f"  {name:8} P {interval(round(p * n_p), n_p)}   "
              f"R {interval(round(r * n_r), n_r)}   F1 {f1:.2f}   "
              f"(weighted: caught {tp:.0f}, missed {fn:.0f}; misses labelled {found})")

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
    for name, keep in (("overall", lambda p: True), ("latin", lambda p: key[p]["script"] == "latin"),
                       ("chinese", lambda p: key[p]["script"] == "chinese")):
        tp = fp = fn = 0
        for p in done:
            if label[p] == "?" or not keep(p):
                continue
            app, human = key[p]["app_said_same"], label[p] == "Y"
            tp += app and human
            fp += app and not human
            fn += human and not app
        print(f"  {name:8} {prf(tp, fp, fn)}")
    _agreement(sheets, "id", "same", "proposal")


def extraction(folder: Path, key_dir: Path) -> None:
    sheets = _returned(folder, "3-extraction")
    if not sheets:
        return
    print("\nEXTRACTION")
    verdicts, missed, fielderr = {}, defaultdict(set), Counter()
    langs = {}
    for _, df in sheets:
        for row in df.itertuples():
            ent = (getattr(row, "entity", "") or "").strip()
            art = getattr(row, "article_url", "")
            v = (getattr(row, "verdict", "") or "").strip().lower()
            if ent and v:
                verdicts.setdefault((art, ent), v)
                langs[(art, ent)] = getattr(row, "language", "en")
                for f in (getattr(row, "field_errors", "") or "").replace(";", ",").split(","):
                    if f.strip():
                        fielderr[f.strip()] += 1
            for m in (getattr(row, "missed", "") or "").splitlines():
                if m.strip():
                    missed[art].add(m.strip())
    n_missed = sum(len(v) for v in missed.values())
    print(f"  entities marked {len(verdicts)}, names reported missing {n_missed}")
    for name, keep in (("overall", lambda k: True), ("english", lambda k: langs[k] == "en"),
                       ("chinese", lambda k: langs[k] == "zh")):
        ok = sum(1 for k, v in verdicts.items() if v == "ok" and keep(k))
        bad = sum(1 for k, v in verdicts.items() if v in ("wrong", "not_worth") and keep(k))
        miss = n_missed if name == "overall" else sum(
            len(v) for a, v in missed.items()
            if any(keep(k) for k in verdicts if k[0] == a))
        print(f"  {name:8} {prf(ok, bad, miss)}")
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
    print("\nIntervals are 95%. A wide one means the sheet was small, not that the "
          "system is uncertain.")
    return 0
