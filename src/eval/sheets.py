"""
The labelled sheets the team fills in, and the key kept back from them.

    python -m src.eval sheets --window 2026-08 --out data/eval

Three sheets, one per stage, drawn from one month of the feed. Each is an
Excel file with the column to fill left blank and the app's own answer held
in a separate key file, so a labeller cannot see what they are grading.
Every sheet carries a `minutes` cell for the time it took, which is the
only figure the team has to remember to write down.

Sampling is stratified because positives are rare: about one article in
nine is judged relevant, so labelling a month at random would spend ten
hours to find a handful of the cases that matter. See docs/evaluation.md
for what each sheet produces and how recall is weighted back.
"""

import json
import random
import re
from pathlib import Path

import pandas as pd

from src.export.cards import IDENTIFYING, plausible
from src.shared.pagination import fetch_all
from src.shared.supabase_client import get_client

RELEVANCE_ANSWERS = Path("data/backfill/answers/relevance.csv")
SEED = 20260824
SHARED = 50          # rows every labeller gets, for agreement between them

# The relevance sheet is a stratified sample of one month, in three parts that
# between them cover every article: what the app called relevant, and the two
# halves of what it rejected, split by whether the article names a record TTE
# holds. The split is mechanical (see NAME_MIN) and applied to the whole
# month, so every article had a known chance of being drawn and the estimate
# is unbiased. Misses concentrate in the named half, which is why it is
# sampled harder; its weight puts it back in proportion.
N_NAMED_REJECT = 200   # of the rejects that name a TTE record
N_OTHER_REJECT = 300   # of the rejects that do not
NAME_MIN = 7           # shortest TTE name allowed to mark an article "named"
N_MATCH = 150          # per side of the matching sheet
N_ARTICLES = 60        # articles on the extraction sheet
CJK = re.compile(r"[一-鿿]")


# Rows are shuffled before they are written, so the first SHARED of them are a
# random subset: everyone marks those, which is what agreement is measured on,
# and the rest are divided between labellers.
SPLIT = ("Everyone marks rows 1 to {shared}; divide the rest between you. The rows are in "
         "random order, so any block is a fair share.")


def _write(out: Path, stem: str, sheet: pd.DataFrame, key: pd.DataFrame, note: str) -> None:
    """The sheet for the team, and the answers held back from it."""
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{stem}.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame({"how long did this take (minutes)": [""],
                      "what to do": [note],
                      "how to share it out": [SPLIT.format(shared=SHARED)]}).to_excel(
            writer, sheet_name="start here", index=False)
        sheet.to_excel(writer, sheet_name="rows", index=False)
    key.to_json(out / f"{stem}-key.json", orient="records", force_ascii=False, indent=1)
    print(f"  {path}  {len(sheet)} rows      (key: {stem}-key.json)")


def _names_in_tte() -> set[str]:
    rows = fetch_all(lambda: get_client().from_("entities").select("name,is_active"), order="uid")
    return {r["name"].lower() for r in rows if r.get("is_active") and len(r["name"]) >= NAME_MIN}


def relevance(window: str, out: Path) -> None:
    """Every article the app called relevant, plus a weighted sample of the rest."""
    keep = []
    for chunk in pd.read_csv(RELEVANCE_ANSWERS, dtype=str, keep_default_na=False,
                             encoding="utf-8-sig", chunksize=100_000,
                             usecols=["url", "source", "title", "description", "published", "relevant"]):
        hit = chunk[chunk.published.str[:7] == window]
        if len(hit):
            keep.append(hit)
    if not keep:
        raise SystemExit(f"No archive rows for {window}. Is {RELEVANCE_ANSWERS} the right file?")
    month = pd.concat(keep).drop_duplicates(subset="url")
    said_yes = month[month.relevant.str.upper() == "TRUE"]
    said_no = month[month.relevant.str.upper() != "TRUE"]

    # The rule that splits the rejects, applied to every one of them: does the
    # title or description name a record TTE holds? Nothing is chosen by hand,
    # so the two halves are populations whose sizes are known exactly.
    tte = _names_in_tte()
    said_no = said_no.assign(_named=[any(n in (row.title + " " + row.description).lower()
                                         for n in tte) for row in said_no.itertuples()])
    named_pop, other_pop = said_no[said_no._named], said_no[~said_no._named]

    rng = random.Random(SEED)

    def draw(frame, size):
        idx = list(frame.index)
        rng.shuffle(idx)
        return frame.loc[idx[:min(size, len(idx))]]

    named, other = draw(named_pop, N_NAMED_REJECT), draw(other_pop, N_OTHER_REJECT)

    # Every article in the month sits in exactly one stratum, and a stratum's
    # weight is how many articles each row drawn from it stands for.
    strata = {"the app called it relevant": (said_yes, len(said_yes)),
              "rejected, names a TTE record": (named, len(named_pop)),
              "rejected, names none": (other, len(other_pop))}
    of_row, weights = {}, {}
    for label, (sample, population) in strata.items():
        weights[label] = round(population / max(len(sample), 1), 3)
        for url in sample.url:
            of_row[url] = label

    rows = pd.concat([said_yes, named, other])
    order = list(rows.index)
    rng.shuffle(order)
    rows = rows.loc[order]
    sheet = pd.DataFrame({
        "url": rows.url, "source": rows.source, "published": rows.published.str[:10],
        "title": rows.title, "description": rows.description, "relevant": "",
    })
    key = pd.DataFrame({"url": rows.url, "app_said": rows.relevant.str.upper() == "TRUE",
                        "stratum": [of_row[u] for u in rows.url],
                        "weight": [weights[of_row[u]] for u in rows.url]})
    _write(out, "1-relevance", sheet, key,
           "Fill in 'relevant' with TRUE or FALSE for every row. TRUE = the article names an "
           "entity the authority file holds or should hold, AND reports a fact that would change "
           "or create its record. A mention alone is FALSE.")
    _sampling_note(out, window, len(month), strata, weights)


def _sampling_note(out: Path, window: str, month: int, strata: dict, weights: dict) -> None:
    """
    How the relevance sheet was drawn, written down before anyone labels it.

    A stratified estimate is only unbiased if the strata were fixed in advance
    and every article had a known chance of being drawn. This file is the
    record of that, and the paragraph the paper quotes.
    """
    lines = [f"# How the relevance sheet was sampled ({window})", "",
             f"Articles the feed carried in {window}: **{month}**. Each sits in exactly one of",
             "three strata, and each stratum was sampled at random with the seed below. No",
             "article was chosen by hand.", "",
             "| stratum | in the month | sampled | each row stands for |",
             "|---|---|---|---|"]
    for label, (sample, population) in strata.items():
        lines.append(f"| {label} | {population} | {len(sample)} | {weights[label]} |")
    lines += ["",
              "The split between the two rejected strata is mechanical: an article is *named*",
              f"when its title or description contains the name of an active TTE record of at",
              f"least {NAME_MIN} characters. Misses concentrate there, which is why it is sampled",
              "harder; the weight puts it back in proportion.", "",
              f"Random seed: `{SEED}`. The identical sheet is rebuilt with",
              f"`python -m src.eval sheets --window {window}`.", "",
              "## How the numbers come out", "",
              "**Precision** is a census of the first stratum, so it needs no weighting: of the",
              "articles the app called relevant, the share a labeller also called relevant.", "",
              "**Recall** is weighted. A labelled miss in a rejected stratum stands for the number",
              "in the last column, so recall is (weighted articles the app caught) divided by",
              "(weighted articles a labeller called relevant). The interval printed beside it is a",
              "95% interval on that estimate, and it is wider than the sample size alone suggests,",
              "because a weighted miss moves it by more than one article.", ""]
    (out / "0-sampling.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  {out / '0-sampling.md'}  how the sample was drawn")


def _fields_line(fields: dict | None) -> str:
    fields = fields or {}
    return " · ".join(f"{k}: {str(fields[k])[:90]}" for k in IDENTIFYING if fields.get(k))


def matching(out: Path) -> None:
    """Pairs the app matched, and pairs it did not, with the sentence each came from."""
    client = get_client()
    props = fetch_all(lambda: client.from_("candidate_matches")
                      .select("id,extracted_id,resolution_action,matched_uid,reasoning,candidates"))
    ents = {e["id"]: e for e in fetch_all(lambda: client.from_("extracted_entities")
                                          .select("id,article_id,entity_name,entity_name_en,evidence,evidence_en"),
                                          order="id")}
    arts = {a["id"]: a for a in fetch_all(lambda: client.from_("article").select("id,url,title"))}
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

    matched = [p for p in props if p["resolution_action"] == "MATCH_AND_UPDATE" and p["matched_uid"]]
    # The app's "no": the best record it was shown and did not take.
    rejected = [p for p in props if p["resolution_action"] == "CREATE_NEW" and plausible(p.get("candidates") or [])]

    rng = random.Random(SEED)
    rng.shuffle(matched)
    rng.shuffle(rejected)
    picked = []
    for p in matched[:N_MATCH]:
        picked.append((p, p["matched_uid"], True))
    for p in rejected[:N_MATCH]:
        picked.append((p, plausible(p["candidates"])[0]["canonical_uid"], False))
    rng.shuffle(picked)

    rows, key = [], []
    for p, uid, said_same in picked:
        e = ents.get(p["extracted_id"]) or {}
        rec = records.get(uid) or {}
        if not e or not rec:
            continue
        art = arts.get(e.get("article_id"), {})
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
        key.append({"id": p["id"], "app_said_same": said_same, "tte_id": uid,
                    "script": "chinese" if CJK.search(e.get("entity_name", "")) else "latin"})
    _write(out, "2-matching", pd.DataFrame(rows), pd.DataFrame(key),
           "Fill in 'same' with Y, N or ? for every row. Y = the sentence and the TTE record "
           "describe one and the same person or thing. ? = the row does not carry enough to "
           "decide; it is a real answer and is counted.")


def extraction(window: str, out: Path) -> None:
    """Articles the app processed, with what it pulled out, to be checked and added to."""
    client = get_client()
    arts = {a["id"]: a for a in fetch_all(lambda: client.from_("article").select("id,url,title,pubDate"))}
    ents = fetch_all(lambda: client.from_("extracted_entities")
                     .select("id,article_id,entity_name,entity_name_en,entity_type,fields,evidence"),
                     order="id")
    by_article: dict[int, list[dict]] = {}
    for e in ents:
        art = arts.get(e["article_id"])
        if art and (art.get("pubDate") or "")[:7] == window:
            by_article.setdefault(e["article_id"], []).append(e)
    if not by_article:
        raise SystemExit(f"No processed articles dated {window}.")

    chinese = [a for a in by_article if "zaobao" in (arts[a].get("url") or "")]
    other = [a for a in by_article if a not in chinese]
    rng = random.Random(SEED)
    rng.shuffle(chinese)
    rng.shuffle(other)
    half = N_ARTICLES // 2
    picked = chinese[:half] + other[:N_ARTICLES - min(half, len(chinese))]
    picked = picked[:N_ARTICLES]
    rng.shuffle(picked)

    rows, key = [], []
    for aid in picked:
        art = arts[aid]
        lang = "zh" if "zaobao" in (art.get("url") or "") else "en"
        for e in by_article[aid]:
            rows.append({
                "article_url": art.get("url", ""), "language": lang, "article": art.get("title", ""),
                "entity": e["entity_name"], "type": e["entity_type"],
                "fields": " · ".join(f"{k}: {v}" for k, v in (e.get("fields") or {}).items() if k != "Name"),
                "evidence": (e.get("evidence") or "")[:300],
                "verdict": "", "field_errors": "", "missed": "",
            })
            key.append({"entity_id": e["id"], "article_id": aid, "language": lang,
                        "entity": e["entity_name"], "type": e["entity_type"]})
        # One blank row per article: where the names it should have found go.
        rows.append({"article_url": art.get("url", ""), "language": lang, "article": art.get("title", ""),
                     "entity": "", "type": "", "fields": "", "evidence": "",
                     "verdict": "", "field_errors": "", "missed": ""})
    _write(out, "3-extraction", pd.DataFrame(rows), pd.DataFrame(key),
           "For each name the app found, put ok / wrong / not_worth in 'verdict', and any field "
           "whose value is wrong in 'field_errors'. On each article's blank last row, put in "
           "'missed' any name the article carries that the app should have found, one per line.")


def logs(out: Path) -> None:
    """The two sheets the team fills in as they work, with one example row each."""
    out.mkdir(parents=True, exist_ok=True)
    changes = pd.DataFrame([{
        "method": "manual", "article_url": "https://www.straitstimes.com/…",
        "tte_entity": "Khaw Boon Wan", "tte_uuid": "18533710", "kind": "amend",
        "field": "Affiliations", "old": "People's Action Party",
        "new": "People's Action Party | SPH Media Trust", "date": "2026-10-14", "who": "Yaw Huah",
    }])
    weekly = pd.DataFrame([{"week_start": "2026-10-05", "minutes": 140, "changes": 6,
                            "method": "manual", "user": "Yaw Huah"}])
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
