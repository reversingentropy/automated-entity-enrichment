"""
Files for the Supabase dashboard's CSV importer.

    python -m src.backfill dashboard articles CSV [CSV ...]
    python -m src.backfill dashboard entities CSV [CSV ...]
    python -m src.backfill dashboard resolutions CSV [CSV ...]

The API path (`ingest`, `resolve-import`) writes one article at a time, and
a free-tier connection is closed after 20,000 requests. The dashboard's
importer takes a whole file in one go, but stops at about 10 MB and aborts
on a duplicate key. So this writes the same rows the API path would, in
files under 6 MB, leaving out anything the table already holds.

The order matters. extracted_entities.article_id is a foreign key, so the
articles go in first and get their ids, then the entities are built against
those ids. candidate_matches.extracted_id likewise needs the entities in,
and the `resolved` flag that closes them is set by the SQL written beside
the files, to be run after the import and not before.
"""

import contextlib
import csv
import io
import json
from pathlib import Path

import pandas as pd

from src.backfill.ingest import iso_dates, parse as parse_extraction
from src.backfill.resolve import ENTITY_COLUMNS, load_candidates, parse as parse_resolution
from src.job2_extraction.update import build_rows as entity_rows
from src.job3_resolution.update import build_rows as match_rows
from src.shared.pagination import fetch_all
from src.shared.supabase_client import get_client

MAX_BYTES = 6_000_000

ARTICLE_COLUMNS = ["url", "title", "description", "category", "pubDate", "relevant", "reason",
                   "text", "processed_extraction", "backfill"]
ENTITY_FIELDS = ["article_id", "entity_name", "entity_name_en", "entity_type", "summary",
                 "evidence", "evidence_en", "fields", "confidence", "backfill"]
MATCH_COLUMNS = ["extracted_id", "resolution_action", "matched_uid", "confidence", "reasoning",
                 "field_updates", "inverse_updates", "re_query_term", "duplicate_uids",
                 "candidates", "applied"]


def cell(value):
    """A CSV cell the importer reads back as the column's type: JSON for jsonb,
    True/False for boolean, empty for null (an empty cell became NULL last time)."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def write_parts(out: Path, stem: str, columns: list[str], rows: list[dict]) -> list[tuple[Path, int]]:
    """<stem>-partN.csv, each under MAX_BYTES, utf-8, one header each."""
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob(f"{stem}-part*.csv"):
        old.unlink()
    files: list[tuple[Path, int]] = []
    buf, count, part = io.StringIO(), 0, 1
    writer = csv.DictWriter(buf, fieldnames=columns)
    writer.writeheader()

    def flush():
        nonlocal buf, count, part, writer
        if count == 0:
            return
        path = out / f"{stem}-part{part}.csv"
        path.write_text(buf.getvalue(), encoding="utf-8")
        files.append((path, count))
        part += 1
        buf, count = io.StringIO(), 0
        writer = csv.DictWriter(buf, fieldnames=columns)
        writer.writeheader()

    for row in rows:
        line = io.StringIO()
        csv.DictWriter(line, fieldnames=columns).writerow({k: cell(row.get(k)) for k in columns})
        if count and buf.tell() + len(line.getvalue().encode("utf-8")) > MAX_BYTES:
            flush()
        buf.write(line.getvalue())
        count += 1
    flush()
    return files


def valid_extractions(csvs: list[str]) -> tuple[list[tuple[dict, object]], dict]:
    """Every row whose answer passes the schema, one per URL, with the skip counts."""
    seen: set[str] = set()
    kept, skipped = [], {}
    for path in csvs:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        for row in frame.to_dict("records"):
            resp, why = parse_extraction(row.get("entities", ""))
            if resp is None:
                skipped[why] = skipped.get(why, 0) + 1
            elif row["url"] in seen:
                skipped["duplicate url"] = skipped.get("duplicate url", 0) + 1
            else:
                seen.add(row["url"])
                kept.append((row, resp))
    return kept, skipped


def article_ids() -> dict[str, int]:
    return {a["url"]: int(a["id"]) for a in
            fetch_all(lambda: get_client().from_("article").select("id, url"))}


def articles(csvs: list[str], out: Path | str) -> dict:
    """The article rows for every valid extraction whose URL the table lacks."""
    kept, skipped = valid_extractions(csvs)
    existing = article_ids()
    dates = iso_dates()
    rows, present = [], 0
    for row, _ in kept:
        if row["url"] in existing:
            present += 1
            continue
        published = dates.get(row["url"]) or (row.get("published") or None)
        rows.append({
            "url": row["url"], "title": row.get("title") or None,
            "description": row.get("description") or None, "category": row.get("category") or None,
            "pubDate": published, "relevant": True, "reason": row.get("reason") or None,
            "text": None, "processed_extraction": True, "backfill": True,
        })
    files = write_parts(Path(out), "import-articles", ARTICLE_COLUMNS, rows)
    return {"valid": len(kept), "new": len(rows), "already_present": present,
            "skipped": skipped, "files": files}


def entities(csvs: list[str], out: Path | str) -> dict:
    """The extracted_entities rows, against the article ids the import produced."""
    kept, skipped = valid_extractions(csvs)
    ids = article_ids()
    rows, missing, dropped = [], 0, 0
    for row, resp in kept:
        article_id = ids.get(row["url"])
        if article_id is None:
            missing += 1
            continue
        quiet = io.StringIO()
        with contextlib.redirect_stdout(quiet):
            built = entity_rows(article_id, resp)
        dropped += quiet.getvalue().count("dropped ")
        for r in built:
            r["backfill"] = True
        rows.extend(built)
    files = write_parts(Path(out), "import-entities", ENTITY_FIELDS, rows)
    return {"valid": len(kept), "entities": len(rows), "articles_missing": missing,
            "dropped_fields": dropped, "skipped": skipped, "files": files}


def resolutions(csvs: list[str], out: Path | str,
                sidecar: str = "data/backfill/answers/resolution-candidates.jsonl") -> dict:
    """
    The candidate_matches rows for every answer that passes the schema, built
    by Job 3's own `build_rows` against the entities the model was shown, and
    resolved.sql to close those entities once the rows are in.
    """
    offered = load_candidates(sidecar)
    client = get_client()
    from src.backfill.local_match import Index, load_entities
    index = Index(load_entities())
    search = lambda name, t: index.match(name, 3, t)
    by_article: dict[int, list[dict]] = {}
    for e in fetch_all(lambda: client.from_("extracted_entities").select(ENTITY_COLUMNS)
                       .eq("resolved", False).eq("backfill", True).order("id")):
        by_article.setdefault(int(e["article_id"]), []).append(e)

    rows, closed, skipped, n_articles = [], [], {}, 0
    for path in csvs:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        for row in frame.to_dict("records"):
            resp, why = parse_resolution(row.get("resolutions", ""))
            if resp is None:
                skipped[why] = skipped.get(why, 0) + 1
                continue
            ents = by_article.get(int(row["article_id"]))
            if not ents:
                skipped["article has no unresolved entities"] = \
                    skipped.get("article has no unresolved entities", 0) + 1
                continue
            with contextlib.redirect_stdout(io.StringIO()):
                built = match_rows(resp, ents, {e["id"]: offered.get(e["id"], []) for e in ents}, search=search)
            for r in built:
                r["applied"] = False
            rows.extend(built)
            closed.extend(e["id"] for e in ents)
            n_articles += 1

    out = Path(out)
    files = write_parts(out, "import-resolutions", MATCH_COLUMNS, rows)
    sql = out / "resolved.sql"
    ids = ",".join(str(i) for i in closed)
    sql.write_text(
        "-- Run AFTER every import-resolutions-part*.csv is in candidate_matches.\n"
        "-- Marks the entities those rows resolve, so Job 3 never re-queues them.\n"
        f"update public.extracted_entities set resolved = true where id in ({ids});\n",
        encoding="utf-8")
    return {"articles": n_articles, "proposals": len(rows), "entities_closed": len(closed),
            "skipped": skipped, "files": files, "sql": sql}
