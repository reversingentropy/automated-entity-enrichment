"""
Build the audit page: cards that both Gemini and jev would let through, for a person to check.

    .venv/bin/python scripts/jev_audit.py          # writes data/jev/audit.html and data/jev/audit-key.json

The question the page answers: if cards like these were applied with nobody checking, how often would one be wrong?

A card is "auto-approvable" when all of these hold (nothing here is tuned on human answers, there are none yet):
  - Gemini matched the entity to a record (MATCH_AND_UPDATE);
  - jev, asked as one multiple-choice question over the candidates, picks the same record with at least 90% probability,
    and picks it again with the options in the opposite order;
  - every change Gemini proposed is judged by jev to be supported by the article's quote.
It samples 100 cards with changes and 50 with no change, plus 10 "planted" cards where the models disagree, mixed in without
a label, so the person can be seen to catch (or miss) the kind of error jev flags. The page shows no model verdicts.
The key (which card is which, and what the models said) is written separately and is not in the page's visible text.
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jev_fair as F
import jev_pipeline as P
import jev_replay as J
from src.export import cards

OUT = J.OUT
SEED = 42
SHOW_ORDER = ["Occupation", "Title", "Nationality", "Birth Year (yyyy)", "Death Year (yyyy)", "Country", "Affiliations(groupName)", "Education", "Awards", "Parent Organisation", "Founder", "Year Started (yyyy)"]


def chip(v, n=200):
    v = " ".join(str(v).split())
    return v if len(v) <= n else v[:n].rsplit(" ", 1)[0] + "…"


def main():
    rng = random.Random(SEED)
    snap = {r["extracted_id"]: r for r in J.snapshot()}
    dec = F.listwise_decisions()
    cx = F.context()
    matched = {m["extracted_id"]: m for m in json.loads((OUT / "matched.json").read_text(encoding="utf-8"))}
    upd = P.load_answers(OUT / "updates.jsonl")

    def verdicts(eid, m):
        return [upd.get(f"{eid}|{u['field']}", {}).get("evidence") for u in m["field_updates"]]

    def agrees(r, eid):
        d = dec.get(eid)
        return bool(d) and d["action"] == "match" and d["top"] == r["gemini_uid"] and d["p"] >= 0.9 and d["stable"]

    changed, nochange = [], []
    for eid, m in matched.items():
        r = snap.get(eid)
        if not r or not m["ext"] or not (r["summary"] or "").strip() or r["summary"].strip().lower() == "test" or not agrees(r, eid):
            continue
        ev = verdicts(eid, m)
        if not m["field_updates"]:
            nochange.append(eid)
        elif all(e and e["choice"] == "supports" for e in ev):
            changed.append(eid)

    contra, ident, nothing = [], [], []
    for eid, m in matched.items():
        r = snap.get(eid)
        if not r or not (r["summary"] or "").strip() or r["summary"].strip().lower() == "test":
            continue
        ev = [e for e in verdicts(eid, m) if e]
        if any(e["choice"] == "contradicts" and e["confidence"] >= 0.5 for e in ev):
            contra.append(eid)
        elif any(e["choice"] == "says_nothing" and e["confidence"] >= 0.9 for e in ev):
            nothing.append(eid)
        d = dec.get(eid)
        if d and (d["action"] != "match" or d["top"] != r["gemini_uid"]) and d["p"] >= 0.6:
            ident.append(eid)

    picked = [(e, "changed") for e in rng.sample(changed, 100)] + [(e, "nochange") for e in rng.sample(nochange, 50)]
    used = {e for e, _ in picked}
    for pool, name, n in ((contra, "control-quote", 5), (ident, "control-id", 3), (nothing, "control-nothing", 2)):
        pool = [e for e in pool if e not in used]
        for e in rng.sample(pool, min(n, len(pool))):
            picked.append((e, name))
            used.add(e)
    rng.shuffle(picked)
    print(f"pools: {len(changed)} with changes, {len(nochange)} without; controls: {len(contra)} quote-contradicts, {len(ident)} identity conflicts, {len(nothing)} quote-says-nothing")

    from src.shared.supabase_client import get_client
    cl = get_client()
    aids = list({cx[e]["article_id"] for e, _ in picked})
    urls = {a["id"]: a["url"] for a in cl.from_("article").select("id,url").in_("id", aids).execute().data}

    out, key = [], {}
    for i, (eid, group) in enumerate(picked, 1):
        r, m = snap[eid], matched[eid]
        cand = next(c for c in m["candidates"] if c["canonical_uid"] == r["gemini_uid"])
        held = cand["canonical_fields"] or {}
        facts = {k: chip(held[k]) for k in SHOW_ORDER if held.get(k)}
        changes = []
        for u in m["field_updates"]:
            have = str(held.get(u["field"]) or "")
            c = {"field": u["field"], "strategy": u["strategy"], "value": u["value"], "have": have if u["strategy"] != "MERGE" else ""}
            if u["strategy"] == "MERGE" and have:
                c["parts"] = cards.diff_parts(have, u["value"])
            changes.append(c)
        cid = f"c{i:03d}"
        out.append({"id": cid, "group": group, "headline": r["title"], "published": r["published"], "url": urls.get(cx[eid]["article_id"], ""),
                    "entity": r["name"], "entityEn": r["name_en"], "type": J.KIND.get(r["type"], r["type"].lower()), "summary": r["summary"],
                    "quote": r["quote_en"] or (r["quote"] if not J.non_latin(r["quote"]) else ""), "original": r["quote"] if J.non_latin(r["quote"]) else "",
                    "record": {"uid": cand["canonical_uid"], "name": cand["canonical_name"], "facts": facts, "description": str(held.get("Description") or "")},
                    "changes": changes})
        d = dec[eid]
        key[cid] = {"extracted_id": eid, "group": group, "gemini_uid": r["gemini_uid"], "jev_top": d["top"], "jev_p": round(d["p"], 3), "jev_stable": d["stable"],
                    "quote_checks": [{"field": u["field"], "choice": e["choice"], "confidence": round(e["confidence"], 2)} if e else {"field": u["field"], "choice": None}
                                     for u, e in zip(m["field_updates"], verdicts(eid, m))]}

    html = (Path(__file__).resolve().parent / "audit_template.html").read_text(encoding="utf-8")
    payload = json.dumps(out, ensure_ascii=False).replace("</", "<\\/")
    (OUT / "audit.html").write_text(html.replace("__CARDS__", payload), encoding="utf-8")
    (OUT / "audit-key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print(f"wrote {OUT / 'audit.html'} with {len(out)} cards: {dict(Counter(g for _, g in picked))}")


if __name__ == "__main__":
    main()
