"""
Round two: a fair test of jev. The first round gave jev a one-paragraph question and trimmed text, while Gemini's prompts have
been tuned for months and Gemini receives far more. Here jev gets what Gemini gets (the article's headline, the name as written and
its romanisation, the other entities from the same article, the extractor's fields, the whole record with nothing cut off) and the
rules from the Gemini prompts, put as jev's criteria.

To keep the tuning honest, rows are split by id: even ids are the development half, odd ids the held-out half. Wording variants are
compared on the development half only; the winner is then run once on the held-out half, and only that number is reported.

    .venv/bin/python scripts/jev_fair.py identity dev          # three wordings on the development half
    .venv/bin/python scripts/jev_fair.py identity held         # the winner on the held-out half, against round one
    .venv/bin/python scripts/jev_fair.py identity report

Everything is cached under data/jev/. Only English summaries, translated quotes and public TTE fields are sent.
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jev_pipeline as P
import jev_replay as J

OUT = J.OUT
SKIP = J.SKIP_FIELDS
FIELD_CAP = 3500                                    # the longest description in the file is about 3,000 characters


def whole(fields, cap=FIELD_CAP):
    """The record's fields with nothing cut short."""
    return {k: str(v)[:cap] for k, v in (fields or {}).items() if k not in SKIP and v}


def context():
    """extracted_id -> {article_id, fields}: what Gemini sees that the first round left out."""
    path = OUT / "ctx.json"
    if path.exists():
        return {int(k): v for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
    from src.shared.pagination import fetch_all
    from src.shared.supabase_client import get_client
    cl = get_client()
    rows = fetch_all(lambda: cl.from_("extracted_entities").select("id,article_id,fields,role"))
    out = {r["id"]: {"article_id": r["article_id"], "fields": r["fields"] or {}, "role": r["role"]} for r in rows}
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def half(eid):
    return "dev" if eid % 2 == 0 else "held"


# ---- identity ---------------------------------------------------------------------------------

RULES_TRUE = ("The article's entity and the record describe the same individual or body: occupation, affiliation, title and era are consistent. "
              "The record may be older than the article, so a newer post, title or employer is normal, and the record is often written in another spelling or language.")
RULES_FALSE = ("The record's fields point somewhere else: a different employer, profession, era or sphere entirely. Singapore personal names are widely shared, so an identical name proves only that two records "
               "use the same string. A record found only through the extractor's romanisation of a non-English name is weak name evidence: decide on the fields.")
LEVELS = ["Different: the record's fields point somewhere else, or only the name is shared.",
          "Unsure: some facts fit, others are missing or odd, and the article cannot settle it.",
          "Same: occupation, affiliation, title and era fit, and nothing conflicts. The record may be older than the article."]


def found_through(c):
    if c.get("romanised"):
        return "the extractor's English romanisation of a non-English name (a guess, which can be wrong)"
    if c.get("matched_name") and c["matched_name"] != c["canonical_name"] and (c.get("similarity") or 0) >= 0.9:
        return f"a linked record in the other language with the same name as the article ({c['matched_name']})"
    return "the name as the article spells it"


def id_state(r, c, cx, by_art, variant):
    name_en = r["name_en"] if r["name_en"] and r["name_en"] != r["name"] else None
    quote = r["quote_en"] or (r["quote"] if not J.non_latin(r["quote"]) else None)
    ent = {"name_as_written": r["name"], **({"name_in_English": name_en} if name_en else {}), "type": J.KIND.get(r["type"], r["type"].lower()),
           "article_published": r["published"], "what_the_article_says": r["summary"], **({"quote_from_article": quote} if quote else {})}
    f = whole(cx.get(r["extracted_id"], {}).get("fields"))
    if f:
        ent["facts_the_extractor_found"] = f
    if variant == "u":                                                  # round one's state and wording exactly, with nothing cut off
        saved = (J.CAPS, J.DEFAULT_CAP)
        J.CAPS, J.DEFAULT_CAP = {}, FIELD_CAP
        try:
            return J.pair_state(r, c)
        finally:
            J.CAPS, J.DEFAULT_CAP = saved
    others = [{"name": o["name_en"] or o["name"], "what_the_article_says": o["summary"]} for o in by_art.get(cx.get(r["extracted_id"], {}).get("article_id"), []) if o["extracted_id"] != r["extracted_id"]][:6]
    return {"article_headline": r["title"], "entity_in_the_article": ent, **({"other_entities_in_the_same_article": others} if others else {}),
            "authority_record": {"name": c["canonical_name"], "facts": whole(c.get("canonical_fields")), "found_through": found_through(c), "name_similarity": round(c.get("similarity") or 0, 2)}}


def id_questions(r, variant):
    kind = J.KIND.get(r["type"], r["type"].lower())
    if variant == "u":
        return {"same_entity": J.questions(kind)["same_entity"]}
    ask = (f"Is the {kind} in the article the same real-world {kind} as the authority record? Compare occupation, affiliation, title and description. "
           "Use the other entities from the same article as context: if a person chairs an organisation that also appears and clearly matches, that raises confidence.")
    if variant == "ctx":
        return {"same_entity": {"type": "noul", "instructions": ask, "criteria": {"true": RULES_TRUE, "false": RULES_FALSE}}}
    return {"same_entity": {"type": "score", "instructions": ask, "criteria": LEVELS}}


def p_of(answers):
    a = answers["same_entity"]
    return a["noul"] if "noul" in a else a["probabilities"]["2"]


def id_rows(which):
    return [r for r in J.snapshot() if r["candidates"] and (which == "all" or half(r["extracted_id"]) == which)]


def id_run(variant, which):
    cx = context()
    snap = J.snapshot()
    by_art = {}
    for r in snap:
        by_art.setdefault(cx.get(r["extracted_id"], {}).get("article_id"), []).append(r)
    jobs = [(f"{r['extracted_id']}|{c['canonical_uid']}", id_state(r, c, cx, by_art, variant), id_questions(r, variant)) for r in id_rows(which) for c in r["candidates"]]
    P.run_jobs(OUT / f"fair-id-{variant}.jsonl", jobs, f"identity {variant} on {which}")


def id_best(variant, rows):
    ans = P.load_answers(OUT / f"fair-id-{variant}.jsonl")
    best = {}
    for r in rows:
        ps = [p_of(ans[f"{r['extracted_id']}|{c['canonical_uid']}"]) for c in r["candidates"] if f"{r['extracted_id']}|{c['canonical_uid']}" in ans]
        if len(ps) == len(r["candidates"]):
            best[r["extracted_id"]] = max(ps)
    return best


def legacy_best(rows):
    pairs = J.load_pairs()
    return {r["extracted_id"]: max(s["same"] for s in pairs[r["extracted_id"]].values()) for r in rows if r["extracted_id"] in pairs and len(pairs[r["extracted_id"]]) == len(r["candidates"])}


def summarise(name, best, rows, hi=0.8, lo=0.2):
    rows = [r for r in rows if r["extracted_id"] in best]
    g = lambda r: J.GEM.get(r["gemini"], "other")
    dec = [r for r in rows if g(r) in ("match", "new")]
    y = [g(r) == "match" for r in dec]
    s = [best[r["extracted_id"]] for r in dec]
    act = lambda p: "match" if p >= hi else ("new" if p <= lo else "ambiguous")
    agree = sum(g(r) == act(best[r["extracted_id"]]) for r in rows if g(r) in ("match", "new", "ambiguous"))
    tot = sum(g(r) in ("match", "new", "ambiguous") for r in rows)
    gm = [r for r in rows if g(r) == "match"]
    keep = sum(act(best[r["extracted_id"]]) == "match" for r in gm)
    zh = [r for r in gm if J.non_latin(r["name"])]
    en = [r for r in gm if not J.non_latin(r["name"])]
    kz = sum(act(best[r["extracted_id"]]) == "match" for r in zh)
    ke = sum(act(best[r["extracted_id"]]) == "match" for r in en)
    alone = sum(act(best[r["extracted_id"]]) != "ambiguous" for r in rows)
    ga = [r for r in rows if g(r) == "ambiguous"]
    amb_new = sum(act(best[r["extracted_id"]]) == "new" for r in ga)
    print(f"  {name:<28} n={len(rows):>5}  AUC(match vs new) {P.auc(y, s):.3f} | agree {agree / tot * 100:>5.1f}% | Gemini's matches kept {keep / len(gm) * 100:>5.1f}% (English {ke / len(en) * 100:.1f}%, Chinese {kz / len(zh) * 100:.1f}%) | jev decides alone {alone / len(rows) * 100:.0f}% | Gemini's ambiguous called new {amb_new / max(len(ga), 1) * 100:.0f}%")


def id_dev_report(variants=("u", "ctx", "score")):
    rows = id_rows("dev")
    print(f"IDENTITY, development half ({len(rows):,} entities). Round one used the first line below with its text cut at 600 characters.\n")
    summarise("round one (as run)", legacy_best(rows), rows)
    for v in variants:
        if (OUT / f"fair-id-{v}.jsonl").exists():
            summarise(f"variant {v}", id_best(v, rows), rows)


def tune_cutoffs(best, rows):
    """The match and new cut-offs that agree most with Gemini on these rows (development half only)."""
    top = (0.0, 0.8, 0.2)
    g = lambda r: J.GEM.get(r["gemini"], "other")
    rows = [r for r in rows if r["extracted_id"] in best and g(r) in ("match", "new", "ambiguous")]
    for hi in np.arange(0.4, 0.96, 0.05):
        for lo in np.arange(0.05, 0.5, 0.05):
            if lo >= hi:
                continue
            act = lambda p: "match" if p >= hi else ("new" if p <= lo else "ambiguous")
            ag = sum(g(r) == act(best[r["extracted_id"]]) for r in rows) / len(rows)
            if ag > top[0]:
                top = (ag, float(round(hi, 2)), float(round(lo, 2)))
    return top[1], top[2]


def id_held(variant):
    dev, held = id_rows("dev"), id_rows("held")
    legacy_cut = tune_cutoffs(legacy_best(dev), dev)
    new_cut = tune_cutoffs(id_best(variant, dev), dev)
    id_run(variant, "held")
    print(f"\nIDENTITY, held-out half ({len(held):,} entities), never used for tuning. Each version gets the cut-offs that were best on the development half.\n")
    summarise(f"round one, cut-offs {legacy_cut[0]}/{legacy_cut[1]}", legacy_best(held), held, *legacy_cut)
    summarise(f"fair round '{variant}', cut-offs {new_cut[0]}/{new_cut[1]}", id_best(variant, held), held, *new_cut)
    summarise("fair round, the original 0.8/0.2", id_best(variant, held), held, 0.8, 0.2)
    return new_cut


# ---- identity as the same multiple-choice question Gemini answers ----------------------------------------------
#
# Gemini sees all of an entity's candidates at once and picks one action: a record, "new", or "ambiguous". The pairwise questions above
# scored each record alone and needed cut-offs to become those labels. Here jev gets the same single question: the candidates are the
# options, plus "none of these" (new) and "unsure" (ambiguous). No cut-off is involved: the option jev rates most likely is its answer.
# Each entity is asked twice, with the options in opposite orders, and the probabilities averaged, because jev's guide warns that a
# choice can favour the first option.

LETTERS = "ABCDE"


def listwise_state(r, order, cx, by_art):
    st = id_state(r, order[0], cx, by_art, "ctx")
    st.pop("authority_record")
    st["candidate_records"] = {L: {"name": c["canonical_name"], "facts": whole(c.get("canonical_fields")), "found_through": found_through(c), "name_similarity": round(c.get("similarity") or 0, 2)}
                               for L, c in zip(LETTERS, order)}
    return st


def listwise_questions(r, order):
    kind = J.KIND.get(r["type"], r["type"].lower())
    crit = {L: f"Candidate record {L} is the same real-world {kind} as the one in the article." for L in LETTERS[:len(order)]}
    crit["none"] = f"None of the candidate records is this {kind}: it is a different entity that has no record yet."
    crit["unsure"] = f"Two or more candidate records could be this {kind}, or the facts cannot settle which."
    ask = (f"Which of the candidate records, if any, is the same real-world {kind} as the entity in the article? Compare occupation, affiliation, title and description. "
           "Singapore personal names are widely shared, so an identical name proves only that two records use the same string. A record found only through the extractor's romanisation "
           "of a non-English name is weak name evidence: decide on the fields. The record may be older than the article, so a newer post, title or employer is normal. "
           "Use the other entities from the same article as context.")
    return {"which_record": {"type": "choice", "instructions": ask, "criteria": crit}}


def listwise_run():
    cx = context()
    snap = J.snapshot()
    by_art = {}
    for r in snap:
        by_art.setdefault(cx.get(r["extracted_id"], {}).get("article_id"), []).append(r)
    jobs = []
    for r in snap:
        if not r["candidates"]:
            continue
        for tag, order in (("fwd", r["candidates"]), ("rev", r["candidates"][::-1])):
            jobs.append((f"{r['extracted_id']}|{tag}", listwise_state(r, order, cx, by_art), listwise_questions(r, order)))
    P.run_jobs(OUT / "fair-listwise.jsonl", jobs, "identity as one multiple-choice question")


def listwise_decisions():
    ans = P.load_answers(OUT / "fair-listwise.jsonl")
    out = {}
    for r in J.snapshot():
        if not r["candidates"]:
            continue
        probs, runs = {}, []
        for tag, order in (("fwd", r["candidates"]), ("rev", r["candidates"][::-1])):
            a = ans.get(f"{r['extracted_id']}|{tag}")
            if not a:
                break
            pr = a["which_record"]["probabilities"]
            by = {c["canonical_uid"]: pr.get(L, 0.0) for L, c in zip(LETTERS, order)} | {"none": pr.get("none", 0.0), "unsure": pr.get("unsure", 0.0)}
            runs.append(max(by, key=by.get))
            for k, v in by.items():
                probs[k] = probs.get(k, 0.0) + v / 2
        else:
            top = max(probs, key=probs.get)
            out[r["extracted_id"]] = {"top": top, "p": probs[top], "probs": probs, "stable": runs[0] == runs[1],
                                      "action": "new" if top == "none" else ("ambiguous" if top == "unsure" else "match")}
    return out


def listwise_report():
    dec = listwise_decisions()
    rows = [r for r in J.snapshot() if r["extracted_id"] in dec]
    g = lambda r: {"MATCH_AND_UPDATE": "match", "CREATE_NEW": "new", "FLAG_AMBIGUOUS": "ambiguous"}.get(r["gemini"])
    comparable = [r for r in rows if g(r)]
    print(f"IDENTITY as one multiple-choice question, {len(rows):,} entities with candidates; {len(comparable):,} have a Gemini action that maps onto it (the rest are 'search again' and 'duplicate').\n")
    agree = sum(g(r) == dec[r["extracted_id"]]["action"] for r in comparable)
    print(f"  3-way agreement with Gemini (match / new / ambiguous): {agree / len(comparable) * 100:.1f}%   (no cut-off tuned anywhere)")
    print("\n   Gemini/jev      match     new  ambiguous")
    for a in ("match", "new", "ambiguous"):
        c = [r for r in comparable if g(r) == a]
        print(f"   {a:<12}" + "".join(f"{sum(dec[r['extracted_id']]['action'] == b for r in c):>8}" for b in ("match", "new", "ambiguous")) + f"     ({len(c):,})")
    both = [r for r in comparable if g(r) == "match" and dec[r["extracted_id"]]["action"] == "match"]
    same = sum(dec[r["extracted_id"]]["top"] == r["gemini_uid"] for r in both)
    print(f"\n  When both say match, they pick the same record: {same / len(both) * 100:.1f}% ({same:,}/{len(both):,}).")
    st = sum(dec[r["extracted_id"]]["stable"] for r in rows)
    print(f"  Option-order check: the two orders give the same top option for {st / len(rows) * 100:.1f}% of entities.")
    zh = [r for r in comparable if J.non_latin(r["name"])]
    en = [r for r in comparable if not J.non_latin(r["name"])]
    for nm, sub in (("English-named", en), ("Chinese-named", zh)):
        gm = [r for r in sub if g(r) == "match"]
        print(f"  {nm}: Gemini's matches kept {sum(dec[r['extracted_id']]['action'] == 'match' for r in gm) / len(gm) * 100:.1f}% ({len(gm):,}); overall agreement {sum(g(r) == dec[r['extracted_id']]['action'] for r in sub) / len(sub) * 100:.1f}%")
    other = [r for r in rows if r["gemini"] in ("RE_QUERY_REQUIRED", "FLAG_DB_DUPLICATE")]
    import collections
    print(f"  Gemini 'search again' / 'duplicate' ({len(other)}): jev answers {dict(collections.Counter(dec[r['extracted_id']]['action'] for r in other))}")
    conf = sum(dec[r["extracted_id"]]["p"] for r in rows) / len(rows)
    print(f"  Average probability jev gives its top option: {conf:.2f}")


# ---- what to write into the record ----------------------------------------------------------

# Verbatim from prompts/tte/fields_brief.txt, the rules Gemini is given for each field.
FIELD_RULES = {
    "Occupation": "Occupation is a durable profession from a fixed thesaurus: Engineer, Politician, Teacher, Lawyer. A POST IS NOT AN OCCUPATION -- \"Chairperson\", \"CEO\", \"Chief Financial Officer\", \"Minister for Defence\" describe a role someone holds, and belong in Description.",
    "Title": "Title means royalty, nobility, religious rank, honour or office: Sir, Dr, Prof, Venerable, Haji, Dato. Never a profession or a post.",
    "Affiliations(groupName)": "Affiliations(groupName) is every organisation other than the ones already in Education.",
    "Education": "Education is the institution attended.",
    "Achievements": "Achievements excludes: awards (their own field), anything the Description already says, a list of posts or designations, the person's relationship with someone else, and illegal acts.",
}
THESAURUS = None


def thesaurus():
    global THESAURUS
    if THESAURUS is None:
        lines = (J.ROOT / "prompts" / "tte" / "occupations.txt").read_text(encoding="utf-8").splitlines()
        THESAURUS = {ln.strip().casefold() for ln in lines[lines.index("Academic"):] if ln.strip()} if "Academic" in lines else set()
    return THESAURUS


def up_context():
    rows = json.loads((OUT / "matched.json").read_text(encoding="utf-8"))
    cand = {}
    for r in rows:
        c = next((c for c in r["candidates"] if c["canonical_uid"] == r["gemini_uid"]), None)
        if c:
            cand[r["extracted_id"]] = c
    return cand, {r["extracted_id"]: r for r in J.snapshot()}


def up_state(item, cand, snap, cx, variant):
    kind = J.KIND.get(item["type"], item["type"].lower())
    c = cand[item["extracted_id"]]
    ent = {"name": item["name"], "article_published": item["published"], "what_the_article_says": item["summary"], **({"quote_from_article": item["quote"]} if item["quote"] else {})}
    if variant == "u":
        record = {"name": item["record"], item["field"]: item["have"] or "(empty)"}
        state = {"entity_in_the_article": ent, "authority_record": record}
    else:
        f = whole(cx.get(item["extracted_id"], {}).get("fields"))
        if f:
            ent["facts_the_extractor_found"] = f
        state = {"article_headline": snap[item["extracted_id"]]["title"], "entity_in_the_article": ent, "authority_record": {"name": item["record"], "facts": whole(c.get("canonical_fields"))}}
    if item["field"] != "Description":
        state["proposed_addition"] = {item["field"]: (item["fresh"] or "")[:1500]}
    return state


def up_questions(item, variant):
    kind = J.KIND.get(item["type"], item["type"].lower())
    if item["field"] == "Description":
        if variant == "u":
            return {"adds_new_fact": P.update_questions(item)["adds_new_fact"]}
        if variant == "rules":
            return {"adds_new_fact": {"type": "noul", "instructions": f"Does the article state a change or fact about this {kind} that the record's description does not already record?",
                                      "criteria": {"true": "The article reports a post, appointment (an announced appointment counts from the announcement, even if it starts later), departure, death, award, rename, relocation, merger or similar fact that the description lacks.",
                                                   "false": "The description already records it, including the same post with the same year, or the article only rephrases it or repeats background the description holds."}}}
        return {"adds_new_fact": {"type": "choice", "instructions": f"How does what the article says about this {kind} stand against the record's description?",
                                  "criteria": {"already_recorded": "The description already says it, including the same post with the same year, or the article only rephrases it or repeats background.",
                                               "new_fact": "The article reports a post, appointment (an announced one counts), departure, death, award, rename, relocation, merger or similar fact the description lacks.",
                                               "conflicts": "The description states something different: another date, name or post."}}}
    if variant == "u":
        return {"worth_recording": P.update_questions(item)["worth_recording"]}
    rule = FIELD_RULES.get(item["field"], "")
    return {"worth_recording": {"type": "noul", "instructions": f"Should the proposed value be added to the authority record's '{item['field']}' field for this {kind}? {rule}".strip(),
                                "criteria": {"true": "It is a lasting fact about this entity that fits what this field holds, and the record does not already hold it.",
                                             "false": "It does not fit this field's rule, is already recorded, is incidental or temporary, or is only loosely connected to this entity."}}}


def up_p(answers, field):
    a = answers["adds_new_fact" if field == "Description" else "worth_recording"]
    return a["noul"] if "noul" in a else a["probabilities"]["new_fact"]


def up_run(variant, which):
    cand, snap = up_context()
    cx = context()
    items = [i for i in P.matched_items() if i["extracted_id"] in cand and (which == "all" or half(i["extracted_id"]) == which)]
    P.run_jobs(OUT / f"fair-up-{variant}.jsonl", [(i["key"], up_state(i, cand, snap, cx, variant), up_questions(i, variant)) for i in items], f"updates {variant} on {which}")


def up_eval(variant, which, thresholds=None):
    cand, _ = up_context()
    ans = P.load_answers(OUT / ("updates.jsonl" if variant == "round1" else f"fair-up-{variant}.jsonl"))
    items = [i for i in P.matched_items() if i["key"] in ans and half(i["extracted_id"]) == which]
    out = {}
    for group, test in (("Description", lambda i: i["field"] == "Description"), ("other fields", lambda i: i["field"] != "Description"), ("Awards", lambda i: i["field"] == "Awards"),
                        ("Affiliations", lambda i: i["field"] == "Affiliations(groupName)"), ("Occupation", lambda i: i["field"] == "Occupation"), ("Title", lambda i: i["field"] == "Title")):
        sub = [i for i in items if test(i)]
        if len(sub) < 20:
            continue
        y = np.array([i["gemini"] != "none" for i in sub])
        s = np.array([up_p(ans[i["key"]], i["field"]) for i in sub])
        t = (thresholds or {}).get(group) or P.best_f1_threshold(y, s)
        tp = int(((s >= t) & y).sum())
        agree = ((s >= t) == y).mean()
        out[group] = (t, P.auc(y, s), agree, len(sub), y.mean(), tp / max(int((s >= t).sum()), 1), tp / max(int(y.sum()), 1))
    return out


def up_dev_report():
    print("FIELD UPDATES, development half. AUC for 'Gemini applied this'; the threshold is the best-F1 one on this half.\n")
    print(f"  {'variant':<10}{'group':<14}{'n':>5}{'Gemini applies':>16}{'AUC':>7}{'agree':>8}{'precision':>11}{'recall':>8}  threshold")
    for v in ("u", "rules", "choice"):
        if not (OUT / f"fair-up-{v}.jsonl").exists():
            continue
        for g, (t, a, ag, n, rate, pr, rc) in up_eval(v, "dev").items():
            print(f"  {v:<10}{g:<14}{n:>5}{rate * 100:>15.0f}%{a:>7.3f}{ag * 100:>7.0f}%{pr * 100:>10.0f}%{rc * 100:>7.0f}%  {t:.2f}")
    # the rule a closed list gives for free: a proposed Occupation must be on the thesaurus
    items = [i for i in P.matched_items() if i["field"] == "Occupation" and half(i["extracted_id"]) == "dev"]
    ok = [i for i in items if i["fresh"] and all(t.strip().casefold() in thesaurus() for t in i["fresh"].split("|") if t.strip())]
    both = sum(i["gemini"] != "none" for i in ok)
    print(f"\n  Code alone, Occupation: a proposed value is on the thesaurus for {len(ok)} of {len(items)} proposals; Gemini applied {both} of those and {sum(i['gemini'] != 'none' for i in items) - both} that are not on the list.")


def up_held():
    """Per group: the wording with the best development AUC, and its development best-F1 threshold, run once on the held-out half."""
    variants = ("u", "rules", "choice")
    for v in variants:
        up_run(v, "held")
    dev = {v: up_eval(v, "dev") for v in variants}
    dev["round1"] = up_eval("round1", "dev")
    print("\nFIELD UPDATES, held-out half. Per group: the wording chosen on the development half (best AUC there) and its development threshold.\n")
    print(f"  {'group':<14}{'n':>5}{'Gemini applies':>16}  {'round one: AUC / agree':<24}{'fair round: wording':<22}{'AUC / agree / precision / recall'}")
    for g in ("Description", "other fields", "Awards", "Affiliations", "Occupation", "Title"):
        cands = [(dev[v][g][1], v) for v in variants if g in dev[v]]
        if not cands:
            continue
        _, v = max(cands)
        t = dev[v][g][0]
        r1 = up_eval("round1", "held", {g: dev["round1"][g][0]})[g]
        new = up_eval(v, "held", {g: t})[g]
        print(f"  {g:<14}{new[3]:>5}{new[4] * 100:>15.0f}%  {r1[1]:.3f} / {r1[2] * 100:.0f}%{'':<10}{v:<22}{new[1]:.3f} / {new[2] * 100:.0f}% / {new[5] * 100:.0f}% / {new[6] * 100:.0f}%")


# ---- relevance, asked the way jev's own guide recommends: several narrow questions instead of one broad one -----------------

def relevance_parts():
    text = (J.ROOT / "prompts" / "relevance.txt").read_text(encoding="utf-8").replace("\r\n", "\n")
    body = text.split("OUTPUT INSTRUCTIONS")[0]
    needed = body.split("A knowledge base update is needed when")[1].split("NOT needed when:")[0]
    not_needed, singapore = body.split("NOT needed when:")[1].split("The entity must be Singaporean:")
    bullets = lambda block: [ln.strip()[2:].strip() for ln in block.splitlines() if ln.strip().startswith("- ")]
    return bullets(needed), bullets(not_needed), bullets(singapore)


def relevance_questions_d():
    needed, not_needed, singapore = relevance_parts()
    qs = {}
    for i, b in enumerate(needed):
        qs[f"change_{i}"] = {"type": "noul", "instructions": f"Does this Singapore news headline and description report the following? {b}",
                             "criteria": {"true": "The item reports this concretely, about a specific named entity.", "false": "It does not, or only mentions or discusses it."}}
    qs["singaporean"] = {"type": "noul", "instructions": "Is the entity the item is about Singaporean? " + " ".join(f"{b}." for b in singapore),
                         "criteria": {"true": "A Singapore person, institution, building, place, programme or law.", "false": "A foreign entity, or a foreign brand or company with a Singapore branch."}}
    qs["excluded"] = {"type": "noul", "instructions": "Is this item one of the following kinds, which do not change a record? " + "; ".join(not_needed),
                      "criteria": {"true": "The item is of one of these kinds.", "false": "It is none of these."}}
    return qs, len(needed)


def rel_combos(a, n):
    ch = max(a[f"change_{i}"]["noul"] for i in range(n))
    sg, ex = a["singaporean"]["noul"], a["excluded"]["noul"]
    return {"max change": ch, "x singaporean": ch * sg, "x singaporean x not excluded": ch * sg * (1 - ex), "x not excluded": ch * (1 - ex)}


def rel_run(which):
    qs, _ = relevance_questions_d()
    sets = P.relevance_sets()
    for name in ("val",) if which == "dev" else ("test", "live", "human"):
        P.run_jobs(OUT / "fair-rel-d.jsonl", [(f"{name}:{r['url']}", r["text"], qs) for r in sets[name]], f"relevance D {name}")


def rel_report(which="dev", pick=None):
    ans = P.load_answers(OUT / "fair-rel-d.jsonl")
    a_ans = P.load_answers(OUT / "relevance-A.jsonl")
    sets = P.relevance_sets()
    _, n = relevance_questions_d()

    def scored(name, how):
        rows = [r for r in sets[name] if f"{name}:{r['url']}" in ans]
        s = np.array([a_ans[f"{name}:{r['url']}"]["relevant"]["noul"] if how == "one question" else rel_combos(ans[f"{name}:{r['url']}"], n)[how] for r in rows])
        return rows, s, np.array([r["label"] for r in rows])

    hows = ["one question", "max change", "x singaporean", "x singaporean x not excluded", "x not excluded"]
    if which == "dev":
        print("RELEVANCE, development set (3,000 validation articles):\n")
        for h in hows:
            rows, s, y = scored("val", h)
            print(f"  {h:<30} AUC {P.auc(y, s):.3f}   best F1 {P.prf(y, s, P.best_f1_threshold(y, s))[2]:.2f}   precision at 95% recall {P.precision_at_recall(y, s):.2f}")
        return
    vr, vs, vy = scored("val", pick)
    t_f1 = P.best_f1_threshold(vy, vs)
    print(f"RELEVANCE, held-out sets, '{pick}' (threshold chosen on the 3,000 development articles: {t_f1:.3f}); first line is round one's single question\n")
    print(f"{'set':<8}{'wording':<30}{'n':>6}{'AUC':>7}{'F1':>6}{'prec':>6}{'recall':>7}{'prec@95%rec':>13}")
    for name in ("test", "live", "human"):
        for h in ("one question", pick):
            rows, s, y = scored(name, h)
            t = P.best_f1_threshold(vy, scored("val", h)[1])
            p, r, f = P.prf(y, s, t)
            print(f"{name:<8}{h:<30}{len(rows):>6}{P.auc(y, s):>7.3f}{f:>6.2f}{p:>6.2f}{r:>7.2f}{P.precision_at_recall(y, s):>13.2f}")


def fair_funnel():
    """The first funnel, redone on the held-out half only: fair identity wording with development-tuned cut-offs, and the fair description wording."""
    dev, held = id_rows("dev"), id_rows("held")
    hi, lo = tune_cutoffs(id_best("u", dev), dev)
    t_desc = up_eval("rules", "dev")["Description"][0]
    best = id_best("u", held)
    ans = P.load_answers(OUT / "fair-up-rules.jsonl")
    cand, _ = up_context()
    rows = [r for r in J.snapshot() if half(r["extracted_id"]) == "held"]
    gem_prose = {i["extracted_id"] for i in P.matched_items() if i["field"] == "Description" and i["gemini"] != "none"}
    c = {"no candidate": 0, "jev: different, create new": 0, "jev: same, no prose needed": 0, "jev: same, a sentence for the description": 0, "jev unsure": 0}
    best_case = 0
    for r in rows:
        eid = r["extracted_id"]
        if not r["candidates"]:
            c["no candidate"] += 1
            continue
        p = best.get(eid)
        if p is None:
            continue
        if p <= lo:
            c["jev: different, create new"] += 1
        elif p < hi:
            c["jev unsure"] += 1
        else:
            a = ans.get(f"{eid}|Description")
            if a and up_p(a, "Description") >= t_desc:
                c["jev: same, a sentence for the description"] += 1
            else:
                c["jev: same, no prose needed"] += 1
            best_case += eid in gem_prose
    n = sum(c.values())
    print(f"RESOLUTION on the held-out half, {n:,} entities. Identity: match >= {hi}, new <= {lo} (tuned on the other half). Description: jev 'adds a fact' >= {t_desc:.2f} (also tuned on the other half).\n")
    for k, v in c.items():
        print(f"  {v:>5,}  {v / n * 100:>4.0f}%  {k}")
    gem = c["jev: same, a sentence for the description"] + c["jev unsure"]
    print(f"\n  Gemini still touches {gem:,} of {n:,} ({gem / n * 100:.0f}%). If jev knew exactly which matches Gemini would rewrite, it would be {(best_case + c['jev unsure']) / n * 100:.0f}%.")


def id_sheet():
    """Every held-out entity where jev (fair wording, tuned cut-offs) and Gemini disagree on match / new, plus a sample of Gemini's 'ambiguous' that jev calls different."""
    import random
    dev, held = id_rows("dev"), id_rows("held")
    hi, lo = tune_cutoffs(id_best("u", dev), dev)
    best = id_best("u", held)
    ans = P.load_answers(OUT / "fair-id-u.jsonl")
    cx = context()
    act = lambda p: "match" if p >= hi else ("new" if p <= lo else "unsure")
    g = lambda r: J.GEM.get(r["gemini"], "other")
    picked = []
    amb_new = []
    for r in held:
        if r["extracted_id"] not in best or g(r) not in ("match", "new", "ambiguous"):
            continue
        a = act(best[r["extracted_id"]])
        if g(r) == "ambiguous" and a == "new":
            amb_new.append(r)
        elif (g(r) != a) and not (g(r) == "ambiguous" and a == "unsure"):
            picked.append(r)
    picked += random.Random(5).sample(amb_new, min(10, len(amb_new)))
    from src.shared.supabase_client import get_client
    cl = get_client()
    aid = {r["extracted_id"]: cx[r["extracted_id"]]["article_id"] for r in picked}
    urls = {a["id"]: a["url"] for a in cl.from_("article").select("id,url").in_("id", list(set(aid.values()))).execute().data}
    out = [f"# Identity, held-out half: where jev (fair wording) and Gemini disagree, {len(picked)} cases", "",
           f"Decide: is the article's entity the same real-world person or body as the record shown?", "",
           f"**How to read jev's number.** It is jev's chance, from 0 to 1, that the article's entity IS the same as the record. 0.04 means jev is 96% sure it is NOT the same; 0.97 means 97% sure it is. "
           f"Cut-offs (tuned on the other half of the data): {hi} or more counts as 'same', {lo} or less as 'different', in between as 'unsure'.", ""]
    random.Random(8).shuffle(picked)
    for i, r in enumerate(picked, 1):
        sc = {c["canonical_uid"]: p_of(ans[f"{r['extracted_id']}|{c['canonical_uid']}"]) for c in r["candidates"]}
        top = max(r["candidates"], key=lambda c: sc[c["canonical_uid"]])
        out += [f"## {i}. {r['name_en'] or r['name']}" + (f" ({r['name']})" if r["name_en"] and r["name_en"] != r["name"] else ""), "",
                f"*{r['published']}* · [{r['title']}]({urls.get(aid[r['extracted_id']], '')})", "",
                f"**What the pipeline pulled from the article:** {r['summary'] or '(empty)'}", ""]
        quote = r["quote_en"] or r["quote"]
        if quote:
            out += [f"> {quote}", ""] + ([f"> {r['quote']}", ""] if r["quote_en"] and J.non_latin(r["quote"]) else [])
        out += [f"**The closest record the search offered** (`{top['canonical_uid']}`): **{top['canonical_name']}**  (jev's chance it is the same: {sc[top['canonical_uid']] * 100:.0f}%)", ""]
        out += [f"- {k}: {v}" for k, v in whole(top.get("canonical_fields")).items()]
        out += ["", f"**Gemini said:** {J.GEM_NAME.get(r['gemini'], r['gemini'])}" + (f" with `{r['gemini_uid']}`" if r["gemini_uid"] else ""), f"> {(r['gemini_why'] or '').strip()[:700]}", "",
                "**Your verdict:**  [ ] Gemini right   [ ] jev right   [ ] both wrong   [ ] cannot tell", "", "---", ""]
    (OUT / "evaluate-identity-fair.md").write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {OUT / 'evaluate-identity-fair.md'} ({len(picked)} cases)")


CMDS = {
    ("identity", "dev"): lambda: [id_run(v, "dev") for v in ("u", "ctx", "score")] and id_dev_report(),
    ("identity", "report"): id_dev_report,
    ("updates", "dev"): lambda: [up_run(v, "dev") for v in ("u", "rules", "choice")] and up_dev_report(),
    ("updates", "report"): up_dev_report,
    ("updates", "held"): up_held,
    ("listwise", "run"): lambda: [listwise_run(), listwise_report()],
    ("listwise", "report"): listwise_report,
    ("funnel", "fair"): fair_funnel,
    ("identity", "sheet"): id_sheet,
    ("relevance", "dev"): lambda: [rel_run("dev"), rel_report("dev")],
    ("relevance", "dev-report"): lambda: rel_report("dev"),
}

if __name__ == "__main__":
    a = tuple(sys.argv[1:3])
    if a in CMDS:
        CMDS[a]()
    elif a[:2] == ("identity", "held") and len(sys.argv) > 3:
        id_held(sys.argv[3])
    elif a[:2] == ("relevance", "held") and len(sys.argv) > 3:
        rel_run("held")
        rel_report("held", sys.argv[3])
    else:
        sys.exit(__doc__)
