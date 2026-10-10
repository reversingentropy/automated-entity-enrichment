"""
Which articles are the same story.

The url is unique in `article`, but it is not the story. Outlets change it after
publishing, and the ingest runs twice a day, so the second run can meet an article
again at a new address: The Straits Times moves one between sections
(/singapore/courts-crime/... became /singapore/... between the evening and the
morning run, articles 19312 and 19420), CNA rewrites the headline in it and keeps
the number at the end, and Zaobao is on two domains. Two rules say two articles
are one story:

  - the same story key: CNA's article number, Zaobao's story number, or the last
    part of a Straits Times address, whatever the section;
  - the same outlet and the same title, published within two days of each other,
    unless the outlet uses that title over and over: 速读狮城, "Must-reads" and
    "ST Live: News as it happens" are columns, and "Singapore re-elected to
    governing body of ICAO" three years apart is two elections.

A description is not a rule: 84 old Straits Times articles share "Read more at
straitstimes.com", and the daily haze reports share their second sentence.
Different outlets reporting one event are two sources, never a copy.
"""

import html
import re
from datetime import datetime, timedelta
from typing import Callable
from urllib.parse import urlsplit

WINDOW = timedelta(days=2)
RECURRING = 3     # a title an outlet has used on this many different days is a column, not a story


def outlet(url: str) -> str:
    host = urlsplit(url or "").netloc.lower().removeprefix("www.")
    if host.endswith("channelnewsasia.com"):
        return "cna"
    if host.endswith("straitstimes.com"):
        return "st"
    if "zaobao" in host:
        return "zaobao"
    return host


def story_key(url: str) -> str:
    """What stays the same when an outlet changes an article's address."""
    path = urlsplit(url or "").path.rstrip("/")
    last = path.rsplit("/", 1)[-1]
    name = outlet(url)
    if name == "cna":
        m = re.search(r"-(\d{6,})$", last)
        if m:
            return f"cna:{m.group(1)}"
    elif name == "zaobao":
        m = re.search(r"story\d{8}-\d+", path)
        if m:
            return f"zaobao:{m.group(0)}"
    elif name == "st" and last:
        return f"st:{last}"
    return f"{name}:{path}"


def same_title(title: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(title or "")).strip().casefold()


def _when(article: dict) -> datetime | None:
    for key in ("pubDate", "created_at"):
        value = article.get(key)
        if value:
            try:
                return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                continue
    return None


def _close(a: dict, b: dict) -> bool:
    ta, tb = _when(a), _when(b)
    return ta is not None and tb is not None and abs(ta - tb) <= WINDOW


def find_copies(new: list[dict], known: list[dict],
                uses: Callable[[str, str], int] | None = None) -> dict[str, tuple]:
    """
    The new articles that are a story already seen, as {url: (original, why)}.

    `known` are stored articles ({id, url, title, pubDate, duplicate_of}); the
    original is a stored article's id, or the url of an earlier article in `new`
    when both arrived in one run. `uses(outlet, title)` counts the different days
    an outlet has published a title as stored, for the column check (days, not
    articles: CNA's archive holds one SilkAir story four times on one day);
    without it, only `known` is counted. A copy is remembered under its original, so a third copy that
    matches only the second still finds the first.
    """
    days: dict[tuple, set] = {}
    for a in known:
        when = _when(a)
        days.setdefault((outlet(a["url"]), same_title(a.get("title"))), set()).add(when.date() if when else None)

    def recurring(article: dict) -> bool:
        name = outlet(article["url"])
        n = uses(name, article.get("title") or "") if uses else len(days.get((name, same_title(article.get("title"))), ()))
        return n >= RECURRING

    by_key: dict[str, tuple] = {}
    by_title: dict[tuple, list[tuple]] = {}

    def remember(article: dict, original):
        by_key.setdefault(story_key(article["url"]), (original, article))
        title = same_title(article.get("title"))
        if title:
            by_title.setdefault((outlet(article["url"]), title), []).append((original, article))

    for a in sorted(known, key=lambda a: a["id"]):
        remember(a, a.get("duplicate_of") or a["id"])

    copies: dict[str, tuple] = {}
    stored = {a["url"] for a in known}
    for a in new:
        if a["url"] in stored or a["url"] in copies:
            continue
        name, title = outlet(a["url"]), same_title(a.get("title"))
        hit = by_key.get(story_key(a["url"]))
        earlier = [o for o, b in by_title.get((name, title), []) if _close(a, b)] if title else []
        if hit and hit[1]["url"] != a["url"]:
            copies[a["url"]] = (hit[0], "the same article at a new address")
        elif earlier and not recurring(a):
            copies[a["url"]] = (earlier[0], "the same title from the same outlet within two days")
        remember(a, copies[a["url"]][0] if a["url"] in copies else a["url"])
    return copies
