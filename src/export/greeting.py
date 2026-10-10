"""
A short line for the desk's home screen, written by the model once a day.

The nightly publish asks for it and puts it in the desk file beside the
pipeline's status; the page shows it under the reviewer's greeting on the day
it was written, and not after. One request a day at most: the noon run finds
the morning's line already written and keeps it. If the model cannot be
reached, or answers with something unusable, there is simply no line.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel

PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "desk_greeting.txt"
SINGAPORE = timezone(timedelta(hours=8))
MAX_CHARS = 140


class Line(BaseModel):
    line: str


def today_in_singapore() -> datetime:
    return datetime.now(SINGAPORE)


def clean(text: str) -> str:
    """One line, no wrapping quotes, short enough for the screen; "" if it is not."""
    first = next((t.strip() for t in str(text or "").splitlines() if t.strip()), "")
    first = first.strip(' "“”\'')
    return first if 0 < len(first) <= MAX_CHARS else ""


def daily_line(previous: dict | None = None, now: datetime | None = None) -> dict:
    """
    {"date": "YYYY-MM-DD", "text": "..."} for today, or {} when there is none.

    `previous` is the line in the desk file already published: kept as it is
    if it is today's.
    """
    now = now or today_in_singapore()
    day = now.date().isoformat()
    previous = previous or {}
    if previous.get("date") == day and previous.get("text"):
        return previous
    try:
        from src.shared.config import SETTINGS
        from src.shared.gemini_client import generate_json
        prompt = PROMPT.read_text(encoding="utf-8").format(
            weekday=now.strftime("%A"), date=now.strftime("%-d %B %Y"),
            previous=previous.get("text") or "none")
        got = generate_json(SETTINGS.greeting.models, prompt, Line, thinking_level=SETTINGS.greeting.thinking)
    except Exception as exc:
        print(f"  no line for the desk today: {exc}")
        return {}
    text = clean(got.line)
    return {"date": day, "text": text} if text else {}
