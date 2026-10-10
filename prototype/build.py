"""
Build the standalone design prototype of the review desk: every current card, offline.

    uv run python prototype/build.py            # writes data/dist/prototype.html
    uv run python prototype/build.py --review   # data/dist/prototype-review.html: no prototype toolbar, for reviewers
    uv run python prototype/build.py --review --fresh --out data/dist/tea-app.html

Reads the deck, the search index and the held cards from the database (read-only)
and fills them into desk.template.html. Nothing is written back. The page needs no
server: open it in a browser. --fresh builds the cards with the current card builder
instead of taking the last published deck, so builder fixes show before the next
publish; --out writes somewhere other than the default file.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.shared.pagination import fetch_all  # noqa: E402
from src.shared.supabase_client import get_client  # noqa: E402


def blob(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def main():
    client = get_client()
    if "--fresh" in sys.argv:
        from src.export.cards import build_cards, build_index, npt_map
        full, variants = build_index(with_variants=True)
        cards, _ = build_cards(index=full, variants=variants)
        desk = {"index": full, "npt": npt_map(variants, full)}
    else:
        deck = fetch_all(lambda: client.from_("deck").select("key,card"), order="key")
        cards = [r["card"] for r in deck]
        desk = json.loads(client.storage.from_("desk").download("desk.json"))
    cards = sorted(cards, key=lambda c: c["i"])
    index = [[r[0], r[1], r[2], r[3], (r[4] or "")[:70]] for r in desk["index"]]
    held = [{"key": r["card_key"], "since": r["claimed_at"][:16]}
            for r in client.from_("claims").select("card_key,claimed_at").execute().data]

    review = "--review" in sys.argv
    page = (ROOT / "prototype" / "desk.template.html").read_text(encoding="utf-8")
    assert page.count("/*__REVIEW__*/false") == 1
    page = page.replace("/*__REVIEW__*/false", "true" if review else "false")
    for marker, value in (("/*__CARDS__*/[]", cards), ("/*__INDEX__*/{ index: [], npt: {} }", {"index": index, "npt": desk["npt"]}),
                          ("/*__HELD__*/[]", held)):
        assert page.count(marker) == 1, marker
        page = page.replace(marker, blob(value))
    out = ROOT / "data" / "dist" / ("prototype-review.html" if review else "prototype.html")
    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1]).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote {out} ({len(page) // 1024:,} KB): {len(cards)} cards, {len(index):,} searchable records, {len(held)} held")


if __name__ == "__main__":
    main()
