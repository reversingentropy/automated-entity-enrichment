"""
Check a proposed description against what the record already says.

A TTE description is curated prose, sometimes years of it. The resolution model
is asked to make the smallest edit that carries the new fact, and this measures
whether it did -- because the prompt asking is not the same as the answer
complying. Two questions, and they have different answers when violated:

  Does it add anything?   If not, the edit is pure restyling. Dropped outright,
                          since discarding a change that carries no new fact
                          cannot lose information.
  Does it delete much?    Flagged, never dropped. A large deletion is sometimes
                          right -- a description can be wrong -- so that is a
                          person's call, not a threshold's.
"""

import difflib
import re

# Below this, the rewrite is not an edit of the existing description. Set from
# the observed split: every proposal that preserved the record's facts scored
# above it, and Teo Chee Hean's, which deleted his Navy career, his years as
# Deputy Prime Minister and every constituency he held, scored 0.08.
SURVIVES_FLOOR = 0.7

# An addition shorter than this is rewording -- "and", "1990, having", a moved
# comma -- not a fact the record was missing. A year is a fact whatever its
# length.
NEW_FACT_WORDS = 4
YEAR = re.compile(r"\b(1[89]|20)\d{2}\b")

# The style guide for descriptions (7.2): "limited to 3 to 5 sentences". Editing
# is told to keep every fact, so a description only ever grows; in the stored
# rewrites 12 in 100 records were already over the limit and 25 in 100 were
# after Gemini's rewrite. A change that pushes a description past it is held
# for a person, like a large deletion: never dropped, never decided by code.
SENTENCE_LIMIT = 5
_ABBREVIATION = re.compile(r"\b(Mr|Mrs|Ms|Dr|Prof|St|No|Co|Ltd|Pte|Inc|Jr|Sr|vs|approx)\.")


def split_sentences(text: str) -> list[str]:
    """A description's sentences. Titles and company suffixes ("Dr.", "Pte.") do not end one."""
    text = _ABBREVIATION.sub(r"\1<dot>", (text or "").strip())
    return [s.replace("<dot>", ".") for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", text) if s.strip()]


def sentence_count(text: str) -> int:
    """Sentences in a description."""
    return len(split_sentences(text))


def over_limit(old: str, new: str) -> bool:
    """
    Whether this change takes a description past the guide's limit: it ends
    longer than five sentences and longer than it began. A record already over
    the limit is not flagged for a change that adds nothing to its length.
    """
    after = sentence_count(new)
    return after > SENTENCE_LIMIT and after > sentence_count(old)


def _blocks(old: str, new: str):
    return difflib.SequenceMatcher(None, old.split(), new.split()).get_opcodes()


def survives(old: str, new: str) -> float:
    """
    How much of the existing text is still there, 0 to 1.

    Matched characters over the length of the OLD text. Not `ratio()`, which is
    2*matched/(len(old)+len(new)) and so scores a rewrite badly for *adding* a
    paragraph -- it flagged six proposals that deleted nothing whatsoever.
    """
    if not old:
        return 1.0
    matcher = difflib.SequenceMatcher(None, old, new)
    return sum(block.size for block in matcher.get_matching_blocks()) / len(old)


def additions(old: str, new: str) -> list[str]:
    """The passages the rewrite adds, rewording excluded."""
    words = new.split()
    out = []
    for tag, _, _, j1, j2 in _blocks(old, new):
        if tag not in ("insert", "replace"):
            continue
        text = " ".join(words[j1:j2])
        if len(text.split()) >= NEW_FACT_WORDS or YEAR.search(text):
            out.append(text)
    return out


def _keeps(old: str, new: str) -> bool:
    """Whether a new sentence keeps what an old one said: most of its words, in order."""
    a, b = re.findall(r"\w+", old.casefold()), re.findall(r"\w+", new.casefold())
    kept = sum(m.size for m in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())
    return not a or kept / len(a) >= SURVIVES_FLOOR


def sentence_edits(old: str, new: str) -> list[dict]:
    """
    A rewrite as whole sentences, so that two rewrites of one description can be put together.

    The model usually works a new fact into the last sentence ("from May 2025." became "from May 2025, and chairs
    an action team..."), and the added words alone are not a sentence: put after the description, they read
    "May 2025. 2025, and chairs". So each edit is one sentence and where it goes: it replaces existing sentence `at`
    (`to` is `at + 1`), or, when `at == to`, goes in before sentence `at`. A sentence that keeps most of an old one's
    words replaces it; any other new sentence goes in, and the old ones stay, since nothing in the record is lost
    unasked. Rewording that adds no fact is not an edit.
    """
    a, b = split_sentences(old), split_sentences(new)
    out = []

    def put(at: int, text: str):
        if text not in a and additions("", text):
            out.append({"at": at, "to": at, "text": text})

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("equal", "delete"):
            continue
        j = j1
        for i in range(i1, i2):
            match = next((m for m in range(j, j2) if _keeps(a[i], b[m])), None)
            if match is None:
                continue
            for m in range(j, match):
                put(i, b[m])
            if additions(a[i], b[match]):
                out.append({"at": i, "to": i + 1, "text": b[match]})
            j = match + 1
        for m in range(j, j2):
            put(i2, b[m])
    return out


def judge(old: str, new: str) -> tuple[str, float, list[str]]:
    """
    What to do with a proposed description: keep, drop or flag it.

    Returns the verdict, how much of the old text survives, and what the
    rewrite adds.
    """
    old, new = (old or "").strip(), (new or "").strip()
    if not old:
        return "keep", 1.0, [new] if new else []
    if old == new:
        return "drop", 1.0, []
    gained = additions(old, new)
    left = survives(old, new)
    if not gained:
        return "drop", left, []
    return ("flag" if left < SURVIVES_FLOOR else "keep"), left, gained
