"""
Trial: can AI Singapore's SEA-LION answer the pipeline's questions? Nothing here touches the database or the nightly jobs.

The key is a trial key: free, rate-limited (10 requests a minute), and not for production use. So SEA-LION is only
ever asked here, never by the nightly pipeline, until the trial says it is worth a proper key.

    .venv/bin/python scripts/sealion_trial.py smoke      # which models the key reaches, and whether one answers in JSON
    .venv/bin/python scripts/sealion_trial.py relevance  # Job 1's prompt on the Malay and Tamil trial articles

relevance reads data/sea_news/articles.jsonl (scripts/sea_news.py) and asks three times, each answer kept under
data/sea_news/ so a re-run asks nothing again:
  - Gemini, exactly as Job 1 asks: the production prompt, model and settings, every article in one request
    (Job 1 sends up to 100 at a time). One request of the day's allowance.
  - SEA-LION, the same prompt and the same single batch, for a like-for-like comparison.
  - SEA-LION in batches of ten. Smaller batches find more (config/pipeline.toml), and SEA-LION's allowance is
    per minute rather than per day, so it could afford them.
Each article goes in as Job 1 would see it: the printed headline from the Google News sitemap, and the page's
own one-line summary as the description.

Needs SEALION_API_KEY in .env. The chat API is OpenAI's shape; it is called with httpx, so nothing new is installed.
"""

import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv()

TRIAL = ROOT / "data" / "sea_news"

BASE = "https://api.sea-lion.ai/v1"
MODEL = "aisingapore/Nemotron-SEA-LION-v4.8-120B-A12B"
PER_MINUTE = 10


def key() -> str:
    token = os.environ.get("SEALION_API_KEY", "").strip()
    if not token:
        sys.exit("SEALION_API_KEY is not set in .env")
    return token


def client() -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=120, headers={"Authorization": f"Bearer {key()}"})


def chat(c: httpx.Client, messages: list[dict], schema: dict | None = None, model: str = MODEL, **extra) -> tuple[dict, dict]:
    """One request: the reply and the response headers that say how much of the allowance is left."""
    body = {"model": model, "messages": messages, **extra}
    if schema:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema, "strict": True}}
    response = c.post("/chat/completions", json=body)
    limits = {k: v for k, v in response.headers.items() if "ratelimit" in k.lower() or k.lower() == "retry-after"}
    if response.status_code >= 400:
        return {"error": response.status_code, "body": response.text[:500]}, limits
    return response.json(), limits


SMOKE_SCHEMA = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean"},
        "entities": {"type": "array", "items": {"type": "object", "properties": {
            "name_en": {"type": "string"}, "name_original": {"type": "string"},
            "type": {"type": "string", "enum": ["PERSON", "ORGANISATION", "FACILITY", "OTHER"]}},
            "required": ["name_en", "name_original", "type"], "additionalProperties": False}},
        "evidence_en": {"type": "string"},
    },
    "required": ["relevant", "entities", "evidence_en"],
    "additionalProperties": False,
}

# Two lines in the style of each site's Singapore pages (written for this test, not quoted from an article).
SMOKE_TEXT = {
    "ms": "Masjid Al-Islah di Punggol akan dinaik taraf mulai Januari, kata Majlis Ugama Islam Singapura (Muis) dalam satu kenyataan.",
    "ta": "சிங்கப்பூர் இந்திய மரபுடைமை நிலையம் புதிய கண்காட்சியை அடுத்த மாதம் தொடங்கவுள்ளது என்று தேசிய மரபுடைமைக் கழகம் தெரிவித்தது.",
}


def smoke():
    with client() as c:
        response = c.get("/models")
        print(f"/models: {response.status_code}")
        if response.status_code < 400:
            ids = [m.get("id") for m in response.json().get("data", [])]
            print("  " + "\n  ".join(ids))
            if MODEL not in ids:
                print(f"  {MODEL} is not among them")
        for lang, text in SMOKE_TEXT.items():
            time.sleep(60 / PER_MINUTE)
            messages = [{"role": "system", "content": "You read Singapore news for a library's authority file. Answer in the JSON schema given."},
                        {"role": "user", "content": "Is this sentence about a Singapore organisation, place or person the library might keep a record of? "
                                                    "List each one with its English name and its name as written, and translate the sentence into English.\n\n" + text}]
            start = time.time()
            reply, limits = chat(c, messages, SMOKE_SCHEMA, max_completion_tokens=2000)
            took = time.time() - start
            if "error" in reply:
                print(f"{lang}: HTTP {reply['error']} after {took:.1f}s -- {reply['body']}")
                continue
            content = reply["choices"][0]["message"].get("content") or ""
            try:
                parsed = json.loads(content)
                shape = "matches the schema" if set(parsed) == set(SMOKE_SCHEMA["required"]) else f"keys {sorted(parsed)}"
            except json.JSONDecodeError:
                parsed, shape = None, "NOT JSON"
            print(f"{lang}: {took:.1f}s, {shape}, usage {reply.get('usage')}")
            print(f"  limits {limits}")
            print("  " + (json.dumps(parsed, ensure_ascii=False, indent=1) if parsed else content[:800]).replace("\n", "\n  "))


# Job 1's answer (src/shared/models.py RelevanceResponse), written out for SEA-LION's strict JSON mode.
RELEVANCE_SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "integer"}, "reason": {"type": "string"}},
        "required": ["id", "reason"], "additionalProperties": False}}},
    "required": ["results"],
    "additionalProperties": False,
}


def trial_articles() -> list[dict]:
    """
    The 92 pilot articles (16-18 Oct 2026, from the Google News sitemaps) as Job 1 would get them, numbered by
    their line in the file (it is only appended to). Only these: the archive collected after them into the same
    file must never reach the Gemini question by accident, at 100 articles a request.
    """
    lines = (TRIAL / "articles.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    return [{"id": n, "url": r["url"], "site": r["site"], "title": r.get("listed_title") or r.get("title") or "",
             "description": r.get("description") or ""}
            for n, r in enumerate(rows, 1) if "error" not in r and r.get("listed_in") == "googlenews"]


def sealion_relevance(c: httpx.Client, batch: list[dict]) -> dict[int, str]:
    from src.job1_relevance.prompt import render
    reply, _ = chat(c, [{"role": "user", "content": render(batch)}], RELEVANCE_SCHEMA, max_completion_tokens=16000)
    if "error" in reply:
        raise RuntimeError(f"SEA-LION HTTP {reply['error']}: {reply['body']}")
    ids = {a["id"] for a in batch}
    results = json.loads(reply["choices"][0]["message"]["content"])["results"]
    return {r["id"]: r["reason"] for r in results if r["id"] in ids}


def ask_once(path: Path, label: str, ask) -> dict[int, str]:
    """An answer already on file is read back, never asked again: the Gemini one spends the day's allowance."""
    if path.exists():
        return {int(k): v for k, v in json.loads(path.read_text(encoding="utf-8"))["relevant"].items()}
    start = time.time()
    relevant = ask()
    path.write_text(json.dumps({"asked": label, "seconds": round(time.time() - start, 1), "relevant": relevant},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{label}: {len(relevant)} relevant, {time.time() - start:.0f}s")
    return relevant


def relevance():
    arts = trial_articles()
    print(f"{len(arts)} articles")

    def gemini():
        from src.job1_relevance.prompt import classify
        return classify(arts)

    def sealion_tens():
        out = {}
        with client() as c:
            for i in range(0, len(arts), 10):
                if i:
                    time.sleep(60 / PER_MINUTE)
                out |= sealion_relevance(c, arts[i:i + 10])
        return out

    def sealion_one():
        with client() as c:
            return sealion_relevance(c, arts)

    answers = {
        "Gemini, one batch": ask_once(TRIAL / "relevance-gemini.json", "Gemini, one batch (Job 1 as it runs)", gemini),
        "SEA-LION, one batch": ask_once(TRIAL / "relevance-sealion-one.json", "SEA-LION, one batch", sealion_one),
        "SEA-LION, tens": ask_once(TRIAL / "relevance-sealion-tens.json", "SEA-LION, batches of ten", sealion_tens),
    }
    print()
    for label, rel in answers.items():
        by_site = {s: sum(1 for a in arts if a["id"] in rel and a["site"] == s) for s in ("bh", "tm")}
        print(f"{label:22} {len(rel):3} relevant  (Berita Harian {by_site['bh']}, Tamil Murasu {by_site['tm']})")
    print()
    for a in arts:
        said = [label for label, rel in answers.items() if a["id"] in rel]
        if not said:
            continue
        marks = "  ".join("G" if "Gemini" in l else ("S1" if "one" in l else "S10") for l in said)
        print(f"#{a['id']:<3} {a['site']}  [{marks}]  {a['title']}")
        print(f"      {a['description'][:200]}")
        for label in said:
            print(f"      {label}: {answers[label][a['id']]}")


if __name__ == "__main__":
    commands = {"smoke": smoke, "relevance": relevance}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(__doc__)
    commands[sys.argv[1]]()
