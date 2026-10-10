"""
Build review cards straight from the Supabase tables.

Every field on a card is read live from `candidate_matches`,
`extracted_entities`, `article` and `entities` -- nothing is transcribed or
cached. Re-run it after any pipeline run and the cards reflect the database as
it stands.

The shape exists to make one question answerable at a glance: is the entity in
the news the same as the record we hold? Both sides are therefore reduced to
the SAME three facets, in the same order, so the difference is visible rather
than something the reader has to find in a paragraph.
"""

import difflib
import html
import json
import re
from pathlib import Path

from src.shared.description import (
    SENTENCE_LIMIT, SURVIVES_FLOOR, additions, judge, over_limit, sentence_count, sentence_edits,
    split_sentences, survives)
from src.shared.names import (
    LINKED_FIELDS, YEAR, house, plain, renamed, tries_for)
from src.shared.pagination import fetch_all
from src.shared.supabase_client import column_exists, get_client

CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")
LATIN = re.compile(r"^[\x00-\x7F\u00C0-\u024F\s.,'’()-]+$")

# Fields worth showing when asking "is this the same entity", most
# identifying first. Shown under their real names rather than an invented
# abstraction, so the reviewer sees which field carries what.
# Written exactly as TTE stores them: "Affiliations" and "Birth Year" matched
# nothing, so neither side of a card ever showed an affiliation or a birth
# year, and a reviewer asked to add an affiliation could not see that the
# record had none.
IDENTIFYING = (
    "Title", "Occupation", "Feature Type",
    "Affiliations(groupName)", "Parent Organisation", "Awards",
    "Nationality", "Country", "Street Address",
    "Birth Year (yyyy)", "Death Year (yyyy)",
    "Description", "SN",
)

# A candidate this far below the best one is not a competing answer, it is
# noise from trigram matching. Showing it makes the choice look harder than it
# is: at 1.00 against 0.33, there is one candidate, not three.
PLAUSIBLE_MARGIN = 0.25

VERB = {"APPEND": "Add to", "MERGE": "Rewrite", "REPLACE": "Replace",
        "INSERT_RELATION": "Link"}

# A rewrite keeping less than this is not really a merge. One proposal cut Teo
# Chee Hean's 636-character description to 405, deleting his Navy career, his
# years as Deputy Prime Minister and every constituency he held, while still
# labelled MERGE -- so the card says how much survives rather than leaving the
# reviewer to compare two long paragraphs by eye.
REWRITE_WARN_BELOW = SURVIVES_FLOOR


def diff_parts(old: str, new: str) -> list[dict]:
    """
    The change between two passages, as a run of kept, added and removed parts.

    Lets a card show what actually changed instead of two near-identical walls
    of text, which is the only way a reviewer can check a rewrite.
    """
    before, after = old.split(), new.split()
    matcher = difflib.SequenceMatcher(None, before, after)
    parts = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            parts.append({"op": "same", "text": " ".join(before[i1:i2])})
            continue
        # One clause worked into a sentence comes back as several opcodes --
        # "and" out, "2015." out, "2015, and Chairman of..." in -- which reads
        # as four separate edits instead of the single insertion it is. Runs of
        # change are therefore merged, keeping removed text before added.
        for op, text in (("out", " ".join(before[i1:i2])),
                         ("in", " ".join(after[j1:j2]))):
            if not text:
                continue
            if parts and parts[-1]["op"] == op:
                parts[-1]["text"] += " " + text
            else:
                parts.append({"op": op, "text": text})
    return parts


def edits_in(parts: list[dict]) -> tuple[list[str], list[dict]]:
    """
    What a rewrite does to the existing text: the runs it removes outright,
    and the runs it replaces, each with what replaces it.

    Every removal is listed however short. Thirteen of fourteen rewrites on
    one deck removed only a word or two ("2015." became "2015, and ..."),
    below the four-word floor the list once had, so the screen said "nothing
    removed" over a text that had been changed.
    """
    drops, subs = [], []
    for i, part in enumerate(parts):
        if part["op"] != "out":
            continue
        was = " ".join(part["text"].split())
        nxt = parts[i + 1] if i + 1 < len(parts) else None
        if nxt and nxt["op"] == "in":
            subs.append({"was": was, "now": " ".join(nxt["text"].split())})
        else:
            drops.append(was)
    return drops, subs


# How much of the existing text survives a rewrite. Lives in shared/ because
# Job 3 applies the same measurement when it decides what to store.
kept_ratio = survives

FLAG_WHY = {
    "FLAG_AMBIGUOUS": "Two records could be this entity",
    "FLAG_DB_DUPLICATE": "The knowledge base may hold duplicates",
    "RE_QUERY_REQUIRED": "May exist under another name",
    "OMITTED_EXACT": "The model gave no answer for this name; the record carries it",
}

# Multi-valued authority fields are stored pipe-separated.
DELIMITER = " | "


# Neither side of a comparison, for different reasons: names are the identity
# question the card has already asked, and these carry no judgement a reviewer
# could make.
NOT_COMPARED = {
    "Name", "Name (DisplayName)", "Name (LCNA)", "Name (Chinese)",
    "Image Link", "DBpedia URI", "SN", "Qualifier",
}


def _values(text) -> list[str]:
    return [v.strip() for v in str(text or "").split(DELIMITER) if v.strip()]


CJK = re.compile(r"[㐀-鿿豈-﫿]")

# A comma straight after a closing bracket, before the next name: "X (中文), Y (中文)".
# That is a list the model joined with commas instead of the delimiter. A name with a
# comma inside it ("Tan, Tony") has no bracket before the comma, so it survives.
_JOINED_LIST = re.compile(r"(?<=[)）])\s*[,，、]\s*(?=[A-Z㐀-鿿])")

# Fields TTE records in English whatever language the article was in. The street
# address rule asks for "<street number> <street name>, <#unit> <building name>", spelled
# out; no field rule lists Chinese for it. A cataloguer should confirm any other field.
ENGLISH_ONLY = {"Street Address"}

PROSE = {"Description", "Achievements"}


def _gloss(value: str) -> str:
    """The English in brackets after an original-language name, else the value itself."""
    m = re.search(r"\(([^()]*[A-Za-z][^()]*)\)\s*$", value)
    return (m.group(1) if m else value).strip()


def news_values(text) -> list[str]:
    """What an article's field value holds, one entry per name, including a list joined with commas."""
    out = []
    for v in _values(text):
        out.extend(p.strip() for p in _JOINED_LIST.split(v) if p.strip())
    return out


def clean_news_value(field: str, value) -> str:
    """
    A model's value for a field, put the way TTE holds it.

    A list is one entry per delimiter, however the model joined it. An English-only field
    keeps the English: "裕廊大会堂路 (Jurong Town Hall Road)" is "Jurong Town Hall Road", and a
    value with no English in it is nothing to offer.
    """
    if field in PROSE:
        return str(value or "")
    entries = news_values(value)
    if field in ENGLISH_ONLY:
        entries = [_gloss(v) for v in entries if not CJK.search(_gloss(v))]
    return DELIMITER.join(entries)


def _covered(field: str, value: str, held: list[str]) -> bool:
    """Is this value already among what the record holds, in either of its two languages?"""
    lower = {v.casefold() for v in held}
    if value.casefold() in lower or _gloss(value).casefold() in lower:
        return True
    if field == "Street Address":    # the model often gives only the street: "Margaret Drive" is in "53 Margaret Drive"
        street = _gloss(value).casefold()
        return bool(street) and any(street in v.casefold() for v in held)
    return False


def delta(news: dict | None, record: dict | None) -> list[dict]:
    """
    What the article would add to a record, field by field.

    Two in five matches propose no change at all, because the authority record
    already holds the fact -- the record carried the 2026 award before the
    article reporting it was read. Without this the reviewer meets "Confirm
    match" above an empty space, and cannot tell whether that means "nothing
    is new" or "the model gave up". Stating "already recorded" against the
    field is the difference between a no-op and an unexplained blank.

    Computed per candidate record, so switching the answer to "which record is
    this?" re-answers "and what would that change?" too.
    """
    news, held = news or {}, (record or {})
    out = []
    for field, value in news.items():
        if field in NOT_COMPARED or not str(value).strip():
            continue
        value = clean_news_value(field, value)
        if not value.strip():
            continue
        have = str(held.get(field, "")).strip()
        # Prose is one value; every other field is a pipe-separated set, so a
        # fact can already be recorded among several others.
        if field == "Description":
            state = "same" if not have or have == str(value).strip() else "differs"
            if not have:
                state = "new"
            fresh = "" if state == "same" else str(value).strip()
        else:
            mine, theirs = _values(value), _values(have)
            missing = [v for v in mine if not _covered(field, v, theirs)]
            fresh = DELIMITER.join(missing)
            state = "new" if not theirs else ("same" if not missing else "extra")
        out.append({"field": field, "news": str(value).strip(),
                    "have": have, "fresh": fresh, "state": state})
    rank = {"new": 0, "extra": 1, "differs": 2, "same": 3}
    out.sort(key=lambda d: (rank[d["state"]], d["field"]))
    return out


def result_of(strategy: str, existing: list[str], value: str) -> str:
    """
    What the field would hold afterwards.

    The one question a reviewer is actually asking is whether approving
    overwrites what is there. Naming the operation does not answer it; showing
    the resulting value does.
    """
    if strategy == "APPEND":
        return DELIMITER.join(existing + [value]) if existing else value
    return value


def derived_changes(delta_rows: list[dict], covered: set[str]) -> list[dict]:
    """
    Facts the article carries that the record lacks and the model did not
    propose.

    These are offered, never assumed: the model saw the same fields and chose
    not to propose them, so they arrive unticked. Description is deliberately
    excluded -- the article's own summary is news-derived prose, and swapping a
    curated description for it is exactly the loss the pipeline exists to avoid.
    """
    out = []
    for row in delta_rows:
        if row["field"] in covered or row["field"] == "Description":
            continue
        if row["state"] not in ("new", "extra"):
            continue
        have = _values(row["have"])
        out.append({
            "field": row["field"],
            "verb": "Add to" if have else "Add",
            "strategy": "APPEND",
            "adding": row["fresh"],
            "existing": have,
            "result": result_of("APPEND", have, row["fresh"]),
            "derived": True,
        })
    return out




def _same_fact(value: str) -> str:
    """Two wordings of one fact, reduced to what they share: letters, no year."""
    return " ".join(re.sub(r"[^a-z\u4e00-\u9fff ]+", " ", YEAR.sub("", value.lower())).split())


# Words too common to say two sentences are about the same thing.
_COMMON = frozenset("the and for with from that this was has have had his her its into also are "
                    "were been will who which their they them than then there she him".split())


def _content_words(sentence: str) -> set[str]:
    return {w for w in re.findall(r"[\w'-]+", sentence.casefold()) if len(w) > 2 and w not in _COMMON}


def near_same(a: str, b: str) -> bool:
    """
    Two sentences saying one thing in different words: most of the shorter
    one's content words are in the longer. The Straits Times and Lianhe
    Zaobao on Goh Yihan's appointment gave two such sentences, and both went
    into one description. Two different appointments ("Minister for Trade"
    and "Minister for Health") share too little to count.
    """
    wa, wb = _content_words(a), _content_words(b)
    small = min(len(wa), len(wb))
    return small >= 3 and len(wa & wb) / small >= 0.75


def _fact_tokens(text: str) -> set[str]:
    """The words worth matching a fact on: content words, and each Chinese character."""
    return _content_words(text) | set(re.findall(r"[一-鿿]", text))


def _said(sentence: dict) -> str:
    return f"{sentence.get('quote') or ''} {sentence.get('original') or ''}"


def quote_for(change: dict, names: list[str], own: dict, others: list[dict]) -> dict | None:
    """
    The sentence from the same article that best backs one change, when it is
    not the person's own.

    Extraction keeps one evidence sentence per person. Anita Fam had two facts
    in two sentences, two awards in one and her new chairmanship in the other,
    and extraction filed the second under Gerard Ee, whom the article is about.
    Her card then quoted the awards sentence under the chairmanship too, so a
    reviewer checking the change found nothing that supported it. The other
    people's sentences from the same article are candidates, but only those
    that name this person: a sentence about someone else proves nothing about
    her. Each sentence is {"quote", "original"}. None when her own is as good.
    """
    target = _fact_tokens(" ".join(change.get("adds") or [change["adding"]]))
    if not target:
        return None

    def score(sentence: dict) -> float:
        return len(target & _fact_tokens(_said(sentence))) / len(target)

    own_score = score(own)
    best, best_score = None, own_score
    for other in others:
        if not any(n and n.casefold() in _said(other).casefold() for n in names):
            continue
        s = score(other)
        if s > best_score:
            best, best_score = other, s
    if best is None or best_score < 0.5 or best_score - own_score < 0.2:
        return None
    return {"quote": best.get("quote") or "", "original": best.get("original") or ""}


def collapse(changes: list[dict]) -> list[dict]:
    """
    One note per fact, however many clippings carried it.

    Two articles reporting the same award produce two proposals, and if the
    strings differ by a year in brackets they used to be two questions. A
    second source is evidence, not a second question: the guidelines want two
    sources for a change, so the card should say "two clippings say this" on
    one note rather than ask twice. When the sources disagree on the year the
    note says so instead, and offers both; the reviewer picks, never the code.
    """
    groups: dict[tuple, list[dict]] = {}
    for ch in changes:
        if ch["field"] == "Description" and ch["strategy"] in ("MERGE", "REPLACE"):
            # Two articles each rewriting the description are not two
            # rewrites to choose between: they are two sets of sentences to
            # add. One note, the existing text kept whole, every clipping's
            # additions after it.
            key = ("Description", "MERGE", "*")
        elif ch["strategy"] == "REPLACE":
            # A scalar field with two different values is one question with
            # two answers, not two questions.
            key = (ch["field"], "REPLACE", "*")
        elif ch["strategy"] == "APPEND":
            # Two articles adding to one list field are one note carrying
            # every value either named: "SPH Media Trust | SPH Media
            # Holdings" from one and "SPH Media Trust" from the other were
            # two screens, the second a subset of the first, and two rows
            # on the sheet for a cataloguer to reconcile. Values that are
            # the same fact with different years are split out below and
            # kept as a question.
            key = (ch["field"], "APPEND", "*")
        else:
            key = (ch["field"], ch["strategy"], _same_fact(ch["adding"]))
        groups.setdefault(key, []).append(ch)
    out = []
    for key, group in list(groups.items()):
        if key[0] == "Description" and key[2] == "*" and len(group) > 1:
            out.append(_combined_rewrite(group))
            continue
        if key[1] == "APPEND":
            out.extend(_combined_additions(group))
            continue
        best = max(group, key=lambda ch: len(ch["adding"]))
        merged = dict(best)
        merged["supporters"] = sorted({ch.get("from") for ch in group if ch.get("from")})
        merged["variants"] = sorted({ch["adding"] for ch in group} - {best["adding"]})
        # Which source gave which wording, so a disagreement can be settled
        # by the source and not only by the string.
        merged["saidBy"] = [{"value": ch["adding"], "from": ch.get("from") or ""} for ch in group]
        # A disagreement needs two sources. One description with four years
        # in it, or one value naming two awards, is not a conflict, though
        # the year rule once said so and put "1 articles disagree" on a card.
        if len(group) > 1:
            # A source that names no year does not disagree with one that does.
            facts = {_same_fact(ch["adding"]) for ch in group}
            years = {y.strip("()") for ch in group for y in YEAR.findall(ch["adding"])}
            merged["conflict"] = len(facts) > 1 or len(years) > 1
        else:
            merged["conflict"] = False
        out.append(merged)
    return out


def _combined_additions(group: list[dict]) -> list[dict]:
    """
    One note per list field with every value any source named, and a
    separate question for a value the sources give different years for.
    """
    clusters: dict[str, list[dict]] = {}
    for ch in group:
        for value in _values(ch["adding"]):
            clusters.setdefault(_same_fact(value), []).append({**ch, "adding": value})
    # Two articles word one achievement differently ("the first Singaporean to
    # win a gold medal at the Paralympic Games in Beijing in 2008" and "became
    # the first Singaporean to win a Paralympic gold medal at the 2008 Games in
    # Beijing"); same_fact keeps them apart, so one record's Achievements came
    # as five rows. Long values that say one thing are one value.
    pooled: list[list[dict]] = []
    for members in clusters.values():
        best = max(members, key=lambda m: len(m["adding"]))
        home = next((c for c in pooled if len(best["adding"].split()) >= 6
                     and near_same(max(c, key=lambda m: len(m["adding"]))["adding"], best["adding"])), None)
        if home is None:
            pooled.append(list(members))
        else:
            home.extend(members)
    union, out = [], []
    for members in pooled:
        years = {y.strip("()") for m in members for y in YEAR.findall(m["adding"])}
        if len(years) > 1:
            best = max(members, key=lambda m: len(m["adding"]))
            note = dict(best)
            note.update({
                "result": result_of("APPEND", best["existing"], best["adding"]),
                "supporters": sorted({m.get("from") for m in members if m.get("from")}),
                "variants": sorted({m["adding"] for m in members} - {best["adding"]}),
                "saidBy": [{"value": m["adding"], "from": m.get("from") or ""} for m in members],
                "conflict": True,
            })
            out.append(note)
            continue
        best = max(members, key=lambda m: len(m["adding"]))
        union.append({"value": best["adding"],
                      "sources": sorted({m.get("from") for m in members if m.get("from")}),
                      "variants": sorted({m["adding"] for m in members} - {best["adding"]})})
    if union:
        first = group[0]
        adding = DELIMITER.join(v["value"] for v in union)
        note = dict(first)
        note.update({
            "adding": adding,
            "result": result_of("APPEND", first["existing"], adding),
            "supporters": sorted({ch.get("from") for ch in group if ch.get("from")}),
            "variants": sorted(w for v in union for w in v["variants"]), "conflict": False,
            "saidBy": [{"value": v["value"], "from": f} for v in union for f in v["sources"]],
            "perValue": union,
        })
        out.insert(0, note)
    return out


def _combined_rewrite(group: list[dict]) -> dict:
    """
    One description note carrying every clipping's new facts.

    Each rewrite is taken as whole sentences (`sentence_edits`): a sentence one
    clipping lengthened replaces the old one where it stands, and a sentence it
    added goes where it put it. The added words alone are not a sentence: Chee
    Hong Tat's two clippings, one working an action team into his last sentence
    and one adding a sentence of its own, became "from May 2025. 2025, and
    chairs an action team...", and the second clipping's sentence was held back.
    """
    first = group[0]
    before = " ".join(first["existing"]) if first["existing"] else ""
    base = split_sentences(before)
    edits: list[dict] = []
    origin: dict[str, str] = {}
    for ch in group:
        for e in sentence_edits(before, ch["adding"]):
            if e["text"] in before or any(e["text"] == x["text"] for x in edits):
                continue
            edits.append(e)
            origin[e["text"]] = ch.get("from") or ""
    # Two clippings changing the same sentence, or near-identical sentences
    # from different sources, are one edit in two wordings: the one carrying
    # the most the description lacks is used, the others offered in its place.
    # Not the longest: a lengthened sentence is long with the old words, and
    # Chan Yeng Kit's "later became Chief Executive Officer of SPH Media" was
    # once chosen over "In July 2024, he was appointed chief executive officer
    # of SPH Media", which has the date.
    def same_edit(a: dict, b: dict) -> bool:
        both_change = a["at"] < a["to"] and b["at"] < b["to"]
        if both_change and a["at"] < b["to"] and b["at"] < a["to"]:
            return True
        return origin[a["text"]] != origin[b["text"]] and near_same(a["text"], b["text"])
    clusters: list[list[dict]] = []
    for e in edits:
        home = next((c for c in clusters if any(same_edit(w, e) for w in c)), None)
        if home is None:
            clusters.append([e])
        else:
            home.append(e)
    # A famous record collects sentences from dozens of articles: Lawrence Wong's
    # note carried thirteen, Lee Hsien Loong's nine, and the nine heaviest
    # records took more than half of one reviewer's time. The style guide allows
    # three to five sentences, so the note carries only as many new sentences as
    # fit under that limit, best supported first (a sentence several articles
    # carried outranks one a single article did), and the rest are shown as
    # held back, not dropped: the reviewer can still add them. A lengthened
    # sentence adds none, so it always fits.
    had = _fact_tokens(before)
    best_of = [max(c, key=lambda e: (len(_fact_tokens(e["text"]) - had), len(e["text"]))) for c in clusters]
    support = [len({origin[e["text"]] for e in c}) for c in clusters]
    room = max(1, SENTENCE_LIMIT - sentence_count(before))
    keep, used = set(), 0
    for i in sorted(range(len(clusters)), key=lambda i: (-support[i], i)):
        n = max(0, sentence_count(best_of[i]["text"]) - (best_of[i]["to"] - best_of[i]["at"]))
        if keep and n and used + n > room:
            continue
        keep.add(i)
        used += n
    kept, alts, held = [], [], []
    for i, cluster in enumerate(clusters):
        best = best_of[i]
        if i not in keep:
            held.append(best["text"])
            continue
        kept.append(best)
        if len(cluster) > 1:
            alts.append({"wordings": [best["text"]] + [e["text"] for e in cluster if e is not best]})
    # The description with the kept edits in place.
    inserts: dict[int, list[str]] = {}
    changes: dict[int, dict] = {}
    for e in kept:
        if e["to"] > e["at"]:
            changes[e["at"]] = e
        else:
            inserts.setdefault(e["at"], []).append(e["text"])
    parts, i = [], 0
    while True:
        parts += inserts.get(i, [])
        if i >= len(base):
            break
        if i in changes:
            e = changes[i]
            parts.append(e["text"])
            for k in range(i + 1, e["to"]):
                parts += inserts.get(k, [])
            i = e["to"]
        else:
            parts.append(base[i])
            i += 1
    value = " ".join(parts).strip()
    diff = diff_parts(before, value)
    drops, subs = edits_in(diff)
    merged = dict(first)
    merged.update({
        "adding": value, "result": value, "strategy": "MERGE", "verb": VERB["MERGE"],
        "adds": [e["text"] for e in kept], "drops": drops, "subs": subs, "diff": diff,
        "kept": round(kept_ratio(before, value), 2) if before else 1.0,
        "overEdit": False,
        "overLimit": over_limit(before, value), "sentences": sentence_count(value),
        "supporters": sorted({ch.get("from") for ch in group if ch.get("from")}),
        "variants": [], "conflict": False, "alts": alts, "held": held,
    })
    return merged


def identifying(fields: dict | None) -> list[dict]:
    """The fields that establish who a record is, as key/value pairs."""
    fields = fields or {}
    return [{"key": k, "value": fields[k]} for k in IDENTIFYING if fields.get(k)]


def news_facts(fields: dict | None) -> list[dict]:
    """The identifying fields an article gave, as a new record would take them: an English-only field keeps its English or is left out."""
    out = []
    for f in identifying(fields):
        if f["key"] in ENGLISH_ONLY:
            f = {**f, "value": clean_news_value(f["key"], f["value"])}
        if f["value"]:
            out.append(f)
    return out


def plausible(candidates: list[dict]) -> list[dict]:
    """
    The candidates that are genuinely competing answers.

    Trigram always returns its best five, but when the top scores 1.00 and the
    rest 0.33 those others are not alternatives -- they are different people
    with vaguely similar names, and offering them as choices makes an easy
    decision look hard.
    """
    if not candidates:
        return []
    # Rows written since retrieval learned to rank on shared fields carry a
    # combined score; older rows only the name similarity.
    measure = lambda c: c.get("score", c["similarity"])
    best = max(measure(c) for c in candidates)
    return [c for c in candidates if best - measure(c) <= PLAUSIBLE_MARGIN]


def _by_id(table: str, column: str, ids: list, select: str) -> dict:
    out: dict = {}
    ids = [i for i in dict.fromkeys(ids) if i]
    for start in range(0, len(ids), 200):
        rows = (
            get_client().from_(table).select(select)
            .in_(column, ids[start:start + 200]).execute().data or []
        )
        out.update({r[column]: r for r in rows})
    return out


OMITTED = "Not returned by the model"
EXACT = 0.95


def omitted_exact(p: dict, entity: dict) -> dict | None:
    """
    The candidate an omitted entity plainly is, when there is one.

    The prompt's contract makes an entity the model left out of its answer a
    CREATE_NEW, and the card then said "not in TTE" of Tommy Koh with Koh,
    Tommy in the candidates at similarity 1. Five such rows in 1,280
    omissions, every one matched under the same name in another article. An
    exact hit through the article's own spelling (not a romanised guess)
    makes the card an identity question instead; the stored row is left as
    written, since "the model said nothing" is the truth of it.
    """
    if not (p.get("reasoning") or "").startswith(OMITTED):
        return None
    top = max((p.get("candidates") or []), key=lambda c: c.get("similarity") or 0, default=None)
    if top is None or (top.get("similarity") or 0) < EXACT or top.get("romanised"):
        return None
    if top.get("matched_via") and top["matched_via"] != entity["entity_name"]:
        return None
    return top


def _group_key(proposal: dict, entity: dict) -> str:
    """
    What makes two proposals the same decision.

    The record, when one was matched: several articles reporting on the same
    person all update the same record, and asking a reviewer to confirm that
    identity once per article wastes their time and invites inconsistent
    answers. Where nothing matched, the entity's own name serves, so two
    articles about the same new entity still arrive together.
    """
    if proposal.get("matched_uid"):
        return "uid:" + proposal["matched_uid"]
    name = (entity.get("entity_name_en") or entity["entity_name"]).strip().lower()
    return "new:" + entity["entity_type"] + ":" + name


# An article's subject is the entity whose change is the news. The extraction
# model says so from now on (`role`); for rows written before it did, the name
# in the headline is the subject, and a new law, event, award or programme is
# the news whenever the article carries one. An institution that granted a
# degree, or the agency a bill empowers, is context: the reviewer who saw a
# card for Nanyang Technological University under "Teo Chee Hean receives NTU
# honorary degree" called it the wrong focus, and it was.
SUBJECT_TYPES = {"LEGAL_ACT", "EVENT", "AWARD", "PROGRAMME"}


def subjects_of(entities: list[dict], title: str, updates: dict[int, int]) -> set[int]:
    """The ids of the entities an article is about."""
    said = {e["id"] for e in entities if e.get("role") == "subject"}
    if said or any(e.get("role") for e in entities):
        return said
    t = (title or "").casefold()
    named = {e["id"] for e in entities
             if any(n and n.casefold() in t
                    for n in (e["entity_name"], e.get("entity_name_en") or ""))}
    typed = {e["id"] for e in entities if e["entity_type"] in SUBJECT_TYPES}
    out = named | typed
    if not out and entities:
        out = {max(entities, key=lambda e: (updates.get(e["id"], 0), -e["id"]))["id"]}
    return out


# LINKED_FIELDS, the four the reviewers asked for, lives in shared/names.py
# with the naming rules, since Job 3 applies them when it stores a proposal.
# Spouse, Parent and Child also name records; Successor and Predecessor are
# not fields at all in TTE but relationship rows, which the pipeline cannot
# yet express.
SOFT_LINKED_FIELDS: dict[str, str] = {}
NEAR_ENOUGH = 0.6


class Lookup:
    """
    Records of one type by name: exact after normalising, else the nearest by
    trigram, the same measure retrieval uses. "Singapore Civil Defence Force"
    is in TTE as "Singapore. Civil Defence Force", and the badge says so
    rather than calling it absent.
    """

    def __init__(self, index: list[list] | None, entity_type: str,
                 variants: list[list] | None = None):
        from src.backfill.local_match import trigrams
        self.exact: dict[str, str] = {}
        self.styled: dict[str, tuple[str, str]] = {}
        self.rows: list[tuple[str, str, set]] = []
        for row in index or []:
            if row[2] != entity_type:
                continue
            self.exact.setdefault(plain(row[1]), row[0])
            self.styled.setdefault(house(row[1]), (row[0], row[1]))
            self.rows.append((row[0], row[1], trigrams(row[1])))
        # A variant name (Chinese, a former name) reaches its canonical
        # record by exact match only; it is never offered as "nearest".
        self.canonical_name = {row[0]: row[1] for row in index or [] if row[2] == entity_type}
        for name, canonical_uid, etype in variants or []:
            if etype == entity_type and canonical_uid in self.canonical_name:
                self.exact.setdefault(plain(name), canonical_uid)
        self._grams = trigrams

    def find(self, name: str) -> dict:
        """
        {"uid"} for the name itself; {"uid", "as"} for the same thing in
        TTE's house style; {"uid": None, "nearest", "nearest_uid"} when only
        a different-looking record is close, which is a hint and not a
        match: "Inspiring Teacher Award" was nearest to "Inspiring Teacher
        of English Award", a different award.
        """
        key = plain(name)
        if key in self.exact:
            uid = self.exact[key]
            label = self.canonical_name.get(uid, "")
            # Found under a variant name: say which record that is.
            return {"uid": uid, "as": label} if label and plain(label) != key else {"uid": uid}
        styled = house(name)
        if styled and styled in self.styled:
            uid, label = self.styled[styled]
            return {"uid": uid, "as": label}
        q = self._grams(name)
        best, best_sim = None, 0.0
        for uid, label, grams in self.rows:
            shared = len(q & grams)
            if not shared:
                continue
            sim = shared / (len(q) + len(grams) - shared)
            if sim > best_sim:
                best, best_sim = (uid, label), sim
        if best and best_sim >= NEAR_ENOUGH:
            return {"uid": None, "nearest": best[1], "nearest_uid": best[0]}
        return {"uid": None}


def named_as_tte(change: dict) -> None:
    """
    A link field holds the names of records, written as TTE writes them.

    Once the lookup has found the record, the proposal carries the record's
    name and keeps what the article wrote beside it: "Housing and
    Development Board" is proposed as "Singapore. Housing and Development
    Board", so the reviewer is not asked to reword a house-style prefix and
    the sheet carries the value the cataloguer will type. A record that is
    merely nearest is left as written; the desk offers it as one click.
    """
    swap = {a["name"]: renamed(a["name"], a["as"]) for a in change["inTTE"] if a.get("uid") and a.get("as")}
    swap = {k: v for k, v in swap.items() if k != v}
    if not swap:
        return
    values = [swap.get(v, v) for v in _values(change["adding"])]
    change["wrote"] = {v: k for k, v in swap.items()}
    change["adding"] = DELIMITER.join(values)
    change["result"] = result_of(change["strategy"], change.get("existing") or [], change["adding"])
    for a in change["inTTE"]:
        if a["name"] in swap:
            a["wrote"], a["name"] = a["name"], swap[a["name"]]
    for pv in change.get("perValue") or []:
        pv["value"] = swap.get(pv["value"], pv["value"])
    for sb in change.get("saidBy") or []:
        sb["value"] = swap.get(sb["value"], sb["value"])


def record_flags(value: str, lookup: "Lookup", soft: bool = False) -> list[dict]:
    """
    Each value, with the TTE record it names if there is one.

    A value from a non-English article comes as the original name with the
    English in brackets, "博理中学 (Bendemeer Secondary School)". Both are
    looked up: the original reaches the record through a variant name TTE
    holds, the gloss through the English name.
    """
    out = []
    for v in _values(value):
        found = {"uid": None}
        for t in tries_for(v):
            got = lookup.find(t)
            if got.get("uid"):
                found = got
                break
            if got.get("nearest") and not found.get("nearest"):
                found = got
        if soft and not found.get("uid"):
            continue
        out.append({"name": v, **found})
    return out


def build_cards(include_new: bool = True, backfill: bool = False,
                index: list[list] | None = None,
                variants: list[list] | None = None) -> tuple[list[dict], list[dict]]:
    """
    One card per decision, ordered by article, with the article's subject first.

    A card carries two questions in the order a reviewer answers them: which
    record is this, and then what should change on it. Proposals that resolve
    to the same record are merged into one card, so the identity question is
    answered once and every change from every article that mentioned it is
    listed together.

    Not every entity gets a card. The first reviewer found a card for an
    entity that matched its record with nothing to add a waste of attention,
    and eighteen of fifty-three were that. Now: the article's subject is dealt
    whenever there is anything to decide, including "not in TTE yet"; another
    entity is dealt only when the model proposed a change to it or flagged it;
    everything else is a footnote on the article's cards. An article whose
    subject is on record and up to date is not dealt at all, and is listed
    instead, so the reviewer can see it was read.

    Returns the cards and that list.
    """
    client = get_client()
    proposals = fetch_all(lambda: client.from_("candidate_matches").select("*"))
    if not include_new:
        proposals = [p for p in proposals if p["resolution_action"] != "CREATE_NEW"]
    if not proposals:
        return [], []

    entities = {
        r["id"]: r
        for r in fetch_all(lambda: client.from_("extracted_entities").select("*"))
    }
    # The historical backfill is thousands of proposals; the nightly deck is
    # dozens. A reviewer gets one or the other, never both mixed.
    if column_exists("extracted_entities", "backfill"):
        entities = {k: v for k, v in entities.items() if bool(v.get("backfill")) == backfill}
        proposals = [p for p in proposals if p["extracted_id"] in entities]
    articles = _by_id("article", "id",
                      [e["article_id"] for e in entities.values()], "id, title, url, pubDate")
    # Feed titles arrive HTML-escaped ("Singapore&#039;s highest civilian
    # honour"); the desk and the sheets show text.
    for a in articles.values():
        a["title"] = html.unescape(a.get("title") or "")

    uids = [p["matched_uid"] for p in proposals]
    for p in proposals:
        uids += p.get("duplicate_uids") or []
        uids += [c["canonical_uid"] for c in (p.get("candidates") or [])]
    records = _by_id("entities", "uid", uids, "uid, name, entity_type, fields")
    lookups = {t: Lookup(index, t, variants) for t in set(LINKED_FIELDS.values()) | set(SOFT_LINKED_FIELDS.values())}

    def flags_for(field: str, value: str):
        if field in LINKED_FIELDS:
            return record_flags(value, lookups[LINKED_FIELDS[field]])
        if field in SOFT_LINKED_FIELDS:
            return record_flags(value, lookups[SOFT_LINKED_FIELDS[field]], soft=True) or None
        return None

    # Which entities each article is about, judged over the article's whole set.
    by_article: dict[int, list[dict]] = {}
    for p in proposals:
        e = entities.get(p["extracted_id"])
        if e:
            by_article.setdefault(e["article_id"], []).append(e)
    n_updates = {p["extracted_id"]: len(p.get("field_updates") or []) for p in proposals}
    subject_ids: set[int] = set()
    for aid, ents in by_article.items():
        subject_ids |= subjects_of(ents, (articles.get(aid) or {}).get("title", ""), n_updates)

    def as_option(uid: str, similarity: float | None = None, via: str | None = None,
                  original: str = "", matched_name: str | None = None) -> dict | None:
        record = records.get(uid)
        if record is None:
            return None
        option = {
            "uid": uid,
            "name": record["name"],
            "fields": identifying(record.get("fields")),
            "similarity": round(similarity, 2) if similarity is not None else None,
        }
        # Reached through the extractor's English rendering of a non-Latin
        # name, which is a guess: the card says so.
        if via and original and via != original and not LATIN.match(original):
            option["romanised"] = True
        # Reached through a non-preferred term, which is how most candidates
        # arrive: 1,714 of 2,899 in a sample. The reviewer sees which name
        # matched, and so why the record is offered at all.
        if matched_name and not same_words(matched_name, record["name"]):
            option["npt"] = matched_name
        return option

    grouped: dict[str, dict] = {}
    for p in proposals:
        entity = entities.get(p["extracted_id"])
        if entity is None:
            continue
        article = articles.get(entity["article_id"], {})
        exact = omitted_exact(p, entity)
        if exact is not None:
            p = {**p, "matched_uid": exact["canonical_uid"], "resolution_action": "OMITTED_EXACT"}
        record = records.get(p["matched_uid"] or "", {})
        is_new = p["resolution_action"] == "CREATE_NEW"
        is_flag = not is_new and p["resolution_action"] != "MATCH_AND_UPDATE"

        # The records the reviewer may choose between, best first.
        options = []
        for c in plausible(p.get("candidates") or []):
            option = as_option(c["canonical_uid"], c.get("similarity"), c.get("matched_via"),
                               entity["entity_name"], c.get("matched_name"))
            if option:
                options.append(option)
        for uid in p.get("duplicate_uids") or []:
            if uid not in {o["uid"] for o in options}:
                option = as_option(uid)
                if option:
                    options.append(option)
        options.sort(key=lambda o: -(o["similarity"] or 0))

        current = record.get("fields") or {}
        changes = []
        for u in (p.get("field_updates") or []):
            before = current.get(u["field"], "")
            held = [v.strip() for v in before.split(DELIMITER) if v.strip()]
            # Put the model's value the way TTE holds it: a list split however the model
            # joined it, an English-only field in English. Nothing left, or nothing the
            # record does not already say in another language, is no change to offer.
            value = clean_news_value(u["field"], u["value"])
            if not value.strip():
                continue
            if u["field"] in ENGLISH_ONLY and all(_covered(u["field"], v, held) for v in _values(value)):
                continue
            u = {**u, "value": value}
            change = {
                "field": u["field"],
                "verb": VERB.get(u["strategy"], u["strategy"]),
                "strategy": u["strategy"],
                "adding": u["value"],
                "existing": held,
                "result": result_of(u["strategy"], held, u["value"]),
            }
            # A rewrite is shown as a diff; an addition needs no diff, since it
            # joins a list rather than replacing text.
            # A diff over "22" -> "25" is noise; a plain before-and-after says
            # it. Only prose earns the comparison machinery.
            if u["strategy"] in ("MERGE", "REPLACE") and len(before) >= 60:
                # Job 3 applies this same judgement when it stores a proposal,
                # but these rows were written before it existed. Re-checking
                # here keeps a reviewer from spending attention on a rewrite
                # the pipeline would no longer put in front of them.
                if change["field"] == "Description":
                    verdict, left, _ = judge(before, u["value"])
                    if verdict == "drop":
                        continue
                    change["overEdit"] = verdict == "flag"
                    change["overLimit"] = over_limit(before, u["value"])
                    change["sentences"] = sentence_count(u["value"])
                # The sentence the rewrite adds, stated plainly. A reviewer who
                # reads one line and glances at the diff to confirm it is doing
                # something a reviewer parsing a diff cannot reliably do.
                change["adds"] = additions(before, u["value"])
                change["diff"] = diff_parts(before, u["value"])
                change["drops"], change["subs"] = edits_in(change["diff"])
                change["kept"] = round(kept_ratio(before, u["value"]), 2)
            changes.append(change)

        summary = entity.get("summary") or ""
        title = article.get("title", "") or ""
        source = {
            "pid": p["id"],
            "name": entity["entity_name"],
            "says": summary,
            "fields": identifying(entity.get("fields")),
            "quote": entity.get("evidence_en") or entity.get("evidence") or "",
            # The sentence as printed, when the article was not in English:
            # a reviewer who reads the language checks the translation, one
            # who does not still has the English.
            "original": (entity.get("evidence") or "") if entity.get("evidence_en") else "",
            "article": title,
            "link": article.get("url", ""),
            "articleId": entity["article_id"],
            "date": (article.get("pubDate") or "")[:10],
        }
        # The source of each change is the article's link, not its headline:
        # the Straits Times and CNA ran the same headline on Khaw Boon Wan
        # two days apart, and two sources counted as one.
        for change in changes:
            change["from"] = article.get("url") or title

        key = _group_key(p, entity)
        card = grouped.get(key)
        if card is None:
            grouped[key] = {
                "key": key,
                "pids": [p["id"]],
                "eids": [entity["id"]],
                "entity": entity["entity_name"],
                "entityEn": entity.get("entity_name_en") or "",
                "type": entity["entity_type"],
                "newsFields": news_facts(entity.get("fields")),
                "newsRaw": dict(entity.get("fields") or {}),
                # Which clipping first carried each fact, so the desk can put
                # that clipping, and only that one, beside the pencil note.
                "newsFrom": {k: (article.get("url") or title) for k in (entity.get("fields") or {})},
                "newsSays": summary,
                "options": options,
                "picked": p.get("matched_uid") or "",
                "isFlag": is_flag,
                "isNew": is_new,
                "flagWhy": FLAG_WHY.get(p["resolution_action"], ""),
                "subject": entity["id"] in subject_ids,
                "changes": changes,
                "sources": [source],
            }
            continue

        # Merge a second article's take on the same record. The same article
        # quoted twice is one clipping, not two.
        card["pids"].append(p["id"])
        card["eids"].append(entity["id"])
        if not any(x["article"] == source["article"] and x["quote"] == source["quote"]
                   for x in card["sources"]):
            card["sources"].append(source)
        card["changes"].extend(changes)
        # An omission folded into a record another article matched outright
        # is settled by that match: the identity question is asked once, on
        # the match's evidence, and the omission's reason is not carried.
        omitted = FLAG_WHY["OMITTED_EXACT"]
        if p["resolution_action"] == "MATCH_AND_UPDATE" and card["flagWhy"] == omitted:
            card["isFlag"], card["flagWhy"] = False, ""
        elif p["resolution_action"] != "OMITTED_EXACT":
            card["isFlag"] = card["isFlag"] or is_flag
            card["flagWhy"] = card["flagWhy"] or FLAG_WHY.get(p["resolution_action"], "")
        card["subject"] = card["subject"] or entity["id"] in subject_ids
        seen = {o["uid"] for o in card["options"]}
        card["options"].extend(o for o in options if o["uid"] not in seen)
        # Keep whichever spelling of the name is longest; the fuller form is
        # more use to a reviewer than "Alan Chan" when the record reads
        # "Alan Chan Heng Loon".
        if len(entity["entity_name"]) > len(card["entity"]):
            card["entity"] = entity["entity_name"]
        for f in news_facts(entity.get("fields")):
            if f["key"] not in {x["key"] for x in card["newsFields"]}:
                card["newsFields"].append(f)
        for key, value in (entity.get("fields") or {}).items():
            card["newsRaw"].setdefault(key, value)
            card["newsFrom"].setdefault(key, article.get("url") or title)

    # Every person's evidence sentence, by article: where a change whose own
    # person's sentence does not back it finds one that does.
    said_in: dict[int, list[dict]] = {}
    for e in entities.values():
        said_in.setdefault(e["article_id"], []).append({
            "id": e["id"], "quote": e.get("evidence_en") or e.get("evidence") or "",
            "original": (e.get("evidence") or "") if e.get("evidence_en") else ""})

    cards = list(grouped.values())
    for card in cards:
        # Two articles proposing the same fact is one note, not two.
        card["changes"] = collapse(card["changes"])
        first_of = {}
        for s in card["sources"]:
            first_of.setdefault(s["link"], s)
        for ch in card["changes"]:
            quotes = {}
            for link in ch.get("supporters") or [ch.get("from")]:
                s = first_of.get(link)
                if s is None:
                    continue
                better = quote_for(ch, [card["entity"], card["entityEn"], s["name"]], s,
                                   [t for t in said_in.get(s["articleId"], []) if t["id"] not in card["eids"]])
                if better:
                    quotes[link] = better
            if quotes:
                ch["quotes"] = quotes
        for ch in card["changes"]:
            if ch["strategy"] != "MERGE":
                ch["inTTE"] = flags_for(ch["field"], ch["adding"])
                if ch["inTTE"]:
                    named_as_tte(ch)
        card["options"].sort(key=lambda o: -(o["similarity"] or 0))
        # Every candidate answers "and what would that change?", not just the
        # one the model picked -- a reviewer who overrides the match needs the
        # same answer for the record they chose instead.
        news = card.pop("newsRaw")
        covered = {ch["field"] for ch in card["changes"]}
        for option in card["options"]:
            rows = delta(news, (records.get(option["uid"]) or {}).get("fields"))
            option["delta"] = rows
            # Only the record the model actually matched carries its proposals,
            # so for any other candidate everything the article adds is offered
            # rather than assumed.
            same = option["uid"] == card["picked"]
            option["extra"] = derived_changes(rows, covered if same else set())
            for row in option["extra"]:
                row["inTTE"] = flags_for(row["field"], row["adding"])
                if row["inTTE"]:
                    named_as_tte(row)
        if card["isNew"]:
            card["newsLinked"] = {f: flags_for(f, news[f]) for f in list(LINKED_FIELDS) + list(SOFT_LINKED_FIELDS)
                                  if news.get(f) and flags_for(f, news[f])}

    # What is dealt, what is noted, and what is merely footnoted.
    def anything_to_decide(card: dict) -> bool:
        if card["changes"] or card["isFlag"]:
            return True
        picked = next((o for o in card["options"] if o["uid"] == card["picked"]), None)
        return bool(picked and picked["extra"])

    dealt, noted = [], []
    for card in cards:
        if card["isNew"]:
            (dealt if card["subject"] else noted).append(card)
        elif card["subject"] and not anything_to_decide(card):
            noted.append(card)
        elif card["subject"] or anything_to_decide(card):
            dealt.append(card)
        else:
            noted.append(card)

    # The footnote: everything else the article named, and what became of it.
    by_article_cards: dict[int, list[dict]] = {}
    for card in cards:
        for src in card["sources"]:
            by_article_cards.setdefault(src["articleId"], []).append(card)
    dealt_keys = {c["key"] for c in dealt}
    for card in dealt:
        also, seen_names = [], {card["entity"]}
        for src in card["sources"]:
            for other in by_article_cards.get(src["articleId"], []):
                if other["entity"] in seen_names:
                    continue
                seen_names.add(other["entity"])
                if other["key"] in dealt_keys:
                    state = "card"
                elif other["isNew"]:
                    state = "not in TTE"
                else:
                    state = "on record"
                also.append({"name": other["entity"], "state": state,
                             "uid": other["picked"] or None})
        card["also"] = also

    dealt.sort(key=deal_order)
    for index_, card in enumerate(dealt):
        card["i"] = index_
    up_to_date = [{"entity": c["entity"], "uid": c["picked"] or None, "new": c["isNew"],
                   "article": c["sources"][0]["article"], "link": c["sources"][0]["link"]}
                  for c in noted]
    return dealt, up_to_date


def deal_order(card: dict) -> tuple:
    """
    Latest news first, by the card's newest article: a record reported again
    today comes up with today's news, not where its first report left it.
    Within one article, its subject before the rest. An article with no
    publication date goes last.
    """
    newest = max(card["sources"], key=lambda s: (s.get("date") or "", s["articleId"]))
    day = (newest.get("date") or "").replace("-", "")
    return (-int(day) if day.isdigit() else 0, -newest["articleId"],
            not card["subject"], not card["isFlag"], card["entity"])


def write_cards(path: Path | str) -> int:
    index, variants = build_index(with_variants=True)
    cards, _ = build_cards(index=index, variants=variants)
    Path(path).write_text(
        json.dumps(cards, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return len(cards)


# What identifies a record in a one-line search result, most useful first.
SEARCH_IDENTITY = ("Occupation", "Title", "Description", "Feature Type", "Country")


def index_row(record: dict) -> list | None:
    """
    One searchable entry, or None if the record should not be offered.

    A retired record cannot receive an update, and a non-preferred term is
    never the right answer -- resolution always lands on the record holding the
    fields, so offering one would let a reviewer pick a target that cannot take
    the change. Positional, to keep the payload small: it ships in the page.
    """
    if not record.get("is_active"):
        return None
    canonical_uid = record.get("canonical_uid")
    if canonical_uid and canonical_uid != record["uid"]:
        return None

    fields = record.get("fields") or {}
    identity = next((str(fields[k])[:64] for k in SEARCH_IDENTITY if fields.get(k)), "")
    # The opening of the description, for a reviewer who knows what the
    # person did but not how TTE spells the name: "Environment Agency" finds
    # the man the extractor called "Lee, Choon Seng". Kept short; it ships
    # inside the page for every record.
    gist = " ".join(str(fields.get("Description") or "").split())[:120]
    return [record["uid"], record["name"], record["entity_type"], identity, gist]


def build_index(with_variants: bool = False):
    """
    Every record a reviewer may pick, sorted by name; with `with_variants`,
    also every active variant name as [name, canonical uid, type], which the
    badge lookup uses and the page does not ship.
    """
    rows = fetch_all(lambda: get_client().from_("entities")
                     .select("uid,name,entity_type,fields,canonical_uid,is_active"), order="uid")
    out = [row for row in (index_row(r) for r in rows) if row]
    out.sort(key=lambda e: e[1])
    if not with_variants:
        return out
    variants = [[r["name"], r["canonical_uid"], r["entity_type"]] for r in rows
                if r.get("is_active") and r.get("canonical_uid") and r["canonical_uid"] != r["uid"]]
    return out, variants


def same_words(a: str, b: str) -> bool:
    """
    Whether two names are the same words in another order or dress. "Khaw
    Boon Wan" is how most people write "Khaw, Boon Wan", and "Singapore
    Civil Defence Force" is "Singapore. Civil Defence Force" without the
    house style; neither tells a reviewer anything. 许通美 does.
    """
    words = lambda s: sorted(re.sub(r"[^\w\s]", " ", s.casefold()).split())
    return words(a) == words(b)


def npt_map(variants: list[list], index: list[list] | None = None) -> dict[str, list[str]]:
    """
    Every non-preferred term by the record it names, for the page's search:
    a reviewer who types the name a Chinese article used finds the English
    record it is a variant of, labelled as such. A variant that is the
    record's own name in another order is left out, as are duplicates and
    blanks; order is kept.
    """
    canonical = {row[0]: row[1] for row in (index or [])}
    out: dict[str, list[str]] = {}
    for name, uid, _ in variants:
        name = (name or "").strip()
        if not name or not uid or (uid in canonical and same_words(name, canonical[uid])):
            continue
        names = out.setdefault(uid, [])
        if name not in names:
            names.append(name)
    return out
