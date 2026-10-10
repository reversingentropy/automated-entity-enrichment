"""
Trigram retrieval done locally, against a one-time copy of the authority file.

The nightly path calls `match_entities()` in Postgres once or twice per
entity, which is fine for a dozen entities a night. For 31,000 backfill
entities it is 60,000 RPC calls to a free-tier database that closes the
connection after 20,000; the first export died a third of the way through.
The authority file is 52,628 rows. Pull it once, index its names by
trigram in memory, and retrieval is a few milliseconds an entity with no
network at all.

This reproduces pg_trgm's measure, so the shortlist is the one the SQL
would have returned: names lower-cased and split on non-word characters,
each word padded with two spaces before and one after, three-character
grams, similarity = shared / (grams in either). The 0.30 floor, the type
filter, the canonical join and the top-five cut are the same.
"""

import pickle
import re
from collections import defaultdict
from pathlib import Path

from src.shared.pagination import fetch_all
from src.shared.supabase_client import get_client

CACHE = Path("data/backfill/entities-cache.pkl")
COLUMNS = "uid, name, entity_type, language, canonical_uid, is_active, fields"
WORD = re.compile(r"\w+")


def trigrams(text: str) -> set[str]:
    out: set[str] = set()
    for word in WORD.findall((text or "").lower()):
        padded = "  " + word + " "
        out.update(padded[i:i + 3] for i in range(len(padded) - 2))
    return out


def load_entities(refresh: bool = False) -> list[dict]:
    """Every authority record, from the local cache or one paged pull."""
    if CACHE.exists() and not refresh:
        return pickle.loads(CACHE.read_bytes())
    rows = fetch_all(lambda: get_client().from_("entities").select(COLUMNS), order="uid")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_bytes(pickle.dumps(rows))
    return rows


class Index:
    def __init__(self, entities: list[dict]):
        self.by_uid = {e["uid"]: e for e in entities}
        self.active = [e for e in entities if e.get("is_active")]
        self.grams = [trigrams(e["name"]) for e in self.active]
        self.postings: dict[str, list[int]] = defaultdict(list)
        for i, g in enumerate(self.grams):
            for t in g:
                self.postings[t].append(i)

    def match(self, query_name: str, match_count: int = 5, want_type: str | None = None,
              min_similarity: float = 0.30) -> list[dict]:
        """The rows match_entities() would return, in the same shape."""
        q = trigrams(query_name)
        if not q:
            return []
        shared: dict[int, int] = defaultdict(int)
        for t in q:
            for i in self.postings.get(t, ()):
                shared[i] += 1
        scored = []
        for i, n in shared.items():
            e = self.active[i]
            if want_type and e["entity_type"] != want_type:
                continue
            sim = n / (len(q) + len(self.grams[i]) - n)
            if sim >= min_similarity:
                scored.append((sim, e))
        scored.sort(key=lambda x: (-x[0], x[1]["name"]))
        out = []
        for sim, e in scored[:match_count]:
            c = self.by_uid.get(e.get("canonical_uid") or e["uid"], e)
            out.append({
                "matched_uid": e["uid"], "matched_name": e["name"],
                "matched_language": e.get("language"), "similarity": round(sim, 6),
                "canonical_uid": c["uid"], "canonical_name": c["name"],
                "canonical_type": c["entity_type"], "canonical_language": c.get("language"),
                "canonical_fields": c.get("fields") or {},
            })
        return out
