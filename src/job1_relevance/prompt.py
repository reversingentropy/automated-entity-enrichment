"""Build the relevance prompt and turn Gemini's answer into {id: reason}."""

import html
import json
from pathlib import Path

from src.shared.config import SETTINGS
from src.shared.gemini_client import generate_json
from src.shared.models import RelevanceResponse

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "relevance.txt"


def load_prompt() -> str:
    """Read the relevance prompt. Text mode normalises the file's CRLF endings."""
    return PROMPT_PATH.read_text(encoding="utf-8")


def build_article_payload(articles: list[dict]) -> str:
    """
    Serialise the batch as the id/description pairs the prompt scores.

    Descriptions come from RSS and arrive HTML-escaped ("&#039;" for an
    apostrophe), so they are unescaped before the model sees them.
    """
    return json.dumps(
        [
            {
                "id": a["id"],
                "title": html.unescape(a.get("title") or ""),
                "description": html.unescape(a.get("description") or ""),
            }
            for a in articles
        ],
        ensure_ascii=False,
        indent=2,
    )


def render(articles: list[dict]) -> str:
    """
    Combine the prompt template with the batch.

    prompts/relevance.txt currently ends on its JSON example with no
    placeholder, so the articles are appended. If an `{articles}` placeholder is
    added later, it is substituted instead.
    """
    template = load_prompt()
    payload = build_article_payload(articles)

    if "{articles}" in template:
        return template.replace("{articles}", payload)
    return f"{template}\n\nARTICLES TO SCORE:\n{payload}"


def classify(articles: list[dict]) -> dict[int, str]:
    """
    Score one batch, returning {article_id: reason} for the relevant articles.

    Ids the model invents, or echoes back from outside this batch, are dropped
    -- otherwise they would be written as verdicts against unrelated rows.
    """
    response = generate_json(
        model=SETTINGS.relevance.models,
        prompt=render(articles),
        schema=RelevanceResponse,
        thinking_level=SETTINGS.relevance.thinking,
    )

    batch_ids = {a["id"] for a in articles}
    relevant: dict[int, str] = {}

    for result in response.results:
        if result.id in batch_ids:
            relevant[result.id] = result.reason
        else:
            print(f"  Ignoring id {result.id}: not in this batch")

    return relevant
