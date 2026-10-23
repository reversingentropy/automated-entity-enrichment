"""The prompt onto the clipboard, the answer off it, and the answer's JSON out of whatever a chat wraps it in."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

POWERSHELL = shutil.which("powershell.exe")   # WSL: the Windows clipboard


def copy(path: Path) -> bool:
    """Put a UTF-8 file on the clipboard. False where there is no Windows clipboard to reach (CI, a Mac)."""
    if not POWERSHELL:
        return False
    try:
        win = subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True, check=True).stdout.strip()
        subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command",
                        f"Get-Content -Raw -Encoding UTF8 '{win}' | Set-Clipboard"], check=True, capture_output=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def paste() -> str | None:
    if not POWERSHELL:
        return None
    try:
        out = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command",
                              "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"],
                             capture_output=True, check=True).stdout
        return out.decode("utf-8")
    except (OSError, subprocess.CalledProcessError):
        return None


def shape(schema: type[BaseModel]) -> str:
    """
    The answer's shape, written out for a chat window. The API is given it separately (response_schema) and
    holds the model to it; a chat has only the text.
    """
    return ("Answer with one JSON object and nothing else: no markdown, no text before or after. "
            "It must match this JSON schema:\n" + json.dumps(schema.model_json_schema(), ensure_ascii=False))


CUT = "the answer stops before its end, so it looks cut short"


def wide(ch: str) -> bool:
    """Chinese and Japanese characters and their punctuation: text written without spaces between words."""
    return bool(ch) and ("　" <= ch <= "鿿" or "豈" <= ch <= "﫿" or "＀" <= ch <= "￯"
                         or "‘" <= ch <= "‟")


def unwrap(text: str) -> str:
    """
    Line breaks inside the JSON's strings taken out again.

    Copied out of a chat, a long answer can arrive broken into lines of about 80 characters, the breaks landing
    inside values, where JSON allows none: the first answer by hand (23 Oct 2026) was refused for exactly that.
    A break that replaced a space becomes a space again; one between two Chinese characters, where there was
    no space, is simply closed. Breaks between values are left alone: there JSON does not mind them.
    """
    out, i, inside = [], 0, False
    while i < len(text):
        ch = text[i]
        if inside and ch == "\\":
            out.append(text[i:i + 2])
            i += 2
            continue
        if ch == '"':
            inside = not inside
        elif inside and ch in " \t\r\n":
            j = i
            while j < len(text) and text[j] in " \t\r\n":
                j += 1
            if "\n" in text[i:j]:
                before = out[-1][-1:] if out else ""
                out.append("" if wide(before) and wide(text[j:j + 1]) else " ")
                i = j
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def closing(text: str) -> int | None:
    """Where the object opened by text[0] closes, or None if the text ends first."""
    depth, inside, i = 0, False, 0
    while i < len(text):
        ch = text[i]
        if inside:
            if ch == "\\":
                i += 1
            elif ch == '"':
                inside = False
        elif ch == '"':
            inside = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def parse(text: str, schema: type[T]) -> T:
    """
    The answer, checked as the API's would be. A chat often wraps JSON in ```json fences or adds a line
    before or after it, so only the object itself is read; and a copy can break long lines, so those breaks
    are mended first (unwrap). What is left must still be valid JSON of the right shape.
    """
    start = text.find("{")
    if start < 0:
        raise ValueError("there is no JSON object in it")
    body = unwrap(text[start:])
    end = closing(body)
    if end is None:
        raise ValueError(CUT)
    return schema.model_validate(json.loads(body[:end + 1], strict=False))
