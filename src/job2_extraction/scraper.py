"""
Fetch article text from a news URL.

A generic <p>-tag extraction, which was verified to work on all three sources
currently in the feed (Channel NewsAsia, Straits Times, Zaobao). None of them
blocked a plain request, so no per-site handling is needed yet.
"""

import re

import httpx
from bs4 import BeautifulSoup

# Sites serve a stripped page to clients that look like bots.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "en-SG,en;q=0.9,zh-CN;q=0.8",
}

TIMEOUT = 30

# Anything shorter is a paywall interstitial, a redirect stub or an error page
# rather than an article. Zaobao pieces run ~1,300 chars, so this sits well
# below the real floor.
MIN_TEXT_LENGTH = 400

# Boilerplate that survives tag stripping.
NOISE = (
    "Sign up now: Get ST's newsletters delivered to your inbox",
    "Read this subscriber-only article for free!",
)

STRIP_TAGS = ("script", "style", "nav", "header", "footer", "aside", "form", "figure")


class ScrapeError(RuntimeError):
    """Raised when a URL yields no usable article text."""


def scrape(url: str) -> str:
    """
    Return the article body text at `url`.

    Raises ScrapeError if the page cannot be fetched or holds too little text
    to be a real article -- the caller leaves such rows unprocessed so they
    are retried on the next run.
    """
    try:
        response = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ScrapeError(f"could not fetch {url}: {exc}") from exc

    text = text_from(response.text)
    if len(text) < MIN_TEXT_LENGTH:
        raise ScrapeError(
            f"only {len(text)} chars from {url} "
            f"(minimum {MIN_TEXT_LENGTH}) -- likely a paywall or error page"
        )
    return text


def text_from(html: str) -> str:
    """The article's paragraphs, boilerplate removed. No length check."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(STRIP_TAGS):
        tag.decompose()
    paragraphs = (p.get_text(" ", strip=True) for p in soup.find_all("p"))
    text = re.sub(r"\s+", " ", " ".join(paragraphs)).strip()
    for phrase in NOISE:
        text = text.replace(phrase, "")
    return re.sub(r"\s+", " ", text).strip()
