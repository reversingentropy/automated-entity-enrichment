"""
Mark the copies already stored in `article`: the stories stored twice before the ingest learned to check.

    uv run python scripts/mark_duplicate_articles.py            # dry run: what it would mark, nothing written
    uv run python scripts/mark_duplicate_articles.py --apply    # write it (needs sql/14_article_duplicates.sql)

Uses the ingest's own rules (src/shared/stories.py) over the whole table. In each story the first one kept is the
one that has had the most work done (extracted, then judged relevant, then the earliest id); every other copy gets
`duplicate_of` pointing at it. A copy nothing has worked on yet (waiting for Job 1, or judged relevant and waiting
for Job 2) is also marked as judged, `relevant` false with the reason, so no job takes it. A copy already worked on
keeps what was done, for the record. Nothing is deleted. Before writing, the current values of every row it
touches are saved to data/backups/.
"""

import argparse
import collections
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.shared.pagination import fetch_all  # noqa: E402
from src.shared.stories import find_copies, outlet, same_title  # noqa: E402
from src.shared.supabase_client import column_exists, get_client  # noqa: E402


def waiting(a: dict) -> bool:
    return a["relevant"] is None or (a["relevant"] is True and not a["processed_extraction"])


def plan(rows: list[dict]) -> list[dict]:
    """Every copy, with the article it is a copy of and why."""
    days = collections.defaultdict(set)
    for a in rows:
        days[(outlet(a["url"]), same_title(a["title"]))].add((a["pubDate"] or a["created_at"] or "")[:10])
    # The most-worked article of a story comes first, so it is the one kept.
    order = sorted(rows, key=lambda a: (not a["processed_extraction"], a["relevant"] is not True, a["id"]))
    copies = find_copies(order, [], uses=lambda name, title: len(days[(name, same_title(title))]))
    by_url = {a["url"]: a for a in rows}
    out = []
    for url, (original, why) in copies.items():
        first = by_url[original]
        out.append({"copy": by_url[url], "first": first, "why": why})
    return sorted(out, key=lambda x: x["copy"]["id"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write the marks (default: dry run)")
    args = parser.parse_args()

    client = get_client()
    linked = column_exists("article", "duplicate_of")
    columns = "id,url,title,pubDate,created_at,relevant,reason,processed_extraction" + (",duplicate_of" if linked else "")
    rows = fetch_all(lambda: client.from_("article").select(columns), order="id")
    todo = plan(rows)
    if linked:
        todo = [x for x in todo if x["copy"].get("duplicate_of") != x["first"]["id"]]

    stories = {x["first"]["id"] for x in todo}
    print(f"{len(rows):,} articles. {len(todo)} copies of {len(stories)} stories to mark.")
    print("  by rule:   ", dict(collections.Counter(x["why"] for x in todo)))
    print("  by outlet: ", dict(collections.Counter(outlet(x["copy"]["url"]) for x in todo)))
    stop = [x for x in todo if waiting(x["copy"])]
    print(f"  {len(stop)} copies are waiting for a job and will be marked as judged, so none takes them:")
    for x in stop:
        print(f"    {x['copy']['id']} -> {x['first']['id']}  {x['copy']['url']}")
    done = sum(1 for x in todo if x["copy"]["processed_extraction"])
    print(f"  {done} copies were already extracted; that work is kept, and the copy is only pointed at the first.")

    if not args.apply:
        print("\nDry run: nothing written. --apply to write.")
        return 0
    if not linked:
        print("\nRun sql/14_article_duplicates.sql first: article.duplicate_of does not exist yet.")
        return 1

    backup = ROOT / "data" / "backups" / f"article-duplicates-before-{date.today().isoformat()}.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(json.dumps([x["copy"] for x in todo], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nSaved the current values of {len(todo)} rows to {backup.relative_to(ROOT)}")
    for x in todo:
        change = {"duplicate_of": x["first"]["id"]}
        if waiting(x["copy"]):
            change |= {"relevant": False, "reason": f"Same story as article {x['first']['id']}: {x['why']}."}
        client.from_("article").update(change).eq("id", x["copy"]["id"]).execute()
    print(f"Marked {len(todo)} copies.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
