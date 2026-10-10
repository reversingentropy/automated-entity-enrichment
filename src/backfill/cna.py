"""
CNA, through the search index its own site queries.

The search page is a JavaScript shell over Algolia, and like every Algolia
site it publishes a search-only key for the browser to use. Querying the
index directly is what the page does; it just skips the page. Each hit
carries title, brief, URL, release date and the article body as a list of
paragraphs, so CNA needs no page fetches at all.

Two limits shape the code. A query returns at most 3,000 hits however it is
paged, so the index is read one month at a time (busiest month seen: 477).
And the unfiltered hit count is approximate; the monthly counts are exact and
sum to about 76,700 Singapore articles from 2015.
"""

import datetime as dt

import httpx

from src.backfill.months import bounds, label

# Public, search-only, embedded in every page of the site. Not a secret.
APP = "KKWFBQ38XF"
KEY = "e4b61225b5a00162761c501328a58ac7"
INDEX = "cnarevamp-ezrqv5hx"
URL = f"https://{APP}-dsn.algolia.net/1/indexes/{INDEX}/query"
HEADERS = {"X-Algolia-Application-Id": APP, "X-Algolia-API-Key": KEY,
           "Content-Type": "application/json"}
FILTER = 'type:article AND categories:"Singapore"'
PER_PAGE = 1000


def _query(params: str) -> dict:
    r = httpx.post(URL, headers=HEADERS, json={"params": params}, timeout=30)
    r.raise_for_status()
    return r.json()


def _month_params(y: int, m: int, page: int, per_page: int) -> str:
    a, b = bounds(y, m)
    return (f"query=&filters={FILTER}&hitsPerPage={per_page}&page={page}"
            f"&numericFilters=field_release_date>={a},field_release_date<={b}")


def count(y: int, m: int) -> int:
    return _query(_month_params(y, m, 0, 1))["nbHits"]


def row(hit: dict, y: int, m: int) -> dict | None:
    """One index hit as a backfill row. Body is not stored; see the module."""
    url = hit.get("link_absolute") or ""
    if not url.startswith("http"):
        return None
    stamp = hit.get("field_release_date")
    published = (dt.datetime.fromtimestamp(stamp, dt.timezone.utc).date().isoformat()
                 if isinstance(stamp, (int, float)) else None)
    cats = hit.get("categories")
    if isinstance(cats, list):
        cats = "; ".join(str(c) for c in cats)
    return {
        "source": "cna",
        "url": url,
        "title": (hit.get("title") or "").strip() or None,
        # `brief` is empty on most articles before 2022; the body is not.
        "description": (hit.get("brief") or "").strip() or opening(body(hit)) or None,
        "category": (cats or "").strip() or None,
        "published": published,
        "month": label(y, m),
    }


def body(hit: dict) -> str:
    """
    The article text the index carries.

    Recent articles store it as a list of paragraphs. Older ones store it as a
    list of single characters, thousands long, so joining on a blank line
    would put every letter on its own paragraph; those are joined on nothing.
    """
    parts = [p for p in (hit.get("paragraph_text") or []) if isinstance(p, str)]
    if not parts:
        return ""
    if sum(len(p) for p in parts) / len(parts) <= 2:
        return "".join(parts).strip()
    return "\n\n".join(p.strip() for p in parts if p.strip())


def opening(text: str, limit: int = 280) -> str:
    """The first sentence or two, as a description when the index has none."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("。"), cut.rfind("! "), cut.rfind("? "))
    return (cut[:end + 1] if end > limit // 2 else cut.rsplit(" ", 1)[0] + "…").strip()


def collect(y: int, m: int) -> list[dict]:
    out, page = [], 0
    while True:
        j = _query(_month_params(y, m, page, PER_PAGE))
        for hit in j.get("hits", []):
            r = row(hit, y, m)
            if r:
                out.append(r)
        page += 1
        if page >= j.get("nbPages", 0) or not j.get("hits"):
            break
    return out


def body_for(url: str) -> str | None:
    """Fetch one article's body from the index by its URL."""
    j = _query(f'query=&hitsPerPage=1&filters=link_absolute:"{url}"')
    hits = j.get("hits") or []
    return body(hits[0]) if hits else None
