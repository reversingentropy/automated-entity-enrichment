"""Build the resolution prompt for one article and validate the answer."""

import json
from pathlib import Path

from src.shared.field_rules import inject
from src.shared.config import SETTINGS
from src.shared.gemini_client import generate_json
from src.shared.models import ResolutionResponse

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "resolution.txt"

# Fields the model does not need. Dropping them keeps candidate blocks, which
# dominate the prompt, as small as they can usefully be.
DROP_FROM_CANDIDATE = ("matched_uid", "matched_language", "canonical_type")


def load_prompt() -> str:
    return inject(PROMPT_PATH.read_text(encoding="utf-8"))


def build_entity_block(entity: dict, candidates: list[dict],
                       article_title: str = "") -> dict:
    """One entity plus the candidates retrieved for it."""
    return {
        "article_title": article_title,
        "entity_name": entity["entity_name"],
        "entity_name_en": entity.get("entity_name_en"),
        "entity_type": entity["entity_type"],
        "summary": entity.get("summary"),
        "evidence": entity.get("evidence"),
        "fields": entity.get("fields") or {},
        "candidates": [
            {k: v for k, v in c.items() if k not in DROP_FROM_CANDIDATE}
            for c in candidates
        ],
    }


def render(blocks: list[dict]) -> str:
    return load_prompt().replace(
        "{article_entities}", json.dumps(blocks, ensure_ascii=False, indent=2))


def resolve(blocks: list[dict]) -> ResolutionResponse:
    """
    Resolve a batch of entities, which may span several articles.

    The prompt returns entries only for entities that matched or need flagging;
    anything omitted is understood to be new.
    """
    return generate_json(
        model=SETTINGS.resolution.models,
        prompt=render(blocks),
        schema=ResolutionResponse,
        thinking_level=SETTINGS.resolution.thinking,
    )
