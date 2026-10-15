"""
Small relevance classifiers fine-tuned, fitted or asked zero-shot, all scored on one cleaned train / val / test split.

The relevance step reads an article's headline and summary and says whether it reports a change to a record. The
labels here are the LLM's verdicts in data/relevance/test_for_relevance.csv (column LLM_Relevance): the 295,268
archive articles, 2015 to September 2026, with the same verdicts the first benchmark used (scripts/relevance_finetune.py).
A classifier can at best agree with that LLM. The 69 human labels (articles where Gemini and that LLM disagreed) are the
only check against people, and a small, hard one.

Three existing environments between them have everything; nothing is installed:

    PY=~/anaconda3/envs/new_env/bin/python        # fastText, sentence encoders, torch with CUDA, scikit-learn
    GL=~/.venvs/gliner/bin/python                 # transformers 5 (mmBERT) and gliclass 0.1.20
    XG=~/anaconda3/envs/link_env/bin/python       # XGBoost
    M1=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
    M2=sentence-transformers/all-MiniLM-L12-v2

    $PY scripts/relevance_models.py dataset              # once: the split, in data/relevance/splits/, and its numbers
    $PY scripts/relevance_models.py fasttext             # fastText with its defaults, then the best of 20 settings on val
    $PY scripts/relevance_models.py finetune $M1         # the whole encoder fine-tuned
    $PY scripts/relevance_models.py embed $M1            # frozen vectors, kept for `heads`
    $PY scripts/relevance_models.py heads $M1 --heads logreg
    $PY scripts/relevance_models.py finetune $M2
    $PY scripts/relevance_models.py embed $M2
    $XG scripts/relevance_models.py heads $M2 --heads xgb
    $GL scripts/relevance_models.py finetune jhu-clsp/mmBERT-base
    $GL scripts/relevance_models.py gliclass knowledgator/gliclass-multilang-mini                    # zero-shot: no training
    $GL scripts/relevance_models.py gliclass knowledgator/gliclass-multilang-mini --asked changes    # the question put another way
    $GL scripts/relevance_models.py gliclass knowledgator/gliclass-multilang-mini --prompt --examples 8   # with our prompt and examples
    $GL scripts/relevance_models.py finetune-gliclass knowledgator/gliclass-multilang-mini               # GLiClass fine-tuned
    $GL scripts/relevance_models.py embed jhu-clsp/mmBERT-base && $GL scripts/relevance_models.py heads jhu-clsp/mmBERT-base
    $PY scripts/relevance_models.py tfidf                # word and character counts + logistic regression
    $PY scripts/relevance_models.py e5                   # the first benchmark's multilingual-e5-small vectors + three classifiers
    $GL scripts/relevance_models.py mmbert               # the first benchmark's fine-tuned mmBERT-small, as saved
    $PY scripts/relevance_models.py cpu && $GL scripts/relevance_models.py cpu   # each saved model's speed on 4 CPU threads, and size
    $PY scripts/relevance_models.py report               # one table: data/relevance/report.md

The split
    Excel damage   some articles in the CSV carry Excel's damage (â€™ for ’, "#NAME?" for a summary that began with
                   "-"); their text is taken from the untouched copy, data/backfill/answers/relevance.csv.
    copies         a story is kept once: the rules of src/shared/stories.py (the same article at a new address, or the
                   same outlet and title within two days unless the title is a column), plus the same headline and
                   summary on any date. The earliest copy stays. A story whose copies the LLM labelled differently is
                   dropped.
    by date        train before July 2024, val July 2024 to June 2025, test July 2025 to June 2026. A model is tested
                   on news later than anything it learned from, as it will be used. These are the first benchmark's
                   dates, so its saved models line up. July to September 2026 is left out: it overlaps the live set.
    live, human    from the first benchmark: Gemini's verdicts on 3,747 live articles, and the 69 human labels.

Every model is scored the same way. The thresholds are fixed on val, never on test (one maximising F1, one keeping
recall at 95%), then applied to train, val, test, live and human. Train against val shows how much a model memorised.
"""

import argparse
import csv
import json
import math
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import relevance_finetune as rf                        # noqa: E402  the measures, batching and classifiers of the first benchmark

DATA = Path(os.environ.get("RELEVANCE_DATA") or ROOT / "data" / "relevance")    # another folder, for a quick trial on a sample
SOURCE = DATA / "test_for_relevance.csv"
UNTOUCHED = ROOT / "data/backfill/answers/relevance.csv"
FIRST = ROOT / "data" / "finetune"                     # the first benchmark
SPLITS = DATA / "splits"
SETS = ("train", "val", "test", "live", "human")


def read(name):
    path = SPLITS / f"{name}.jsonl"
    if not path.exists():
        sys.exit(f"no {path}: run `dataset` first")
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def labels(rows):
    return np.array([r["label"] for r in rows], dtype=np.float32)


# ---- 1. the dataset ----------------------------------------------------------------

CJK = re.compile(r"([⺀-鿿豈-﫿＀-￯])")


def ft_tokens(text):
    """fastText splits on spaces, and Chinese has none: each Chinese character becomes a word (word pairs then cover
    two-character words), and punctuation is split off."""
    t = CJK.sub(r" \1 ", text.casefold())
    t = re.sub(r"([^\w\s])", r" \1 ", t)
    return " ".join(t.split())


def dataset(_args):
    from src.shared.stories import find_copies, outlet, same_title
    csv.field_size_limit(2 ** 31 - 1)
    untouched = {}
    if UNTOUCHED.exists():
        with open(UNTOUCHED, encoding="utf-8-sig", newline="") as f:
            untouched = {r["url"]: (r["title"], r["description"]) for r in csv.DictReader(f)}
    rows, n_read, repaired, no_text = [], 0, 0, 0
    with open(SOURCE, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            n_read += 1
            title, description = r["title"], r["description"]
            good = untouched.get(r["url"])
            if good and rf.clean(*good) != rf.clean(title, description):
                (title, description), repaired = good, repaired + 1
            text = rf.clean(title, description)
            if not text:
                no_text += 1
                continue
            rows.append({"url": r["url"], "source": r["source"], "lang": rf.lang_of(r["source"]),
                         "day": datetime.strptime(r["published"].strip(), "%d/%m/%Y").date().isoformat(),     # day first: 13/1/2015
                         "title": title, "text": text, "label": int(r["LLM_Relevance"].strip().upper() == "TRUE"), "reason": r["reason"]})
    rows.sort(key=lambda r: r["day"])                  # stable, so within a day the file's order holds; the earliest copy is kept

    # copies: the pipeline's own rules, then the same headline and summary on any date
    days = defaultdict(set)
    for r in rows:
        days[(outlet(r["url"]), same_title(r["title"]))].add(r["day"])
    copies = find_copies([{"url": r["url"], "title": r["title"], "pubDate": r["day"]} for r in rows], [],
                         uses=lambda name, title: len(days[(name, same_title(title))]))
    parent = {r["url"]: r["url"] for r in rows}

    def root(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    found = Counter()

    def join(earlier, later, why):
        a, b = root(earlier), root(later)
        if a != b:
            parent[b] = a
            found[why] += 1

    for url, (original, why) in copies.items():
        join(original, url, why)
    first = {}
    for r in rows:
        key = re.sub(r"\W+", " ", r["text"].casefold()).strip()
        if key in first:
            join(first[key], r["url"], "the same headline and summary")
        else:
            first[key] = r["url"]
    groups = defaultdict(list)
    for r in rows:
        groups[root(r["url"])].append(r)
    kept, removed, conflicting = [], 0, 0
    for g in groups.values():
        if len({r["label"] for r in g}) > 1:
            conflicting += len(g)
            continue
        kept.append(g[0])
        removed += len(g) - 1

    sets, later = {"train": [], "val": [], "test": []}, 0
    for r in kept:
        del r["title"]
        if r["day"] < rf.CUTS[0]:
            sets["train"].append(r)
        elif r["day"] < rf.CUTS[1]:
            sets["val"].append(r)
        elif r["day"] < rf.CUTS[2]:
            sets["test"].append(r)
        else:
            later += 1
    sets["live"] = rf.read_jsonl("live")               # the first benchmark's, from data/finetune
    sets["human"] = rf.read_jsonl("human")
    in_splits = {r["url"] for name in ("train", "val", "test") for r in sets[name]}
    (SPLITS / "fasttext").mkdir(parents=True, exist_ok=True)
    for name in SETS:
        write(SPLITS / f"{name}.jsonl", sets[name])
        with open(SPLITS / "fasttext" / f"{name}.txt", "w", encoding="utf-8") as f:
            for r in sets[name]:
                f.write(f"__label__{r['label']} {ft_tokens(r['text'])}\n")

    info = {"read": n_read, "excel_damage_repaired": repaired, "no_text": no_text, "copies_removed": removed,
            "copies_found_by_rule": dict(found), "conflicting_copies_dropped": conflicting, "july_to_september_2026_left_out": later,
            "cuts": rf.CUTS, "live_or_human_in_splits": sum(r["url"] in in_splits for n in ("live", "human") for r in sets[n]), "sets": {}}
    print(f"read {n_read:,}; Excel damage repaired {repaired:,}; no text {no_text:,}; copies removed {removed:,} {dict(found)}; "
          f"copies the LLM labelled differently, dropped {conflicting:,}; July to September 2026 left out {later:,}")
    print(f"\n{'set':<7}{'from':>12}{'to':>12}{'articles':>10}{'relevant':>10}{'share':>7}{'English':>9}{'relevant':>10}{'Chinese':>9}{'relevant':>10}")
    for name in SETS:
        rs = sets[name]
        en, zh = [r for r in rs if r["lang"] == "en"], [r for r in rs if r["lang"] == "zh"]
        dated = sorted(r["day"] for r in rs if len(r.get("day", "")) == 10)
        e = {"articles": len(rs), "relevant": sum(r["label"] for r in rs), "english": len(en), "english_relevant": sum(r["label"] for r in en),
             "chinese": len(zh), "chinese_relevant": sum(r["label"] for r in zh), "from": dated[0] if dated else "", "to": dated[-1] if dated else ""}
        info["sets"][name] = e
        print(f"{name:<7}{e['from']:>12}{e['to']:>12}{e['articles']:>10,}{e['relevant']:>10,}{e['relevant'] / max(e['articles'], 1):>7.1%}"
              f"{e['english']:>9,}{e['english_relevant']:>10,}{e['chinese']:>9,}{e['chinese_relevant']:>10,}")
    (DATA / "dataset.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    print(f"\nwritten to {SPLITS}; live or human articles also in train/val/test: {info['live_or_human_in_splits']}")


# ---- 2. scoring, the same for every model ----------------------------------------------

def save_preds(name, split, rows, scores):
    folder = DATA / "preds"
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / f"{rf.slug(name)}-{split}.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["url", "lang", "label", "score"])
        for r, s in zip(rows, scores):
            w.writerow([r["url"], r["lang"], r["label"], f"{float(s):.5f}"])


def show(res):
    for split in SETS:
        for lang in ("all", "en", "zh"):
            e = res.get(split, {}).get(lang)
            if e:
                m = e["f1_best"]
                print(f"  {split:<6}{lang:<4}n={e['n']:>7,} relevant={e['relevant']:>6,}  AUC {e['auc']:.3f}  AP {e['ap']:.3f}  "
                      f"| at the val F1 threshold: P {m['precision']:.2f} R {m['recall']:.2f} F1 {m['f1']:.2f} | at 95% val recall: P {e['recall_95']['precision']:.2f} R {e['recall_95']['recall']:.2f}")


def score_everything(name, score_fn, info, sets=SETS):
    """Score every set, fix the thresholds on val, keep the results and each article's score (train's are not kept)."""
    out, scored = {"model": name, **info}, {}
    for split in sets:
        rows = read(split)
        rf.say(f"scoring {split} ({len(rows):,} articles)")
        t0 = time.perf_counter()
        scored[split] = (rows, np.asarray(score_fn(rows, split), dtype=np.float64), time.perf_counter() - t0)
    rows, s_val, _ = scored["val"]
    y = labels(rows)
    out["thresholds"] = {"f1_best": rf.best_f1_threshold(y, s_val), "recall_95": rf.recall_threshold(y, s_val, 0.95)}
    for split, (rows, scores, seconds) in scored.items():
        out[split] = rf.summarise(rows, scores, out["thresholds"])
        out[split]["seconds"] = round(seconds, 1)
        if split != "train":
            save_preds(name, split, rows, scores)
    if "articles_per_second" not in out and "test" in scored:
        rows, _, seconds = scored["test"]
        out["articles_per_second"] = round(len(rows) / max(seconds, 1e-9))
    (DATA / "results").mkdir(parents=True, exist_ok=True)
    (DATA / "results" / f"{rf.slug(name)}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\n{name}  (thresholds fixed on val: F1-best {out['thresholds']['f1_best']:.4f}, 95% recall {out['thresholds']['recall_95']:.4f})")
    show(out)
    return out


HEAD_ARGS = SimpleNamespace(seed=0, min_delta=0.0005, patience=3)


def standardised(x):
    """Each set's features scaled by train's mean and spread."""
    mu, sd = x["train"].mean(0), x["train"].std(0) + 1e-6
    return {k: ((v - mu) / sd).astype(np.float32) for k, v in x.items()}


# ---- 3. fastText ------------------------------------------------------------------------

def fasttext_stage(args):
    """fastText's own autotune can try settings that need more memory than this machine has (10M buckets x hundreds of
    dimensions), so the search is a fixed random sample of settings within safe bounds, each judged on val."""
    import fasttext
    folder = SPLITS / "fasttext"
    train_n = sum(1 for _ in open(folder / "train.txt", encoding="utf-8"))
    val = read("val")
    yv = labels(val)
    val_texts = [ft_tokens(r["text"]) for r in val]
    threads = max(1, (os.cpu_count() or 4) - 4)

    def p_relevant(model, texts):
        got, probs = model.predict(texts, k=-1)         # a list goes to fastText's C++ in one call (and misses its NumPy 2 bug)
        return np.array([dict(zip(g, p)).get("__label__1", 0.0) for g, p in zip(got, probs)])

    rng = random.Random(args.seed)
    trials = [{}]                                      # fastText's defaults first
    for _ in range(args.trials):
        minn, maxn = rng.choice([(0, 0), (2, 5), (3, 6)])
        trials.append({"lr": round(math.exp(rng.uniform(math.log(0.05), math.log(1.0))), 3), "epoch": rng.randint(5, 40),
                       "dim": rng.choice([50, 100, 200]), "wordNgrams": rng.choice([1, 2, 3]), "minn": minn, "maxn": maxn, "bucket": 2_000_000})
    search, default, best = [], None, None
    t_search = time.perf_counter()
    for i, params in enumerate(trials):
        t0 = time.perf_counter()
        model = fasttext.train_supervised(input=str(folder / "train.txt"), thread=threads, verbose=0, seed=args.seed, **params)
        seconds = time.perf_counter() - t0
        s = p_relevant(model, val_texts)
        ap, auc = rf.avg_precision(yv, s), rf.rank_auc(yv, s)
        search.append({"settings": params or "defaults", "val_ap": ap, "val_auc": auc, "seconds": round(seconds, 1)})
        rf.say(f"  {i:>2}/{len(trials) - 1} {params or 'defaults'}: val AP {ap:.4f}  AUC {auc:.4f}  ({seconds:.0f} s)")
        if i == 0:
            default = (model, seconds)
        if best is None or ap > best[0]:
            best = (ap, params, model, seconds)
    search_minutes = (time.perf_counter() - t_search) / 60
    (DATA / "fasttext-search.json").write_text(json.dumps(search, indent=1), encoding="utf-8")

    def scorer(model):
        return lambda rows, split: p_relevant(model, [ft_tokens(r["text"]) for r in rows])

    model, seconds = default
    score_everything("fastText, default settings", scorer(model),
                     {"kind": "fastText", "how": "fastText's defaults (5 epochs, single words)", "trained_on": train_n, "train_minutes": round(seconds / 60, 2)})
    ap, params, model, seconds = best
    path = DATA / "models" / "fasttext.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(path))
    score_everything("fastText, tuned on val", scorer(model),
                     {"kind": "fastText", "how": f"the best of {len(trials)} settings by val average precision", "settings": params,
                      "trained_on": train_n, "train_minutes": round(search_minutes, 1), "fit_minutes_best": round(seconds / 60, 2),
                      "model_mb": round(path.stat().st_size / 1e6)})


# ---- 4. encoders: frozen vectors + a classifier, the whole encoder fine-tuned, or zero-shot ------------------

SHORT = {"sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": "MiniLM-L12 multilingual",
         "sentence-transformers/all-MiniLM-L12-v2": "all-MiniLM-L12 (English only)",
         "jhu-clsp/mmBERT-base": "mmBERT-base",
         "knowledgator/gliclass-multilang-mini": "GLiClass multilang-mini"}
HEAD_LABEL = {"logreg": "logistic regression", "mlp": "MLP", "hgb": "gradient-boosted trees", "xgb": "XGBoost"}
HEADS = {"logreg": rf.fit_logreg, "mlp": rf.fit_mlp, "hgb": rf.fit_hgb, "xgb": rf.fit_xgb}


def short(model):
    return SHORT.get(model, model.rsplit("/", 1)[-1])


def embed(args):
    """Each article's vector from the frozen encoder (the mean of its token vectors, unit length), kept for `heads`."""
    from transformers import AutoModel, AutoTokenizer
    dev = rf.device_of()
    tok = AutoTokenizer.from_pretrained(args.model)
    enc = AutoModel.from_pretrained(args.model).to(dev).eval()
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else 0
    folder = DATA / "emb" / rf.slug(args.model)
    folder.mkdir(parents=True, exist_ok=True)
    meta = {"model": args.model, "max_len": args.max_len, "sets": {}}
    for s in SETS:
        rows = read(s)
        rf.sync(dev)
        t0 = time.perf_counter()
        ids = rf.encode(tok, rows, args.max_len)
        vec = rf.with_smaller_batches(lambda b: rf.embed_ids(enc, ids, pad_id, dev, b, "mean", f"embedding {s}"), 256)
        rf.sync(dev)
        seconds = time.perf_counter() - t0
        np.save(folder / f"{s}.npy", vec.astype(np.float16))
        meta["sets"][s] = {"n": len(rows), "urls_md5": rf.urls_md5(rows), "articles_per_second": round(len(rows) / seconds)}
        print(f"{s}: {len(rows):,} articles in {seconds:.0f} s, tokenising included", flush=True)
    (folder / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"saved in {folder}; now:  heads {args.model} --heads logreg,xgb")


def heads(args):
    """Classifiers on the frozen vectors that `embed` saved."""
    folder = DATA / "emb" / rf.slug(args.model)
    if not (folder / "meta.json").exists():
        sys.exit(f"no vectors for {args.model}: run `embed {args.model}` first")
    meta = json.loads((folder / "meta.json").read_text())
    data, x = {s: read(s) for s in SETS}, {}
    for s in SETS:
        if meta["sets"].get(s, {}).get("urls_md5") != rf.urls_md5(data[s]):
            sys.exit(f"the saved {s} vectors are of other articles: run `embed {args.model}` again")
        x[s] = rf.head_features(np.load(folder / f"{s}.npy"), data[s])
    x = standardised(x)
    dev = rf.device_of()
    for kind in args.heads.split(","):
        yt, yv = labels(data["train"]), labels(data["val"])
        if kind == "xgb":                              # XGBoost wants whole-number classes
            yt, yv = yt.astype(int), yv.astype(int)
        t0 = time.perf_counter()
        fit = HEADS[kind](x["train"], yt, x["val"], yv, dev, HEAD_ARGS)
        score_everything(f"{short(args.model)}, frozen + {HEAD_LABEL[kind]}", lambda rows, s: fit(x[s]),
                         {"kind": "embedding+head", "how": f"frozen encoder, mean-pooled, + {HEAD_LABEL[kind]}", "trained_on": len(yt),
                          "train_minutes": round((time.perf_counter() - t0) / 60, 2), "articles_per_second": meta["sets"]["test"]["articles_per_second"]})


def fit(model, args, steps_per_epoch, epoch_batches, loss_of, val_scores, y_val):
    """The recipe every fine-tune here shares. AdamW with weight decay 0.01 except on biases and norms; the learning rate
    warms up over the first 6% of steps, then falls linearly to zero; gradients clipped at 1. Val is scored twice an
    epoch (and at the very end, unless a check has only just happened); training stops after --patience checks without
    improvement in val average precision, and the best weights are put back. The learning rate is --lr, or by size:
    3e-5 for a model of 200M parameters or more, 5e-5 below."""
    import torch
    params = sum(p.numel() for p in model.parameters())
    lr = args.lr or (3e-5 if params >= 200e6 else 5e-5)
    decay = [p for n, p in model.named_parameters() if p.ndim >= 2 and "norm" not in n.lower()]
    no_decay = [p for n, p in model.named_parameters() if not (p.ndim >= 2 and "norm" not in n.lower())]
    opt = torch.optim.AdamW([{"params": decay, "weight_decay": 0.01}, {"params": no_decay, "weight_decay": 0.0}], lr=lr)
    total, warm = steps_per_epoch * args.epochs, max(1, int(0.06 * steps_per_epoch * args.epochs))
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min((s + 1) / warm, max(0.0, (total - s) / max(total - warm, 1))))
    every = max(1, steps_per_epoch // 2)
    print(f"{params / 1e6:.0f}M parameters; learning rate {lr:g}; {steps_per_epoch:,} steps an epoch, up to {args.epochs} epochs; "
          f"checked on val every {every:,} steps; stops after {args.patience} checks without improvement", flush=True)
    best = {"ap": -1.0, "state": None, "step": 0}
    stale, step, history, stopped = 0, 0, [], "completed all epochs"
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    t_train = time.perf_counter()
    model.train()
    try:
        for epoch in range(1, args.epochs + 1):
            running, n = 0.0, 0
            pb = rf.bar(epoch_batches(epoch), total=steps_per_epoch, desc=f"epoch {epoch}/{args.epochs}", unit=" steps")
            for batch in pb:
                loss = loss_of(batch)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                sched.step()
                opt.zero_grad(set_to_none=True)
                step += 1
                running, n = running + loss.item(), n + 1
                if n % 50 == 0 and hasattr(pb, "set_postfix"):
                    pb.set_postfix(loss=f"{running / n:.4f}")
                if step % every == 0 or (step == total and step % every >= every // 2):
                    s_val = val_scores()
                    ap, auc = rf.avg_precision(y_val, s_val), rf.rank_auc(y_val, s_val)
                    better = ap > best["ap"] + args.min_delta
                    if better:
                        best = {"ap": ap, "step": step, "state": {k: v.detach().to("cpu", copy=True) for k, v in model.state_dict().items()}}
                        stale = 0
                    else:
                        stale += 1
                    history.append({"step": step, "epoch": round(step / steps_per_epoch, 2), "train_loss": round(running / n, 4), "val_ap": ap,
                                    "val_auc": auc, "minutes": round((time.perf_counter() - t_train) / 60, 2)})
                    rf.say(f"  step {step:,} (epoch {step / steps_per_epoch:.2f}): train loss {running / n:.4f}  val AP {ap:.4f}  AUC {auc:.4f}  "
                           + ("best so far" if better else f"no better ({stale}/{args.patience})"))
                    if stale >= args.patience and step < total:
                        stopped = f"early stop: no improvement in {args.patience} checks"
                        break
            if hasattr(pb, "close"):
                pb.close()
            if stopped.startswith("early"):
                break
    except KeyboardInterrupt:
        stopped = "stopped by Ctrl+C"
        rf.say("Ctrl+C: scoring the best weights so far")
    if best["state"] is None:
        sys.exit("stopped before the first check on val: nothing to score")
    model.load_state_dict(best["state"])
    model.eval()
    return {"params_m": round(params / 1e6), "lr": lr, "train_minutes": round((time.perf_counter() - t_train) / 60, 1), "stopped": stopped,
            "best_step": best["step"], "best_val_ap": best["ap"], "checks": len(history), "history": history, "epochs_max": args.epochs, "batch": args.batch,
            "peak_gpu_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2) if torch.cuda.is_available() else 0}


def finetune(args):
    """The whole encoder fine-tuned: the mean of its token vectors (as sentence encoders are trained to embed) into one output."""
    import torch
    from transformers import AutoModel, AutoTokenizer
    dev = rf.device_of()
    tok = AutoTokenizer.from_pretrained(args.model)
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else 0
    data = {s: read(s) for s in SETS}
    ids = {s: rf.encode(tok, rows, args.max_len) for s, rows in data.items()}
    torch.manual_seed(args.seed)

    class Classifier(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.encoder = AutoModel.from_pretrained(args.model)
            self.drop = torch.nn.Dropout(0.1)
            self.head = torch.nn.Linear(self.encoder.config.hidden_size, 1)

        def forward(self, x, m):
            h = self.encoder(input_ids=x, attention_mask=m).last_hidden_state.float()
            v = (h * m.unsqueeze(-1)).sum(1) / m.sum(1, keepdim=True)
            return self.head(self.drop(v)).squeeze(-1)

    model = Classifier().to(dev)
    bf16 = dev.type == "cuda"

    def scores_of(token_ids, batch=256):
        was_training = model.training
        model.eval()
        order = np.argsort([len(t) for t in token_ids])
        out = np.zeros(len(token_ids), dtype=np.float32)
        with torch.no_grad():
            for i in range(0, len(order), batch):
                idx = order[i:i + batch]
                x, m = rf.pad([token_ids[j] for j in idx], pad_id, dev)
                with torch.autocast(dev.type, dtype=torch.bfloat16, enabled=bf16):
                    out[idx] = torch.sigmoid(model(x, m).float()).cpu().numpy()
        model.train(was_training)
        return out

    lengths = [len(t) for t in ids["train"]]
    y = torch.tensor(labels(data["train"]))
    rng = random.Random(args.seed)

    def loss_of(idx):
        x, m = rf.pad([ids["train"][j] for j in idx], pad_id, dev)
        with torch.autocast(dev.type, dtype=torch.bfloat16, enabled=bf16):
            logits = model(x, m)
        return torch.nn.functional.binary_cross_entropy_with_logits(logits.float(), y[idx].to(dev))

    print(f"{args.model}: {len(lengths):,} training articles ({int(y.sum()):,} relevant), median {int(np.median(lengths))} tokens", flush=True)
    run = fit(model, args, math.ceil(len(lengths) / args.batch), lambda epoch: rf.batches(lengths, args.batch, rng), loss_of,
              lambda: scores_of(ids["val"]), labels(data["val"]))
    rf.sync(dev)
    t0 = time.perf_counter()
    scores_of(rf.encode(tok, data["test"], args.max_len))   # speed, tokenising included
    rf.sync(dev)
    speed = round(len(data["test"]) / (time.perf_counter() - t0))
    res = score_everything(f"{short(args.model)}, fine-tuned", lambda rows, s: scores_of(ids[s]),
                           {"kind": "fine-tuned", "how": f"whole encoder fine-tuned, mean pooling; best of {run['checks']} checks on val",
                            "trained_on": len(lengths), "articles_per_second": speed, "max_len": args.max_len, **run})
    folder = DATA / "models" / rf.slug(args.model)
    model.encoder.save_pretrained(folder)
    tok.save_pretrained(folder)
    torch.save(model.head.state_dict(), folder / "head.pt")
    (folder / "meta.json").write_text(json.dumps({"base": args.model, "pooling": "mean", "max_len": args.max_len, "thresholds": res["thresholds"],
                                                  "best_val_ap": run["best_val_ap"], "step": run["best_step"]}, indent=1), encoding="utf-8")
    print(f"saved in {folder}")


def finetune_gliclass(args):
    """GLiClass fine-tuned with its own data format and loss (its two described labels, which one is right), under the same
    recipe as the encoders above. Its labels are shuffled in training so it cannot learn their order; scoring keeps them in order."""
    import torch
    from gliclass import GLiClassModel
    from gliclass.data_processing import AugmentationConfig, DataCollatorWithPadding, GLiClassDataset
    from transformers import AutoTokenizer
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    dev = rf.device_of()
    bf16 = dev.type == "cuda"
    torch.manual_seed(args.seed)
    model = GLiClassModel.from_pretrained(args.model).to(dev)
    tok = AutoTokenizer.from_pretrained(args.model)
    cfg = model.config
    cfg.problem_type = "multi_label_classification"    # one yes/no score per label, as the pipeline scores it (the checkpoint says single-label)
    choices = [rf.LABEL_REL, rf.LABEL_OTHER]
    data = {s: read(s) for s in SETS}
    collate = DataCollatorWithPadding(device=str(dev), config=cfg)

    def dataset(rows, shuffle):
        items = [{"text": r["text"], "all_labels": list(choices), "true_labels": [choices[0] if r["label"] else choices[1]]} for r in rows]
        return GLiClassDataset(items, tok, AugmentationConfig(enabled=False), max_length=args.max_len + 128, problem_type="multi_label_classification",
                               architecture_type=cfg.architecture_type, prompt_first=cfg.prompt_first, shuffle_labels=shuffle)

    def on_device(batch, keep_labels):
        inputs = {k: v.to(dev) for k, v in batch.items() if isinstance(v, torch.Tensor) and (keep_labels or k != "labels")}
        return inputs, batch["max_num_classes"]

    def scores_of(rows, batch=128):
        was_training = model.training
        model.eval()
        out = []
        with torch.no_grad():
            for b in torch.utils.data.DataLoader(dataset(rows, False), batch_size=batch, collate_fn=collate, num_workers=4):
                inputs, k = on_device(b, False)
                with torch.autocast(dev.type, dtype=torch.bfloat16, enabled=bf16):
                    logits = model(**inputs, max_num_classes=k).logits
                out.append(torch.sigmoid(logits[:, 0].float()).cpu().numpy())      # the relevant label comes first
        model.train(was_training)
        return np.concatenate(out)

    train_set = dataset(data["train"], True)

    def epoch_batches(epoch):
        return torch.utils.data.DataLoader(train_set, batch_size=args.batch, shuffle=True, collate_fn=collate, num_workers=4,
                                           generator=torch.Generator().manual_seed(args.seed + epoch))

    def loss_of(b):
        inputs, k = on_device(b, True)
        with torch.autocast(dev.type, dtype=torch.bfloat16, enabled=bf16):
            out = model(**inputs, max_num_classes=k)
        return out.loss.float()

    print(f"{args.model}: {len(train_set):,} training articles, labels {choices}", flush=True)
    run = fit(model, args, math.ceil(len(train_set) / args.batch), epoch_batches, loss_of, lambda: scores_of(data["val"]), labels(data["val"]))
    rf.sync(dev)
    t0 = time.perf_counter()
    scores_of(data["test"])
    rf.sync(dev)
    speed = round(len(data["test"]) / (time.perf_counter() - t0))
    res = score_everything(f"{short(args.model)}, fine-tuned", lambda rows, s: scores_of(rows),
                           {"kind": "fine-tuned", "how": f"fine-tuned on its two described labels; best of {run['checks']} checks on val",
                            "trained_on": len(train_set), "articles_per_second": speed, "max_len": args.max_len + 128, **run})
    folder = DATA / "models" / rf.slug(args.model)
    model.save_pretrained(folder)
    tok.save_pretrained(folder)
    (folder / "meta.json").write_text(json.dumps({"base": args.model, "labels": choices, "thresholds": res["thresholds"],
                                                  "best_val_ap": run["best_val_ap"], "step": run["best_step"]}, indent=1), encoding="utf-8")
    print(f"saved in {folder}")


# Two ways to put the question to a zero-shot classifier: the first benchmark's two described labels, or one short label
# per kind of record change (the article's score is its best change label).
CHANGES = ["a person died", "a person was appointed to a new post", "a person retired or stepped down", "a person or organisation won an award",
           "organisations merged", "an organisation was renamed", "something opened or launched", "something closed or shut down",
           "a new law took effect"]
ASKED = {"described": ([rf.LABEL_REL, rf.LABEL_OTHER], [rf.LABEL_REL]), "changes": (CHANGES + ["other news"], CHANGES)}
# prompts/relevance.txt (the pipeline's prompt to Gemini), shortened to fit beside the article in GLiClass's 1,024 tokens
TASK_PROMPT = ("Decide whether this Singapore news article reports a concrete change, already made or announced, to a named Singapore "
               "person, organisation, building, place, event, programme or law, that a national knowledge base should record: a death, "
               "appointment, retirement, marriage or named award; an organisation created, merged, closed, renamed or relocated; a building "
               "opened, closed, demolished, renamed or given heritage status; an event cancelled, postponed or moved; a programme launched or "
               "ended; a law enacted, amended or repealed. Not relevant: commentary, people merely quoted, reactions, routine updates, court "
               "cases, foreign entities, one-off events, and plans not yet in effect.")


def few_shot(n, labels_of, seed=0):
    """n short training articles, half relevant and half not, a quarter of each half Chinese: in-context examples."""
    rng = random.Random(seed)
    train = [r for r in read("train") if len(r["text"]) <= (120 if r["lang"] == "zh" else 260)]
    picked = []
    for label in (1, 0):
        for lang, k in (("zh", n // 8), ("en", n // 2 - n // 8)):
            picked += rng.sample([r for r in train if r["label"] == label and r["lang"] == lang], k)
    return [{"text": r["text"], "labels": labels_of(r["label"])} for r in picked]


def gliclass(args):
    """A zero-shot classifier asked the relevance question, with no training. It learns nothing from train, so it has no
    train score; its thresholds are still fixed on val."""
    from gliclass import GLiClassModel, ZeroShotClassificationPipeline
    from transformers import AutoTokenizer
    dev = rf.device_of()
    pipe = ZeroShotClassificationPipeline(GLiClassModel.from_pretrained(args.model), AutoTokenizer.from_pretrained(args.model),
                                          classification_type="multi-label", device=str(dev))
    choices, relevant = ASKED[args.asked]
    examples = few_shot(args.examples, lambda y: relevant[:1] if y else [choices[-1]]) if args.examples else None
    extra = {"prompt": TASK_PROMPT if args.prompt else None, "examples": examples}

    def score(rows, split):
        out = []
        for i in rf.bar(range(0, len(rows), args.batch), desc=f"zero-shot {split}", unit=" batches", leave=False):
            for res in pipe([r["text"] for r in rows[i:i + args.batch]], choices, threshold=0.0, batch_size=args.batch, **extra):
                got = {d["label"]: d["score"] for d in res}
                out.append(max(got.get(c, 0.0) for c in relevant))
        return out

    how = "two described labels" if args.asked == "described" else f"{len(CHANGES)} kinds of change and \"other news\""
    how += (", our relevance prompt" if args.prompt else "") + (f", {args.examples} training articles as examples" if args.examples else "")
    tag = args.asked + (", our prompt" if args.prompt else "") + (f" + {args.examples} examples" if args.examples else "")
    score_everything(f"{short(args.model)}, zero-shot ({tag})", score,
                     {"kind": "zero-shot", "how": f"asked with {how}, no training", "trained_on": 0, "labels": choices, **extra},
                     sets=("val", "test", "live", "human"))


# ---- 5. the earlier models on this split --------------------------------------------------

def tfidf(_args):
    """Word and character counts and logistic regression, as in the first benchmark, refitted on this split."""
    from scipy.sparse import hstack
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    train, val = read("train"), read("val")
    chars = TfidfVectorizer(analyzer="char_wb", ngram_range=(1, 3), min_df=5, max_features=300000, sublinear_tf=True, dtype=np.float32)
    words = TfidfVectorizer(analyzer="word", token_pattern=r"(?u)\b\w+\b", ngram_range=(1, 2), min_df=5, max_features=300000, sublinear_tf=True, dtype=np.float32)

    def vectorise(rows, fit=False):
        texts = [r["text"] for r in rows]
        return hstack([chars.fit_transform(texts), words.fit_transform(texts)] if fit else [chars.transform(texts), words.transform(texts)]).tocsr()

    t0 = time.perf_counter()
    print(f"counting words and characters in {len(train):,} training articles", flush=True)
    xt = vectorise(train, fit=True)
    xv = vectorise(val)
    best = None
    for C in (1.0, 4.0, 16.0):
        clf = LogisticRegression(C=C, solver="liblinear", max_iter=200).fit(xt, labels(train))
        ap = rf.avg_precision(labels(val), clf.predict_proba(xv)[:, 1])
        rf.say(f"  C={C:g}: val AP {ap:.4f}  ({time.perf_counter() - t0:.0f} s so far)")
        if best is None or ap > best[0]:
            best = (ap, C, clf)
    minutes = (time.perf_counter() - t0) / 60
    _, C, clf = best
    test = read("test")
    t1 = time.perf_counter()
    clf.predict_proba(vectorise(test))
    score_everything("TF-IDF + logistic regression", lambda rows, s: clf.predict_proba(vectorise(rows))[:, 1],
                     {"kind": "tfidf", "how": f"word and character counts + logistic regression (C={C:g}, chosen on val)", "trained_on": len(train),
                      "train_minutes": round(minutes, 1), "articles_per_second": round(len(test) / (time.perf_counter() - t1))})


def e5(_args):
    """The first benchmark's multilingual-e5-small vectors (frozen), looked up by url, and its three classifiers refitted on this split."""
    import torch  # noqa: F401  (the classifiers below use it)
    folder = FIRST / "intfloat__multilingual-e5-small" / "emb"
    meta = json.loads((folder / "meta.json").read_text())
    data = {s: read(s) for s in SETS}
    vec = {}
    for s in SETS:
        old = rf.read_jsonl(s)                         # the first benchmark's set of the same name, in the order it was embedded
        if rf.urls_md5(old) != meta["sets"][s]["urls_md5"]:
            sys.exit(f"the first benchmark's {s} set no longer matches its saved vectors")
        where = {r["url"]: i for i, r in enumerate(old)}
        missing = [r["url"] for r in data[s] if r["url"] not in where]
        if missing:
            sys.exit(f"{len(missing):,} {s} articles have no saved vector (e.g. {missing[0]})")
        vec[s] = rf.head_features(np.load(folder / f"{s}.npy")[[where[r["url"]] for r in data[s]]], data[s])
    x = standardised(vec)
    dev = rf.device_of()
    yt, yv = labels(data["train"]), labels(data["val"])
    for kind in ("logreg", "mlp", "hgb"):
        t0 = time.perf_counter()
        fit = HEADS[kind](x["train"], yt, x["val"], yv, dev, HEAD_ARGS)
        score_everything(f"e5-small multilingual, frozen + {HEAD_LABEL[kind]}", lambda rows, s: fit(x[s]),
                         {"kind": "embedding+head", "how": f"frozen encoder (first benchmark's vectors) + {HEAD_LABEL[kind]}", "trained_on": len(yt),
                          "train_minutes": round((time.perf_counter() - t0) / 60, 2), "articles_per_second": meta["sets"]["test"]["articles_per_second"]})


def mmbert(args):
    """The first benchmark's fine-tuned mmBERT-small, as saved: trained on the same dates, before copies were removed."""
    folder = FIRST / "jhu-clsp__mmBERT-small" / "model"
    meta = json.loads((folder / "meta.json").read_text())
    first = json.loads((FIRST / "jhu-clsp__mmBERT-small" / "train.json").read_text())
    dev = rf.device_of()
    tok = rf.load_tokenizer(str(folder))
    model = rf.classifier(str(folder), False).to(dev)
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else 0
    max_len = meta.get("max_len", args.max_len)
    score_everything("mmBERT-small, fine-tuned", lambda rows, s: rf.predict(model, rf.encode(tok, rows, max_len), pad_id, dev, batch=256),
                     {"kind": "fine-tuned", "how": "whole encoder fine-tuned in the first benchmark (same dates, copies not removed)", "params_m": first["params_m"],
                      "trained_on": first["trained_on"], "train_minutes": first["train_minutes"], "articles_per_second": first["articles_per_second"]})


# ---- 6. what running a model in GitHub Actions would cost -------------------------------------------

def cpu(args):
    """Each saved model scoring --n test articles on the CPU with --threads threads (a free GitHub Actions runner has 4),
    tokenising included, and its size on disk. Models whose library is missing in this environment are skipped, so run it
    in new_env (fastText, the MiniLMs) and in the gliner venv (mmBERT, GLiClass)."""
    import torch
    torch.set_num_threads(args.threads)
    dev = torch.device("cpu")
    rows = read("test")
    random.Random(args.seed).shuffle(rows)
    rows = rows[:args.n]

    def size_mb(path):
        return round(sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file()) / 1e6) if Path(path).is_dir() else round(Path(path).stat().st_size / 1e6)

    def timed(name, path, score):
        score(rows[:32])                               # warm-up: first calls are slow
        t0 = time.perf_counter()
        score(rows)
        speed = round(len(rows) / (time.perf_counter() - t0))
        res_path = DATA / "results" / f"{rf.slug(name)}.json"
        if not res_path.exists():
            print(f"{name}: no results file, so nothing recorded")
            return
        r = json.loads(res_path.read_text())
        r.update({"cpu_threads": args.threads, "cpu_articles_per_second": speed, "size_mb": size_mb(path)})
        res_path.write_text(json.dumps(r, indent=1), encoding="utf-8")
        print(f"{name}: {speed:,} articles/s on {args.threads} CPU threads; {size_mb(path):,} MB on disk", flush=True)

    def mean_pooled(enc, head, tok, max_len):
        def score(batch_rows):
            ids = rf.encode(tok, batch_rows, max_len)
            order, out = np.argsort([len(t) for t in ids]), np.zeros(len(ids))
            with torch.no_grad():
                for i in range(0, len(ids), 32):
                    idx = order[i:i + 32]
                    x, m = rf.pad([ids[j] for j in idx], tok.pad_token_id or 0, dev)
                    h = enc(input_ids=x, attention_mask=m).last_hidden_state
                    out[idx] = torch.sigmoid(head((h * m.unsqueeze(-1)).sum(1) / m.sum(1, keepdim=True)).squeeze(-1)).numpy()
            return out
        return score

    models = DATA / "models"
    if (models / "fasttext.bin").exists():
        try:
            import fasttext
            ft = fasttext.load_model(str(models / "fasttext.bin"))
            timed("fastText, tuned on val", models / "fasttext.bin", lambda b: ft.predict([ft_tokens(r["text"]) for r in b], k=-1))
        except ImportError:
            print("fastText: not installed in this environment, skipped")
    for folder in sorted(p for p in models.iterdir() if p.is_dir()):
        meta = json.loads((folder / "meta.json").read_text())
        try:
            if (folder / "head.pt").exists():                  # an encoder fine-tuned by `finetune`
                from transformers import AutoModel, AutoTokenizer
                enc = AutoModel.from_pretrained(folder).eval()
                head = torch.nn.Linear(enc.config.hidden_size, 1)
                head.load_state_dict(torch.load(folder / "head.pt", map_location="cpu"))
                timed(f"{short(meta['base'])}, fine-tuned", folder, mean_pooled(enc, head, AutoTokenizer.from_pretrained(folder), meta["max_len"]))
            else:                                               # GLiClass fine-tuned by `finetune-gliclass`, as it would be deployed
                from gliclass import GLiClassModel, ZeroShotClassificationPipeline
                from transformers import AutoTokenizer
                pipe = ZeroShotClassificationPipeline(GLiClassModel.from_pretrained(folder), AutoTokenizer.from_pretrained(folder),
                                                      classification_type="multi-label", device="cpu", progress_bar=False)
                timed(f"{short(meta['base'])}, fine-tuned", folder, lambda b: pipe([r["text"] for r in b], meta["labels"], threshold=0.0, batch_size=32))
        except Exception as e:                                  # an architecture this environment's transformers cannot load, or a missing library
            print(f"{folder.name}: skipped here ({type(e).__name__}: {str(e)[:120]})")
    first = FIRST / "jhu-clsp__mmBERT-small" / "model"
    try:
        model = rf.classifier(str(first), False).eval()
        tok = rf.load_tokenizer(str(first))
        timed("mmBERT-small, fine-tuned", first, lambda b: rf.predict(model, rf.encode(tok, b, 192), tok.pad_token_id or 0, dev, batch=32))
    except Exception as e:
        print(f"mmBERT-small: skipped here ({type(e).__name__}: {str(e)[:120]})")


# ---- 7. the table ------------------------------------------------------------------------------

def report(_args):
    ds = json.loads((DATA / "dataset.json").read_text())
    results = [json.loads(p.read_text()) for p in sorted((DATA / "results").glob("*.json"))]
    if not results:
        sys.exit("nothing scored yet")
    results.sort(key=lambda r: -r["test"]["all"]["ap"])

    def f(v, d=2):
        return "-" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.{d}f}"

    def get(r, split, lang, *keys):
        try:
            v = r[split][lang]
            for k in keys:
                v = v[k]
            return v
        except (KeyError, TypeError):
            return None

    lines = ["# Relevance classifiers on one split", "",
             f"Labels: the LLM's verdicts (LLM_Relevance) in data/relevance/test_for_relevance.csv. {ds['read']:,} articles read; "
             f"{ds['excel_damage_repaired']:,} with Excel damage repaired from the untouched copy; {ds['copies_removed']:,} copies of a story removed; "
             f"{ds['conflicting_copies_dropped']:,} dropped because the LLM labelled copies of one story differently; "
             f"{ds['july_to_september_2026_left_out']:,} from July to September 2026 left out (they overlap the live set).", "",
             "| Set | dates | articles | relevant | share | English | relevant | Chinese | relevant |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, e in ds["sets"].items():
        lines.append(f"| {name} | {e['from'] + ' to ' + e['to'] if e['from'] else '-'} | {e['articles']:,} | {e['relevant']:,} | {e['relevant'] / max(e['articles'], 1):.1%} | "
                     f"{e['english']:,} | {e['english_relevant']:,} | {e['chinese']:,} | {e['chinese_relevant']:,} |")
    share = ds["sets"]["test"]["relevant"] / ds["sets"]["test"]["articles"]
    lines += ["", "F1, precision and recall are at the threshold that maximises F1 on val, applied unchanged to every set. "
              "Train F1 well above val F1 means the model memorised its training articles.", "",
              "| Model | how it learned | train F1 | val F1 | test F1 | test precision | test recall | test AUC | test AP | test precision at 95% recall | "
              "test share passed at 95% recall | test F1 English | test F1 Chinese | F1 vs Gemini (live) | F1 vs people (69) | minutes to train | "
              "articles/s as run | articles/s on 4 CPU threads | size (MB) |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        how = r["how"] + (f" ({r['test']['all']['n']:,} test articles)" if r["test"]["all"]["n"] != ds["sets"]["test"]["articles"] else "")
        lines.append(f"| {r['model']} | {how} | {f(get(r, 'train', 'all', 'f1_best', 'f1'))} | {f(get(r, 'val', 'all', 'f1_best', 'f1'))} | "
                     f"{f(get(r, 'test', 'all', 'f1_best', 'f1'))} | {f(get(r, 'test', 'all', 'f1_best', 'precision'))} | {f(get(r, 'test', 'all', 'f1_best', 'recall'))} | "
                     f"{f(get(r, 'test', 'all', 'auc'), 3)} | {f(get(r, 'test', 'all', 'ap'), 3)} | {f(get(r, 'test', 'all', 'recall_95', 'precision'))} | "
                     f"{f(get(r, 'test', 'all', 'recall_95', 'flagged'))} | "
                     f"{f(get(r, 'test', 'en', 'f1_best', 'f1'))} | {f(get(r, 'test', 'zh', 'f1_best', 'f1'))} | {f(get(r, 'live', 'all', 'f1_best', 'f1'))} | "
                     f"{f(get(r, 'human', 'all', 'f1_best', 'f1'))} | {r.get('train_minutes', '-')} | {r.get('articles_per_second') or '-'} | "
                     f"{r.get('cpu_articles_per_second') or '-'} | {r.get('size_mb') or '-'} |")
    lines.append(f"| flag every article | - | - | - | {2 * share / (1 + share):.2f} | {share:.2f} | 1.00 | 0.500 | {share:.3f} | {share:.2f} | 1.00 | - | - | - | - | - | - | - | - |")
    text = "\n".join(lines) + "\n"
    (DATA / "report.md").write_text(text, encoding="utf-8")
    print(text)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stage", choices=["dataset", "fasttext", "embed", "heads", "finetune", "gliclass", "finetune-gliclass", "tfidf", "e5", "mmbert", "cpu", "report"])
    p.add_argument("model", nargs="?", help="for embed, heads, finetune, gliclass: a Hugging Face model id")
    p.add_argument("--heads", default="logreg", help="heads: any of logreg, mlp, hgb, xgb (XGBoost, in link_env)")
    p.add_argument("--asked", choices=list(ASKED), default="described", help="gliclass: how the question is put")
    p.add_argument("--prompt", action="store_true", help="gliclass: give it our relevance prompt, shortened, as the task description")
    p.add_argument("--examples", type=int, default=0, help="gliclass: this many training articles as in-context examples (half relevant)")
    p.add_argument("--trials", type=int, default=20, help="fasttext: settings tried after the defaults")
    p.add_argument("--max-len", type=int, default=192)
    p.add_argument("--batch", type=int, default=32)
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--lr", type=float, default=None, help="finetune: default 3e-5 for a model of 200M parameters or more, 5e-5 otherwise")
    p.add_argument("--patience", type=int, default=3, help="finetune: stop after this many checks on val without improvement")
    p.add_argument("--min-delta", type=float, default=0.0005)
    p.add_argument("--threads", type=int, default=4, help="cpu: CPU threads (a free GitHub Actions runner has 4)")
    p.add_argument("--n", type=int, default=1000, help="cpu: test articles timed")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    if args.stage in ("embed", "heads", "finetune", "gliclass", "finetune-gliclass") and not args.model:
        p.error("this stage needs a model id")
    {"dataset": dataset, "fasttext": fasttext_stage, "embed": embed, "heads": heads, "finetune": finetune, "gliclass": gliclass, "finetune-gliclass": finetune_gliclass, "tfidf": tfidf,
     "e5": e5, "mmbert": mmbert, "cpu": cpu, "report": report}[args.stage](args)


if __name__ == "__main__":
    main()
