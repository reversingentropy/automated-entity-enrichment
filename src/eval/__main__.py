"""
Run the resolution prompt against frozen cases and report what it decided.

The unit suite covers code, not model behaviour. The two worst bugs found so
far were behavioural -- field_updates absent from every match, and a name
collision matched rather than flagged -- and neither could fail a unit test.
This is the check that would have caught both.

Cases live in src/eval/cases.json with their candidates frozen, so a run needs no
database and is reproducible. Each case states what it expects; where the right
answer is a judgement call the case says so and the run reports rather than
grades it.

  python -m src.eval                 # every case
  python -m src.eval --case edge-    # only ids containing "edge-"
  python -m src.eval --show          # print the model's reasoning too

The labelled sheets the team fills in are built here too, and need no model:

  python -m src.eval sheets                      # all five, from August 2026
  python -m src.eval sheets --window 2026-07     # another month
  python -m src.eval score data/eval/returned    # the marked sheets, scored
"""

import argparse
import json
import sys
from pathlib import Path

from src.job3_resolution.prompt import resolve

CASES = Path(__file__).resolve().parent / "cases.json"


def check(case: dict, result) -> tuple[bool, str]:
    """Compare one case's expectation against what the model returned."""
    want = case["expect"]
    action = result.resolution_action if result else "OMITTED"

    if "action" in want and action != want["action"]:
        return False, f"expected {want['action']}, got {action}"
    if "action_in" in want and action not in want["action_in"]:
        return False, f"expected one of {want['action_in']}, got {action}"
    if want.get("matched_id") and (not result or result.matched_id != want["matched_id"]):
        got = result.matched_id if result else None
        return False, f"expected match to {want['matched_id']}, got {got}"

    updates = result.field_updates if result else []

    if "field_updates_include" in want:
        need = want["field_updates_include"]
        if not any(u.field == need["field"] and u.strategy == need["strategy"] for u in updates):
            got = ", ".join(f"{u.strategy} {u.field}" for u in updates) or "none"
            return False, f"expected {need['strategy']} on {need['field']}; got {got}"

    if "no_replace_of" in want:
        field = want["no_replace_of"]
        if any(u.field == field and u.strategy == "REPLACE" for u in updates):
            return False, f"REPLACE on {field} would discard authority data"

    if "no_title_containing" in want:
        bad = want["no_title_containing"].lower()
        if any(u.field == "Title" and bad in u.value.lower() for u in updates):
            return False, f"Title update contains '{want['no_title_containing']}'"

    if "no_duplicate_award" in want:
        dup = want["no_duplicate_award"].lower()
        if any(u.field == "Awards" and dup in u.value.lower() for u in updates):
            return False, f"re-appends an award the record already holds: {want['no_duplicate_award']}"

    return True, ", ".join(f"{u.strategy} {u.field}" for u in updates) or "no updates"


def sheets(argv: list[str]) -> int:
    """Build the labelled sheets. No model call; the database and the archive suffice."""
    parser = argparse.ArgumentParser(prog="python -m src.eval sheets")
    parser.add_argument("--window", default="2026-08", help="the month to draw from (YYYY-MM)")
    parser.add_argument("--out", default="data/eval", help="where to write the sheets")
    parser.add_argument("--only", default=None,
                        help="one of relevance, matching, extraction, logs, sus")
    args = parser.parse_args(argv)

    from src.eval import sheets as build
    out = Path(args.out)
    steps = [("relevance", lambda: build.relevance(args.window, out)),
             ("matching", lambda: build.matching(out)),
             ("extraction", lambda: build.extraction(args.window, out)),
             ("logs", lambda: build.logs(out)),
             ("sus", lambda: build.sus(out))]
    print(f"Sheets from {args.window} into {out}/")
    for name, run in steps:
        if args.only and args.only != name:
            continue
        run()
    print("The key files stay with you; send the .xlsx files only.")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "sheets":
        return sheets(argv[1:])
    if argv and argv[0] == "score":
        from src.eval.score import report
        rest = argv[1:]
        folder = rest[0] if rest and not rest[0].startswith("-") else "data/eval/returned"
        key = rest[1] if len(rest) > 1 else None
        return report(folder, key)

    parser = argparse.ArgumentParser(prog="python -m src.eval")
    parser.add_argument("--case", default=None, help="only ids containing this string")
    parser.add_argument("--show", action="store_true", help="print the model's reasoning")
    args = parser.parse_args(argv)

    cases = json.loads(CASES.read_text(encoding="utf-8"))
    if args.case:
        cases = [c for c in cases if args.case in c["id"]]
    if not cases:
        print("No cases matched.")
        return 0

    passed = failed = judgement = 0

    for case in cases:
        block = {"article_title": case["article_title"], **case["entity"],
                 "candidates": case["candidates"]}
        try:
            response = resolve([block])
        except Exception as exc:
            print(f"  ERROR  {case['id']}: {exc}")
            failed += 1
            continue

        result = response.resolutions[0] if response.resolutions else None
        ok, detail = check(case, result)
        is_judgement = case.get("confidence", "").startswith("judgement")

        if is_judgement:
            mark, judgement = "NOTE ", judgement + 1
        elif ok:
            mark, passed = "pass ", passed + 1
        else:
            mark, failed = "FAIL ", failed + 1

        action = result.resolution_action if result else "OMITTED"
        print(f"  {mark} {case['id']:34} {action:17} {detail}")
        if not ok and not is_judgement:
            print(f"         note: {case['note']}")
        if args.show and result:
            print(f"         model: {result.reasoning[:110]}")

    print(f"\n{passed} passed, {failed} failed, {judgement} judgement call(s) reported not graded")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
