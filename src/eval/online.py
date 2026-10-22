"""
The three labelled sheets, labelled on the desk's Evaluation page instead of in Excel.

    python -m src.eval online publish      # the sheets' rows to the page (sql/19_evaluation.sql)
    python -m src.eval online pull         # the labels back, as the returned sheets score reads
    python -m src.eval online results      # score them, and show the report on the page

The rows go up from the same .xlsx files the team would otherwise fill in, and
nothing of the app's answers goes with them: those stay in the key files on
this PC, so the page cannot show a labeller what they are grading. The labels
come back as one returned sheet per labeller, in the folder and the format
`python -m src.eval score` has always read, so the scoring is unchanged.

The extraction sheet carries only each article's headline, and a missed name
cannot be spotted from a headline, so the articles' text goes up with them:
fetched once, ten seconds apart, when the sheet is drawn (sheets.readable) and
kept beside the sheets; `publish` fetches only what is still missing, and
`--no-fetch` publishes with what is kept.
"""

import contextlib
import io
import json
import re
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd

CJK = re.compile(r"[一-鿿]")
TASKS = ("relevance", "matching", "extraction")
STEMS = {"relevance": "1-relevance", "matching": "2-matching", "extraction": "3-extraction"}
TEXTS = "3-extraction-texts.json"
SECONDS_BETWEEN_PAGES = 10     # the crawl delay the news sites ask for
# What a row may carry up: the key files' columns never do (tests/test_eval_online.py).
KEY_COLUMNS = {"app_said", "app_said_same", "stratum", "side", "weight", "script", "entity_id", "article_id"}
# The field a value belongs to: "Founder: Chng Siew Hern · Description: …" (sheets._fields_line, extraction rows).
FIELD = re.compile(r"\s·\s(?=[A-Z][^:·]{0,60}: )")


def lang_of(link: str) -> str:
    """The desk's langOf: an article's language by its outlet."""
    return "zh" if "zaobao" in link else "ms" if "beritaharian" in link else "ta" if "tamilmurasu" in link else "en"


def fields(line: str) -> list[list[str]]:
    """'Country: Singapore · Founder: Chng Siew Hern' as [['Country', 'Singapore'], ['Founder', 'Chng Siew Hern']]."""
    out = []
    for part in FIELD.split(str(line or "").strip()):
        key, sep, value = part.partition(": ")
        if part.strip():
            out.append([key.strip(), value.strip()] if sep else ["", part.strip()])
    return out


def _rows(folder: Path, task: str) -> pd.DataFrame:
    return pd.read_excel(folder / f"{STEMS[task]}.xlsx", sheet_name="rows", dtype=str, keep_default_na=False)


def items(folder: str | Path = "data/eval", texts: dict[str, str] | None = None) -> list[dict]:
    """Every row of the three sheets as the page shows it: (task, item, ord, lang, body)."""
    folder, texts = Path(folder), texts or {}
    out = []
    for n, r in enumerate(_rows(folder, "relevance").itertuples(), 1):
        out.append({"task": "relevance", "item": r.url, "ord": n, "lang": lang_of(r.url),
                    "body": {"url": r.url, "source": r.source, "published": r.published,
                             "title": r.title, "description": r.description}})
    for n, r in enumerate(_rows(folder, "matching").itertuples(), 1):
        out.append({"task": "matching", "item": str(r.id), "ord": n, "lang": "zh" if CJK.search(r.evidence) else "en",
                    "body": {"name": r.name, "name_en": r.name_in_english, "evidence": r.evidence,
                             "article": r.article, "url": r.url, "tte_id": r.tte_id, "tte_name": r.tte_name,
                             "tte_fields": fields(r.tte_fields)}})
    # One row per name and a blank row closing each article; the page shows the article once.
    articles: dict[str, dict] = {}
    for r in _rows(folder, "extraction").itertuples():
        a = articles.setdefault(r.article_url, {"url": r.article_url, "lang": r.language or "en",
                                                "title": r.article, "names": []})
        if r.entity.strip() and r.entity not in {x["entity"] for x in a["names"]}:
            a["names"].append({"entity": r.entity, "type": r.type, "fields": fields(r.fields), "evidence": r.evidence})
    for n, a in enumerate(articles.values(), 1):
        out.append({"task": "extraction", "item": a["url"], "ord": n, "lang": a.pop("lang"),
                    "body": {**a, "text": texts.get(a["url"], "")}})
    return out


def fetch_texts(folder: str | Path = "data/eval", fetch=None, pause: float = SECONDS_BETWEEN_PAGES) -> dict[str, str]:
    """The extraction articles' text, fetched once and kept beside the sheets; a page that fails stays blank."""
    if fetch is None:
        from src.job2_extraction.scraper import scrape as fetch
    folder = Path(folder)
    path = folder / TEXTS
    kept = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    urls = [u for u in dict.fromkeys(_rows(folder, "extraction").article_url) if u and not kept.get(u)]
    for n, url in enumerate(urls):
        if n:
            time.sleep(pause)
        try:
            kept[url] = fetch(url)
        except Exception as exc:
            print(f"  could not fetch {url}: {exc}")
        path.write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")
    return kept


def publish(folder: str | Path = "data/eval", fetch: bool = True) -> dict[str, int]:
    """Put the rows where the Evaluation page reads them. Run again, it updates them; labels are kept."""
    from src.eval.guide import stale
    from src.shared.supabase_client import get_client
    for line in stale():
        print("  Note: " + line)
    cached = Path(folder) / TEXTS
    texts = fetch_texts(folder) if fetch else json.loads(cached.read_text(encoding="utf-8")) if cached.exists() else {}
    rows = items(folder, texts)
    client = get_client()
    for start in range(0, len(rows), 200):
        client.from_("eval_items").upsert(rows[start:start + 200], on_conflict="task,item").execute()
    counts = {t: sum(1 for r in rows if r["task"] == t) for t in TASKS}
    blank = sum(1 for r in rows if r["task"] == "extraction" and not r["body"]["text"])
    print(f"Published {counts['relevance']} relevance rows, {counts['matching']} matching rows and "
          f"{counts['extraction']} extraction articles" + (f" ({blank} without their text)" if blank else "") + ".")
    return counts


def returned(folder: str | Path, labels: list[dict], names: dict[str, str]) -> dict[str, dict[str, int]]:
    """One returned sheet per labeller and task, the label column filled in from their labels."""
    folder = Path(folder)
    out_dir = folder / "returned"
    out_dir.mkdir(parents=True, exist_ok=True)
    mine = defaultdict(lambda: defaultdict(dict))         # labeller -> task -> item -> label
    secs = defaultdict(float)
    for r in labels:
        mine[r["labeller"]][r["task"]][r["item"]] = r["label"]
        secs[r["labeller"]] += r.get("seconds") or 0
    used, done = set(), {}
    for who, tasks in mine.items():
        name = re.sub(r"[^\w-]+", "-", names.get(who) or who[:8]).strip("-") or who[:8]
        if name in used:
            name = f"{name}-{who[:4]}"
        used.add(name)
        done[name] = {}
        for task, got in tasks.items():
            df = _rows(folder, task)
            if task == "relevance":
                df["relevant"] = [("TRUE" if got[u]["relevant"] else "FALSE") if u in got else "" for u in df.url]
            elif task == "matching":
                df["same"] = [got[i]["same"] if i in got else "" for i in df.id]
            else:
                verdict, errors, missed = [], [], []
                closing = {u: i for i, u in enumerate(df.article_url)}     # each article's blank last row
                for i, r in enumerate(df.itertuples()):
                    g = got.get(r.article_url) or {}
                    lab = (g.get("names") or {}).get(r.entity) if r.entity.strip() else None
                    verdict.append(lab["verdict"] if lab else "")
                    errors.append(", ".join(lab.get("wrong_fields") or []) if lab else "")
                    missed.append("\n".join(g.get("missed") or []) if g and closing[r.article_url] == i else "")
                df["verdict"], df["field_errors"], df["missed"] = verdict, errors, missed
            with pd.ExcelWriter(out_dir / f"{STEMS[task]}-{name}.xlsx", engine="openpyxl") as writer:
                pd.DataFrame({"how long did this take (minutes)": [round(secs[who] / 60)]}).to_excel(
                    writer, sheet_name="start here", index=False)
                df.to_excel(writer, sheet_name="rows", index=False)
            done[name][task] = len(got)
    return done


def pull(folder: str | Path = "data/eval") -> dict[str, dict[str, int]]:
    """Every label from the page, written out as the returned sheets."""
    from src.export.accounts import is_test
    from src.shared.pagination import fetch_all
    from src.shared.supabase_client import get_client
    client = get_client()
    labels = fetch_all(lambda: client.from_("eval_labels").select("task,item,labeller,label,seconds")
                       .order("task").order("item").order("labeller"), order="")
    users = list(client.auth.admin.list_users())
    testers = {u.id for u in users if is_test(u)}
    names = {u.id: (u.user_metadata or {}).get("name") or (u.email or "").split("@")[0] for u in users}
    done = returned(folder, [r for r in labels if r["labeller"] not in testers], names)
    for name, tasks in done.items():
        print(f"  {name}: " + ", ".join(f"{t} {n}" for t, n in tasks.items()))
    print(f"Wrote the returned sheets to {Path(folder) / 'returned'}/. Score them with: python -m src.eval online results")
    return done


def results(folder: str | Path = "data/eval") -> str:
    """Score the returned sheets against the key, and put the report where the page shows it."""
    from src.eval.score import report
    from src.shared.supabase_client import get_client
    folder = Path(folder)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        report(folder / "returned", folder)
    text = buf.getvalue()
    print(text)
    get_client().from_("eval_results").insert({"report": text}).execute()
    print("The report is on the Evaluation page.")
    return text


def main(argv: list[str]) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="python -m src.eval online")
    parser.add_argument("step", choices=("publish", "pull", "results"))
    parser.add_argument("--folder", default="data/eval", help="where the sheets and their keys are")
    parser.add_argument("--no-fetch", action="store_true", help="publish with the articles' text already kept, fetching none")
    args = parser.parse_args(argv)
    if args.step == "publish":
        publish(args.folder, fetch=not args.no_fetch)
    elif args.step == "pull":
        pull(args.folder)
    else:
        results(args.folder)
    return 0
