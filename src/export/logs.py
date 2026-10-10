"""
The evaluation's two logs, as CSVs, test accounts left out.

    python -m src.export --logs [--out data/evaluation]

change-log.csv: every change a reviewer logged from the desk's sheet page;
weekly-log.csv: each reviewer's minutes and changes per week and way of
working. Both are per person, which is why they are collected here with the
service role rather than shown to colleagues.
"""

import csv
from pathlib import Path


def collect(out_dir: Path | str = "data/evaluation") -> dict[str, int]:
    from src.export.accounts import is_test
    from src.shared.pagination import fetch_all
    from src.shared.supabase_client import get_client

    client = get_client()
    users = list(client.auth.admin.list_users())
    names = {u.id: (u.user_metadata or {}).get("name") or (u.email or "").split("@")[0] for u in users}
    testers = {u.id for u in users if is_test(u)}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    counts = {}
    for table, columns in (
        ("change_log", ["found_on", "method", "reviewer", "tte_entity", "tte_uid", "kind", "field",
                        "old_value", "new_value", "article_url", "at"]),
        ("weekly_log", ["week_start", "method", "reviewer", "minutes", "changes", "at"]),
    ):
        rows = [r for r in fetch_all(lambda: client.from_(table).select("*"), order="id") if r["reviewer"] not in testers]
        path = out / f"{table.replace('_', '-')}.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(columns)
            for r in sorted(rows, key=lambda r: (str(r.get(columns[0])), str(r.get("at")))):
                w.writerow([names.get(r[c], r[c]) if c == "reviewer" else r.get(c, "") for c in columns])
        counts[path.name] = len(rows)
    return counts
