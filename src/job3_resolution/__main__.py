"""
Job 3 -- Entity Resolution.

For each article with unresolved entities: retrieve database candidates for
every entity, ask Gemini which correspond to existing authority records, and
write the decisions to candidate_matches as proposals.

Nothing mutates the `entities` table. Resolutions are recorded with
`applied = false` for a review step.

  python -m src.job3_resolution                      # full run (what CI does)
  python -m src.job3_resolution --limit 2 --dry-run  # no writes
  python -m src.job3_resolution --limit 2            # resolve 2 articles
"""

import argparse
import sys
import time

from tqdm import tqdm

from src.job3_resolution.candidates import candidates_for
from src.job3_resolution.fetch import fetch_unresolved
from src.job3_resolution.prompt import build_entity_block, resolve
from src.job3_resolution.update import build_rows, save
from src.shared import gemini_client
from src.shared.config import SETTINGS
from src.shared.supabase_client import column_exists


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.job3_resolution")
    parser.add_argument("--limit", type=int, default=None,
                        help="only resolve the first N articles")
    parser.add_argument("--dry-run", action="store_true",
                        help="retrieve and resolve, but write nothing")
    parser.add_argument("--requeue-stale", action="store_true",
                        help="after a TTE update, requeue only the entities the "
                             "new snapshot actually affects, then stop")
    args = parser.parse_args(argv)

    if args.requeue_stale:
        from src.job3_resolution.requeue import requeue, stale_entities
        stale = stale_entities()
        if not stale:
            print("Nothing to requeue: the new snapshot changes no resolution.")
            return 0
        for entity in stale[:20]:
            print(f"  {entity['entity_name'][:40]:42} {entity['why']}")
        if len(stale) > 20:
            print(f"  ... and {len(stale) - 20} more")
        if args.dry_run:
            print(f"\nDry run: {len(stale)} entit(ies) would be requeued.")
            return 0
        requeue([e["id"] for e in stale])
        print(f"\nRequeued {len(stale)} entit(ies). Run again without the flag to resolve.")
        return 0

    articles = fetch_unresolved(limit_articles=args.limit)

    if not articles:
        print("No unresolved entities. Nothing to do.")
        return 0

    total_entities = sum(len(a["entities"]) for a in articles)
    print(f"Fetched {total_entities} unresolved entit(ies) across "
          f"{len(articles)} article(s)."
          + (" [DRY RUN -- nothing will be written]" if args.dry_run else ""))

    resolved = matched = flagged = created = failed = 0

    batches = [articles[i:i + SETTINGS.resolution.articles_per_request]
               for i in range(0, len(articles), SETTINGS.resolution.articles_per_request)]

    bar = tqdm(batches, unit="batch", disable=None,
               bar_format="{n_fmt}/{total_fmt} |{bar}| {percentage:3.0f}% · {remaining} left")

    for index, batch in enumerate(bar, start=1):
        entities = [e for article in batch for e in article["entities"]]
        titles = {e["id"]: a["title"] for a in batch for e in a["entities"]}
        years = {e["id"]: a.get("year") for a in batch for e in a["entities"]}

        if len(batch) == 1:
            bar.write(f"[{index}/{len(batches)}] article {batch[0]['article_id']}: "
                      f"{batch[0]['title'][:56]} ({len(entities)} entities)")
        else:
            bar.write(f"[{index}/{len(batches)}] {len(batch)} articles, "
                      f"{len(entities)} entities")

        try:
            candidates_by_id = {e["id"]: candidates_for(e, years.get(e["id"]))
                                for e in entities}
        except Exception as exc:
            bar.write(f"  Candidate retrieval failed, leaving unresolved: {exc}")
            failed += 1
            continue

        blocks = [build_entity_block(e, candidates_by_id[e["id"]], titles[e["id"]])
                  for e in entities]

        try:
            response = resolve(blocks)
        except Exception as exc:
            bar.write(f"  Resolution failed, leaving unresolved: {exc}")
            failed += 1
            continue

        rows = build_rows(response, entities, candidates_by_id)
        if column_exists("candidate_matches", "resolution_model"):
            for row in rows:
                row["resolution_model"] = gemini_client.LAST_MODEL
        decided = {r["extracted_id"] for r in rows}

        for entity in entities:
            row = next((r for r in rows if r["extracted_id"] == entity["id"]), None)
            n = len(candidates_by_id[entity["id"]])
            if row is None:
                bar.write(f"    CREATE_NEW        {entity['entity_name'][:34]}  ({n} candidates seen)")
            else:
                target = row["matched_uid"] or "-"
                bar.write(f"    {row['resolution_action']:<17} {entity['entity_name'][:34]}"
                          f"  -> {target}  [{row['confidence']}]")
                bar.write(f"        {row['reasoning'][:96]}")

        if args.dry_run:
            bar.write(f"  Dry run: would write {len(rows)} resolution(s).")
        else:
            try:
                save([e["id"] for e in entities], rows)
            except Exception as exc:
                bar.write(f"  Write failed, leaving unresolved: {exc}")
                failed += 1
                continue
            bar.write(f"  Wrote {len(rows)} resolution(s), marked {len(entities)} resolved.")

        resolved += len(entities)
        matched += sum(1 for r in rows if r["resolution_action"] == "MATCH_AND_UPDATE")
        flagged += sum(1 for r in rows if r["resolution_action"] != "MATCH_AND_UPDATE")
        created += len(entities) - len(decided)

        if index < len(batches):
            time.sleep(SETTINGS.resolution.seconds_between_articles)

    verb = "Would resolve" if args.dry_run else "Resolved"
    print(f"\n{verb} {resolved}/{total_entities} entit(ies): "
          f"{matched} matched, {flagged} flagged, {created} new.")

    if failed:
        print(f"{failed} article(s) failed and will be retried next run.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
