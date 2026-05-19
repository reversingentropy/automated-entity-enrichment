"""
Load RSS feeds from a JSON file and collect the latest articles.

The resulting dictionary is keyed by article URL and contains:
- title
- summary
- published date
"""

import json
import feedparser
from datetime import datetime


RSS_FEEDS_PATH = "../rss_feeds/feeds.json"


def collect_latest_articles(feeds_file: str = RSS_FEEDS_PATH) -> dict[str, dict[str, str]]:
    """Load feeds from a JSON file and return all latest articles."""
    with open(feeds_file, "r", encoding="utf-8") as file:
        feeds: dict[str, str] = json.load(file)

    latest_articles: dict[str, dict[str, str]] = {}

    for source, feed_url in feeds.items():
        parsed_feed = feedparser.parse(feed_url)

        for entry in parsed_feed.get("entries", []):
            link = entry.get("link")

            if not link:
                continue
            
            # Convert string to datetime object for SQL timestamp
            dt = datetime.strptime(entry.get("published", ""), "%a, %d %b %Y %H:%M:%S %z")
            sql_timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")

            latest_articles[link] = {
                "title": entry.get("title", ""),
                "summary": entry.get("summary", ""),
                "published": sql_timestamp,
                'source' : source
            }

    return latest_articles

if __name__ == "__main__":
    print(list(collect_latest_articles().items())[0])