"""
One deck, in the redesigned review desk, for everything that needs a person's judgement from the jev work.

    .venv/bin/python scripts/jev_desk_audit.py     # writes data/dist/prototype-audit.html and data/jev/desk-audit-key.json

It replaces the separate audit files: the entities from the planted cards, the flagged cards and the fully automated flow's decisions are
built into ordinary desk cards (what Gemini proposed, exactly as a reviewer normally sees it), shuffled together, with no model verdict shown.
Decide each card in the desk as usual: same record / not this record / create / not worth a record / keep for review, then each change.
Then use "Your sheet" in the desk to download your decisions and give me the file; the key written here says which card was which.
Read-only on the database; the page needs no server.
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "prototype"))
import jev_replay as J
from build import blob
from src.export import cards
from src.shared.pagination import fetch_all
from src.shared.supabase_client import get_client

OUT = J.OUT


def sample():
    """extracted_id -> why it is in the deck."""
    why = {}
    for name, field in (("audit-key.json", "group"), ("audit-flagged-key.json", "kind"), ("flow-sample-key.json", "outcome")):
        for cid, v in json.loads((OUT / name).read_text(encoding="utf-8")).items():
            if name == "audit-key.json" and not v["group"].startswith("control"):
                continue
            why.setdefault(v["extracted_id"], []).append(f"{name.split('-')[0]}:{v[field]}")
    return why


def main():
    why = sample()
    client = get_client()
    ids = list(why)
    props = {}
    for i in range(0, len(ids), 80):
        for r in client.from_("candidate_matches").select("id,extracted_id").in_("extracted_id", ids[i:i + 80]).execute().data:
            props[r["id"]] = r["extracted_id"]
    flags = {}
    for i in range(0, len(ids), 80):
        for r in client.from_("extracted_entities").select("id,backfill").in_("id", ids[i:i + 80]).execute().data:
            flags[r["id"]] = bool(r.get("backfill"))
    print(f"{len(ids)} entities in the sample; {sum(flags.values())} from the archive, {len(flags) - sum(flags.values())} from the live feed")

    index, variants = cards.build_index(with_variants=True)
    dealt = []
    for mode in sorted(set(flags.values())):
        built, _ = cards.build_cards(include_new=True, backfill=mode, index=index, variants=variants)
        dealt += [c for c in built if any(p in props for p in c["pids"])]
    rng = random.Random(31)
    rng.shuffle(dealt)
    key, dealt_entities = {}, set()
    for n, c in enumerate(dealt):
        c["i"] = n
        eids = sorted({props[p] for p in c["pids"] if p in props})
        dealt_entities |= set(eids)
        key[c["key"]] = {"position": n + 1, "pids": c["pids"], "extracted_ids": eids, "why": sorted({w for e in eids for w in why[e]})}
    (OUT / "desk-audit-key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")

    desk = json.loads(client.storage.from_("desk").download("desk.json"))
    page = (ROOT / "prototype" / "desk.template.html").read_text(encoding="utf-8")
    assert page.count("/*__REVIEW__*/false") == 1
    page = page.replace("/*__REVIEW__*/false", "true")
    held_ = []
    idx = [[r[0], r[1], r[2], r[3], (r[4] or "")[:70]] for r in desk["index"]]
    for marker, value in (("/*__CARDS__*/[]", dealt), ("/*__INDEX__*/{ index: [], npt: {} }", {"index": idx, "npt": desk["npt"]}), ("/*__HELD__*/[]", held_)):
        assert page.count(marker) == 1, marker
        page = page.replace(marker, blob(value))
    out = ROOT / "data" / "dist" / "prototype-audit.html"
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} ({len(page) // 1024:,} KB): {len(dealt)} cards covering {len(dealt_entities)} of the {len(ids)} entities")
    print(f"not dealt as cards (the desk treats them as nothing to decide): {len(ids) - len(dealt_entities)}")


if __name__ == "__main__":
    main()
