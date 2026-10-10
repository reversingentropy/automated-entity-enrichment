"""
The archive's answers as the reviewers' Excel template, unreviewed.

    python -m src.backfill proposals [--out data/backfill/archive-proposals-unreviewed.xlsx]

Same sheets and columns as the weekly file (src/export/weekly.py), with
Reviewer and Timestamp left empty: nobody has checked these, so nobody's name
is on them. One column is added, Article Date, and rows run latest news
first, since the archive spans a decade. Built from the answer files and a read-only pull of the archive's
entities and article links; nothing is written to the database, which the
archive would outgrow.

The newest round of answers wins for an article answered twice. A match the
model only flagged (ambiguous, a duplicate, worth re-searching) names no
record to change, so it has no row; a confirmed match with nothing to add has
none either.
"""

import contextlib
import datetime as dt
import io
from collections import Counter
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from src.export.cards import DELIMITER, result_of
from src.export.weekly import _NON_LATIN, HEADERS, SGT, write

ROUNDS = ["data/backfill/results/results.csv",          # newest first
          "data/backfill/answers/resolution-1b.csv",
          "data/backfill/answers/resolution-1a.csv"]
OUT = Path("data/backfill/archive-proposals-unreviewed.xlsx")
ARCHIVE_HEADERS = HEADERS[:7] + ["Article Date"] + HEADERS[7:]


def _date(stamp) -> dt.date | None:
    """A publication time as its Singapore date, or None when there is none."""
    try:
        return dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).astimezone(SGT).date()
    except (TypeError, ValueError):
        return None


def _values(text) -> list[str]:
    return [v.strip() for v in str(text or "").split("|") if v.strip()]


def rows_from(rows: list[dict], entities: dict[int, dict], url: str, day: dt.date | None,
              records: dict[str, dict], vocab_for_type: dict[str, str]) -> tuple[list[list], list[list], Counter]:
    """One article's resolution rows, as template rows for existing and new entities."""
    existing, new, skipped = [], [], Counter()
    for r in rows:
        entity = entities.get(r["extracted_id"])
        if entity is None:
            continue
        action = r["resolution_action"]
        if action == "CREATE_NEW":
            name = (f"{entity['entity_name']} ({entity['entity_name_en']})" if entity.get("entity_name_en")
                    else entity["entity_name"])
            vocab = vocab_for_type.get(entity["entity_type"], "")
            fields = {k: v for k, v in (entity.get("fields") or {}).items() if k != "Name" and str(v).strip()}
            for k, v in fields.items():
                new.append(["", name, vocab, k, "", str(v), url, day, "", "", ""])
            if not fields:
                new.append(["", name, vocab, "Name", "", name, url, day, "", "", ""])
            continue
        record = records.get(r.get("matched_uid") or "")
        if action != "MATCH_AND_UPDATE" or record is None:
            skipped[action] += 1
            continue
        uid, rname = record["uid"], record["name"]
        vocab = vocab_for_type.get(record["entity_type"], "")
        updates = r.get("field_updates") or []
        if not updates:
            skipped["match, nothing to add"] += 1
        if updates and _NON_LATIN.search(entity["entity_name"]) and not _NON_LATIN.search(rname):
            existing.append([uid, rname, vocab, "Variant name", "", entity["entity_name"], url, day, "", "", ""])
        for u in updates:
            held = _values((record.get("fields") or {}).get(u["field"]))
            existing.append([uid, rname, vocab, u["field"], DELIMITER.join(held),
                             result_of(u["strategy"], held, u["value"]), url, day, "", "", ""])
    return existing, new, skipped


def build(out: Path = OUT) -> tuple[Path, int, int, Counter]:
    from src.backfill.local_match import Index, load_entities
    from src.backfill.resolve import ENTITY_COLUMNS, load_candidates, parse
    from src.job3_resolution.update import build_rows
    from src.shared.pagination import fetch_all
    from src.shared.supabase_client import get_client

    answers: dict[int, str] = {}
    for f in ROUNDS:
        if Path(f).exists():
            for row in pd.read_csv(f, dtype=str, keep_default_na=False, encoding="utf-8-sig").to_dict("records"):
                answers.setdefault(int(row["article_id"]), row.get("resolutions", ""))

    client = get_client()
    ids = sorted(answers)
    entities_by_article: dict[int, list[dict]] = {}
    urls: dict[int, str] = {}
    dates: dict[int, dt.date | None] = {}
    for i in tqdm(range(0, len(ids), 200), desc="archive entities", unit="batch", disable=None):
        chunk = ids[i:i + 200]
        for e in fetch_all(lambda: client.from_("extracted_entities").select(ENTITY_COLUMNS)
                           .in_("article_id", chunk), order="id"):
            entities_by_article.setdefault(e["article_id"], []).append(e)
        for a in client.from_("article").select('id, url, "pubDate"').in_("id", chunk).execute().data:
            urls[a["id"]] = a.get("url") or ""
            dates[a["id"]] = _date(a.get("pubDate"))

    tte = load_entities()
    index = Index(tte)
    search = lambda name, t: index.match(name, 3, t)
    vocab_for_type = {}
    for t in {e["entity_type"] for e in tte}:
        hit = client.from_("entities").select("vocabulary").eq("entity_type", t).eq("language", "en").limit(1).execute().data
        if hit:
            vocab_for_type[t] = hit[0]["vocabulary"]
    offered = load_candidates("data/backfill/answers/resolution-candidates.jsonl")

    existing, new, skipped, seen = [], [], Counter(), set()
    for article_id in tqdm(ids, desc="archive answers", unit="article", disable=None):
        resp, why = parse(answers[article_id])
        entities = entities_by_article.get(article_id, [])
        if resp is None or not entities:
            skipped["answer unreadable: " + why if resp is None else "article has no entities"] += 1
            continue
        with contextlib.redirect_stdout(io.StringIO()):
            rows = build_rows(resp, entities, {e["id"]: offered.get(e["id"], []) for e in entities}, search=search)
        ex, nw, sk = rows_from(rows, {e["id"]: e for e in entities}, urls.get(article_id, ""),
                               dates.get(article_id), index.by_uid, vocab_for_type)
        skipped.update(sk)
        for sheet, got in ((existing, ex), (new, nw)):
            for row in got:
                key = (row[0] or row[1], row[3], row[5])
                if key not in seen:
                    seen.add(key)
                    sheet.append(row)
    # Latest news first; an undated article last.
    order = lambda row: (-(row[7].toordinal() if row[7] else 0), row[1], row[3])
    return (write(sorted(existing, key=order), sorted(new, key=order), out, ARCHIVE_HEADERS),
            len(existing), len(new), skipped)
