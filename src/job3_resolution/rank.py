"""
Order retrieval's shortlist by more than the name.

Trigram similarity finds records whose names look alike, and that is all it
knows. Of 211 candidates ever shown to the resolver, 32 had died before the
article was written, and for "Alan Chan" the right record sat fourth at 0.47
behind three living strangers at 0.58. Both sides of a comparison carry
fields, though, and the review card already compares them; using the same
comparison to rank the shortlist costs nothing new.

Two rules, both general:

  A person recorded as dead before the article cannot be its subject, unless
  the article is itself about a death.

  A candidate sharing a distinguishing fact with the extracted entity ranks
  above one that does not. Where nothing overlaps the name decides, as it did
  before -- absence never demotes, only presence promotes, which is what makes
  this safe to apply to every type.
"""

import re

# Fields whose shared values say something about identity, and how much.
# Nationality and Country are shared by nearly everyone and say nothing;
# an affiliation or a birth year is close to a fingerprint.
STRONG = {
    "Affiliations(groupName)", "Parent Organisation", "Street Address",
    "Postal Code", "Awards", "Education", "Birth Year (yyyy)",
    "Place of Birth", "Founder", "Group Members", "Spouse", "Child", "Parent",
}
WEAK = {"Occupation", "Feature Type", "Title", "Category"}
STRONG_BONUS = 0.20
WEAK_BONUS = 0.08
MAX_BONUS = 0.45

DELIMITER = "|"
DEATH = "Death Year (yyyy)"

# An article about someone's death, memorial or legacy may legitimately name
# a person the file records as dead.
ABOUT_A_DEATH = re.compile(
    r"\b(the late|died|death|passed away|posthumous|obituar|memorial)\b|逝世|去世|已故|离世",
    re.I)


def _values(text) -> set[str]:
    return {v.strip().casefold() for v in str(text or "").split(DELIMITER) if v.strip()}


def _shared(mine: set[str], theirs: set[str]) -> bool:
    if mine & theirs:
        return True
    # "National Council of Social Service" against "...Social Services":
    # one contains the other, and both are long enough for that to mean it.
    return any(len(a) >= 8 and len(b) >= 8 and (a in b or b in a)
               for a in mine for b in theirs)


def overlap(entity_fields: dict | None, candidate_fields: dict | None) -> list[str]:
    """The distinguishing fields on which both sides agree."""
    entity_fields, candidate_fields = entity_fields or {}, candidate_fields or {}
    out = []
    for field in STRONG | WEAK:
        if field in entity_fields and field in candidate_fields:
            if _shared(_values(entity_fields[field]), _values(candidate_fields[field])):
                out.append(field)
    return sorted(out)


def bonus(shared: list[str]) -> float:
    total = sum(STRONG_BONUS if f in STRONG else WEAK_BONUS for f in shared)
    return min(total, MAX_BONUS)


def impossible(candidate: dict, entity: dict, article_year: int | None) -> str | None:
    """Why a candidate cannot be this entity, or None if it can."""
    if not article_year or entity.get("entity_type") != "PERSON":
        return None
    fields = candidate.get("canonical_fields") or {}
    died = str(fields.get(DEATH, "")).strip()
    if not died.isdigit():
        return None
    if int(died) >= article_year - 1:
        return None
    if DEATH in (entity.get("fields") or {}):
        return None
    if ABOUT_A_DEATH.search(" ".join(str(entity.get(k) or "")
                                     for k in ("summary", "evidence"))):
        return None
    return f"died {died}, article {article_year}"


def rank(candidates: list[dict], entity: dict, article_year: int | None,
         keep: int) -> list[dict]:
    """
    The shortlist, filtered and ordered, each candidate annotated with why.

    `score` is what the resolver and the review card should sort on;
    `similarity` stays as the raw name measure it always was.
    """
    ranked = []
    for c in candidates:
        why = impossible(c, entity, article_year)
        if why:
            continue
        shared = overlap(entity.get("fields"), c.get("canonical_fields"))
        ranked.append({**c, "overlap": shared,
                       "score": round(c["similarity"] + bonus(shared), 3)})
    ranked.sort(key=lambda c: (-c["score"], -c["similarity"]))
    return ranked[:keep]
