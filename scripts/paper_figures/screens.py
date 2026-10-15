"""
Figure 2: the review desk the team chose (prototype/desk.template.html), on the paper's worked example, Gerard Ee.

    uv run python scripts/paper_figures/screens.py

Builds the desk from the published deck (prototype/build.py, reading the database only), opens Gerard Ee's card on
its three screens (same record?, the new affiliation, the description), takes each at twice the resolution, crops it
to the desk's own column, and lays the three out as one figure with (a), (b), (c) and a few numbered callouts.
Nothing is mocked up: the article, the TTE record and the proposed changes are the real ones.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import FONTS, INK2, NAVY, OUT, RED, ROOT, WIDTH, chrome  # noqa: E402

KEY = "uid:18567994"            # Ee, Gerard
SCALE = 2
VIEW_W, VIEW_H = 1180, 1400

PROBE = """<script>setTimeout(() => {
  const c = CARDS.find(c => c.key === "%(key)s"); cur = LIST.indexOf(CARDS.indexOf(c)); PAGE = "review";
  const st = stOf(c), o = ordered(c)[0], rows = rowsFor(c, o);
  const screen = "%(screen)s";
  if (screen === "who") Object.assign(st, { screen: "who", cand: 0 });
  else Object.assign(st, { screen: "change", chosen: 0, ch: rows.findIndex(r => r.field === screen) });
  draw(true);
  const box = el => { if (!el) return null; const r = el.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; };
  const q = s => document.querySelector(s), qa = s => [...document.querySelectorAll(s)];
  const out = { stage: box(q("#stage")), h1: box(q("#stage h1")), focus: box(q("#stage .focus")),
                actions: box(qa("#stage .stamp, #stage .stamps, #stage .acts").pop() || null),
                news: box(q("#stage .news, #stage .newsblock, #stage .clip")), rec: box(q("#stage .rec, #stage .record, #stage .card")),
                diff: box(q("#stage .desc:not(.fade)")), final: box(q("#stage .final")), arrow: box(q("#stage .arrow")),
                quote: box(q("#stage blockquote, #stage .quote, #stage q")),
                lastButton: box(qa("#stage button.stamp, #stage .stamps button, #stage button.go, #stage button.grey").pop() || null) };
  const pre = document.querySelector("#selftest"); pre.hidden = false; pre.textContent = "RECTS " + JSON.stringify(out);
}, 400);</script>"""


def desk_page(work: Path) -> Path:
    page = work / "desk.html"
    if not page.exists():
        subprocess.run([sys.executable, str(ROOT / "prototype" / "build.py"), "--review", "--out", str(page)], check=True)
    return page


def shoot(base: str, screen: str, work: Path) -> tuple[Path, dict]:
    seed = "<script>try{localStorage.setItem('proto-langs','[\"en\"]');localStorage.setItem('desk2-welcomed','1')}catch(e){}</script>"
    page = base.replace("<head>", "<head>" + seed, 1).replace("</body>", PROBE % {"key": KEY, "screen": screen} + "</body>")
    html = work / f"screen-{screen.split('(')[0].lower()}.html"
    html.write_text(page, encoding="utf-8")
    args = [chrome(), "--headless", "--no-sandbox", "--disable-gpu", "--allow-file-access-from-files", "--hide-scrollbars",
            f"--user-data-dir={work / 'profile'}", f"--window-size={VIEW_W},{VIEW_H}", "--virtual-time-budget=6000"]
    dom = subprocess.run(args + ["--dump-dom", html.as_uri() + "#nowelcome"], capture_output=True, text=True, timeout=120).stdout
    rects = json.loads(re.search(r"RECTS (\{.*?\})</pre>", dom, re.S).group(1).replace("&quot;", '"'))
    png = html.with_suffix(".png")
    subprocess.run(args + [f"--force-device-scale-factor={SCALE}", f"--screenshot={png}", html.as_uri() + "#nowelcome"],
                   check=True, capture_output=True, timeout=120)
    return png, rects


def crop(png: Path, rects: dict, bottom_key: str, pad: int = 14) -> Path:
    """The desk's own column, from the step line to the end of the part that matters."""
    stage = rects["stage"]
    left, top = stage[0] - 4, stage[1] - 2
    right = stage[2] + 4
    bottom = (rects.get(bottom_key) or stage)[3] + pad
    img = Image.open(png)
    out = png.with_name(png.stem + "-crop.png")
    img.crop(tuple(int(v * SCALE) for v in (left, top, right, bottom))).save(out)
    return out




# ---- composing the figure ---------------------------------------------------------------------------------
# What each panel keeps, in CSS pixels of the desk at 1180 px wide (the screenshots are at twice that). The article
# is shown once, in (a); (b) and (c) keep the question and the change itself, and a dashed rule marks where the
# repeated article was cut out.
PANELS = [
    ("a", "who", [(61, 486)], "Identity first: the article's sentence beside the TTE record"),
    ("b", "Affiliations(groupName)", [(61, 128), (250, 476)], "One change per screen: the affiliations in TTE now, and after accepting"),
    ("c", "Description", [(61, 128), (388, 602)], "The description: the added clause in green, what it replaces struck through"),
]


def panel(png: Path, rects: dict, strips: list[tuple[int, int]], out: Path) -> Path:
    img = Image.open(png)
    left, right = (rects["stage"][0] - 6) * SCALE, (rects["stage"][2] + 6) * SCALE
    pieces = [img.crop((int(left), y0 * SCALE, int(right), y1 * SCALE)) for y0, y1 in strips]
    gap = 22
    h = sum(p.height for p in pieces) + gap * (len(pieces) - 1)
    canvas = Image.new("RGB", (pieces[0].width, h), img.getpixel((int(left) + 4, 40)))
    y = 0
    from PIL import ImageDraw
    d = ImageDraw.Draw(canvas)
    for n, p in enumerate(pieces):
        canvas.paste(p, (0, y))
        y += p.height
        if n < len(pieces) - 1:
            for x in range(12, canvas.width - 12, 18):
                d.line([(x, y + gap // 2), (x + 9, y + gap // 2)], fill=(150, 156, 168), width=2)
            y += gap
    canvas.save(out)
    return out


def compose(panels: list[tuple[str, str, Path]]) -> Path:
    from build import render_html
    widths = [Image.open(p).size for _, _, p in panels]
    # one page at most: the panels share a width chosen so the whole figure fits in 200 mm
    head_mm, gap_mm, max_h = 6.0, 3.0, 200.0
    ratio = sum(h / w for w, h in widths)
    pw = min(WIDTH, (max_h - len(panels) * (head_mm + gap_mm)) / ratio)
    H = sum(pw * h / w for w, h in widths) + len(panels) * (head_mm + gap_mm)
    body = "".join(
        f'<div style="margin:0 0 {gap_mm}mm 0"><div style="font:bold 9pt Paper;color:{NAVY};height:{head_mm}mm;line-height:{head_mm - 1.2}mm">'
        f'({tag})&nbsp; <span style="font-weight:normal">{text}</span></div>'
        f'<img src="{p.as_uri()}" style="display:block;width:{pw:.2f}mm;margin:0 auto;border:0.25mm solid #D5D2CA"></div>'
        for (tag, text, p) in panels)
    return render_html(f'<div style="width:{pw:.2f}mm;margin:0 auto">{body}</div>', H + 1, OUT / "figure-2.png"), pw, H


def figure2() -> Path:
    work = OUT / "work"
    work.mkdir(parents=True, exist_ok=True)
    base = desk_page(work).read_text(encoding="utf-8")
    made = []
    for tag, screen, strips, text in PANELS:
        png, rects = shoot(base, screen, work)
        made.append((tag, text, panel(png, rects, strips, work / f"panel-{tag}.png")))
    out, pw, H = compose(made)
    print(f"figure 2: panels {pw:.0f} mm wide, {H:.0f} mm tall; the desk's 16 px body text prints at {16 * pw / 748 / 0.3528:.1f} pt")
    return out


if __name__ == "__main__":
    figure2()
