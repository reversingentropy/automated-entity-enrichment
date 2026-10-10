"""
The pipeline stage by stage, on the same entities, with the same question at each stage: what the stored model decided, and what jev (and code) would decide.

    .venv/bin/python scripts/jev_same_entities.py

Population: the 2,281 stored resolutions in the held-out half (odd extracted ids), the half never used to set jev's cut-offs. Every stage is run on
its own on those same entities, so each row compares like with like. Nothing here is a measure of accuracy: "Now" is what the pipeline's stored
answers say (the nightly Gemini pipeline for 10%, the archive's internal model for 90%), and jev is judged only by how it differs from them.

  1 relevance     entities whose article jev keeps (flow-full2.csv, jev's relevance score); Now is 100 by construction, since every stored
                  entity comes from an article the model passed
  2 extraction    the same stored extraction in both; jev only checks the entity type (96 in 100 agree, PIPELINE-REPORT.md)
  3 retrieval     entities with at least one candidate record (code, identical in both)
  4 resolution    same record / new / unsure: the stored answer against jev's identity call plus "no candidate" (as fair_funnel in jev_fair.py)
  5 changes       entities with at least one change: the stored model's proposals against the changes jev's flow writes (flow-full.csv)
  6 a person      entities with something for a person to decide (a change, a new record or a flag) against none
"""

import csv
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jev_fair as F  # noqa: E402
import jev_pipeline as P  # noqa: E402
import jev_replay as J  # noqa: E402

OUT = J.OUT
REL_STRICT, REL_LOOSE = 0.53, 0.23


def live_relevance():
    """Articles, not entities: the live feed's articles, judged by the nightly pipeline's model (the labels) and by jev, at the cut-off that keeps
    95 in 100 of the relevant ones on the validation articles (chosen there, as in jev_pipeline.relevance_report)."""
    ans = P.load_answers(OUT / "relevance-A.jsonl")
    sets = P.relevance_sets()

    def scored(name):
        rows = [r for r in sets[name] if f"{name}:{r['url']}" in ans]
        return np.array([ans[f"{name}:{r['url']}"]["relevant"]["noul"] for r in rows]), np.array([r["label"] for r in rows]), rows

    vs, vy, _ = scored("val")
    cut = max((t for t in np.unique(np.round(vs, 3)) if P.prf(vy, vs, t)[1] >= 0.95), default=0.0)
    s, y, rows = scored("live")
    kept = s >= cut
    days = sorted(r["day"] for r in rows)
    return {"n": len(rows), "model_kept": int(y.sum()), "jev_kept": int(kept.sum()), "jev_catches": int((kept & (y == 1)).sum()), "cut": float(cut), "from": days[0], "to": days[-1]}


def numbers():
    snap = J.snapshot()
    held = [r for r in snap if F.half(r["extracted_id"]) == "held"]
    ids = {r["extracted_id"] for r in held}
    n = len(held)
    f2 = {int(r["extracted_id"]): r for r in csv.DictReader(open(OUT / "flow-full2.csv", encoding="utf-8-sig"))}
    f1 = {int(r["extracted_id"]): r for r in csv.DictReader(open(OUT / "flow-full.csv", encoding="utf-8-sig"))}
    matched = {m["extracted_id"]: m for m in json.loads((OUT / "matched.json").read_text(encoding="utf-8"))}
    rel = {e: float(f2[e]["relevance"]) for e in ids if f2[e]["relevance"]}
    stored = Counter("same" if r["gemini"] == "MATCH_AND_UPDATE" else "new" if r["gemini"] == "CREATE_NEW" else "unsure" for r in held)

    # jev's identity call, exactly as fair_funnel: cut-offs tuned on the other half
    dev, hold = F.id_rows("dev"), F.id_rows("held")
    hi, lo = F.tune_cutoffs(F.id_best("u", dev), dev)
    best = F.id_best("u", hold)
    jev = Counter()
    for r in held:
        if not r["candidates"]:
            jev["new"] += 1
            continue
        p = best.get(r["extracted_id"])
        if p is None:
            continue
        jev["new" if p <= lo else "unsure" if p < hi else "same"] += 1

    changes_stored = sum(1 for e in ids if e in matched and matched[e]["field_updates"])
    changes_jev = sum(1 for e in ids if e in f1 and f1[e]["applied"])
    desk = stored["new"] + stored["unsure"] + changes_stored
    out = {"n": n,
           "relevance": (100.0, sum(v >= REL_STRICT for v in rel.values()) / n * 100, sum(v >= REL_LOOSE for v in rel.values()) / n * 100),
           "candidates": sum(1 for r in held if r["candidates"]) / n * 100,
           "resolution_now": tuple(stored[k] / n * 100 for k in ("same", "new", "unsure")),
           "resolution_jev": tuple(jev[k] / n * 100 for k in ("same", "new", "unsure")),
           "changes": (changes_stored / n * 100, changes_jev / n * 100),
           "desk": desk / n * 100}
    return out


if __name__ == "__main__":
    o = numbers()
    n = o["n"]
    print(f"{n:,} held-out stored entities, per 100, each stage on its own\n")
    lr = live_relevance()
    print(f"0 relevance on articles: live feed {lr['from']} to {lr['to']}, {lr['n']:,} articles; the model kept {lr['model_kept']}; jev at {lr['cut']} kept {lr['jev_kept']} and caught {lr['jev_catches']} of the model's {lr['model_kept']}")
    print(f"1 relevance: kept   now 100 | jev {o['relevance'][1]:.0f} at {REL_STRICT}, {o['relevance'][2]:.0f} at {REL_LOOSE}")
    print(f"2 extraction: same entities in both")
    print(f"3 retrieval: with a candidate record {o['candidates']:.0f} in both (code)")
    print("4 resolution (same / new / unsure): now {:.0f} / {:.0f} / {:.0f} | jev {:.0f} / {:.0f} / {:.0f}".format(*o["resolution_now"], *o["resolution_jev"]))
    print(f"5 changes: entities with a change: now {o['changes'][0]:.0f} proposed | jev {o['changes'][1]:.0f} written")
    print(f"6 a person: entities with something to decide: now {o['desk']:.0f} | jev 0")
