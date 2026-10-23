"""
Comments taken out of a page before it is served.

The template keeps its comments for whoever maintains it; the page Cloudflare serves to anyone with the link
carries none (23 Oct 2026). HTML comments go, and so do comments inside <style> and <script>. Strings, template
literals and regular expressions are read as such, so a "//" inside a URL, a string or a pattern stays.
"""

import re

REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^") | {""}
REGEX_WORDS = {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw", "instanceof", "yield", "await"}


def _blank_line_end(out: list[str]) -> bool:
    """Whether what is written since the last newline is only spaces: a comment that had a line to itself."""
    tail = "".join(out[-40:]).rsplit("\n", 1)[-1]
    return tail.strip() == ""


def _drop_indent(out: list[str]) -> None:
    while out and out[-1] in (" ", "\t"):
        out.pop()


def _quoted(src: str, i: int, quote: str) -> int:
    """Index just past the string opened at src[i]."""
    j = i + 1
    while j < len(src) and src[j] != quote:
        j += 2 if src[j] == "\\" else 1
    return j + 1


def _regex(src: str, i: int) -> int:
    """Index just past the regular expression opened at src[i], flags included."""
    j, in_class = i + 1, False
    while j < len(src) and src[j] != "\n":
        ch = src[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            j += 1
            while j < len(src) and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            return j
        j += 1
    raise ValueError(f"an unclosed regular expression at character {i}")


def _before(out: list[str]) -> str:
    """The last thing written that is not a space: a character, or a whole word."""
    tail = "".join(out[-60:]).rstrip()
    if not tail:
        return ""
    word = re.search(r"[A-Za-z_$][\w$]*$", tail)
    return word.group(0) if word else tail[-1]


def js(src: str) -> str:
    out: list[str] = []
    braces: list[int] = []          # for each template literal's open ${ }, the brace depth it opened at
    depth, i = 0, 0
    while i < len(src):
        ch, nxt = src[i], src[i + 1:i + 2]
        if ch in "'\"":
            j = _quoted(src, i, ch)
            out.append(src[i:j])
            i = j
        elif ch == "`" or (ch == "}" and braces and braces[-1] == depth):
            if ch == "}":
                braces.pop()
            j = i + 1
            while j < len(src) and src[j] != "`" and src[j:j + 2] != "${":
                j += 2 if src[j] == "\\" else 1
            if src[j:j + 2] == "${":
                out.append(src[i:j + 2])
                braces.append(depth)
                i = j + 2
            else:
                out.append(src[i:j + 1])
                i = j + 1
        elif ch == "/" and nxt == "/":
            j = src.find("\n", i)
            j = len(src) if j < 0 else j
            if _blank_line_end(out):
                _drop_indent(out)
                j += 1                   # the line goes with it
            i = j
        elif ch == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            if j < 0:
                raise ValueError(f"an unclosed comment at character {i}")
            body = src[i:j + 2]
            i = j + 2
            if _blank_line_end(out) and src[i:i + 1] in ("\n", ""):
                _drop_indent(out)
                i += 1
            else:
                out.append("\n" if "\n" in body else " ")   # a line break can end a statement; keep it
        elif ch == "/" and (_before(out) in REGEX_AFTER or _before(out) in REGEX_WORDS):
            j = _regex(src, i)
            out.append(src[i:j])
            i = j
        else:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            out.append(ch)
            i += 1
    return "".join(out)


def css(src: str) -> str:
    out, i = [], 0
    while i < len(src):
        ch = src[i]
        if ch in "'\"":
            j = _quoted(src, i, ch)
            out.append(src[i:j])
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0:
                raise ValueError(f"an unclosed comment at character {i}")
            i = j + 2
            if _blank_line_end(out) and src[i:i + 1] == "\n":
                _drop_indent(out)
                i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


BLOCK = re.compile(r"(<script\b[^>]*>)(.*?)(</script>)|(<style\b[^>]*>)(.*?)(</style>)|<!--.*?-->\n?", re.S | re.I)


def page(html: str) -> str:
    """The whole document with its comments taken out."""
    def one(m: re.Match) -> str:
        if m.group(1):
            return m.group(1) + js(m.group(2)) + m.group(3)
        if m.group(4):
            return m.group(4) + css(m.group(5)) + m.group(6)
        return ""
    return BLOCK.sub(one, html)
