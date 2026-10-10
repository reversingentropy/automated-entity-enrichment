"""
The Straits Times and Zaobao, through the monthly sitemaps they publish.

Neither search page yields a result without JavaScript, and neither has an
API a browser is meant to call. Both publish sitemaps for Google, one per
month, back to January 2015 (ST) and January 2016 (Zaobao). A sitemap gives
the URL and sometimes a date, never the title, so each URL costs one page
fetch for its title and description. The section is in the path, which is
the Singapore filter the search pages could not offer.

The Straits Times caps each month at 5,000 URLs, so a busy month is
truncated; there is nothing to be done about that from outside.
"""

import re

import httpx

from src.backfill.months import label

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
           "Accept-Language": "en-SG,en;q=0.9,zh;q=0.8"}

SOURCES = {
    "st": {"index": "https://www.straitstimes.com/sitemap/{y:04d}/{m:02d}/feeds.xml",
           "keep": re.compile(r"straitstimes\.com/singapore/")},
    "zb": {"index": "https://www.zaobao.com.sg/sitemaps/sitemap-{y:04d}{m:02d}.xml",
           "keep": re.compile(r"zaobao\.com\.sg/news/singapore/")},
}

LOC = re.compile(r"<url>(.*?)</url>", re.S)
TAG = lambda name: re.compile(rf"<{name}>(.*?)</{name}>", re.S)


def parse(xml: str, source: str, y: int, m: int) -> list[dict]:
    """Rows for the Singapore URLs in one monthly sitemap. Pure; testable."""
    keep = SOURCES[source]["keep"]
    out = []
    for block in LOC.findall(xml):
        loc = TAG("loc").search(block)
        if not loc:
            continue
        # The Straits Times appends ?ai-allowed=1 to sitemap URLs, an explicit
        # welcome to AI crawlers. Stored without it, so the URL matches the
        # form the nightly `article` table holds.
        url = loc.group(1).strip().split("?")[0]
        if not keep.search(url):
            continue
        mod = TAG("lastmod").search(block)
        out.append({
            "source": source,
            "url": url,
            "title": None,
            "description": None,
            "category": section(url),
            "published": mod.group(1).strip()[:10] if mod else None,
            "month": label(y, m),
        })
    return out


def section(url: str) -> str:
    """The section path between the host and the slug: 'singapore/politics'."""
    path = re.sub(r"^https?://[^/]+/", "", url).split("?")[0].strip("/")
    parts = path.split("/")
    return "/".join(parts[:-1]) if len(parts) > 1 else parts[0]


def collect(source: str, y: int, m: int) -> list[dict]:
    url = SOURCES[source]["index"].format(y=y, m=m)
    r = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=30)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    return parse(r.text, source, y, m)


# ---- the one page fetch that turns a URL into a title ----------------------

META = {
    "title": [r'<meta property="og:title" content="([^"]*)"', r"<title>(.*?)</title>"],
    "description": [r'<meta property="og:description" content="([^"]*)"',
                    r'<meta name="description" content="([^"]*)"'],
    "published": [r'"datePublished":\s*"([^"]+)"',
                  r'<meta property="article:published_time" content="([^"]*)"'],
    "category": [r'<meta property="article:section" content="([^"]*)"'],
}


def meta_from(html: str) -> dict:
    """Title, description and date from a page's own metadata."""
    out = {}
    for key, patterns in META.items():
        for pat in patterns:
            m = re.search(pat, html, re.S)
            if m:
                val = re.sub(r"\s+", " ", m.group(1)).strip()
                val = (val.replace("&amp;", "&").replace("&quot;", '"')
                          .replace("&#039;", "'").replace("&#39;", "'"))
                out[key] = val[:10] if key == "published" else val
                break
    return out


def slug_title(url: str) -> str:
    """
    The headline as the Straits Times writes it into the URL.

    'singaporean-man-suspected-for-drug-trafficking-arrested-in-vietnam' is
    the headline with hyphens. For deciding relevance from a title it is the
    title, and it costs nothing; the real headline and description are worth
    a page fetch only for the few articles that pass, when the body is being
    fetched anyway.
    """
    slug = url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    words = slug.replace("-", " ").strip()
    return (words[:1].upper() + words[1:]) if words else ""


class Throttled(RuntimeError):
    """The site asked us to slow down; the caller backs off and retries."""


def fetch_meta(url: str, client: httpx.Client | None = None, retries: int = 3) -> dict:
    """
    One page's title, description and date. A shared `client` reuses the
    connection, which is most of the difference between 6 and 8 pages a
    second per worker. A 429 or 503 is a request to slow down, honoured with
    a growing pause; anything else is the caller's problem.
    """
    get = client.get if client else (lambda u: httpx.get(u, headers=HEADERS, follow_redirects=True, timeout=25))
    pause = 2.0
    for attempt in range(retries + 1):
        r = get(url)
        if r.status_code in (429, 503) and attempt < retries:
            import time
            time.sleep(pause)
            pause *= 2
            continue
        if r.status_code in (429, 503):
            raise Throttled(f"HTTP {r.status_code} after {retries} retries")
        r.raise_for_status()
        return meta_from(r.text)
    return {}
