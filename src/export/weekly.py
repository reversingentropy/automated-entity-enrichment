"""
The week's approved changes, as the Excel file the reviewers work from.

    python -m src.export --weekly                     # the last seven days
    python -m src.export --weekly --since 2026-09-21  # from a date

Agreed with Yaw Huah, 28 Sep 2026: one file a week, two sheets (existing
entities and new ones), one row per change, and a Status column each reviewer
sets to Done once the change is in TTE. Each reviewer applies their own
changes by hand, so rows are grouped by reviewer. Test accounts are left out.
"""

import datetime as dt
import re
from pathlib import Path

HEADERS = ["UID", "Descriptor", "Vocab Class", "Attribute", "Current Value",
           "Suggested Value", "Article URL", "Reviewer", "Timestamp", "Status"]
SGT = dt.timezone(dt.timedelta(hours=8))

# The desk's own test: a name in Chinese, Malay-Jawi or Tamil script.
_NON_LATIN = re.compile(r"[^\x00-\x7FÀ-ɏ\s.,'’()\-]")


def _day(stamp: str) -> str:
    """An ISO time as the Singapore date, written 28/9/2026."""
    when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(SGT)
    return f"{when.day}/{when.month}/{when.year}"


def rows_for(decisions: list[dict], cards: dict[str, dict], vocab_of: dict[str, str],
             vocab_for_type: dict[str, str]) -> tuple[list[list], list[list]]:
    """
    Existing-entity rows and new-entity rows, one per change.

    `decisions` are the desk's labels (one per proposal); `cards` maps each
    proposal id to its card; `vocab_of` maps a record's UID to its TTE
    vocabulary, `vocab_for_type` an entity type to the vocabulary a new record
    goes into. A card settled several proposals with one decision, so each
    decision is taken once per card, and a change repeated by two articles is
    one row.
    """
    existing, new, seen_cards, seen_rows = [], [], set(), set()
    for d in sorted(decisions, key=lambda d: d.get("at") or ""):
        card = cards.get(str(d.get("pid")))
        if d.get("verdict") != "approve" or not card or card["key"] in seen_cards:
            continue
        seen_cards.add(card["key"])
        who, when = d.get("reviewer", ""), _day(d["at"])
        # Marked on the desk once the change is made in TTE.
        status = "Done" if d.get("done") else ""
        src = (card.get("sources") or [{}])[0]

        def add(sheet, uid, name, vocab, attr, current, proposed, link):
            key = (uid or name, attr, proposed)
            if key not in seen_rows:
                seen_rows.add(key)
                sheet.append([uid, name, vocab, attr, current, proposed, link or src.get("link", ""), who, when, status])

        if d.get("chose") == "new-entity":
            name = f"{card['entity']} ({card['entityEn']})" if card.get("entityEn") else card["entity"]
            vocab = vocab_for_type.get(card.get("type", ""), "")
            fields = card.get("newsFields") or []
            for f in fields:
                add(new, "", name, vocab, f["key"], "", f["value"], None)
            if not fields:
                add(new, "", name, vocab, "Name", "", name, None)
            continue

        uid, record = d.get("chose") or "", d.get("record") or ""
        vocab = vocab_of.get(uid, "")
        # A Chinese name confirmed against an English record is a variant name
        # TTE lacks; once added, the next article in that language matches it.
        if _NON_LATIN.search(card["entity"]) and record and not _NON_LATIN.search(record):
            add(existing, uid, record, vocab, "Variant name", "", card["entity"], None)
        for r in d.get("rows") or []:
            add(existing, uid, record, vocab, r["field"], r.get("current", ""), r.get("proposed", ""), r.get("from"))

    order = lambda row: (row[7], row[1], row[3])
    return sorted(existing, key=order), sorted(new, key=order)


WIDTHS = {"UID": 12, "Descriptor": 32, "Vocab Class": 16, "Attribute": 24, "Current Value": 40,
          "Suggested Value": 40, "Article URL": 50, "Article Date": 12, "Reviewer": 16, "Timestamp": 12,
          "Status": 10}


def write(existing: list[list], new: list[list], path: Path, headers: list[str] = HEADERS) -> Path:
    """
    The two sheets, headers bold, columns sized, Status (the last column) a
    Done/blank list. A date value is written as a real date, so Excel sorts
    and filters it as one.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    status = get_column_letter(len(headers))
    for i, (title, rows) in enumerate((("Existing entities", existing), ("New entities", new))):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = title
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for r, row in enumerate(rows, start=2):
            ws.append(row)
            for c, value in enumerate(row, start=1):
                if isinstance(value, dt.date):
                    ws.cell(row=r, column=c).number_format = "d/m/yyyy"
        ws.freeze_panes = "A2"
        for n, name in enumerate(headers, start=1):
            ws.column_dimensions[get_column_letter(n)].width = WIDTHS.get(name, 16)
        done = DataValidation(type="list", formula1='"Done"', allow_blank=True)
        ws.add_data_validation(done)
        done.add(f"{status}2:{status}{max(len(rows) + 1, 2) + 200}")
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def build(since: dt.date, out: Path | None = None) -> tuple[Path, int, int]:
    """Read the week's decisions and the deck, and write the file."""
    from src.export.reviews import from_table
    from src.shared.pagination import fetch_all
    from src.shared.supabase_client import get_client

    client = get_client()
    start = dt.datetime.combine(since, dt.time(), SGT)
    decisions = [doc for doc, _ in from_table()
                 if dt.datetime.fromisoformat(doc["at"].replace("Z", "+00:00")) >= start]
    cards = {}
    for r in fetch_all(lambda: client.from_("deck").select("key, card"), order="key"):
        for pid in r["card"].get("pids") or []:
            cards[str(pid)] = r["card"]
    uids = sorted({d.get("chose") for d in decisions if d.get("chose") not in (None, "", "new-entity")})
    vocab_of = {}
    for i in range(0, len(uids), 200):
        for e in client.from_("entities").select("uid, vocabulary").in_("uid", uids[i:i + 200]).execute().data:
            vocab_of[e["uid"]] = e["vocabulary"]
    vocab_for_type = {}
    for t in {c.get("type") for c in cards.values()}:
        hit = client.from_("entities").select("vocabulary").eq("entity_type", t).eq("language", "en").limit(1).execute().data
        if hit:
            vocab_for_type[t] = hit[0]["vocabulary"]
    existing, new = rows_for(decisions, cards, vocab_of, vocab_for_type)
    today = dt.datetime.now(SGT).date()
    out = out or Path("data/changes") / f"approved-changes-{today.isoformat()}.xlsx"
    return write(existing, new, out), len(existing), len(new)
