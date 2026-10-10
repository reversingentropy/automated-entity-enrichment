"""
A TTE dump zip, as TTE delivers it.

    TTE-DELTA_20260901.zip
      TTE-DELTA_20260901/LDMS.zip
        LDMS/TTE/2026-09-01/mod/TTE-<VOCABULARY>_FULL_<date>.csv   one full export per vocabulary
        LDMS/TTE/2026-09-01/del/TTE-DELETE_DELTA_<date>.txt       uids to delete, one per line

Only the vocabularies this pipeline holds are read; the rest (subject
headings, languages, collections ...) are never unpacked.
"""

import io
import zipfile

from src.load_tte.parse import is_ours


def expand(data: bytes) -> tuple[list[tuple[str, str]], set[str], list[str]]:
    """The dump's CSVs we load, as (filename, text); its delete list; the files skipped."""
    outer = zipfile.ZipFile(io.BytesIO(data))
    nested = [n for n in outer.namelist() if n.lower().endswith(".zip")]
    archive = zipfile.ZipFile(io.BytesIO(outer.read(nested[0]))) if nested else outer
    csvs, deletes, skipped = [], set(), []
    for member in archive.namelist():
        base = member.rsplit("/", 1)[-1]
        if "/del/" in member and base.lower().endswith(".txt"):
            text = archive.read(member).decode("utf-8-sig", "replace")
            deletes |= {line.strip() for line in text.splitlines() if line.strip()}
        elif base.lower().endswith(".csv"):
            if is_ours(base):
                csvs.append((base, archive.read(member).decode("utf-8-sig")))
            else:
                skipped.append(base)
    return csvs, deletes, skipped
