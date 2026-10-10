"""Build the extraction prompt and validate Gemini's answer."""

from pathlib import Path

from src.shared.field_rules import inject
from src.shared.config import SETTINGS
from src.shared.gemini_client import generate_json
from src.shared.models import ExtractionResponse

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "extraction.txt"


def load_prompt() -> str:
    return inject(PROMPT_PATH.read_text(encoding="utf-8"))


def render(title: str, article_text: str, published: str | None = None) -> str:
    """
    Combine the prompt template with one article.

    prompts/extraction.txt ends on a bare "Article:" marker, so
    the headline and body are appended directly after it, with the
    publication date first. Without it every "on Tuesday" and "last year" in
    an article from 2016 is a guess, and every dated field in TTE asks for a
    year.
    """
    when = f"Published: {str(published)[:10]}\n" if published else ""
    return f"{load_prompt()}\n{when}{title}\n\n{article_text}"


def extract(title: str, article_text: str, published: str | None = None) -> ExtractionResponse:
    """
    Extract entities from a single article.

    Unlike Job 1 this prompt handles one article per call -- it ends with a
    single "Article:" marker rather than taking a batch.
    """
    return generate_json(
        model=SETTINGS.extraction.models,
        prompt=render(title, article_text, published),
        schema=ExtractionResponse,
        thinking_level=SETTINGS.extraction.thinking,
    )
