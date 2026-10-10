"""
The no-human flow, replayed on the stored data: what would happen to each entity if decisions were made by rules and a decision model
(jev), words were written by Gemini only where text must be written, and nobody reviewed. Nothing is written anywhere; Gemini's stored
answers are reused, so no new Gemini calls and no production change.

    .venv/bin/python scripts/jev_flow.py        # prints the summary, writes data/jev/flow-results.csv

Every entity ends in one of five outcomes (the desk's own: same / amended / to create / not worth / kept for review), split here into
what the flow could settle alone and what it would still hand to a person, with the reason. The rules are the constants below. The identity cut-off (0.9), the
contradiction cut-off and the quote rules were set before the audit. The two "passing detail" cut-offs (0.9 and 0.7) were set AFTER
seeing the audit answers, so the comparison with those answers is in-sample for the description gate and is not a clean test of it.

  identity   jev picks one candidate record, "none" or "unsure" in one multiple-choice question, asked in two option orders
             -> settled alone only when it picks the same record Gemini chose (or "none"), at 90% or more, in both orders
  new record neither model has been tested on notability, and there is no written rule: always handed to a person
  each change from Gemini, in order:
             broken text (an HTML entity in the new text)           -> hand to a person
             the article's quote contradicts it (jev, >= 0.5)        -> leave it out
             the quote says nothing about it, or there is no quote   -> hand to a person
             a description past the guide's 5 sentences              -> hand to a person
             a description change that is a passing detail (jev)     -> leave it out at 0.9 or more, hand to a person at 0.7 or more
"""

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jev_fair as F
import jev_pipeline as P
import jev_replay as J
from src.shared.description import over_limit

OUT = J.OUT
IDENTITY_P = 0.9
CONTRADICTS_P = 0.5
LASTING_LEAVE_OUT, LASTING_HAND_OVER = 0.9, 0.7
ENTITY = re.compile(r"&(amp|lt|gt|quot|#\d+|#x[0-9a-fA-F]+);")


def flow():
    snap = {r["extracted_id"]: r for r in J.snapshot()}
    dec = F.listwise_decisions()
    matched = {m["extracted_id"]: m for m in json.loads((OUT / "matched.json").read_text(encoding="utf-8"))}
    ev = P.load_answers(OUT / "updates.jsonl")
    lasting = P.load_answers(OUT / "audit-lasting.jsonl")
    results = {}
    for eid, r in snap.items():
        reasons, left_out, applied = [], [], 0
        d = dec.get(eid)
        if not r["candidates"] or d is None:
            outcome, reasons = "held", ["new record: no rule for notability"]
        elif d["p"] < IDENTITY_P or not d["stable"]:
            outcome, reasons = "held", ["identity: jev unsure"]
        elif d["action"] != "match":
            outcome, reasons = "held", ["new record: no rule for notability"]
        elif r["gemini"] != "MATCH_AND_UPDATE" or d["top"] != r["gemini_uid"]:
            outcome, reasons = "held", ["identity: the two models disagree"]
        else:
            m = matched[eid]
            held = []
            cand = next(c for c in m["candidates"] if c["canonical_uid"] == r["gemini_uid"])
            for u in m["field_updates"]:
                a = ev.get(f"{eid}|{u['field']}") or {}
                e = a.get("evidence")
                before = str((cand["canonical_fields"] or {}).get(u["field"]) or "")
                if ENTITY.search(u["value"]):
                    held.append("broken text in the new value")
                    continue
                if e is None:
                    held.append("no quote to check the change against")
                    continue
                if e["choice"] == "contradicts" and e["confidence"] >= CONTRADICTS_P:
                    left_out.append(f"{u['field']}: quote contradicts")
                    continue
                if e["choice"] != "supports":
                    held.append("quote does not back the change")
                    continue
                if u["field"] == "Description" and u["strategy"] == "MERGE" and before:
                    if over_limit(before, u["value"]):
                        held.append("description past 5 sentences")
                        continue
                    la = lasting.get(f"all-{eid}")
                    nl = 1 - la["lasting"]["noul"] if la else 0.0
                    if nl >= LASTING_LEAVE_OUT:
                        left_out.append("Description: a passing detail")
                        continue
                    if nl >= LASTING_HAND_OVER:
                        held.append("description may be a passing detail")
                        continue
                applied += 1
            if held:
                outcome, reasons = "held", sorted(set(held))
            elif not m["field_updates"]:
                outcome = "auto: same (nothing to change)"
            elif applied:
                outcome = "auto: amended" + (" (some changes left out)" if left_out else "")
            else:
                outcome = "auto: every change left out"
        results[eid] = {"outcome": outcome, "reasons": reasons, "left_out": left_out, "applied": applied}
    return snap, results


def report():
    snap, res = flow()
    n = len(res)
    auto = [e for e, x in res.items() if x["outcome"].startswith("auto")]
    held = [e for e, x in res.items() if x["outcome"] == "held"]
    print(f"{n:,} entities. With the rules in this file and nobody reviewing:\n")
    print(f"  settled alone: {len(auto) / n * 100:4.1f} in 100")
    for k, v in Counter(res[e]["outcome"] for e in auto).most_common():
        print(f"     {v / n * 100:5.1f}  {k}")
    print(f"  handed to a person: {len(held) / n * 100:4.1f} in 100, by the first reason")
    order = ["identity: jev unsure", "identity: the two models disagree", "new record: no rule for notability", "broken text in the new value", "no quote to check the change against",
             "quote does not back the change", "description past 5 sentences", "description may be a passing detail"]
    first = Counter()
    anyr = Counter()
    for e in held:
        rs = res[e]["reasons"]
        first[min(rs, key=lambda x: order.index(x) if x in order else 99)] += 1
        for x in rs:
            anyr[x] += 1
    for k in order:
        if anyr[k]:
            print(f"     {first[k] / n * 100:5.1f}  {k}   (appears on {anyr[k] / n * 100:.1f} in 100)")
    lo = Counter(x for e in res.values() for x in e["left_out"])
    print(f"  changes the flow would leave out by itself: {sum(lo.values())} ({dict(lo)})")

    # against the one person who has judged cards: the 150 audit cards, where both models had already agreed and the quote backed every change,
    # so only the description gates can differ from his answers
    key = json.loads((OUT / "audit-key.json").read_text(encoding="utf-8"))
    ans = list(csv.DictReader(open(OUT / "audit-answers.csv", encoding="utf-8-sig")))
    print("\nAGAINST YOUR AUDIT (150 cards where the models agreed; 10 planted cards shown apart):")
    t = Counter()
    for a in ans:
        k = key[a["card_id"]]
        if k["group"].startswith("control"):
            continue
        x = res[k["extracted_id"]]
        side = "auto" if x["outcome"].startswith("auto") and not x["left_out"] else ("left out" if x["left_out"] and x["outcome"].startswith("auto") else "held")
        t[(a["verdict"], side)] += 1
    for v in ("yes", "no"):
        print(f"  you said {v:<3}: flow settles alone {t[(v, 'auto')]:>3} · leaves a change out {t[(v, 'left out')]:>3} · hands to a person {t[(v, 'held')]:>3}")
    print("  planted cards (you said yes to all):")
    for a in ans:
        k = key[a["card_id"]]
        if k["group"].startswith("control"):
            x = res[k["extracted_id"]]
            print(f"     {a['card_id']} {a['entity'][:34]:<34} {x['outcome']:<42} {'; '.join(x['reasons'] + x['left_out'])[:80]}")
    with open(OUT / "flow-results.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["extracted_id", "entity", "gemini", "outcome", "reasons", "left_out"])
        for e, x in res.items():
            r = snap[e]
            w.writerow([e, r["name_en"] or r["name"], r["gemini"], x["outcome"], "; ".join(x["reasons"]), "; ".join(x["left_out"])])
    print(f"\nper-entity results: {OUT / 'flow-results.csv'}")


if __name__ == "__main__" and not (len(sys.argv) > 1 and sys.argv[1] in ("full", "full2")):
    report()


# ---- the fully automated version: "Gemini writes text, jev decides everything else" (docs/alternate-minimalist.md) -----------------------
#
# No entity is handed to a person. Every hold above becomes a decision, and the two decisions nobody answered become jev's:
#   new record  jev, one yes/no built from prompts/tte/notability.txt (>= 0.5 creates, otherwise "not worth a record")
#   changes     code lists what the article would add to the record; jev says which are worth recording (>= 0.5); each must then pass the quote
#               check (anything the quote does not clearly back is left out) and, for a description, the 5-sentence and "lasting" gates
# Gemini's stored text is reused: a description sentence Gemini never wrote cannot be replayed, so those entities are counted, not judged.
# Nothing here is tuned on human answers; there are no human labels for notability at all.

NOTABLE_Q = 0.5
WORTH_P = 0.5


def notability_question():
    text = (J.ROOT / "prompts" / "tte" / "notability.txt").read_text(encoding="utf-8").replace("\r\n", "\n")
    paras = [" ".join(p.split()) for p in text.split("\n\n") if p.strip()]
    yes = [p for p in paras if p.startswith(("A person is likely", "An organisation is likely", "A place is likely"))]
    no = [p for p in paras if p.startswith("Someone quoted in passing")]
    return {"notable": {"type": "noul", "instructions": "Is this entity notable enough to warrant a record in a national library's name authority file? " + paras[1],
                        "criteria": {"true": " ".join(yes), "false": " ".join(no) + " Appearing once in a news article is, by itself, weak evidence."}}}


def new_record_entities(snap, dec):
    out = []
    for eid, r in snap.items():
        d = dec.get(eid)
        if not r["candidates"] or d is None or d["action"] != "match":
            out.append(eid)
    return out


def notability_run():
    snap = {r["extracted_id"]: r for r in J.snapshot()}
    dec = F.listwise_decisions()
    cx = F.context()
    q = notability_question()
    jobs = []
    for eid in new_record_entities(snap, dec):
        r = snap[eid]
        st = {"article_headline": r["title"], "entity": {"name": r["name_en"] or r["name"], "type": J.KIND.get(r["type"], r["type"].lower()), "article_published": r["published"],
                                                         "what_the_article_says": r["summary"], **({"quote_from_article": r["quote_en"] or r["quote"]} if (r["quote_en"] or not J.non_latin(r["quote"])) else {})}}
        f = F.whole(cx.get(eid, {}).get("fields"))
        if f:
            st["entity"]["facts_the_extractor_found"] = f
        jobs.append((str(eid), st, q))
    P.run_jobs(OUT / "flow-notability.jsonl", jobs, "notability of entities with no record")


def full():
    snap = {r["extracted_id"]: r for r in J.snapshot()}
    dec = F.listwise_decisions()
    nota = P.load_answers(OUT / "flow-notability.jsonl")
    ev = P.load_answers(OUT / "updates.jsonl")
    fair = P.load_answers(OUT / "fair-up-rules.jsonl")
    lasting = P.load_answers(OUT / "audit-lasting.jsonl")
    items = {}
    for i in P.matched_items():
        items.setdefault(i["extracted_id"], []).append(i)
    matched = {m["extracted_id"]: m for m in json.loads((OUT / "matched.json").read_text(encoding="utf-8"))}
    t_desc = F.up_eval("rules", "dev")["Description"][0]       # the development-half threshold for "adds a fact", worked out once
    res = {}
    for eid, r in snap.items():
        d = dec.get(eid)
        if not r["candidates"] or d is None or d["action"] != "match":
            nq = nota.get(str(eid), {}).get("notable", {}).get("noul")
            res[eid] = {"outcome": "to create" if (nq or 0) >= NOTABLE_Q else "not worth a record", "applied": [], "left_out": [], "needs_sentence": False, "notability": nq}
            continue
        applied, left, needs = [], [], False
        m = matched.get(eid)
        cand = next((c for c in m["candidates"] if c["canonical_uid"] == d["top"]), None) if m else None
        if not m or not cand:
            res[eid] = {"outcome": "same", "applied": [], "left_out": [], "needs_sentence": False, "notability": None, "not_replayed": True}
            continue
        for i in items.get(eid, []):
            a = fair.get(i["key"]) or {}
            e = (ev.get(i["key"]) or {}).get("evidence")
            if i["field"] == "Description":
                if (a.get("adds_new_fact") or {}).get("noul", 0) < t_desc:
                    continue
                if i["gemini"] == "none" or not i["gemini_value"]:
                    needs = True                                   # a sentence Gemini would have to write: not replayed
                    continue
                before = i["have"]
                la = lasting.get(f"all-{eid}")
                nl = 1 - la["lasting"]["noul"] if la else 0.0
                if ENTITY.search(i["gemini_value"]) or over_limit(before, i["gemini_value"]) or nl >= LASTING_HAND_OVER or e is None or e["choice"] != "supports":
                    left.append("Description")
                else:
                    applied.append("Description")
            else:
                if (a.get("worth_recording") or {}).get("noul", 0) < WORTH_P:
                    continue
                if e is None or e["choice"] != "supports":
                    left.append(i["field"])
                else:
                    applied.append(i["field"])
        res[eid] = {"outcome": "amended" if applied else "same", "applied": applied, "left_out": left, "needs_sentence": needs, "notability": None}
    return snap, res


def full_report():
    snap, res = full()
    n = len(res)
    c = Counter(x["outcome"] for x in res.values())
    print(f"{n:,} entities, 100% automated (jev decides, Gemini's stored text reused, nobody reviews). Per 100:")
    for k in ("same", "amended", "to create", "not worth a record"):
        print(f"  {c[k] / n * 100:5.1f}  {k}")
    ns = sum(x["needs_sentence"] for x in res.values())
    print(f"  of the 'same' or 'amended': {ns} ({ns / n * 100:.1f} in 100) also need a description sentence Gemini never wrote (not replayed)")
    # against what Gemini's own pipeline did
    g = Counter()
    for eid, x in res.items():
        r = snap[eid]
        g[(J.GEM_NAME.get(r["gemini"], r["gemini"]).split(" (")[0], x["outcome"])] += 1
    print("\nAGAINST GEMINI'S OWN DECISIONS (Gemini action -> this flow's outcome):")
    for (ga, o), v in sorted(g.items(), key=lambda kv: -kv[1])[:10]:
        print(f"  {v:>5}  Gemini: {ga:<42} -> flow: {o}")
    gem_changes = Counter(u["field"] for m in json.loads((OUT / "matched.json").read_text(encoding="utf-8")) for u in m["field_updates"])
    mine = Counter(f for x in res.values() for f in x["applied"])
    print(f"\nCHANGES WRITTEN: Gemini's pipeline {sum(gem_changes.values()):,}; this flow {sum(mine.values()):,}, and left out {sum(len(x['left_out']) for x in res.values())}")
    for f in ("Description", "Affiliations(groupName)", "Awards", "Title", "Occupation", "Nationality"):
        print(f"   {f:<26} Gemini {gem_changes[f]:>5}   flow {mine[f]:>5}")
    # against the one person's audit
    key = json.loads((OUT / "audit-key.json").read_text(encoding="utf-8"))
    ans = list(csv.DictReader(open(OUT / "audit-answers.csv", encoding="utf-8-sig")))
    matched = {m["extracted_id"]: m for m in json.loads((OUT / "matched.json").read_text(encoding="utf-8"))}
    t = Counter()
    for a in ans:
        k = key[a["card_id"]]
        if k["group"].startswith("control"):
            continue
        gem_fields = {u["field"] for u in matched[k["extracted_id"]]["field_updates"]}
        x = res[k["extracted_id"]]
        keeps = x["outcome"] in ("same", "amended") and gem_fields <= set(x["applied"])
        t[(a["verdict"], "flow writes exactly what Gemini proposed" if keeps else "flow differs from Gemini's card")] += 1
    print("\nAGAINST YOUR AUDIT (150 cards; in-sample for the description gate):")
    for v in ("yes", "no"):
        print(f"  you said {v:<3}: flow writes exactly what Gemini proposed {t[(v, 'flow writes exactly what Gemini proposed')]:>3} · flow differs {t[(v, 'flow differs from Gemini' + chr(39) + 's card')]:>3}")
    print("  the 10 planted cards:", {a["card_id"]: res[key[a["card_id"]]["extracted_id"]]["outcome"] + (" (left out: " + ", ".join(res[key[a["card_id"]]["extracted_id"]]["left_out"]) + ")" if res[key[a["card_id"]]["extracted_id"]]["left_out"] else "") for a in ans if key[a["card_id"]]["group"].startswith("control")})
    nq = [x["notability"] for x in res.values() if x["notability"] is not None]
    import numpy as np
    print(f"\nNOTABILITY, {len(nq):,} entities with no record: jev says notable (>=0.5) for {np.mean([v >= 0.5 for v in nq]) * 100:.0f}% of them; "
          f"median score {np.median(nq):.2f}")
    with open(OUT / "flow-full.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["extracted_id", "entity", "gemini", "flow_outcome", "applied", "left_out", "needs_sentence", "notability"])
        for e, x in res.items():
            r = snap[e]
            w.writerow([e, r["name_en"] or r["name"], r["gemini"], x["outcome"], "; ".join(x["applied"]), "; ".join(x["left_out"]), x["needs_sentence"], x["notability"]])
    return snap, res


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "full":
    notability_run()
    full_report()


# ---- the same flow with the new-record gates Ashwin's decisions pointed to (2026-10-06) ---------------------------------------
#
# His nine new-record decisions were not about notability: Tokyo 2020 was not Singapore-centric; Berita Harian's parent organisation
# is already the record (a domain convention nobody had written down); Sun Quan's article should never have passed relevance.
# So the notability question is replaced by gates, in order:
#   the article was relevant   jev, headline and description (>= 0.53, the cut-off chosen on validation); otherwise nothing is done
#   Singapore-centric          jev (>= 0.5); otherwise "not worth a record"
#   its parent is a record     code: the extractor's Parent Organisation names a record already in the file -> "kept for review"
#   otherwise                  create
# Only the relevance and scope cut-offs come from earlier, unrelated work; none is tuned on his answers.

REL_CUT = 0.53
SCOPE_CUT = 0.5


def relevance_run_for_articles():
    import html as _html
    cx = F.context()
    from src.shared.supabase_client import get_client
    cl = get_client()
    aids = sorted({v["article_id"] for v in cx.values()})
    rows = []
    for i in range(0, len(aids), 100):
        rows += cl.from_("article").select("id,title,description").in_("id", aids[i:i + 100]).execute().data
    q = P.relevance_question("A")
    P.run_jobs(OUT / "flow-relevance.jsonl", [(str(r["id"]), f"{_html.unescape(r['title'] or '')}. {_html.unescape(r.get('description') or '')}", q) for r in rows], "relevance of the articles")


def parent_covered(eid, cx, table):
    parent = (cx.get(eid, {}).get("fields") or {}).get("Parent Organisation") or ""
    for p in [x.strip() for x in parent.split("|") if x.strip()]:
        key = " ".join(p.casefold().split())
        if key in table or key.replace("singapore. ", "") in table:
            return p
    return None


def full2():
    snap, res = full()
    cx = F.context()
    rel = {int(k): v["relevant"]["noul"] for k, v in P.load_answers(OUT / "flow-relevance.jsonl").items()}
    scope = {int(k): v["singaporean"]["noul"] for k, v in P.load_answers(OUT / "flow-scope.jsonl").items()}
    table, _ = P.gazetteer()
    out = {}
    for eid, x in res.items():
        a = rel.get(cx.get(eid, {}).get("article_id"))
        x = dict(x)
        x["relevance"], x["scope"] = a, scope.get(eid)
        if a is not None and a < REL_CUT:
            x.update(outcome="dropped: the article is not relevant", applied=[], left_out=[], needs_sentence=False)
        elif x["notability"] is not None or x["outcome"] in ("to create", "not worth a record"):
            s = scope.get(eid)
            pc = parent_covered(eid, cx, table)
            x["parent"] = pc
            if s is not None and s < SCOPE_CUT:
                x["outcome"] = "not worth a record (not Singapore-centric)"
            elif pc:
                x["outcome"] = "kept for review (its parent organisation is already a record)"
            else:
                x["outcome"] = "to create"
        out[eid] = x
    return snap, out


def full2_report():
    relevance_run_for_articles()
    snap, res = full2()
    n = len(res)
    c = Counter(x["outcome"] for x in res.values())
    print(f"{n:,} entities, 100% automated, with the new-record gates. Per 100:")
    for k, v in c.most_common():
        print(f"  {v / n * 100:5.1f}  {k}")
    rels = [x["relevance"] for x in res.values() if x["relevance"] is not None]
    print(f"\njev's relevance would drop the article for {sum(1 for x in res.values() if x['outcome'].startswith('dropped')) / n * 100:.1f} in 100 entities (Gemini passed every one)")
    d = list(csv.DictReader(open(J.ROOT / "data" / "audit results" / "decisions.csv", encoding="utf-8-sig")))
    key = json.loads((OUT / "desk-audit-key.json").read_text(encoding="utf-8"))
    html_ = (J.ROOT / "data" / "dist" / "prototype-audit.html").read_text(encoding="utf-8")
    tpl = (J.ROOT / "prototype" / "desk.template.html").read_text(encoding="utf-8")
    i = tpl.index("/*__CARDS__*/[]")
    pre = tpl[max(0, i - 60):i][-30:]
    cards, _ = json.JSONDecoder().raw_decode(html_[html_.index(pre) + len(pre):].replace("<\\/", "</"))
    e2k = {c_["entity"]: c_["key"] for c_ in cards}
    print("\nYOUR 9 NEW-RECORD DECISIONS against this flow:")
    agree = 0
    for r in d:
        if r["Outcome"] not in ("To create", "Not worth a record"):
            continue
        k = next((k for e, k in e2k.items() if r["Entity"].startswith(e) or e in r["Entity"]), None)
        eids = key[k]["extracted_ids"] if k else []
        o = sorted({res[e]["outcome"] for e in eids if e in res})
        ok = (r["Outcome"] == "To create" and "to create" in o) or (r["Outcome"] == "Not worth a record" and any(x.startswith(("not worth", "dropped")) for x in o))
        agree += ok
        print(f"  {r['Entity'][:44]:<44} you: {r['Outcome']:<19} flow: {'; '.join(o)[:62]}  {'✓' if ok else ('~' if any(x.startswith('kept') for x in o) else '✗')}")
    print(f"  agree on {agree} of 9 (a 'kept for review' is shown as ~, because you called Berita Harian ambiguous)")
    with open(OUT / "flow-full2.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["extracted_id", "entity", "gemini", "flow_outcome", "relevance", "scope", "parent"])
        for e, x in res.items():
            r = snap[e]
            w.writerow([e, r["name_en"] or r["name"], r["gemini"], x["outcome"], x.get("relevance"), x.get("scope"), x.get("parent")])
    return snap, res


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "full2":
    full2_report()
