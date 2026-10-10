"""
Every count the documents, slides and paper quote, from one run, dated.

    python -m src.export --numbers        # writes docs/numbers.md

Two funnels side by side: the archive collected from the outlets (2015 on,
run through the internal model, its answers kept in files) and the live
nightly pipeline. Read-only: the database and the archive files are only read.
"""

import collections
import contextlib
import datetime as dt
import glob
import io
from pathlib import Path

import pandas as pd

OUT = Path("docs/numbers.md")
OUTCOMES = [  # (resolution outcome, how the documents name it)
    ("changed", "matched to a TTE record, proposes a change"),
    ("nothing", "matched to a TTE record, nothing to add"),
    ("CREATE_NEW", "new, not in TTE"),
    ("FLAG_AMBIGUOUS", "unsure which record"),
    ("RE_QUERY_REQUIRED", "thinks it is in TTE under another name"),
    ("FLAG_DB_DUPLICATE", "points at duplicate TTE records"),
    ("unreadable", "model's answer unreadable"),
]


def _outcome(row: dict) -> str:
    if row["resolution_action"] == "MATCH_AND_UPDATE":
        return "changed" if row.get("field_updates") else "nothing"
    return row["resolution_action"]


def live() -> dict:
    from src.shared.pagination import fetch_all
    from src.shared.supabase_client import get_client

    sb = get_client()
    n = lambda q: q.limit(1).execute().count
    art = lambda: sb.table("article").select("id", count="exact").eq("backfill", False)
    first = sb.table("article").select("created_at").eq("backfill", False).order("created_at").limit(1).execute().data
    ents = fetch_all(lambda: sb.table("extracted_entities").select("id, article_id").eq("backfill", False), order="id")
    rows = fetch_all(lambda: sb.table("candidate_matches")
                     .select("resolution_action, field_updates, extracted_entities!inner(backfill)")
                     .eq("extracted_entities.backfill", False), order="id")
    deck = fetch_all(lambda: sb.table("deck").select("key, card"), order="key")
    return {
        "since": first[0]["created_at"][:10] if first else "",
        "collected": n(art()),
        "relevant": n(art().eq("relevant", True)),
        "extracted": n(art().eq("relevant", True).eq("processed_extraction", True)),
        "entities": len(ents),
        "entity_articles": len({e["article_id"] for e in ents}),
        "outcomes": collections.Counter(_outcome(r) for r in rows),
        "cards": len(deck),
        "new_cards": sum(1 for d in deck if d["card"].get("isNew")),
        "decisions": n(sb.table("reviews").select("id", count="exact")),
        "tte": n(sb.table("entities").select("uid", count="exact").eq("is_active", True)),
        "tte_dump": max((r["filename"] for r in sb.table("tte_imports").select("filename")
                         .ilike("filename", "%.zip").execute().data), default=""),
    }


def archive() -> dict:
    from src.backfill.local_match import Index, load_entities
    from src.backfill.proposals import ROUNDS
    from src.backfill.resolve import ENTITY_COLUMNS, load_candidates, parse
    from src.job3_resolution.update import build_rows
    from src.shared.pagination import fetch_all
    from src.shared.supabase_client import get_client

    by_source = collections.Counter()
    for f in sorted(glob.glob("data/backfill/archive/*.csv")):
        by_source[Path(f).name.split("-")[0]] += len(pd.read_csv(f, dtype=str, keep_default_na=False, usecols=[0]))
    rel = pd.read_csv("data/backfill/answers/relevance.csv", dtype=str, keep_default_na=False,
                      usecols=["relevant", "published"])
    relevant = int(rel["relevant"].str.strip().str.upper().isin(["TRUE", "YES", "1", "Y"]).sum())

    answers: dict[int, str] = {}
    for f in ROUNDS:
        if Path(f).exists():
            for row in pd.read_csv(f, dtype=str, keep_default_na=False, encoding="utf-8-sig").to_dict("records"):
                answers.setdefault(int(row["article_id"]), row.get("resolutions", ""))
    client = get_client()
    extracted = client.table("article").select("id", count="exact").eq("backfill", True).limit(1).execute().count
    ents = fetch_all(lambda: client.from_("extracted_entities").select(ENTITY_COLUMNS).eq("backfill", True), order="id")
    by_article = collections.defaultdict(list)
    for e in ents:
        by_article[e["article_id"]].append(e)
    index = Index(load_entities())
    search = lambda name, t: index.match(name, 3, t)
    offered = load_candidates("data/backfill/answers/resolution-candidates.jsonl")
    outcomes = collections.Counter()
    for aid, es in by_article.items():
        resp, _ = parse(answers.get(aid, ""))
        if resp is None:
            outcomes["unreadable" if aid in answers else "unanswered"] += len(es)
            continue
        with contextlib.redirect_stdout(io.StringIO()):
            rows = build_rows(resp, es, {e["id"]: offered.get(e["id"], []) for e in es}, search=search)
        outcomes.update(_outcome(r) for r in rows)
    return {
        "from": rel["published"].min()[:7], "to": rel["published"].max()[:7],
        "collected": sum(by_source.values()), "by_source": by_source,
        "relevant": relevant, "extracted": extracted,
        "entities": len(ents), "entity_articles": len(by_article), "outcomes": outcomes,
    }


def render(a: dict, v: dict, when: dt.date) -> str:
    f = lambda x: f"{x:,}"
    total = lambda k: a[k] + v[k]
    names = {"cna": "CNA", "st": "The Straits Times", "zb": "Lianhe Zaobao"}
    lines = [
        f"# The numbers, as of {when:%-d %B %Y}",
        "",
        "Generated by `python -m src.export --numbers`; quote from here, with the date, and re-run",
        "before anything is finalised. The archive is the outlets' own archives from "
        f"{a['from']} to {a['to']}, run through the internal model; the live pipeline has run nightly since "
        f"{v['since']}.",
        "",
        "| Stage | Archive | Live | Total |",
        "|---|---:|---:|---:|",
        f"| Articles collected | {f(a['collected'])} | {f(v['collected'])} | **{f(total('collected'))}** |",
        f"| Judged relevant | {f(a['relevant'])} | {f(v['relevant'])} | **{f(total('relevant'))}** "
        f"({total('relevant') / total('collected'):.1%}) |",
        f"| Through extraction (articles) | {f(a['extracted'])} | {f(v['extracted'])} | **{f(total('extracted'))}** |",
        f"| Entities extracted | {f(a['entities'])} | {f(v['entities'])} | **{f(total('entities'))}** |",
    ]
    for key, label in OUTCOMES:
        ak, vk = a["outcomes"].get(key, 0), v["outcomes"].get(key, 0)
        lines.append(f"| → {label} | {f(ak)} | {f(vk)} | **{f(ak + vk)}** |")
    if a["outcomes"].get("unanswered"):
        lines.append(f"| → not yet answered | {f(a['outcomes']['unanswered'])} | 0 | "
                     f"**{f(a['outcomes']['unanswered'])}** |")
    lines += [
        f"| Ready for review | spreadsheet (`python -m src.backfill proposals`) | {f(v['cards'])} cards "
        f"({f(v['new_cards'])} new entities) | |",
        f"| Decided by a reviewer | 0 | {f(v['decisions'])} | **{f(v['decisions'])}** |",
        "",
        "Collected by outlet: " + ", ".join(f"{names.get(s, s)} {f(k)}" for s, k in a["by_source"].most_common()) + ".",
        "",
        f"The TTE copy holds {f(v['tte'])} records in the nine vocabularies the pipeline uses "
        f"(loaded from {v['tte_dump'] or 'the latest dump'}); TTE as a whole holds about 1.8 million.",
        "",
        f"Only {f(a['extracted'])} of the archive's {f(a['relevant'])} relevant articles have been through extraction.",
        "",
    ]
    return "\n".join(lines)


def build(out: Path = OUT) -> Path:
    when = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
    out.write_text(render(archive(), live(), when), encoding="utf-8")
    return out
