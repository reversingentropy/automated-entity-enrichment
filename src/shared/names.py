"""
Names of records, as TTE writes them.

A link field (Awards, Affiliations, Parent Organisation, Founder) holds the
names of other records, and TTE writes a name its own way: "Singapore.
Ministry of Health", "National Wages Council (Singapore)", "Awards" in the
plural. A value proposed as the article wrote it would have to be reworded
by hand, so once the record is found the value is its name, with what the
article wrote kept beside it.
"""

import re

LINKED_FIELDS = {"Awards": "AWARD", "Affiliations(groupName)": "ORGANISATION",
                 "Parent Organisation": "ORGANISATION", "Founder": "PERSON"}
DELIMITER = " | "
YEAR = re.compile(r"\(?\b(?:18|19|20)\d{2}\b\)?")
TRAILING_YEAR = re.compile(r"\s*\((?:18|19|20)\d{2}\)\s*$")
HOUSE_STYLE = re.compile(r"^singapore\.?\s+|\s*\(singapore\)$|\s*\([a-z]{2,6}\)|^the\s+|,?\s+singapore$")
# "博理中学 (Bendemeer Secondary School)": the original name with its gloss.
ORIGINAL_WITH_GLOSS = re.compile(r"^(?P<original>[^()]*[^\x00-\x7F][^()]*?)\s*\((?P<gloss>[^()]+)\)\s*$")


def values(text) -> list[str]:
    return [v.strip() for v in str(text or "").split(DELIMITER) if v.strip()]


def plain(name: str) -> str:
    """A name as a lookup key: case, quote style and spacing set aside."""
    return " ".join(name.replace("’", "'").replace("‘", "'")
                    .replace("“", '"').replace("”", '"').casefold().split())


def house(name: str) -> str:
    """
    The name with TTE's house style set aside. Two names equal under this
    are the same thing spelt TTE's way; two that are merely near are not.
    """
    n = HOUSE_STYLE.sub("", plain(name)).strip()
    n = re.sub(r"['’]s\b", "", n)
    n = re.sub(r"\bawards\b", "award", n)
    return " ".join(re.sub(r"[^\w一-鿿 ]+", " ", n).split())


def without_year(value: str) -> str:
    return " ".join(YEAR.sub("", value).split())


def renamed(value: str, tte_name: str) -> str:
    """The record's name, keeping the year the value carried: it is the person's, not the award's."""
    m = TRAILING_YEAR.search(value)
    return tte_name + (m.group(0).rstrip() if m else "")


def tries_for(value: str) -> list[str]:
    """What to look up for one value: the original and its gloss, or the value itself."""
    name = without_year(value)
    m = ORIGINAL_WITH_GLOSS.match(name)
    return [m.group("original").strip(), m.group("gloss").strip()] if m else [name]


def name_as_tte(value: str, hits: list[dict]) -> str | None:
    """
    The record's name for a value, given what a name search returned for it,
    or None when none of the hits is the same thing. A hit counts when its
    name is the value's, or the value in TTE's house style.
    """
    wanted = {plain(t) for t in tries_for(value)} | {house(t) for t in tries_for(value)}
    for h in hits:
        canonical = h.get("canonical_name") or h.get("name") or ""
        # The search may have matched a variant name (a Chinese one, a former
        # one) that points at the canonical record; the variant is what has
        # to equal the value, and the canonical name is what is returned.
        for label in (h.get("matched_name") or "", canonical):
            if label and (plain(label) in wanted or house(label) in wanted):
                return canonical
    return None


def name_link_values(update: dict, search) -> None:
    """
    Rewrite a link field's value to TTE's names in place, keeping what the
    article wrote under "wrote". `search(name, entity_type)` returns the
    name search's rows for a name. Values TTE does not hold are left as
    written.
    """
    field = update.get("field")
    if field not in LINKED_FIELDS or update.get("strategy") not in ("APPEND", "REPLACE"):
        return
    out, wrote = [], {}
    for v in values(update.get("value")):
        found = None
        for t in tries_for(v):
            found = name_as_tte(v, search(t, LINKED_FIELDS[field]) or [])
            if found:
                break
        new = renamed(v, found) if found else v
        if new != v:
            wrote[new] = v
        out.append(new)
    if wrote:
        update["value"] = DELIMITER.join(out)
        update["wrote"] = wrote
