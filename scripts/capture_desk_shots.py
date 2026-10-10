"""
Screenshots of the redesigned review desk for the talk, taken from the offline prototype with headless Chromium.

    uv run python prototype/build.py --review      # first: data/dist/prototype-review.html, from the live deck (read-only)
    .venv/bin/python scripts/capture_desk_shots.py # then: data/slides/desk-new-*.png

Drives the page over the Chrome DevTools protocol (the `websockets` package, already in the project's environment) and
reads only a local file. It needs the Chromium that Playwright caches under ~/.cache/ms-playwright.
Cards are named by their position in the deck, which changes as the deck is rebuilt: 163 Gerard Ee, 164 Anita Fam,
178 李全盛, 202 Tang See Chim, 218 林泉宝 (Lim Chuan Poh). Look the index up again before re-running on a newer deck.
"""

import asyncio
import base64
import io
import json
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "data/dist/prototype-review.html").as_uri()
OUT = ROOT / "data/slides"
PORT = 9333
LEFT, RIGHT, TOP = 310, 1812, 176      # the card column of a 2x screenshot


def trim(png: bytes, name: str, welcome: bool = False):
    """Crop to the card column, down to the last row that holds anything but page background."""
    im = Image.open(io.BytesIO(png)).convert("RGB")
    if welcome:
        im = im.crop((186, 226, 1786, 1294))
    else:
        column = im.crop((LEFT, TOP, RIGHT, im.height))
        bg = Image.new("RGB", column.size, im.getpixel((im.width - 20, 700)))
        marked = ImageChops.difference(column, bg).convert("L").point(lambda v: 255 if v > 12 else 0)
        im = column.crop((0, 0, column.width, min(column.height, marked.getbbox()[3] + 28)))
    im.save(OUT / f"{name}.png", optimize=True)
    print("saved", name, im.size, flush=True)


async def shoot(ws_url):
    async with websockets.connect(ws_url, max_size=None) as ws:
        n = 0

        async def call(method, **params):
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": method, "params": params}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == n:
                    if "error" in msg:
                        raise RuntimeError(f"{method}: {msg['error']}")
                    return msg.get("result", {})

        async def js(code):
            return await call("Runtime.evaluate", expression=code, returnByValue=True)

        async def keep(name, welcome=False):
            await asyncio.sleep(0.8)
            trim(base64.b64decode((await call("Page.captureScreenshot", format="png"))["data"]), name, welcome)

        go_to = '(() => { const c = card(), st = stOf(c), rows = rowsFor(c, chosenOpt(c, st)); st.screen = "change"; st.ch = rows.findIndex(r => r.field.startsWith("%s")); draw(); })()'
        show = 'PAGE="review"; if (LIST.indexOf(%d) < 0) LIST.unshift(%d); cur = LIST.indexOf(%d); draw();'
        await call("Page.enable")
        await call("Emulation.setDeviceMetricsOverride", width=1000, height=1100, deviceScaleFactor=2, mobile=False)
        await call("Page.navigate", url=PAGE)
        await asyncio.sleep(3)
        await js('localStorage.setItem("proto-langs", JSON.stringify(["en","zh"]))')   # so the language question is already answered
        await call("Page.navigate", url=PAGE)
        await asyncio.sleep(3)
        await keep("desk-new-welcome", welcome=True)        # the opening picture a first-time user meets
        await js('act("closewelcome")')
        await js(show % (163, 163, 163))
        await keep("desk-new-identity")                     # Gerard Ee: is this the same person?
        await js(show % (164, 164, 164)); await js('act("same")'); await js('act("accept")')
        await keep("desk-new-fam-change")                   # Anita Fam: her affiliation, quoted with her awards sentence
        await js(show % (178, 178, 178))
        await keep("desk-new-lee-identity")                 # 李全盛: aged 71 against a record born in 1888
        await js(show % (218, 218, 218)); await js('act("same")'); await js(go_to % "Description")
        await keep("desk-new-lim-diff")                     # Lim Chuan Poh: the rewrite and its warning
        await js(show % (202, 202, 202)); await js('act("same")'); await js(go_to % "Death Day")
        await keep("desk-new-tang-death")                   # Tang See Chim: replace the death day 15 with 16


if __name__ == "__main__":
    chrome = next(Path.home().glob(".cache/ms-playwright/chromium-*/chrome-linux*/chrome"))
    fonts = Path(tempfile.mkdtemp())                              # a font that can draw Chinese, for this browser only: a throwaway fontconfig, nothing installed
    for face in ("msyh.ttc", "msyhbd.ttc"):                      # Microsoft YaHei, from Windows when this runs under WSL
        if Path("/mnt/c/Windows/Fonts", face).exists():
            (fonts / face).symlink_to(Path("/mnt/c/Windows/Fonts", face))
    (fonts / "fonts.conf").write_text(f'<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>'
                                      f'<include ignore_missing="yes">/etc/fonts/fonts.conf</include><dir>{fonts}</dir><cachedir>{fonts}/cache</cachedir></fontconfig>')
    env = {**os.environ, "FONTCONFIG_FILE": str(fonts / "fonts.conf")}
    proc = subprocess.Popen([str(chrome), "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars", f"--remote-debugging-port={PORT}",
                             f"--user-data-dir={tempfile.mkdtemp()}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    try:
        for _ in range(60):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                break
            except Exception:
                time.sleep(0.5)
        asyncio.run(shoot(next(t["webSocketDebuggerUrl"] for t in targets if t["type"] == "page")))
    finally:
        proc.terminate()
