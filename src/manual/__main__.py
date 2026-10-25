"""
The three Gemini stages done by hand in Google AI Studio, for days the API is busy or out of requests.

    python -m src.manual relevance export     # every unscored article in one prompt, onto the clipboard
    python -m src.manual relevance import     # AI Studio's answer, off the clipboard, into the database

    python -m src.manual extraction export    # every relevant article not yet extracted, its text read now
    python -m src.manual extraction import

    python -m src.manual matching export      # every entity not yet matched, with the records it could be
    python -m src.manual matching import

In between: open a new chat at aistudio.google.com, choose the model and thinking level the export names, paste,
wait for the whole answer, and copy it with the copy button under it. Run the stages in order, each once the one
before is imported, as the nightly run does; the desk shows the result after the next publish
(python -m src.export --publish, or the nightly run).

Options:
  export --limit N     only the first N (articles; for matching, articles' entities)
  import --file PATH   read the answer from a file instead of the clipboard
  import --model NAME  the model actually used in AI Studio, if not the one the export named (it is recorded)
  import --dry-run     check the answer and say what would be written, writing nothing

Each export replaces the last one not yet imported. The prompt is also saved to data/manual/<stage>-prompt.txt,
for when the clipboard cannot be reached. An import that succeeds files the prompt, the answer and what was sent
under data/manual/done/, so it can be traced later which articles were answered by hand, and with what.
"""

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from src.manual import clipboard
from src.manual.stages import STAGES
from src.shared.config import SETTINGS

DIR = Path(__file__).resolve().parents[2] / "data" / "manual"


def paths(stage: str) -> tuple[Path, Path]:
    return DIR / f"{stage}-prompt.txt", DIR / f"{stage}.json"


def tokens(text: str) -> int:
    """Roughly what Gemini counts: about four characters a token in English, one in Chinese or Tamil."""
    wide = sum(1 for ch in text if ord(ch) > 0x2000)
    return (len(text) - wide) // 4 + wide


def export(stage: str, limit: int | None) -> int:
    make, _, settings = STAGES[stage]
    prompt_path, sent_path = paths(stage)
    if sent_path.exists():
        made = json.loads(sent_path.read_text(encoding="utf-8"))["made"]
        print(f"(Replacing the {stage} export from {made}, which was never imported.)")
    made = make(limit)
    if made is None:
        if stage != "extraction":   # extraction says itself when articles were waiting but none could be read
            print(f"Nothing waiting for {stage}.")
        return 0
    prompt, sent, what = made
    model = getattr(SETTINGS, settings).models[0]
    thinking = getattr(SETTINGS, settings).thinking
    DIR.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    sent_path.write_text(json.dumps({"made": datetime.now().isoformat(timespec="seconds"), "model": model, **sent},
                                    ensure_ascii=False), encoding="utf-8")
    copied = clipboard.copy(prompt_path)
    print(f"\n{what}: one prompt, about {tokens(prompt) // 1000 or 1}k tokens.")
    print(("It is on the clipboard." if copied else f"Copy all of {prompt_path}.") +
          f"\n  1. New chat at aistudio.google.com, model {model}, thinking {thinking}.\n"
          f"  2. Paste, and wait for the whole answer.\n"
          f"  3. Copy it (the copy button under the answer), then run:  python -m src.manual {stage} import")
    return 0


def do_import(stage: str, file: str | None, model: str | None, dry_run: bool) -> int:
    _, take, _ = STAGES[stage]
    prompt_path, sent_path = paths(stage)
    if not sent_path.exists():
        print(f"No {stage} export waiting to be imported: run  python -m src.manual {stage} export  first.")
        return 1
    sent = json.loads(sent_path.read_text(encoding="utf-8"))
    text = Path(file).read_text(encoding="utf-8") if file else clipboard.paste()
    if not text:
        print("Nothing on the clipboard." if not file else f"{file} is empty.")
        return 1
    if prompt_path.exists() and text.strip() == prompt_path.read_text(encoding="utf-8").strip():
        print("The clipboard still holds the prompt: copy AI Studio's answer first.")
        return 1
    try:
        summary = take(text, sent, model or sent["model"], dry_run, clipboard.parse)
    except (ValueError, ValidationError) as exc:
        cut = clipboard.CUT in str(exc)
        print(f"That answer does not fit, so nothing was written:\n  {str(exc)[:800]}")
        print("  It looks cut short: export again with a smaller --limit." if cut else
              "  Ask AI Studio to fix it (\"Return only the JSON, matching the schema\"), copy it again, and import again.")
        return 1
    if dry_run:
        print(f"Dry run, nothing written. It would write: {summary}.")
        return 0
    done = DIR / "done"
    done.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (done / f"{stage}-{stamp}-answer.txt").write_text(text, encoding="utf-8")
    shutil.move(str(prompt_path), done / f"{stage}-{stamp}-prompt.txt")
    shutil.move(str(sent_path), done / f"{stage}-{stamp}.json")
    print(f"Written: {summary}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.manual", description="See the top of src/manual/__main__.py.")
    parser.add_argument("stage", choices=list(STAGES))
    parser.add_argument("step", choices=["export", "import"])
    parser.add_argument("--limit", type=int, default=None, help="export: only the first N")
    parser.add_argument("--file", help="import: read the answer from this file instead of the clipboard")
    parser.add_argument("--model", help="import: the model actually used in AI Studio, if not the one the export named")
    parser.add_argument("--dry-run", action="store_true", help="import: check and report, write nothing")
    args = parser.parse_args(argv)
    if args.step == "export":
        return export(args.stage, args.limit)
    return do_import(args.stage, args.file, args.model, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
