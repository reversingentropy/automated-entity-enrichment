"""
Parse a TTE authority CSV into entities and links.

The files are EAV: every row is (Key UID, Key Descriptor, Key Vocabulary,
Relationship Type, Related UID, Related Descriptor, Related Vocabulary).

A row is an entity-to-entity LINK when Related UID is set (Use, UF, CHItoENG,
BT, NT, RT, ...), and an ATTRIBUTE otherwise, with the value in Related
Descriptor (Description, Country, Occupation, ...).
"""

import csv
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# Filenames look like TTE-PEOPLE_FULL_20260603.csv
FILENAME_RE = re.compile(r"TTE-(?P<vocab>[A-Z_]+)_FULL_(?P<snapshot>\d{8})\.csv$", re.I)

# The nine authority files map onto the eight entity types the prompts use.
# Historical events share the EVENT type; `vocabulary` keeps them distinguishable.
TYPE_BY_FILE = {
    "PEOPLE": "PERSON",
    "ORGANISATIONS": "ORGANISATION",
    "GEOBUILDINGS": "FACILITY",
    "GEOGRAPHICS": "LOCATION",
    "EVENTS": "EVENT",
    "HISTORICAL_EVENTS": "EVENT",
    "AWARDS": "AWARD",
    "PROGRAMMES": "PROGRAMME",
    "LEGALACTS": "LEGAL_ACT",
}

# Vocabulary suffixes mark the language of a record, e.g. _Organisations_CN.
LANGUAGE_BY_SUFFIX = {"CN": "zh", "MY": "ms", "TM": "ta"}

# Attributes that carry no meaning for matching or field-level merging.
SKIP_ATTRIBUTES = {"LDMS URI", "VIAF URI", "Wikidata URI", "Source"}

# Matches the delimiter the resolution prompt expects for multi-valued fields.
VALUE_DELIMITER = " | "

# Only the links canonical resolution walks are read. The export also carries
# UF, ENGtoCHI, BT, NT, RT, Successor and Predecessor -- 63% of all links --
# which nothing queries. `Use` reaches a preferred term; the *toENG links reach
# the English record that holds the fields. ENGtoCHI is deliberately excluded:
# following it would resolve an English match into a field-less one.
STORED_LINK_TYPES = {"Use", "CHItoENG", "MAYtoENG", "TAMtoENG"}


@dataclass
class Entity:
    uid: str
    name: str
    vocabulary: str
    entity_type: str
    language: str
    fields: dict[str, str] = field(default_factory=dict)
    # The record that actually receives updates. Equals uid when this entity is
    # already the preferred English form, which is true of ~40% of the export.
    canonical_uid: str = ""


CROSS_LANGUAGE = {"CHItoENG", "MAYtoENG", "TAMtoENG"}


@dataclass
class ParsedFile:
    entity_type: str
    snapshot: date
    entities: dict[str, Entity]
    links: list[tuple[str, str, str]]


def resolve_canonical(entities: dict[str, "Entity"],
                      links: list[tuple[str, str, str]]) -> None:
    """
    Set each entity's canonical_uid: the record an article's fact belongs on.

    At most two hops, and the two are mutually exclusive -- no entity carries
    both kinds of link:

      1. `Use` takes a non-preferred term to its preferred form. It never
         crosses languages.
      2. A cross-language link then takes a non-English record to the English
         one, which is the only side holding attribute fields.

    ENGtoCHI is deliberately never followed: it would resolve an English match
    into a field-less Chinese record. Verified across the full export as
    acyclic and never crossing file boundaries, so this is safe to compute per
    file during a partial import.
    """
    use: dict[str, str] = {}
    cross: dict[str, str] = {}
    for source, target, link_type in links:
        # A handful of entities (~0.1%) list several targets. Take the lowest
        # uid so a re-import is deterministic rather than order-dependent.
        table = use if link_type == "Use" else cross if link_type in CROSS_LANGUAGE else None
        if table is not None:
            if source not in table or target < table[source]:
                table[source] = target

    for uid, entity in entities.items():
        preferred = use.get(uid, uid)
        target = entities.get(preferred)
        if target is not None and target.language != "en":
            preferred = cross.get(preferred, preferred)
        entity.canonical_uid = preferred


def is_ours(filename: str) -> bool:
    """True for a full export of a vocabulary this pipeline holds."""
    match = FILENAME_RE.search(filename)
    return bool(match) and match.group("vocab").upper() in TYPE_BY_FILE


def parse_filename(filename: str) -> tuple[str, date]:
    """Return (entity_type, snapshot_date) inferred from a TTE filename."""
    match = FILENAME_RE.search(filename)
    if not match:
        raise ValueError(f"unrecognised TTE filename: {filename}")

    vocab = match.group("vocab").upper()
    if vocab not in TYPE_BY_FILE:
        raise ValueError(f"unknown authority file type: {vocab}")

    raw = match.group("snapshot")
    return TYPE_BY_FILE[vocab], date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))


def language_of(vocabulary: str) -> str:
    """Derive the record language from its vocabulary suffix."""
    suffix = vocabulary.rsplit("_", 1)[-1].upper()
    return LANGUAGE_BY_SUFFIX.get(suffix, "en")


def parse(path: Path | str, content: str | None = None) -> ParsedFile:
    """
    Parse one authority file.

    `content` allows parsing a file downloaded into memory; otherwise the
    path is read from disk.
    """
    path = Path(path)
    entity_type, snapshot = parse_filename(path.name)

    if content is None:
        content = path.read_text(encoding="utf-8-sig")

    entities: dict[str, Entity] = {}
    links: list[tuple[str, str, str]] = []

    for row in csv.DictReader(content.splitlines()):
        uid = (row.get("Key UID") or "").strip()
        name = (row.get("Key Descriptor") or "").strip()
        if not uid or not name:
            continue

        vocabulary = (row.get("Key Vocabulary") or "").strip()
        entity = entities.get(uid)
        if entity is None:
            entity = entities[uid] = Entity(
                uid=uid,
                name=name,
                vocabulary=vocabulary,
                entity_type=entity_type,
                language=language_of(vocabulary),
            )

        relationship = (row.get("Relationship Type") or "").strip()
        related_uid = (row.get("Related UID") or "").strip()
        related = (row.get("Related Descriptor") or "").strip()

        if related_uid:
            if related_uid != uid and relationship in STORED_LINK_TYPES:
                links.append((uid, related_uid, relationship))
        elif relationship and relationship not in SKIP_ATTRIBUTES and related:
            # Repeated attributes (several occupations, awards, ...) accumulate.
            existing = entity.fields.get(relationship)
            if existing is None:
                entity.fields[relationship] = related
            elif related not in existing.split(VALUE_DELIMITER):
                entity.fields[relationship] = existing + VALUE_DELIMITER + related

    resolve_canonical(entities, links)
    return ParsedFile(entity_type, snapshot, entities, links)
