"""
Job 2 -- Entity Extraction.

For every article Job 1 marked relevant but that has not been extracted yet:
read the page, ask Gemini which Singapore entities need knowledge base
updates, write them to `extracted_entities`, then mark the article processed.
The text is not kept; the pipeline stores what it extracted, not what it read.
A page that cannot be read is counted on the row and given up after three
nights.

  python -m src.job2_extraction                      # full run (what CI does)
  python -m src.job2_extraction --limit 3 --dry-run  # scrape + extract, no writes
  python -m src.job2_extraction --limit 3            # process 3 articles

For extraction on another model in bulk, see src/backfill (prompts, ingest).
"""

import argparse
import sys
import time

from tqdm import tqdm

from src.job2_extraction.fetch import MAX_ATTEMPTS, fetch_unextracted_articles
from src.job2_extraction.prompt import extract
from src.job2_extraction.scraper import ScrapeError, scrape
from src.job2_extraction.update import build_rows, record_fetch_failure, save
from src.shared import gemini_client
from src.shared.config import SETTINGS
from src.shared.supabase_client import column_exists



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.job2_extraction")
    parser.add_argument("--limit", type=int, default=None,
                        help="only process the first N queued articles")
    parser.add_argument("--dry-run", action="store_true",
                        help="scrape and extract, but write nothing")
    args = parser.parse_args(argv)

    articles = fetch_unextracted_articles(limit=args.limit)

    if not articles:
        print("No relevant articles awaiting extraction. Nothing to do.")
        return 0

    print(f"Fetched {len(articles)} article(s) awaiting extraction."
          + (" [DRY RUN -- nothing will be written]" if args.dry_run else ""))

    processed = 0
    entities_total = 0
    failed = 0

    # disable=None hides the bar when output is not a terminal, so CI logs
    # stay readable while an interactive run gets a progress line.
    bar = tqdm(articles, unit="article", disable=None,
               bar_format="{n_fmt}/{total_fmt} |{bar}| {percentage:3.0f}% · {remaining} left")

    for index, article in enumerate(bar, start=1):
        title = article.get("title") or ""
        bar.write(f"[{index}/{len(articles)}] id={article['id']} {title[:66]}")

        # Text on the row means a person supplied it by hand (a paywalled
        # page, say); otherwise the page is read now and kept only for the
        # seconds between here and the write.
        text = article.get("text")
        if text:
            bar.write(f"  using text from the row ({len(text):,} chars)")
        else:
            try:
                text = scrape(article["url"])
            except ScrapeError as exc:
                attempts = article.get("fetch_attempts") or 0
                bar.write(f"  Could not read the page (attempt {attempts + 1} of "
                          f"{MAX_ATTEMPTS}): {exc}")
                if not args.dry_run:
                    record_fetch_failure(article["id"], attempts, str(exc))
                failed += 1
                continue

        try:
            response = extract(title, text, article.get("pubDate"))
        except Exception as exc:
            bar.write(f"  Extraction failed, leaving unprocessed: {exc}")
            failed += 1
            continue

        rows = build_rows(article["id"], response)
        if column_exists("extracted_entities", "extraction_model"):
            for row in rows:
                row["extraction_model"] = gemini_client.LAST_MODEL
        for entity in response.entities:
            bar.write(f"    {entity.entity_type:13} {entity.entity_name}")
            bar.write(f"      {entity.summary}")
        if not rows:
            bar.write("    no entities found")

        if args.dry_run:
            bar.write(f"  Dry run: would write {len(rows)} entit(ies).")
        else:
            try:
                save(article["id"], rows)
            except Exception as exc:
                bar.write(f"  Write failed, leaving unprocessed: {exc}")
                failed += 1
                continue
            bar.write(f"  Wrote {len(rows)} entit(ies), marked processed.")

        processed += 1
        entities_total += len(rows)

        if index < len(articles):
            time.sleep(SETTINGS.extraction.seconds_between_articles)

    verb = "Would process" if args.dry_run else "Processed"
    print(f"\n{verb} {processed}/{len(articles)} article(s), "
          f"{entities_total} entit(ies) extracted.")

    if failed:
        print(f"{failed} article(s) failed and will be retried next run.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
