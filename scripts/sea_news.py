"""
Trial: the Berita Harian (Malay) and Tamil Murasu (Tamil) archives, before either paper's backlog goes near the pipeline.

Nothing here touches the database or the nightly jobs: every article lands in data/sea_news/articles.jsonl, one
line each. (The nightly pipeline reads both papers' RSS feeds from sql/18 on; this is the archive behind them.)

    .venv/bin/python scripts/sea_news.py collect                     # the whole archive, newest month first
    .venv/bin/python scripts/sea_news.py collect --from 2026-10-01   # only from that month on
    .venv/bin/python scripts/sea_news.py count                       # what has been collected so far

Both papers list every article in a sitemap per month, back to January 2015: the link and a date, never the
title, so each article is one page fetch for its headline, one-line summary, publish date and text (the text
read the way Job 2 reads every outlet). Only the Singapore sections are kept, as the feeds keep them.

It is slow on purpose. robots.txt on both asks for ten seconds between requests, and each paper gets one
request at a time, ten seconds apart: about 90,000 Singapore articles, a week or so of the PC being on. So it
is built to be stopped and started whenever:
  - Ctrl+C, closing the window, the PC sleeping or shutting down: at most the page being fetched is lost.
  - Each month's list of links is kept under data/sea_news/sitemaps/ once read, so a restart starts fetching
    at once. The two newest months are read again each run, as they are still growing.
  - Each article is written the moment it is read; a link already collected is never fetched again.
  - A page that fails is noted in errors.jsonl and tried again on later runs, up to three times.
  - A 429 or 503 is the site asking us to slow down: honoured, with a growing pause.

The monthly sitemaps stop at 1,000 links: in a month with more, the rest are not listed anywhere, and `count`
says which months were cut short.
"""

import argparse
import json
import re
import sys
import threading
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.job2_extraction.scraper import HEADERS, MIN_TEXT_LENGTH, text_from  # noqa: E402

DIR = ROOT / "data" / "sea_news"
OUT = DIR / "articles.jsonl"
ERRORS = DIR / "errors.jsonl"
SITEMAPS = DIR / "sitemaps"
PAUSE = 10
TRIES = 3
CAP = 1000
FIRST = date(2015, 1, 1)

# The Singapore sections, as the feeds keep them (sql/18): Tamil Murasu's community pages are Singapore's
# Indian community, so they stay.
SITES = {
    "bh": {"name": "Berita Harian", "host": "https://www.beritaharian.sg", "lang": "ms",
           "keep": re.compile(r"\.sg/singapura/")},
    "tm": {"name": "Tamil Murasu", "host": "https://www.tamilmurasu.com.sg", "lang": "ta",
           "keep": re.compile(r"\.sg/(singapore|community)/")},
}

# Text the paragraphs carry that is not the article: Berita Harian's follow-topic button, Tamil Murasu's timestamp.
LEAD = re.compile(r"^(Topik diikuti\s+|\d{1,2} \w{3} \d{4} - \d{1,2}:\d{2} [ap]m\s+)")

URL = re.compile(r"<url>(.*?)</url>", re.S)


def tag(name: str, block: str) -> str | None:
    m = re.search(rf"<{name}>(.*?)</{name}>", block, re.S)
    return m.group(1).strip() if m else None


def bare(url: str) -> str:
    """The link as the pipeline stores it: the ?ai-allowed=1 the sitemaps add, dropped (as for ST)."""
    return url.split("?")[0]


def months(since: date):
    """Every month from `since` to this one, newest first."""
    today = date.today()
    y, m = today.year, today.month
    while (y, m) >= (since.year, since.month):
        yield y, m
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)


def read_lines(path: Path) -> list[dict]:
    """A JSON-lines file, skipping a last line cut short by a stop mid-write."""
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def span(seconds: float) -> str:
    """A length of time as a person would say it: 34 min, 7 h, 3 days 4 h."""
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} min"
    hours = round(seconds / 3600)
    return f"{hours} h" if hours < 48 else f"{hours // 24} days {hours % 24} h"


class Pacer:
    """One request at a time to a site, at least PAUSE seconds apart."""

    def __init__(self):
        self.last = 0.0

    def wait(self):
        gap = self.last + PAUSE - time.monotonic()
        if gap > 0:
            time.sleep(gap)
        self.last = time.monotonic()


def fetch(client: httpx.Client, pacer: Pacer, url: str, label: str) -> httpx.Response:
    """
    One polite request. A 429 or 503 means slow down: wait as long as the site says, or longer each time.

    No connection at all (the PC asleep, the network down) is not the page's fault: wait a minute and ask again,
    rather than count it against the page.
    """
    pause = 60
    while True:
        pacer.wait()
        try:
            response = client.get(url, follow_redirects=True)
        except httpx.TransportError as exc:
            tqdm.write(f"{label}: no connection ({type(exc).__name__}), trying again in a minute")
            time.sleep(60)
            continue
        if response.status_code not in (429, 503):
            return response
        said = response.headers.get("retry-after", "")
        wait = int(said) if said.isdigit() else pause
        tqdm.write(f"{label}: the site answered {response.status_code}, so pausing {wait // 60} min {wait % 60} s")
        time.sleep(wait)
        pause = min(pause * 2, 900)


def month_links(client: httpx.Client, pacer: Pacer, site: str, y: int, m: int) -> list[dict]:
    """One month's Singapore links, from the copy kept on disk once the month is over."""
    s = SITES[site]
    path = SITEMAPS / f"{site}-{y:04d}-{m:02d}.json"
    today = date.today()
    settled = (today.year * 12 + today.month) - (y * 12 + m) >= 2
    if settled and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["links"]
    response = fetch(client, pacer, f"{s['host']}/sitemap-articles-{y:04d}-{m:02d}.xml", s["name"])
    if response.status_code == 404:
        blocks = []
    else:
        response.raise_for_status()
        blocks = URL.findall(response.text)
    links = []
    for block in blocks:
        url = bare(tag("loc", block) or "")
        if s["keep"].search(url):
            links.append({"url": url, "month": f"{y:04d}-{m:02d}", "lastmod": tag("lastmod", block)})
    SITEMAPS.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"listed": len(blocks), "capped": len(blocks) >= CAP, "links": links}), encoding="utf-8")
    return links


def meta(soup: BeautifulSoup, key: str) -> str | None:
    el = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    value = (el.get("content") or "").strip() if el else ""
    return value or None


def read_page(html: str) -> dict:
    """One article page: its headline, summary, publish date and text."""
    soup = BeautifulSoup(html, "html.parser")
    title = meta(soup, "og:title") or (soup.title.get_text(strip=True) if soup.title else None)
    text = LEAD.sub("", text_from(html))
    return {"title": title, "description": meta(soup, "og:description") or meta(soup, "description"),
            "published": meta(soup, "article:published_time"), "keywords": meta(soup, "keywords"),
            "text": text, "chars": len(text)}


class Run:
    """What both sites share: the file each article is written to, and what is already in it."""

    def __init__(self):
        DIR.mkdir(parents=True, exist_ok=True)
        self.done = {r["url"] for r in read_lines(OUT)}
        self.failures = Counter(r["url"] for r in read_lines(ERRORS))
        self.lock = threading.Lock()
        self.out = open(OUT, "a", encoding="utf-8")
        self.errors = open(ERRORS, "a", encoding="utf-8")
        self.fetched = Counter()
        self.left = {}

    def write(self, row: dict, failed: bool):
        with self.lock:
            f = self.errors if failed else self.out
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()


def one_site(run: Run, site: str, since: date, position: int):
    s = SITES[site]
    client, pacer = httpx.Client(headers=HEADERS, timeout=30), Pacer()
    links = []
    try:
        for y, m in tqdm(list(months(since)), desc=f"{s['name']}: listing months", unit="month",
                         position=position, leave=False, dynamic_ncols=True):
            links += month_links(client, pacer, site, y, m)
    except httpx.HTTPError as exc:
        tqdm.write(f"{s['name']}: could not read a monthly sitemap, so stopping this site for now -- {exc}")
        return
    todo = [l for l in links if l["url"] not in run.done and run.failures[l["url"]] < TRIES]
    run.left[site] = len(todo)
    bar = tqdm(total=len(todo), desc=s["name"], unit="page", position=position, dynamic_ncols=True, smoothing=0.02,
               bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed} so far, {remaining} left]{postfix}")
    bar.set_postfix_str(f"{len(links) - len(todo):,} of {len(links):,} collected before")
    for link in todo:
        row = {"url": link["url"], "site": site, "lang": s["lang"], "section": link["url"].split("/")[3],
               "listed_in": link["month"], "listed_date": link["lastmod"]}
        try:
            response = fetch(client, pacer, link["url"], s["name"])
            response.raise_for_status()
            run.write(row | read_page(response.text), failed=False)
        except httpx.HTTPError as exc:
            run.write({"url": link["url"], "site": site, "error": str(exc)[:300],
                       "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}, failed=True)
        run.fetched[site] += 1
        run.left[site] -= 1
        bar.update()
    bar.close()


def collect(since: date):
    run = Run()
    start = time.monotonic()
    print(f"{len(run.done):,} articles already collected. One request every {PAUSE} s per site; "
          f"stop with Ctrl+C whenever, and the next run carries on.\n")
    threads = [threading.Thread(target=one_site, args=(run, site, since, i), daemon=True) for i, site in enumerate(SITES)]
    for t in threads:
        t.start()
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    print(f"\n\nThis run: {span(time.monotonic() - start)}, "
          + ", ".join(f"{SITES[s]['name']} {run.fetched[s]:,} pages" for s in SITES) + ".")
    for s in SITES:
        if s in run.left:
            left = run.left[s]
            print(f"  {SITES[s]['name']}: {left:,} still to fetch, about {span(left * PAUSE)} of the PC being on.")


def count():
    rows = read_lines(OUT)
    errors = read_lines(ERRORS)
    for site, s in SITES.items():
        mine = [r for r in rows if r["site"] == site]
        lists = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(SITEMAPS.glob(f"{site}-*.json"))]
        print(f"{s['name']}: {len(mine):,} articles collected of {sum(len(l['links']) for l in lists):,} listed "
              f"in the {len(lists)} months read so far")
        if lists:
            print(f"  months cut short at {CAP:,} links: {sum(l['capped'] for l in lists)} of {len(lists)}")
        failed = {e["url"] for e in errors if e["site"] == site} - {r["url"] for r in mine}
        if failed:
            print(f"  {len(failed)} could not be fetched yet (tried again next run, up to {TRIES} times)")
        if not mine:
            continue
        print(f"  headline {sum(bool(r.get('title')) for r in mine):,}, summary {sum(bool(r.get('description')) for r in mine):,}, "
              f"publish date {sum(bool(r.get('published')) for r in mine):,}, "
              f"text of {MIN_TEXT_LENGTH}+ characters {sum(r.get('chars', 0) >= MIN_TEXT_LENGTH for r in mine):,}")
        years = Counter((r.get("published") or r.get("listed_in") or "")[:4] for r in mine)
        print(f"  by year {dict(sorted(years.items()))}")
        print(f"  sections {dict(Counter(r['section'] for r in mine))}")
        chars = sorted(r.get("chars", 0) for r in mine)
        print(f"  text length: median {chars[len(chars) // 2]:,} characters, shortest {chars[0]:,}")


def main():
    parser = argparse.ArgumentParser(prog="scripts/sea_news.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--from", dest="since", type=date.fromisoformat, default=FIRST,
                   help="the first month to collect (default: January 2015, the archive's start)")
    sub.add_parser("count")
    args = parser.parse_args()
    if args.cmd == "collect":
        collect(args.since)
    else:
        count()


if __name__ == "__main__":
    main()
