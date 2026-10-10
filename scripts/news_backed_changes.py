"""
How many of the team's own changes to TTE had the pipeline already read in the news?

The TTE exports in data/previous_dumps are snapshots, September 2024 to
September 2026. Between two snapshots, a value that appears on a record is a
change the team made. This finds the changes for which an archive article,
published before the change, said the same thing about the same record, and
the pipeline extracted it and matched it to that record.

For each record the archive matched, each fact the article gave, and the
snapshots either side of the article's date:

    absent in the snapshot before the article,
    present in the snapshot after it          ->  a news-backed change

Counted per (period, record, field), against every change the team made to
the same fields in the same periods. It is a floor, not a rate: only articles
the archive extracted can count (12,447 of 27,941 judged relevant), a value
written differently in TTE than in the article may not be recognised, and
changes the team made from other sources are in the denominator by design.

Only fields news changes are counted (NEWS_FIELDS). Name, description,
nationality and country are left out: a match on those says little about
whether the news drove the change. New records are not counted either.

    uv run python scripts/news_backed_changes.py

Reads the dumps and the archive's answer files, and the archive's entities
and article dates from the database (read-only). Writes the matches to
data/coverage/news-backed-changes.csv and a summary to
data/coverage/news-backed-changes.txt.
"""

import contextlib
import csv
import io
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DUMPS = ROOT / "data" / "previous_dumps"
OUT = ROOT / "data" / "coverage"
CACHE = OUT / "archive-matches.json"

NEWS_FIELDS = ["Occupation", "Affiliations(groupName)", "Awards", "Title", "Achievements",
               "Death Year (yyyy)", "Birth Year (yyyy)", "Parent Organisation",
               "Year Started (yyyy)", "Year Ended (yyyy)", "Year Completed (yyyy)", "Street Address"]
YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")


# ---- the snapshots -------------------------------------------------------------

def snapshots(with_names=False):
    """
    [(date, {uid: {field: [values]}})] for English records, oldest first. With
    `with_names`, [(date, records, {uid: {name, ...}})]: every name, in any
    language, that resolves to the record, its own included.
    """
    from src.load_tte.dump import expand
    from src.load_tte.parse import parse

    out = []
    for path in sorted(DUMPS.glob("TTE-DELTA_*.zip")):
        day = date(int(path.stem[-8:-4]), int(path.stem[-4:-2]), int(path.stem[-2:]))
        csvs, _, _ = expand(path.read_bytes())
        records, names = {}, defaultdict(set)
        for name, text in csvs:
            for uid, entity in parse(name, text).entities.items():
                names[entity.canonical_uid or uid].add(entity.name)
                if entity.language != "en":
                    continue
                fields = {f: [v.strip() for v in entity.fields[f].split(" | ") if v.strip()]
                          for f in NEWS_FIELDS if entity.fields.get(f)}
                records[uid] = fields
        out.append((day, records, dict(names)) if with_names else (day, records))
        print(f"  {day}: {len(records):,} English records", flush=True)
    return out


def team_changes(snaps):
    """
    Every change the team made to these fields, as {period: {(uid, field)}} and
    a count by field. A change is a value present after that was not there
    before, on a record that existed before. A value only reworded ("Workers'
    Party" to "Workers' Party (Singapore)") is not a new fact and not counted.
    """
    team, by_field = defaultdict(set), Counter()
    for k in range(1, len(snaps)):
        before, after = snaps[k - 1][1], snaps[k][1]
        for uid, fields in after.items():
            if uid not in before:
                continue                 # a new record: not counted here
            for f, values in fields.items():
                old = before[uid].get(f, [])
                added = [v for v in values if v not in set(old)]
                if any(not any(same(v, o, f) for o in old) for v in added):
                    team[k].add((uid, f))
                    by_field[f] += 1
    return team, by_field


# ---- the archive's matches -----------------------------------------------------

def archive_matches():
    """[{uid, day, url, entity, fields}] for every archive entity matched to a record."""
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    import pandas as pd

    from src.backfill.local_match import Index, load_entities
    from src.backfill.proposals import ROUNDS, _date
    from src.backfill.resolve import ENTITY_COLUMNS, load_candidates, parse
    from src.job3_resolution.update import build_rows
    from src.shared.pagination import fetch_all
    from src.shared.supabase_client import get_client

    answers = {}
    for f in ROUNDS:
        if (ROOT / f).exists():
            for row in pd.read_csv(ROOT / f, dtype=str, keep_default_na=False, encoding="utf-8-sig").to_dict("records"):
                answers.setdefault(int(row["article_id"]), row.get("resolutions", ""))
    client = get_client()
    ids = sorted(answers)
    entities, urls, days = defaultdict(list), {}, {}
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        for e in fetch_all(lambda: client.from_("extracted_entities").select(ENTITY_COLUMNS)
                           .in_("article_id", chunk), order="id"):
            entities[e["article_id"]].append(e)
        for a in client.from_("article").select('id, url, "pubDate"').in_("id", chunk).execute().data:
            urls[a["id"]] = a.get("url") or ""
            days[a["id"]] = _date(a.get("pubDate"))
        print(f"  entities for {min(i + 200, len(ids)):,} / {len(ids):,} articles", end="\r", flush=True)
    print()
    index = Index(load_entities())
    search = lambda name, t: index.match(name, 3, t)
    offered = load_candidates(str(ROOT / "data/backfill/answers/resolution-candidates.jsonl"))

    matches = []
    for article_id in ids:
        resp, _ = parse(answers[article_id])
        ents = entities.get(article_id, [])
        if resp is None or not ents or days.get(article_id) is None:
            continue
        with contextlib.redirect_stdout(io.StringIO()):
            rows = build_rows(resp, ents, {e["id"]: offered.get(e["id"], []) for e in ents}, search=search)
        by_id = {e["id"]: e for e in ents}
        for r in rows:
            e = by_id.get(r["extracted_id"])
            if r["resolution_action"] != "MATCH_AND_UPDATE" or not r.get("matched_uid") or e is None:
                continue
            matches.append({"uid": r["matched_uid"], "day": days[article_id].isoformat(),
                            "url": urls.get(article_id, ""), "entity": e["entity_name"],
                            "fields": {f: v for f, v in (e.get("fields") or {}).items() if f in NEWS_FIELDS and v}})
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(matches, ensure_ascii=False), encoding="utf-8")
    return matches


# ---- comparing a fact with a record --------------------------------------------

def norm(value):
    text = re.sub(r"\((?!\d)[^)]*\)", " ", str(value).casefold())   # "Perkamus (Association)", but keep "(2016)"
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"^singapore\s+", "", " ".join(text.split()))   # TTE writes "Singapore. Ministry of Health"
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
                    for w in text.split())                        # "Awards" and "Award"


def same(article_value, record_value, field):
    """Whether the article's value and the record's value are the same fact."""
    if field.endswith("(yyyy)"):
        a, b = YEAR.findall(str(article_value)), YEAR.findall(str(record_value))
        return bool(a) and a[:1] == b[:1]
    a, b = norm(article_value), norm(record_value)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    # One inside the other, when the shorter is a name and not a word: "Public
    # Service Commission" in "Singapore. Public Service Commission".
    if len(short.split()) >= 2 and f" {short} " in f" {long_} ":
        return True
    ta, tb = set(a.split()), set(b.split())
    return len(ta & tb) / len(ta | tb) >= 0.75


def news_backed(snaps, matches, team):
    """
    The team's changes the pipeline had already read: an archive article said
    it, the record lacked it before the article, and had it in the next
    snapshot. Returns ({(period, uid, field): row}, matches examined).
    """
    days = [s[0] for s in snaps]
    hits, examined = {}, 0
    for m in matches:
        day = date.fromisoformat(m["day"])
        if not (days[0] <= day < days[-1]) or not m["fields"]:
            continue
        k = next(i for i in range(1, len(days)) if day < days[i])   # first snapshot after the article
        before, after = snaps[k - 1][1], snaps[k][1]
        if m["uid"] not in before or m["uid"] not in after:
            continue
        examined += 1
        for f, raw in m["fields"].items():
            for v in [x.strip() for x in str(raw).split("|") if x.strip()]:
                had = any(same(v, w, f) for w in before[m["uid"]].get(f, []))
                got = next((w for w in after[m["uid"]].get(f, []) if same(v, w, f)), None)
                if not had and got and (m["uid"], f) in team[k]:
                    key = (k, m["uid"], f)
                    if key not in hits:
                        hits[key] = {"period": f"{days[k - 1]} to {days[k]}", "uid": m["uid"], "field": f,
                                     "article_value": v, "record_value": got, "article_day": m["day"],
                                     "entity": m["entity"], "url": m["url"]}
    return hits, examined


def main():
    print("Reading the TTE snapshots ...", flush=True)
    snaps = snapshots()
    days = [d for d, _ in snaps]
    print("Reading the archive's matches ...", flush=True)
    matches = archive_matches()

    team, team_by_field = team_changes(snaps)
    team_total = sum(len(s) for s in team.values())
    hits, examined = news_backed(snaps, matches, team)

    by_field = Counter(h["field"] for h in hits.values())
    lines = [
        f"Snapshots: {len(snaps)}, {days[0]} to {days[-1]} ({len(snaps) - 1} periods)",
        f"Team changes to existing records, these fields, adding a fact and not only rewording one: "
        f"{team_total:,} (period, record, field)",
        f"Archive matches examined (matched, with facts in these fields, dated inside the snapshots): {examined:,}",
        f"News-backed: {len(hits):,} of the team's {team_total:,} changes "
        f"({len(hits) / max(team_total, 1):.1%}) were reported by an article the pipeline had extracted and matched, "
        f"before the change appeared in TTE",
        "",
        f"{'field':<26}{'team changes':>14}{'news-backed':>13}",
    ]
    for f in NEWS_FIELDS:
        if team_by_field[f] or by_field[f]:
            lines.append(f"{f:<26}{team_by_field[f]:>14,}{by_field[f]:>13,}")
    lines += ["", "Examples:"]
    for h in list(hits.values())[:12]:
        lines.append(f"  {h['period']}  {h['entity']} [{h['field']}]  article ({h['article_day']}): "
                     f"{h['article_value'][:50]}  ->  TTE: {h['record_value'][:50]}")
    summary = "\n".join(lines)
    print(summary)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "news-backed-changes.txt").write_text(summary + "\n", encoding="utf-8")
    with open(OUT / "news-backed-changes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["period", "uid", "field", "article_value", "record_value",
                                          "article_day", "entity", "url"])
        w.writeheader()
        w.writerows(hits.values())


if __name__ == "__main__":
    main()
