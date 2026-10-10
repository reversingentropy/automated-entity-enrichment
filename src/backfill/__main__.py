"""
Collect the outlets' archives into CSV files of 50,000 rows.

FROZEN. This package did one job, the historical archive of September 2026:
295,279 articles collected, relevance and extraction on an institutional
model, 4,128 resolutions imported. It is kept as the record of how, and is
not developed further; the nightly pipeline is src/job1_relevance onward.

  python -m src.backfill count [--from 2015-01] [--to 2026-09]
      How many Singapore articles each archive holds, by year. Reads only the
      indexes; writes nothing.

  python -m src.backfill collect cna --from 2015-01 [--to 2026-09] [--out data/backfill/collected]
      Titles and descriptions come with the index: about 140 requests for
      eleven years, a minute or two.

  python -m src.backfill collect st --from 2015-01 [--to 2026-09] [--slugs]
      URLs from the monthly sitemaps, then one page fetch per URL for the
      headline and description, sixteen in flight. --slugs skips the fetch
      and takes the headline from the URL: minutes, but no description.

  python -m src.backfill repair zb|st
      Re-fetch, gently, the rows a run could not read, and rewrite the files.

  python -m src.backfill collect zb --from 2016-01 [--to 2026-09] [--workers 16]
      URLs from the monthly sitemaps, then one page fetch per URL for its
      title and description, `workers` pages in flight. Zaobao's slugs carry
      no words, so there is no shortcut; at 16 in flight the whole archive is
      under an hour. A 429 or 503 is honoured with a growing pause. Stop it
      whenever; it resumes, skipping every URL already in a CSV in the
      output directory.

  python -m src.backfill bodies data/backfill/sent/positives.csv
      Article text for the rows that passed relevance, into article_text in
      place. CNA from its index, the rest one page fetch each. Resumable.

  python -m src.backfill ingest data/backfill/answers/extraction-1.csv [--limit N] [--dry-run]
      The internal model's extraction output into the pipeline's tables,
      validated against the same schema, behind the backfill flag (sql/09).

  python -m src.backfill resolve-export [--limit N]
  python -m src.backfill resolve-import data/backfill/answers/resolution-2.csv [--dry-run]
      Resolution on the internal model: export each backfill article's
      entities with their ranked candidates, import the answers through
      Job 3's own validation and storage.

  python -m src.backfill dashboard articles|entities|resolutions CSV [CSV ...] [--out DIR]
      The same rows, as files for the dashboard's CSV importer instead of
      the API: articles first (they get their ids), then entities, then
      resolutions with a resolved.sql to run after. Under 6 MB a file.

  python -m src.backfill prompts [--out data/backfill/prompts]
      The two prompts for an internal model: relevance with a verdict per
      row, and extraction with the field rules and vocabularies in the text.

  python -m src.backfill collect all [--out data/backfill/collected]
      All three at once, each with its own progress bar, from each archive's
      first month. Under twenty minutes for everything.

Columns: url, source, title, description, category, published, month.

Under data/backfill/: collected/ is what the collector writes and split/
re-splits into archive/, the 295,279 rows as the internal system took them;
prompts/ the system prompts as sent; sent/ what an export produced, which
can go once its answers are back, since the answers echo their inputs;
answers/ what the internal model returned, with the candidates sidecar the
resolution import checks against; import/ files for the console importer,
which can go once imported; labels/ the human labels, which never go.
"""

import argparse
import csv
import sys
from pathlib import Path

import httpx
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from src.backfill import cna, prompts, sitemaps
from src.backfill.csvout import Writer
from src.backfill.months import label, span


def cmd_count(args) -> int:
    months = span(args.since, args.to)
    per_year: dict[str, Counter] = {"cna": Counter(), "st": Counter(), "zb": Counter()}
    for y, m in tqdm(months, desc="months", unit="month"):
        per_year["cna"][y] += cna.count(y, m)
        for src in ("st", "zb"):
            try:
                per_year[src][y] += len(sitemaps.collect(src, y, m))
            except Exception:
                pass
    years = sorted({y for c in per_year.values() for y in c})
    print(f"\n{'year':6} {'CNA':>8} {'ST':>8} {'Zaobao':>8}")
    for y in years:
        print(f"{y:<6} {per_year['cna'][y]:>8,} {per_year['st'][y]:>8,} {per_year['zb'][y]:>8,}")
    tot = {k: sum(v.values()) for k, v in per_year.items()}
    print(f"{'total':<6} {tot['cna']:>8,} {tot['st']:>8,} {tot['zb']:>8,}   = {sum(tot.values()):,}")
    return 0


def collect_cna(args, out: Writer) -> int:
    months = span(args.since, args.to)
    wrote = 0
    bar = tqdm(months, desc="cna months", unit="month", position=getattr(args, "position", 0), leave=True)
    for y, m in bar:
        rows = cna.collect(y, m)
        n = sum(out.write(r) for r in rows)
        wrote += n
        bar.set_postfix(month=label(y, m), rows=len(rows), written=wrote)
    return wrote


def collect_sitemap(args, out: Writer) -> int:
    source = args.source
    months = span(args.since, args.to)

    # Sitemaps first, quickly, so the bar over the slow part knows its total.
    todo = []
    pos = getattr(args, "position", 0)
    for y, m in tqdm(months, desc=f"{source} sitemaps", unit="month", position=pos, leave=False):
        try:
            todo += [r for r in sitemaps.collect(source, y, m) if r["url"] not in out.seen]
        except Exception as exc:
            tqdm.write(f"  {label(y, m)}: sitemap failed, {str(exc)[:80]}")
    if not todo:
        print("Nothing new.")
        return 0

    # The Straits Times writes the headline into the URL, so --slugs can skip
    # the fetch; but a slug has no description, so fetching is the default.
    if source == "st" and args.slugs:
        wrote = 0
        for row in tqdm(todo, desc="st slugs", unit="row", position=pos, leave=True):
            row["title"] = sitemaps.slug_title(row["url"])
            wrote += out.write(row)
        return wrote

    # Otherwise one page per URL, `workers` in flight on one shared client.
    wrote = failed = 0
    bar = tqdm(total=len(todo), desc=f"{source} pages", unit="page", smoothing=0.02, position=pos, leave=True)
    with httpx.Client(headers=sitemaps.HEADERS, follow_redirects=True, timeout=25) as client:
        def fetch(row):
            try:
                meta = sitemaps.fetch_meta(row["url"], client)
                row["title"] = meta.get("title") or row["title"]
                row["description"] = meta.get("description")
                row["published"] = meta.get("published") or row["published"]
                row["category"] = meta.get("category") or row["category"]
            except Exception as exc:
                row["title"] = row["title"] or sitemaps.slug_title(row["url"])
                row["description"] = f"[fetch failed: {str(exc)[:80]}]"
            return row

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for fut in as_completed(pool.submit(fetch, r) for r in todo):
                row = fut.result()
                if str(row.get("description") or "").startswith("[fetch failed"):
                    failed += 1
                wrote += out.write(row)
                bar.update(1)
                bar.set_postfix(written=wrote, failed=failed)
    bar.close()
    if failed:
        print(f"{failed} page(s) could not be read; their rows carry the slug as title "
              f"and the error as description.")
    return wrote


# Each source starts from its own year; earlier months return empty.
FIRST_MONTH = {"cna": "2015-01", "st": "2015-01", "zb": "2016-01"}


def collect_one(args, source: str, position: int = 0) -> tuple[int, int, list[str]]:
    """One source into its own files. Returns (new rows, total rows, files)."""
    a = argparse.Namespace(**vars(args))
    a.source = source
    a.since = max(args.since, FIRST_MONTH[source]) if args.since else FIRST_MONTH[source]
    a.position = position
    if getattr(args, "redo", False):
        for path in Path(args.out).glob(f"{source}-*.csv"):
            path.unlink()
    out = Writer(args.out, source)
    if out.written:
        tqdm.write(f"Resuming {source}: {out.written:,} rows already in {args.out}/")
    try:
        wrote = collect_cna(a, out) if source == "cna" else collect_sitemap(a, out)
    finally:
        out.close()
    files = sorted(p.name for p in out.dir.glob(f"{source}-*.csv"))
    return wrote, out.written, files


def cmd_collect(args) -> int:
    sources = ("cna", "st", "zb") if args.source == "all" else (args.source,)
    results = {}
    if len(sources) == 1:
        results[sources[0]] = collect_one(args, sources[0])
    else:
        # The three archives are independent and the slow one is bound by the
        # network, so they run at once, each with its own progress bar.
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(collect_one, args, src, i): src for i, src in enumerate(sources)}
            for fut in as_completed(futures):
                results[futures[fut]] = fut.result()
    print()
    grand = 0
    for src in sources:
        wrote, total, files = results[src]
        grand += total
        print(f"  {src:4} {wrote:>8,} new  {total:>8,} total  in {', '.join(files) or '-'}")
    print(f"  {'all':4} {'':>8}      {grand:>8,} rows in {args.out}/")
    return 0


def cmd_repair(args) -> int:
    """
    Re-fetch the rows a run could not read, in place.

    A sustained run at sixteen in flight tripped Zaobao's limiter on about a
    quarter of one percent of pages, past three retries. Those rows carry the
    error as their description; this fetches them again, gently, and rewrites
    the files. Genuine 404s stay failed and are reported.
    """
    files = sorted(Path(args.out).glob(f"{args.source}-*.csv"))
    tables = {f: list(csv.DictReader(f.open(encoding="utf-8-sig", newline=""))) for f in files}
    todo = [(f, i) for f, rows in tables.items() for i, r in enumerate(rows)
            if (r.get("description") or "").startswith("[fetch failed")]
    if not todo:
        print("Nothing to repair.")
        return 0
    fixed = still = 0
    bar = tqdm(total=len(todo), desc=f"{args.source} repair", unit="page")
    with httpx.Client(headers=sitemaps.HEADERS, follow_redirects=True, timeout=25) as client:
        def fetch(item):
            f, i = item
            row = tables[f][i]
            try:
                meta = sitemaps.fetch_meta(row["url"], client, retries=5)
                row["title"] = meta.get("title") or row["title"]
                row["description"] = meta.get("description") or ""
                row["published"] = meta.get("published") or row["published"]
                row["category"] = meta.get("category") or row["category"]
                return True
            except Exception as exc:
                row["description"] = f"[fetch failed: {str(exc)[:80]}]"
                return False
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for ok in pool.map(fetch, todo):
                fixed += ok; still += (not ok)
                bar.update(1); bar.set_postfix(fixed=fixed, still_failed=still)
    bar.close()
    for f, rows in tables.items():
        with f.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=rows[0].keys() if rows else [])
            w.writeheader(); w.writerows(rows)
    print(f"Repaired {fixed}; {still} still cannot be read (removed articles, most likely).")
    return 0


def cmd_bodies(args) -> int:
    from src.backfill.bodies import fill
    result = fill(args.csv)
    print(f"\n{result['with_text']:,} of {result['rows']:,} rows have text, of which "
          f"{result['partial']:,} are paywalled ST pages with only the opening; "
          f"{result['failed']:,} could not be read (see text_error).")
    print("  by source:", {k: f"{v:.0%}" for k, v in result["by_source"].items()})
    print(f"  original kept at {result['backup']}")
    return 0


def cmd_ingest(args) -> int:
    from src.backfill.ingest import ingest
    c = ingest(args.csv, limit=args.limit, dry_run=args.dry_run)
    verb = "Would write" if args.dry_run else "Wrote"
    print(f"\n{verb} {c['entities']:,} entities from {c['articles']:,} articles "
          f"({c['by_source']}); {c['dropped_fields']:,} field(s) TTE does not have were dropped.")
    if c["skipped"]:
        print("  skipped, by reason:")
        for why, n in sorted(c["skipped"].items(), key=lambda kv: -kv[1]):
            print(f"    {n:6,}  {why}")
    if c.get("failed"):
        print("  failed to write after retries (re-run to retry; the write is idempotent):")
        for why, n in sorted(c["failed"].items(), key=lambda kv: -kv[1]):
            print(f"    {n:6,}  {why}")
    return 0


def cmd_resolve_export(args) -> int:
    from src.backfill.resolve import export
    c = export(args.out, limit_articles=args.limit, sidecar=args.candidates)
    print(f"\nExported {c['entities']:,} entities from {c['articles']:,} articles into "
          f"{c['files']} file(s) under {args.out}/ (resolve-NNN.csv, one article per row, "
          f"the model's input in the `input` cell). Candidates kept in {args.candidates} "
          f"for the import.")
    return 0


def cmd_proposals(args) -> int:
    from src.backfill.proposals import build
    path, n_existing, n_new, skipped = build(Path(args.out))
    print(f"Wrote {path}: {n_existing:,} changes to existing records, {n_new:,} rows for new entities (unreviewed)")
    for why, n in skipped.most_common():
        print(f"  no row: {why:40} {n:,}")
    return 0


def cmd_resolve_import(args) -> int:
    from src.backfill.resolve import import_answers
    c = import_answers(args.csv, sidecar=args.candidates, dry_run=args.dry_run)
    verb = "Would write" if args.dry_run else "Wrote"
    print(f"\n{verb} {c['proposals']:,} proposals for {c['articles']:,} articles.")
    for why, n in sorted(c["skipped"].items(), key=lambda kv: -kv[1]):
        print(f"    {n:6,}  {why}")
    return 0


def cmd_dashboard(args) -> int:
    from src.backfill import dashboard
    if args.table == "articles":
        c = dashboard.articles(args.csv, args.out)
        print(f"\n{c['new']:,} articles to import ({c['already_present']:,} of the {c['valid']:,} "
              f"valid are already in the table).")
    elif args.table == "entities":
        c = dashboard.entities(args.csv, args.out)
        print(f"\n{c['entities']:,} entities to import from {c['valid']:,} articles; "
              f"{c['dropped_fields']:,} field(s) TTE does not have were dropped.")
        if c["articles_missing"]:
            print(f"  {c['articles_missing']:,} articles are not in the table yet: import the "
                  f"articles first, then run this again.")
    else:
        c = dashboard.resolutions(args.csv, args.out, sidecar=args.candidates)
        print(f"\n{c['proposals']:,} proposals for {c['articles']:,} articles, closing "
              f"{c['entities_closed']:,} entities; then run {c['sql']}.")
    for path, n in c["files"]:
        print(f"  {path}  {n:,} rows, {path.stat().st_size / 1e6:.1f} MB")
    if c["skipped"]:
        print("  skipped, by reason:")
        for why, n in sorted(c["skipped"].items(), key=lambda kv: -kv[1]):
            print(f"    {n:6,}  {why}")
    return 0


def cmd_prompts(args) -> int:
    for path in prompts.write(args.out):
        text = path.read_text(encoding="utf-8")
        print(f"  {path}  {len(text):,} chars, ~{len(text) // 4:,} tokens")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m src.backfill")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("count")
    c.add_argument("--from", dest="since", default="2015-01", metavar="YYYY-MM")
    c.add_argument("--to", default=None, metavar="YYYY-MM")
    g = sub.add_parser("collect")
    g.add_argument("source", choices=("all", "cna", "st", "zb"))
    g.add_argument("--from", dest="since", default=None, metavar="YYYY-MM",
                   help="default: each archive's first month (CNA and ST 2015-01, Zaobao 2016-01)")
    g.add_argument("--to", default=None, metavar="YYYY-MM")
    g.add_argument("--out", default="data/backfill/collected", help="directory for the CSV files")
    g.add_argument("--workers", type=int, default=16,
                   help="pages in flight for zb, or st with --fetch (default 16)")
    g.add_argument("--slugs", action="store_true",
                   help="st only: take the title from the URL and skip the page (no description)")
    g.add_argument("--redo", action="store_true",
                   help="discard this source's existing files and collect again")
    r = sub.add_parser("repair")
    r.add_argument("source", choices=("st", "zb"))
    r.add_argument("--out", default="data/backfill/collected")
    r.add_argument("--workers", type=int, default=4)
    b = sub.add_parser("bodies")
    b.add_argument("csv", help="a CSV with url and source columns; article_text is filled in place")
    i = sub.add_parser("ingest")
    i.add_argument("csv", help="the internal model's extraction results")
    i.add_argument("--limit", type=int, default=None)
    i.add_argument("--dry-run", action="store_true", help="validate and count, write nothing")
    re_ = sub.add_parser("resolve-export")
    re_.add_argument("--out", default="data/backfill/sent")
    re_.add_argument("--candidates", default="data/backfill/answers/resolution-candidates.jsonl",
                     help="where each entity's offered candidates are kept for the import")
    re_.add_argument("--limit", type=int, default=None, help="articles")
    ri = sub.add_parser("resolve-import")
    ri.add_argument("csv", help="rows of article_id, resolutions (the model's JSON)")
    ri.add_argument("--candidates", default="data/backfill/answers/resolution-candidates.jsonl")
    ri.add_argument("--dry-run", action="store_true")
    pr = sub.add_parser("proposals", help="the archive's answers as the reviewers' Excel template, unreviewed")
    pr.add_argument("--out", default="data/backfill/archive-proposals-unreviewed.xlsx")
    d = sub.add_parser("dashboard")
    d.add_argument("table", choices=("articles", "entities", "resolutions"))
    d.add_argument("csv", nargs="+", help="the internal model's output files")
    d.add_argument("--out", default="data/backfill/import")
    d.add_argument("--candidates", default="data/backfill/answers/resolution-candidates.jsonl")
    q = sub.add_parser("prompts")
    q.add_argument("--out", default="data/backfill/prompts")
    args = p.parse_args(argv)
    return {"count": cmd_count, "collect": cmd_collect, "prompts": cmd_prompts, "dashboard": cmd_dashboard,
            "repair": cmd_repair, "bodies": cmd_bodies, "ingest": cmd_ingest,
            "resolve-export": cmd_resolve_export, "resolve-import": cmd_resolve_import,
            "proposals": cmd_proposals}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
