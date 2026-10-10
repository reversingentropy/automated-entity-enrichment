"""
CSV output in 50,000-row files, resumable.

The archive is 240,000 articles and the ST/Zaobao halves take days of polite
fetching, so a run has to survive being stopped. Every URL already written to
any file in the output directory is skipped on the next run; a file is only
ever appended to, and a new one is opened at 50,000 rows.
"""

import csv
from pathlib import Path

COLUMNS = ["url", "source", "title", "description", "category", "published", "month"]
ROWS_PER_FILE = 50_000


class Writer:
    def __init__(self, directory: Path | str, source: str):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.source = source
        self.seen: set[str] = set()
        self._part = 0
        self._count = 0
        self._handle = None
        self._writer = None
        self._resume()

    def _files(self) -> list[Path]:
        return sorted(self.dir.glob(f"{self.source}-*.csv"))

    def _resume(self):
        """Read what previous runs wrote, so this one continues rather than repeats."""
        for path in self._files():
            with path.open(encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
            self.seen.update(r["url"] for r in rows if r.get("url"))
            self._part = int(path.stem.rsplit("-", 1)[1])
            self._count = len(rows)
        if self._files() and self._count < ROWS_PER_FILE:
            self._open(self._part, append=True)

    def _open(self, part: int, append: bool = False):
        if self._handle:
            self._handle.close()
        path = self.dir / f"{self.source}-{part:03d}.csv"
        new = not (append and path.exists())
        self._handle = path.open("a" if append else "w", encoding="utf-8-sig", newline="")
        self._writer = csv.DictWriter(self._handle, fieldnames=COLUMNS, extrasaction="ignore")
        if new:
            self._writer.writeheader()
        self._part = part
        if not append:
            self._count = 0

    def write(self, row: dict) -> bool:
        """Write one row unless its URL is already on disk. Returns whether it wrote."""
        if row["url"] in self.seen:
            return False
        if self._handle is None or self._count >= ROWS_PER_FILE:
            self._open(self._part + 1 if self._handle or self._files() else 1)
        self._writer.writerow(row)
        self._handle.flush()
        self.seen.add(row["url"])
        self._count += 1
        return True

    def close(self):
        if self._handle:
            self._handle.close()
            self._handle = None

    @property
    def written(self) -> int:
        return len(self.seen)
