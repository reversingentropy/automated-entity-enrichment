"""
One description addition per record, from every article about it (docs/descriptions.md).

Job 3 reads each article alone, so four articles about one person proposed four descriptions: the same fact in
four wordings, and the desk showed them all. For a record that two or more articles proposed description text
for, one model call is given TTE's description and each article's new sentences, numbered as the card numbers its
sources, and writes the sentences to add, each with the articles that state it. Code then checks the answer
(`checked`) and only what passes is stored, in `description_drafts`, which the card builder reads.

Article pages are not kept (sql/21_drop_unused.sql), so a sentence is traced to what was recorded from each article
it cites: its headline, its evidence quote, and the sentences Job 3 proposed from the full page.
"""

import re

from pydantic import BaseModel

TABLE = "description_drafts"


class Sentence(BaseModel):
    text: str
    sources: list[int]


class Value(BaseModel):
    value: str
    sources: list[int]


class Disagreement(BaseModel):
    about: str
    values: list[Value]


class Correction(BaseModel):
    quote: str
    replace_with: str
    sources: list[int]


class Combined(BaseModel):
    add: list[Sentence]
    disagreements: list[Disagreement]
    corrections: list[Correction]
    left_out: list[Sentence]


class RecordCombined(Combined):
    key: str


class CombineBatch(BaseModel):
    records: list[RecordCombined]


PROMPT = """You are helping a librarian update one record in a national authority file.

Below is the record's current description, and new sentences that {n} news articles proposed for it. Each article
was read on its own, so they repeat each other in different words, and some repeat what the description already says.

Write the sentences to ADD to the end of the current description. Rules:
1. Add only facts that the current description does not already state. Never repeat or reword it.
2. Each fact once, however many articles gave it. Use the most specific wording: dates, posts, names in full.
   Every date in full, with its year. A date an article gives without a year, or "this year", is in the year the
   article was published.
3. Facts only: a post, a date, an appointment, an award, an event. No praise or characterisation ("distinguished",
   "renowned", "prominent", "veteran", "well-known", "respected", "leading").
4. Use only what the articles say. No fact, date or name that is not in the articles below.
5. After each sentence, list the article numbers that state its facts, including its dates and numbers. List an
   article only if it states them.
6. If articles give different values for the same fact (a different year, date or post), do not choose: write the
   sentence without that value, and report it under disagreements with each value and its articles.
7. If the articles show that words in the current description are now wrong (a post it says he still holds),
   give those words exactly as they appear under corrections, with the words to put in their place and the
   articles that show it. Do not change the description yourself.
8. At most {room} sentences. Put any further facts, least important first, under left_out.
9. Write in the style of the current description: plain, third person, past or present tense as it uses.

Current description:
{tte}

Articles:
{articles}
"""

BATCH = """

---

The above is the instruction for ONE record. Below are {n} records, each with its key, its current description,
its room and its articles. Answer every record by the same rules, each under its key.

{records}
"""

FILLER = re.compile(r"\b(distinguished|renowned|prominent|veteran|well-known|respected|leading|esteemed|illustrious|"
                    r"celebrated|notable|eminent|acclaimed|stalwart)\b", re.I)
NUMBER = re.compile(r"\d[\d,.]*\d|\d")
MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
# "on 1 September" or "September 1" with no year after it
NO_YEAR = re.compile(rf"\b(?:\d{{1,2}} {MONTH}|{MONTH} \d{{1,2}})\b(?!,? \d{{4}})")
_CAPITAL = re.compile(r"\b[A-Z][A-Za-z'’&-]+\b")
_PLAIN = {"He", "She", "It", "They", "In", "The", "On", "At", "From", "As", "His", "Her", "Its", "A", "An", "And",
          "After", "Before", "Since", "Until", "With", "For", "Of", "To"}
_SENTENCE_END = re.compile(r"[.!?。](?:\s|$)")
_WORD = re.compile(r"[a-z0-9]+")
_SMALL = {"he", "she", "it", "they", "his", "her", "its", "their", "is", "was", "are", "were", "be", "been", "has",
          "have", "had", "a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or", "as", "by", "with", "from",
          "also", "who", "which", "that", "this", "one", "s"}


def room(tte: str, limit: int = 5) -> int:
    """How many sentences fit under the style guide's five; at least one, as a record at the limit still gets one."""
    return max(1, limit - len(_SENTENCE_END.findall(tte.strip() + " ")))


def articles_block(record: dict) -> str:
    return "\n\n".join(f"[{s['n']}] {s['outlet']}, published {s.get('date') or 'date unknown'}: {s['title']}\nEvidence: {s['quote']}\nProposed sentences:\n"
                       + "\n".join("- " + t for t in s["new_sentences"]) for s in record["sources"])


def prompt_for(record: dict) -> str:
    return PROMPT.format(n=len(record["sources"]), room=room(record["tte"]), tte=record["tte"],
                         articles=articles_block(record))


def batch_prompt(records: list[dict]) -> str:
    """One prompt for many records, for a run by hand in AI Studio."""
    head = PROMPT.split("Current description:")[0].replace("{n}", "several").replace(
        "At most {room} sentences", "At most the record's room in sentences")
    blocks = "\n\n=====\n\n".join(f"KEY: {r['key']}\nRoom: {room(r['tte'])} sentences\nCurrent description:\n{r['tte']}\n\n"
                                  f"Articles:\n{articles_block(r)}" for r in records)
    return head + BATCH.format(n=len(records), records=blocks)


def records_from_cards(cards: list[dict]) -> list[dict]:
    """
    Every description note two or more articles gave sentences to, as the combine step's input. Sources are numbered
    as the card numbers them, so the desk shows the answer's numbers as they are.
    """
    out = []
    for card in cards:
        for ch in card["changes"]:
            said = ch.get("said")
            if ch["field"] != "Description" or not said:
                continue
            links = {link for ls in said.values() for link in ls}
            if len(links) < 2:
                continue
            sources = []
            for i, s in enumerate(card["sources"], 1):
                sents = [t for t, ls in said.items() if s["link"] in ls]
                if sents and not any(x["link"] == s["link"] for x in sources):
                    sources.append({"n": i, "link": s["link"], "outlet": (s["link"].split("/") + ["", "", ""])[2],
                                    "date": s.get("date") or "", "title": s.get("article") or "",
                                    "quote": s.get("quote") or "",
                                    "notes": " ".join([s.get("says") or ""] + [f["value"] for f in s.get("fields") or []]),
                                    "new_sentences": sents})
            out.append({"key": draft_key(card, ch), "name": card["entity"], "tte": " ".join(ch.get("existing") or []),
                        "sources": sources})
    return out


def draft_key(card: dict, ch: dict) -> str:
    """The record and exactly which articles' sentences: a new article about it makes a new key, and a new draft."""
    said = ch.get("said") or {}
    links = sorted({link for ls in said.values() for link in ls})
    pids = sorted({int(s["pid"]) for s in card["sources"] if s["link"] in links})
    return f"{card['key']}|{','.join(map(str, pids))}"


def _material(source: dict) -> str:
    """
    What the extraction step recorded from an article, and the year it was published (an article's "Sept 1" is that
    year's). Not Job 3's proposed sentences: they are what is being checked, and a year Job 3 made up would pass.
    """
    return " ".join([source.get("title") or "", source.get("quote") or "", source.get("notes") or "",
                     (source.get("date") or "")[:4]])


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in NUMBER.findall(text)}


def _names(text: str) -> list[str]:
    """Capitalised words, less months and each sentence's first word ("Following his retirement")."""
    firsts = {m.group(1) for m in re.finditer(r"(?:^|[.!?]\s+)([A-Za-z'’&-]+)", text)}
    return [w for w in _CAPITAL.findall(text) if w not in _PLAIN and w not in firsts and not re.fullmatch(MONTH, w)]


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower())) - _SMALL


def _redundant(add: list[dict], tte: str, dropped: list[str]) -> list[dict]:
    """
    Overlap the model left. A sentence with no word TTE lacks says nothing new, and goes. A sentence whose every word
    is in another added sentence is the same fact in fewer words: it goes, and its articles move to the other. A
    sentence with one new word ("stepped down") stays: that word can be the whole fact.
    """
    have = _words(tte)
    out = []
    for s in add:
        if _words(s["text"]) <= have:
            dropped.append(f"nothing the description lacks: {s['text']}")
        else:
            out.append(s)
    for s in list(out):
        wider = next((o for o in out if o is not s and _words(s["text"]) <= _words(o["text"])
                      and (len(_words(s["text"])) < len(_words(o["text"])) or out.index(o) < out.index(s))), None)
        if wider:
            wider["sources"] += [x for x in s["sources"] if x not in wider["sources"]]
            out.remove(s)
            dropped.append(f"inside another added sentence: {s['text']}")
    return out


def checked(record: dict, got: Combined) -> dict:
    """
    The answer as stored: sources as links, and only what passed.

    A sentence is dropped when it repeats the description, carries filler, or gives a day and month with no year. An
    article is taken off a sentence when what was recorded from it lacks one of the sentence's numbers or names; a
    sentence left with none is dropped. Then overlap goes: see _redundant. `ok` is false when nothing to add survived, and the card then shows each
    article's own sentences instead.
    """
    by = {s["n"]: s for s in record["sources"]}
    tte = record["tte"]
    dropped = []

    def stating(text: str, cited: list[int]) -> list[str]:
        """The cited articles whose record holds every number and name in the text."""
        keep = []
        for n in dict.fromkeys(cited):
            src = by.get(n)
            if src is None:
                continue
            m = _material(src) + " " + tte
            if _numbers(text) - _numbers(m) or [w for w in _names(text) if w.lower() not in m.lower()]:
                continue
            keep.append(src["link"])
        return keep

    def sentence(s: Sentence) -> dict | None:
        text = " ".join(s.text.split())
        if not text:
            return None
        if text in tte:
            dropped.append(f"repeats the description: {text}")
            return None
        if FILLER.search(text):
            dropped.append(f"filler: {text}")
            return None
        if NO_YEAR.search(text):
            dropped.append(f"a date with no year: {text}")
            return None
        keep = stating(text, s.sources)
        if not keep:
            dropped.append(f"no article it cites states it: {text}")
            return None
        return {"text": text, "sources": keep}

    add = _redundant([x for x in (sentence(s) for s in got.add) if x], tte, dropped)
    more = _redundant([x for x in (sentence(s) for s in got.left_out) if x], tte + " " + " ".join(s["text"] for s in add),
                      dropped)
    disagree = []
    for d in got.disagreements:
        values = [{"value": v.value, "sources": stating(v.value, v.sources)} for v in d.values]
        values = [v for v in values if v["sources"]]
        if len(values) > 1:
            disagree.append({"about": d.about, "values": values})
    fixes = []
    for c in got.corrections:
        srcs = [by[n]["link"] for n in c.sources if n in by]
        if c.quote and c.quote in tte and srcs and not FILLER.search(c.replace_with):
            fixes.append({"quote": c.quote, "with": c.replace_with, "sources": srcs})
        else:
            dropped.append(f"correction not in the description or unsourced: {c.quote}")
    return {"ok": bool(add), "add": add, "left_out": more, "disagreements": disagree, "corrections": fixes,
            "dropped": dropped}


def stored(client=None) -> dict[str, dict]:
    """Every stored draft by key; none when the table is not there yet (sql/22_description_drafts.sql)."""
    from src.shared.pagination import fetch_all
    from src.shared.supabase_client import get_client
    try:
        client = client or get_client()
        rows = fetch_all(lambda: client.from_(TABLE).select("key,combined"), order="key")
    except Exception:
        return {}
    return {r["key"]: r["combined"] for r in rows}


def save(record: dict, combined: dict, model: str, client=None) -> None:
    from src.shared.supabase_client import get_client
    (client or get_client()).from_(TABLE).upsert(
        {"key": record["key"], "record": record["key"].split("|")[0], "combined": combined, "model": model}).execute()
