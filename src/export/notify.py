"""
The daily email: each reviewer hears from the desk only when there is
something for them, and otherwise not at all.

    python -m src.export --notify [--dry-run]

Run once a day after the midnight pipeline. A reviewer is written to only if
at least one of these holds for them:

  - a card on their desk: one they hold and have not stamped;
  - changes to apply: decisions they approved and have not marked done in TTE;
  - cards waiting in their part of the pile: matching the groups and
    languages they chose on the desk, counted by group;
  - something new since yesterday: new cards, a new TTE dump loaded, or a
    pipeline step that failed.

The email carries that reviewer's own list and the team's totals, never
another person's numbers. Test accounts get nothing.

Mail settings come from the environment: MAIL_SERVER, MAIL_PORT (default
587), MAIL_USERNAME, MAIL_PASSWORD, MAIL_FROM. Without them, or with
--dry-run, the emails are printed instead of sent.
"""

import datetime as dt
import os
import re
import smtplib
from email.message import EmailMessage

GROUPS = [("people", "People", {"PERSON"}), ("organisations", "Organisations", {"ORGANISATION"}),
          ("legal acts", "Legal acts", {"LEGAL_ACT"}), ("everything else", "Everything else", None)]
STEP_NAMES = {"ingest": "RSS ingestion", "load": "loading the TTE dump", "relevance": "relevance",
              "extraction": "extraction", "resolution": "matching", "publish": "publishing the cards"}


def group_of(card: dict) -> str:
    return next(key for key, _, types in GROUPS if types is None or card.get("type") in types)


def languages_of(card: dict) -> set[str]:
    """As the desk reads it: the language of each article the card came from."""
    def lang(link: str) -> str:
        return ("zh" if re.search("zaobao", link) else "ms" if re.search("beritaharian", link)
                else "ta" if re.search("tamilmurasu", link) else "en")
    return {lang(s.get("link") or "") for s in card.get("sources") or []} or {"en"}


def messages(people: list[dict], cards: list[dict], reviews: list[dict], holds: list[dict],
             news: dict, desk_url: str = "") -> list[dict]:
    """
    One email per reviewer with something to act on; none for anyone else.

    `people` are {id, email, name, langs, types}; `reviews` and `holds` are the
    desk's rows; `news` is {new_cards, dump, failed}.
    """
    decided = {r["card_key"] for r in reviews}
    held_by = {h["card_key"]: h["reviewer"] for h in holds}
    by_key = {c["key"]: c for c in cards}
    kept = len({r["card_key"] for r in reviews if (r.get("decision") or {}).get("verdict") == "unsure"})
    team = f"The team so far: {len(cards)} cards, {len(decided)} decided, {kept} kept for review."
    new_lines = []
    if news.get("new_cards"):
        new_lines.append(f"{news['new_cards']} new card{'s' if news['new_cards'] != 1 else ''}")
    if news.get("dump"):
        new_lines.append(f"TTE dump {news['dump']} loaded")
    for step in news.get("failed") or []:
        new_lines.append(f"the {STEP_NAMES.get(step, step)} step failed")

    out = []
    for p in people:
        mine_held = [c for k, c in by_key.items() if held_by.get(k) == p["id"] and k not in decided]
        to_apply: dict[str, int] = {}
        for r in reviews:
            d = r.get("decision") or {}
            if r["reviewer"] == p["id"] and d.get("verdict") == "approve" and not d.get("done"):
                name = (by_key.get(r["card_key"]) or {}).get("entity") or d.get("entity") or r["card_key"]
                to_apply[name] = max(to_apply.get(name, 0), len(d.get("rows") or []) or 1)
        groups, langs = p.get("types"), set(p.get("langs") or ["en"])
        waiting: dict[str, int] = {}
        for k, c in by_key.items():
            if k in decided or k in held_by:
                continue
            if groups and group_of(c) not in groups:
                continue
            if not languages_of(c) & langs:
                continue
            waiting[group_of(c)] = waiting.get(group_of(c), 0) + 1

        if not (mine_held or to_apply or waiting or new_lines):
            continue
        subject, body = [], [f"Hello {p.get('name') or p['email'].split('@')[0]},", ""]
        if mine_held:
            subject.append(f"{len(mine_held)} card{'s' if len(mine_held) > 1 else ''} on your desk")
            body += [f"On your desk: {', '.join(c['entity'] for c in mine_held)}. "
                     "It stays yours until you stamp it.", ""]
        if to_apply:
            n = sum(to_apply.values())
            subject.append(f"{n} change{'s' if n != 1 else ''} to make in TTE")
            body.append("To make in TTE, then mark done on Your sheet:")
            for name, k in list(to_apply.items())[:10]:
                body.append(f"  - {name} ({k} change{'s' if k != 1 else ''})")
            if len(to_apply) > 10:
                body.append(f"  ... and {len(to_apply) - 10} more records")
            body.append("")
        if waiting:
            total = sum(waiting.values())
            subject.append(f"{total} card{'s' if total != 1 else ''} waiting")
            parts = ", ".join(f"{name} {waiting[key]}" for key, name, _ in GROUPS if waiting.get(key))
            body += [f"Waiting in your part of the pile: {total} ({parts}).", ""]
        if new_lines:
            body += ["New since yesterday: " + "; ".join(new_lines) + ".", ""]
        body.append(team)
        if desk_url:
            body += ["", desk_url]
        out.append({"to": p["email"], "subject": "TTE desk: " + (" · ".join(subject) or "news from the desk"),
                    "body": "\n".join(body) + "\n"})
    return out


def gather() -> tuple[list[dict], list[dict], list[dict], list[dict], dict]:
    """Everything messages() needs, read with the service role."""
    from src.export.accounts import is_test
    from src.shared.pagination import fetch_all
    from src.shared.supabase_client import get_client

    client = get_client()
    people = []
    for u in client.auth.admin.list_users():
        if is_test(u) or not u.email:
            continue
        meta = u.user_metadata or {}
        people.append({"id": u.id, "email": u.email, "name": meta.get("name") or "",
                       "langs": meta.get("langs") or ["en"], "types": meta.get("types")})
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)).isoformat()
    deck = fetch_all(lambda: client.from_("deck").select("key, card, built_at"), order="key")
    reviews = fetch_all(lambda: client.from_("reviews").select("pid, card_key, reviewer, decision"), order="pid")
    holds = fetch_all(lambda: client.from_("claims").select("card_key, reviewer"), order="card_key")
    dumps = (client.from_("tte_imports").select("filename").eq("entity_type", "DUMP")
             .gte("loaded_at", since).execute().data)
    steps = dict(pair.split("=", 1) for pair in os.environ.get("PIPELINE_STEPS", "").split(",") if "=" in pair)
    news = {"new_cards": sum(1 for d in deck if (d.get("built_at") or "") >= since),
            "dump": dumps[0]["filename"] if dumps else None,
            "failed": [s for s, outcome in steps.items() if outcome == "failure"]}
    return people, [d["card"] for d in deck], reviews, holds, news


def send(mails: list[dict], dry_run: bool = False) -> int:
    """Send through the environment's mail server, or print when there is none."""
    server, sender = os.environ.get("MAIL_SERVER"), os.environ.get("MAIL_FROM")
    if dry_run or not (server and sender and os.environ.get("MAIL_USERNAME") and os.environ.get("MAIL_PASSWORD")):
        for m in mails:
            print(f"--- to {m['to']}: {m['subject']}\n{m['body']}")
        if not dry_run:
            print("No mail settings (MAIL_SERVER, MAIL_FROM, MAIL_USERNAME, MAIL_PASSWORD): printed, not sent.")
        return 0
    with smtplib.SMTP(server, int(os.environ.get("MAIL_PORT") or 587), timeout=60) as smtp:
        smtp.starttls()
        smtp.login(os.environ["MAIL_USERNAME"], os.environ["MAIL_PASSWORD"])
        for m in mails:
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = sender, m["to"], m["subject"]
            msg.set_content(m["body"])
            smtp.send_message(msg)
    return len(mails)
