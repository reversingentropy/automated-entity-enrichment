"""
Publish the deck for the online desk.

    python -m src.export --publish

The cards the zip embeds go into the `deck` table instead, one row per card
keyed by the card's own key, and the search index, the NPT map and the
noted list go into the private `desk` bucket as one JSON file; the page
fetches both after sign-in. Runs nightly after Job 3 with the service role.

A card whose key is no longer built is removed unless a review names it, so
a decided card keeps its row and a reviewer's sheet can still reopen it.
"""

import json

from src.export.cards import build_cards, build_index, npt_map
from src.shared.pagination import fetch_all
from src.shared.supabase_client import get_client

BUCKET = "desk"
DESK_FILE = "desk.json"


def published_line(client) -> dict:
    """The line of the day in the desk file now in the bucket, or {} if there is none to read."""
    try:
        data = client.storage.from_(BUCKET).download(DESK_FILE)
        return (json.loads(data).get("status") or {}).get("line") or {}
    except Exception:
        return {}


def deck_rows(cards: list[dict]) -> list[dict]:
    """The `deck` rows for a built deck, one per card."""
    return [{"key": c["key"], "type": c["type"], "entity": c["entity"], "card": c} for c in cards]


def pipeline_status(cards: list[dict], steps: str | None, dump: str = "") -> dict:
    """
    What the team page shows of the pipeline, which reviewers' accounts cannot
    read directly: when this deck was published, the newest news in it, the TTE
    dump loaded, and how each step of this run went (PIPELINE_STEPS, set by the
    workflow as step=outcome pairs).
    """
    from datetime import datetime, timezone
    newest = max((s.get("date") or "" for c in cards for s in c.get("sources", [])), default="")
    outcomes = dict(pair.split("=", 1) for pair in (steps or "").split(",") if "=" in pair)
    return {"published": datetime.now(timezone.utc).isoformat(), "newest_news": newest,
            "tte_dump": dump, "steps": outcomes}


def desk_file(index: list[list], variants: list[list], noted: list[dict], status: dict | None = None) -> bytes:
    """The one JSON file the page fetches beside the deck."""
    body = {"index": index, "npt": npt_map(variants, index), "noted": noted, "status": status or {}}
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def publish(backfill: bool = False) -> dict:
    client = get_client()
    index, variants = build_index(with_variants=True)
    cards, noted = build_cards(backfill=backfill, index=index, variants=variants)
    rows = deck_rows(cards)

    for start in range(0, len(rows), 50):
        client.from_("deck").upsert(rows[start:start + 50], on_conflict="key").execute()

    built = {r["key"] for r in rows}
    held = fetch_all(lambda: client.from_("deck").select("key"), order="key")
    reviewed = {r["card_key"] for r in fetch_all(lambda: client.from_("reviews").select("card_key"),
                                                   order="card_key")}
    stale = [r["key"] for r in held if r["key"] not in built and r["key"] not in reviewed]
    for start in range(0, len(stale), 100):
        client.from_("deck").delete().in_("key", stale[start:start + 100]).execute()

    import os
    dumps = (client.from_("tte_imports").select("filename, snapshot").eq("entity_type", "DUMP")
             .order("snapshot", desc=True).limit(1).execute().data)
    dump = f"{dumps[0]['filename']} ({dumps[0]['snapshot']})" if dumps else ""
    status = pipeline_status(cards, os.environ.get("PIPELINE_STEPS"), dump)
    # The home screen's line of the day: today's is kept if the file already has it.
    from src.export.greeting import daily_line
    status["line"] = daily_line(published_line(client))
    client.storage.from_(BUCKET).upload(DESK_FILE, desk_file(index, variants, noted, status),
                                        {"content-type": "application/json", "upsert": "true"})
    return {"cards": len(rows), "removed": len(stale), "noted": len(noted), "index": len(index)}
