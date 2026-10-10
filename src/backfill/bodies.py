"""
Fetch the article text for the rows that passed relevance.

    python -m src.backfill bodies data/backfill/results/positives.csv

Fills the `article_text` column in place, and adds `text_error` for the rows
that could not be read. CNA bodies come from its search index, one query per
URL and no page fetch; Straits Times and Zaobao bodies are one page fetch
each, extracted the way the nightly pipeline extracts them.

Every fetched body is appended to a sidecar (`<csv>.bodies.jsonl`) the moment
it arrives, so a stopped run resumes without refetching, and the CSV itself
is rewritten once at the end rather than once per row.
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import pandas as pd
from tqdm import tqdm

from src.backfill import cna, sitemaps
from src.job2_extraction.scraper import text_from

# Zaobao pieces run ~1,300 characters and Chinese is dense; anything under
# this is a stub, a paywall interstitial or an error page.
MIN_CHARS = 150

# What each outlet tolerated in the collection run: ST began answering 429
# above six in flight, Zaobao and Algolia did not mind sixteen.
WORKERS = {"cna": 8, "st": 4, "zb": 12}


def body_cna(url: str, client: httpx.Client) -> str:
    j = client.post(cna.URL, headers=cna.HEADERS,
                    json={"params": f'query=&hitsPerPage=1&filters=link_absolute:"{url}"'},
                    timeout=30).json()
    hits = j.get("hits") or []
    return cna.body(hits[0]) if hits else ""


class Throttled(RuntimeError):
    pass


def body_page(url: str, client: httpx.Client) -> str:
    """
    The Straits Times throttles with a 302 to its homepage rather than a
    429, which a naive fetch records as a successful page of sidebar text.
    A landing on "/" is treated as "slow down", like a 429.
    """
    import time
    pause = 2.0
    for attempt in range(5):
        r = client.get(url)
        landed_home = r.url.path.rstrip("/") == "" and url.rstrip("/").count("/") > 2
        if (r.status_code in (429, 503) or landed_home) and attempt < 4:
            time.sleep(pause); pause *= 2
            continue
        if landed_home:
            raise Throttled("redirected to the homepage after retries")
        r.raise_for_status()
        return text_from(r.text)
    return ""


# Below this an ST page is the standfirst and a caption, not the article:
# the body is behind the paywall for older pieces. Kept, and marked.
PARTIAL_CHARS = 800


def fetch_all(rows: list[dict], sidecar: Path) -> dict[str, dict]:
    """Bodies by URL, from the sidecar first and the network for the rest."""
    done: dict[str, dict] = {}
    if sidecar.exists():
        with sidecar.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rec = json.loads(line)
                    done[rec["url"]] = rec
    todo = [r for r in rows if r["url"] not in done]
    if not todo:
        return done

    bar = tqdm(total=len(todo), desc="bodies", unit="page", smoothing=0.02)
    out = sidecar.open("a", encoding="utf-8")
    try:
        with httpx.Client(headers=sitemaps.HEADERS, follow_redirects=True, timeout=25) as client:
            def fetch(row):
                url, source = row["url"], row["source"]
                try:
                    text = body_cna(url, client) if source == "cna" else body_page(url, client)
                    if len(text) < MIN_CHARS:
                        return {"url": url, "text": "", "error": f"only {len(text)} chars"}
                    if source == "st" and len(text) < PARTIAL_CHARS:
                        return {"url": url, "text": text, "error": f"partial: paywalled, {len(text)} chars"}
                    return {"url": url, "text": text, "error": ""}
                except Exception as exc:
                    return {"url": url, "text": "", "error": str(exc)[:120]}

            # One pool per outlet, sized to what that outlet tolerates, all
            # running at once.
            pools = {s: ThreadPoolExecutor(max_workers=n) for s, n in WORKERS.items()}
            futures = [pools[r["source"]].submit(fetch, r) for r in todo if r["source"] in pools]
            failed = 0
            for fut in as_completed(futures):
                rec = fut.result()
                done[rec["url"]] = rec
                out.write(json.dumps(rec, ensure_ascii=False) + "\n"); out.flush()
                failed += bool(rec["error"])
                bar.update(1); bar.set_postfix(failed=failed)
            for p in pools.values():
                p.shutdown()
    finally:
        out.close(); bar.close()
    return done


def fill(csv_path: Path | str) -> dict:
    path = Path(csv_path)
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if "article_text" not in frame.columns:
        frame["article_text"] = ""
    rows = frame[["url", "source"]].to_dict("records")
    done = fetch_all(rows, path.with_suffix(".bodies.jsonl"))
    frame["article_text"] = frame["url"].map(lambda u: done.get(u, {}).get("text", ""))
    frame["text_error"] = frame["url"].map(lambda u: done.get(u, {}).get("error", ""))
    backup = path.with_suffix(".before-bodies.csv")
    if not backup.exists():
        path.replace(backup)
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
    got = int((frame["article_text"] != "").sum())
    partial = int(frame["text_error"].str.startswith("partial").sum())
    return {"rows": len(frame), "with_text": got, "partial": partial, "failed": len(frame) - got,
            "by_source": frame.assign(ok=frame["article_text"] != "").groupby("source")["ok"].mean().round(3).to_dict(),
            "backup": str(backup)}
