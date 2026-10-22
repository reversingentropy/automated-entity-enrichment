"""
The labelling guide (docs/labelling-guide.md), as the desk's Evaluation page shows it.

The guide is the prompts' rules in plain words, so a labeller checks the AI against what it was told. Each
task's section names the prompt files it was written from, with the first eight characters of each file's
SHA-256; `stale()` lists any that have changed since, and the tests stop on them, so a rule changed in a
prompt is never labelled against the old one without anyone noticing.

The site build (`python -m src.export --site`) puts the sections into the page; this reads only the little
Markdown the guide uses: `##` sections with an `{#id}`, `###` headings, `-` lists (nested by two spaces),
paragraphs, **bold**, *italic* and `code`.
"""

import hashlib
import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "labelling-guide.md"
SECTION = re.compile(r"^## (.+?) \{#(\w+)\}\s*$")
SOURCE = re.compile(r"`(prompts/[\w/.-]+)` \(version ([0-9a-f]{8})\)")


def version(path: str) -> str:
    """A prompt file's version code: the start of its SHA-256."""
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()[:8]


def _inline(text: str) -> str:
    t = html.escape(text, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", t)


def _list(lines: list[str]) -> str:
    out, depth = "", 0
    for line in lines:
        m = re.match(r"^( *)- (.*)$", line)
        if not m:                                   # a bullet carried on to the next line
            out += " " + _inline(line.strip())
            continue
        d = len(m.group(1)) // 2 + 1
        if d > depth:
            out += "<ul><li>"
            depth += 1
        else:
            while depth > d:
                out += "</li></ul>"
                depth -= 1
            out += "</li><li>"
        out += _inline(m.group(2))
    return out + "</li></ul>" * depth


def to_html(text: str) -> str:
    """One section's Markdown as HTML, block by block (blocks are separated by blank lines)."""
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.splitlines()
        if not lines:
            continue
        if lines[0].startswith("### "):
            out.append(f"<h3>{_inline(lines[0][4:].strip())}</h3>")
            lines = lines[1:]
        if not lines:
            continue
        if lines[0].lstrip().startswith("- "):
            out.append(_list(lines))
        else:
            out.append("<p>" + _inline(" ".join(x.strip() for x in lines)) + "</p>")
    return "".join(out)


def sections(path: Path = GUIDE) -> dict[str, dict]:
    """Each section by its id: its title, the prompts it was written from, and its rules."""
    found, key = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = SECTION.match(line)
        if m:
            key = m.group(2)
            found[key] = {"title": m.group(1), "lines": []}
        elif key:
            found[key]["lines"].append(line)
    out = {}
    for key, sec in found.items():
        body = "\n".join(sec["lines"])
        sources = [[p, v] for p, v in SOURCE.findall(body)]
        body = "\n".join(x for x in sec["lines"] if not x.startswith("Written from "))
        out[key] = {"title": sec["title"], "sources": sources, "html": to_html(body)}
    return out


def stale(path: Path = GUIDE) -> list[str]:
    """The prompt files changed since the guide was written from them, each with what to do."""
    out = []
    for key, sec in sections(path).items():
        for p, v in sec["sources"]:
            now = version(p)
            if now != v:
                out.append(f"{p} has changed since the {sec['title']} section of {path.name} was written from it "
                           f"(version {v}, now {now}). Read the change; if a rule changed, change the section to "
                           f"match; then set its version to {now}.")
    return out
