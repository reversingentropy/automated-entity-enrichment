"""
The field names TTE actually stores, and the code that enforces them.

The prompt asks the model to use exact names; this makes sure it did. A value
filed under "Year Started" instead of "Year Started (yyyy)", or "Affiliations"
instead of "Affiliations(groupName)", creates a new field rather than extending
the one that exists -- a silent corruption that looks like a successful update.

Names below are taken from the National Library Board's cataloguing guidelines
and verified against the loaded authority data.
"""

import re

COMMON = ("Name", "Description")

FIELDS: dict[str, set[str]] = {
    "PERSON": {*COMMON, "Title", "Occupation", "Nationality", "Place of Birth",
               "Birth Year (yyyy)", "Birth Month (mm)", "Birth Day (dd)",
               "Death Year (yyyy)", "Death Month (mm)", "Death Day (dd)",
               "Active Years", "Achievements", "Education", "Awards",
               "Affiliations(groupName)", "Spouse", "Child", "Parent"},
    "ORGANISATION": {*COMMON, "Country", "Street Address", "Postal Code", "Founder",
                     "Year Started (yyyy)", "Month Started (mm)", "Day Started (dd)",
                     "Year Ended (yyyy)", "Month Ended (mm)", "Day Ended (dd)",
                     "Parent Organisation", "Group Members", "Awards"},
    "FACILITY": {*COMMON, "Street Address", "Country", "Postal Code", "Feature Type",
                 "Year Completed (yyyy)", "Month Completed (mm)", "Day Completed (dd)"},
    "LOCATION": {*COMMON, "Country", "Feature Type", "Street Address", "Postal Code"},
    "EVENT": {*COMMON, "SN", "Organiser", "Year", "Month", "Day",
              "Category", "Topic", "Locality"},
    "AWARD": {"Name", "SN", "Awarding Entity", "Year First Awarded"},
    "PROGRAMME": {*COMMON},
    "LEGAL_ACT": {"Name", "SN"},
}


def _normalise(name: str) -> str:
    """
    Reduce a field name to what a model is likely to get right.

    The bracketed suffixes are the part that gets dropped -- "Year Started" for
    "Year Started (yyyy)", "Affiliations" for "Affiliations(groupName)" -- so
    they are removed before comparing. Case and spacing go too.
    """
    return re.sub(r"[^a-z]", "", re.sub(r"\s*\([^)]*\)", "", name).lower())


_LOOKUP = {etype: {_normalise(f): f for f in fields} for etype, fields in FIELDS.items()}


def canonical(entity_type: str, field: str) -> str | None:
    """
    The stored name for `field`, or None if TTE has no such field.

    Matching ignores case, spacing and brackets, so "Year Started",
    "year started (yyyy)" and "YearStarted" all resolve to the one real name.
    Anything that does not resolve is a field the model invented.
    """
    return _LOOKUP.get(entity_type, {}).get(_normalise(field))


def _vocabulary(path_name: str) -> set[str]:
    from src.shared.field_rules import occupations, vocabularies
    if path_name == "Occupation":
        return {t for t in occupations().splitlines() if t and " " not in t[:1]}
    block, terms = None, set()
    for line in vocabularies().splitlines():
        if line and not line.startswith(" "):
            block = line.split("  (")[0]
        elif block and block.endswith(path_name) and line.startswith("  "):
            terms |= {t.strip() for t in line.split(",") if t.strip()}
    return terms


# Fields whose value must come from a controlled list. Enforced here rather
# than in the prompt: the lists cost 1,550 tokens of instructions, and an
# ablation showed that volume of rules suppressing extraction by 16%.
CONSTRAINED = ("Occupation", "Nationality", "Title", "Feature Type", "Category")

DELIMITER = " | "


def clean_value(field: str, value: str) -> str | None:
    """
    Keep only the parts of a value that the controlled list allows.

    A multi-valued field keeps its valid terms and drops the rest, so
    "Lawyer | Chief Executive Officer" becomes "Lawyer" rather than being lost
    entirely. A field with nothing valid left is dropped.
    """
    if field not in CONSTRAINED:
        return value
    allowed = _vocabulary(field)
    if not allowed:
        return value
    kept = [t.strip() for t in str(value).split(DELIMITER)
            if t.strip() and t.strip() in allowed]
    return DELIMITER.join(kept) or None


def clean_fields(entity_type: str, fields: dict) -> tuple[dict, list[str]]:
    """Return the fields under their stored names, plus any that were dropped."""
    kept, dropped = {}, []
    for name, value in (fields or {}).items():
        real = canonical(entity_type, name)
        if real is None:
            dropped.append(name)
            continue
        cleaned = clean_value(real, value)
        if cleaned is None:
            dropped.append(f"{real}={value!r}")
            continue
        kept[real] = cleaned
    return kept, dropped
