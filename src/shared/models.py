"""
Pydantic models for every job's LLM response.

These mirror the JSON contracts written at the bottom of each file in
prompts/. They are passed to Gemini as a response schema so the model is
constrained to valid JSON, and re-validated on the way back.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


# --- Job 1: relevance ------------------------------------------------------
# prompts/relevance.txt returns ONLY the articles that are relevant.
# Anything absent from `results` is not relevant.

class RelevanceResult(BaseModel):
    id: int
    reason: str = Field(description="Brief explanation for inclusion.")


class RelevanceResponse(BaseModel):
    results: list[RelevanceResult]


# --- Job 2: field extraction ----------------------------------------------
# prompts/extraction.txt

EntityType = Literal[
    "PERSON", "ORGANISATION", "FACILITY", "LOCATION",
    "EVENT", "AWARD", "PROGRAMME", "LEGAL_ACT",
]


class ExtractedEntity(BaseModel):
    entity_name: str
    entity_name_en: Optional[str] = Field(
        default=None,
        description="English or romanised name, when entity_name is not English.",
    )
    entity_type: EntityType
    summary: str
    evidence: str = Field(description="One sentence copied verbatim from the article.")
    evidence_en: Optional[str] = Field(
        default=None,
        description="English translation of evidence, when the source is not English.",
    )
    fields: dict[str, str] = Field(default_factory=dict)
    confidence: str = "high"
    # Required but nullable: the API must fill it (a default would keep it
    # out of the schema's required list, which is how field_updates once went
    # missing from every match), while an answer from a model that was never
    # asked is read with role=None and the reviewer's deck falls back to the
    # headline.
    role: Optional[Literal["subject", "mentioned"]] = Field(
        description="\"subject\" when the article is about this entity and its change is "
                    "the news; \"mentioned\" for anyone else the article names.",
    )


class ExtractionResponse(BaseModel):
    entities: list[ExtractedEntity]


# --- Job 3: entity resolution ---------------------------------------------
# prompts/resolution.txt returns a single object per article entity.

class FieldUpdate(BaseModel):
    field: str
    # MERGE and REPLACE both set the field to `value`; they differ in what the
    # model was asked to do. MERGE preserves what the record already said,
    # REPLACE deliberately discards it -- a distinction the reviewer needs,
    # since overwriting a curated description is the riskier of the two.
    strategy: Literal["APPEND", "REPLACE", "MERGE", "INSERT_RELATION"]
    value: str


class InverseUpdate(BaseModel):
    target_db_id: str
    field: str
    strategy: Literal["INSERT_RELATION"]
    value: str


class ResolutionResult(BaseModel):
    """One entity's resolution. The prompt returns one of these per entity."""

    article_entity_name: str
    entity_type: EntityType
    resolution_action: Literal[
        "MATCH_AND_UPDATE", "CREATE_NEW", "RE_QUERY_REQUIRED",
        "FLAG_DB_DUPLICATE", "FLAG_AMBIGUOUS",
    ]
    # matched_id and field_updates carry no default on purpose. A field with a
    # default is absent from the JSON schema's `required` list, and a model
    # generating against that schema will simply omit it -- which is exactly
    # what happened: every MATCH_AND_UPDATE came back with no field updates at
    # all. Required-but-nullable forces an explicit decision.
    matched_id: Optional[str]
    confidence: Literal["high", "medium", "low"]
    reasoning: str
    field_updates: list[FieldUpdate]
    inverse_updates: list[InverseUpdate] = Field(default_factory=list)
    re_query_term: Optional[str] = None
    duplicate_db_ids: list[str] = Field(default_factory=list)

    def matched_uid_is_invalid(self, offered: set[str]) -> bool:
        """
        True if this claims a match the retriever never offered.

        MATCH_AND_UPDATE must name one of that entity's own candidates. The
        other actions carry no match, so a uid on them is meaningless.
        """
        if self.resolution_action != "MATCH_AND_UPDATE":
            return False
        return self.matched_id is None or self.matched_id not in offered


class ResolutionResponse(BaseModel):
    """
    All resolutions for one article.

    Job 3 batches per article rather than per entity: entities from the same
    article are mutually informative, and one combined call costs far less than
    one call each (measured: 10 entities in 1 request at ~5.5k tokens, versus
    10 requests at ~21k).
    """

    resolutions: list[ResolutionResult]
