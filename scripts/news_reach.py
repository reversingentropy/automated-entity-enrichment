"""
How much of the team's work on TTE could a news pipeline reach, and how much
did this one find?

The team's work between two TTE snapshots, English records only, is counted
as two kinds of addition:

  - a new record: a preferred record in the later snapshot that was not in
    the earlier one;
  - a fact added to an existing record, in a field news can bear on (the
    changes news_backed_changes.py counts: a value only reworded is not one).

For each, two questions:

  name printed  did any archive article published in that period, or the two
                months before, print one of the record's names in its headline
                or summary? A pipeline reading these sources cannot propose
                anything about a name none of them printed.
  found         had the pipeline already read it? For a new record: the
                archive matched an entity to it from an article published
                before the record appeared. For a fact: an archive article
                said it, the record lacked it before the article and had it
                after (news_backed_changes.py).

A record's names are its own and every non-preferred term that resolves to it,
in any language, in the forms an article prints them: "Lee, Wei Ling" as "Lee
Wei Ling" and "Wei Ling Lee", "Singapore. Ministry of Health" as "Ministry of
Health", qualifiers in brackets dropped. A name is matched as whole words,
ignoring case and punctuation; a Chinese name as it is written. Names too
short to mean anything alone are left out: a Latin name of one word under 8
letters, a Chinese name under 3 characters, and initialisms.

A printed name is necessary, not sufficient: the article may not report the
addition. The archive holds headlines and summaries only, and full text would
hold more names. Other work, such as new variant names and rewritten
descriptions, is not counted.

    uv run python scripts/news_reach.py

Reads the dumps, data/backfill/answers/relevance.csv (the archive's headlines
and summaries) and the archive's matches (data/coverage/archive-matches.json,
built by news_backed_changes.py). Writes a summary to
data/coverage/news-reach.txt and every addition to news-reach.csv.
"""

import csv
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from news_backed_changes import OUT, archive_matches, news_backed, norm as fact_norm, same, snapshots, team_changes  # noqa: E402

ARCHIVE = ROOT / "data" / "backfill" / "answers" / "relevance.csv"
BEFORE = timedelta(days=60)                # "the two months before" a period
CJK = re.compile(r"[㐀-鿿]")
LATIN = re.compile(r"[a-z]")


def norm(text):
    return " ".join(re.sub(r"[^\w\s]", " ", str(text).casefold()).split())


def forms(name):
    """The forms of a TTE name an article would print, normalised; usable ones only."""
    n = " ".join(re.sub(r"\([^)]*\)", " ", name).split())
    out = set()
    if n.count(",") == 1 and not CJK.search(n):          # "Lee, Wei Ling"
        a, b = (x.strip() for x in n.split(","))
        out |= {f"{a} {b}", f"{b} {a}"}
    else:
        out.add(n)
        if n.startswith("Singapore. "):
            out.add(n[len("Singapore. "):])
    usable = set()
    for f in map(norm, out):
        if CJK.search(f):
            if len(f.replace(" ", "")) >= 3:
                usable.add(f.replace(" ", ""))
        elif LATIN.search(f):
            words = f.split()
            if len(words) >= 2 and not all(len(w) == 1 for w in words) or len(words) == 1 and len(f) >= 8:
                usable.add(f)
    return usable


def load_articles(start, end):
    """[(day, source, title, normalised headline and summary)] published in [start, end)."""
    csv.field_size_limit(10 ** 9)
    out = []
    with open(ARCHIVE, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                day = date.fromisoformat(r["published"][:10])
            except ValueError:
                continue
            if start <= day < end:
                out.append((day, r["source"], r["title"], norm(f"{r['title']} {r['description']}")))
    return out


class Finder:
    """Which articles print a name: whole words for Latin names, as written for Chinese."""

    def __init__(self, articles):
        self.articles = articles
        self.postings = defaultdict(set)
        for i, (_, _, _, text) in enumerate(articles):
            for w in set(text.split()):
                if LATIN.search(w):
                    self.postings[w].add(i)
        self.chinese = [i for i, a in enumerate(articles) if CJK.search(a[3])]
        self.cache = {}

    def find(self, form):
        if form not in self.cache:
            if CJK.search(form):
                hits = [i for i in self.chinese if form in self.articles[i][3]]
            else:
                words = form.split()
                rarest = min(words, key=lambda w: len(self.postings.get(w, ())))
                padded = f" {form} "
                hits = [i for i in self.postings.get(rarest, ()) if padded in f" {self.articles[i][3]} "]
            self.cache[form] = sorted(hits)
        return self.cache[form]

    def first(self, names, start, end):
        """The earliest article in [start, end) printing any of the names, or None."""
        best = None
        for form in set().union(*(forms(n) for n in names)) if names else ():
            for i in self.find(form):
                if start <= self.articles[i][0] < end and (best is None or self.articles[i][0] < self.articles[best][0]):
                    best = i
        return best


def new_records(snaps):
    """{period: {uid}}: preferred English records in a snapshot that were not in the one before."""
    out = {}
    for k in range(1, len(snaps)):
        (_, before, before_names), (_, after, after_names) = snaps[k - 1], snaps[k]
        out[k] = {uid for uid in after if uid in after_names and uid not in before and uid not in before_names}
    return out


def offered(snaps, matches):
    """
    Every distinct fact the pipeline had about a record it matched, from an
    article inside the snapshots, by what became of it: already in TTE before
    the article, added by the team in that period, added later, or never added.
    """
    days = [s[0] for s in snaps]
    seen, out = set(), Counter()
    for m in matches:
        day = date.fromisoformat(m["day"])
        if not (days[0] <= day < days[-1]):
            continue
        k = next(i for i in range(1, len(days)) if day < days[i])
        uid = m["uid"]
        if uid not in snaps[k - 1][1]:
            continue
        for f, raw in m["fields"].items():
            for v in [x.strip() for x in str(raw).split("|") if x.strip()]:
                key = (uid, f, v[:4] if f.endswith("(yyyy)") else fact_norm(v))
                if key in seen:
                    continue
                seen.add(key)
                has = lambda snap: any(same(v, w, f) for w in snap[1].get(uid, {}).get(f, []))
                if has(snaps[k - 1]):
                    out["already in TTE"] += 1
                elif has(snaps[k]):
                    out["added by the team that period"] += 1
                elif any(has(sn) for sn in snaps[k + 1:]):
                    out["added by the team later"] += 1
                else:
                    out["never added"] += 1
    return out


def main():
    print("Reading the TTE snapshots ...", flush=True)
    snaps = snapshots(with_names=True)
    days = [s[0] for s in snaps]
    team, _ = team_changes(snaps)
    created = new_records(snaps)

    print("Reading the archive ...", flush=True)
    matches = archive_matches()
    backed, _ = news_backed(snaps, matches, team)
    articles = load_articles(days[0] - BEFORE, days[-1])
    finder = Finder(articles)

    # An archive entity matched to a record, from an article in the window
    # before the record appeared: the pipeline had read about it first.
    matched_on = defaultdict(list)
    for m in matches:
        matched_on[m["uid"]].append(date.fromisoformat(m["day"]))

    rows = []
    for k in range(1, len(snaps)):
        start, end = days[k - 1] - BEFORE, days[k]
        names = snaps[k][2]
        period = f"{days[k - 1]} to {days[k]}"
        work = [("new record", uid, "") for uid in sorted(created[k])]
        work += [("fact added", uid, field) for uid, field in sorted(team.get(k, ()))]
        for kind, uid, field in work:
            i = finder.first(names.get(uid), start, end)
            if kind == "new record":
                found = any(start <= d < end for d in matched_on.get(uid, ()))
            else:
                found = (k, uid, field) in backed
            a = articles[i] if i is not None else None
            rows.append({"kind": kind, "period": period, "uid": uid, "field": field,
                         "names": " | ".join(sorted(names.get(uid, ())))[:200],
                         "printed": int(a is not None), "found": int(found),
                         "article_day": a[0] if a else "", "source": a[1] if a else "",
                         "title": a[2] if a else ""})

    def line(label, rs):
        n, p = len(rs), sum(r["printed"] for r in rs)
        f = sum(r["found"] and r["printed"] for r in rs)
        return f"{label:<34}{n:>8,}{p:>8,} ({p / max(n, 1):>4.0%}){f:>8,} ({f / max(p, 1):>4.0%} of printed)"

    deaths = [r for r in rows if r["field"] == "Death Year (yyyy)"]
    lines = [
        f"Snapshots: {len(snaps)}, {days[0]} to {days[-1]} ({len(snaps) - 1} periods); "
        f"{len(articles):,} archive articles from {days[0] - BEFORE}",
        "",
        f"{'':<34}{'work':>8}{'name printed':>16}{'found':>8}",
        line("new records", [r for r in rows if r["kind"] == "new record"]),
        line("facts added to existing records", [r for r in rows if r["kind"] == "fact added"]),
        line("  of which, year of death", deaths),
        line("all", rows),
        "",
        "'found' counts only what was also printed in a headline or summary, and is shown as a share of it.",
    ]
    # found but not printed (a name form the check missed): reported, not hidden
    missed = sum(1 for r in rows if r["found"] and not r["printed"])
    lines.append(f"Found by the pipeline but missed by the name check: {missed:,}")
    facts = offered(snaps, matches)
    lines += ["", f"Facts the pipeline had about records it matched: {sum(facts.values()):,}"]
    lines += [f"  {c:<32}{facts[c]:>7,}" for c in
              ("already in TTE", "added by the team that period", "added by the team later", "never added")]
    summary = "\n".join(lines)
    print(summary)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "news-reach.txt").write_text(summary + "\n", encoding="utf-8")
    with open(OUT / "news-reach.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
