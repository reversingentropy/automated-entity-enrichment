"""Comments out of the served page (src/export/strip.py), and nothing else."""

from pathlib import Path

from src.export import strip
from src.export.site import online_page


def test_comments_go_and_strings_patterns_and_templates_stay():
    src = ('const a = "https://x.sg // not a comment"; // gone\n'
           "  // a line to itself, gone with its line\n"
           "const re = /\\/\\/|[/*]/g, half = 10 / 2 / 1; /* gone */ const b = 'it\\'s';\n"
           "const t = `a ${x ? `in ${y /* gone */}` : '//'} // kept, inside the template`;\n"
           "if (ok) return /^\\/*$/.test(s);\n")
    out = strip.js(src)
    assert "gone" not in out and "a line to itself" not in out
    assert '"https://x.sg // not a comment"' in out and "/\\/\\/|[/*]/g" in out and "10 / 2 / 1" in out
    assert "// kept, inside the template`" in out and "'//'" in out and "/^\\/*$/.test(s)" in out
    assert out.count("\n") == src.count("\n") - 1


def test_css_and_html_comments_go():
    html = ('<!-- about the page -->\n<style>\n  /* the colours */\n  a{content:"/* kept */"}\n</style>\n'
            "<p>Text</p><script>\n// note\nlet x = 1;</script>")
    out = strip.page(html)
    assert "about the page" not in out and "the colours" not in out and "note" not in out
    assert 'content:"/* kept */"' in out and "<p>Text</p>" in out and "let x = 1;" in out


def test_the_served_desk_carries_no_comments():
    page = online_page(Path("prototype/desk.template.html").read_text(encoding="utf-8"), "https://p.supabase.co", "anon")
    assert "<!--" not in page and "/*" not in page
    assert not [line for line in page.splitlines() if line.strip().startswith("//")]
