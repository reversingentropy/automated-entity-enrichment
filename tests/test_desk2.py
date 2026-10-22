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
    # Glenn's one desk decision: the date started (two parts) and the description accepted, the founder left out
    decision = {"verdict": "approve", "kind": "approved", "reviewer": "Glenn", "at": an_hour_ago,
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
