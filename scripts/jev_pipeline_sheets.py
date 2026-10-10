"""
Two readable outputs from the jev pipeline test, both written to data/jev/:

    pipeline-examples.md   what a handful of real articles look like stage by stage, with jev doing what it can
    evaluate-pipeline.md   examples from every stage for a person to judge (no verdicts filled in)

    .venv/bin/python scripts/jev_pipeline_sheets.py examples
    .venv/bin/python scripts/jev_pipeline_sheets.py sheet

Both read the cached answers in data/jev/ and call jev only for the one headline-level relevance question per example article.
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
import jev_pipeline as P
import jev_replay as J

OUT = J.OUT


def pct(x):
    return f"{x * 100:.0f}%"


def relevance_of(title):
    """jev's relevance score for an article from its headline and RSS description, as the pipeline's first stage sees it."""
    from src.shared.supabase_client import get_client
    rows = get_client().from_("article").select("id,title,description,url").eq("title", title).limit(1).execute().data
    if not rows:
        return None, None
    import html
    text = f"{html.unescape(rows[0]['title'])}. {html.unescape(rows[0].get('description') or '')}"
    with httpx.Client() as c:
        a = J.ask(c, J.key(), text, P.relevance_question("A"), raw=True)
    return a["relevant"]["noul"], rows[0]


def examples():
    snap = J.snapshot()
    pairs = J.load_pairs()
    ext_rows = {r["extracted_id"]: r for r in P.extract_rows()}
    ext_ans = P.load_answers(OUT / "extract.jsonl")
    items = {}
    for i in P.matched_items():
        items.setdefault(i["extracted_id"], []).append(i)
    upd = P.load_answers(OUT / "updates.jsonl")
    picks = []
    for name, year in (("Gerard Ee", "2026"), ("林泉宝", None), ("Tang See Chim", None), ("Lawrence Wong", "2025")):
        for r in snap:
            if r["name"] == name and r["summary"] and (year is None or r["published"].startswith(year)) and r["candidates"]:
                picks.append(r["title"])
                break
    out = ["# What the pipeline looks like with jev doing everything it can", "",
           "Four real articles from the live deck, stage by stage. **jev** answers yes/no or picks from a list; **code** does exact work; **Gemini** is named only where jev cannot do the job.", ""]
    for title in picks:
        ents = [r for r in snap if r["title"] == title]
        rel, art = relevance_of(title)
        out += [f"## {title}", "", f"*{ents[0]['published']}*" + (f" · {art['url']}" if art else ""), "",
                f"**1. Is it relevant?** (headline and RSS description) jev scores it **{rel:.2f}**" + (" → passes on." if rel and rel >= 0.23 else " → would be dropped."), "",
                f"**2. Which entities, and what kind?** Gemini wrote {len(ents)} entities from the article. jev's check of each, from Gemini's own evidence sentence:", "",
                "| entity | Gemini's type | jev's type | jev: is it the subject? | jev: concrete change? |", "|---|---|---|---|---|"]
        for r in ents:
            a = ext_ans.get(str(r["extracted_id"]))
            e = ext_rows.get(r["extracted_id"], {})
            if a:
                out.append(f"| {r['name_en'] or r['name']} | {r['type']} | {a['entity_type']['choice']} | {a['is_subject']['noul']:.2f} | {a['concrete_change']['noul']:.2f} |")
        out += ["", "**3. Which record is it?** (retrieval is the trigram search, unchanged; jev compares the article with each record offered)", "",
                "| entity | Gemini said | best record offered | jev: same? | jev-first result |", "|---|---|---|---|---|"]
        for r in ents:
            sc = pairs.get(r["extracted_id"], {})
            if not r["candidates"]:
                out.append(f"| {r['name_en'] or r['name']} | {J.GEM_NAME.get(r['gemini'], r['gemini'])} | none | n/a | new record (no candidates, no model) |")
                continue
            act, uid, p, _ = J.decide(r, sc)
            top = next((c for c in r["candidates"] if c["canonical_uid"] == (uid or r["gemini_uid"])), r["candidates"][0])
            result = {"match": "same record", "new": "new record", "ambiguous": "**Gemini decides** (jev unsure)"}[act]
            out.append(f"| {r['name_en'] or r['name']} | {J.GEM_NAME.get(r['gemini'], r['gemini'])} | {top['canonical_name']} | {p:.2f} | {result} |")
        out += ["", "**4. What would change?** Code finds what the article would add to the record (no model). jev says whether it is worth recording and whether the article's own quote backs it:", ""]
        any_item = False
        for r in ents:
            for i in items.get(r["extracted_id"], []):
                a = upd.get(i["key"])
                if not a:
                    continue
                any_item = True
                ev = a.get("evidence")
                judged = f"adds a new fact: {a['adds_new_fact']['noul']:.2f}" if i["field"] == "Description" else f"worth recording: {a['worth_recording']['noul']:.2f}"
                shown = (i["gemini_value"] or i["fresh"] or "")[:150].replace("\n", " ")
                out.append(f"- **{i['name']} · {i['field']}** · Gemini {'applied it' if i['gemini'] != 'none' else 'left it out'} · jev {judged}" + (f" · quote **{ev['choice']}** ({ev['confidence']:.2f})" if ev else "") + f"\n  proposed: _{shown}_")
        if not any_item:
            out.append("- nothing to change on matched records")
        out += ["", "---", ""]
    (OUT / "pipeline-examples.md").write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {OUT / 'pipeline-examples.md'}")


def sheet():
    rng = random.Random(17)
    ans_rel = P.load_answers(OUT / "relevance-A.jsonl")
    live = {r["url"]: r for r in P.load_set("live")}
    sections = []

    # 1 relevance: where jev and the stored label disagree on the live feed
    t = 0.53
    fp, fn = [], []
    for k, a in ans_rel.items():
        if not k.startswith("live:"):
            continue
        r = live[k[5:]]
        s = a["relevant"]["noul"]
        if s >= 0.85 and r["label"] == 0:
            fp.append((r, s))
        if s <= 0.15 and r["label"] == 1:
            fn.append((r, s))
    body = []
    for nm, pool, n in (("jev says relevant, the stored label says not", fp, 8), ("jev says not relevant, the stored label says relevant", fn, 8)):
        for r, s in rng.sample(pool, min(n, len(pool))):
            body.append((f"**{r['text'][:420]}**\n\n{r['url']} ({r['lang']}, {r['day']})\n\nStored label (Gemini on the live feed): **{'relevant' if r['label'] else 'not relevant'}** · jev: **{s:.2f}**",
                         "[ ] relevant   [ ] not relevant   [ ] cannot tell    (would a record change?)", nm))
    sections.append(("Stage 1: relevance", "Would this article change a record in the national name authority file? Judge from the headline and description only.", body))

    # 2 extraction: Gemini's extractions where jev sees only a mention
    rows = {r["extracted_id"]: r for r in P.extract_rows()}
    ans = P.load_answers(OUT / "extract.jsonl")
    low = [rows[int(k)] | {"a": a} for k, a in ans.items() if int(k) in rows and a["concrete_change"]["noul"] < 0.1 and rows[int(k)]["role"] != "mentioned"]
    body = []
    for r in rng.sample(low, min(10, len(low))):
        body.append((f"**{r['name']}** ({r['type']}) · {r['published']} · {r['title']}\n\nGemini's summary: {r['summary']}\n\n> {r['sentence']}\n\njev: concrete change **{r['a']['concrete_change']['noul']:.2f}**, subject **{r['a']['is_subject']['noul']:.2f}**",
                     "[ ] there is a change to this entity (Gemini right)   [ ] only mentioned (jev right)   [ ] cannot tell", "jev says only mentioned"))
    typed = [rows[int(k)] | {"a": a} for k, a in ans.items() if int(k) in rows and a["entity_type"]["choice"] != rows[int(k)]["type"]]
    for r in rng.sample(typed, min(6, len(typed))):
        body.append((f"**{r['name']}** · Gemini's type: **{r['type']}** · jev's type: **{r['a']['entity_type']['choice']}**\n\n> {r['sentence']}", "[ ] Gemini's type right   [ ] jev's type right   [ ] either is fine", "type differs"))
    sections.append(("Stage 2: extraction (type, and whether there is a change at all)", "Gemini extracted these entities. Is there a concrete change to the entity in the sentence?", body))

    # 3 field updates
    items = {i["key"]: i for i in P.matched_items()}
    ua = P.load_answers(OUT / "updates.jsonl")
    got = [items[k] | {"a": a} for k, a in ua.items() if k in items]
    body = []
    desc_yes = [i for i in got if i["field"] == "Description" and i["gemini"] == "none" and i["a"]["adds_new_fact"]["noul"] >= 0.9]
    desc_no = [i for i in got if i["field"] == "Description" and i["gemini"] != "none" and i["a"]["adds_new_fact"]["noul"] <= 0.3]
    for nm, pool, n, q in (("jev says there is a new fact; Gemini wrote no description change", desc_yes, 7, "[ ] Gemini right to leave it   [ ] jev right: a fact is missing   [ ] cannot tell"),
                            ("jev says no new fact; Gemini rewrote the description", desc_no, 5, "[ ] Gemini right to rewrite   [ ] jev right: nothing new   [ ] cannot tell")):
        for i in rng.sample(pool, min(n, len(pool))):
            body.append((f"**{i['name']}** → record **{i['record']}** · {i['published']}\n\nArticle: {i['summary']}\n\n> {i['quote'] or ''}\n\nRecord's description: {i['have'][:500]}\n\nGemini's added text: _{(i['gemini_value'] or '(none)')[:250]}_\n\njev: adds a new fact **{i['a']['adds_new_fact']['noul']:.2f}**",
                         q, nm))
    aff = [i for i in got if i["field"] == "Affiliations(groupName)" and i["gemini"] == "none" and i["a"]["worth_recording"]["noul"] >= 0.9]
    aff2 = [i for i in got if i["field"] != "Description" and i["gemini"] != "none" and i["a"]["worth_recording"]["noul"] <= 0.2]
    for nm, pool, n, q in (("jev says worth recording; Gemini left the field alone", aff, 6, "[ ] Gemini right to skip   [ ] jev right: should be recorded   [ ] cannot tell"),
                            ("jev says not worth recording; Gemini applied it", aff2, 5, "[ ] Gemini right to apply   [ ] jev right: should not be recorded   [ ] cannot tell")):
        for i in rng.sample(pool, min(n, len(pool))):
            body.append((f"**{i['name']}** → record **{i['record']}** · {i['published']} · field **{i['field']}**\n\n> {i['quote'] or i['summary']}\n\nRecord has: {i['have'][:300] or '(empty)'}\n\nProposed: _{(i['gemini_value'] or i['fresh'])[:250]}_\n\njev: worth recording **{i['a']['worth_recording']['noul']:.2f}**", q, nm))
    sections.append(("Stage 5: what to write into the record", "Should this change be made to the authority record?", body))

    # 4 quote support
    ev = [i for i in got if i["gemini"] != "none" and "evidence" in i["a"]]
    contra = [i for i in ev if i["a"]["evidence"]["choice"] == "contradicts"]
    nothing = [i for i in ev if i["a"]["evidence"]["choice"] == "says_nothing" and i["a"]["evidence"]["confidence"] >= 0.9]
    sup = [i for i in ev if i["a"]["evidence"]["choice"] == "supports" and i["a"]["evidence"]["confidence"] >= 0.9]
    body = []
    for nm, pool, n in (("jev says the quote contradicts the change", contra, 12), ("jev says the quote says nothing about the change", nothing, 8), ("control: jev says the quote supports it", sup, 4)):
        for i in rng.sample(pool, min(n, len(pool))):
            body.append((f"**{i['name']}** · {i['field']} · {i['published']}\n\nQuote shown on the card: > {i['quote']}\n\nProposed change: _{(i['gemini_value'] or '')[:300]}_\n\njev: **{i['a']['evidence']['choice']}** ({i['a']['evidence']['confidence']:.2f})",
                         "[ ] jev right   [ ] jev wrong   [ ] cannot tell", nm))
    sections.append(("Stage 6: does the quote back the change?", "Read the quote, then the proposed change. Does the quote support it?", body))

    out = ["# Judge jev at every stage", "", "Each example shows what the pipeline produced and what jev said. Tick one box. Nothing is pre-judged; the heading of each group is in the key at the end so it does not bias you.", "",
           "**How to read jev's numbers.** Each is jev's chance, from 0 to 1, that the statement is true. 'adds a new fact 0.96' means 96% sure the article adds something; 'worth recording 0.16' means 84% sure it is not. For the quote check, jev picks supports, contradicts or says_nothing and the number is how sure it is of that pick.", ""]
    key = []
    n = 0
    for title, ask, body in sections:
        out += [f"# {title}", "", f"*{ask}*", ""]
        rng.shuffle(body)
        for text, boxes, tag in body:
            n += 1
            out += [f"### {n}", "", text, "", f"**Your verdict:**  {boxes}", "", "---", ""]
            key.append(f"{n}. {tag}")
    out += ["# Key", ""] + key
    (OUT / "evaluate-pipeline.md").write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {OUT / 'evaluate-pipeline.md'} ({n} examples)")


if __name__ == "__main__":
    {"examples": examples, "sheet": sheet}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit(__doc__))()
