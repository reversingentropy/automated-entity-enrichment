"""
Each stage's prompt for everything waiting, and its answer written exactly as the nightly job writes one.

An export keeps a note of what it sent (data/manual/<stage>.json): the articles, and for matching the candidates
each entity was shown, which the answer is checked against. An import reads that note, not the queue as it is
by then, and writes only what is still waiting: anything the nightly run did in between is left as it did it.
"""

import time
from urllib.parse import urlparse

from pydantic import BaseModel

from src.manual.clipboard import shape
from src.shared.models import (ExtractedEntity, ExtractionResponse, RelevanceResponse, ResolutionResponse,
                               ResolutionResult)
from src.shared.supabase_client import column_exists, get_client

PAUSE = 10   # seconds between two pages from one site: what the papers' robots.txt asks


class ArticleEntities(BaseModel):
    article_id: int
    entities: list[ExtractedEntity]


class ExtractionBatch(BaseModel):
    articles: list[ArticleEntities]


class ArticleResolutions(BaseModel):
    article_id: int
    resolutions: list[ResolutionResult]


class ResolutionBatch(BaseModel):
    articles: list[ArticleResolutions]


def still(table: str, ids: list, column: str, value) -> set:
    """Which of `ids` are still waiting: `column` still holds `value` (None for NULL)."""
    left = set()
    for start in range(0, len(ids), 200):
        q = get_client().from_(table).select("id").in_("id", ids[start:start + 200])
        q = q.is_(column, None) if value is None else q.eq(column, value)
        left |= {r["id"] for r in q.execute().data or []}
    return left


def by_hand(model: str) -> str:
    return f"{model} (AI Studio, by hand)"


# ---- relevance ----------------------------------------------------------------------------------

def relevance_export(limit: int | None) -> tuple[str, dict, str] | None:
    from src.job1_relevance.fetch import fetch_unscored_articles
    from src.job1_relevance.prompt import render
    articles = fetch_unscored_articles(limit=limit)
    if not articles:
        return None
    note = ""
    if len(articles) > 100:
        note = (f"\n  {len(articles)} articles in one prompt. The nightly job sends 100 at a time because a smaller batch "
                f"finds more (548 at once found 6 relevant, the same 548 in hundreds found 16). Use --limit 100 to match it.")
    return (render(articles) + "\n\n" + shape(RelevanceResponse),
            {"ids": [a["id"] for a in articles]},
            f"{len(articles)} unscored articles" + note)


def relevance_import(text: str, sent: dict, model: str, dry_run: bool, parse) -> str:
    from src.job1_relevance.update import build_payload, write_verdicts
    answer = parse(text, RelevanceResponse)
    ids = sent["ids"]
    relevant = {r.id: r.reason for r in answer.results if r.id in set(ids)}
    invented = [r.id for r in answer.results if r.id not in set(ids)]
    waiting = still("article", ids, "relevant", None)
    payload = build_payload([{"id": i} for i in ids if i in waiting], relevant)
    kept = sum(1 for p in payload if p["relevant"])
    if not dry_run:
        for start in range(0, len(payload), 200):
            write_verdicts(payload[start:start + 200])
        if column_exists("article", "relevance_model"):
            done = [p["id"] for p in payload]
            for start in range(0, len(done), 200):
                get_client().from_("article").update({"relevance_model": by_hand(model)}) \
                    .in_("id", done[start:start + 200]).execute()
    return (f"{len(payload)} verdicts, {kept} relevant"
            + (f"; {len(ids) - len(payload)} left alone, scored by the nightly run since the export" if len(payload) < len(ids) else "")
            + (f"; ignored ids the prompt did not contain: {invented}" if invented else ""))


# ---- extraction ---------------------------------------------------------------------------------

EXTRACTION_BATCH = """

---

This time there is not one article but {n}, below, each headed "=== ARTICLE <number> ===". Do everything above for
each article on its own: an entity belongs to the article it was found in, its evidence is a sentence copied from
that article, and each article's dates are read against its own "Published" line.

Answer with one JSON object that groups the entities by article:
{{"articles": [{{"article_id": <the number after ARTICLE>, "entities": [ ...each exactly as in the output format above... ]}}]}}
Give every article an entry, with "entities": [] when it has none.
"""


def extraction_export(limit: int | None) -> tuple[str, dict, str] | None:
    from src.job2_extraction.fetch import MAX_ATTEMPTS, fetch_unextracted_articles
    from src.job2_extraction.prompt import load_prompt
    from src.job2_extraction.scraper import ScrapeError, scrape
    from src.job2_extraction.update import record_fetch_failure
    articles = fetch_unextracted_articles(limit=limit)
    if not articles:
        print("Nothing waiting for extraction.")
        return None
    blocks, sent, unread, last = [], [], [], {}
    for n, a in enumerate(articles, 1):
        text = a.get("text")
        if not text:
            host = urlparse(a["url"]).netloc
            wait = last.get(host, 0) + PAUSE - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            print(f"  reading {n}/{len(articles)}: {a['url'][:90]}", flush=True)
            try:
                text = scrape(a["url"])
            except ScrapeError as exc:
                # As Job 2 does: counted on the row, and given up after MAX_ATTEMPTS.
                record_fetch_failure(a["id"], a.get("fetch_attempts") or 0, str(exc))
                unread.append(a["id"])
                continue
            finally:
                last[host] = time.monotonic()
        when = f"Published: {str(a['pubDate'])[:10]}\n" if a.get("pubDate") else ""
        blocks.append(f"=== ARTICLE {a['id']} ===\n{when}{a.get('title') or ''}\n\n{text}\n")
        sent.append(a["id"])
    if not sent:
        if unread:
            print(f"Nothing to export: {len(unread)} waiting, none could be read (counted, as Job 2 counts them; "
                  f"given up after {MAX_ATTEMPTS}).")
        return None
    instructions = load_prompt().rstrip()
    if instructions.endswith("Article:"):
        instructions = instructions[:-len("Article:")].rstrip()
    prompt = (instructions + EXTRACTION_BATCH.format(n=len(sent)) + "\n" + "\n".join(blocks)
              + "\n" + shape(ExtractionBatch))
    note = f"{len(sent)} relevant articles, their text read just now"
    if unread:
        note += f"; {len(unread)} could not be read (counted, as Job 2 counts them; given up after {MAX_ATTEMPTS})"
    if len(sent) > 15:
        note += ("\n  That is a long answer to write. If AI Studio stops before the end, the import will say the JSON is "
                 "cut short: export again with --limit 15.")
    return prompt, {"ids": sent}, note


def extraction_import(text: str, sent: dict, model: str, dry_run: bool, parse) -> str:
    from src.job2_extraction.update import build_rows, save
    answer = parse(text, ExtractionBatch)
    ids = sent["ids"]
    answered = {a.article_id: a.entities for a in answer.articles if a.article_id in set(ids)}
    waiting = still("article", ids, "processed_extraction", False)
    labelled = column_exists("extracted_entities", "extraction_model")
    written = entities = 0
    for article_id in ids:
        if article_id not in waiting or article_id not in answered:
            continue
        rows = build_rows(article_id, ExtractionResponse(entities=answered[article_id]))
        if labelled:
            for row in rows:
                row["extraction_model"] = by_hand(model)
        if not dry_run:
            save(article_id, rows)
        written += 1
        entities += len(rows)
    missing = [i for i in ids if i in waiting and i not in answered]
    return (f"{written} articles, {entities} entities"
            + (f"; {len(ids) - len(waiting)} left alone, extracted by the nightly run since the export" if len(waiting) < len(ids) else "")
            + (f"; {len(missing)} not in the answer, left for the next run: {missing}" if missing else ""))


# ---- matching -----------------------------------------------------------------------------------

MATCHING_BATCH = """

==================================================
THIS TIME: SEVERAL ARTICLES
==================================================

The entities above come from {n} articles; each carries its "article_id". Resolve every entity exactly as
described, against its own candidates only, and group the answer by article:
{{"articles": [{{"article_id": <article_id>, "resolutions": [ ...each exactly as in OUTPUT FORMAT above... ]}}]}}
Give every article an entry, with "resolutions": [] when every entity in it is simply new.
"""


def matching_export(limit: int | None) -> tuple[str, dict, str] | None:
    import json
    from src.job3_resolution.candidates import candidates_for
    from src.job3_resolution.fetch import fetch_unresolved
    from src.job3_resolution.prompt import build_entity_block, load_prompt
    articles = fetch_unresolved(limit_articles=limit)
    if not articles:
        return None
    blocks, candidates = [], {}
    for a in articles:
        for e in a["entities"]:
            candidates[e["id"]] = candidates_for(e, a.get("year"))
            blocks.append({"article_id": a["article_id"], **build_entity_block(e, candidates[e["id"]], a["title"])})
    prompt = (load_prompt().replace("{article_entities}", json.dumps(blocks, ensure_ascii=False, indent=2))
              + MATCHING_BATCH.format(n=len(articles)) + "\n" + shape(ResolutionBatch))
    entities = sum(len(a["entities"]) for a in articles)
    return (prompt, {"articles": articles, "candidates": {str(k): v for k, v in candidates.items()}},
            f"{entities} entities from {len(articles)} articles, each with the records it could be")


def matching_import(text: str, sent: dict, model: str, dry_run: bool, parse) -> str:
    from src.job3_resolution.update import build_rows, save
    answer = parse(text, ResolutionBatch)
    candidates = {int(k): v for k, v in sent["candidates"].items()}
    answered = {a.article_id: a.resolutions for a in answer.articles}
    ids = [e["id"] for a in sent["articles"] for e in a["entities"]]
    waiting = still("extracted_entities", ids, "resolved", False)
    labelled = column_exists("candidate_matches", "resolution_model")
    written = matched = 0
    skipped, missing = [], []
    for a in sent["articles"]:
        mine = [e["id"] for e in a["entities"]]
        if not all(i in waiting for i in mine):
            skipped.append(a["article_id"])      # resolved since the export, wholly or in part: left as it is
            continue
        if a["article_id"] not in answered:
            missing.append(a["article_id"])
            continue
        rows = build_rows(ResolutionResponse(resolutions=answered[a["article_id"]]), a["entities"], candidates)
        if labelled:
            for row in rows:
                row["resolution_model"] = by_hand(model)
        if not dry_run:
            save(mine, rows)
        written += 1
        matched += sum(1 for r in rows if r["resolution_action"] == "MATCH_AND_UPDATE")
    return (f"{written} articles, {matched} matches to existing records"
            + (f"; {len(skipped)} left alone, resolved by the nightly run since the export" if skipped else "")
            + (f"; {len(missing)} not in the answer, left for the next run: {missing}" if missing else ""))


STAGES = {
    "relevance": (relevance_export, relevance_import, "relevance"),
    "extraction": (extraction_export, extraction_import, "extraction"),
    "matching": (matching_export, matching_import, "resolution"),
}
