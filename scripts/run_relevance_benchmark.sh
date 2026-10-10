#!/usr/bin/env bash
# Everything for the relevance benchmark, in order, with a log per step. A failed download or `before` step stops the run;
# a failed fine-tune does not stop the other model. Ctrl+C stops after the step in hand has saved what it has.
#
#   scripts/run_relevance_benchmark.sh clean    # if a run looks stuck: stop stale runs and clear half-finished downloads
#   scripts/run_relevance_benchmark.sh before   # mmBERT-small before fine-tuning, then the table (a few minutes)
#   scripts/run_relevance_benchmark.sh train    # fine-tune mmBERT-small, then the full table
#   scripts/run_relevance_benchmark.sh all      # both of the above
#   scripts/run_relevance_benchmark.sh train-base   # later, if wanted: fine-tune mmBERT-base too (its "before" is already saved)
#   scripts/run_relevance_benchmark.sh cheap    # no fine-tuning: word counts, and a small embedding model (EMB=...) with cheap classifiers
#   scripts/run_relevance_benchmark.sh quick-cheap  # the same on a small sample, to see it work first
#   scripts/run_relevance_benchmark.sh quick    # a few-minute trial of the whole path on a small sample (saves nothing as a result)
#
# The first run downloads each model (about 0.6 GB for small, 1.2 GB for base), with a bar, before anything else.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONUNBUFFERED=1
PY="${PY:-$HOME/.venvs/gliner/bin/python}"
S="$PY scripts/relevance_finetune.py"
HUB="$HOME/.cache/huggingface/hub"
mkdir -p data/finetune/logs
SMALL=jhu-clsp/mmBERT-small
BASE=jhu-clsp/mmBERT-base

# Ctrl+Z only pauses a run, and a paused run ignores the polite stop that pkill sends but still holds the model
# download. So stale runs, their wrapper scripts and their logs are killed outright.
# Everything of ours in another process group (this run, its subshells and its children all share one).
stale() {
  local mine; mine=$(ps -o pgid= -p $$ | tr -d ' ')
  ps -eo pid=,pgid=,cmd= | awk -v mine="$mine" '$2 != mine && /relevance_finetune\.py|run_relevance_benchmark\.sh|tee .*data\/finetune\/logs/ { print $1 }'
}

if [ "${1:-all}" = clean ]; then
  pids=$(stale)
  if [ -n "$pids" ]; then
    echo "stopping: $(echo $pids | tr '\n' ' ')"
    [ -n "${DRY:-}" ] || { kill -9 $pids 2>/dev/null || true; sleep 1; }
  else
    echo "no stale runs"
  fi
  left=$(stale)
  [ -n "${DRY:-}" ] || { [ -z "$left" ] && echo "all stopped" || echo "still alive: $left"; }
  rm -rf "$HUB"/.locks/models--jhu-clsp--mmBERT-*
  find "$HUB" -path "*models--jhu-clsp--mmBERT-*" -name "*.incomplete" -delete 2>/dev/null || true
  echo "cleaned; now run:  scripts/run_relevance_benchmark.sh before"
  exit 0
fi

# Two runs share one model download and wait on each other for ever: both look stuck, and neither prints anything.
if [ -n "$(stale)" ]; then
  echo "Another run is still going (process $(stale | tr '\n' ' ')), running or paused. Stop it first with:"
  echo "    scripts/run_relevance_benchmark.sh clean"
  echo "(Stop a run with Ctrl+C. Ctrl+Z only pauses it, and a paused run still holds the model download.)"
  exit 1
fi

# Ctrl+C reaches the script, python and tee together. tee -i ignores it, so python can still print and save what it has; the script then
# stops after the step instead of going on to the next one.
interrupted=0
trap 'interrupted=1' INT
step() {
  local name="$1"; shift
  echo; echo "=== $name"
  "$@" 2>&1 | tee -i "data/finetune/logs/$name.log" || return $?
  [ "$interrupted" = 0 ] || { echo "stopped by Ctrl+C after $name"; exit 130; }
}
failed=()
try() { step "$@" || { failed+=("$1"); [ "$interrupted" = 0 ] || exit 130; }; }

[ -s data/finetune/train.jsonl ] || step splits $S splits

case "${1:-all}" in
  quick)
    step download-small $S download $SMALL
    step quick-train $S train $SMALL --limit-train 20000 --limit-eval 5000 --epochs 1 ;;
  before | all)
    step download-small $S download $SMALL
    step before-small $S before $SMALL
    step report-before $S report-before
    [ "${1:-all}" = all ] || exit 0 ;&
  train)
    try train-small $S train $SMALL
    step report $S report
    if [ "${#failed[@]}" -gt 0 ]; then echo; echo "these steps failed (see data/finetune/logs/): ${failed[*]}"; exit 1; fi ;;
  train-base)
    step download-base $S download $BASE
    [ -s data/finetune/jhu-clsp__mmBERT-base/before.json ] || step before-base $S before $BASE
    try train-base $S train $BASE
    step report $S report
    if [ "${#failed[@]}" -gt 0 ]; then echo; echo "these steps failed (see data/finetune/logs/): ${failed[*]}"; exit 1; fi ;;
  quick-cheap)
    EMB="${EMB:-intfloat/multilingual-e5-small}"
    step download-emb $S download $EMB
    step quick-tfidf $S tfidf --limit-train 20000 --limit-eval 5000
    step quick-embed $S embed $EMB --limit-train 20000 --limit-eval 5000
    step quick-head $S head $EMB --limit-train 20000 --limit-eval 5000 ;;
  cheap)
    EMB="${EMB:-intfloat/multilingual-e5-small}"
    step download-emb $S download $EMB
    step tfidf $S tfidf
    step embed-${EMB##*/} $S embed $EMB
    step heads-${EMB##*/} $S head $EMB
    step report $S report ;;
  *) echo "usage: $0 [clean|before|train|train-base|cheap|quick-cheap|all|quick]"; exit 2 ;;
esac
