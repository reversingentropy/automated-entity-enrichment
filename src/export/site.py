"""
The online desk: the same page as the zip, with a database behind it.

    python -m src.export --site data/dist/site
    python -m http.server -d data/dist/site 8000     # then open localhost:8000

Writes `index.html` and the explainer beside it. The page carries the
Supabase URL and the anon key, which is public by design: what it may read
and write is set by the policies in `sql/11_desk_online.sql`, not by the
key. The deck and the search index are fetched after sign-in, so the page
itself is small and holds nothing from TTE. It runs from a local folder or
from any static host; nothing in it depends on where it is served from.
"""

import json
import os
from pathlib import Path

from src.export.package import standalone

SUPABASE_JS = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js"


def online_page(template: str, url: str, anon_key: str) -> str:
    """The template as the online page: the client library and the keys in the head."""
    config = {"url": url, "anonKey": anon_key}
    head = (f'<script src="{SUPABASE_JS}"></script>\n'
            f"<script>window.__ONLINE__ = {json.dumps(config)};</script>\n")
    # The second desk is a whole document already: the two scripts go into its own head.
    if template.lstrip().lower().startswith("<!doctype"):
        at = template.lower().index("<head>") + len("<head>")
        return template[:at] + "\n" + head + template[at:]
    return standalone(template, head=head)


def build_site(template_path: str | Path, out_dir: str | Path) -> Path:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError("Set SUPABASE_URL and SUPABASE_ANON_KEY to build the site.")
    url, key = url.strip(), key.strip()
    # The two are easy to paste into each other's box, and the page then builds
    # fine and only fails when someone tries to sign in.
    if not url.startswith("https://") or key.startswith("http"):
        raise RuntimeError("SUPABASE_URL should look like https://xxxx.supabase.co and SUPABASE_ANON_KEY "
                           "like eyJ...: they look swapped or mistyped.")
    template = Path(template_path).read_text(encoding="utf-8")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    page = out / "index.html"
    page.write_text(online_page(template, url, key), encoding="utf-8")
    # The explainer, linked from the sign-in screen for anyone who arrives
    # without the briefing.
    explainer = Path("docs/pipeline.html")
    if explainer.exists():
        (out / "pipeline.html").write_text(standalone(explainer.read_text(encoding="utf-8")),
                                           encoding="utf-8")
    return page
