"""
Single shared Supabase client.

Every job imports `get_client()` from here rather than calling
create_client() itself, so credential handling lives in one place.
"""

import os

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

_client: Client | None = None


def get_client() -> Client:
    """Return the process-wide Supabase client, creating it on first use."""
    global _client
    if _client is not None:
        return _client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        raise RuntimeError(
            "Missing Supabase credentials. Set SUPABASE_URL and SUPABASE_KEY "
            "(the secret key) in .env or the environment."
        )

    _client = create_client(url, key)
    return _client


_COLUMNS: dict[tuple[str, str], bool] = {}


def column_exists(table: str, column: str) -> bool:
    """
    True if `table.column` is present, cached for the process.

    Migrations are applied by hand in the SQL editor, so code that reads a
    new column has to keep working before it exists; selecting a column
    that is not there fails the whole query.
    """
    key = (table, column)
    if key not in _COLUMNS:
        try:
            get_client().from_(table).select(column).limit(1).execute()
            _COLUMNS[key] = True
        except Exception:
            _COLUMNS[key] = False
    return _COLUMNS[key]
