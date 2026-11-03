"""
The pipeline's settings, from config/pipeline.toml.

Checked when a job starts: a misspelt, missing or out-of-range setting stops
the run with the reason, rather than being ignored. Nothing overrides the file.
"""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PATH = Path(__file__).resolve().parents[2] / "config" / "pipeline.toml"


class _Job(BaseModel):
    model_config = ConfigDict(extra="forbid")
    models: list[str] = Field(min_length=1)
    thinking: Literal["minimal", "low", "medium", "high"]


class Relevance(_Job):
    batch_size: int = Field(gt=0)
    seconds_between_batches: int = Field(ge=0)


class Extraction(_Job):
    seconds_between_articles: int = Field(ge=0)


class Resolution(_Job):
    seconds_between_articles: int = Field(ge=0)
    articles_per_request: int = Field(gt=0)


class Combine(_Job):
    """One description addition per record from all its articles."""
    records_per_run: int = Field(gt=0)
    seconds_between_records: int = Field(ge=0)


class Greeting(_Job):
    """The line of the day on the desk's home screen: one request a day."""


class Notify(BaseModel):
    model_config = ConfigDict(extra="forbid")
    desk_url: str = ""


class Pipeline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relevance: Relevance
    extraction: Extraction
    resolution: Resolution
    combine: Combine = Combine(models=["gemini-3.8-flash"], thinking="high", records_per_run=5, seconds_between_records=5)
    greeting: Greeting = Greeting(models=["gemini-3.8-flash"], thinking="low")
    notify: Notify = Notify()


def load(path: Path = PATH) -> Pipeline:
    with open(path, "rb") as f:
        return Pipeline.model_validate(tomllib.load(f))


SETTINGS = load()
