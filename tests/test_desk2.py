"""
The second desk (prototype/desk.template.html), the one the reviewers chose, run in a headless browser.

Its screens are written as HTML strings, which the small DOM stand-in the first desk's tests use cannot run, so
these tests need Chromium (Playwright's headless shell is found on its own; DESK_CHROME points elsewhere). The
cards are real ones from a build of the deck (tests/fixtures/desk2_cards.json); nothing reaches a database.
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
    found += sorted(glob.glob(str(home / "chromium-*" / "chrome-linux64" / "chrome")), reverse=True)
    found += [shutil.which(n) or "" for n in ("chromium", "chromium-browser", "google-chrome")]
    return next((f for f in found if f and Path(f).exists()), None)


CHROME = chrome()
needs_chrome = pytest.mark.skipif(CHROME is None, reason="needs a headless Chromium")


def blob(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def run(page: str, tmp_path: Path, fragment: str = "") -> str:
    """Open the page headless, let its timers run, and return what it wrote into #selftest."""
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
    cards = FIXTURE["cards"]
    by = {c["key"]: c for c in cards}
    fake = {
        "deck": [{"key": c["key"], "card": c} for c in cards],
        # someone else decided the Singapore Institute of Technology, and holds Snow City; Clifford Centre is ours
        "reviews": [{"pid": by["uid:18491949"]["pids"][0], "card_key": "uid:18491949", "reviewer": "u2",
                     "decision": {"verdict": "approve", "reviewer": "Jo", "rows": [], "at": "2026-10-09T01:00:00Z"}}],
        "claims": [{"card_key": "uid:18773908", "reviewer": "u2", "claimed_at": "2026-10-09T01:00:00Z"},
                   {"card_key": "uid:20614903", "reviewer": "u1", "claimed_at": "2026-10-09T02:00:00Z"}],
        "desk": {"index": FIXTURE["index"], "npt": FIXTURE["npt"],
                 "status": {"published": "2026-10-09T04:52:00Z", "newest_news": "2026-10-08", "tte_dump": "TTE-DELTA", "steps": {}}},
        "mine": "uid:20614903", "theirs": "uid:18773908", "theirReview": "uid:18491949", "mixed": "uid:18338504",
    }
    page = online_page(TEMPLATE.read_text(encoding="utf-8"), "https://example.supabase.co", "anon")
    setup = ("<script>window.__FAKE__ = " + blob(fake) + ";"
             "try { localStorage.setItem('proto-langs', '[\"en\",\"zh\"]'); localStorage.setItem('desk2-welcomed', '1'); } catch (e) {}</script>\n"
             "<script>" + (ROOT / "tests" / "desk" / "app2_fake.js").read_text(encoding="utf-8") + "</script>")
    page = page.replace(f'<script src="{SUPABASE_JS}"></script>', setup)
    page = page.replace("</body>", "<script>" + (ROOT / "tests" / "desk" / "app2_drive.js").read_text(encoding="utf-8") + "</script>\n</body>")
    got = run(page, tmp_path)
    assert got.startswith("RESULT "), got
    out = json.loads(got[len("RESULT "):])
    failed = {k: v for k, v in out.items() if v is False}
    assert not failed, out
    assert out["cards"] == len(cards)
