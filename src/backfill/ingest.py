"""
Bring the internal model's extraction output into the pipeline's tables.

    python -m src.backfill ingest data/backfill/answers/extraction-1.csv [--limit N] [--dry-run]

Each row is one article with an `entities` cell holding the model's answer.
The answer is validated against the same schema the nightly pipeline
enforces at the API (`ExtractionResponse`); anything that fails is counted
and skipped, never repaired by guesswork. What passes goes through the same
code the nightly path uses -- `build_rows` corrects field names to TTE's and
cleans controlled vocabularies, `save` writes delete-then-insert -- so a row
that arrived by CSV is indistinguishable from one that arrived by API,
except for the `backfill` flag that keeps it out of the nightly queues.

The article has to exist first: extracted_entities.article_id is a foreign
key. Backfill articles are upserted by URL with relevant=true and
processed_extraction=true so no nightly job ever considers them work.
"""

import contextlib
import io
import json
import re
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from src.job2_extraction.update import build_rows, save
from src.shared.models import ExtractionResponse
from src.shared.supabase_client import column_exists, get_client

FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def parse(cell: str):
    """The model's answer as an ExtractionResponse, or the reason it is not."""
    raw = FENCE.sub("", (cell or "").strip())
    if not raw:
        return None, "empty"
    try:
        obj = json.loads(raw)
    except Exception:
        # An answer that starts as JSON and does not parse was cut off by an
        # output limit; one that never starts is the model's analysis in prose.
        return None, "JSON cut off" if raw[:1] in "{[" else "prose, not JSON"
    # The model sometimes returns the list without its wrapper. That is the
    # same answer, so it is read as one; a missing key is not a missing fact.
    if isinstance(obj, list):
        obj = {"entities": obj}
    # The internal model was never asked which entity the article is about;
    # the deck falls back to the headline for these.
    if isinstance(obj, dict):
        for e in obj.get("entities") or []:
            if isinstance(e, dict):
                e.setdefault("role", None)
    try:
        resp = ExtractionResponse.model_validate(obj)
    except Exception as exc:
        first = str(exc).split("\n")[1:2]
        loc = first[0].strip() if first else ""
        if "entities" == loc:
            return None, "echoed the input, no entities list"
        if loc.endswith(("summary", "evidence")):
            return None, "entities lack summary or evidence"
        return None, f"schema: {loc or 'unknown'}"
    return resp, ""


def iso_dates(split_dir: Path | str = "data/backfill/archive") -> dict[str, str]:
    """
    Publication dates by URL from the collected files, which are ISO. The
    results CSV went through Excel and came back as 5/1/2015, which is
    ambiguous between January and May.
    """
    out = {}
    for path in sorted(Path(split_dir).glob("*.csv")):
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=["url", "published"])
        out.update(dict(zip(frame.url, frame.published)))
    return out


def upsert_article(client, row: dict, published: str | None) -> int:
    """The article row a backfill entity hangs off. Returns its id."""
    payload = {
        "url": row["url"],
        "title": row.get("title") or None,
        "description": row.get("description") or None,
        "category": row.get("category") or None,
        "pubDate": published,
        "relevant": True,
        "reason": row.get("reason") or None,
        "text": None,   # the answer file holds it; the table keeps what was extracted
        "processed_extraction": True,
        "backfill": True,
    }
    # Select then insert or update, rather than an upsert that would need a
    # unique constraint on url that the table was not created with.
    found = client.from_("article").select("id").eq("url", row["url"]).limit(1).execute().data
    if found:
        client.from_("article").update(payload).eq("id", found[0]["id"]).execute()
        return int(found[0]["id"])
    got = client.from_("article").insert(payload).execute().data
    return int(got[0]["id"])


def ingest(csv_path: Path | str, limit: int | None = None, dry_run: bool = False,
           workers: int = 4) -> dict:
    # utf-8-sig: the internal system writes a byte-order mark before the first column name.
    frame = pd.read_csv(csv_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if limit:
        frame = frame.head(limit)
    dates = iso_dates()
    client = None if dry_run else get_client()
    if not dry_run and not column_exists("article", "backfill"):
        raise SystemExit("Run sql/09_backfill_flag.sql first: the backfill flag is what keeps "
                         "these rows out of the nightly queues.")

    counts = {"articles": 0, "entities": 0, "skipped": {}, "by_source": {}, "dropped_fields": 0}

    # Validate everything first, in one thread; only what passed is written.
    todo = []
    for row in frame.to_dict("records"):
        resp, why = parse(row.get("entities", ""))
        if resp is None:
            counts["skipped"][why] = counts["skipped"].get(why, 0) + 1
        else:
            todo.append((row, resp))

    # Four sequential requests per article makes one article a second; a
    # few in flight makes it several. Each article is independent and the
    # write is idempotent, so a restart costs nothing.
    def one(item):
        row, resp = item
        published = dates.get(row["url"]) or None
        # A dropped connection under load took a whole run down at article
        # 681. Each article is retried on its own, and a failure is counted,
        # never allowed to end the run; the write is idempotent either way.
        import time
        for attempt in range(4):
            try:
                article_id = 0 if dry_run else upsert_article(client, row, published)
                quiet = io.StringIO()
                with contextlib.redirect_stdout(quiet):
                    rows = build_rows(article_id, resp)
                for r in rows:
                    r["backfill"] = True
                if not dry_run:
                    save(article_id, rows)
                return row.get("source", "?"), len(rows), quiet.getvalue().count("dropped "), None
            except Exception as exc:
                if attempt == 3:
                    return row.get("source", "?"), 0, 0, f"{type(exc).__name__}: {str(exc)[:80]}"
                time.sleep(2 ** attempt)

    from concurrent.futures import ThreadPoolExecutor
    counts["failed"] = {}
    bar = tqdm(total=len(todo), desc="ingest", unit="article", disable=None)
    with ThreadPoolExecutor(max_workers=1 if dry_run else workers) as pool:
        for src, n, dropped, err in pool.map(one, todo):
            if err:
                counts["failed"][err] = counts["failed"].get(err, 0) + 1
            else:
                counts["articles"] += 1
                counts["entities"] += n
                counts["dropped_fields"] += dropped
                counts["by_source"][src] = counts["by_source"].get(src, 0) + 1
            bar.update(1); bar.set_postfix(articles=counts["articles"], entities=counts["entities"],
                                          failed=sum(counts["failed"].values()))
    bar.close()
    return counts
