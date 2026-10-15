"""
The paper's figures, drawn from code: vector drawings at their printed size, rendered to 300 dpi PNG.

    uv run python scripts/paper_figures/build.py            # all figures into data/dist/paper-figures/
    uv run python scripts/paper_figures/build.py 1 4        # only figures 1 and 4

Figures 1, 3 and 4 are SVG written here, in Times New Roman (the paper's body face), no text below 8 pt at the
printed width of 152 mm (the paper's text column). Estimates are hatched, not only tinted, so every figure still
reads in black and white. Figure 2 is screenshots of the review desk (screens.py). Every number is the paper's own
or the measurement behind it: nothing is typed in that is not in the text or the data.
"""

import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "dist" / "paper-figures"
WIDTH = 152          # mm, the paper's text column
DPI = 300

NAVY, INK2, RULE = "#1F2A44", "#4A5468", "#C9CED8"
TEAL, TEAL_BG = "#2E6F73", "#E8F1F1"
RED, RED_BG = "#A8322D", "#F7E9E7"
PAPER, GREY = "#F4F1EA", "#E3E1DC"
PT8, PT9, PT10 = 2.82, 3.17, 3.53    # font sizes in mm


def chrome() -> str:
    home = Path.home() / ".cache" / "ms-playwright"
    found = [os.environ.get("DESK_CHROME", "")]
    found += sorted(glob.glob(str(home / "chromium_headless_shell-*" / "chrome-headless-shell-linux64" / "chrome-headless-shell")), reverse=True)
    found += sorted(glob.glob(str(home / "chromium_headless_shell-*" / "chrome-linux" / "headless_shell")), reverse=True)
    found += [shutil.which("chrome-headless-shell") or ""]
    path = next((f for f in found if f and Path(f).exists()), None)
    if not path:
        sys.exit("Needs Chrome's headless shell (uvx playwright install --only-shell chromium).")
    return path


FONTS = """
@font-face { font-family: 'Paper'; src: url('file:///mnt/c/Windows/Fonts/times.ttf'); }
@font-face { font-family: 'Paper'; font-weight: bold; src: url('file:///mnt/c/Windows/Fonts/timesbd.ttf'); }
@font-face { font-family: 'Paper'; font-style: italic; src: url('file:///mnt/c/Windows/Fonts/timesi.ttf'); }
"""


def render(svg: str, height_mm: float, out: Path) -> Path:
    """An SVG drawn in millimetres, rendered to PNG at 300 dpi."""
    css_w, css_h = round(WIDTH / 25.4 * 96), round(height_mm / 25.4 * 96)
    page = f"""<!doctype html><meta charset="utf-8"><style>{FONTS}
html,body{{margin:0;padding:0;background:#fff}} svg{{display:block;width:{css_w}px;height:{css_h}px}}
text{{font-family:'Paper','Times New Roman',serif}}</style>{svg}"""
    work = OUT / "work"
    work.mkdir(parents=True, exist_ok=True)
    html = work / (out.stem + ".html")
    html.write_text(page, encoding="utf-8")
    (work / (out.stem + ".svg")).write_text(svg, encoding="utf-8")
    subprocess.run([chrome(), "--headless", "--no-sandbox", "--disable-gpu", "--allow-file-access-from-files",
                    "--hide-scrollbars", f"--force-device-scale-factor={DPI / 96}", f"--window-size={css_w},{css_h}",
                    "--virtual-time-budget=3000", f"--screenshot={out}", html.as_uri()],
                   check=True, capture_output=True, timeout=120)
    return out


def render_html(body: str, height_mm: float, out: Path) -> Path:
    """HTML laid out in millimetres at the column width, rendered to PNG at 300 dpi (Figure 2's composition)."""
    css_w, css_h = round(WIDTH / 25.4 * 96), round(height_mm / 25.4 * 96)
    page = f"""<!doctype html><meta charset="utf-8"><style>{FONTS}
html,body{{margin:0;padding:0;background:#fff;width:{css_w}px;height:{css_h}px;overflow:hidden}}</style>{body}"""
    work = OUT / "work"
    work.mkdir(parents=True, exist_ok=True)
    html = work / (out.stem + ".html")
    html.write_text(page, encoding="utf-8")
    subprocess.run([chrome(), "--headless", "--no-sandbox", "--disable-gpu", "--allow-file-access-from-files",
                    "--hide-scrollbars", f"--force-device-scale-factor={DPI / 96}", f"--window-size={css_w},{css_h}",
                    "--virtual-time-budget=4000", f"--screenshot={out}", html.as_uri()],
                   check=True, capture_output=True, timeout=120)
    return out


def lines(x: float, y: float, rows: list[str], size: float = PT8, lead: float = 1.22, anchor: str = "start",
          weight: str = "normal", style: str = "normal", fill: str = NAVY) -> str:
    """Text set line by line: SVG does not wrap."""
    spans = "".join(f'<tspan x="{x}" dy="{0 if i == 0 else size * lead:.2f}">{r}</tspan>' for i, r in enumerate(rows))
    return (f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" font-weight="{weight}" '
            f'font-style="{style}" fill="{fill}">{spans}</text>')


def svg(width: float, height: float, body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">'
            f'<defs><pattern id="hatch" width="1.6" height="1.6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
            f'<rect width="1.6" height="1.6" fill="#fff"/><line x1="0" y1="0" x2="0" y2="1.6" stroke="{NAVY}" stroke-width="0.55"/></pattern>'
            f'<marker id="arrow" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="4.2" markerHeight="4.2" orient="auto">'
            f'<path d="M0,0 L6,3 L0,6 z" fill="{INK2}"/></marker></defs>{body}</svg>')


# ---- Figure 1: the pipeline -------------------------------------------------------------------------------
def figure1() -> Path:
    """Six stages as in the text (Section 2), the worked example from the text (Gerard Ee, 31 August 2026)."""
    H = 64
    n, gap = 6, 3.2
    w = (WIDTH - gap * (n - 1)) / n
    top, box_h = 12, 19
    stages = [
        ("1  Ingestion", ["Three outlets'", "feeds, every", "two hours"], "code"),
        ("2  Relevance", ["Relevant? From", "title and", "summary only"], "model"),
        ("3  Extraction", ["Full article read:", "entities, facts,", "one quoted line"], "model"),
        ("4  Retrieval", ["Trigram search", "on the name and", "its romanisation"], "code"),
        ("5  Resolution", ["Same record or", "new? What is", "it missing?"], "model"),
        ("6  Review", ["Identity first,", "then each", "change"], "person"),
    ]
    flows = [
        ["60 articles", "a day (median)"],
        ["about 4% pass", "(149 of 3,511)"],
        ["2 people: Gerard", "Ee, Anita Fam"],
        ["2 candidate", "records"],
        ["Same record;", "2 changes"],
        ["accepted, edited", "or rejected"],
    ]
    body = []
    xb = 5 * (w + gap) - gap
    xh = 5 * (w + gap)
    body.append(f'<path d="M0,8.5 L0,6 L{xb:.2f},6 L{xb:.2f},8.5" fill="none" stroke="{TEAL}" stroke-width="0.35"/>')
    body.append(f'<rect x="{xb / 2 - 24}" y="3" width="48" height="5" fill="#fff"/>')
    body.append(lines(xb / 2, 7.1, ["Automated, on a schedule"], PT9, anchor="middle", weight="bold", fill=TEAL))
    body.append(lines(xh + w / 2, 7.1, ["A person"], PT9, anchor="middle", weight="bold", fill=RED))
    xdiv = xh - gap / 2
    body.append(f'<line x1="{xdiv:.2f}" y1="2" x2="{xdiv:.2f}" y2="{H - 1}" stroke="{RED}" stroke-width="0.35" stroke-dasharray="1.4 1.1"/>')
    for i, (name, desc, who) in enumerate(stages):
        x = i * (w + gap)
        human = who == "person"
        fill, edge = (RED_BG, RED) if human else (TEAL_BG, TEAL)
        body.append(f'<rect x="{x:.2f}" y="{top}" width="{w:.2f}" height="{box_h}" rx="1.2" fill="{fill}" stroke="{edge}" stroke-width="0.35"/>')
        body.append(lines(x + 1.6, top + 4.6, [name], PT9, weight="bold", fill=RED if human else NAVY))
        body.append(lines(x + 1.6, top + 9, desc, PT8))
        tag = {"model": "language model", "code": "code, no model", "person": "cataloguer"}[who]
        body.append(lines(x + w - 1.4, top + box_h + 3.4, [tag], PT8, anchor="end", style="italic", fill=RED if human else TEAL))
        if i < n - 1:
            ax = x + w + 0.25
            body.append(f'<line x1="{ax:.2f}" y1="{top + box_h / 2}" x2="{ax + gap - 0.8:.2f}" y2="{top + box_h / 2}" stroke="{INK2}" stroke-width="0.35" marker-end="url(#arrow)"/>')
    # the stream of articles, narrowing at relevance: 60 a day to about 4 in 100
    sy, full = top + box_h + 6.5, 7.0
    thin = max(0.5, full * 0.04)
    mid = sy + full / 2
    x1, xa, xz = 1.5, w + gap * 0.3, (w + gap) + w * 0.9
    body.append(f'<path d="M{x1},{sy} L{xa:.2f},{sy} C{xa + 9:.2f},{sy} {xz - 9:.2f},{mid - thin / 2:.2f} {xz:.2f},{mid - thin / 2:.2f} '
                f'L{xb:.2f},{mid - thin / 2:.2f} L{xb:.2f},{mid + thin / 2:.2f} L{xz:.2f},{mid + thin / 2:.2f} '
                f'C{xz - 9:.2f},{mid + thin / 2:.2f} {xa + 9:.2f},{sy + full} {xa:.2f},{sy + full} L{x1},{sy + full} z" fill="{GREY}"/>')
    for i, f in enumerate(flows):
        body.append(lines(i * (w + gap) + 1.6, sy + full + 5, f, PT8, style="italic", fill=INK2))
    body.append(lines(xdiv - 2, H - 2.4, ["The pipeline never writes to TTE: a person decides every change."], PT8, anchor="end", weight="bold", fill=RED))
    return render(svg(WIDTH, H, "".join(body)), H, OUT / "figure-1.png")


# ---- Figure 3: what each stage's failure costs ------------------------------------------------------------
def figure3() -> Path:
    """The content of the paper's Figure 3 and Section 4, without icons."""
    label_w = 26
    col_w = (WIDTH - label_w) / 3
    head_h = 12
    rows = [
        ("What goes wrong", [["A relevant story", "is rejected."], ["The wrong record", "is chosen."], ["Existing text is removed", "or overwritten."]], NAVY, 11.5),
        ("What it costs", [["Invisible loss: the update", "never reaches anyone."], ["Misattribution: correct", "facts on the wrong record."],
                           ["Information loss: valid", "text is destroyed."]], RED, 11.5),
        ("Design response", [["Favour recall: a low", "threshold, noise accepted", "early."], ["Verify identity: evidence", "and key fields first."],
                             ["Make changes inspectable:", "show the difference, flag", "deletions, one change", "per screen."]], TEAL, 21),
    ]
    heads = [("1  Relevance", "article selection"), ("2  Identity", "entity resolution"), ("3  Editing", "field updates")]
    H = head_h + sum(r[3] for r in rows) + 15
    body = []
    for j, (h, sub) in enumerate(heads):
        x = label_w + j * col_w
        body.append(f'<rect x="{x + 0.6:.2f}" y="0" width="{col_w - 1.2:.2f}" height="{head_h}" fill="{PAPER}"/>')
        body.append(lines(x + col_w / 2, 5.2, [h], PT10, anchor="middle", weight="bold"))
        body.append(lines(x + col_w / 2, 9.6, [sub], PT8, anchor="middle", style="italic", fill=INK2))
    y = head_h
    for label, cells, colour, rh in rows:
        body.append(f'<line x1="0" y1="{y}" x2="{WIDTH}" y2="{y}" stroke="{RULE}" stroke-width="0.3"/>')
        body.append(lines(0.5, y + 5, [label], PT9, weight="bold", fill=colour))
        for j, cell in enumerate(cells):
            x = label_w + j * col_w + 2.5
            first, rest = cell[0], cell[1:]
            if ":" in first:
                head, tail = first.split(":", 1)
                body.append(f'<text x="{x}" y="{y + 5}" font-size="{PT9}"><tspan font-weight="bold" fill="{colour}">{head}:</tspan>'
                            f'<tspan fill="{NAVY}">{tail}</tspan></text>')
                body.append(lines(x, y + 5 + PT9 * 1.22, rest, PT9))
            else:
                body.append(lines(x, y + 5, cell, PT9))
        y += rh
    body.append(f'<line x1="0" y1="{y}" x2="{WIDTH}" y2="{y}" stroke="{RULE}" stroke-width="0.3"/>')
    body.append(f'<rect x="{label_w + 0.6}" y="{y + 3}" width="{WIDTH - label_w - 1.2}" height="10" fill="{TEAL_BG}" stroke="{TEAL}" stroke-width="0.3"/>')
    body.append(lines(0.5, y + 9.2, ["Overall"], PT9, weight="bold", fill=TEAL))
    body.append(lines(label_w + (WIDTH - label_w) / 2, y + 9.2, ["Move uncertainty towards the reviewer; remove structural errors in code."],
                      PT10, anchor="middle", weight="bold"))
    return render(svg(WIDTH, H, "".join(body)), H, OUT / "figure-3.png")


# ---- Figure 4: the coverage ceiling ----------------------------------------------------------------------
def figure4() -> Path:
    """One bar: the 12% measured is part of the ~19% estimated (docs/evaluation.md); the rest out of reach."""
    H = 41
    measured, estimated = 0.12, 0.19
    bw, by, bh = WIDTH, 19, 9
    xm, xe = bw * measured, bw * estimated
    body = [lines(0, 4, ["The team's own edits: 4,046 field changes across seven TTE exports, September 2024 to September 2026"], PT9, weight="bold"),
            lines(0, 8.4, ["Share whose name one of the three outlets printed in that period or the two months before"], PT8, style="italic", fill=INK2)]
    # the estimate, above the bar: it includes the measured part
    body.append(f'<path d="M0.15,{by - 0.6} L0.15,{by - 2.4} L{xe - 0.15:.2f},{by - 2.4} L{xe - 0.15:.2f},{by - 0.6}" fill="none" stroke="{INK2}" stroke-width="0.3"/>')
    body.append(lines(xe + 2, by - 1.4, ["about 19%, estimated (about 1 in 5): counting names in the full text too, 1.6 times as many"], PT8))
    body.append(f'<rect x="0" y="{by}" width="{bw}" height="{bh}" fill="{GREY}"/>')
    body.append(f'<rect x="{xm:.2f}" y="{by}" width="{xe - xm:.2f}" height="{bh}" fill="url(#hatch)" stroke="{NAVY}" stroke-width="0.3"/>')
    body.append(f'<rect x="0" y="{by}" width="{xm:.2f}" height="{bh}" fill="{NAVY}"/>')
    body.append(lines(xm / 2, by + bh / 2 + 1.1, ["12%"], PT9, anchor="middle", weight="bold", fill="#fff"))
    body.append(lines((xe + bw) / 2, by + bh / 2 + 1.1, ["about 81%: not observable in these three sources by this comparison"], PT9, anchor="middle"))
    # the measured part, below the bar
    ty = by + bh + 0.6
    body.append(f'<path d="M0.15,{ty} L0.15,{ty + 1.8} L{xm - 0.15:.2f},{ty + 1.8} L{xm - 0.15:.2f},{ty}" fill="none" stroke="{INK2}" stroke-width="0.3"/>')
    body.append(lines(xm + 2, ty + 2.6, ["12%, measured (about 1 in 8): the name in a headline or summary"], PT8))
    ly = H - 1.8
    body.append(f'<rect x="{WIDTH - 52}" y="{ly - 2.6}" width="4" height="3" fill="{NAVY}"/>')
    body.append(lines(WIDTH - 47, ly, ["measured"], PT8))
    body.append(f'<rect x="{WIDTH - 29}" y="{ly - 2.6}" width="4" height="3" fill="url(#hatch)" stroke="{NAVY}" stroke-width="0.3"/>')
    body.append(lines(WIDTH - 24, ly, ["estimated"], PT8))
    return render(svg(WIDTH, H, "".join(body)), H, OUT / "figure-4.png")


# ---- Figure 5: the 48 pilot cards, with and without a person ---------------------------------------------
# Outcome kinds per card, from the replay's own data (scripts/build_talk_v4.py: desk_counts, desk_agreement) and,
# for the stored answers alone (the archive's internal model on 41 of these 48 cards, the nightly Gemini pipeline on
# 7), the stored resolution of each card's entities in the same replay file
# (data/jev/flow-full2.csv): amended if it proposed a change, new if it proposed one, flagged if it flagged it.
FIG5 = [
    ("Reviewer", "one person", [39, 6, 0, 3, 0, 0], None),
    ("Proposals accepted", "unreviewed", [37, 7, 1, 0, 3, 0], "43 of 48"),
    ("Jev's decisions", "unreviewed", [8, 12, 18, 1, 1, 8], "16 of 48"),
]
KINDS = [("Amended", NAVY, "#fff"), ("New record", TEAL, "#fff"), ("No change", GREY, NAVY),
         ("Not worth a record", "#9AA3B2", NAVY), ("Flagged or kept for review", "url(#hatch)", NAVY),
         ("Dropped before review", "#fff", NAVY)]


def figure5() -> Path:
    H = 61
    lx, bx, bw, rx = 0, 37, 88, 129
    per = bw / 48
    bh, gap, top = 7, 6.2, 10
    body = [lines(rx, 4.2, ["Same outcome", "as the reviewer"], PT8, weight="bold")]
    body.append(lines(bx, 4.2, ["48 pilot cards, by outcome"], PT8, weight="bold"))
    for r, (name, sub, counts, agree) in enumerate(FIG5):
        y = top + r * (bh + gap)
        body.append(lines(lx, y + 3.1, [name], PT9, weight="bold"))
        body.append(lines(lx, y + 6.6, [sub], PT8, style="italic", fill=INK2))
        x, small = bx, 0
        for (kind, fill, ink), n in zip(KINDS, counts):
            if not n:
                continue
            w = n * per
            dash = ' stroke-dasharray="0.9 0.6"' if kind.startswith("Dropped") else ""
            body.append(f'<rect x="{x:.2f}" y="{y}" width="{w:.2f}" height="{bh}" fill="{fill}" stroke="{NAVY}" stroke-width="0.25"{dash}/>')
            if w >= 4:
                if fill.startswith("url"):    # a number on hatching gets a white backing
                    body.append(f'<rect x="{x + w / 2 - 1.6:.2f}" y="{y + bh / 2 - 1.8:.2f}" width="3.2" height="3.4" fill="#fff"/>')
                body.append(lines(x + w / 2, y + bh / 2 + 1.1, [str(n)], PT8, anchor="middle", weight="bold", fill=ink))
            else:   # too narrow to hold its number: above, then below, so neighbours do not collide
                ty = y - 0.9 if small % 2 == 0 else y + bh + 2.9
                body.append(lines(x + w / 2, ty, [str(n)], PT8, anchor="middle", weight="bold"))
                small += 1
            x += w
        body.append(lines(rx, y + 4.8, [agree or "(reference)"], PT10 if agree else PT8, weight="bold" if agree else "normal",
                          style="normal" if agree else "italic", fill=NAVY if agree else INK2))
    # the legend, two rows of three
    ly = top + 3 * (bh + gap) + 1.5
    for i, (kind, fill, _) in enumerate(KINDS):
        cx = bx + (i % 3) * 38
        cy = ly + (i // 3) * 5
        dash = ' stroke-dasharray="0.9 0.6"' if kind.startswith("Dropped") else ""
        body.append(f'<rect x="{cx}" y="{cy - 2.6}" width="4" height="3" fill="{fill}" stroke="{NAVY}" stroke-width="0.25"{dash}/>')
        body.append(lines(cx + 5.2, cy, [kind], PT8))
    return render(svg(WIDTH, H, "".join(body)), H, OUT / "figure-5.png")


FIGURES = {"1": figure1, "3": figure3, "4": figure4, "5": figure5}

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for k in (sys.argv[1:] or FIGURES):
        if k in FIGURES:
            print("wrote", FIGURES[k]().relative_to(ROOT))
