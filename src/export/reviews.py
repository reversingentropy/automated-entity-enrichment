"""
Collect librarians' review decisions into a spreadsheet.

Decisions arrive two ways: as the CSV a reviewer downloaded from the desk
(review-decisions-<name>.csv, in a folder), or from the online desk's
`reviews` table (pass "table"). One row per reviewer per proposal either
way: several librarians may judge the same proposal, and a single row per
proposal would mean the second verdict silently replaced the first. Here
disagreement is visible rather than lost.
"""

import csv
import json
from pathlib import Path

from src.export.cards import build_cards

COLUMNS = [
    "proposal_id", "reviewer", "entity", "type", "verdict",
    "chose_record", "record_name", "found_by_search", "reason", "note",
    "changes_applied", "changes_dropped", "edited_wording",
    "seconds", "article", "decided_at",
]


def from_table() -> list[tuple[dict, Path]]:
    """Every decision in the online desk's `reviews` table, as the desk wrote it."""
    from src.export.accounts import is_test
    from src.shared.pagination import fetch_all
    from src.shared.supabase_client import get_client
    client = get_client()
    names, testers = {}, set()
    try:
        for u in client.auth.admin.list_users():
            meta = u.user_metadata or {}
            names[u.id] = meta.get("name") or (u.email or "").split("@")[0]
            # A test account's decisions are practice, not evidence.
            if is_test(u):
                testers.add(u.id)
    except Exception:
        pass
    rows = fetch_all(lambda: client.from_("reviews").select("pid, reviewer, decision, at"))
    out = []
    for r in rows:
        if r["reviewer"] in testers:
            continue
        doc = dict(r["decision"] or {})
        doc["pid"] = r["pid"]
        doc["reviewer"] = names.get(r["reviewer"]) or doc.get("reviewer") or r["reviewer"]
        doc.setdefault("at", r["at"])
        out.append((doc, Path("reviews-table") / str(r["pid"]) / str(r["reviewer"])))
    return out


def collect(reviews_dir: Path | str) -> list[dict]:
    """
    Join decisions against the proposals they judged.

    `reviews_dir` is a folder of the desk's CSVs, or "table" for the online
    desk's rows.
    """
    cards = {}
    dealt, _ = build_cards()
    for card in dealt:
        for pid in card["pids"]:
            cards[str(pid)] = card

    docs: list[tuple[dict, Path]] = []
    if str(reviews_dir) == "table":
        docs = from_table()
        reviews_dir = Path("/nonexistent")
    for path in sorted(Path(reviews_dir).rglob("*.json")) if Path(reviews_dir).exists() else []:
        try:
            docs.append((json.loads(path.read_text(encoding="utf-8")), path))
        except json.JSONDecodeError:
            continue
    for path in sorted(Path(reviews_dir).rglob("*.csv")) if Path(reviews_dir).exists() else []:
        # The desk's own sheet: one row per proposal, the reviewer in a
        # column on newer sheets and in the filename on older ones.
        who = path.stem.removeprefix("review-").removeprefix("decisions-")
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                if "proposal_id" not in r:
                    break
                docs.append(({"pid": r["proposal_id"], "entity": r.get("entity", ""),
                              "verdict": r.get("verdict", ""), "chose": r.get("chose") or None,
                              "reason": r.get("reason", ""), "note": r.get("note", ""),
                              "changes": [x.strip() for x in (r.get("applied") or "").split(";") if x.strip()],
                              "dropped": [x.strip() for x in (r.get("dropped") or "").split(";") if x.strip()],
                              "foundBySearch": (r.get("found_by_search") or "").lower() == "yes",
                              "seconds": r.get("seconds", ""),
                              "reviewer": r.get("reviewer") or who, "at": r.get("at", "")}, path))

    rows = []
    for doc, path in docs:
        pid = str(doc.get("pid") or path.parent.parent.name)
        card = cards.get(pid, {})
        chose = doc.get("chose")
        record = next((o["name"] for o in card.get("options", []) if o["uid"] == chose), "")
        edits = doc.get("edits") or {}
        rows.append({
            "proposal_id": pid,
            "reviewer": doc.get("reviewer", "") or path.stem,
            "entity": doc.get("entity", "") or card.get("entity", ""),
            "type": card.get("type", ""),
            "verdict": doc.get("verdict", ""),
            "chose_record": "" if chose in (None, "new-entity") else chose,
            "record_name": "new record" if chose == "new-entity" else record,
            # True marks a record retrieval should have offered and did not.
            "found_by_search": "yes" if doc.get("foundBySearch") else "",
            "reason": doc.get("reason", ""),
            "note": doc.get("note", ""),
            "changes_applied": "; ".join(doc.get("changes") or []),
            "changes_dropped": "; ".join(doc.get("dropped") or []),
            "edited_wording": " || ".join(f"{k}: {v}" for k, v in edits.items()),
            # From the card coming onto the desk to the stamp: the app's side
            # of the time comparison the team asked for.
            "seconds": doc.get("seconds", ""),
            "article": (card.get("sources") or [{}])[0].get("article", ""),
            "decided_at": doc.get("at", ""),
        })
    rows.sort(key=lambda r: (r["entity"], r["reviewer"]))
    return rows


def disagreements(rows: list[dict]) -> list[dict]:
    """Proposals where reviewers reached different verdicts."""
    by_pid: dict[str, list[dict]] = {}
    for row in rows:
        by_pid.setdefault(row["proposal_id"], []).append(row)
    return [r for group in by_pid.values() if len({g["verdict"] for g in group}) > 1
            for r in group]
