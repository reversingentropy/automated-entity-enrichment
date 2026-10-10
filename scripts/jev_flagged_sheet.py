"""
A slow-read sheet of cards the second model (jev) flagged that were NOT in the audit, so a person can check whether its flags are real.

    .venv/bin/python scripts/jev_flagged_sheet.py        # writes data/jev/audit-flagged.md

Four kinds, mixed and unlabelled: a change the article's quote contradicts; a change the quote says nothing about (high confidence);
an entity jev thinks is a different record from the one Gemini matched; and two records, one Gemini chose and one jev prefers, for the
person to pick between (shown as A and B in random order). The page shows no model verdicts: the key goes to data/jev/audit-flagged-key.json.
"""
import html
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jev_fair as F
import jev_pipeline as P
import jev_replay as J
from src.export import cards

OUT = J.OUT
rng = random.Random(9)


def main():
    snap = {r["extracted_id"]: r for r in J.snapshot()}
    dec = F.listwise_decisions()
    cx = F.context()
    matched = {m["extracted_id"]: m for m in json.loads((OUT / "matched.json").read_text(encoding="utf-8"))}
    upd = P.load_answers(OUT / "updates.jsonl")
    used = {v["extracted_id"] for v in json.loads((OUT / "audit-key.json").read_text(encoding="utf-8")).values()}
    ok = lambda r: r and (r["summary"] or "").strip() and r["summary"].strip().lower() != "test"

    def ev(eid, m):
        return [(u, upd.get(f"{eid}|{u['field']}", {}).get("evidence")) for u in m["field_updates"]]

    contra, nothing, ident = [], [], []
    for eid, m in matched.items():
        r = snap.get(eid)
        if eid in used or not ok(r):
            continue
        e = ev(eid, m)
        c = [x for _, x in e if x and x["choice"] == "contradicts" and x["confidence"] >= 0.3]
        if c:
            contra.append((max(x["confidence"] for x in c), eid))
        elif any(x and x["choice"] == "says_nothing" and x["confidence"] >= 0.99 and u["field"] != "Description" for u, x in e):
            nothing.append(eid)
        d = dec.get(eid)
        if d and (d["action"] != "match" or d["top"] != r["gemini_uid"]) and d["p"] >= 0.6:
            ident.append((d["p"], eid))
    picks = [(e, "contradicts") for _, e in sorted(contra, reverse=True)[:5]] + [(e, "says-nothing") for e in rng.sample(nothing, 5)]
    picks += [(e, "identity") for _, e in sorted(ident, reverse=True)[:4] if e not in {p for p, _ in picks}]

    # two records to choose between: Gemini's and jev's top, for the cases where they differ (pairwise scores)
    ans = P.load_answers(OUT / "fair-id-u.jsonl")
    twin = []
    for r in snap.values():
        if r["gemini"] != "MATCH_AND_UPDATE" or not r["gemini_uid"] or r["extracted_id"] in used or len(r["candidates"]) < 2:
            continue
        sc = {c["canonical_uid"]: F.p_of(ans[f"{r['extracted_id']}|{c['canonical_uid']}"]) for c in r["candidates"] if f"{r['extracted_id']}|{c['canonical_uid']}" in ans}
        if len(sc) == len(r["candidates"]) and r["gemini_uid"] in sc and max(sc, key=sc.get) != r["gemini_uid"]:
            twin.append((r["extracted_id"], max(sc, key=sc.get), sc))
    wanted = ("Chee Hong Tat", "Tan, Chuan-Jin", "Gambling Regulatory Authority", "WongPartnership")
    twin = [t for t in twin if (snap[t[0]]["name_en"] or snap[t[0]]["name"]) in wanted and t[0] not in {e for e, _ in picks}]
    picks += [(e, "two-records") for e, _, _ in twin]
    twin_top = {e: top for e, top, _ in twin}
    rng.shuffle(picks)

    from src.shared.supabase_client import get_client
    cl = get_client()
    aids = list({cx[e]["article_id"] for e, _ in picks})
    urls = {a["id"]: a["url"] for a in cl.from_("article").select("id,url").in_("id", aids).execute().data}
    md = [f"# {len(picks)} more cards to read slowly", "",
          "These are cards a second model flagged, mixed in no particular order, with nothing said about why. Open each article link and read the card against the **article**, not only the quote shown.", "",
          "For each: is the record right, and is every proposed change true according to the article? For the two-record cards, which record (A or B) is the one the article is about?", ""]
    key = {}
    for i, (eid, kind) in enumerate(picks, 1):
        r, m = snap[eid], matched[eid]
        cid = f"f{i:02d}"
        by_uid = {c["canonical_uid"]: c for c in m["candidates"]}
        md += [f"## {cid}: {r['name_en'] or r['name']}" + (f" ({r['name']})" if r["name_en"] and r["name_en"] != r["name"] else ""), "",
               f"*Published {r['published']}* · [{html.unescape(r['title'])}]({urls.get(cx[eid]['article_id'], '')})", "", f"**Pipeline's summary:** {r['summary']}", ""]
        q = r["quote_en"] or (r["quote"] if not J.non_latin(r["quote"]) else "")
        md += [f"> {q}"] + ([f"> {r['quote']}"] if q and J.non_latin(r["quote"]) else []) + [""]
        if kind == "two-records":
            pair = [r["gemini_uid"], twin_top[eid]]
            rng.shuffle(pair)
            for L, uid in zip("AB", pair):
                c = by_uid[uid]
                md += [f"**Record {L}:** {c['canonical_name']} (`{uid}`)"] + [f"- {k}: {v}" for k, v in F.whole(c.get("canonical_fields")).items() if k != "Description"][:7]
                d = str((c.get("canonical_fields") or {}).get("Description") or "")
                md += ([f"- Description: {d[:420]}"] if d else []) + [""]
            md += ["**Your verdict:**  [ ] A is right   [ ] B is right   [ ] they are duplicates of each other   [ ] neither   [ ] cannot tell", "", "---", ""]
            key[cid] = {"extracted_id": eid, "kind": kind, "gemini_uid": r["gemini_uid"], "jev_uid": twin_top[eid], "A": pair[0], "B": pair[1]}
            continue
        cand = by_uid[r["gemini_uid"]]
        md += [f"**Record it would update:** {cand['canonical_name']} (`{cand['canonical_uid']}`)"] + [f"- {k}: {v}" for k, v in F.whole(cand.get("canonical_fields")).items() if k != "Description"][:6]
        d0 = str((cand.get("canonical_fields") or {}).get("Description") or "")
        md += ([f"- Description: {d0[:420]}"] if d0 else []) + [""]
        for u in m["field_updates"]:
            have = str((cand["canonical_fields"] or {}).get(u["field"]) or "")
            if u["strategy"] == "MERGE" and have:
                parts = cards.diff_parts(have, u["value"])
                new = " ".join(p["text"] for p in parts if p["op"] == "in"); gone = " ".join(p["text"] for p in parts if p["op"] == "out")
                md.append(f"- **{u['field']}** (rewrite): adds _{new}_" + (f"; removes _{gone}_" if gone else ""))
            else:
                md.append(f"- **{u['field']}** ({u['strategy'].lower()}): _{u['value']}_" + (f" (record had: {have})" if have else ""))
        md += ["", "**Your verdict after reading:**  [ ] fine to let through   [ ] wrong record   [ ] a change is wrong or unsupported   [ ] broken text   [ ] cannot tell", "", "---", ""]
        key[cid] = {"extracted_id": eid, "kind": kind, "quote_checks": [{"field": u["field"], "choice": x and x["choice"], "conf": x and round(x["confidence"], 2)} for u, x in ev(eid, m)],
                    "jev_top": dec[eid]["top"], "jev_p": round(dec[eid]["p"], 3)}
    (OUT / "audit-flagged.md").write_text("\n".join(md), encoding="utf-8")
    (OUT / "audit-flagged-key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print(f"wrote {OUT / 'audit-flagged.md'}: {len(picks)} cards {dict(Counter(k for _, k in picks))}")


if __name__ == "__main__":
    main()
