"""
The second desk (prototype/desk.template.html), the one the reviewers chose, run in a headless browser.

Its screens are written as HTML strings, which the small DOM stand-in the first desk's tests use cannot run, so
these tests need Chrome's headless shell (Playwright's is found on its own; DESK_CHROME points elsewhere; CI
installs it). Not the full browser: with --dump-dom it never exits, even on a one-line page, and in CI, which has
Google Chrome installed, both tests waited out their two minutes and failed every push from 10 October. The cards
are real ones from a build of the deck (tests/fixtures/desk2_cards.json); nothing reaches a database.
"""

import glob
import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.export.site import SUPABASE_JS, online_page

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "prototype" / "desk.template.html"
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "desk2_cards.json").read_text(encoding="utf-8"))


def chrome() -> str | None:
    found = [os.environ.get("DESK_CHROME", "")]
    home = Path.home() / ".cache" / "ms-playwright"
    found += sorted(glob.glob(str(home / "chromium_headless_shell-*" / "chrome-headless-shell-linux64" / "chrome-headless-shell")), reverse=True)
    # older Playwright releases, such as the one CI installs, lay it out as chrome-linux/headless_shell
    found += sorted(glob.glob(str(home / "chromium_headless_shell-*" / "chrome-linux" / "headless_shell")), reverse=True)
    found += [shutil.which("chrome-headless-shell") or ""]
    return next((f for f in found if f and Path(f).exists()), None)


CHROME = chrome()
# CI sets this: there the shell is installed on purpose, so not finding it is a failure, not a skip. A skip passed
# quietly once, when the shell was installed where the search above did not look.
REQUIRED = bool(os.environ.get("DESK_REQUIRE_CHROME"))
needs_chrome = pytest.mark.skipif(CHROME is None and not REQUIRED,
                                  reason="needs Chrome's headless shell (uvx playwright install --only-shell chromium)")


def blob(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def run(page: str, tmp_path: Path, fragment: str = "") -> str:
    """Open the page headless, let its timers run, and return what it wrote into #selftest."""
    assert CHROME, "Chrome's headless shell was not found, and DESK_REQUIRE_CHROME says it should be there"
    path = tmp_path / "page.html"
    path.write_text(page, encoding="utf-8")
    done = subprocess.run([CHROME, "--headless", "--no-sandbox", "--disable-gpu", "--allow-file-access-from-files",
                           f"--user-data-dir={tmp_path / 'profile'}", "--virtual-time-budget=60000", "--dump-dom",
                           path.as_uri() + fragment], capture_output=True, text=True, timeout=120)
    m = re.search(r'<pre id="selftest"[^>]*>(.*?)</pre>', done.stdout, re.S)
    assert m, done.stderr[-2000:]
    return html.unescape(m.group(1))


@needs_chrome
def test_every_screen_of_every_card_draws(tmp_path):
    page = TEMPLATE.read_text(encoding="utf-8")
    page = page.replace("/*__CARDS__*/[]", blob(FIXTURE["cards"]))
    page = page.replace("/*__INDEX__*/{ index: [], npt: {} }", blob({"index": FIXTURE["index"], "npt": FIXTURE["npt"]}))
    got = run(page, tmp_path, "#selftest")
    assert got.startswith(f"selftest: {len(FIXTURE['cards'])} cards"), got
    assert ", 0 errors" in got.splitlines()[0], got


@needs_chrome
def test_the_desk_online_holds_saves_and_shares_records(tmp_path):
    from datetime import datetime, timedelta, timezone
    cards = FIXTURE["cards"]
    by = {c["key"]: c for c in cards}
    ago = lambda minutes: (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    jo = lambda key, verdict: [{"pid": pid, "card_key": key, "reviewer": "u2", "verdict": verdict, "at": ago(600),
                                "decision": {"verdict": verdict, "reviewer": "Jo", "rows": [], "at": ago(600),
                                             "kept_by": ["u2"] if verdict == "unsure" else []}} for pid in by[key]["pids"]]
    chee = by["uid:18581011"]
    fake = {
        "deck": [{"key": c["key"], "card": c} for c in cards],
        # Jo decided the Singapore Institute of Technology, kept Isa'ad for review, and is working on Snow City;
        # Clifford Centre was on this reviewer's desk when they last stopped
        "reviews": jo("uid:18491949", "approve") + jo("uid:18696145", "unsure"),
        "claims": [{"card_key": "uid:18773908", "reviewer": "u2", "claimed_at": ago(10)},
                   {"card_key": "uid:20614903", "reviewer": "u1", "claimed_at": ago(5)}],
        "desk": {"index": FIXTURE["index"], "npt": FIXTURE["npt"],
                 "status": {"published": "2026-10-09T04:52:00Z", "newest_news": "2026-10-08", "tte_dump": "TTE-DELTA", "steps": {}}},
        "mineKey": "uid:20614903", "theirs": "uid:18773908", "theirReview": "uid:18491949", "keptByJo": "uid:18696145",
        "mixed": "uid:18338504",
        "newChange": next(ch for ch in chee["changes"] if ch["field"] == "Affiliations(groupName)"),
    }
    out = online(fake, "app2_drive.js", tmp_path)
    assert out["cards"] == len(cards)


def online(fake: dict, driver: str, tmp_path: Path) -> dict:
    """The page as the site serves it, against the stand-in for Supabase, driven by tests/desk/<driver>."""
    page = online_page(TEMPLATE.read_text(encoding="utf-8"), "https://example.supabase.co", "anon")
    setup = ("<script>window.__FAKE__ = " + blob(fake) + ";"
             "try { localStorage.setItem('proto-langs', '[\"en\",\"zh\"]'); localStorage.setItem('desk2-welcomed', '1'); } catch (e) {}</script>\n"
             "<script>" + (ROOT / "tests" / "desk" / "app2_fake.js").read_text(encoding="utf-8") + "</script>")
    page = page.replace(f'<script src="{SUPABASE_JS}"></script>', setup)
    page = page.replace("</body>", "<script>" + (ROOT / "tests" / "desk" / driver).read_text(encoding="utf-8") + "</script>\n</body>")
    got = run(page, tmp_path)
    assert got.startswith("RESULT "), got
    out = json.loads(got[len("RESULT "):])
    failed = {k: v for k, v in out.items() if v is False}
    assert not failed, out
    return out


@needs_chrome
def test_the_evaluation_page_deals_rows_and_saves_labels(tmp_path):
    from datetime import datetime, timedelta, timezone
    cards = FIXTURE["cards"]
    zh = lambda n: n in (3, 55)          # one shared row and one dealt row an English reader is never given
    rel = [{"task": "relevance", "ord": n, "lang": "zh" if zh(n) else "en",
            "item": f"https://www.{'zaobao.com/news/singapore' if zh(n) else 'straitstimes.com/singapore'}/r{n}",
            "body": {"source": "", "published": "2026-09-16", "title": f"Headline {n}", "description": f"Summary {n}"}}
           for n in range(1, 56)]
    for r in rel:
        r["body"]["url"] = r["item"]
    match = [{"task": "matching", "item": str(500 + n), "ord": n, "lang": "en",
              "body": {"name": "Lee Theng Kiat", "name_en": "", "evidence": "Mr Lee Theng Kiat will chair the board.",
                       "article": "New chairman for the board", "url": "https://www.channelnewsasia.com/singapore/m",
                       "tte_id": "18500001", "tte_name": "Lee, Theng Kiat", "tte_fields": [["Occupation", "Civil servant"]]}}
             for n in (1, 2, 3)]
    ext = [{"task": "extraction", "item": "https://www.channelnewsasia.com/business/a1", "ord": 1, "lang": "en",
            "body": {"url": "https://www.channelnewsasia.com/business/a1", "title": "Robot maker raises funds",
                     "names": [{"entity": "Acme Robotics", "type": "ORGANISATION", "evidence": "Acme Robotics raised $5 million.",
                                "fields": [["Country", "Singapore"], ["Founder", "Chng Siew Hern"]]},
                               {"entity": "Chng Siew Hern", "type": "PERSON", "evidence": "founded by Chng Siew Hern", "fields": []}],
                     "text": "Acme Robotics, founded by Chng Siew Hern, raised $5 million.\n\nIts adviser Lim Bee Hoon said the money would go to hiring."}},
           {"task": "extraction", "item": "https://www.straitstimes.com/singapore/a2", "ord": 2, "lang": "en",
            "body": {"url": "https://www.straitstimes.com/singapore/a2", "title": "Library reopens",
                     "names": [{"entity": "Woodlands Regional Library", "type": "ORGANISATION", "evidence": "Woodlands Regional Library reopened.",
                                "fields": [["Country", "Singapore"]]}],
                     "text": ""}}]
    an_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    card = cards[0]
    # One reviewer's desk decision: the date started (two parts) and the description accepted, the founder left out
    decision = {"verdict": "approve", "kind": "approved", "reviewer": "Alex", "at": an_hour_ago,
                "link": "https://www.zaobao.com/news/singapore/x",
                "rows": [{"field": "Day Started (dd)", "current": "01", "proposed": "16", "from": "https://www.zaobao.com/news/singapore/x"},
                         {"field": "Description", "current": "", "proposed": "A maker of robots.", "from": "https://www.zaobao.com/news/singapore/x"}],
                "dropped": ["Month Started (mm)", "Founder"]}
    fake = {
        "deck": [{"key": c["key"], "card": c} for c in cards],
        "reviews": [{"pid": card["pids"][0], "card_key": card["key"], "reviewer": "u1", "verdict": "approve", "at": an_hour_ago, "decision": decision}],
        "claims": [],
        "desk": {"index": FIXTURE["index"], "npt": FIXTURE["npt"],
                 "status": {"published": "2026-10-09T04:52:00Z", "newest_news": "2026-10-08", "tte_dump": "TTE-DELTA", "steps": {}}},
        "evalItems": rel + match + ext,
        "evalResults": [{"id": 1, "at": "2026-10-21T08:00:00Z", "report": "RELEVANCE\n  precision 0.91 <weighted>"}],
    }
    online(fake, "app2_eval_drive.js", tmp_path)


def dom(page: str, tmp_path: Path, fragment: str) -> str:
    """Open the page headless at one screen and return the text of what it drew."""
    assert CHROME, "Chrome's headless shell was not found, and DESK_REQUIRE_CHROME says it should be there"
    path = tmp_path / "screen.html"
    path.write_text(page, encoding="utf-8")
    done = subprocess.run([CHROME, "--headless", "--no-sandbox", "--disable-gpu", "--allow-file-access-from-files",
                           f"--user-data-dir={tmp_path / 'profile'}", "--virtual-time-budget=20000", "--dump-dom",
                           path.as_uri() + fragment], capture_output=True, text=True, timeout=120)
    m = re.search(r'<div id="stage"[^>]*>(.*)', done.stdout, re.S)
    assert m, done.stderr[-2000:]
    return html.unescape(re.sub(r"<[^>]+>", " ", m.group(1).split("<script")[0]))


@needs_chrome
def test_nothing_a_source_said_is_out_of_sight(tmp_path):
    """
    docs/merging-values.md. Similar values are shown and linked, never merged; each carries only its own sources;
    a single-value field given two values offers both; a description shows its other wordings and held-back sentences.
    """
    import copy
    from src.export.cards import collapse
    c = copy.deepcopy(next(x for x in FIXTURE["cards"] if x["entity"] == "Tommy Koh"))
    s = [x["link"] for x in c["sources"]]
    before = "Diplomat and law professor."
    desc = lambda add, src: {"field": "Description", "strategy": "MERGE", "existing": [before], "adding": before + " " + add, "from": src}
    aw = lambda v, src: {"field": "Awards", "strategy": "APPEND", "existing": [], "adding": v, "from": src}
    c["changes"] = collapse([
        aw("World's Best Economy Class (2026) | World's Best Economy Class Onboard Catering (2026)", s[0]),
        aw("Skytrax World's Best Economy Class (2026)", s[1]),
        {"field": "Title", "strategy": "REPLACE", "existing": ["Ambassador"], "adding": "Ambassador-at-Large", "from": s[0]},
        {"field": "Title", "strategy": "REPLACE", "existing": ["Ambassador"], "adding": "Professor", "from": s[2]},
        # Changi Air Base East: three papers on one runway, two dates
        desc("It is being expanded for the relocation of Paya Lebar Air Base, and a new runway became operational on September 17, 2026.", s[0]),
        desc("It is being expanded for the relocation of Paya Lebar Air Base, and a new 3,660-metre runway was commissioned on September 28, 2026.", s[1]),
    ])
    page = TEMPLATE.read_text(encoding="utf-8")
    page = page.replace("/*__CARDS__*/[]", blob([c]))
    page = page.replace("/*__INDEX__*/{ index: [], npt: {} }", blob({"index": FIXTURE["index"], "npt": FIXTURE["npt"]}))
    screens = [" ".join(dom(page, tmp_path, f"#c=0&s=change&i={i}&cand=0").split()) for i in range(3)]
    awards = next(t for t in screens if "Add this to the awards?" in t)
    for v in ("World's Best Economy Class (2026)", "World's Best Economy Class Onboard Catering (2026)",
              "Skytrax World's Best Economy Class (2026)"):
        assert v in awards
    # one row per award: the two wordings of Best Economy Class are one row, the other wording under it
    assert awards.count("also written") == 1 and "may be the same as" not in awards and "sources say this" not in awards
    assert "+ Skytrax World's Best Economy Class (2026)" in awards and "also written “World's Best Economy Class (2026)”" in awards
    title = next(t for t in screens if "Set the title to this?" in t)
    assert "The sources disagree. Keep the one you trust:" in title and "Ambassador-at-Large" in title and "Keep both" not in title
    text = next(t for t in screens if "description?" in t or "description like this?" in t)
    assert "different numbers or dates" in text and "also written" in text and "September 28" in text


@needs_chrome
def test_a_description_is_one_row_per_new_fact(tmp_path):
    """docs/descriptions.md: one paragraph, TTE's words then the new sentences, the combined addition when there is one."""
    import copy
    from src.combine import draft_key
    from src.export.cards import collapse, description_rows
    c = copy.deepcopy(next(x for x in FIXTURE["cards"] if x["entity"] == "Tommy Koh"))
    s = [x["link"] for x in c["sources"]]
    for i, x in enumerate(c["sources"]):
        x["pid"] = 100 + i
    before = "Diplomat and law professor. He served as Ambassador-at-Large from 1990."
    desc = lambda add, src: {"field": "Description", "strategy": "MERGE", "existing": [before], "adding": before + " " + add, "from": src}
    notes = collapse([desc("He retired from the Ministry of Foreign Affairs in August 2026.", s[0]),
                      desc("He retired from the Foreign Ministry in August 2026.", s[1]),
                      desc("He won the Ramon Magsaysay Award in 2026.", s[2])])
    page = lambda card: (TEMPLATE.read_text(encoding="utf-8").replace("/*__CARDS__*/[]", blob([card]))
                         .replace("/*__INDEX__*/{ index: [], npt: {} }", blob({"index": FIXTURE["index"], "npt": FIXTURE["npt"]})))
    # before combining: each article's sentences, wordings of one fact as one row
    own = copy.deepcopy(c)
    own["changes"] = copy.deepcopy(notes)
    description_rows(own, own["changes"][0], {})
    got = " ".join(dom(page(own), tmp_path, "#c=0&s=change&i=0&cand=0").split())
    assert "Add this to the description?" in got and "also written" in got
    assert "Diplomat and law professor. He served as Ambassador-at-Large from 1990. He retired from" in got
    assert got.count("Ramon Magsaysay Award in 2026") == 1 and "Rewrite" not in got
    # combined: its sentences, the disagreement, and the correction made in place, struck and replaced
    draft = {"ok": True, "add": [{"text": "He retired from the Ministry of Foreign Affairs in August 2026.", "sources": [s[0], s[1]]}],
             "left_out": [{"text": "He won the Ramon Magsaysay Award in 2026.", "sources": [s[2]]}],
             "disagreements": [{"about": "the month he retired", "values": [{"value": "August", "sources": [s[0]]}, {"value": "July", "sources": [s[1]]}]}],
             "corrections": [{"quote": "from 1990", "with": "from 1990 to 2026", "sources": [s[0]]}]}
    comb = copy.deepcopy(c)
    comb["changes"] = copy.deepcopy(notes)
    description_rows(comb, comb["changes"][0], {draft_key(comb, comb["changes"][0]): draft})
    got = " ".join(dom(page(comb), tmp_path, "#c=0&s=change&i=0&cand=0").split())
    assert "The sources disagree on the month he retired" in got
    assert "Left out to keep within five sentences" in got and "+ Add" in got
    assert "Ambassador-at-Large from 1990 1990 to 2026" in got   # "from" kept, "1990" struck and "Correct it" not in got
    assert "in August 2026." in got.split("Left out")[0] and "Ramon Magsaysay" in got.split("Left out")[1]
