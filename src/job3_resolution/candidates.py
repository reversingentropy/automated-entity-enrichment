"""Retrieve database candidates for an extracted entity."""

from src.job3_resolution.rank import rank
from src.shared.supabase_client import get_client

RPC = "match_entities"

# Signal lives in the top three: measured max similarity falls 1.00 -> 0.78 ->
# 0.68 by rank, then flattens at 0.62 from rank four on. Five is cheap
# insurance; beyond that candidates are no likelier to be correct.
MATCH_COUNT = 5

# Asked of the database, before the dead are removed and the rest re-ranked.
# The function limits *name rows*, and a record with variant names occupies
# a row per variant, so eight rows can be four records. The right record for
# 李全盛 scored 0.579 under its guessed spelling, sixth by name, and eight
# rows ended before it. Over 73 confirmed matches the right record was never
# deeper than sixth, and fetching fifteen rows sends the resolver 0.4 more
# candidates per entity, about 350 tokens a night; the cap it sees stays
# MATCH_COUNT.
FETCH_COUNT = MATCH_COUNT + 10

# A name the extractor romanised is its guess, not the article's. 李全盛 came
# out as "Lee, Choon Seng", which is a real record for a different man, at
# similarity 1.00; the man himself is "Lee, Chuan Seng". A candidate reached
# only through the romanisation is therefore held below an exact match, so
# the resolver and the reviewer both see that the name evidence is one step
# removed, and a record the Chinese name itself matched outranks it.
ROMANISED_CEILING = 0.9
LATIN = __import__("re").compile(r"^[\x00-\x7F\u00C0-\u024F\s.,'’()-]+$")


def candidates_for(entity: dict, article_year: int | None = None,
                   lookup=None) -> list[dict]:
    """
    Candidates for one entity, searched under both of its names.

    Non-English names are matched twice -- as written and via
    `entity_name_en` -- because institutional names translate consistently and
    that lookup roughly doubled the Chinese match rate. Results are merged and
    de-duplicated on the canonical record, keeping the better score, then
    filtered and ordered by `rank` -- see that module for the two rules.
    """
    best: dict[str, dict] = {}

    # `lookup` replaces the database call with the same query answered
    # elsewhere; the backfill answers it from an in-memory copy of the file.
    def rpc(name):
        return (get_client().rpc(RPC, {"query_name": name, "match_count": FETCH_COUNT,
                                       "want_type": entity["entity_type"]})
                .execute().data or [])
    ask = lookup or rpc

    original = entity.get("entity_name") or ""
    guessed = bool(entity.get("entity_name_en")) and not LATIN.match(original)
    for name in (original, entity.get("entity_name_en")):
        if not name:
            continue
        rows = ask(name) if lookup is None else lookup(name, FETCH_COUNT, entity["entity_type"])
        for row in rows:
            uid = row["canonical_uid"]
            row = {**row, "matched_via": name}
            if guessed and name != original:
                row["similarity"] = min(row["similarity"], ROMANISED_CEILING)
                row["romanised"] = True
            if uid not in best or row["similarity"] > best[uid]["similarity"]:
                best[uid] = row

    return rank(list(best.values()), entity, article_year, keep=MATCH_COUNT)
