"""
Paged reads.

PostgREST caps every response at 1,000 rows regardless of how many match, and
does so silently -- an unbounded select on a large table simply returns the
first page and looks like a complete result. Anything that must see every row
goes through fetch_all().
"""

from typing import Callable

PAGE_SIZE = 1000


def fetch_all(build_query: Callable, page_size: int = PAGE_SIZE, order: str = "id") -> list[dict]:
    """
    Run a query repeatedly with .range() until every row has been read.

    `build_query` is called for each page and must return a fresh PostgREST
    query builder, since a builder cannot be re-executed with a new range.

    Every page is ordered by `order`, the table's key. Without an order,
    Postgres hands back rows in whatever order the heap has them, and that
    order shifts between pages once the table has been written to in bulk:
    a 48,000-row read came back with the right total and 349 rows repeated
    in place of 349 missed. Pass `order="uid"` for the authority table.
    """
    rows: list[dict] = []
    start = 0

    while True:
        query = build_query()
        if order:
            query = query.order(order)
        page = query.range(start, start + page_size - 1).execute().data or []
        rows.extend(page)
        if len(page) < page_size:
            return rows
        start += page_size
