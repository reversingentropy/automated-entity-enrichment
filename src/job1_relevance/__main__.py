"""
Job 1 -- Relevance Scoring.

Fetch every article with no relevance verdict yet, ask Gemini which ones would
require a knowledge base update, and write the verdicts back.

  python -m src.job1_relevance                      # full run (what CI does)
  python -m src.job1_relevance --limit 10 --dry-run # 1 call, writes nothing
  python -m src.job1_relevance --limit 10           # 1 call, writes 10 verdicts
"""

import argparse
import html
import sys
import time

from src.job1_relevance.fetch import fetch_unscored_articles
from src.job1_relevance.prompt import classify
from src.job1_relevance.update import build_payload, write_verdicts
from src.shared.config import SETTINGS

def record_model(ids: list[int]) -> None:
    """Which model scored this batch, once sql/12 has added the column."""
    from src.shared import gemini_client
    from src.shared.supabase_client import column_exists, get_client
    if not column_exists("article", "relevance_model") or not gemini_client.LAST_MODEL:
        return
    for start in range(0, len(ids), 200):
        get_client().from_("article").update({"relevance_model": gemini_client.LAST_MODEL}) \
            .in_("id", ids[start:start + 200]).execute()


def chunked(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def preview(batch: list[dict], payload: list[dict]) -> None:
    """Print each verdict, so a dry run can be eyeballed before committing."""
    # Unescaped to match exactly what was sent to the model.
    descriptions = {a["id"]: html.unescape(a.get("description") or "") for a in batch}
    for row in payload:
        mark = "RELEVANT " if row["relevant"] else "         "
        snippet = descriptions[row["id"]][:70].replace("\n", " ")
        print(f"    {mark} {row['id']:>6}  {snippet}")
        if row["reason"]:
            print(f"               reason: {row['reason']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.job1_relevance")
    parser.add_argument("--limit", type=int, default=None,
                        help="only score the first N unscored articles")
    parser.add_argument("--dry-run", action="store_true",
                        help="call Gemini and print verdicts, but write nothing")
    args = parser.parse_args(argv)

    articles = fetch_unscored_articles(limit=args.limit)

    # Nothing to score: exit cleanly without calling Gemini or writing anything.
    if not articles:
        print("No unscored articles. Nothing to do.")
        return 0

    print(f"Fetched {len(articles)} unscored article(s)."
          + (" [DRY RUN -- nothing will be written]" if args.dry_run else ""))

    batches = list(chunked(articles, SETTINGS.relevance.batch_size))
    scored = 0
    relevant_total = 0
    failed = 0

    for index, batch in enumerate(batches, start=1):
        print(f"Batch {index}/{len(batches)} ({len(batch)} articles)...")

        try:
            relevant = classify(batch)
        except Exception as exc:
            # Leave this batch's rows at NULL so the next run retries them,
            # rather than burying them as not-relevant.
            print(f"  Failed, leaving batch unscored for the next run: {exc}")
            failed += 1
            continue

        # Only reached once the model has answered and validated, so a failure
        # above never results in a write.
        payload = build_payload(batch, relevant)
        preview(batch, payload)

        if args.dry_run:
            print(f"  Dry run: would write {len(payload)} verdict(s), "
                  f"{len(relevant)} relevant.")
        else:
            try:
                write_verdicts(payload)
            except Exception as exc:
                print(f"  Write failed, batch stays unscored: {exc}")
                failed += 1
                continue
            print(f"  Wrote {len(payload)} verdict(s), {len(relevant)} relevant.")
            record_model([a["id"] for a in batch])

        scored += len(batch)
        relevant_total += len(relevant)
        for article in batch:
            article["relevant"] = article["id"] in relevant

        if index < len(batches):
            time.sleep(SETTINGS.relevance.seconds_between_batches)

    verb = "Would score" if args.dry_run else "Scored"
    print(f"\n{verb} {scored}/{len(articles)} article(s): "
          f"{relevant_total} relevant, {scored - relevant_total} not relevant.")
    if failed:
        print(f"{failed} batch(es) failed and will be retried next run.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
