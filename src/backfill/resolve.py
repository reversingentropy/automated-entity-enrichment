"""
Resolution for backfill entities, by export to an internal model and import.

    python -m src.backfill resolve-export [--out data/backfill/results] [--limit N]
    python -m src.backfill resolve-import data/backfill/results/resolve-answers.csv [--dry-run]

Gemini's free tier cannot resolve eight thousand articles, so the judgement
runs elsewhere and everything around it stays here. Export builds, for every
unresolved backfill entity, exactly what Job 3 would have sent: the entity,
and its candidates from `candidates_for` with the ranking and the dead
removed. One JSON object per article, grouped as Job 3 groups them, since
the entities of one article are mutually informative. Import validates the
answer with `ResolutionResponse`, then writes through Job 3's own
`build_rows` and `save`: the uid must be one that was offered, field names
are corrected, a description rewrite is judged, and an entity the model
left out gets its CREATE_NEW row rather than silence.

The candidates each entity was offered are kept in a sidecar, because the
import has to check the answer against the question that was actually asked.
"""

import json
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from src.job3_resolution.candidates import candidates_for
from src.job3_resolution.prompt import build_entity_block
from src.job3_resolution.update import build_rows, save
from src.shared.models import ResolutionResponse
from src.shared.pagination import fetch_all
from src.shared.supabase_client import column_exists, get_client

ENTITY_COLUMNS = ("id, article_id, entity_name, entity_name_en, entity_type, "
                  "summary, evidence, fields")


def unresolved_backfill(limit_articles: int | None = None) -> list[dict]:
    """Backfill articles with unresolved entities, each with its entities and year."""
    client = get_client()
    if not column_exists("extracted_entities", "backfill"):
        raise SystemExit("Run sql/09_backfill_flag.sql first.")
    rows = fetch_all(lambda: client.from_("extracted_entities").select(ENTITY_COLUMNS)
                     .eq("resolved", False).eq("backfill", True).order("article_id"))
    by_article: dict[int, list[dict]] = {}
    for r in rows:
        by_article.setdefault(r["article_id"], []).append(r)
    ids = sorted(by_article)
    if limit_articles:
        ids = ids[:limit_articles]
    meta: dict[int, dict] = {}
    for start in range(0, len(ids), 200):
        chunk = ids[start:start + 200]
        for a in (client.from_("article").select("id, title, pubDate").in_("id", chunk).execute().data or []):
            year = str(a.get("pubDate") or "")[:4]
            meta[a["id"]] = {"title": a.get("title") or "", "year": int(year) if year.isdigit() else None}
    return [{"article_id": aid, "title": meta.get(aid, {}).get("title", ""),
             "year": meta.get(aid, {}).get("year"), "entities": by_article[aid]} for aid in ids]


# The internal system reads a CSV, applies the model to one cell per row
# under a system prompt, and writes the answer beside it. So the export is
# one row per article with everything the model needs in one cell.
COLUMNS = ["article_id", "title", "n_entities", "input"]
CSV_ROWS_PER_FILE = 49_999


def export(out_dir: Path | str, limit_articles: int | None = None, workers: int = 8,
           sidecar: Path | str = "data/backfill/answers/resolution-candidates.jsonl") -> dict:
    """
    resolve-NNN.csv: one row per article, `input` holding that article's
    entities and their candidates as the JSON array the prompt describes.
    The sidecar: what each entity was offered, for the import to check against.
    """
    import csv, time
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    articles = unresolved_backfill(limit_articles)

    # Resume: every article already in a resolve-NNN.csv is skipped, and the
    # last file is appended to. Supabase closes a connection after 20,000
    # requests on it, which ended the first run a third of the way through.
    done: set[int] = set()
    files = sorted(out.glob("resolve-*.csv"))
    for f in files:
        with f.open(encoding="utf-8", newline="") as fh:
            done.update(int(r["article_id"]) for r in csv.DictReader(fh))
    articles = [a for a in articles if a["article_id"] not in done]
    part = len(files) or 1
    rows_in_part = 0
    if files:
        with files[-1].open(encoding="utf-8", newline="") as fh:
            rows_in_part = sum(1 for _ in csv.DictReader(fh))
    written = entities = 0

    def opened(n, append=False):
        path = out / f"resolve-{n:03d}.csv"
        new = not (append and path.exists())
        fh = path.open("a" if append else "w", encoding="utf-8", newline="")
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        return fh, w

    handle, writer = opened(part, append=bool(files))
    Path(sidecar).parent.mkdir(parents=True, exist_ok=True)
    sidecar = Path(sidecar).open("a", encoding="utf-8")

    # Retrieval against an in-memory copy of the authority file: no RPC, no
    # connection to drop, a few milliseconds an entity.
    from src.backfill.local_match import Index, load_entities
    index = Index(load_entities())

    def retrieve(article):
        return [candidates_for(e, article["year"], lookup=index.match) for e in article["entities"]]

    try:
        for a in tqdm(articles, desc="resolve-export", unit="article", disable=None):
            blocks = []
            for e, cands in zip(a["entities"], retrieve(a)):
                blocks.append(build_entity_block(e, cands, a["title"]))
                sidecar.write(json.dumps({"extracted_id": e["id"], "article_id": a["article_id"],
                                          "candidates": cands}, ensure_ascii=False) + "\n")
                entities += 1
            if rows_in_part >= CSV_ROWS_PER_FILE:
                handle.close(); part += 1; rows_in_part = 0
                handle, writer = opened(part)
            writer.writerow({"article_id": a["article_id"], "title": a["title"],
                             "n_entities": len(blocks),
                             "input": json.dumps(blocks, ensure_ascii=False)})
            rows_in_part += 1
            written += 1
    finally:
        handle.close(); sidecar.close()
    return {"articles": written, "entities": entities, "files": part, "skipped_done": len(done)}


def load_candidates(sidecar: Path | str) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    with Path(sidecar).open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rec = json.loads(line)
                out[rec["extracted_id"]] = rec["candidates"]
    return out


def parse(cell: str):
    """The model's answer as a ResolutionResponse, or why it is not."""
    import re
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", (cell or "").strip())
    if not raw:
        return None, "empty"
    try:
        obj = json.loads(raw)
    except Exception:
        return None, "JSON cut off" if raw[:1] in "{[" else "prose, not JSON"
    if isinstance(obj, list):  # the list without its wrapper is the same answer
        obj = {"resolutions": obj}
    try:
        return ResolutionResponse.model_validate(obj), ""
    except Exception as exc:
        first = str(exc).split("\n")[1:2]
        return None, "schema: " + (first[0].strip() if first else "unknown")


def import_answers(csv_path: Path | str, sidecar: Path | str = "data/backfill/answers/resolution-candidates.jsonl",
                   dry_run: bool = False) -> dict:
    """
    A CSV with `article_id` and `resolutions` (the model's JSON) per row.

    Every entity of the article is fetched again from the database, so an
    entity the model left out still gets its CREATE_NEW row, exactly as in
    the nightly path.
    """
    frame = pd.read_csv(csv_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    offered = load_candidates(sidecar)
    client = get_client()
    from src.backfill.local_match import Index, load_entities
    index = Index(load_entities())
    search = lambda name, t: index.match(name, 3, t)
    counts = {"articles": 0, "proposals": 0, "skipped": {}}
    for row in tqdm(frame.to_dict("records"), desc="resolve-import", unit="article", disable=None):
        resp, why = parse(row.get("resolutions", ""))
        if resp is None:
            counts["skipped"][why] = counts["skipped"].get(why, 0) + 1
            continue
        article_id = int(row["article_id"])
        entities = (client.from_("extracted_entities").select(ENTITY_COLUMNS)
                    .eq("article_id", article_id).execute().data or [])
        if not entities:
            counts["skipped"]["article has no entities in the database"] = \
                counts["skipped"].get("article has no entities in the database", 0) + 1
            continue
        cands = {e["id"]: offered.get(e["id"], []) for e in entities}
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            rows = build_rows(resp, entities, cands, search=search)
        if not dry_run:
            save([e["id"] for e in entities], rows)
        counts["articles"] += 1
        counts["proposals"] += len(rows)
    return counts
