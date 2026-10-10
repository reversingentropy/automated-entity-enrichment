"""
A sheet of what the fully automated flow decided (scripts/jev_flow.py full), for a person to judge: would you accept this outcome?
Stratified so that the new-record decisions, where no rule exists, cover the whole range of jev's notability score. The score is not shown,
so the answers can later be used to calibrate the cut-off. Writes data/jev/flow-sample.md and flow-sample-key.json.

    .venv/bin/python scripts/jev_flow_sheet.py
"""
import html
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jev_fair as F
import jev_flow as L
import jev_replay as J

OUT = J.OUT


def main():
    rng = random.Random(23)
    snap, res = L.full()
    cx = F.context()
    matched = {m["extracted_id"]: m for m in json.loads((OUT / "matched.json").read_text(encoding="utf-8"))}
    band = lambda v: 0 if v < 0.1 else (1 if v < 0.3 else (2 if v < 0.5 else (3 if v < 0.8 else 4)))
    notes = [(e, x) for e, x in res.items() if x["notability"] is not None]
    picks = []
    for b, n in ((0, 4), (1, 4), (2, 4), (3, 4), (4, 4)):
        pool = [e for e, x in notes if band(x["notability"]) == b and snap[e]["summary"] and snap[e]["summary"].strip().lower() != "test"]
        picks += rng.sample(pool, min(n, len(pool)))
    drops = [e for e, x in res.items() if x["outcome"] == "not worth a record" and snap[e]["gemini"] == "MATCH_AND_UPDATE"]
    picks += rng.sample(drops, min(5, len(drops)))                                    # Gemini matched it, the flow discards it
    amended = [e for e, x in res.items() if x["outcome"] == "amended" and x["applied"]]
    picks += rng.sample(amended, 8)
    withheld = [e for e, x in res.items() if x["left_out"] and x["outcome"] in ("same", "amended")]
    picks += rng.sample(withheld, 6)
    seen = set(); picks = [e for e in picks if not (e in seen or seen.add(e))]
    rng.shuffle(picks)

    from src.shared.supabase_client import get_client
    cl = get_client()
    aids = list({cx[e]["article_id"] for e in picks})
    urls = {a["id"]: a["url"] for a in cl.from_("article").select("id,url").in_("id", aids).execute().data}
    md = [f"# {len(picks)} decisions the fully automated flow made: would you accept each?", "",
          "No person reviewed these. For each, read what the flow decided and say whether you would accept it. Open the article link when in doubt.", ""]
    key = {}
    for i, e in enumerate(picks, 1):
        r, x = snap[e], res[e]
        cid = f"a{i:02d}"
        md += [f"## {cid}: {r['name_en'] or r['name']}" + (f" ({r['name']})" if r["name_en"] and r["name_en"] != r["name"] else "") + f"  ·  {J.KIND.get(r['type'], r['type'].lower())}", "",
               f"*{r['published']}* · [{html.unescape(r['title'])}]({urls.get(cx[e]['article_id'], '')})", "", f"**What the pipeline pulled from the article:** {r['summary']}", ""]
        q = r["quote_en"] or (r["quote"] if not J.non_latin(r["quote"]) else "")
        md += ([f"> {q}", ""] if q else [])
        o = x["outcome"]
        fields = F.whole(cx.get(e, {}).get("fields"))
        if o in ("to create", "not worth a record"):
            near = r["candidates"][0]["canonical_name"] if r["candidates"] else "none"
            md += [f"**Flow's decision: {'CREATE A NEW RECORD' if o == 'to create' else 'DO NOT CREATE A RECORD (not worth one)'}**", "",
                   "What it would be built from: " + "; ".join(f"{k}: {str(v)[:160]}" for k, v in fields.items() if k not in ("Name",) )[:520], "", f"Closest existing record: {near}", "",
                   "**Your verdict:**  [ ] right   [ ] wrong: it should be the other way   [ ] it already has a record   [ ] cannot tell", ""]
        else:
            m = matched.get(e)
            cand = next((c for c in m["candidates"] if c["canonical_uid"] == r["gemini_uid"]), None) if m else None
            md += [f"**Flow's decision: {o.upper()}** on record **{cand['canonical_name'] if cand else '?'}**", ""]
            for u in (m["field_updates"] if m else []):
                st = "WRITTEN" if u["field"] in x["applied"] else ("LEFT OUT" if u["field"] in x["left_out"] else "not proposed by the flow")
                md.append(f"- **{u['field']}** ({u['strategy'].lower()}) {st}: _{u['value'][:260]}_")
            extra = [f for f in x["applied"] if f not in {u['field'] for u in (m['field_updates'] if m else [])}]
            md += ([f"- the flow also WROTE (Gemini had not proposed): {', '.join(extra)}"] if extra else []) + [""]
            md += ["**Your verdict:**  [ ] right   [ ] wrong record   [ ] a written change is wrong   [ ] a left-out change should have been written   [ ] cannot tell", ""]
        md += ["---", ""]
        key[cid] = {"extracted_id": e, "outcome": o, "notability": x["notability"], "applied": x["applied"], "left_out": x["left_out"], "gemini": r["gemini"]}
    (OUT / "flow-sample.md").write_text("\n".join(md), encoding="utf-8")
    (OUT / "flow-sample-key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT / 'flow-sample.md'} ({len(picks)} decisions)")


if __name__ == "__main__":
    main()
