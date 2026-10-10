"""The home screen's line of the day: one request a day, nothing shown when anything goes wrong."""

import json
from datetime import datetime

from src.export import greeting
from src.export.deck import published_line

MONDAY = datetime(2026, 10, 12, 0, 30, tzinfo=greeting.SINGAPORE)


def test_todays_line_is_kept_without_asking_the_model_again(monkeypatch):
    def never(*a, **k):
        raise AssertionError("the model was asked twice in one day")
    monkeypatch.setattr("src.shared.gemini_client.generate_json", never)
    kept = {"date": "2026-10-12", "text": "A fresh week of names to tidy."}
    assert greeting.daily_line(kept, now=MONDAY) == kept


def test_a_new_day_asks_the_model_and_cleans_its_answer(monkeypatch):
    asked = []
    def answer(models, prompt, schema, thinking_level="medium"):
        asked.append(prompt)
        return schema(line='"Monday: the catalogue missed you."\nand a second line')
    monkeypatch.setattr("src.shared.gemini_client.generate_json", answer)
    got = greeting.daily_line({"date": "2026-10-11", "text": "Sunday's line"}, now=MONDAY)
    assert got == {"date": "2026-10-12", "text": "Monday: the catalogue missed you."}
    assert "Monday, 12 October 2026" in asked[0] and "Sunday's line" in asked[0]


def test_no_line_when_the_model_fails_or_rambles(monkeypatch):
    def down(*a, **k):
        raise RuntimeError("quota")
    monkeypatch.setattr("src.shared.gemini_client.generate_json", down)
    assert greeting.daily_line(None, now=MONDAY) == {}
    assert greeting.clean("x" * 200) == ""
    assert greeting.clean("   ") == ""


class _Bucket:
    def __init__(self, body):
        self.body = body
    def from_(self, name):
        return self
    def download(self, path):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class _Client:
    def __init__(self, body):
        self.storage = _Bucket(body)


def test_the_published_line_is_read_back_from_the_desk_file():
    line = {"date": "2026-10-12", "text": "Hello"}
    assert published_line(_Client(json.dumps({"status": {"line": line}}).encode())) == line
    assert published_line(_Client(json.dumps({"status": {}}).encode())) == {}
    assert published_line(_Client(RuntimeError("no file yet"))) == {}
