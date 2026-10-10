"""
Pure RSS/Atom parsing: XML in, `article` rows out. No network, no Supabase.

Ported from the Supabase Edge Function this job replaces (`rss-ingest-v5`),
kept behaviourally equivalent rather than redesigned: same language
detection, same "read description on both RSS and Atom, ignore Atom's
`summary`/`content`" simplification, same first-link-with-an-href rule for
Atom. Only the three feeds in `rss_feeds` are RSS in practice, so the Atom
branch exists for a feed type we do not currently receive.
"""

import re
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

TAG_RE = re.compile(r"<[^>]*>")
PARA_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)


def local_tag(tag: str) -> str:
    """Element tag with any XML namespace stripped, e.g. '{ns}link' -> 'link'."""
    return tag.rsplit("}", 1)[-1]


def children(elem: ET.Element, tag: str) -> list[ET.Element]:
    return [c for c in elem if local_tag(c.tag) == tag]


def text_of(elem: ET.Element | None) -> str | None:
    if elem is None or elem.text is None:
        return None
    s = elem.text.strip()
    return s or None


def strip_tags(html: str) -> str | None:
    return TAG_RE.sub("", html).strip() or None


def detect_language(feed_url: str) -> str:
    """'chinese' for Zaobao (however it's mirrored), 'english' otherwise."""
    return "chinese" if "zaobao" in feed_url.lower() else "english"


def extract_description(description: str | None, language: str) -> str | None:
    """
    English: strip tags and use the whole thing.

    Chinese (Zaobao, via an RSSHub mirror): the mirror wraps the real summary
    in a <p>, alongside boilerplate the rest of the description carries: take
    the first <p>...</p>, or fall back to the whole thing stripped.
    """
    if not description:
        return None
    if language == "english":
        return strip_tags(description)
    match = PARA_RE.search(description)
    if match:
        return strip_tags(match.group(1))
    return strip_tags(description)


def parse_pubdate(raw: str | None) -> str | None:
    """RFC 822 (RSS `pubDate`) or ISO 8601 (Atom `published`/`updated`) to UTC ISO."""
    if not raw:
        return None
    raw = raw.strip()
    for parser in (parsedate_to_datetime, _iso):
        try:
            dt = parser(raw)
        except (TypeError, ValueError):
            continue
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return None


def _iso(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _rss_item(item: ET.Element, language: str) -> dict:
    link = text_of(next(iter(children(item, "link")), None))
    guid = text_of(next(iter(children(item, "guid")), None))
    url = link or guid or ""
    title = text_of(next(iter(children(item, "title")), None)) or url
    description = extract_description(
        text_of(next(iter(children(item, "description")), None)), language)
    cats = [text_of(c) for c in children(item, "category")]
    cats = [c for c in cats if c]
    category = ", ".join(cats) if cats else None
    pub_date = parse_pubdate(
        text_of(next(iter(children(item, "pubDate")), None)))
    return {"url": url.strip(), "title": title, "description": description,
            "category": category, "pubDate": pub_date}


def _atom_entry(entry: ET.Element, language: str) -> dict:
    href = None
    for link in children(entry, "link"):
        candidate = (link.get("href") or "").strip()
        if candidate:
            href = candidate
            break
    entry_id = text_of(next(iter(children(entry, "id")), None))
    url = href or entry_id or ""
    title = text_of(next(iter(children(entry, "title")), None)) or url
    # Parity with the Edge Function: only "description" is read here, which
    # Atom entries do not carry (they use summary/content) -- so this is
    # None in practice until a real Atom feed is added.
    description = extract_description(
        text_of(next(iter(children(entry, "description")), None)), language)
    pub_raw = (text_of(next(iter(children(entry, "published")), None))
               or text_of(next(iter(children(entry, "updated")), None)))
    return {"url": url.strip(), "title": title, "description": description,
            "category": None, "pubDate": parse_pubdate(pub_raw)}


def parse_feed(xml_text: str, feed_url: str) -> dict:
    """
    One feed's articles, plus how it was read.

    Returns {"mode": "rss"|"atom"|"unknown", "items_found": int,
    "after_filter": int, "articles": [...]}. Never raises on a document it
    does not recognise; an unparseable one propagates from ET.fromstring, for
    the caller to catch alongside the fetch itself.
    """
    language = detect_language(feed_url)
    root = ET.fromstring(xml_text)
    root_tag = local_tag(root.tag)

    if root_tag == "rss":
        channel = next(iter(children(root, "channel")), root)
        items = children(channel, "item")
        articles = [_rss_item(i, language) for i in items]
        mode = "rss"
    elif root_tag == "feed":
        items = children(root, "entry")
        articles = [_atom_entry(e, language) for e in items]
        mode = "atom"
    else:
        return {"mode": "unknown", "items_found": 0, "after_filter": 0, "articles": []}

    filtered = [a for a in articles if a["url"]]
    return {"mode": mode, "items_found": len(items), "after_filter": len(filtered),
            "articles": filtered}
