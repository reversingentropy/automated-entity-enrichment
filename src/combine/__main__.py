"""
The combine step: one description addition per record from all its articles (docs/descriptions.md).

    python -m src.combine              # what the nightly run does, after Job 3
    python -m src.combine --dry-run    # ask and check, write nothing; prints each answer
    python -m src.combine --limit 2
    python -m src.combine --recheck    # the checks again on every stored draft, no model call

Runs on the deck as it would be built, so it combines exactly the description notes a reviewer would see, and
only those not combined yet: at most `records_per_run` a night (config/pipeline.toml), newest first.
"""

import argparse
import json
import sys
import time

from src.combine import TABLE, Combined, checked, prompt_for, records_from_cards, save, stored
from src.shared import gemini_client
from src.shared.config import SETTINGS


def pending(limit: int | None = None) -> list[dict]:
    from src.export.cards import build_cards, build_index
    index, variants = build_index(with_variants=True)
    cards, _ = build_cards(index=index, variants=variants)    # newest news first
    done = stored()
    return [r for r in records_from_cards(cards) if r["key"] not in done][:limit]


def recheck(dry_run: bool) -> int:
    """
    The checks again on every stored draft, after a check has changed. A draft is checked from the input and answer
    stored with it; one stored before those were kept, from the manual import it came from (data/manual/done).
    """
    from src.combine import CombineBatch
    from src.manual import clipboard
    from src.manual.__main__ import DIR
    from src.shared.pagination import fetch_all
    from src.shared.supabase_client import get_client
    imported = {}
    for sent_path in sorted((DIR / "done").glob("combine-*.json")):
        answer_path = sent_path.with_name(sent_path.stem + "-answer.txt")
        if answer_path.exists():
            answers = {r.key: r for r in clipboard.parse(answer_path.read_text(encoding="utf-8"), CombineBatch).records}
            for record in json.loads(sent_path.read_text(encoding="utf-8"))["records"]:
                if record["key"] in answers:
                    imported[record["key"]] = (record, answers[record["key"]])
    client = get_client()
    rows = fetch_all(lambda: client.from_(TABLE).select("key,combined,model"), order="key")
    changed = 0
    for row in rows:
        kept = row["combined"]
        if "input" in kept and "answer" in kept:
            record, got = kept["input"], Combined.model_validate(kept["answer"])
        elif row["key"] in imported:
            record, got = imported[row["key"]]
        else:
            print(f"  {row['key']}: no answer kept, left as it is")
            continue
        result = checked(record, got)
        if "answer" in kept and all(kept.get(k) == v for k, v in result.items()):
            continue
        changed += 1
        print(f"  {record['name']}: {len(result['add'])} to add, {len(result['dropped'])} dropped by the checks"
              + ("" if result["ok"] else ", nothing passes: each article's own sentences"))
        if not dry_run:
            save(record, result, row["model"], got, client)
    print(f"{changed} of {len(rows)} drafts " + ("would change (dry run, nothing written)" if dry_run else "updated"))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.combine")
    parser.add_argument("--limit", type=int, default=None, help="at most N records (default: records_per_run)")
    parser.add_argument("--dry-run", action="store_true", help="ask and check, but write nothing")
    parser.add_argument("--recheck", action="store_true", help="the checks again on every stored draft; no model call")
    args = parser.parse_args(argv)
    if args.recheck:
        return recheck(args.dry_run)
    settings = SETTINGS.combine
    from src.shared.supabase_client import get_client
    try:
        get_client().from_(TABLE).select("key").limit(1).execute()
    except Exception:
        print(f"No {TABLE} table: run sql/22_description_drafts.sql in the Supabase SQL editor first.")
        return 0 if args.dry_run else 1
    records = pending(args.limit or settings.records_per_run)
    if not records:
        print("Nothing to combine.")
        return 0
    failed = 0
    for i, record in enumerate(records):
        if i:
            time.sleep(settings.seconds_between_records)
        try:
            got = gemini_client.generate_json(settings.models, prompt_for(record), Combined, thinking_level=settings.thinking)
        except Exception as exc:              # a busy or spent model: left for the next run
            print(f"  {record['name']}: no answer ({str(exc)[:120]}); left for the next run")
            failed += 1
            continue
        result = checked(record, got)
        model = gemini_client.LAST_MODEL or settings.models[0]
        print(f"  {record['name']}: {len(result['add'])} to add, {len(result['disagreements'])} disagreements, "
              f"{len(result['corrections'])} corrections, {len(result['dropped'])} dropped by the checks")
        if args.dry_run:
            print(json.dumps(result, ensure_ascii=False, indent=1))
            continue
        save(record, result, model, got)
    print(f"Combined {len(records) - failed} of {len(records)}" + (" (dry run, nothing written)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
