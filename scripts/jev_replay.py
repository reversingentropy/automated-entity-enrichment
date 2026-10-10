"""
Replay Gemini's stored resolution decisions through TypeSafe's jev, to see where they agree and where they do not.

    .venv/bin/python scripts/jev_replay.py pilot      # ~70 entities, to check the wording of the questions first
    .venv/bin/python scripts/jev_replay.py run        # every stored resolution that had candidates (resumable)
    .venv/bin/python scripts/jev_replay.py report     # agreement with Gemini, and the disagreements to read
    .venv/bin/python scripts/jev_replay.py sheet      # a short, mixed set of disagreements to judge by hand: data/jev/evaluate.md

Read-only on the database; nothing is written to it. Results go to data/jev/.
Each (entity, candidate) pair is sent to jev as one request with three yes/no questions: is it the same entity, does the
record conflict with the article, and is the name the only thing they share. The state is English only: the English
summary, the translated quote, the English fields, and the record's own (English) fields. The article's Chinese is never sent.
jev is weak at dates and counting (its own docs say so), so ages and life dates are checked in code, separately.

Needs TYPESAFE_API_KEY in .env; the key is never printed. Calls are retried with backoff on 429 and 5xx.
"""

import csv
import json
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "jev"
SNAP = OUT / "snapshot.jsonl"
PAIRS = OUT / "pairs.jsonl"
URL = "https://api.typesafe.ai/v1/systemone"
PRICE_PER_TOKEN = 0.042 / 1e6          # $42 per billion input tokens; output is free
WORKERS = 12

try:
    from tqdm import tqdm
except ImportError:                      # no bars, but it still runs
    tqdm = None

KIND = {"PERSON": "person", "ORGANISATION": "organisation", "FACILITY": "building or structure", "LOCATION": "place", "EVENT": "event",
        "AWARD": "award", "PROGRAMME": "programme", "LEGAL_ACT": "law"}
SKIP_FIELDS = {"Image Link", "DBpedia URI", "Name (DisplayName)", "Name"}
CAPS = {"Description": 600, "Awards": 300, "Achievements": 300}
DEFAULT_CAP = 250


def key():
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("TYPESAFE_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("TYPESAFE_API_KEY is not in .env")


def non_latin(text):
    return any(ord(c) >= 0x2E80 for c in (text or ""))


def trim_fields(fields, keep_name=False):
    out = {}
    for k, v in (fields or {}).items():
        if (k in SKIP_FIELDS and not (keep_name and k == "Name")) or not v:
            continue
        v = str(v)
        out[k] = v[:CAPS.get(k, DEFAULT_CAP)]
    return out


# ---- the snapshot: what Gemini saw and decided, from the database ---------------------------

def snapshot():
    if SNAP.exists():
        return [json.loads(line) for line in SNAP.read_text(encoding="utf-8").splitlines()]
    from src.shared.pagination import fetch_all
    from src.shared.supabase_client import get_client
    c = get_client()
    print("reading the stored resolutions from the database (read-only)...", flush=True)
    cm = fetch_all(lambda: c.from_("candidate_matches").select("id,extracted_id,resolution_action,matched_uid,confidence,reasoning,candidates"), order="id")
    ents = {e["id"]: e for e in fetch_all(lambda: c.from_("extracted_entities").select("id,article_id,entity_name,entity_name_en,entity_type,summary,evidence,evidence_en,fields"))}
    arts = {a["id"]: a for a in fetch_all(lambda: c.from_("article").select("id,title,pubDate"))}
    rows = []
    for r in cm:
        e = ents.get(r["extracted_id"])
        if not e:
            continue
        a = arts.get(e["article_id"], {})
        rows.append({"extracted_id": r["extracted_id"], "gemini": r["resolution_action"], "gemini_uid": r["matched_uid"], "gemini_conf": r["confidence"], "gemini_why": r["reasoning"],
                     "name": e["entity_name"], "name_en": e["entity_name_en"], "type": e["entity_type"], "summary": e["summary"], "quote": e["evidence"], "quote_en": e["evidence_en"],
                     "fields": e["fields"], "title": a.get("title"), "published": (a.get("pubDate") or "")[:10], "candidates": r["candidates"] or []})
    OUT.mkdir(parents=True, exist_ok=True)
    SNAP.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows), encoding="utf-8")
    print(f"snapshot: {len(rows):,} resolutions saved to {SNAP}")
    return rows


# ---- what is sent to jev --------------------------------------------------------------------

def pair_state(r, cand):
    """The article's entity and one authority record, in English only."""
    name = r["name_en"] or r["name"]
    quote = r["quote_en"] or (r["quote"] if not non_latin(r["quote"]) else None)
    entity = {"name": name, "type": KIND.get(r["type"], r["type"].lower()), "article_published": r["published"], "what_the_article_says": r["summary"]}
    if non_latin(r["name"]):
        entity["name_as_written_in_the_article"] = r["name"]            # a transliteration alone can miss the record: 朱倍庆 is Desmond Choo, not "Zhu Pei Qing"
    if quote:
        entity["quote_from_article"] = quote
    described = trim_fields(r["fields"])
    if described:
        entity["facts_in_the_article"] = described
    record = {"name": cand["canonical_name"], "facts": trim_fields(cand.get("canonical_fields"))}
    linked = cand.get("matched_name")
    if linked and linked != cand["canonical_name"] and (cand.get("similarity") or 0) >= 0.9:
        record["linked_record_with_the_same_name_as_the_article"] = linked   # the authority file links records across languages
    return {"entity_in_the_article": entity, "authority_record": record}


def questions(kind):
    return {
        "same_entity": {"type": "noul",
                        "instructions": f"Is the {kind} described in the article the same real-world {kind} as the authority record? A shared name is not enough: the facts in the article must fit the record.",
                        "criteria": {"true": "The article's facts (profession, organisation, role, era, life dates) are consistent with the record, and it plausibly describes the same individual or body. The record may be older than the article: a newer or additional role or title is not a conflict.",
                                     "false": "The record describes a different individual or body: a different profession, organisation or era, or only the name is shared."}},
        "facts_fit": {"type": "noul",
                      "instructions": "Leaving the name aside, do the facts the article gives about this entity (occupation, role, organisation, place, dates) fit the facts in the authority record?",
                      "criteria": {"true": "The article's facts fit the record: the same kind of role, organisation, place or period. The record may be older than the article, so a newer or additional role is consistent.",
                                   "false": "The article's facts describe someone or something else: a different profession, organisation, place or era."}},
        "record_conflicts": {"type": "noul",
                             "instructions": "Does the authority record contain a fact that conflicts with what the article says about this entity?",
                             "criteria": {"true": "A different profession, employer or nationality, or the record's person had died before the article was published.",
                                          "false": "No conflicting fact."}},
        "only_the_name_matches": {"type": "noul",
                                  "instructions": "Apart from the name, do the article and the record share no supporting fact at all?",
                                  "criteria": {"true": "No shared occupation, organisation, role, place or date.", "false": "At least one shared supporting fact."}},
    }


# ---- code checks for what jev is weak at: ages and life dates -------------------------------

AGE = re.compile(r"(?:aged|age of|\()\s*(\d{2})\b|\b(\d{2})[- ]year[- ]old|(\d{2})岁|（(\d{2})岁）")


def code_veto(r, cand):
    """A reason the match is impossible, from arithmetic alone, or None."""
    year = int(r["published"][:4]) if r["published"][:4].isdigit() else None
    f = cand.get("canonical_fields") or {}
    birth = re.search(r"\d{4}", str(f.get("Birth Year (yyyy)") or ""))
    death = re.search(r"\d{4}", str(f.get("Death Year (yyyy)") or ""))
    if year and death and int(death.group()) < year - 1:
        return f"the record's person died in {death.group()}, before the article ({year})"
    if year and birth and r["type"] == "PERSON":
        for age in ages_beside_the_name(r):
            if 15 <= age <= 105 and abs((year - age) - int(birth.group())) > 2:
                return f"the article says aged {age} (born about {year - age}); the record says born {birth.group()}"
    return None


def ages_beside_the_name(r):
    """Ages written right after the person's own name. An age elsewhere in a quote may belong to someone else, or be a rule ('taxi drivers must be 30')."""
    names = {n.lower() for n in (r["name"], r["name_en"]) if n}
    names |= {w.lower() for n in list(names) for w in re.split(r"[ ,]+", n) if len(w) > 2}
    found = []
    for text in (r["quote"], r["quote_en"], r["summary"]):
        low = (text or "").lower()
        for m in AGE.finditer(text or ""):
            before = low[max(0, m.start() - 45):m.start()]
            if any(n in before for n in names):
                found.append(int(next(g for g in m.groups() if g)))
    return found


# ---- calling jev ----------------------------------------------------------------------------

class Meter:
    def __init__(self):
        self.lock, self.tokens, self.calls, self.failed = threading.Lock(), 0, 0, 0

    def add(self, usage):
        with self.lock:
            self.tokens += (usage or {}).get("input_tokens", 0)
            self.calls += 1


METER = Meter()


def ask(client, token, state, qs, raw=False):
    last = None
    for attempt in range(7):
        try:
            resp = client.post(URL, headers={"Authorization": f"Bearer {token}"}, json={"state": state, "model": "jev-latest", "questions": qs}, timeout=60)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last = f"{type(e).__name__}"
            time.sleep(min(30, 2 ** attempt) + random.random())
            continue
        if resp.status_code == 200:
            body = resp.json()
            METER.add(body.get("usage"))
            if raw:
                return body["answers"]
            return {k: v.get("noul") for k, v in body["answers"].items()}
        if resp.status_code in (429, 500, 502, 503, 504, 529):
            last = f"HTTP {resp.status_code}"
            wait = float(resp.headers.get("retry-after", 0) or 0) or min(30, 2 ** attempt)
            time.sleep(wait + random.random())
            continue
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")          # 401, 422 and the like will not fix themselves
    raise RuntimeError(f"gave up after retries ({last})")


def score_pairs(rows, label):
    """Score every (entity, candidate) pair not already in pairs.jsonl. Resumable; Ctrl+C keeps what is done."""
    token = key()
    done = set()
    if PAIRS.exists():
        for line in PAIRS.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            done.add((d["extracted_id"], d["uid"]))
    jobs = [(r, c) for r in rows for c in r["candidates"] if (r["extracted_id"], c["canonical_uid"]) not in done]
    print(f"{label}: {len(jobs):,} pairs to score ({len(done):,} already done)", flush=True)
    if not jobs:
        return
    out = open(PAIRS, "a", encoding="utf-8")
    lock = threading.Lock()
    errors = []
    t0 = time.time()
    client = httpx.Client(limits=httpx.Limits(max_connections=WORKERS * 2))

    def one(job):
        r, c = job
        p = ask(client, token, pair_state(r, c), questions(KIND.get(r["type"], "entity")))
        rec = {"extracted_id": r["extracted_id"], "uid": c["canonical_uid"], "same": p["same_entity"], "facts": p["facts_fit"], "conflict": p["record_conflicts"], "name_only": p["only_the_name_matches"],
               "name_sim": c.get("similarity")}
        with lock:
            out.write(json.dumps(rec) + "\n")
            out.flush()

    pool = ThreadPoolExecutor(max_workers=WORKERS)
    futures = [pool.submit(one, j) for j in jobs]
    bar = tqdm(total=len(futures), desc=label, unit=" pairs", dynamic_ncols=True) if tqdm else None
    try:
        for i, f in enumerate(as_completed(futures), 1):
            try:
                f.result()
            except RuntimeError as e:
                errors.append(str(e))
                if len(errors) >= 25 or "HTTP 401" in str(e) or "HTTP 422" in str(e):
                    print(f"\nstopping: {e}", flush=True)
                    break
            if bar:
                bar.update(1)
            elif i % 500 == 0:
                print(f"  {i:,}/{len(futures):,}", flush=True)
    except KeyboardInterrupt:
        print("\nCtrl+C: keeping what is done; run again to resume", flush=True)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        out.close()
        if bar:
            bar.close()
    secs = time.time() - t0
    print(f"{METER.calls:,} calls in {secs:.0f}s ({METER.calls / max(secs, 1):.1f}/s), {METER.tokens:,} tokens = ${METER.tokens * PRICE_PER_TOKEN:.3f}; {len(errors)} errors" + (f" e.g. {errors[0]}" if errors else ""))


def load_pairs():
    pairs = {}
    if PAIRS.exists():
        for line in PAIRS.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            pairs.setdefault(d["extracted_id"], {})[d["uid"]] = d
    return pairs


# ---- the decision rule, applied to jev's numbers --------------------------------------------

def decide(r, scored, hi=0.8, lo=0.2, veto=False, facts_when_name_is_exact=False):
    """match / new / ambiguous from jev's numbers, plus the code veto. Returns (action, uid, p_same, why)."""
    if not r["candidates"]:
        return "new", None, 0.0, "no candidates"
    best = None
    for c in r["candidates"]:
        s = scored.get(c["canonical_uid"])
        if not s:
            continue
        p = s["same"]
        if facts_when_name_is_exact and (s.get("name_sim") or 0) >= 0.95 and s.get("facts") is not None:
            p = s["facts"]       # the name is not in doubt (exact, or an exact alias in the other language), so the facts decide
        v = code_veto(r, c) if veto else None
        if v:
            p = min(p, 0.05)
        if best is None or p > best[0]:
            best = (p, c, v, s)
    if best is None:
        return "missing", None, 0.0, "not scored"
    p, c, v, s = best
    if p >= hi:
        return "match", c["canonical_uid"], p, ""
    if p <= lo:
        return "new", None, p, v or ""
    return "ambiguous", c["canonical_uid"], p, ""


GEM = {"MATCH_AND_UPDATE": "match", "CREATE_NEW": "new", "FLAG_AMBIGUOUS": "ambiguous", "RE_QUERY_REQUIRED": "new", "FLAG_DB_DUPLICATE": "duplicate"}


# ---- stages ---------------------------------------------------------------------------------

def pilot():
    rows = [r for r in snapshot() if r["candidates"]]
    rng = random.Random(1)
    pick = []
    for action, n in (("MATCH_AND_UPDATE", 28), ("FLAG_AMBIGUOUS", 22), ("CREATE_NEW", 14)):
        pool = [r for r in rows if r["gemini"] == action]
        pick += rng.sample(pool, min(n, len(pool)))
    known = [x for x in rows if x["name_en"] in ("Lee, Choon Seng",) or x["name"] in ("Kevin Tan", "Gerard Ee", "Anita Fam", "Lawrence Wong", "李全盛", "林泉宝")]
    seen = {r["extracted_id"] for r in pick}
    pick += [k for k in known if k["extracted_id"] not in seen]
    score_pairs(pick, "pilot")
    pairs = load_pairs()
    print(f"\n{'entity':<24} {'gemini':<18} {'jev':<10} top candidate (same / conflict / name only)")
    for r in pick:
        sc = pairs.get(r["extracted_id"], {})
        act, uid, p, why = decide(r, sc)
        top = max(r["candidates"], key=lambda c: sc.get(c["canonical_uid"], {}).get("same", -1))
        s = sc.get(top["canonical_uid"], {})
        flag = "" if GEM.get(r["gemini"]) == act else "  <-- differs"
        print(f"{(r['name_en'] or r['name'])[:23]:<24} {r['gemini'][:17]:<18} {act:<10} {top['canonical_name'][:26]:<26} "
              f"{s.get('same', float('nan')):.2f} / {s.get('conflict', float('nan')):.2f} / {s.get('name_only', float('nan')):.2f}{flag}" + (f"  [veto: {why}]" if why else ""))


def run():
    rows = [r for r in snapshot() if r["candidates"]]
    score_pairs(rows, "all stored resolutions")


def report():
    rows = snapshot()
    pairs = load_pairs()
    have = [r for r in rows if r["candidates"] and r["extracted_id"] in pairs]
    print(f"{len(rows):,} stored resolutions; {len(have):,} had candidates and are scored by jev\n")
    import collections
    for hi, lo in ((0.8, 0.2), (0.9, 0.1), (0.7, 0.3)):
        conf = collections.Counter()
        for r in have:
            conf[(GEM.get(r["gemini"], "other"), decide(r, pairs[r["extracted_id"]], hi, lo)[0])] += 1
        total = sum(conf.values())
        agree = sum(v for (g, j), v in conf.items() if g == j)
        gm = sum(v for (g, j), v in conf.items() if g == "match")
        print(f"thresholds match>={hi}, new<={lo}: agree on {agree / total:.1%} of {total:,}; of Gemini's {gm:,} matches jev also says match for {conf[('match', 'match')] / max(gm, 1):.1%}")
        if (hi, lo) == (0.8, 0.2):
            print(f"   {'Gemini/jev':<14}{'match':>8}{'new':>8}{'ambiguous':>11}")
            for g in ("match", "new", "ambiguous"):
                print(f"   {g:<14}" + "".join(f"{conf[(g, j)]:>8}" for j in ("match", "new")) + f"{conf[(g, 'ambiguous')]:>11}")
    # by script of the entity's name
    for lang, test in (("English-named", lambda r: not non_latin(r["name"])), ("Chinese-named", lambda r: non_latin(r["name"]))):
        sub = [r for r in have if test(r) and GEM.get(r["gemini"]) in ("match", "new", "ambiguous")]
        ag = sum(1 for r in sub if GEM[r["gemini"]] == decide(r, pairs[r["extracted_id"]])[0])
        print(f"{lang}: {ag / max(len(sub), 1):.1%} agree ({len(sub):,} entities)")
    # the code veto, on its own
    vetoed = [(r, c) for r in have for c in r["candidates"] if code_veto(r, c)]
    gm_v = sum(1 for r, c in vetoed if GEM.get(r["gemini"]) == "match" and r["gemini_uid"] == c["canonical_uid"])
    print(f"code veto (age or life dates impossible): fires on {len(vetoed):,} pairs, {gm_v} of them pairs Gemini chose as a match")
    # disagreements to read
    out = []
    for r in have:
        act, uid, p, why = decide(r, pairs[r["extracted_id"]])
        g = GEM.get(r["gemini"], "other")
        if g != act and g in ("match", "new", "ambiguous"):
            top = next((c for c in r["candidates"] if c["canonical_uid"] == (uid or r["gemini_uid"])), r["candidates"][0])
            out.append({"entity": r["name_en"] or r["name"], "script": "zh" if non_latin(r["name"]) else "en", "gemini": g, "jev": act, "p_same": round(p, 2), "jev_why": why,
                        "article": r["title"], "summary": (r["summary"] or "")[:240], "quote": (r["quote_en"] or "")[:200],
                        "candidate": top["canonical_name"], "candidate_facts": json.dumps(trim_fields(top.get("canonical_fields")), ensure_ascii=False)[:300],
                        "gemini_reason": (r["gemini_why"] or "")[:300], "extracted_id": r["extracted_id"], "your_verdict (jev / gemini / both wrong)": ""})
    out.sort(key=lambda d: (d["gemini"] != "match", abs(d["p_same"] - 0.5)))
    path = OUT / "disagreements.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys())) if out else None
        if w:
            w.writeheader()
            w.writerows(out)
    print(f"\n{len(out):,} disagreements written to {path} (Gemini's matches first), for you to read: who is right?")


def sheet():
    """~45 disagreements, a mix of kinds, written so a person can judge each without opening anything else. No verdicts are pre-filled."""
    rows = [r for r in snapshot() if r["candidates"]]
    pairs = load_pairs()
    rng = random.Random(11)
    picked = []                                    # (heading, row, candidate, jev decision)

    def take(heading, sel, n):
        sel = list(sel)
        for r, c, act, p in (sel if len(sel) <= n else rng.sample(sel, n)):
            picked.append((heading, r, c, act, p))

    scored = []
    for r in rows:
        sc = pairs.get(r["extracted_id"])
        if not sc:
            continue
        act, uid, p, _ = decide(r, sc)
        g = GEM.get(r["gemini"])
        # the record under test: the one Gemini chose; else the one jev would pick; else retrieval's first offer (what Gemini's "top candidate" means)
        by_uid = {c["canonical_uid"]: c for c in r["candidates"]}
        cand = by_uid.get(r["gemini_uid"]) or by_uid.get(uid) or r["candidates"][0]
        scored.append((r, cand, g, act, p))
    sel = lambda g, j, lo=0.0, hi=1.0: [(r, c, a, p) for r, c, gg, a, p in scored if gg == g and a == j and lo <= p <= hi]
    take("Gemini said MATCH; jev said DIFFERENT (all of them)", sel("match", "new"), 5)
    take("Gemini said NEW (no match); jev said MATCH (all of them)", sel("new", "match"), 9)
    take("Gemini said AMBIGUOUS; jev said MATCH (all of them)", sel("ambiguous", "match"), 5)
    take("Gemini said AMBIGUOUS; jev said DIFFERENT (a random 10 of 202)", sel("ambiguous", "new"), 10)
    take("Gemini said MATCH; jev was doubtful, score below 0.5 (a random 7 of 37)", sel("match", "ambiguous", 0, 0.5), 7)
    take("Gemini said MATCH; jev was lukewarm, score 0.5 to 0.8 (a random 7 of 204)", sel("match", "ambiguous", 0.5, 0.8), 7)
    take("Control: Gemini said MATCH and jev agreed (a random 5, should be easy)", sel("match", "match", 0.9, 1), 5)

    ids = [r["extracted_id"] for _, r, *_ in picked]
    from src.shared.supabase_client import get_client
    cl = get_client()
    art = {e["id"]: e["article_id"] for e in cl.from_("extracted_entities").select("id,article_id").in_("id", ids).execute().data}
    urls = {a["id"]: a["url"] for a in cl.from_("article").select("id,url").in_("id", list(set(art.values()))).execute().data}

    out = ["# Judge jev against Gemini: " + str(len(picked)) + " examples", "",
           "For each one, decide: is the article's entity the same real-world person or body as the authority record shown?",
           "Then tick who was right. Nothing here is pre-judged. Gemini's own reasoning is shown because it is the answer under test.",
           "jev's numbers are the chance it gave that something is true (0 = no, 1 = yes). `same` is the one that decides; the others are shown for interest.", ""]
    rng.shuffle(picked)                              # mixed order, so the headings do not tell you the answer
    for i, (heading, r, c, act, p) in enumerate(picked, 1):
        sc = pairs[r["extracted_id"]][c["canonical_uid"]]
        out += [f"## {i}. {r['name_en'] or r['name']}" + (f"  ({r['name']})" if r["name_en"] and r["name_en"] != r["name"] else ""), "",
                f"*{r['published']}* · [{r['title']}]({urls.get(art.get(r['extracted_id']), '')})", "",
                f"**What the pipeline pulled from the article** ({KIND.get(r['type'], r['type'])}): {r['summary'] or '(empty)'}", ""]
        if r["quote_en"] or r["quote"]:
            out.append(f"> {r['quote_en'] or r['quote']}")
            if r["quote_en"] and non_latin(r["quote"]):
                out.append(f"> \n> {r['quote']}")
            out.append("")
        out += [f"**The authority record offered** (`{c['canonical_uid']}`): **{c['canonical_name']}**", ""]
        for k, v in trim_fields(c.get("canonical_fields")).items():
            out.append(f"- {k}: {v}")
        others = [x for x in r["candidates"] if x["canonical_uid"] != c["canonical_uid"]]
        if others:
            out += ["", "Other records the search offered (name, then jev's `same` for each):"]
            for x in others:
                f = x.get("canonical_fields") or {}
                out.append(f"- {x['canonical_name']} ({str(f.get('Occupation') or f.get('Description') or '')[:80]}): {pairs[r['extracted_id']].get(x['canonical_uid'], {}).get('same', float('nan')):.2f}")
        out += ["", f"**Gemini said:** {GEM_NAME.get(r['gemini'], r['gemini'])}" + (f" with `{r['gemini_uid']}`" if r["gemini_uid"] else ""),
                f"> {(r['gemini_why'] or '').strip()[:700]}", "",
                f"**jev said:** same = {sc['same']:.2f} · facts fit = {sc['facts']:.2f} · record conflicts = {sc['conflict']:.2f} · only the name matches = {sc['name_only']:.2f}", "",
                "**Your verdict:**  [ ] Gemini right   [ ] jev right   [ ] both wrong   [ ] cannot tell", "", "---", ""]
    out += ["", "## Key (kept at the end so it does not bias you)", ""]
    for i, (heading, r, *_ ) in enumerate(picked, 1):
        out.append(f"{i}. {heading}")
    (OUT / "evaluate.md").write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {OUT / 'evaluate.md'} ({len(picked)} examples)")


GEM_NAME = {"MATCH_AND_UPDATE": "MATCH (same entity)", "CREATE_NEW": "NEW (no record fits; this entity gets a new record)", "FLAG_AMBIGUOUS": "AMBIGUOUS (unsure; a person must decide)",
            "RE_QUERY_REQUIRED": "SEARCH AGAIN", "FLAG_DB_DUPLICATE": "THE FILE ALREADY HAS DUPLICATES"}


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    {"pilot": pilot, "run": run, "report": report, "sheet": sheet}.get(stage, lambda: sys.exit(__doc__))()
