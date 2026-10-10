"""
Re-split the collected archive to a fixed rows-per-file limit.

    python -m src.backfill.split [--limit 49999] [--in data/backfill/collected] [--out data/backfill/archive]

Reads every collected CSV, drops any URL seen twice, and writes one set of
files per source, each holding at most `limit` data rows, as plain UTF-8
without a byte-order mark. The collector writes 50,000 a file; the system
the files are for takes 49,999.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

COLUMNS = ["url", "source", "title", "description", "category", "published", "month"]


def combine(directory: Path) -> pd.DataFrame:
    frames = []
    for path in sorted(directory.glob("*-*.csv")):
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        frames.append(frame[[c for c in COLUMNS if c in frame.columns]])
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    all_rows = pd.concat(frames, ignore_index=True)
    return all_rows.drop_duplicates(subset="url", keep="first").reset_index(drop=True)


def split(frame: pd.DataFrame, out: Path, limit: int) -> list[tuple[Path, int]]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for source, rows in frame.groupby("source", sort=True):
        rows = rows.sort_values(["published", "url"], kind="stable").reset_index(drop=True)
        for part, start in enumerate(range(0, len(rows), limit), start=1):
            chunk = rows.iloc[start:start + limit]
            path = out / f"{source}-{part:03d}.csv"
            chunk.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
            written.append((path, len(chunk)))
    return written


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m src.backfill.split")
    p.add_argument("--in", dest="src", default="data/backfill/collected")
    p.add_argument("--out", default="data/backfill/archive")
    p.add_argument("--limit", type=int, default=49_999)
    args = p.parse_args(argv)

    frame = combine(Path(args.src))
    print(f"{len(frame):,} distinct rows across {frame['source'].nunique()} sources")
    for path, n in split(frame, Path(args.out), args.limit):
        print(f"  {path.name:14} {n:>7,} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
