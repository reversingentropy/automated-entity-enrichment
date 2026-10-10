"""
The review desk, driven headless.

The page is built from the template with an empty deck and run under a small
DOM stand-in in node, through the three practice records, which need no
database and between them reach every screen. It caught a page that would not
parse the day before it existed; a syntax error anywhere in the script means
no screen renders at all, and nothing else here would notice.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_desk_runs_through_the_practice_records(tmp_path):
    from src.export.package import build

    page = build((ROOT / "src/export/desk_template.html").read_text(encoding="utf-8"))
    scripts = re.findall(r"<script>([\s\S]*?)</script>", page)
    (tmp_path / "page.js").write_text("\n;\n".join(scripts), encoding="utf-8")
    for name in ("shim.mjs", "drive.mjs"):
        shutil.copy(ROOT / "tests/desk" / name, tmp_path / name)
    run = subprocess.run(["node", str(tmp_path / "drive.mjs"), str(tmp_path / "page.js")],
                         capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    assert run.stdout.rstrip().endswith("PASS"), run.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_desk_runs_online_against_a_stand_in_database(tmp_path):
    """
    The same page, served with `window.__ONLINE__`: the deck from the table,
    every decision to the table, a card one reviewer's while they hold it.
    """
    from src.export.site import online_page

    page = online_page((ROOT / "src/export/desk_template.html").read_text(encoding="utf-8"),
                       "https://example.supabase.co", "anon-key")
    scripts = re.findall(r"<script>([\s\S]*?)</script>", page)
    (tmp_path / "page.js").write_text("\n;\n".join(scripts), encoding="utf-8")
    for name in ("shim.mjs", "online.mjs"):
        shutil.copy(ROOT / "tests/desk" / name, tmp_path / name)
    run = subprocess.run(["node", str(tmp_path / "online.mjs"), str(tmp_path / "page.js")],
                         capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    assert run.stdout.rstrip().endswith("PASS"), run.stdout
