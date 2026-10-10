"""
Can a small multilingual classifier replace Gemini at the relevance step? Fine-tune several and compare.

The relevance step reads a headline and summary and says whether an article reports a change to a
record. This trains and scores small encoders on that question, before and after fine-tuning, on a
time-ordered split, by language, with speed.

Runs in the gliner venv (torch, transformers, numpy; nothing else is needed):

    PY=~/.venvs/gliner/bin/python
    $PY scripts/relevance_finetune.py splits                         # once: writes data/finetune/*.jsonl
    $PY scripts/relevance_finetune.py before jhu-clsp/mmBERT-small   # a frozen encoder with a linear probe
    $PY scripts/relevance_finetune.py train  jhu-clsp/mmBERT-small   # fine-tune (stops early, keeps the best), save it, score test, live, human
    $PY scripts/relevance_finetune.py score  jhu-clsp/mmBERT-small   # later: the saved model on the labelled sheet, with the same thresholds
    $PY scripts/relevance_finetune.py embed  intfloat/multilingual-e5-small   # a small embedding model: every article embedded once, saved
    $PY scripts/relevance_finetune.py head   intfloat/multilingual-e5-small   # cheap classifiers on those vectors (logistic regression, MLP, gradient boosting)
    $PY scripts/relevance_finetune.py tfidf                          # no neural network: word and character counts + logistic regression (the floor)
    $PY scripts/relevance_finetune.py report-before                  # precision, recall, F1 before fine-tuning, English vs Chinese
    $PY scripts/relevance_finetune.py report                         # one table from everything run so far

    # GLiClass is a zero-shot classifier with its own library (pip install gliclass):
    $PY scripts/relevance_finetune.py before knowledgator/gliclass-multilang-mini --kind zeroshot
    $PY scripts/relevance_finetune.py export-gliclass                # its training file, for its own train.py

Add --limit-train 2000 --limit-eval 1000 --epochs 1 to try a model in a couple of minutes first. That is a trial: it
is saved as trial.json, never as the result, and no model is kept.

Training checks on val twice an epoch and stops after 3 checks without improvement (--patience, --eval-every). The best
weights by val average precision are what get scored and saved, whether the run finishes, stops early, hits Ctrl+C (once:
it keeps the best and scores it) or hits a numerical error. If the GPU runs out of memory, the same batch is run in
smaller pieces and training carries on. A batch whose loss is not a number is skipped. Every run is also kept under
data/finetune/<model>/runs/, and each article's score under preds-*.csv.

The sets
    train / val / test   the archive's labels (the internal model's, not people's), split by date:
                         before 2024-07, 2024-07 to 2025-06, 2025-07 to 2026-06. Later articles are
                         left out: they are the live period.
    live                 3,747 live articles, Gemini's verdicts (a different labeller from the archive's)
    human                69 articles a person decided where Gemini and the internal model disagreed
    sheet                the evaluation's 736 rows, once the team has filled in `relevant` (optional)

The labels are another model's, so a classifier here can at best match that model. How it does against
people is what the human and sheet sets say.

Thresholds are chosen on val, never on test: one that maximises F1, and one that keeps recall at 95%
(a story wrongly dropped at this step is lost for good, so recall is the number that matters).
"""

import argparse
import csv
import html
import json
import math
import random
import re
import sys
import time
from pathlib import Path

import numpy as np

try:
    from tqdm.auto import tqdm
except ImportError:                                  # no bars, but everything still runs
    tqdm = None

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "finetune"
ARCHIVE = ROOT / "data/backfill/answers/relevance.csv"
LIVE = ROOT / "data/gliner/live-articles.json"
HUMAN = ROOT / "data/backfill/labels/relevance-labels.csv"
SHEET = ROOT / "data/eval/1-relevance.xlsx"
SHEET_KEY = ROOT / "data/eval/1-relevance-key.json"
CUTS = ("2024-07-01", "2025-07-01", "2026-07-01")      # train < CUTS[0] <= val < CUTS[1] <= test < CUTS[2]
SETS = ("train", "val", "test", "live", "human", "sheet")
EVAL = ("val", "test", "live", "human", "sheet")

# The two labels GLiClass is asked to choose between.
LABEL_REL = ("relevant news: a named person, organisation, place, event or law had a recorded change "
             "(died, appointed, retired, won an award, merged, renamed, opened, closed, new law)")
LABEL_OTHER = ("other news: commentary, opinion, routine events, crime, sport, lifestyle, "
               "people quoted or reacting, plans not yet in effect")


def bar(iterable, total=None, desc="", leave=True, unit="it"):
    """A progress bar over anything, if tqdm is there."""
    if tqdm is None:
        return iterable
    return tqdm(iterable, total=total, desc=desc, leave=leave, unit=unit, dynamic_ncols=True, mininterval=1.0)


def say(message):
    """Print without breaking a progress bar."""
    (tqdm.write if tqdm is not None else print)(message)


def slug(model):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model.strip("/").replace("/", "__"))


def lang_of(text):
    return "zh" if re.search(r"zaobao|^zb$", text) else "en"


def clean(title, description):
    t = html.unescape((title or "").strip())
    d = html.unescape((description or "").strip())
    return f"{t}. {d}" if d else t


# ---- 1. the sets -------------------------------------------------------------

def write_jsonl(name, rows):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / f"{name}.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(name, limit=None, seed=0):
    path = OUT / f"{name}.jsonl"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    if limit and len(rows) > limit:
        random.Random(seed).shuffle(rows)
        rows = rows[:limit]
    return rows


def make_splits(_args):
    csv.field_size_limit(2 ** 31 - 1)
    human_urls = set()
    if HUMAN.exists():
        with open(HUMAN, encoding="utf-8-sig", newline="") as f:
            human_urls = {r["key"] for r in csv.DictReader(f)}
    sets = {"train": [], "val": [], "test": []}
    descriptions = {}
    skipped = 0
    with open(ARCHIVE, encoding="utf-8-sig", newline="") as f:
        for r in bar(csv.DictReader(f), desc="reading the archive", unit=" rows"):
            day = (r["published"] or "")[:10]
            text = clean(r["title"], r["description"])
            if not text or not re.match(r"\d{4}-\d{2}-\d{2}$", day):
                skipped += 1
                continue
            if r["url"] in human_urls:
                descriptions[r["url"]] = r["description"]
            row = {"url": r["url"], "lang": lang_of(r["source"]), "day": day, "text": text,
                   "label": int(r["relevant"].strip().upper() == "TRUE")}
            if day < CUTS[0]:
                sets["train"].append(row)
            elif day < CUTS[1]:
                sets["val"].append(row)
            elif day < CUTS[2]:
                sets["test"].append(row)
    live = []
    if LIVE.exists():
        for x in json.load(open(LIVE, encoding="utf-8")):
            live.append({"url": x["url"], "lang": lang_of(x["url"]), "day": "2026-08", "text": clean(x["title"], x["description"]),
                         "label": int(str(x["relevant"]).strip().lower() == "true")})
    human = []
    if HUMAN.exists():
        with open(HUMAN, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                human.append({"url": r["key"], "lang": lang_of(r["source"] + r["key"]), "day": "", "text": clean(r["title"], descriptions.get(r["key"], "")),
                              "label": int(r["human"].strip().lower() == "true")})
    sheet = read_sheet()
    for name, rows in (("train", sets["train"]), ("val", sets["val"]), ("test", sets["test"]), ("live", live), ("human", human), ("sheet", sheet)):
        write_jsonl(name, rows)
    print(f"{'set':<8}{'articles':>10}{'relevant':>10}{'share':>8}{'Chinese':>10}{'ZH relevant':>13}")
    for name in SETS:
        rows = read_jsonl(name)
        pos = sum(r["label"] for r in rows)
        zh = [r for r in rows if r["lang"] == "zh"]
        print(f"{name:<8}{len(rows):>10,}{pos:>10,}{pos / max(len(rows), 1):>8.1%}{len(zh):>10,}{sum(r['label'] for r in zh):>13,}")
    print(f"skipped (no text or no date): {skipped:,}. Written to {OUT}")
    if not sheet:
        print("sheet: no labels yet in data/eval/1-relevance.xlsx; re-run `splits` once the team has filled in `relevant`.")


def read_sheet():
    """The evaluation sheet's rows that have been labelled, with the key's sampling weight."""
    if not SHEET.exists():
        return []
    try:
        import openpyxl
    except ImportError:
        print("openpyxl is not installed: the evaluation sheet is skipped")
        return []
    weights = {}
    if SHEET_KEY.exists():
        weights = {k["url"]: k.get("weight", 1.0) for k in json.load(open(SHEET_KEY, encoding="utf-8"))}
    ws = openpyxl.load_workbook(SHEET, read_only=True, data_only=True)["rows"]
    rows = list(ws.iter_rows(values_only=True))
    head = [str(c or "").strip().lower() for c in rows[0]]
    col = {name: head.index(name) for name in ("url", "source", "title", "description", "relevant") if name in head}
    out = []
    for r in rows[1:]:
        verdict = str(r[col["relevant"]]).strip().lower() if col.get("relevant") is not None else ""
        if verdict not in ("true", "false"):
            continue
        out.append({"url": r[col["url"]], "lang": lang_of(f"{r[col['source']]} {r[col['url']]}"), "day": "", "w": weights.get(r[col["url"]], 1.0),
                    "text": clean(r[col["title"]], r[col["description"]]), "label": int(verdict == "true")})
    return out


# ---- 2. the measures ---------------------------------------------------------

def rank_auc(y, s):
    y, s = np.asarray(y), np.asarray(s, dtype=float)
    n1 = int(y.sum())
    n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return float("nan")
    order = np.argsort(s, kind="mergesort")
    _, inv, counts = np.unique(s[order], return_inverse=True, return_counts=True)
    avg = np.cumsum(counts) - (counts - 1) / 2            # tied scores share their average rank
    ranks = np.empty(len(s))
    ranks[order] = avg[inv]
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def avg_precision(y, s):
    y = np.asarray(y)
    if y.sum() == 0:
        return float("nan")
    y = y[np.argsort(-np.asarray(s), kind="mergesort")]
    precision = np.cumsum(y) / np.arange(1, len(y) + 1)
    return float((precision * y).sum() / y.sum())


def at(y, s, t, w=None):
    y, s = np.asarray(y), np.asarray(s)
    w = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    pred = s >= t
    tp, fp = w[pred & (y == 1)].sum(), w[pred & (y == 0)].sum()
    fn, tn = w[~pred & (y == 1)].sum(), w[~pred & (y == 0)].sum()
    n = tp + fp + fn + tn
    precision, recall = tp / max(tp + fp, 1e-9), tp / max(tp + fn, 1e-9)
    po = (tp + tn) / max(n, 1e-9)
    pe = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / max(n * n, 1e-9)
    return {"precision": float(precision), "recall": float(recall), "f1": float(2 * precision * recall / max(precision + recall, 1e-9)),
            "kappa": float((po - pe) / max(1 - pe, 1e-9)), "flagged": float((tp + fp) / max(n, 1e-9))}


def best_f1_threshold(y, s):
    y, s = np.asarray(y), np.asarray(s)
    order = np.argsort(-s, kind="mergesort")
    tp = np.cumsum(y[order])
    k = np.arange(1, len(y) + 1)
    f1 = 2 * tp / (k + y.sum())
    return float(s[order][int(np.argmax(f1))])


def recall_threshold(y, s, target):
    y, s = np.asarray(y), np.asarray(s)
    order = np.argsort(-s, kind="mergesort")
    recall = np.cumsum(y[order]) / max(y.sum(), 1)
    return float(s[order][int(np.argmax(recall >= target))])


def summarise(rows, scores, thresholds):
    """AUC, average precision, and precision/recall/F1/kappa at each threshold: overall and by language."""
    y = np.array([r["label"] for r in rows])
    s = np.asarray(scores)
    w = np.array([r.get("w", 1.0) for r in rows]) if rows and "w" in rows[0] else None
    out = {}
    for name, idx in (("all", np.arange(len(rows))), ("en", np.array([i for i, r in enumerate(rows) if r["lang"] == "en"], dtype=int)),
                      ("zh", np.array([i for i, r in enumerate(rows) if r["lang"] == "zh"], dtype=int))):
        if len(idx) == 0:
            continue
        yy, ss = y[idx], s[idx]
        entry = {"n": int(len(idx)), "relevant": int(yy.sum()), "auc": rank_auc(yy, ss), "ap": avg_precision(yy, ss)}
        for tname, t in thresholds.items():
            entry[tname] = at(yy, ss, t, None if w is None else w[idx])
        out[name] = entry
    return out


# ---- 3. the model, the data in batches -----------------------------------------

def device_of():
    import torch
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load_tokenizer(model_id):
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(model_id)


def encode(tok, rows, max_len, prefix=""):
    ids = []
    for i in bar(range(0, len(rows), 2000), desc=f"tokenising {len(rows):,} articles", unit=" x2000", leave=False):
        ids += tok([prefix + r["text"] for r in rows[i:i + 2000]], truncation=True, max_length=max_len)["input_ids"]
    return ids


def pad(batch_ids, pad_id, device):
    import torch
    width = max(len(x) for x in batch_ids)
    ids = torch.full((len(batch_ids), width), pad_id, dtype=torch.long)
    mask = torch.zeros((len(batch_ids), width), dtype=torch.long)
    for i, x in enumerate(batch_ids):
        ids[i, :len(x)] = torch.tensor(x)
        mask[i, :len(x)] = 1
    return ids.to(device), mask.to(device)


def batches(lengths, size, rng):
    """Random batches of similar length, so little is spent on padding."""
    order = list(range(len(lengths)))
    rng.shuffle(order)
    chunk = size * 50
    out = []
    for i in range(0, len(order), chunk):
        part = sorted(order[i:i + chunk], key=lambda j: lengths[j])
        out += [part[k:k + size] for k in range(0, len(part), size)]
    rng.shuffle(out)
    return out


def classifier(model_id, trust):
    from transformers import AutoModelForSequenceClassification
    kwargs = {"num_labels": 2, "ignore_mismatched_sizes": True, "trust_remote_code": trust}
    try:
        return AutoModelForSequenceClassification.from_pretrained(model_id, attn_implementation="sdpa", **kwargs)
    except (ValueError, TypeError, NotImplementedError):
        return AutoModelForSequenceClassification.from_pretrained(model_id, **kwargs)


def with_smaller_batches(fn, batch):
    """fn(batch); if the GPU runs out of memory, again with half the batch."""
    import torch
    while True:
        try:
            return fn(batch)
        except torch.cuda.OutOfMemoryError:
            pass                                       # leave the handler before freeing memory, or the failed batch is still held
        torch.cuda.empty_cache()
        if batch <= 4:
            sys.exit("the GPU ran out of memory, even with 4 articles at a time")
        batch //= 2
        print(f"  out of GPU memory: trying batches of {batch}", flush=True)


def predict(model, ids, pad_id, device, batch=128, desc="scoring"):
    """P(relevant) for each tokenised text. If the GPU runs out of memory, again with smaller batches."""
    return with_smaller_batches(lambda b: predict_once(model, ids, pad_id, device, b, desc), batch)


def predict_once(model, ids, pad_id, device, batch, desc):
    import torch
    model.eval()
    order = np.argsort([len(x) for x in ids])
    out = np.zeros(len(ids), dtype=np.float32)
    with torch.no_grad():
        for i in bar(range(0, len(order), batch), desc=desc, unit=" batches", leave=False):
            idx = order[i:i + batch]
            x, m = pad([ids[j] for j in idx], pad_id, device)
            with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                logits = model(input_ids=x, attention_mask=m).logits
            out[idx] = torch.softmax(logits.float(), dim=-1)[:, 1].cpu().numpy()
    return out


def sync(device):
    import torch
    if device.type == "cuda":
        torch.cuda.synchronize()


def score_sets(score_fn, args, tag="run", model_id=None):
    """Score val first, fix the thresholds on it, then score every other set with them."""
    results, scores = {}, {}
    val = read_jsonl("val", args.limit_eval, args.seed)
    print(f"scoring val ({len(val):,} articles), to fix the thresholds", flush=True)
    s_val = score_fn(val, "val")
    if model_id:
        save_preds(model_id, tag, "val", val, s_val)
    y_val = np.array([r["label"] for r in val])
    thresholds = {"f1_best": best_f1_threshold(y_val, s_val), f"recall_{int(args.recall * 100)}": recall_threshold(y_val, s_val, args.recall)}
    results["thresholds"] = thresholds
    results["val"] = summarise(val, s_val, thresholds)
    for name in EVAL[1:]:
        rows = read_jsonl(name, args.limit_eval, args.seed)
        if not rows:
            continue
        print(f"scoring {name} ({len(rows):,} articles)", flush=True)
        t0 = time.time()
        s = score_fn(rows, name)
        scores[name] = s
        if model_id:
            save_preds(model_id, tag, name, rows, s)
        results[name] = summarise(rows, s, thresholds)
        results[name]["seconds"] = round(time.time() - t0, 1)
    return results


def save(model_id, stage, payload):
    folder = OUT / slug(model_id)
    folder.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=1)
    (folder / f"{stage}.json").write_text(text, encoding="utf-8")
    (folder / "runs").mkdir(exist_ok=True)
    (folder / "runs" / f"{stage}-{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(text, encoding="utf-8")   # the last run is train.json; earlier ones stay here
    print(f"saved {folder / (stage + '.json')}")


def show(results):
    for name in EVAL:
        if name not in results:
            continue
        for lang in ("all", "en", "zh"):
            e = results[name].get(lang)
            if not e:
                continue
            line = f"  {name:<6}{lang:<4}n={e['n']:>6,} relevant={e['relevant']:>5,}  AUC {e['auc']:.3f}  AP {e['ap']:.3f}"
            for t in results["thresholds"]:
                m = e[t]
                line += f" | {t}: P {m['precision']:.2f} R {m['recall']:.2f} F1 {m['f1']:.2f}"
            print(line)


# ---- 4. before: a frozen encoder with a linear probe, or a zero-shot classifier --------

def download(args):
    """Fetch a model with a visible progress bar, so a slow or stuck download is seen before the long steps start."""
    from huggingface_hub import snapshot_download
    print(f"downloading {args.model} (the first time only)", flush=True)
    path = snapshot_download(args.model, allow_patterns=["*.json", "*.model", "*.txt", "*.safetensors"])
    if not any(Path(path).glob("*.safetensors")):          # an older checkpoint with only pickled weights
        path = snapshot_download(args.model, allow_patterns=["*.json", "*.model", "*.txt", "pytorch_model.bin"])
    size = sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file())
    print(f"ready: {path} ({size / 1e9:.2f} GB)")


def before(args):
    if args.kind == "zeroshot":
        return before_zeroshot(args)
    import torch
    from transformers import AutoModel
    dev = device_of()
    print(f"loading {args.model} on {dev}", flush=True)
    tok = load_tokenizer(args.model)
    enc = AutoModel.from_pretrained(args.model, trust_remote_code=args.trust_remote_code).to(dev).eval()
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else 0

    def embed(rows):
        ids = encode(tok, rows, args.max_len)
        out = np.zeros((len(ids), enc.config.hidden_size), dtype=np.float32)
        order = np.argsort([len(x) for x in ids])
        with torch.no_grad():
            for i in bar(range(0, len(order), 128), desc="embedding", unit=" batches", leave=False):
                idx = order[i:i + 128]
                x, m = pad([ids[j] for j in idx], pad_id, dev)
                with torch.autocast(dev.type, dtype=torch.bfloat16, enabled=dev.type == "cuda"):
                    h = enc(input_ids=x, attention_mask=m).last_hidden_state
                mean = (h.float() * m.unsqueeze(-1)).sum(1) / m.sum(1, keepdim=True)
                out[idx] = mean.cpu().numpy()
        return out

    train = read_jsonl("train", args.probe_n, args.seed)
    print(f"fitting the linear probe on {len(train):,} training articles", flush=True)
    x_train = embed(train)
    mu, sd = x_train.mean(0), x_train.std(0) + 1e-6
    y_train = torch.tensor([r["label"] for r in train], dtype=torch.float32, device=dev)
    xt = torch.tensor((x_train - mu) / sd, device=dev)
    w = torch.zeros(xt.shape[1], device=dev, requires_grad=True)
    b = torch.zeros(1, device=dev, requires_grad=True)
    opt = torch.optim.Adam([w, b], lr=0.01, weight_decay=1e-3)
    for _ in bar(range(400), desc="fitting the probe", unit=" steps", leave=False):
        opt.zero_grad()
        loss = torch.nn.functional.binary_cross_entropy_with_logits(xt @ w + b, y_train)
        loss.backward()
        opt.step()
    w, b = w.detach().cpu().numpy(), b.detach().cpu().numpy()

    def score(rows, name=None):
        z = ((embed(rows) - mu) / sd) @ w + b
        return 1 / (1 + np.exp(-z))

    results = score_sets(score, args, tag="before", model_id=args.model)
    results.update({"kind": "probe", "model": args.model, "trained_on": len(train)})
    print(f"{args.model}: frozen encoder + linear probe on {len(train):,} training articles")
    show(results)
    save(args.model, "before", results)


def before_zeroshot(args):
    try:
        from gliclass import GLiClassModel, ZeroShotClassificationPipeline
    except ImportError:
        sys.exit("gliclass is not installed here: pip install gliclass (in the gliner venv)")
    from transformers import AutoTokenizer
    dev = device_of()
    model = GLiClassModel.from_pretrained(args.model)
    tok = AutoTokenizer.from_pretrained(args.model, add_prefix_space=True)
    pipe = ZeroShotClassificationPipeline(model, tok, classification_type="single-label", device=str(dev))
    labels = [LABEL_REL, LABEL_OTHER]

    def score(rows, name=None):
        out = []
        for i in bar(range(0, len(rows), 16), desc="zero-shot", unit=" x16", leave=False):
            texts = [r["text"] for r in rows[i:i + 16]]
            for res in pipe(texts, labels, threshold=0.0, batch_size=16):
                got = {d["label"]: d["score"] for d in res}
                out.append(got.get(LABEL_REL, 0.0))
        return np.array(out, dtype=np.float32)

    results = score_sets(score, args, tag="before", model_id=args.model)
    results.update({"kind": "zeroshot", "model": args.model})
    print(f"{args.model}: zero-shot, nothing trained")
    show(results)
    save(args.model, "before", results)


# ---- 5. after: fine-tune --------------------------------------------------------------

def disk_ok(need_gb):
    import shutil
    OUT.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(OUT).free / 1e9 > need_gb


def save_model(model, tok, folder, meta):
    folder.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(folder)
    tok.save_pretrained(folder)
    (folder / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")


def save_preds(model_id, tag, name, rows, scores):
    """Every article's score, so the misses can be read afterwards."""
    folder = OUT / slug(model_id)
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / f"preds-{tag}-{name}.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["url", "lang", "label", "score"])
        for r, s in zip(rows, scores):
            w.writerow([r["url"], r["lang"], r["label"], f"{float(s):.5f}"])


def compare(model_id, after):
    p = OUT / slug(model_id) / "before.json"
    if not p.exists():
        print("(no before.json for this model: run `before` to see the change)")
        return
    b = json.loads(p.read_text())
    rk = [k for k in after["thresholds"] if k != "f1_best"][0]
    print("\nbefore -> after fine-tuning (thresholds fixed on val):")
    for split in ("test", "live", "human"):
        for lang in ("all", "en", "zh"):
            eb, ea = b.get(split, {}).get(lang), after.get(split, {}).get(lang)
            if eb and ea:
                print(f"  {split:<6}{lang:<4} AUC {eb['auc']:.3f} -> {ea['auc']:.3f} | F1 {eb['f1_best']['f1']:.2f} -> {ea['f1_best']['f1']:.2f} "
                      f"| precision at about 95% recall {eb[rk]['precision']:.2f} -> {ea[rk]['precision']:.2f} (recall {ea[rk]['recall']:.2f})")


def train(args):
    import torch
    dev = device_of()
    if dev.type != "cuda":
        print("no GPU found: this will be very slow")
    trial = bool(args.limit_train or args.limit_eval)         # a subset: a trial of the path, never saved as the result
    stage = "trial" if trial else "train"
    if trial:
        print("a trial on a subset: nothing is saved as the result (no model, no train.json)")
    print(f"loading {args.model} (the first time, this downloads it)", flush=True)
    tok = load_tokenizer(args.model)
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else 0
    try:
        model = classifier(args.model, args.trust_remote_code)
    except Exception as e:                                           # a checkpoint with its own head (Laya) lands here
        sys.exit(f"{args.model} does not load as a plain sequence classifier ({type(e).__name__}: {str(e)[:200]}).\n"
                 "Its own library is needed to fine-tune it, or fine-tune the encoder it is built on.")
    model.to(dev)
    params = sum(p.numel() for p in model.parameters())
    train_rows = read_jsonl("train", args.limit_train, args.seed)
    val_rows = read_jsonl("val", args.limit_eval, args.seed)
    if not train_rows or not val_rows:
        sys.exit("no data: run `splits` first")
    ids = encode(tok, train_rows, args.max_len)
    y = [r["label"] for r in train_rows]
    val_ids = encode(tok, val_rows, args.max_len)
    y_val = np.array([r["label"] for r in val_rows])
    lengths = [len(x) for x in ids]
    print(f"{args.model}: {params / 1e6:.0f}M parameters, {len(ids):,} training articles "
          f"({sum(y):,} relevant), median {int(np.median(lengths))} tokens", flush=True)

    out_dir = OUT / slug(args.model)
    saving = not args.no_save and not trial
    if saving and not disk_ok(3.0 if "small" in args.model.lower() else 5.0):
        print("not enough free disk to keep the fine-tuned weights: they will NOT be saved (--no-save silences this)")
        saving = False

    lr = args.lr or (5e-5 if "small" in args.model.lower() else 3e-5)
    decay, no_decay = [], []
    for n, p in model.named_parameters():
        (no_decay if p.ndim < 2 or "norm" in n.lower() or "bias" in n else decay).append(p)
    opt = torch.optim.AdamW([{"params": decay, "weight_decay": 0.01}, {"params": no_decay, "weight_decay": 0.0}], lr=lr)
    steps_per_epoch = math.ceil(len(ids) / args.batch)
    total, warm = steps_per_epoch * args.epochs, max(1, int(0.06 * steps_per_epoch * args.epochs))
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min((s + 1) / warm, max(0.0, (total - s) / max(total - warm, 1))))
    weight = torch.tensor([1.0, args.pos_weight], device=dev)
    rng = random.Random(args.seed)
    torch.manual_seed(args.seed)
    if dev.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
    say = tqdm.write if tqdm is not None else print
    eval_every = max(1, int(round(args.eval_every * steps_per_epoch)))
    print(f"{steps_per_epoch:,} steps an epoch, {args.epochs} epochs; checked on val every {eval_every:,} steps"
          + (f"; stops after {args.patience} checks without improvement" if args.patience else "; no early stopping"), flush=True)

    # best: the best val average precision so far. micro: how many articles go through the GPU at once (halved if memory runs out).
    state = {"best": -1.0, "best_state": None, "best_step": 0, "stale": 0, "step": 0, "micro": args.batch, "saved_ap": None, "skipped": 0, "bad_run": 0}
    history = []
    t_train = time.time()

    def keep():
        """The current weights, to disk. Failing to save never stops training."""
        try:
            save_model(model, tok, out_dir / "model", {"model": args.model, "max_len": args.max_len, "val_ap": state["best"], "step": state["best_step"]})
            state["saved_ap"] = state["best"]
        except Exception as e:
            state["saved_ap"] = None
            say(f"  could not save the weights ({type(e).__name__}: {e}); carrying on")

    def evaluate():
        s_val = predict(model, val_ids, pad_id, dev, desc="validating")
        ap, auc = avg_precision(y_val, s_val), rank_auc(y_val, s_val)
        f1 = at(y_val, s_val, best_f1_threshold(y_val, s_val))["f1"]
        improved = state["best_state"] is None or ap > state["best"] + args.min_delta
        if improved:
            state.update(best=ap, best_step=state["step"], stale=0, best_state={k: v.detach().to("cpu", copy=True) for k, v in model.state_dict().items()})
            if saving:                                  # the best so far is on disk too, so a crash still leaves something
                keep()
        else:
            state["stale"] += 1
        history.append({"step": state["step"], "epoch": round(state["step"] / steps_per_epoch, 2), "val_ap": ap, "val_auc": auc, "val_f1": f1,
                        "minutes": round((time.time() - t_train) / 60, 2)})
        note = "best so far" if improved else (f"no better ({state['stale']}/{args.patience})" if args.patience else "no better")
        say(f"  check at step {state['step']:,} (epoch {state['step'] / steps_per_epoch:.2f}): val AP {ap:.4f}  AUC {auc:.4f}  F1 {f1:.3f}  {note}")
        model.train()

    def accumulate(idx, micro):
        """Forward and backward over one batch, `micro` articles at a time. Returns the batch loss. The same result as one pass."""
        target = torch.tensor([y[j] for j in idx], device=dev)
        denom = weight[target].sum()
        loss_value = 0.0
        for i in range(0, len(idx), micro):
            x, m = pad([ids[j] for j in idx[i:i + micro]], pad_id, dev)
            with torch.autocast(dev.type, dtype=torch.bfloat16, enabled=dev.type == "cuda"):
                logits = model(input_ids=x, attention_mask=m).logits
            loss = torch.nn.functional.cross_entropy(logits.float(), target[i:i + micro], weight=weight, reduction="sum") / denom
            loss.backward()
            loss_value += loss.item()
        return loss_value

    stopped, pb = "completed all epochs", None
    try:
        for epoch in range(1, args.epochs + 1):
            model.train()
            running, good = 0.0, 0
            pb = bar(batches(lengths, args.batch, rng), total=steps_per_epoch, desc=f"epoch {epoch}/{args.epochs}", unit=" steps")
            for k, idx in enumerate(pb, 1):
                loss_value = None
                while loss_value is None:
                    oom = False
                    try:
                        loss_value = accumulate(idx, state["micro"])
                    except torch.cuda.OutOfMemoryError:
                        oom = True
                    if oom:                                # out of GPU memory: the same batch again, in smaller pieces
                        opt.zero_grad(set_to_none=True)
                        torch.cuda.empty_cache()
                        if state["micro"] <= 1:
                            sys.exit("the GPU ran out of memory even one article at a time. Close other programs using the GPU, or lower --max-len.")
                        state["micro"] = max(1, state["micro"] // 2)
                        say(f"  out of GPU memory: from now on each batch of {args.batch} goes through in pieces of {state['micro']} (same result, slower)")
                gnorm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                if math.isfinite(loss_value) and bool(torch.isfinite(gnorm)):
                    opt.step()
                    sched.step()
                    state["bad_run"] = 0
                    running += loss_value
                    good += 1
                else:                                      # a bad batch: skip it rather than poison the weights
                    state["skipped"] += 1
                    state["bad_run"] += 1
                    if state["bad_run"] >= 5:
                        raise FloatingPointError(f"the loss was not a number for 5 batches in a row (step {state['step'] + 1}); try a lower --lr")
                opt.zero_grad(set_to_none=True)
                state["step"] += 1
                if tqdm is not None and k % 20 == 0 and good:
                    pb.set_postfix(loss=f"{running / good:.4f}")
                if state["step"] % eval_every == 0 or state["step"] == total:
                    evaluate()
                    if args.patience and state["stale"] >= args.patience:
                        stopped = f"early stop: no improvement in {args.patience} checks"
                        break
            if tqdm is not None:
                pb.close()
            if stopped.startswith("early"):
                break
    except KeyboardInterrupt:
        stopped = "stopped by Ctrl+C"
        say("\nCtrl+C: keeping the best weights so far and scoring them (press Ctrl+C again to quit at once)")
    except FloatingPointError as e:
        stopped = "numerical error"
        say(f"\n{e}\nkeeping the best weights so far and scoring them")
    finally:
        if tqdm is not None and pb is not None:
            pb.close()
    if state["best_state"] is None:                        # stopped before the first check on val: nothing worth keeping
        sys.exit(f"{stopped} before the first check on val (every {eval_every:,} steps), so there is nothing to keep. Nothing was saved.")
    say(f"{stopped}; best val AP {state['best']:.4f} at step {state['best_step']:,}")
    train_minutes = (time.time() - t_train) / 60
    peak = torch.cuda.max_memory_allocated() / 1e9 if dev.type == "cuda" else 0.0
    model.load_state_dict(state["best_state"])
    if saving and state["saved_ap"] != state["best"]:      # an interrupted or failed save: write the best again, whole
        keep()

    def score(rows, name=None):
        return predict(model, encode(tok, rows, args.max_len), pad_id, dev)

    results = score_sets(score, args, tag="trial" if trial else "after", model_id=None if trial else args.model)
    # speed: the test set again, timed, with the tokenising included
    test = read_jsonl("test", args.limit_eval, args.seed)
    sync(dev)
    t0 = time.time()
    score(test)
    sync(dev)
    results.update({"kind": "finetuned", "model": args.model, "params_m": round(params / 1e6), "epochs": args.epochs, "lr": lr, "trained_on": len(ids),
                    "train_minutes": round(train_minutes, 1), "peak_vram_gb": round(peak, 2), "articles_per_second": round(len(test) / (time.time() - t0)),
                    "history": history, "best_val_ap": state["best"], "best_step": state["best_step"], "steps_run": state["step"], "stopped": stopped,
                    "batches_skipped": state["skipped"], "gpu_piece_size": state["micro"], "saved_model": bool(saving and state["saved_ap"] is not None)})
    if results["saved_model"]:
        meta_path = out_dir / "model" / "meta.json"
        meta = json.loads(meta_path.read_text())
        meta.update({"thresholds": results["thresholds"], "stopped": stopped})
        meta_path.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"{args.model}: trained {train_minutes:.1f} min ({stopped}), peak {peak:.1f} GB, {results['articles_per_second']:,} articles/s"
          + (f", {state['skipped']} batches skipped as not a number" if state["skipped"] else ""))
    show(results)
    if not trial:
        compare(args.model, results)
    save(args.model, stage, results)
    if results["saved_model"]:
        print(f"the fine-tuned model is saved in {out_dir / 'model'}; score it on the labelled sheet later with:  score {args.model}")


def score_saved(args):
    """Score a fine-tuned model that was saved, on any set (the evaluation sheet, once the team has labelled it), with the thresholds fixed in training."""
    folder = OUT / slug(args.model) / "model"
    if not (folder / "meta.json").exists():
        sys.exit(f"no saved model for {args.model} (looked in {folder}): train it first, without --no-save")
    meta = json.loads((folder / "meta.json").read_text())
    dev = device_of()
    tok = load_tokenizer(str(folder))
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else 0
    model = classifier(str(folder), args.trust_remote_code).to(dev)
    max_len = meta.get("max_len", args.max_len)
    if "thresholds" not in meta:                            # the training run was cut short before it could fix them: do it on val now
        val = read_jsonl("val", args.limit_eval, args.seed)
        if not val:
            sys.exit("no val set: run `splits` first")
        print(f"fixing the thresholds on val ({len(val):,} articles)", flush=True)
        s_val = predict(model, encode(tok, val, max_len), pad_id, dev)
        y_val = np.array([r["label"] for r in val])
        meta["thresholds"] = {"f1_best": best_f1_threshold(y_val, s_val), f"recall_{int(args.recall * 100)}": recall_threshold(y_val, s_val, args.recall)}
        (folder / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    out = {"model": args.model, "thresholds": meta["thresholds"]}
    for name in [s for s in args.sets.split(",") if s]:
        rows = read_jsonl(name, args.limit_eval, args.seed)
        if not rows:
            print(f"{name}: no articles (for the sheet: fill in `relevant`, then run `splits` again)")
            continue
        print(f"scoring {name} ({len(rows):,} articles)", flush=True)
        s = predict(model, encode(tok, rows, max_len), pad_id, dev)
        save_preds(args.model, "score", name, rows, s)
        out[name] = summarise(rows, s, meta["thresholds"])
    show(out)
    save(args.model, "score", out)


# ---- 5. frozen sentence embeddings + a cheap classifier -----------------------------------

# How each sentence-embedding model wants its text and pooling, from its model card. For any other: --pool and --prefix.
EMBEDDERS = {
    "intfloat/multilingual-e5-small": ("mean", "query: "),
    "intfloat/multilingual-e5-base": ("mean", "query: "),
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": ("mean", ""),
}


def urls_md5(rows):
    import hashlib
    return hashlib.md5("\n".join(r["url"] for r in rows).encode("utf-8")).hexdigest()


def embed_settings(args):
    pool, prefix = EMBEDDERS.get(args.model, ("mean", ""))
    return {"pool": args.pool or pool, "prefix": prefix if args.prefix is None else args.prefix, "max_len": args.max_len}


def embed_ids(enc, ids, pad_id, device, batch, pool, desc):
    """One unit-length vector per tokenised text."""
    import torch
    out = None
    order = np.argsort([len(x) for x in ids])
    with torch.no_grad():
        for i in bar(range(0, len(order), batch), desc=desc, unit=" batches", leave=False):
            idx = order[i:i + batch]
            x, m = pad([ids[j] for j in idx], pad_id, device)
            with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                h = enc(input_ids=x, attention_mask=m).last_hidden_state
            h = h.float()
            v = h[:, 0] if pool == "cls" else (h * m.unsqueeze(-1)).sum(1) / m.sum(1, keepdim=True)
            v = torch.nn.functional.normalize(v, dim=-1)
            if out is None:
                out = np.zeros((len(ids), v.shape[1]), dtype=np.float32)
            out[idx] = v.cpu().numpy()
    return out


def embed_sets(args):
    """Embed every article of every set once and keep the vectors, so the classifiers in `head` are fitted in seconds or minutes."""
    from transformers import AutoModel
    dev = device_of()
    cfg = embed_settings(args)
    trial = bool(args.limit_train or args.limit_eval)
    folder = OUT / slug(args.model) / ("emb-trial" if trial else "emb")
    folder.mkdir(parents=True, exist_ok=True)
    meta_path = folder / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    if meta.get("settings") != cfg:                          # other pooling, prefix or length: the old vectors do not apply
        meta = {"settings": cfg, "sets": {}}
    if trial:
        print("a trial on a subset: kept apart from the real embeddings")
    print(f"loading {args.model} on {dev} ({cfg['pool']} pooling" + (f", text prefix {cfg['prefix']!r}" if cfg["prefix"] else "") + ")", flush=True)
    tok = load_tokenizer(args.model)
    enc = AutoModel.from_pretrained(args.model, trust_remote_code=args.trust_remote_code).to(dev).eval()
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else 0
    for name in SETS:
        rows = read_jsonl(name, args.limit_train if name == "train" else args.limit_eval, args.seed)
        if not rows:
            continue
        md5, done = urls_md5(rows), meta["sets"].get(name)
        if done and done["urls_md5"] == md5 and (folder / f"{name}.npy").exists():
            print(f"{name}: already embedded ({done['n']:,} articles)")
            continue
        sync(dev)
        t0 = time.time()
        ids = encode(tok, rows, args.max_len, cfg["prefix"])
        vectors = with_smaller_batches(lambda b: embed_ids(enc, ids, pad_id, dev, b, cfg["pool"], f"embedding {name}"), 128)
        sync(dev)
        seconds = time.time() - t0
        np.save(folder / f"{name}.npy", vectors.astype(np.float16))
        meta["sets"][name] = {"n": len(rows), "urls_md5": md5, "seconds": round(seconds, 1), "articles_per_second": round(len(rows) / seconds)}
        meta_path.write_text(json.dumps(meta, indent=1), encoding="utf-8")      # after each set, so an interrupted run resumes
        print(f"{name}: {len(rows):,} articles in {seconds:.0f} s ({len(rows) / seconds:,.0f} per second, tokenising included)", flush=True)
    print(f"embeddings saved in {folder}; now:  head {args.model}")


def head_features(x, rows):
    """The embedding plus two cheap columns: Chinese or not, and length."""
    extra = np.array([[float(r["lang"] == "zh"), min(len(r["text"]) / 500, 2.0)] for r in rows], dtype=np.float32)
    return np.hstack([x.astype(np.float32), extra])


def fit_logreg(xt, yt, xv, yv, dev, args):
    import torch
    X, Y, Xv = torch.tensor(xt, device=dev), torch.tensor(yt, device=dev), torch.tensor(xv, device=dev)
    best_ap, best = -1.0, None
    for wd in (1e-5, 1e-4, 1e-3):                              # the penalty is picked on val
        w = torch.zeros(X.shape[1], device=dev, requires_grad=True)
        b = torch.zeros(1, device=dev, requires_grad=True)
        opt = torch.optim.Adam([w, b], lr=0.02)
        for _ in bar(range(300), desc=f"logistic regression, penalty {wd:g}", unit=" steps", leave=False):
            opt.zero_grad()
            loss = torch.nn.functional.binary_cross_entropy_with_logits(X @ w + b, Y) + wd * (w * w).sum()
            loss.backward()
            opt.step()
        with torch.no_grad():
            ap = avg_precision(yv, torch.sigmoid(Xv @ w + b).cpu().numpy())
        say(f"  logistic regression, penalty {wd:g}: val AP {ap:.4f}")
        if ap > best_ap:
            best_ap, best = ap, (w.detach().clone(), b.detach().clone())
    w, b = best

    def predict_scores(x):
        with torch.no_grad():
            return torch.sigmoid(torch.tensor(x, device=dev) @ w + b).cpu().numpy()
    return predict_scores


def fit_mlp(xt, yt, xv, yv, dev, args):
    import torch
    nn = torch.nn
    torch.manual_seed(args.seed)
    X, Y, Xv = torch.tensor(xt, device=dev), torch.tensor(yt, device=dev), torch.tensor(xv, device=dev)
    net = nn.Sequential(nn.Linear(X.shape[1], 512), nn.GELU(), nn.Dropout(0.2), nn.Linear(512, 256), nn.GELU(), nn.Dropout(0.2), nn.Linear(256, 1)).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-2)
    gen = torch.Generator().manual_seed(args.seed)
    best_ap, best_state, stale = -1.0, None, 0
    for epoch in range(1, 41):
        net.train()
        order = torch.randperm(len(X), generator=gen).to(dev)
        for i in bar(range(0, len(order), 512), desc=f"MLP epoch {epoch}", unit=" steps", leave=False):
            idx = order[i:i + 512]
            opt.zero_grad()
            nn.functional.binary_cross_entropy_with_logits(net(X[idx]).squeeze(1), Y[idx]).backward()
            opt.step()
        net.eval()
        with torch.no_grad():
            ap = avg_precision(yv, torch.sigmoid(net(Xv).squeeze(1)).cpu().numpy())
        improved = ap > best_ap + args.min_delta
        if improved:
            best_ap, stale, best_state = ap, 0, {k: v.detach().clone() for k, v in net.state_dict().items()}
        else:
            stale += 1
        say(f"  MLP epoch {epoch}: val AP {ap:.4f}  " + ("best so far" if improved else f"no better ({stale}/{args.patience})"))
        if args.patience and stale >= args.patience:
            break
    if best_state is not None:
        net.load_state_dict(best_state)
    net.eval()

    def predict_scores(x):
        with torch.no_grad():
            return torch.sigmoid(net(torch.tensor(x, device=dev)).squeeze(1)).cpu().numpy()
    return predict_scores


def fit_hgb(xt, yt, xv, yv, dev, args):
    """scikit-learn's gradient-boosted trees: the same family as XGBoost, and already installed."""
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
    except ImportError:
        sys.exit("scikit-learn is not installed here: pip install scikit-learn (in the gliner venv)")
    clf = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.1, max_leaf_nodes=31, l2_regularization=1.0, early_stopping=True,
                                         validation_fraction=0.1, n_iter_no_change=20, random_state=args.seed)
    print("  gradient boosting runs on the CPU with no progress bar; it is the slowest of the three", flush=True)
    clf.fit(xt, yt.astype(int))
    print(f"  gradient boosting stopped at {clf.n_iter_} trees (early stopping on a tenth of the training data)")
    return lambda x: clf.predict_proba(x)[:, 1]


def fit_xgb(xt, yt, xv, yv, dev, args):
    """XGBoost itself, if it is installed. Early stopping on val."""
    try:
        import xgboost as xgb
    except ImportError:
        sys.exit("xgboost is not installed here: pip install xgboost (in the gliner venv)")
    clf = xgb.XGBClassifier(n_estimators=2000, learning_rate=0.05, max_depth=6, subsample=0.8, colsample_bytree=0.5, tree_method="hist",
                            device=dev.type, eval_metric="aucpr", early_stopping_rounds=50, random_state=args.seed)
    clf.fit(xt, yt, eval_set=[(xv, yv)], verbose=False)
    print(f"  xgboost stopped at {clf.best_iteration + 1} trees (early stopping on val)")
    return lambda x: clf.predict_proba(x)[:, 1]


HEADS = {"logreg": fit_logreg, "mlp": fit_mlp, "hgb": fit_hgb, "xgb": fit_xgb}


def head(args):
    """Fit cheap classifiers on the saved embeddings, then score them like everything else (thresholds fixed on val)."""
    dev = device_of()
    trial = bool(args.limit_train or args.limit_eval)
    folder = OUT / slug(args.model) / ("emb-trial" if trial else "emb")
    if not (folder / "meta.json").exists():
        sys.exit(f"no embeddings for {args.model} in {folder}: run `embed {args.model}` first" + (" (with the same --limit flags)" if trial else ""))
    meta = json.loads((folder / "meta.json").read_text())
    kinds = [k for k in args.heads.split(",") if k]
    unknown = [k for k in kinds if k not in HEADS]
    if unknown:
        sys.exit(f"unknown head {unknown}: choose from {', '.join(HEADS)}")

    def load(name, rows):
        """This set's embeddings, checked to be the same articles in the same order that were embedded."""
        info = meta["sets"].get(name)
        if info is None or info["urls_md5"] != urls_md5(rows):
            sys.exit(f"the saved embeddings of {name} are of different articles: run `embed` again, with the same --limit flags as here")
        return head_features(np.load(folder / f"{name}.npy"), rows)

    train_rows = read_jsonl("train", args.limit_train, args.seed)
    val_rows = read_jsonl("val", args.limit_eval, args.seed)
    if not train_rows or not val_rows:
        sys.exit("no data: run `splits` first")
    xt, xv = load("train", train_rows), load("val", val_rows)
    mu, sd = xt.mean(0), xt.std(0) + 1e-6
    xt, xv = (xt - mu) / sd, (xv - mu) / sd
    yt = np.array([r["label"] for r in train_rows], dtype=np.float32)
    yv = np.array([r["label"] for r in val_rows], dtype=np.float32)
    print(f"{args.model}: {len(yt):,} training articles ({int(yt.sum()):,} relevant), {xt.shape[1]} features; heads: {', '.join(kinds)}", flush=True)
    for kind in kinds:
        print(f"\n=== {args.model} + {kind}", flush=True)
        t0 = time.time()
        try:
            predict_fn = HEADS[kind](xt, yt, xv, yv, dev, args)
        except (Exception, SystemExit) as e:                  # one head failing, or not installed, never stops the others
            print(f"{kind}: skipped ({type(e).__name__}: {e})")
            continue
        fit_seconds = time.time() - t0
        results = score_sets(lambda rows, name: predict_fn((load(name, rows) - mu) / sd), args,
                             tag="trial" if trial else f"head-{kind}", model_id=None if trial else args.model)
        results.update({"kind": "embedding+head", "head": kind, "model": args.model, "trained_on": len(yt), "fit_seconds": round(fit_seconds, 1),
                        "embed_articles_per_second": meta["sets"].get("test", {}).get("articles_per_second"), "settings": meta["settings"]})
        print(f"{args.model} + {kind}: fitted in {fit_seconds:.0f} s")
        show(results)
        save(args.model, ("trial-head-" if trial else "head-") + kind, results)


def tfidf(args):
    """No neural network at all: word and character n-gram counts and logistic regression. The floor every model has to beat; it runs on a CPU."""
    try:
        from scipy.sparse import hstack
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        sys.exit("scikit-learn is not installed here: pip install scikit-learn (in the gliner venv)")
    args.model = "tfidf"
    trial = bool(args.limit_train or args.limit_eval)
    train_rows = read_jsonl("train", args.limit_train, args.seed)
    val_rows = read_jsonl("val", args.limit_eval, args.seed)
    if not train_rows or not val_rows:
        sys.exit("no data: run `splits` first")
    if trial:
        print("a trial on a subset: nothing is saved as the result")
    t0 = time.time()
    # characters cover Chinese (no spaces between words) and word pairs cover English
    chars = TfidfVectorizer(analyzer="char_wb", ngram_range=(1, 3), min_df=5, max_features=300000, sublinear_tf=True, dtype=np.float32)
    words = TfidfVectorizer(analyzer="word", token_pattern=r"(?u)\b\w+\b", ngram_range=(1, 2), min_df=5, max_features=300000, sublinear_tf=True, dtype=np.float32)

    def vectorise(rows, fit=False):
        texts = [r["text"] for r in rows]
        return hstack([chars.fit_transform(texts), words.fit_transform(texts)] if fit else [chars.transform(texts), words.transform(texts)]).tocsr()

    print(f"counting words and characters in {len(train_rows):,} training articles (no progress bar; a minute or two)", flush=True)
    xt, xv = vectorise(train_rows, fit=True), None
    xv = vectorise(val_rows)
    yt = np.array([r["label"] for r in train_rows])
    yv = np.array([r["label"] for r in val_rows])
    print(f"{xt.shape[1]:,} features; fitting logistic regression with three penalties", flush=True)
    best_ap, best = -1.0, None
    for C in (1.0, 4.0, 16.0):
        clf = LogisticRegression(C=C, solver="liblinear", max_iter=200)
        clf.fit(xt, yt)
        ap = avg_precision(yv, clf.predict_proba(xv)[:, 1])
        say(f"  logistic regression, C={C:g}: val AP {ap:.4f}  ({time.time() - t0:.0f} s so far)")
        if ap > best_ap:
            best_ap, best = ap, (C, clf)
    fit_seconds = time.time() - t0
    C, clf = best

    def score(rows, name=None):
        return clf.predict_proba(vectorise(rows))[:, 1]

    results = score_sets(score, args, tag="trial" if trial else "head-tfidf", model_id=None if trial else "tfidf")
    test = read_jsonl("test", args.limit_eval, args.seed)
    t1 = time.time()
    score(test)
    speed = round(len(test) / (time.time() - t1))
    results.update({"kind": "tfidf+logreg", "head": f"logistic regression, C={C:g}", "model": "tfidf", "trained_on": len(yt), "fit_seconds": round(fit_seconds, 1),
                    "embed_articles_per_second": speed})
    print(f"tfidf + logistic regression: fitted in {fit_seconds:.0f} s, scores {speed:,} articles per second on the CPU")
    show(results)
    save("tfidf", ("trial-head-" if trial else "head-") + "tfidf", results)


def head_table():
    """One row per saved embedding + classifier run."""
    lines = []
    for folder in sorted(p for p in OUT.iterdir() if p.is_dir()) if OUT.exists() else []:
        for path in sorted(folder.glob("head-*.json")):
            r = json.loads(path.read_text())
            rk = next((k for k in r["thresholds"] if k != "f1_best"), None)

            def cell(split, lang, key):
                try:
                    e = r[split][lang]
                    if key == "auc":
                        return f"{e['auc']:.3f}"
                    return f"{e['f1_best']['f1']:.2f}" if key == "f1" else f"{e[rk]['precision']:.2f}"
                except (KeyError, TypeError):
                    return "-"
            lines.append(f"| {folder.name} | {r['head']} | {cell('test', 'all', 'auc')} | {cell('test', 'all', 'f1')} | {cell('test', 'all', 'p95')} | "
                         f"{cell('test', 'en', 'f1')} | {cell('test', 'zh', 'f1')} | {cell('live', 'all', 'f1')} | {cell('human', 'all', 'f1')} | "
                         f"{r['fit_seconds']} | {r.get('embed_articles_per_second') or '-'} |")
    if not lines:
        return ""
    return "\n".join(["| Embedding model | classifier | test AUC | test F1 | precision at 95% recall | F1 English | F1 Chinese | F1 vs Gemini (live) | F1 vs people | seconds to fit | articles/s |",
                      "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"] + lines)


# ---- 6. GLiClass's own training file, and the table ------------------------------------

def export_gliclass(args):
    rows = read_jsonl("train", args.limit_train or 60000, args.seed)
    data = [{"text": r["text"], "all_labels": [LABEL_REL, LABEL_OTHER], "true_labels": [LABEL_REL if r["label"] else LABEL_OTHER]} for r in rows]
    path = OUT / "gliclass-train.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {path} ({len(data):,} articles). Fine-tune with train.py from github.com/Knowledgator/GLiClass pointed at it,\n"
          "then score the result with:  before <the saved model folder> --kind zeroshot")


def report_before(args):
    """Precision, recall and F1 before any fine-tuning, English against Chinese, on every set."""
    found = False
    for folder in sorted(p for p in OUT.iterdir() if p.is_dir()) if OUT.exists() else []:
        if not (folder / "before.json").exists():
            continue
        found = True
        r = json.loads((folder / "before.json").read_text())
        how = "frozen encoder + linear probe" if r["kind"] == "probe" else "zero-shot"
        print(f"\n=== {r['model']} ({how}); thresholds fixed on val: " + ", ".join(f"{k} = {v:.3f}" for k, v in r["thresholds"].items()))
        print(f"{'set':<6}{'lang':<5}{'articles':>9}{'relevant':>9}{'AUC':>7}   " + "   ".join(f"{t}: precision recall F1" for t in r["thresholds"]))
        for split in ("test", "live", "human", "val"):
            for lang in ("all", "en", "zh"):
                e = r.get(split, {}).get(lang)
                if not e:
                    continue
                cells = "   ".join(f"{' ' * (len(t) + 2)}{e[t]['precision']:>9.3f}{e[t]['recall']:>7.3f}{e[t]['f1']:>6.3f}" for t in r["thresholds"])
                print(f"{split:<6}{lang:<5}{e['n']:>9,}{e['relevant']:>9,}{e['auc']:>7.3f}   {cells}")
        e = r["test"]["all"]
        share = e["relevant"] / e["n"]
        print(f"for scale: flagging every article gives precision {share:.3f}, recall 1.000, F1 {2 * share / (1 + share):.3f} on test; AUC 0.5 is chance")
    if not found:
        sys.exit("no `before` runs yet")


def report(args):
    rows = []
    for folder in sorted(p for p in OUT.iterdir() if p.is_dir()) if OUT.exists() else []:
        b = json.loads((folder / "before.json").read_text()) if (folder / "before.json").exists() else None
        a = json.loads((folder / "train.json").read_text()) if (folder / "train.json").exists() else None
        if b is not None or a is not None:               # skip folders such as logs/
            rows.append((folder.name, b, a))
    heads = head_table()
    if not rows and not heads:
        sys.exit("nothing to report yet")
    if not rows:
        print(heads)
        (OUT / "report.md").write_text(heads + "\n", encoding="utf-8")
        return
    t = f"recall_{int(args.recall * 100)}"

    def cell(res, split, lang, key):
        try:
            e = res[split][lang]
            return e[key] if key in ("auc", "ap") else e["f1_best"][key]
        except (KeyError, TypeError):
            return None

    def f(v, d=2):
        return "-" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.{d}f}"

    lines = ["| Model | size (M) | before: AUC | before: F1 | after: AUC | after: F1 | precision at 95% recall | F1 English | F1 Chinese | F1 vs Gemini (live) | F1 vs people | minutes to train | articles/s | GPU GB |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, b, a in rows:
        def prec95(res):
            try:
                return res["test"]["all"][t]["precision"]
            except (KeyError, TypeError):
                return None
        lines.append(f"| {name} | {a['params_m'] if a else '-'} | {f(cell(b, 'test', 'all', 'auc'), 3)} | {f(cell(b, 'test', 'all', 'f1'))} | "
                     f"{f(cell(a, 'test', 'all', 'auc'), 3)} | {f(cell(a, 'test', 'all', 'f1'))} | {f(prec95(a))} | "
                     f"{f(cell(a, 'test', 'en', 'f1'))} | {f(cell(a, 'test', 'zh', 'f1'))} | {f(cell(a, 'live', 'all', 'f1'))} | {f(cell(a, 'human', 'all', 'f1'))} | "
                     f"{a['train_minutes'] if a else '-'} | {a['articles_per_second'] if a else '-'} | {a['peak_vram_gb'] if a else '-'} |")
    text = "\n".join(lines)
    print(text)
    print("\nF1 is at the threshold that maximises F1 on val. 'before' is a frozen encoder with a linear probe, or zero-shot for GLiClass. "
          "'vs people' is the 69 hard cases (and the evaluation sheet, once labelled).")
    if heads:
        print("\nFrozen sentence embeddings + a cheap classifier (thresholds fixed on val, as above):\n")
        print(heads)
        text += "\n\n" + heads
    (OUT / "report.md").write_text(text + "\n", encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stage", choices=["splits", "download", "before", "train", "score", "embed", "head", "tfidf", "report", "report-before", "export-gliclass"])
    p.add_argument("model", nargs="?", help="a Hugging Face model id, e.g. jhu-clsp/mmBERT-small")
    p.add_argument("--kind", choices=["probe", "zeroshot"], default="probe", help="before: a linear probe on the frozen encoder, or zero-shot (GLiClass)")
    p.add_argument("--max-len", type=int, default=192)
    p.add_argument("--batch", type=int, default=32)
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--lr", type=float, default=None, help="default 5e-5 for a small model, 3e-5 otherwise")
    p.add_argument("--pos-weight", type=float, default=1.0, help="weight on the relevant class; thresholds are tuned on val anyway")
    p.add_argument("--recall", type=float, default=0.95)
    p.add_argument("--limit-train", type=int, default=None, help="train on a random subset, to try a model quickly")
    p.add_argument("--limit-eval", type=int, default=None, help="score a random subset of each evaluation set")
    p.add_argument("--probe-n", type=int, default=20000, help="articles the linear probe is fitted on")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--no-save", action="store_true", help="do not keep the fine-tuned weights (otherwise the best are saved: about 0.6 GB small, 1.2 GB base)")
    p.add_argument("--patience", type=int, default=3, help="stop after this many checks on val without improvement (0 = never stop early)")
    p.add_argument("--eval-every", type=float, default=0.5, help="check on val every this many epochs")
    p.add_argument("--min-delta", type=float, default=0.0005, help="how much better val average precision must get to count as an improvement")
    p.add_argument("--sets", default="live,human,sheet", help="for `score`: which sets to score")
    p.add_argument("--pool", choices=["mean", "cls"], default=None, help="for `embed`: how to pool an embedding model's tokens (default: its model card's)")
    p.add_argument("--prefix", default=None, help="for `embed`: text put before each article (e5 models want 'query: ')")
    p.add_argument("--heads", default="logreg,mlp,hgb", help="for `head`: any of logreg, mlp, hgb (scikit-learn trees), xgb (needs xgboost)")
    p.add_argument("--trust-remote-code", action="store_true")
    args = p.parse_args()
    if args.stage in ("download", "before", "train", "score", "embed", "head") and not args.model:
        p.error("this stage needs a model id")
    {"splits": make_splits, "download": download, "before": before, "train": train, "score": score_saved, "embed": embed_sets, "head": head, "tfidf": tfidf, "report": report, "report-before": report_before, "export-gliclass": export_gliclass}[args.stage](args)


if __name__ == "__main__":
    main()
