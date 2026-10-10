"""Where TTE exports come from: a local directory or the Storage bucket.

Either may hold dump zips as TTE delivers them (TTE-DELTA_<date>.zip) or
loose full-export CSVs (TTE-<VOCABULARY>_FULL_<date>.csv).
"""

from pathlib import Path

from src.shared.supabase_client import get_client

BUCKET = "tte-imports"
LOCAL_DIR = Path(__file__).resolve().parents[2] / "data" / "tte"


def _wanted(name: str) -> bool:
    return name.upper().startswith("TTE-") and name.lower().endswith((".csv", ".zip"))


def list_local(directory: Path | str = LOCAL_DIR) -> list[str]:
    return sorted(p.name for p in Path(directory).glob("*") if _wanted(p.name))


def read_local(name: str, directory: Path | str = LOCAL_DIR) -> bytes:
    return (Path(directory) / name).read_bytes()


def list_bucket() -> list[str]:
    return sorted(o["name"] for o in get_client().storage.from_(BUCKET).list() if _wanted(o["name"]))


def read_bucket(name: str) -> bytes:
    return get_client().storage.from_(BUCKET).download(name)


def remove_from_bucket(names: list[str]) -> None:
    if names:
        get_client().storage.from_(BUCKET).remove(names)
