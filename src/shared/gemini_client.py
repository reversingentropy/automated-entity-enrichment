"""
Shared Gemini client.

Exposes one entry point, `generate_json()`, which sends a prompt and returns a
validated Pydantic object. JSON is enforced by passing the model a response
schema, so we never have to scrape ```json fences out of prose.

Which models each job uses is set in config/pipeline.toml; the jobs pass
their chain in.
"""

import os
import random
import re
import time
from typing import TypeVar

from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel, ValidationError

load_dotenv()

T = TypeVar("T", bound=BaseModel)

_client: genai.Client | None = None

# The longest one request may take. Without a limit, a request that never came
# back held a job until GitHub killed it: three nights of relevance, extraction
# and resolution each sat silent for their whole 30 or 60 minutes. A batch of a
# hundred articles at high thinking has room to answer in five.
REQUEST_TIMEOUT_S = 300


def get_client() -> genai.Client:
    """Return the process-wide Gemini client, creating it on first use."""
    global _client
    if _client is not None:
        return _client

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing GEMINI_API_KEY. Set it in .env locally, or as a GitHub "
            "Actions secret in CI."
        )

    from google.genai import types
    _client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_S * 1000))
    return _client


def _retry_after(exc: Exception) -> float | None:
    """
    How long the server asked us to wait, if it said.

    Gemini puts the wait in the 429 body ("Please retry in 20.3s", or a
    retryDelay field). Honouring it matters: backing off for less simply burns
    another request against the same quota.
    """
    for pattern in (r"retry in ([\d.]+)s", r"retryDelay['\":\s]+([\d.]+)s"):
        match = re.search(pattern, str(exc), re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _is_quota_exhausted(exc: Exception) -> bool:
    """
    True for a quota refusal, as opposed to a transient server error.

    Backing off does not help once a daily cap is reached, so this is the
    signal to move down the model chain rather than keep waiting.
    """
    text = str(exc).lower()
    return any(s in text for s in ("429", "rate limit", "resource_exhausted",
                                   "quota", "too_many_requests"))


def _is_daily_cap(exc: Exception) -> bool:
    """
    True for a per-day quota refusal. Gemini names the quota in the refusal
    (GenerateRequestsPerDayPerProjectPerModel...), and still suggests a retry
    in seconds, which cannot help until the next day.
    """
    return "perday" in str(exc).lower().replace(" ", "")


# Models whose daily cap ran out during this run. Without this, every item
# after the cap rediscovered it: several waits on each spent model before
# falling through, minutes per item for nothing.
_SPENT: set[str] = set()

# Models that did not answer during this run: a request that ran out its time,
# or an overload that outlasted every retry. The rest of the run does not wait
# on them again, so a job with nothing answering ends in minutes and leaves its
# queue for the next run, instead of spending its whole time limit item by item.
_SILENT: set[str] = set()

# The model that answered the most recent call. A chain can fall through to a
# weaker model, so the jobs store this beside each result.
LAST_MODEL: str | None = None


def _is_timeout(exc: Exception) -> bool:
    """A request that ran out its time: retrying it only waits the same again."""
    import httpx
    return isinstance(exc, httpx.TimeoutException) or "timed out" in str(exc).lower()


def _is_silence(exc: Exception) -> bool:
    """The model did not answer: it timed out, or was still overloaded after every retry."""
    text = str(exc).lower()
    return _is_timeout(exc) or "503" in text or "unavailable" in text or "high demand" in text


def _is_retryable(exc: Exception) -> bool:
    """True for rate limits and transient server errors."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code in (429, 500, 502, 503, 504):
        return True
    text = str(exc).lower()
    return any(s in text for s in ("429", "rate limit", "resource_exhausted",
                                   "unavailable", "deadline", "internal error"))


def _raw_call(model: str, prompt: str, schema: type[T], thinking_level: str) -> str:
    """
    One call to Gemini, returning raw JSON text. If the SDK surface changes,
    this is the only function that needs updating.

    generateContent, not the Interactions API this used to prefer. In October
    the Interactions endpoint answered gemini-3.8-flash with 503 "high demand"
    and Retry-After: 30 while generateContent answered the same model at once;
    and the SDK retries Interactions calls by itself, sleeping whatever the
    server asks, so the error never reached this code and a job sat silent
    until it was killed. generateContent makes one attempt, and the retrying
    is left to _generate_one, which says what it is waiting for.
    """
    from google.genai import types

    response = get_client().models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=schema.model_json_schema(),
            thinking_config=types.ThinkingConfig(thinking_level=thinking_level.upper()),
            # No tools are passed; without this the SDK warns about tool calling on every request.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    return response.text


def generate_json(
    model: str | list[str],
    prompt: str,
    schema: type[T],
    thinking_level: str = "medium",
    retries: int = 4,
) -> T:
    """
    Send `prompt` to the first model with quota left, and validate the answer.

    `model` may be a single id or an ordered chain, strongest first. Each is
    retried for transient failures; only a quota refusal moves to the next,
    since waiting cannot recover a daily cap. Raises once the chain is
    exhausted -- callers depend on that, so a failed batch is left unwritten
    rather than written wrong.
    """
    models = [model] if isinstance(model, str) else list(model)
    answering = [m for m in models if m not in _SILENT]
    if not answering:
        raise RuntimeError(f"{', '.join(models)} did not answer earlier in this run; left for the next run")
    live = [m for m in answering if m not in _SPENT] or answering[-1:]
    last_exc: Exception | None = None

    global LAST_MODEL
    for index, candidate in enumerate(live):
        try:
            result = _generate_one(candidate, prompt, schema, thinking_level, retries)
            LAST_MODEL = candidate
            return result
        except Exception as exc:
            last_exc = exc
            if _is_daily_cap(exc):
                _SPENT.add(candidate)
            if _is_silence(exc):
                _SILENT.add(candidate)
                print(f"  {candidate} did not answer ({type(exc).__name__}: {str(exc)[:160]}); not asked again this run")
                if index < len(live) - 1:
                    continue
            is_last = index == len(live) - 1
            if is_last or not _is_quota_exhausted(exc):
                raise
            kind = "daily cap" if _is_daily_cap(exc) else "rate limit"
            print(f"  {candidate} hit its {kind} ({exc}), falling back to {live[index + 1]}")

    raise RuntimeError("no model available") from last_exc


def _generate_one(
    model: str,
    prompt: str,
    schema: type[T],
    thinking_level: str,
    retries: int,
) -> T:
    """One model, with backoff for transient failures."""
    last_exc: Exception | None = None

    for attempt in range(retries):
        try:
            raw = _raw_call(model, prompt, schema, thinking_level)
            return schema.model_validate_json(raw)
        except ValidationError as exc:
            # A schema-violating response won't fix itself on retry.
            raise RuntimeError(
                f"{model} returned JSON that does not match {schema.__name__}: {exc}"
            ) from exc
        except Exception as exc:
            if _is_daily_cap(exc) or _is_timeout(exc) or not _is_retryable(exc) or attempt == retries - 1:
                raise
            last_exc = exc
            # Prefer the server's own hint over blind exponential backoff.
            hinted = _retry_after(exc)
            delay = min(hinted + 1 if hinted else 2 ** attempt + random.uniform(0, 1), 120)
            print(f"  {type(exc).__name__}: {exc}\n"
                  f"    retrying in {delay:.1f}s ({attempt + 1}/{retries - 1})")
            time.sleep(delay)

    raise RuntimeError(f"Exhausted retries calling {model}") from last_exc
