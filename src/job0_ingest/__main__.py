"""
Job 0 -- RSS ingestion.

Fetches every feed in `rss_feeds`, parses whatever RSS/Atom it returns, and
upserts the result into `article` by url. Replaces the Supabase Edge
Function `rss-ingest-v5`: same feeds, same target table, same field mapping,
but a feed that fails to fetch or parse no longer stops the rest -- the
Edge Function threw on the first bad feed and never reached the ones after
it in the list.

  python -m src.job0_ingest              # full run (what CI does)
  python -m src.job0_ingest --dry-run    # fetch and parse, write nothing

Runs before Job 1 in nightly.yml, on both of its schedules: articles a feed
carries now are what Job 1 scores next. An article that is a story already
stored at another address is stored as already judged, so no job works on it
twice (src/shared/stories.py).
"""

import argparse
import sys

import httpx

from src.job0_ingest.parse import parse_feed
from src.job0_ingest.update import fetch_feeds, insert_new_articles, recent_articles, title_uses
from src.shared.stories import find_copies

HEADERS = {"Accept": "application/xml,text/xml,application/rss+xml,*/*"}
TIMEOUT = 30


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.job0_ingest")
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch and parse, but write nothing")
    args = parser.parse_args(argv)

    feeds = fetch_feeds()
    if not feeds:
        print("No feeds in rss_feeds. Nothing to do.")
        return 0

    print(f"{len(feeds)} feed(s)."
          + (" [DRY RUN -- nothing will be written]" if args.dry_run else ""))

    failed = 0
    total_found = total_written = total_copies = 0
    try:
        known = recent_articles()
    except Exception as exc:
        print(f"  Could not read the last week's articles to check for copies -- {exc}")
        known = None

    for feed in feeds:
        label = feed.get("source") or feed["url"]
        try:
            response = httpx.get(feed["url"], headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status()
            parsed = parse_feed(response.text, feed["url"])
        except Exception as exc:
            print(f"  {label}: FAILED to fetch/parse, skipped -- {exc}")
            failed += 1
            continue

        total_found += parsed["after_filter"]
        if args.dry_run:
            copies = find_copies(parsed["articles"], known or [], uses=title_uses)
            print(f"  {label}: {parsed['mode']}, {parsed['items_found']} item(s), "
                  f"{parsed['after_filter']} with a url. Dry run: would insert those not already stored, "
                  f"{len(copies)} of them as the same story as one stored.")
            for url, (original, why) in copies.items():
                print(f"      {url}\n        same story as {original}: {why}")
            continue

        result = insert_new_articles(parsed["articles"], known)
        if result["error"]:
            print(f"  {label}: {parsed['mode']}, {parsed['after_filter']} article(s) -- "
                  f"WRITE FAILED: {result['error']}")
            failed += 1
            continue

        total_written += result["inserted"]
        total_copies += result["copies"]
        print(f"  {label}: {parsed['mode']}, {parsed['after_filter']} article(s) in the feed, "
              f"{result['inserted']} new" + (f", {result['copies']} of them a story already stored (not queued)." if result["copies"] else "."))

    verb = "Would find" if args.dry_run else "Found"
    print(f"\n{verb} {total_found} article(s) across {len(feeds)} feed(s)"
          + ("" if args.dry_run else f", {total_written} new, {total_copies} of them copies."))

    if failed:
        print(f"{failed} feed(s) failed; the rest were still ingested.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
