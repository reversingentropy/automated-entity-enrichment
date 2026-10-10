"""
Load a TTE dump into `entities`, replacing the previous snapshot.

Upload the dump zip exactly as TTE delivers it (TTE-DELTA_<date>.zip) to the
`tte-imports` bucket, or put it in data/tte/; loose full-export CSVs work too.

  python -m src.load_tte                      # read the Storage bucket
  python -m src.load_tte --source local       # read data/tte/
  python -m src.load_tte --dry-run            # report what would change, write nothing
  python -m src.load_tte --new-only --requeue-stale   # what the nightly run does

Only the nine vocabularies the pipeline holds are read. Nothing is written
until the whole dump has been read and checked. Afterwards `entities` is the
dump; the bucket and the ledger keep only the files of this load.

`--new-only` skips files the ledger already holds without downloading them.
`--requeue-stale` runs only when a load changed something: with nothing new,
it would treat the last dump's additions as new again every night.
"""

import argparse
import sys

from src.load_tte import dump, loader, source
from src.load_tte.parse import is_ours, parse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.load_tte")
    parser.add_argument("--source", choices=("bucket", "local"), default="bucket")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change, write nothing")
    parser.add_argument("--force", action="store_true",
                        help="with --new-only: read files the ledger already holds")
    parser.add_argument("--new-only", action="store_true",
                        help="skip files already in the ledger by name, without downloading them")
    parser.add_argument("--requeue-stale", action="store_true",
                        help="after a load that changed something, requeue the matches it may affect")
    args = parser.parse_args(argv)

    listing = source.list_bucket if args.source == "bucket" else source.list_local
    reader = source.read_bucket if args.source == "bucket" else source.read_local

    names = listing()
    if args.new_only and not args.force:
        known = loader.loaded_names()
        if any(n in known for n in names):
            print(f"{sum(n in known for n in names)} file(s) already loaded, not downloaded.")
        names = [n for n in names if n not in known]
    if not names:
        where = f"the {source.BUCKET} bucket" if args.source == "bucket" else str(source.LOCAL_DIR)
        print(f"No new TTE exports in {where}. Nothing to do.")
        return 0
    print(f"Reading {len(names)} file(s) from the {args.source}."
          + (" [DRY RUN -- nothing will be written]" if args.dry_run else ""))

    files, deletes, dumps, not_ours = [], set(), [], []
    for name in names:
        data = reader(name)
        if name.lower().endswith(".zip"):
            csvs, dels, skipped = dump.expand(data)
            files += csvs
            deletes |= dels
            not_ours += skipped
            dumps.append((name, data))
        elif is_ours(name):
            files.append((name, data.decode("utf-8-sig")))
        else:
            not_ours.append(name)
    if not_ours:
        print(f"  {len(not_ours)} file(s) of other vocabularies left unread")

    parsed = {name: (parse(name, text), loader.checksum(text)) for name, text in files}
    entities = [e for pf, _ in parsed.values() for e in pf.entities.values()]
    for name, (pf, _) in parsed.items():
        print(f"  {name}: {len(pf.entities):,} records")
    if deletes:
        print(f"  delete list: {len(deletes):,} uids")

    existing = loader.load_existing()
    to_write = loader.changed(entities, existing)
    gone = loader.dropped(entities, deletes, existing)
    try:
        loader.check_plausible(entities, gone, deletes, existing)
    except loader.SuspectSnapshotError as exc:
        print(f"\nABORTED: {exc}")
        return 1
    matched = loader.matched_uids()
    delete, keep = loader.removable(gone, matched, entities, existing)
    print(f"\n{len(to_write):,} new or changed, {len(entities) - len(to_write):,} unchanged (not rewritten).")
    print(f"{len(gone):,} dropped by the dump or its delete list: {len(delete):,} to delete, "
          f"{len(keep):,} kept as inactive because a proposal or record still points at them.")
    if args.dry_run:
        return 0

    loader.write(to_write, existing)
    loader.remove(gone, entities, existing, matched)
    for name, (pf, digest) in parsed.items():
        loader.record_import(name, pf.entity_type, pf.snapshot, digest, len(pf.entities))
    for name, data in dumps:
        loader.record_import(name, "DUMP", loader.dump_date(name), loader.checksum(data), len(entities))

    # Only the latest: the ledger and the bucket keep this load's files alone.
    this_load = set(parsed) | {name for name, _ in dumps} | set(names)
    forgotten = loader.forget_older(this_load)
    older_files = []
    if args.source == "bucket":
        older_files = [n for n in source.list_bucket() if n not in this_load]
        source.remove_from_bucket(older_files)
    print(f"Done. Removed {len(forgotten)} older ledger row(s) and {len(older_files)} older file(s) from the bucket.")

    if args.requeue_stale and to_write:
        from src.job3_resolution.requeue import requeue, stale_entities
        stale = stale_entities()
        requeue([e["id"] for e in stale])
        print(f"Requeued {len(stale)} matched entit(ies) this dump may have changed; Job 3 resolves them next.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
