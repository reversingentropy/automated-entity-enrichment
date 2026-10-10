"""
The two prompts for running the backfill on an internal model.

The nightly pipeline sends the model a sparse task and enforces the schema in
code afterwards. An internal model run by hand gets neither the injection nor
the enforcement, so these two files are assembled to stand alone: everything
the model needs is in the text, the output contract is one row per input, and
nothing is implied by omission.

    python -m src.backfill prompts [--out data/backfill/prompts]

Regenerate after editing anything under prompts/; do not edit the output.
"""

from pathlib import Path

from src.shared import field_rules

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"


def _read(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8").strip()


def relevance() -> str:
    """
    Relevance with a verdict for every row.

    The pipeline's prompt returns only the articles that pass, and code marks
    the rest. Here there is no code, so the model answers for every row:
    relevant or not, and why, in the row's own order. The criteria are the
    pipeline's, unchanged; only the input and output contract differ.
    """
    src = _read("relevance.txt")
    criteria = src[src.index("A knowledge base update is needed"):src.index("OUTPUT INSTRUCTIONS")].strip()
    return f"""RELEVANCE: DOES THIS ARTICLE CHANGE A RECORD IN SINGAPORE'S NATIONAL KNOWLEDGE BASE?

You are a relevance filter for the National Library Board's authority file
(TTE), which holds records for Singapore persons, organisations, buildings,
places, events, awards, programmes and laws. Each record carries a name,
dates, occupations, affiliations, awards and a short description.

You will be given one or more news articles. For each you have an id, a
title and, where available, a description. Some titles come from a URL and
are lower-case with punctuation missing ("st picks risking his life to save
hostages in 1974 laju hijacking"); read them as headlines. Titles may be in
English or Chinese.

Decide, for EVERY article, whether it likely reports a concrete change to
something the knowledge base records. Judge from the title and description
only; you do not have the body.

{criteria}

OUTPUT

Return a verdict for every input article, in the same order, as a JSON array.
One object per article, nothing omitted, no preamble, no markdown fences:

[
  {{"id": "<the id you were given>", "relevant": true,  "reason": "<one sentence: which entity, what changed>"}},
  {{"id": "<the id you were given>", "relevant": false, "reason": "<a few words: why not>"}}
]

Rules for the output:
  - Every input id appears exactly once. Non-relevant articles are included
    with relevant=false; never leave one out.
  - "reason" is always filled. For a relevant article, name the entity and the
    change ("Gerard Ee stepped down as chairperson of the Agency for
    Integrated Care"). For a non-relevant one, a short phrase is enough
    ("commentary", "foreign entity", "person only quoted", "future plan").
  - Write reasons in English whatever the language of the title.
  - When in doubt, relevant=false. This filter is meant to be precise rather
    than exhaustive; a later stage reads the full article and can afford to
    be generous, but an article passed here costs a full read.

If your system gives you one article at a time, return a JSON array with one
object in it.
"""


def relevance_second_pass() -> str:
    """
    Clean a set that already passed relevance, by naming what does not belong.

    A model under-lists whatever it is asked to list. Asked for the relevant
    articles among many irrelevant ones, it is precise and misses some; that
    is the nightly gate. Asked for the irrelevant ones among a set that is
    already half relevant, the same bias makes each removal safe and leaves
    the doubtful ones in. On the first pass the internal model was 42% precise
    against human labels; this pass exists to take out the other 58% without
    losing what is real.
    """
    src = _read("relevance.txt")
    criteria = src[src.index("A knowledge base update is needed"):src.index("OUTPUT INSTRUCTIONS")].strip()
    return f"""SECOND PASS: WHICH OF THESE DO NOT BELONG?

Every article below has already been judged likely to change a record in
Singapore's national knowledge base (TTE). About half of those judgements
were too generous. Your job is to name the ones that should NOT have passed.

For each article you have an id, a title and, where available, a
description, and the reason the first pass gave for keeping it. Read the
reason critically: it often describes something that is not a change to a
record at all.

{criteria}

WHAT TO NAME

Name an article as NOT relevant when you are confident of it: a commentary,
a programme or scheme with no named Singapore entity whose record would
change, a person merely quoted, a foreign entity, a plan not yet in effect,
or a first-pass reason that describes news rather than a change to a
person, organisation, building, place, event, award, programme or law.

Do not name an article you are unsure about. Leave it in. An article kept
by mistake costs one full read at the next stage; an article removed by
mistake is lost. Err toward leaving in.

OUTPUT

Return only the articles to remove, as a JSON array, no preamble, no
markdown fences:

[
  {{"id": "<the id you were given>", "reason": "<a few words: why it does not belong>"}}
]

Every id you return must be one you were given. If every article in the
batch should stay, return [].
"""


def extraction() -> str:
    """
    Extraction with the rules and vocabularies in the text.

    In the pipeline the occupations thesaurus and the controlled vocabularies
    are never sent; a bad value is rejected in code after the answer. Without
    that code the model has to be told, so both lists are included here. They
    cost about 1,500 tokens a call, which an internal model can afford, and the
    field brief is the same one the pipeline injects. The full 34 kB of field
    definitions stays out: injecting it made a model skim it and find fewer
    entities, not more.
    """
    task = field_rules.inject(_read("extraction.txt"))
    task = task[:task.rindex("Article:")].rstrip()
    return f"""{task}

---

CONTROLLED VOCABULARIES

Five fields take values only from fixed lists. Use a listed term exactly as
written, or omit the field and put the fact in "Description". Never invent a
term, never write a near-synonym, and never put a post or designation
("Chairperson", "CEO", "Minister for Health") in Occupation or Title.

A multi-valued field takes several listed terms separated by " | ", for
example "Lawyer | Politician". A value that mixes a listed term with an
unlisted one ("Lawyer | Chief Executive Officer") is wrong: keep the listed
term, drop the rest.

{_read("tte/occupations.txt")}

{_read("tte/vocabularies.txt").split(chr(10), 1)[1].strip()}

---

INPUT AND OUTPUT

You will be given one article at a time as plain text: a "Published:" line,
the title, then the body. The date matters: resolve every relative or
partial date in the article against it, as the DATES rule above says.

Every value except "Name", "evidence" and the original-language name is
written in English. "evidence" is one sentence copied verbatim from the
article in its own language; when that language is not English,
"evidence_en" carries a plain English translation of it.

YOUR ANSWER IS ONE JSON OBJECT AND NOTHING ELSE. Not an analysis, not a
list of entities to evaluate, not the article handed back. The first
characters of your answer are {{"entities": and the last is }}. No preamble,
no markdown fences, no text after the closing brace. If nothing in the
article warrants an update, the entire answer is {{"entities": []}}.

The shape, exactly:

{{
  "entities": [
    {{
      "entity_name": "...",
      "entity_name_en": "... or null",
      "entity_type": "PERSON | ORGANISATION | FACILITY | LOCATION | EVENT | AWARD | PROGRAMME | LEGAL_ACT",
      "summary": "one English sentence: who this is and what changed",
      "evidence": "one sentence copied verbatim from the article",
      "evidence_en": "English translation of evidence, or null",
      "fields": {{ "Field Name": "value" }},
      "confidence": "high",
      "role": "subject | mentioned"
    }}
  ]
}}

"summary" and "evidence" are required on every entity. An entity without
them cannot be reviewed and will be discarded.

Article:
"""


def resolution() -> str:
    """
    Resolution for an internal model, one article's entities per call.

    The pipeline's prompt, with the field rules, description style and
    notability guidance injected exactly as Job 3 injects them, the input
    described instead of pasted, and the same hard output anchor extraction
    needed: the model that wrote prose for 45% of extractions will do it
    here too unless told where the answer starts and ends.
    """
    task = field_rules.inject(_read("resolution.txt"))
    task = task[:task.rindex("INPUT")].rstrip().rstrip("=").rstrip()
    return f"""{task}

==================================================
INPUT AND OUTPUT
==================================================

You will be given one article's entities as a JSON array, exactly the
"article_entities" described above: each with its name, type, summary,
evidence, fields, and the candidate records retrieved for it with their
fields. Candidates are already canonical.

YOUR ANSWER IS ONE JSON OBJECT AND NOTHING ELSE. The first characters of
your answer are {{"resolutions": and the last is }}. No preamble, no
analysis, no markdown fences, no text after the closing brace. If no entity
in the article matches or needs flagging, the entire answer is
{{"resolutions": []}}; every omitted entity is understood to be new, and is
recorded as such.

ENTITIES:
"""


def write(directory: Path | str) -> list[Path]:
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    files = []
    for name, text in (("relevance.txt", relevance()),
                       ("relevance-second-pass.txt", relevance_second_pass()),
                       ("extraction.txt", extraction()),
                       ("resolution.txt", resolution())):
        path = out / name
        path.write_text(text, encoding="utf-8")
        files.append(path)
    # The schemas, for a system that can enforce one.
    import json
    from src.shared.models import ExtractionResponse, ResolutionResponse
    for name, model in (("extraction.schema.json", ExtractionResponse),
                        ("resolution.schema.json", ResolutionResponse)):
        path = out / name
        path.write_text(json.dumps(model.model_json_schema(), indent=2), encoding="utf-8")
        files.append(path)
    return files
