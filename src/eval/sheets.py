"""
The labelled sheets the team fills in, and the key kept back from them.

    python -m src.eval sheets --out data/eval

Three sheets, one per stage, drawn from everything the AI has handled, 2015 to now, each year in
proportion to its size (src/eval/plan.py has the sizes and the maths). Each is an Excel file with the
column to fill left blank and the app's own answer held in a separate key file, so a labeller cannot see
what they are grading. Every sheet carries a `minutes` cell for the time it took, which is the only
figure the team has to remember to write down. Malay and Tamil have a round of their own, later.

Sampling is stratified because positives are rare: about one article in ten is judged relevant, so
labelling at random would spend hours to find a handful of the cases that matter. Each row's weight, in
the key, is how many items like it it stands for; 0-sampling.md records the draw before anyone labels.
"""

import json
import random
import re
import time
from datetime import date
from pathlib import Path

import pandas as pd

from src.eval.online import SECONDS_BETWEEN_PAGES, TEXTS, lang_of
from src.eval.plan import SEED, SHARED, SIZES, allocate
from src.export.cards import IDENTIFYING, plausible
from src.shared.pagination import fetch_all
from src.shared.supabase_client import get_client

RELEVANCE_ANSWERS = Path("data/backfill/answers/relevance.csv")
LANGS = ("en", "zh")     # Malay and Tamil are a round of their own

# The relevance sheet is a stratified sample, in three parts that between them cover every article: what
# the app called relevant, and the two halves of what it rejected, split by whether the article names a
# record TTE holds. The split is mechanical (see NAME_MIN) and applied to every article, so every article
# had a known chance of being drawn and the estimate is unbiased. Misses concentrate in the named half,
# which is why it is sampled harder; its weight puts it back in proportion.
NAME_MIN = 7           # shortest TTE name allowed to mark an article "named"
CJK = re.compile(r"[\u4e00-\u9fff]")
STRATA = {"kept": "the app called it relevant", "named": "rejected, names a TTE record", "other": "rejected, names none"}


# Rows are shuffled before they are written, so the first of them are a random subset: everyone marks
# those, which is what agreement is measured on, and the rest are divided between labellers.
SPLIT = ("Everyone marks the first {shared}; divide the rest between you. They are in random order, "
         "so any block is a fair share.")


def _write(out: Path, stem: str, sheet: pd.DataFrame, key: pd.DataFrame, note: str, shared: str) -> None:
    """The sheet for the team, and the answers held back from it."""
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{stem}.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame({"how long did this take (minutes)": [""],
                      "what to do": [note],
                      "how to share it out": [SPLIT.format(shared=shared)]}).to_excel(
            writer, sheet_name="start here", index=False)
        sheet.to_excel(writer, sheet_name="rows", index=False)
    key.to_json(out / f"{stem}-key.json", orient="records", force_ascii=False, indent=1)
    print(f"  {path}  {len(sheet)} rows      (key: {stem}-key.json)")


def by_year(items: list, year_of, size: int, rng: random.Random, usable=None) -> tuple[list, dict, int]:
    """
    size items drawn at random, each year given rows in proportion to its share (plan.allocate), and the
    weight of each one drawn: how many items of its year it stands for. An item `usable` turns down is
    passed over for the next one drawn from its year. Returns (drawn, {year: [items, drawn]}, passed over).
    """
    years: dict[str, list] = {}
    for x in items:
        years.setdefault(year_of(x), []).append(x)
    got = allocate({y: len(xs) for y, xs in sorted(years.items())}, size)
    drawn, passed = [], 0
    for y, k in got.items():
        xs = list(years[y])
        rng.shuffle(xs)
        took = []
        for x in xs:
            if len(took) == k:
                break
            if usable is None or usable(x):
                took.append(x)
            else:
                passed += 1
        drawn += [(x, len(xs) / len(took)) for x in took]
        got[y] = len(took)
    return drawn, {y: [len(years[y]), got[y]] for y in sorted(years)}, passed


def _record(out: Path, sheet: str, groups: dict) -> None:
    """The draw, kept beside the sheets (0-plan.json) and written up for the paper (0-sampling.md)."""
    path = out / "0-plan.json"
    plan = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    plan[sheet] = {"drawn_on": date.today().isoformat(), "seed": SEED, "groups": groups}
    path.write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")
    _sampling_note(out, plan)


def _names_in_tte() -> set[str]:
    rows = fetch_all(lambda: get_client().from_("entities").select("name,is_active"), order="uid")
    return {r["name"].lower() for r in rows if r.get("is_active") and len(r["name"]) >= NAME_MIN}


def _namer(names: set[str]):
    """
    Whether a text holds any of the names: `any(n in text.lower() for n in names)`, found through each
    name's first NAME_MIN letters so that 300,000 headlines take seconds rather than days.
    """
    heads: dict[str, list[str]] = {}
    for n in names:
        heads.setdefault(n[:NAME_MIN], []).append(n)

    def named(text: str) -> bool:
        t = text.lower()
        return any(t.startswith(n, i) for i in range(len(t) - NAME_MIN + 1) for n in heads.get(t[i:i + NAME_MIN], ()))
    return named


def relevance(out: Path) -> None:
    """A sample of what the app called relevant, and a weighted sample of the rest, from every year."""
    rows = pd.concat(pd.read_csv(RELEVANCE_ANSWERS, dtype=str, keep_default_na=False, encoding="utf-8-sig",
                                 chunksize=100_000,
                                 usecols=["url", "source", "title", "description", "published", "relevant"]))
    rows = rows.drop_duplicates(subset="url")
    rows = rows[[lang_of(u) in LANGS for u in rows.url]]
    if rows.empty:
        raise SystemExit(f"No archive rows in {RELEVANCE_ANSWERS}.")
    said_yes = rows.relevant.str.upper() == "TRUE"

    # The rule that splits the rejects, applied to every one of them: does the title or description name a
    # record TTE holds? Nothing is chosen by hand, so the two halves are populations whose sizes are known.
    named = _namer(_names_in_tte())
    is_named = pd.Series([not y and named(t + " " + d) for y, t, d in zip(said_yes, rows.title, rows.description)],
                         index=rows.index)
    pops = {"kept": rows[said_yes], "named": rows[~said_yes & is_named], "other": rows[~said_yes & ~is_named]}

    rng = random.Random(SEED)
    drawn, groups = [], {}
    for g, pop in pops.items():
        got, years, _ = by_year(list(pop.index), lambda i: rows.published[i][:4] or "unknown", SIZES["relevance"][g], rng)
        drawn += [(i, g, w) for i, w in got]
        groups[g] = {"label": STRATA[g], "population": len(pop), "drawn": len(got), "years": years}
    rng.shuffle(drawn)

    picked = rows.loc[[i for i, _, _ in drawn]]
    sheet = pd.DataFrame({
        "url": picked.url, "source": picked.source, "published": picked.published.str[:10],
        "title": picked.title, "description": picked.description, "relevant": "",
    })
    key = pd.DataFrame({"url": picked.url, "app_said": [g == "kept" for _, g, _ in drawn],
                        "stratum": [STRATA[g] for _, g, _ in drawn], "weight": [round(w, 3) for _, _, w in drawn],
                        "year": picked.published.str[:4].tolist()})
    _write(out, "1-relevance", sheet, key,
           "Fill in 'relevant' with TRUE or FALSE for every row. TRUE = the article names an "
           "entity the authority file holds or should hold, AND reports a fact that would change "
           "or create its record. A mention alone is FALSE. The full rules: docs/labelling-guide.md.",
           f"{SHARED['relevance']} rows")
    _record(out, "relevance", groups)


def _sampling_note(out: Path, plan: dict) -> None:
    """
    How the sheets were drawn, written down before anyone labels them.

    A weighted estimate is only unbiased if the groups were fixed in advance and every item had a known
    chance of being drawn. This file is the record of that, and the paragraph the paper quotes.
    """
    what = {"relevance": ("Relevance", "headlines"), "matching": ("Matching", "decisions"),
            "extraction": ("Extraction", "articles")}
    lines = ["# How the sheets were drawn", "",
             "Every item the AI handled, 2015 to now, in English and Chinese, sat in exactly one group, and each",
             "group was drawn at random with the seed below, each year given rows in proportion to its share",
             "of the group. Nothing was chosen by hand. A row's weight is how many items of its group and year",
             "it stands for.", ""]
    for sheet in ("relevance", "matching", "extraction"):
        if sheet not in plan:
            continue
        name, unit = what[sheet]
        p = plan[sheet]
        lines += [f"## {name} ({p['drawn_on']}, seed `{p['seed']}`)", "",
                  f"| group | {unit} | drawn | each stands for |", "|---|---:|---:|---:|"]
        for g in p["groups"].values():
            stands = g["population"] / g["drawn"] if g["drawn"] else 0
            lines.append(f"| {g['label']} | {g['population']:,} | {g['drawn']} | about {stands:,.0f} |")
        years = sorted({y for g in p["groups"].values() for y in g["years"]})
        lines += ["", "By year, " + unit + " in the group / drawn:", "",
                  "| year | " + " | ".join(g["label"] for g in p["groups"].values()) + " |",
                  "|---|" + "---:|" * len(p["groups"])]
        for y in years:
            lines.append(f"| {y} | " + " | ".join(
                "{:,} / {}".format(*g["years"].get(y, [0, 0])) for g in p["groups"].values()) + " |")
        lines.append("")
    passed = (plan.get("extraction") or {}).get("groups", {})
    if any(g.get("passed_over") for g in passed.values()):
        lines += [f"Extraction articles whose page would not give its text, passed over for the next drawn from "
                  f"the same year: " + ", ".join(f"{g['label']} {g.get('passed_over', 0)}" for g in passed.values()) + ".",
                  "Each drawn article stands for its year's whole group, those included.", ""]
    lines += ["The relevance split between the two rejected groups is mechanical: an article is *named*",
              f"when its title or description contains the name of an active TTE record of at least {NAME_MIN}",
              "characters. Misses concentrate there, which is why it is drawn harder; the weight puts it back",
              "in proportion.", "",
              "Each score's 95% range is worked out from the labels (src/eval/plan.py); `python -m src.eval",
              "check` shows the ranges hold the true value about 95 times in 100.", "",
              "The same sheets are rebuilt with `python -m src.eval sheets`, as long as the AI's answers have",
              "not changed since."]
    (out / "0-sampling.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  {out / '0-sampling.md'}  how the sheets were drawn")


def _fields_line(fields: dict | None) -> str:
    fields = fields or {}
    return " · ".join(f"{k}: {str(fields[k])[:90]}" for k in IDENTIFYING if fields.get(k))


def matching(out: Path) -> None:
    """Pairs the app matched, and pairs it did not, with the sentence each came from, from every year."""
    client = get_client()
    props = fetch_all(lambda: client.from_("candidate_matches")
                      .select("id,extracted_id,resolution_action,matched_uid,reasoning,candidates"))
    ents = {e["id"]: e for e in fetch_all(lambda: client.from_("extracted_entities")
                                          .select("id,article_id,entity_name,entity_name_en,evidence,evidence_en"),
                                          order="id")}
    arts = {a["id"]: a for a in fetch_all(lambda: client.from_("article").select("id,url,title,pubDate"))}
    uids = {p["matched_uid"] for p in props if p["matched_uid"]}
    for p in props:
        for c in (p.get("candidates") or [])[:1]:
            uids.add(c["canonical_uid"])
    records = {}
    uid_list = [u for u in uids if u]
    for start in range(0, len(uid_list), 200):
        for r in (client.from_("entities").select("uid,name,fields")
                  .in_("uid", uid_list[start:start + 200]).execute().data or []):
            records[r["uid"]] = r

    def article(p):
        return arts.get((ents.get(p["extracted_id"]) or {}).get("article_id")) or {}

    def usable(p, uid):
        return p["extracted_id"] in ents and uid in records and lang_of(article(p).get("url") or "") in LANGS

    # The app's "yes": the record it matched. Its "no": the best record it was shown and did not take.
    sides = {"matched": [(p, p["matched_uid"]) for p in props
                         if p["resolution_action"] == "MATCH_AND_UPDATE" and p["matched_uid"]],
             "rejected": [(p, plausible(p["candidates"])[0]["canonical_uid"]) for p in props
                          if p["resolution_action"] == "CREATE_NEW" and plausible(p.get("candidates") or [])]}
    rng = random.Random(SEED)
    picked, groups = [], {}
    for side, pairs in sides.items():
        pairs = [x for x in pairs if usable(*x)]
        got, years, _ = by_year(pairs, lambda x: (article(x[0]).get("pubDate") or "")[:4] or "unknown",
                                SIZES["matching"][side], rng)
        picked += [(p, uid, side, w) for (p, uid), w in got]
        groups[side] = {"label": f"the app {'matched' if side == 'matched' else 'did not match'}",
                        "population": len(pairs), "drawn": len(got), "years": years}
    rng.shuffle(picked)

    rows, key = [], []
    for p, uid, side, w in picked:
        e, rec, art = ents[p["extracted_id"]], records[uid], article(p)
        rows.append({
            "id": p["id"],
            "name": e.get("entity_name", ""),
            "name_in_english": e.get("entity_name_en") or "",
            "evidence": (e.get("evidence_en") or e.get("evidence") or "")[:400],
            "article": art.get("title", ""),
            "url": art.get("url", ""),
            "tte_id": uid,
            "tte_name": rec.get("name", ""),
            "tte_fields": _fields_line(rec.get("fields")),
            "same": "",
        })
        key.append({"id": p["id"], "app_said_same": side == "matched", "tte_id": uid,
                    "script": "chinese" if CJK.search(e.get("entity_name", "")) else "latin",
                    "side": side, "weight": round(w, 3), "year": (art.get("pubDate") or "")[:4]})
    _write(out, "2-matching", pd.DataFrame(rows), pd.DataFrame(key),
           "Fill in 'same' with Y, N or ? for every row. Y = the sentence and the TTE record "
           "describe one and the same person or thing. ? = the row does not carry enough to "
           "decide; it is a real answer and is counted. The full rules: docs/labelling-guide.md.",
           f"{SHARED['matching']} rows")
    _record(out, "matching", groups)


def readable(out: Path, fetch=None, pause: float = SECONDS_BETWEEN_PAGES):
    """
    Whether an article's page gives its text, fetched once, ten seconds apart, and kept beside the sheets
    for the page (online.fetch_texts reads the same file). A missed name cannot be spotted without the
    text, so an article whose page will not give it is passed over for the next one drawn.
    """
    if fetch is None:
        from src.job2_extraction.scraper import scrape as fetch
    path = out / TEXTS
    kept = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    fetched = []

    def check(url: str) -> bool:
        if not kept.get(url):
            if fetched:
                time.sleep(pause)
            fetched.append(url)
            try:
                kept[url] = fetch(url) or ""
            except Exception as exc:
                print(f"  passed over {url}: {exc}")
                kept[url] = ""
            out.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")
        return bool(kept[url].strip())
    return check


def extraction(out: Path, fetch: bool = True) -> None:
    """Articles the app processed, with what it pulled out, to be checked and added to, from every year."""
    client = get_client()
    arts = {a["id"]: a for a in fetch_all(lambda: client.from_("article").select("id,url,title,pubDate"))}
    ents = fetch_all(lambda: client.from_("extracted_entities")
                     .select("id,article_id,entity_name,entity_name_en,entity_type,fields,evidence"),
                     order="id")
    by_article: dict[int, list[dict]] = {}
    for e in ents:
        art = arts.get(e["article_id"])
        if art and lang_of(art.get("url") or "") in LANGS:
            by_article.setdefault(e["article_id"], []).append(e)
    if not by_article:
        raise SystemExit("No processed articles in the database.")

    rng = random.Random(SEED)
    check = readable(out) if fetch else None
    picked, groups = [], {}
    for lang in SIZES["extraction"]:
        pool = sorted(a for a in by_article if lang_of(arts[a].get("url") or "") == lang)
        got, years, passed = by_year(pool, lambda a: (arts[a].get("pubDate") or "")[:4] or "unknown",
                                     SIZES["extraction"][lang], rng,
                                     (lambda a: check(arts[a].get("url") or "")) if check else None)
        picked += [(a, lang, w) for a, w in got]
        groups[lang] = {"label": {"zh": "Chinese articles", "en": "English articles"}[lang],
                        "population": len(pool), "drawn": len(got), "years": years, "passed_over": passed}
    rng.shuffle(picked)

    rows, key = [], []
    for aid, lang, w in picked:
        art = arts[aid]
        for e in by_article[aid]:
            rows.append({
                "article_url": art.get("url", ""), "language": lang, "article": art.get("title", ""),
                "entity": e["entity_name"], "type": e["entity_type"],
                "fields": " · ".join(f"{k}: {v}" for k, v in (e.get("fields") or {}).items() if k != "Name"),
                "evidence": (e.get("evidence") or "")[:300],
                "verdict": "", "field_errors": "", "missed": "",
            })
            key.append({"entity_id": e["id"], "article_id": aid, "article_url": art.get("url", ""), "language": lang,
                        "entity": e["entity_name"], "type": e["entity_type"], "weight": round(w, 3),
                        "year": (art.get("pubDate") or "")[:4]})
        # One blank row per article: where the names it should have found go.
        rows.append({"article_url": art.get("url", ""), "language": lang, "article": art.get("title", ""),
                     "entity": "", "type": "", "fields": "", "evidence": "",
                     "verdict": "", "field_errors": "", "missed": ""})
    _write(out, "3-extraction", pd.DataFrame(rows), pd.DataFrame(key),
           "For each name the app found, put ok / wrong / not_worth in 'verdict', and any field "
           "whose value is wrong in 'field_errors'. On each article's blank last row, put in "
           "'missed' any name the article carries that the app should have found, one per line. "
           "The full rules: docs/labelling-guide.md.",
           f"{SHARED['extraction']} articles")
    _record(out, "extraction", groups)


def logs(out: Path) -> None:
    """The two sheets the team fills in as they work, with one example row each."""
    out.mkdir(parents=True, exist_ok=True)
    changes = pd.DataFrame([{
        "method": "manual", "article_url": "https://www.straitstimes.com/…",
        "tte_entity": "Khaw Boon Wan", "tte_uuid": "18533710", "kind": "amend",
        "field": "Affiliations", "old": "People's Action Party",
        "new": "People's Action Party | SPH Media Trust", "date": "2026-10-14", "who": "Reviewer A",
    }])
    weekly = pd.DataFrame([{"week_start": "2026-10-05", "minutes": 140, "changes": 6,
                            "method": "manual", "user": "Reviewer A"}])
    issues = pd.DataFrame([{"date": "2026-10-06", "what happened": "The deck was empty this morning",
                            "what you were doing": "signed in at 9am", "blocked you": "yes"}])
    path = out / "4-logs.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        changes.to_excel(writer, sheet_name="changes", index=False)
        weekly.to_excel(writer, sheet_name="weekly", index=False)
        issues.to_excel(writer, sheet_name="issues", index=False)
    print(f"  {path}  three tabs, one example row each (delete the examples before use)")


SUS = [
    "I think that I would like to use this system frequently.",
    "I found the system unnecessarily complex.",
    "I thought the system was easy to use.",
    "I think that I would need the support of a technical person to be able to use this system.",
    "I found the various functions in this system were well integrated.",
    "I thought there was too much inconsistency in this system.",
    "I would imagine that most people would learn to use this system very quickly.",
    "I found the system very cumbersome to use.",
    "I felt very confident using the system.",
    "I needed to learn a lot of things before I could get going with this system.",
]


def sus(out: Path) -> None:
    """The ten statements for the Form.gov.sg survey, and how it is scored."""
    out.mkdir(parents=True, exist_ok=True)
    path = out / "5-usability-survey.md"
    lines = ["# Usability survey (SUS)", "",
             "Ten statements, each scored 1 (strongly disagree) to 5 (strongly agree).",
             "Two minutes, at month one and month three.", ""]
    lines += [f"{i}. {s}" for i, s in enumerate(SUS, 1)]
    lines += ["", "## Scoring", "",
              "Odd-numbered statements score (answer − 1); even-numbered score (5 − answer).",
              "Add the ten, multiply by 2.5, for a score out of 100. Around 68 is average;",
              "above 80 is good. Report the mean across reviewers and the change between",
              "month one and month three."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  {path}  ten statements and the scoring")
