"""
Does a card show every value its articles proposed, and credit each value only
to the articles that gave it? `credit_every_source` runs first, so an article
that states a value another proposed counts as giving it.

The card builder once merged values it judged alike and kept one: Singapore
Airlines' eight awards reached the reviewer as four, credited to papers that
never named them, and nothing noticed. This is the check that would have. It
compares the proposals going into the card builder with the notes coming out,
and names every value that went missing and every credit no proposal backs.
A value is accounted for when it is on the card as proposed, renamed as TTE
names it, or already held by the record.
"""

from src.shared.description import sentence_edits


def account_for(proposed: list[dict], shown: list[dict], settled: list[dict] = ()) -> list[str]:
    """
    Problems with one card, as sentences; none when everything is in order.

    `proposed` are the card's changes before they were merged, one per
    article; `shown` the notes left after merging and renaming; `settled` the
    notes dropped because the record holds every value in them.
    """
    from src.export.cards import _values, value_key

    problems = []
    notes: dict[str, list[dict]] = {}
    for ch in shown:
        notes.setdefault(ch["field"], []).append(ch)
    held_by: dict[str, set[str]] = {}            # field -> values the record holds
    renamed: dict[str, dict[str, str]] = {}      # field -> {as written: as TTE names it}
    for ch in list(shown) + list(settled):
        held_by.setdefault(ch["field"], set()).update(value_key(v) for v in ch.get("existing") or [])
        renamed.setdefault(ch["field"], {}).update(ch.get("named") or {})
        for a in ch.get("inTTE") or []:
            if a.get("wrote"):
                renamed[ch["field"]][a["wrote"]] = a["name"]

    def as_shown(field: str, value: str) -> str:
        return value_key(renamed.get(field, {}).get(value, value))

    # What each article proposed, field by field, as keys.
    gave: dict[tuple[str, str], set[str]] = {}
    for ch in proposed:
        if _prose(ch):
            continue
        for v in _values(ch["adding"]) + [ch["adding"]]:
            gave.setdefault((ch["field"], ch.get("from") or ""), set()).update({value_key(v), as_shown(ch["field"], v)})

    # 1. Every proposed value is on the card, or already in TTE.
    for ch in proposed:
        field, src = ch["field"], ch.get("from") or ""
        if _prose(ch):
            problems += _sentences_missing(ch, notes.get(field, []))
            continue
        on_card = set()
        for n in notes.get(field, []):
            on_card |= {value_key(v) for v in _values(n["adding"])}
            on_card |= {value_key(x["value"]) for x in n.get("saidBy") or []}
            on_card |= {value_key(x["value"]) for x in n.get("perValue") or []}
        for v in _values(ch["adding"]) or [ch["adding"]]:
            if not v.strip():
                continue
            k = as_shown(field, v)
            if k not in on_card and k not in held_by.get(field, set()) and value_key(v) not in held_by.get(field, set()):
                problems.append(f'{field}: "{v}" ({_short(src)}) is not on the card')

    # 2. Every credit on the card is backed by that article's own proposal.
    for field, ns in notes.items():
        for n in ns:
            if _prose(n):
                continue                          # description sentences are checked above
            credits = [(x["value"], s) for x in n.get("perValue") or [] for s in x.get("sources") or []]
            credits += [(x["value"], x["from"]) for x in n.get("saidBy") or [] if x.get("from")]
            for value, src in credits:
                if value_key(value) not in gave.get((field, src), set()):
                    problems.append(f'{field}: "{value}" is credited to {_short(src)}, which did not give it')
    return sorted(set(problems))


def _prose(ch: dict) -> bool:
    return ch["field"] == "Description" and ch["strategy"] in ("MERGE", "REPLACE")


def _sentences_missing(ch: dict, notes: list[dict]) -> list[str]:
    """Each new sentence one article proposed for a description, on the note and credited to it."""
    before = " ".join(ch.get("existing") or [])
    src = ch.get("from") or ""
    out = []
    for n in notes:
        said = n.get("said")
        if said is None:                          # one article's rewrite, shown whole
            if n["adding"] != ch["adding"]:
                out.append(f"Description: {_short(src)}'s rewrite is not the one on the card")
            continue
        on_screen = set(n.get("adds") or []) | set(n.get("held") or [])
        on_screen |= {w for a in n.get("alts") or [] for w in a["wordings"]}
        for e in sentence_edits(before, ch["adding"]):
            t = e["text"]
            if t in before:
                continue
            if t not in on_screen:
                out.append(f'Description: "{t[:60]}" ({_short(src)}) is not on the card')
            elif src and src not in said.get(t, []):
                out.append(f'Description: "{t[:60]}" is not credited to {_short(src)}, which wrote it')
        for t, srcs in said.items():
            if src in srcs and t not in {e["text"] for e in sentence_edits(before, ch["adding"])}:
                out.append(f'Description: "{t[:60]}" is credited to {_short(src)}, which did not write it')
    if not notes:
        out.append(f"Description: {_short(src)}'s rewrite is not on the card")
    return out


def _short(link: str) -> str:
    return (link or "an article").rstrip("/").rsplit("/", 1)[-1][:60]
