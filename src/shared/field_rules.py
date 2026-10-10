"""
The TTE field rules, shared by extraction and resolution.

Compiled from the National Library Board's cataloguing guidelines into
prompts/tte/field_rules.txt, with field names written exactly as TTE stores
them. Both prompts inject this at the {field_rules} placeholder, so there is
one source of truth for what a field means and what belongs in it.

The hand-written lists these replaced were wrong in ways that silently
corrupted output: date fields were missing their (yyyy)/(mm)/(dd) suffixes,
Affiliations was missing its (groupName) suffix, and Successor and Predecessor
were listed for organisations though TTE holds those as links, not fields. A
value filed under a near-miss name creates a new field rather than extending
the existing one.
"""

from functools import lru_cache
from pathlib import Path

# Two files, two audiences. The brief goes into prompts: exact field names,
# one line of meaning each, and the exclusions that are actually got wrong. The
# full compilation stays as the human reference -- injecting all 34k characters
# of cataloguing guidance made the model skim it and reach for short field
# names anyway, while crowding out the extraction task itself.
RULES_PATH = Path(__file__).resolve().parents[2] / "prompts" / "tte" / "fields_brief.txt"
FULL_RULES_PATH = Path(__file__).resolve().parents[2] / "prompts" / "tte" / "field_rules.txt"
OCCUPATIONS_PATH = Path(__file__).resolve().parents[2] / "prompts" / "tte" / "occupations.txt"
VOCABULARIES_PATH = Path(__file__).resolve().parents[2] / "prompts" / "tte" / "vocabularies.txt"
STYLE_PATH = Path(__file__).resolve().parents[2] / "prompts" / "tte" / "description_style.txt"
NOTABILITY_PATH = Path(__file__).resolve().parents[2] / "prompts" / "tte" / "notability.txt"

PLACEHOLDER = "{field_rules}"
OCCUPATIONS_PLACEHOLDER = "{occupations}"
VOCABULARIES_PLACEHOLDER = "{vocabularies}"
STYLE_PLACEHOLDER = "{description_style}"
NOTABILITY_PLACEHOLDER = "{notability}"


@lru_cache(maxsize=1)
def field_rules() -> str:
    return RULES_PATH.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def occupations() -> str:
    """
    The Occupations Thesaurus the guidelines require, as supplied by NLB.

    277 terms from data/Occupations Scope Notes.xlsx. This replaced a list
    derived from the authority file, which was close but wrong in both
    directions: it lacked 20 sanctioned terms that no record happens to use
    yet, and included 24 legacy values the thesaurus does not sanction
    ("Businessman", "Minister", "Director"). Constraining to a closed list
    removes a class of error by construction -- "Chairperson" is not on it.

    The spreadsheet also carries a scope note per term, which is not sent: it
    costs 4,200 tokens and the term names carry their own meaning.
    """
    return OCCUPATIONS_PATH.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def vocabularies() -> str:
    """Closed term lists for the other constrained fields, derived the same way."""
    return VOCABULARIES_PATH.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def description_style() -> str:
    """Section 7 of the guidelines: how a description must be written."""
    return STYLE_PATH.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def notability() -> str:
    """The appendix: whether an entity warrants a record at all."""
    return NOTABILITY_PATH.read_text(encoding="utf-8").strip()


def inject(prompt: str) -> str:
    """Fill the {field_rules} and {occupations} placeholders, if present."""
    if PLACEHOLDER in prompt:
        prompt = prompt.replace(PLACEHOLDER, field_rules())
    for placeholder, source in ((OCCUPATIONS_PLACEHOLDER, occupations),
                                (VOCABULARIES_PLACEHOLDER, vocabularies),
                                (STYLE_PLACEHOLDER, description_style),
                                (NOTABILITY_PLACEHOLDER, notability)):
        if placeholder in prompt:
            prompt = prompt.replace(placeholder, source())
    return prompt
