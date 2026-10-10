"""
What does the pipeline look like if jev (TypeSafe) does everything it can, and Gemini does only what jev cannot?

jev answers typed questions (yes/no probabilities, choices); it writes no text. So every stage is tested as "which of its
decisions can jev make", using the project's own prompts for the wording where they exist. Nothing is written to the
database. Every call is cached under data/jev/, so a stopped run resumes and a re-run costs nothing.

    .venv/bin/python scripts/jev_pipeline.py relevance pilot     # wording check on a validation sample
    .venv/bin/python scripts/jev_pipeline.py relevance run       # live feed, human labels, a test sample
    .venv/bin/python scripts/jev_pipeline.py relevance report

What goes to TypeSafe, per stage: relevance, the headline and RSS description (what Gemini sees today); the later stages,
English summaries, translated quotes and public TTE record fields. Article bodies are never sent.
"""

import json
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jev_replay as J                                          # the client, retry and cost meter

ROOT = J.ROOT
OUT = J.OUT
WORKERS = 20
try:
    from tqdm import tqdm
except ImportError:
    tqdm = None


# ---- a resumable runner for any list of (key, state, questions) ------------------------------

def run_jobs(path: Path, jobs, label):
    done = set()
    if path.exists():
        done = {json.loads(line)["key"] for line in path.read_text(encoding="utf-8").splitlines()}
    todo = [j for j in jobs if j[0] not in done]
    print(f"{label}: {len(todo):,} calls to make ({len(done):,} already done)", flush=True)
    if not todo:
        return
    token = J.key()
    client = httpx.Client(limits=httpx.Limits(max_connections=WORKERS * 2))
    lock, errors = threading.Lock(), []
    out = open(path, "a", encoding="utf-8")

    def one(job):
        key, state, qs = job
        answers = J.ask(client, token, state, qs, raw=True)
        with lock:
            out.write(json.dumps({"key": key, "answers": answers}, ensure_ascii=False) + "\n")
            out.flush()

    t0 = time.time()
    pool = ThreadPoolExecutor(max_workers=WORKERS)
    futures = [pool.submit(one, j) for j in todo]
    bar = tqdm(total=len(futures), desc=label, unit=" calls", dynamic_ncols=True) if tqdm else None
    try:
        for i, f in enumerate(as_completed(futures), 1):
            try:
                f.result()
            except RuntimeError as e:
                errors.append(str(e))
                if len(errors) >= 25 or "HTTP 401" in str(e) or "HTTP 422" in str(e):
                    print(f"\nstopping: {e}", flush=True)
                    break
            if bar:
                bar.update(1)
            elif i % 1000 == 0:
                print(f"  {i:,}/{len(futures):,}", flush=True)
    except KeyboardInterrupt:
        print("\nCtrl+C: keeping what is done; run again to resume", flush=True)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        out.close()
        if bar:
            bar.close()
    secs = time.time() - t0
    print(f"{J.METER.calls:,} calls in {secs:.0f}s, {J.METER.tokens:,} tokens = ${J.METER.tokens * J.PRICE_PER_TOKEN:.3f}; {len(errors)} errors" + (f" e.g. {errors[0]}" if errors else ""), flush=True)


def load_answers(path: Path) -> dict:
    if not path.exists():
        return {}
    return {d["key"]: d["answers"] for d in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())}


# ---- metrics (numpy only: the project's benchmark helpers need torch and sklearn, which are not installed here) -----------

def auc(y, s):
    y, s = np.asarray(y), np.asarray(s)
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s))
    ranks[order] = np.arange(1, len(s) + 1)
    for v in np.unique(s):                          # average the ranks of ties
        m = s == v
        if m.sum() > 1:
            ranks[m] = ranks[m].mean()
    pos = y.sum()
    neg = len(y) - pos
    return float((ranks[y == 1].sum() - pos * (pos + 1) / 2) / (pos * neg)) if pos and neg else float("nan")


def prf(y, s, t):
    y, pred = np.asarray(y), np.asarray(s) >= t
    tp, fp, fn = int(((pred) & (y == 1)).sum()), int(((pred) & (y == 0)).sum()), int(((~pred) & (y == 1)).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def best_f1_threshold(y, s):
    best = (0.0, 0.5)
    for t in np.unique(np.round(np.asarray(s), 3)):
        f = prf(y, s, t)[2]
        if f > best[0]:
            best = (f, float(t))
    return best[1]


def precision_at_recall(y, s, target=0.95):
    y, s = np.asarray(y), np.asarray(s)
    best = 0.0
    for t in np.unique(np.round(s, 3)):
        p, r, _ = prf(y, s, t)
        if r >= target:
            best = max(best, p)
    return best


# ---- stage 1: relevance -------------------------------------------------------------------

def relevance_question(variant="A"):
    """Wording taken from prompts/relevance.txt itself, so a change to the prompt flows through. The output-format paragraph is dropped (jev has its own)."""
    text = (ROOT / "prompts" / "relevance.txt").read_text(encoding="utf-8").replace("\r\n", "\n")
    body = text.split("OUTPUT INSTRUCTIONS")[0]
    needed = body.split("A knowledge base update is needed when")[1].split("NOT needed when:")[0]
    not_needed, singapore = body.split("NOT needed when:")[1].split("The entity must be Singaporean:")
    intro = ("Given a Singapore news headline and its short description, decide whether the article likely contains information that would require "
             "updating a record in Singapore's national knowledge base.")
    if variant == "A":
        return {"relevant": {"type": "noul", "instructions": intro,
                             "criteria": {"true": "A knowledge base update is needed when" + needed.rstrip() + "\nThe entity must be Singaporean:" + singapore.rstrip(),
                                          "false": "Not needed when:" + not_needed.rstrip()}}}
    return {"relevant": {"type": "noul", "instructions": intro + "\n\n" + body.split("Given a Singapore news headline, decide whether this article likely contains information that would require updating a record in Singapore's national knowledge base.")[-1].strip()}}


def load_set(name):
    return [json.loads(line) for line in (ROOT / "data" / "finetune" / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()]


def relevance_sets(for_run=False):
    rng = random.Random(3)
    val, test, live, human = (load_set(n) for n in ("val", "test", "live", "human"))
    sets = {"val": rng.sample(val, 3000), "live": live, "human": human, "test": rng.sample(test, 6000)}
    return sets


def relevance_pilot():
    rng = random.Random(5)
    val = load_set("val")
    pos = [r for r in val if r["label"] == 1]
    neg = [r for r in val if r["label"] == 0]
    sample = rng.sample(pos, 200) + rng.sample(neg, 400)
    for variant in ("A", "B"):
        qs = relevance_question(variant)
        run_jobs(OUT / f"relevance-pilot-{variant}.jsonl", [(r["url"], r["text"], qs) for r in sample], f"relevance pilot {variant}")
    for variant in ("A", "B"):
        ans = load_answers(OUT / f"relevance-pilot-{variant}.jsonl")
        y = [r["label"] for r in sample]
        s = [ans[r["url"]]["relevant"]["noul"] for r in sample]
        zh = [r["lang"] == "zh" for r in sample]
        print(f"variant {variant}: AUC {auc(y, s):.3f}   AUC English {auc([a for a, z in zip(y, zh) if not z], [a for a, z in zip(s, zh) if not z]):.3f}   AUC Chinese {auc([a for a, z in zip(y, zh) if z], [a for a, z in zip(s, zh) if z]):.3f}")


def relevance_run(variant="A"):
    qs = relevance_question(variant)
    for name, rows in relevance_sets().items():
        run_jobs(OUT / f"relevance-{variant}.jsonl", [(f"{name}:{r['url']}", r["text"], qs) for r in rows], f"relevance {name}")


def relevance_report(variant="A"):
    ans = load_answers(OUT / f"relevance-{variant}.jsonl")
    sets = relevance_sets()

    def scored(name):
        rows = [r for r in sets[name] if f"{name}:{r['url']}" in ans]
        return rows, np.array([ans[f"{name}:{r['url']}"]["relevant"]["noul"] for r in rows]), np.array([r["label"] for r in rows])

    vr, vs, vy = scored("val")
    t_f1 = best_f1_threshold(vy, vs)
    # the same operating point the fine-tuned model is judged at: the threshold that keeps 95% of relevant articles, chosen on validation
    cands = np.unique(np.round(vs, 3))
    t_r95 = max((t for t in cands if prf(vy, vs, t)[1] >= 0.95), default=0.0)
    print(f"jev relevance (variant {variant}); thresholds chosen on {len(vr):,} validation articles: best-F1 {t_f1:.3f}, 95%-recall {t_r95:.3f}\n")
    print(f"{'set':<22}{'n':>6}{'pos%':>6}{'AUC':>7}{'F1':>6}{'prec':>6}{'recall':>7}{'prec@95%rec':>13}{'F1 en':>7}{'F1 zh':>7}   reference (fine-tuned mmBERT-small)")
    ref = {"test": "F1 0.75, precision at 95% recall 0.39, en 0.71 / zh 0.77", "live": "F1 0.55 vs Gemini", "human": "F1 0.22 vs people"}
    for name in ("test", "live", "human"):
        rows, s, y = scored(name)
        if not len(rows):
            continue
        p, r, f = prf(y, s, t_f1)
        zh = np.array([x["lang"] == "zh" for x in rows])
        fe = prf(y[~zh], s[~zh], t_f1)[2] if (~zh).sum() else float("nan")
        fz = prf(y[zh], s[zh], t_f1)[2] if zh.sum() else float("nan")
        print(f"{name:<22}{len(rows):>6}{y.mean() * 100:>6.1f}{auc(y, s):>7.3f}{f:>6.2f}{p:>6.2f}{r:>7.2f}{precision_at_recall(y, s):>13.2f}{fe:>7.2f}{fz:>7.2f}   {ref.get(name, '')}")
    # the cost of recall: how many articles per hundred reach the next stage at 95% recall
    for name in ("test", "live"):
        rows, s, y = scored(name)
        if len(rows):
            kept = (s >= t_r95).mean()
            print(f"  at the 95%-recall threshold, {name}: {kept * 100:.0f}% of articles pass on to extraction (Gemini passes about {y.mean() * 100:.0f}% )")



# ---- stage 5: field updates on a matched record ----------------------------------------------
#
# Today Gemini, having matched an entity, decides field by field what to add, what to replace and how to rewrite the description.
# What code can already do alone: say what the article would ADD to each field (cards.delta; no model). What it cannot is say
# whether the addition deserves recording, and whether the quote supports it. Those two are jev's: a yes/no and a choice.

def matched_items():
    """One item per (matched entity, field) where the article proposes something the record does not hold."""
    from src.export import cards
    rows = json.loads((OUT / "matched.json").read_text(encoding="utf-8"))
    snap = {r["extracted_id"]: r for r in J.snapshot()}
    items = []
    for r in rows:
        cand = next((c for c in r["candidates"] if c["canonical_uid"] == r["gemini_uid"]), None)
        e, sn = r["ext"], snap.get(r["extracted_id"])
        if not (cand and e and sn):
            continue
        held = cand["canonical_fields"] or {}
        ups = {u["field"]: u for u in r["field_updates"]}
        for d in cards.delta(e["fields"] or {}, held):
            if d["state"] == "same":
                continue
            u = ups.get(d["field"])
            added = None
            if d["field"] == "Description" and u:
                added = " ".join(p["text"] for p in cards.diff_parts(held.get("Description") or "", u["value"]) if p["op"] == "in") or None
            items.append({"key": f"{r['extracted_id']}|{d['field']}", "extracted_id": r["extracted_id"], "field": d["field"], "state": d["state"],
                          "gemini": u["strategy"] if u else "none", "gemini_value": (added if d["field"] == "Description" else u["value"]) if u else None,
                          "fresh": d["fresh"], "have": d["have"], "record": cand["canonical_name"], "record_uid": cand["canonical_uid"],
                          "name": sn["name_en"] or sn["name"], "type": sn["type"], "zh": J.non_latin(sn["name"]), "published": sn["published"],
                          "summary": sn["summary"], "quote": sn["quote_en"] or (sn["quote"] if not J.non_latin(sn["quote"]) else None)})
    return items


def update_questions(item):
    kind = J.KIND.get(item["type"], item["type"].lower())
    if item["field"] == "Description":
        return {"adds_new_fact": {"type": "noul",
                                  "instructions": f"Does the article state a fact about this {kind} that the authority record's description does not already say? Rephrasing or background detail is not a new fact.",
                                  "criteria": {"true": "A post, appointment, departure, death, award, rename, relocation or similar change that the description does not mention.",
                                               "false": "The description already records it, or the article only repeats background."}}}
    return {"worth_recording": {"type": "noul",
                                "instructions": f"Should the proposed value be added to the authority record's '{item['field']}' field for this {kind}?",
                                "criteria": {"true": "It is a lasting fact about this entity that the record does not already hold.",
                                             "false": "It is already recorded, incidental, temporary, or only loosely connected to this entity."}}}


EVIDENCE = {"type": "choice", "instructions": "Does the quote from the article support the proposed addition to the record?",
            "criteria": {"supports": "The quote states, or directly implies, the proposed addition about this entity.",
                         "contradicts": "The quote says something different about this entity: another date, name, place, post or number.",
                         "says_nothing": "The quote does not mention the proposed addition."}}


def update_job(item):
    state = {"entity_in_the_article": {"name": item["name"], "article_published": item["published"], "what_the_article_says": item["summary"], **({"quote_from_article": item["quote"]} if item["quote"] else {})},
             "authority_record": {"name": item["record"], item["field"]: item["have"][:700] or "(empty)"}}
    qs = update_questions(item)
    if item["gemini"] != "none" and item["gemini_value"] and item["quote"]:
        state["proposed_addition"] = {item["field"]: item["gemini_value"][:500]}
        qs["evidence"] = EVIDENCE
    elif item["field"] != "Description":
        state["proposed_addition"] = {item["field"]: item["fresh"][:500]}
        if item["quote"]:
            qs["evidence"] = EVIDENCE
    return item["key"], state, qs


def updates_run():
    items = matched_items()
    print(f"{len(items):,} (entity, field) proposals: {sum(i['field'] == 'Description' for i in items):,} descriptions, {sum(i['field'] != 'Description' for i in items):,} other fields")
    run_jobs(OUT / "updates.jsonl", [update_job(i) for i in items], "field updates")


def confusion(rows, label, scorer, thresholds=(0.5,)):
    """rows: items; label(row)->bool (Gemini applied it); scorer(row)->jev probability."""
    y = np.array([label(r) for r in rows])
    s = np.array([scorer(r) for r in rows])
    out = [f"  jev's AUC for 'Gemini applied it': {auc(y, s):.3f} over {len(rows):,} proposals ({y.mean() * 100:.0f}% applied by Gemini)"]
    for t in thresholds:
        p, r, f = prf(y, s, t)
        tp, fp = int(((s >= t) & y).sum()), int(((s >= t) & ~y).sum())
        fn, tn = int(((s < t) & y).sum()), int(((s < t) & ~y).sum())
        out.append(f"  at {t:.2f}: both apply {tp:,} · jev yes/Gemini no {fp:,} · jev no/Gemini yes {fn:,} · both skip {tn:,}   (agreement {(tp + tn) / len(y) * 100:.1f}%)")
    return "\n".join(out)


def updates_report():
    items = {i["key"]: i for i in matched_items()}
    ans = load_answers(OUT / "updates.jsonl")
    got = [items[k] | {"a": a} for k, a in ans.items() if k in items]
    desc = [i for i in got if i["field"] == "Description"]
    other = [i for i in got if i["field"] != "Description"]
    print(f"{len(got):,} proposals scored by jev\n")
    print("DESCRIPTION: does the article add a fact the description lacks? (Gemini wrote a rewrite: yes; left it alone: no)")
    print(confusion(desc, lambda r: r["gemini"] != "none", lambda r: r["a"]["adds_new_fact"]["noul"], (0.3, 0.5, 0.7)))
    print(f"  English-sourced / Chinese-sourced AUC: {auc([i['gemini'] != 'none' for i in desc if not i['zh']], [i['a']['adds_new_fact']['noul'] for i in desc if not i['zh']]):.3f} / {auc([i['gemini'] != 'none' for i in desc if i['zh']], [i['a']['adds_new_fact']['noul'] for i in desc if i['zh']]):.3f}")
    print("\nOTHER FIELDS: should the proposed value be recorded? (code alone proposes every difference; Gemini applied the share shown)")
    print(confusion(other, lambda r: r["gemini"] != "none", lambda r: r["a"]["worth_recording"]["noul"], (0.3, 0.5, 0.7)))
    for field in ("Affiliations(groupName)", "Occupation", "Title", "Awards"):
        sub = [i for i in other if i["field"] == field]
        if len(sub) > 20:
            print(f"    {field:<26} n={len(sub):>4}  Gemini applied {sum(i['gemini'] != 'none' for i in sub) / len(sub) * 100:>3.0f}%   jev AUC {auc([i['gemini'] != 'none' for i in sub], [i['a']['worth_recording']['noul'] for i in sub]):.3f}")
    print("\nQUOTE SUPPORT: does the article's own quote back what is proposed?")
    for title, sel in (("proposals Gemini applied", [i for i in got if i["gemini"] != "none" and "evidence" in i["a"]]),
                       ("proposals Gemini left out", [i for i in got if i["gemini"] == "none" and "evidence" in i["a"]])):
        if not sel:
            continue
        c = {k: sum(i["a"]["evidence"]["choice"] == k for i in sel) for k in ("supports", "contradicts", "says_nothing")}
        print(f"  {title} (n={len(sel):,}): supports {c['supports'] / len(sel) * 100:.0f}% · says nothing {c['says_nothing'] / len(sel) * 100:.0f}% · contradicts {c['contradicts'] / len(sel) * 100:.0f}%")
    for who in ("Tang See Chim", "Anita Fam", "Schooling"):
        for i in got:
            if who.lower() in (i["name"] or "").lower() and "evidence" in i["a"]:
                ev = i["a"]["evidence"]
                print(f"  known case, {i['name']} · {i['field']} · Gemini {i['gemini']}: jev says {ev['choice']} ({ev['confidence']:.2f})  proposed: {(i['gemini_value'] or i['fresh'])[:110]!r}")



# ---- stage 2: extraction ------------------------------------------------------------------
#
# Extraction is generative: Gemini reads an article and writes entity names, English summaries and field values. jev writes
# no text, so the test is the part of extraction that is a decision. A jev-first version splits it:
#   find mentions  -> code: look the authority file's own names (and its Chinese variants) up in the article text
#   judge each one -> jev: "does this sentence report a concrete change to this entity?"
# Whatever that cannot do (an entity the file does not hold yet; English names for Chinese articles; field values) stays Gemini's.

def gazetteer():
    """surface form (lower case) -> set of canonical uids, from every active record and variant name in the authority file."""
    from src.export import cards
    records, variants = cards.build_index(with_variants=True)
    table = {}

    def add(surface, uid):
        surface = " ".join(surface.split()).casefold()
        if J.non_latin(surface):
            if len(surface) < 3:
                return
        elif len(surface.split()) < 2 or len(surface) < 7:
            return
        table.setdefault(surface, set()).add(uid)

    def forms(name):
        name = re.sub(r"\s*\([^)]*\)", "", name or "").strip()
        out = {name}
        if "," in name and not J.non_latin(name):
            last, _, rest = name.partition(",")
            rest = rest.split(",")[0].strip()
            out |= {f"{rest} {last}", f"{last} {rest}"}
        if ". " in name:
            out.add(name.split(". ", 1)[1])
        return {f.strip() for f in out if f.strip()}

    for uid, name, *_ in records:
        for f in forms(name):
            add(f, uid)
    for name, uid, _ in variants:
        for f in forms(name):
            add(f, uid)
    return table, {r[0]: r[1] for r in records}


def mentions(text, table):
    """{uid: surface} for every authority name found in the text."""
    found = {}
    low = text.casefold()
    words = [(m.group(), m.start()) for m in re.finditer(r"[\w'’.-]+", low)]
    for i in range(len(words)):
        for n in range(6, 1, -1):
            if i + n > len(words):
                continue
            surface = " ".join(w for w, _ in words[i:i + n]).strip(".")
            uids = table.get(surface)
            if uids:
                for u in uids:
                    found.setdefault(u, surface)
    for run in re.finditer(r"[\u3400-\u9fff]+", text):
        seg = run.group()
        for i in range(len(seg)):
            for n in range(8, 2, -1):
                uids = table.get(seg[i:i + n])
                if uids:
                    for u in uids:
                        found.setdefault(u, seg[i:i + n])
    return found


def sentences_with(text, surface, limit=2):
    parts = re.split(r"(?<=[.!?。！？])\s*|\n+", text)
    hits = [p.strip() for p in parts if surface.casefold() in p.casefold() and len(p.strip()) > 8]
    return hits[:limit]


CHANGE_Q = {"concrete_change": {"type": "noul",
                                "instructions": "Does the text report a concrete, current or immediate change to this entity: a person who died, was appointed, retired, married or received a named award or honour; an organisation, building, place, event, programme or law that was created, merged, closed, renamed, relocated, opened, awarded, launched, ended, enacted, amended or repealed? Merely mentioning the entity, quoting it or commenting is not a change.",
                                "criteria": {"true": "The text states a change of this kind about this entity.",
                                             "false": "The entity is only mentioned, quoted, commenting, or part of background."}}}


TYPES = {"PERSON": "A named individual.", "ORGANISATION": "A Singapore institution or company.", "FACILITY": "A named Singapore building or structure.",
         "LOCATION": "A named Singapore place or area.", "EVENT": "A named Singapore event or competition.", "AWARD": "A named Singapore award.",
         "PROGRAMME": "A named Singapore government programme.", "LEGAL_ACT": "A named Singapore law or piece of legislation."}


def extract_questions():
    return {"entity_type": {"type": "choice", "instructions": "What kind of entity is the named entity in this sentence?", "criteria": TYPES},
            "is_subject": {"type": "noul", "instructions": "Is the named entity what this sentence is mainly about (the one appointed, honoured, renamed, or who died), rather than someone or something merely mentioned alongside?",
                           "criteria": {"true": "The sentence reports something happening to this entity.", "false": "The entity is named in passing, quoted, or commenting."}},
            **CHANGE_Q}


def extract_rows():
    """Every stored extraction with its evidence sentence, Gemini's type and role, and what the authority file would find in that sentence."""
    from src.shared.supabase_client import get_client
    from src.shared.pagination import fetch_all
    cl = get_client()
    meta = {e["id"]: e for e in fetch_all(lambda: cl.from_("extracted_entities").select("id,role,entity_type"))}
    rows = []
    for r in J.snapshot():
        m = meta.get(r["extracted_id"], {})
        sentence = r["quote_en"] or (r["quote"] if not J.non_latin(r["quote"]) else None)
        if not sentence:
            continue
        rows.append({"extracted_id": r["extracted_id"], "name": r["name_en"] or r["name"], "type": m.get("entity_type") or r["type"], "role": m.get("role"), "gemini": r["gemini"], "gemini_uid": r["gemini_uid"],
                     "zh": J.non_latin(r["name"]), "title": r["title"], "published": r["published"], "sentence": sentence, "original": r["quote"], "summary": r["summary"],
                     "record": next((c["canonical_name"] for c in r["candidates"] if c["canonical_uid"] == r["gemini_uid"]), None)})
    return rows


def extract_run():
    rows = extract_rows()
    qs = extract_questions()
    run_jobs(OUT / "extract.jsonl", [(str(r["extracted_id"]), {"article_headline": r["title"], "named_entity": r["name"], "sentence_from_the_article": r["sentence"]}, qs) for r in rows], "extraction judgements")


def extract_report():
    rows = extract_rows()
    ans = load_answers(OUT / "extract.jsonl")
    got = [r | {"a": ans[str(r["extracted_id"])]} for r in rows if str(r["extracted_id"]) in ans]
    print(f"{len(got):,} stored extractions judged by jev (Gemini's evidence sentence, English)\n")
    typed = [r for r in got if r["type"] in TYPES]
    agree = sum(r["a"]["entity_type"]["choice"] == r["type"] for r in typed)
    print(f"ENTITY TYPE: jev picks the same type as Gemini for {agree / len(typed) * 100:.1f}% ({agree:,}/{len(typed):,})")
    for ty in TYPES:
        sub = [r for r in typed if r["type"] == ty]
        if len(sub) >= 20:
            print(f"    {ty:<13} {sum(r['a']['entity_type']['choice'] == ty for r in sub) / len(sub) * 100:>5.1f}%  of {len(sub):,}")
    withrole = [r for r in got if r["role"] in ("subject", "mentioned")]
    y = [r["role"] == "subject" for r in withrole]
    s = [r["a"]["is_subject"]["noul"] for r in withrole]
    print(f"\nSUBJECT OR MENTIONED: Gemini marked {sum(y):,} of {len(y):,} as subject. jev AUC {auc(y, s):.3f}")
    for t in (0.5, 0.7):
        p, rc, f = prf(y, s, t)
        print(f"    jev >= {t}: precision {p * 100:.0f}%, recall {rc * 100:.0f}% for 'subject'")
    cc = np.array([r["a"]["concrete_change"]["noul"] for r in got])
    print(f"\nCONCRETE CHANGE: of the sentences Gemini based an extraction on, jev says there is a concrete change in {(cc >= 0.5).mean() * 100:.0f}% (>=0.5), {(cc >= 0.8).mean() * 100:.0f}% (>=0.8); {(cc < 0.2).sum():,} read as 'only mentioned' (<0.2)")
    subj = [r for r in withrole if r["role"] == "subject"]
    ment = [r for r in withrole if r["role"] == "mentioned"]
    for nm, sel in (("Gemini's subjects", subj), ("Gemini's 'mentioned'", ment)):
        v = np.array([r["a"]["concrete_change"]["noul"] for r in sel])
        print(f"    {nm}: jev sees a concrete change in {(v >= 0.5).mean() * 100:.0f}% ({len(sel):,})")
    # what the authority file alone finds in the sentence: can code spot the entity without a model?
    table, names = gazetteer()
    m = [r for r in got if r["gemini"] == "MATCH_AND_UPDATE" and r["gemini_uid"]]
    hit = {"en": [0, 0], "zh": [0, 0]}
    for r in m:
        k = "zh" if r["zh"] else "en"
        found = mentions(f"{r['title']}\n{r['original']}\n{r['sentence']}", table)
        hit[k][1] += 1
        hit[k][0] += r["gemini_uid"] in found
    print(f"\nSPOTTING THE ENTITY WITHOUT A MODEL: in the evidence sentence and headline, the authority file's own names (plus its Chinese variants) find the record Gemini matched in "
          f"{(hit['en'][0] + hit['zh'][0]) / len(m) * 100:.0f}% of {len(m):,} (English-named {hit['en'][0] / max(hit['en'][1], 1) * 100:.0f}%, Chinese-named {hit['zh'][0] / max(hit['zh'][1], 1) * 100:.0f}%).")
    new = sum(r["gemini"] == "CREATE_NEW" for r in got)
    print(f"  And {new:,} of {len(got):,} extractions ({new / len(got) * 100:.0f}%) are entities with no record yet: a name list cannot find those at all.")
    return got


STAGES_NOTE = None

# ---- the whole pipeline: how much stays with Gemini -----------------------------------------

def funnel():
    """Entity by entity, who has to decide: nobody (code), jev, or Gemini. Gemini's own stored answers are the yardstick, not the truth."""
    snap = J.snapshot()
    pairs = J.load_pairs()
    upd = {}
    for k, a in load_answers(OUT / "updates.jsonl").items():
        eid, field = k.split("|", 1)
        upd.setdefault(int(eid), {})[field] = a
    n = len(snap)
    c = {"new_no_candidates": 0, "new_by_jev": 0, "match_code_only": 0, "match_needs_prose": 0, "gemini_band": 0, "other": 0}
    for r in snap:
        if not r["candidates"]:
            c["new_no_candidates"] += 1
            continue
        act, uid, p, _ = J.decide(r, pairs.get(r["extracted_id"], {}))
        if act == "new":
            c["new_by_jev"] += 1
        elif act == "ambiguous":
            c["gemini_band"] += 1
        elif act == "match":
            a = upd.get(r["extracted_id"], {}).get("Description")
            needs_prose = bool(a) and a["adds_new_fact"]["noul"] >= 0.7
            c["match_needs_prose" if needs_prose else "match_code_only"] += 1
        else:
            c["other"] += 1
    print(f"RESOLUTION, {n:,} entities, if jev decides identity (match >= 0.8, new <= 0.2) and Gemini is kept only where jev cannot do the job:")
    rows = [("new, no candidate in the file (no model needed)", "new_no_candidates"), ("jev says a different entity: create new (no Gemini)", "new_by_jev"),
            ("jev says same; nothing to write in prose; code applies the lists and links (no Gemini)", "match_code_only"),
            ("jev says same; a sentence must go into the description (Gemini writes it)", "match_needs_prose"), ("jev unsure of identity (Gemini decides)", "gemini_band")]
    for label, k in rows:
        print(f"  {c[k]:>5,}  {c[k] / n * 100:>4.0f}%  {label}")
    gem = c["match_needs_prose"] + c["gemini_band"]
    print(f"  => Gemini still touches {gem:,} of {n:,} entities ({gem / n * 100:.0f}%) at the resolution stage; today it touches all of them.")


STAGES = {"relevance": {"pilot": relevance_pilot, "run": relevance_run, "report": relevance_report},
          "updates": {"run": updates_run, "report": updates_report},
          "extract": {"run": extract_run, "report": extract_report},
          "funnel": {"report": funnel}}

if __name__ == "__main__":
    a = sys.argv[1:]
    fn = STAGES.get(a[0] if a else "", {}).get(a[1] if len(a) > 1 else "")
    if not fn:
        sys.exit(__doc__)
    fn()
