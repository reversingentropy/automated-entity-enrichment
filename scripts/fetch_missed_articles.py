"""
Bring in the articles the feeds missed: each outlet's own archive for the months given, against what `article` holds.

    uv run python scripts/fetch_missed_articles.py --from 2026-08              # dry run: what is missing, nothing written
    uv run python scripts/fetch_missed_articles.py --from 2026-08 --apply      # insert them, unjudged, for Job 1

A feed holds only its newest items (Zaobao 24, CNA 20, The Straits Times 50), and read twice a day it moved past
articles before they were read: in October 2026, 1,066 Singapore articles published since 1 August had never been
stored, nine in ten of them Zaobao. The archives are the ones src/backfill reads: CNA's search index, and the ST and
Zaobao monthly sitemaps. An article counts as held when any stored article is the same story (src/shared/stories.py).

CNA's index carries each title and description. For ST and Zaobao they come from the September archive run's file
(data/backfill/answers/relevance.csv) when it has the article, and otherwise from the page, read as the backfill did;
what was read is kept in data/backfill/missed-meta.json, so a second run reads nothing twice. The articles go in
through the ingest's own insert, oldest first, so the copy check applies and each is unjudged: Job 1 judges every
article of the live period, these included. The ids written are saved to data/backups/.
"""

import argparse
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backfill import cna, sitemaps  # noqa: E402
from src.backfill.months import span  # noqa: E402
from src.job0_ingest.update import insert_new_articles  # noqa: E402
from src.shared.pagination import fetch_all  # noqa: E402
from src.shared.stories import outlet, story_key  # noqa: E402
from src.shared.supabase_client import column_exists, get_client  # noqa: E402

SEPTEMBER = ROOT / "data" / "backfill" / "answers" / "relevance.csv"
CACHE = ROOT / "data" / "backfill" / "missed-meta.json"
WORKERS = 6


def archive(since: str, to: str) -> list[dict]:
    rows = []
    for y, m in span(since, to):
        rows += [{**r, "src": "cna"} for r in cna.collect(y, m)]
        for source in ("st", "zb"):
            rows += [{**r, "src": source} for r in sitemaps.collect(source, y, m)]
    return rows


def september() -> dict[str, dict]:
    """Titles and descriptions the September archive run already read, by story key."""
    if not SEPTEMBER.exists():
        return {}
    csv.field_size_limit(sys.maxsize)
    with SEPTEMBER.open(encoding="utf-8") as fh:
        return {story_key(r["url"]): r for r in csv.DictReader(fh)}


def read_pages(urls: list[str]) -> dict[str, dict]:
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    todo = [u for u in urls if u not in cache]
    if todo:
        print(f"Reading {len(todo)} pages for their title and description, {WORKERS} at a time...")
        with httpx.Client(headers=sitemaps.HEADERS, follow_redirects=True, timeout=25) as client:
            def one(url):
                try:
                    return url, sitemaps.fetch_meta(url, client)
                except Exception as exc:
                    return url, {"error": str(exc)[:200]}
            with ThreadPoolExecutor(WORKERS) as pool:
                for url, meta in pool.map(one, todo):
                    cache[url] = meta
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return cache


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="since", required=True, help="first month, as 2026-08")
    parser.add_argument("--to", default=date.today().strftime("%Y-%m"), help="last month (default: this one)")
    parser.add_argument("--apply", action="store_true", help="insert them (default: dry run)")
    args = parser.parse_args()
    first_day = f"{args.since}-01"

    client = get_client()
    columns = "id,url,title,pubDate,created_at" + (",duplicate_of" if column_exists("article", "duplicate_of") else "")
    stored = fetch_all(lambda: client.from_("article").select(columns), order="id")
    held = {story_key(r["url"]) for r in stored}

    rows = [r for r in archive(args.since, args.to) if (r.get("published") or "")[:10] >= first_day]
    missing, seen = [], set()
    for r in rows:
        key = story_key(r["url"])
        if key not in held and key not in seen:
            seen.add(key)
            missing.append(r)
    print(f"{len(rows):,} Singapore articles in the archives since {first_day}; {len(missing):,} not held.")

    known = september()
    need = [r["url"] for r in missing if r["src"] != "cna" and story_key(r["url"]) not in known]
    pages = read_pages(need)
    articles, unread = [], []
    for r in missing:
        meta = known.get(story_key(r["url"])) or pages.get(r["url"]) or {}
        title = r.get("title") if r["src"] == "cna" else meta.get("title")
        description = r.get("description") if r["src"] == "cna" else meta.get("description")
        if not title or title == "None":
            unread.append(r["url"])
            continue
        day = (meta.get("published") if r["src"] != "cna" else None) or r["published"]
        articles.append({"url": r["url"], "title": title, "description": description or None,
                         "category": "Singapore", "pubDate": f"{day[:10]}T00:00:00+00:00"})
    articles.sort(key=lambda a: (a["pubDate"], a["url"]))

    by = {}
    for a in articles:
        k = (outlet(a["url"]), a["pubDate"][:7])
        by[k] = by.get(k, 0) + 1
    print("To insert, by outlet and month:", dict(sorted(by.items())))
    if unread:
        print(f"{len(unread)} pages could not be read for a title and are left out; a second run tries them again:")
        for u in unread[:10]:
            print("   ", u, pages.get(u, {}).get("error", ""))

    if not args.apply:
        print(f"\nDry run: nothing written. --apply to insert {len(articles)} articles.")
        return 0

    started = datetime.now(timezone.utc).isoformat()
    result = insert_new_articles(articles, known=stored)
    if result["error"]:
        print("Insert failed:", result["error"])
        return 1
    urls = {a["url"] for a in articles}
    written = [r for r in fetch_all(lambda: client.from_("article").select("id,url,relevant,duplicate_of")
                                    .gte("created_at", started), order="id") if r["url"] in urls]
    out = ROOT / "data" / "backups" / f"missed-articles-inserted-{date.today().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(written, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Inserted {result['inserted']} ({result['copies']} of them the same story as one held, stored as judged). "
          f"Their ids are in {out.relative_to(ROOT)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
