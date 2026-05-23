#!/usr/bin/env bash
#
# bench_vs_claude_mem.sh — head-to-head bench, weighted-compact vs claude-mem.
#
# Picks 30 source-pair-idxs from the local recon_qa_set.jsonl with a fixed
# seed, drives both tools on the same Qs, scores both with the same gemma3:4b
# judge, writes per-method counts to bench-vs-claude-mem-results.json.
#
# What this script does NOT do:
#   - install either tool (run prerequisites yourself)
#   - guarantee fairness across asymmetric ingestion paths (see
#     docs/bench-vs-claude-mem.md §Asymmetry)
#   - tune anything; defaults match what the public docs document
#
# Run with: bash scripts/bench_vs_claude_mem.sh
# Override seed: BENCH_SEED=7 bash scripts/bench_vs_claude_mem.sh
# Override sample size: BENCH_N=10 bash scripts/bench_vs_claude_mem.sh
#

set -euo pipefail

# ---- config -----------------------------------------------------------------

BENCH_SEED="${BENCH_SEED:-42}"
BENCH_N="${BENCH_N:-30}"
BENCH_K_DROP="${BENCH_K_DROP:-0.5}"
CLAUDE_MEM_PORT="${CLAUDE_MEM_PORT:-37777}"
CLAUDE_MEM_HOST="${CLAUDE_MEM_HOST:-127.0.0.1}"
OLLAMA_URL="${WEIGHTED_COMPACT_OLLAMA_URL:-http://localhost:11434/api/generate}"
SUBSTRATE_DIR="${WEIGHTED_COMPACT_DATA:-$HOME/work/weighted-compact}"
PAIRS_FILE="$SUBSTRATE_DIR/pairs.jsonl"
QA_FILE="$SUBSTRATE_DIR/recon_qa_set.jsonl"
OUT_FILE="${BENCH_OUT:-bench-vs-claude-mem-results.json}"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---- preflight --------------------------------------------------------------

die() { printf 'error: %s\n' "$*" >&2; exit 1; }

step() { printf '\n=== %s ===\n' "$*" >&2; }

step "preflight"

# claude-mem CLI present?
if ! command -v claude-mem >/dev/null 2>&1; then
    if ! command -v npx >/dev/null 2>&1; then
        die "neither claude-mem nor npx found. install: https://github.com/thedotmack/claude-mem"
    fi
    if ! npx --no-install claude-mem --version >/dev/null 2>&1; then
        cat >&2 <<'EOF'
claude-mem is not installed.
Install with: npx claude-mem install
Then start its worker: npx claude-mem start
Then re-run this script.
EOF
        exit 1
    fi
fi

# claude-mem worker running on expected port?
if ! curl -fsS --max-time 3 "http://${CLAUDE_MEM_HOST}:${CLAUDE_MEM_PORT}/api/health" >/dev/null 2>&1; then
    cat >&2 <<EOF
claude-mem worker is not reachable at http://${CLAUDE_MEM_HOST}:${CLAUDE_MEM_PORT}/api/health
Start it with: npx claude-mem start
Or set CLAUDE_MEM_HOST / CLAUDE_MEM_PORT if it's bound elsewhere.
EOF
    exit 1
fi

# substrate present?
if [ ! -f "$PAIRS_FILE" ]; then
    cat >&2 <<EOF
weighted-compact substrate not found at: $PAIRS_FILE
Build it first:
  weighted-compact bootstrap            # extract pairs from ~/.claude/projects/
  weighted-compact build                # features + importance
  weighted-compact recon build          # generate recon_qa_set.jsonl
Or override path: WEIGHTED_COMPACT_DATA=/path/to/substrate bash $0
EOF
    exit 1
fi
if [ ! -f "$QA_FILE" ]; then
    die "recon_qa_set.jsonl missing at $QA_FILE — run \`weighted-compact recon build\` first"
fi

# ollama reachable + required models?
if ! curl -fsS --max-time 3 "${OLLAMA_URL%/api/generate}/api/tags" >/dev/null 2>&1; then
    die "ollama not reachable at ${OLLAMA_URL%/api/generate} — start with: systemctl --user start ollama"
fi

models_json="$(curl -fsS "${OLLAMA_URL%/api/generate}/api/tags")"
for m in "gemma3:4b" "qwen2.5:7b"; do
    if ! printf '%s' "$models_json" | grep -q "\"$m\""; then
        die "ollama model '$m' not pulled — run: ollama pull $m"
    fi
done

# python imports we depend on
if ! python3 -c "import weighted_compact.recon_qa.fidelity" >/dev/null 2>&1; then
    cat >&2 <<EOF
weighted_compact package not importable. Install from this repo with:
  cd "$REPO_DIR" && pip install -e .
EOF
    exit 1
fi

# ---- pick the sample --------------------------------------------------------

step "sampling $BENCH_N source_pair_idxs (seed=$BENCH_SEED)"

SAMPLE_FILE="$(mktemp -t bench_sample.XXXXXX.json)"
trap 'rm -f "$SAMPLE_FILE" "$SAMPLE_FILE.idxs"' EXIT

python3 - "$QA_FILE" "$BENCH_N" "$BENCH_SEED" "$SAMPLE_FILE" <<'PY'
import json, random, sys
qa_path, n_s, seed_s, out_path = sys.argv[1:]
n, seed = int(n_s), int(seed_s)
entries = []
with open(qa_path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
# Distinct source_pair_idx, sorted for determinism, then seeded sample.
distinct = sorted({e["source_pair_idx"] for e in entries})
if len(distinct) < n:
    sys.stderr.write(f"warning: only {len(distinct)} distinct idxs available, "
                     f"requested {n}; using all\n")
    n = len(distinct)
rng = random.Random(seed)
picked = sorted(rng.sample(distinct, n))
# Filter QA entries to only the picked idxs.
sampled = [e for e in entries if e["source_pair_idx"] in set(picked)]
with open(out_path, "w", encoding="utf-8") as f:
    json.dump({"picked_idxs": picked, "qa_entries": sampled}, f)
sys.stderr.write(f"picked {len(picked)} idxs, {len(sampled)} QA entries\n")
sys.stderr.write(f"idxs: {picked}\n")
PY

# ---- run the bench ----------------------------------------------------------

step "running bench (this will take a while — 5 methods x ~$BENCH_N entries each)"

BENCH_SEED="$BENCH_SEED" \
BENCH_N="$BENCH_N" \
BENCH_K_DROP="$BENCH_K_DROP" \
CLAUDE_MEM_HOST="$CLAUDE_MEM_HOST" \
CLAUDE_MEM_PORT="$CLAUDE_MEM_PORT" \
SAMPLE_FILE="$SAMPLE_FILE" \
OUT_FILE="$OUT_FILE" \
python3 - <<'PY'
"""Driver: runs all 5 methods on the same sampled QA set and writes
per-method results to OUT_FILE. Pure stdlib + weighted_compact +
requests (already a transitive dep)."""
import json, os, time, urllib.parse
import requests

from weighted_compact.recon_qa.context import (
    build_compacted_context, load_pairs, load_importance, load_baseline_recency,
)
from weighted_compact.recon_qa.generator import ask_ollama
from weighted_compact.recon_qa.judge import llm_judge, score
from weighted_compact.recon_qa._constants import JUDGE_MODEL
from weighted_compact.baselines.compact_simulator import build_qwen

SAMPLE_FILE = os.environ["SAMPLE_FILE"]
OUT_FILE = os.environ["OUT_FILE"]
K_DROP = float(os.environ.get("BENCH_K_DROP", "0.5"))
CM_HOST = os.environ["CLAUDE_MEM_HOST"]
CM_PORT = int(os.environ["CLAUDE_MEM_PORT"])
CM_BASE = f"http://{CM_HOST}:{CM_PORT}"

with open(SAMPLE_FILE) as f:
    sample = json.load(f)
qa_entries = sample["qa_entries"]

pairs = load_pairs()
pair_by_idx = {p["pair_idx"]: p for p in pairs}

# ---- weighted-compact static rankers (importance, recency) -----------------

def run_wc_static(ranker_name, scores_dict):
    out = []
    for e in qa_entries:
        t0 = time.time()
        ctx = build_compacted_context(
            e["source_pair_idx"], pairs, scores_dict, K_DROP,
            topic_decay=1.0, topic_map=None, query=e.get("q"),
        )
        build_secs = time.time() - t0
        if not ctx:
            out.append({
                "source_pair_idx": e["source_pair_idx"], "q": e["q"],
                "context_chars": 0, "build_secs": build_secs,
                "predicted": "<empty_context>", "judge": "no",
                "judge_reason": "empty context", "substring_pass": False,
            })
            continue
        pred = ask_ollama(ctx, e["q"])
        sp = pair_by_idx.get(e["source_pair_idx"])
        judge = llm_judge(e["q"], e["a_truth"], pred, source_pair=sp)
        out.append({
            "source_pair_idx": e["source_pair_idx"], "q": e["q"],
            "context_chars": len(ctx), "build_secs": build_secs,
            "predicted": pred,
            "judge": judge.get("verdict"),
            "judge_reason": judge.get("reasoning"),
            "substring_pass": score(pred, e["a_truth"]),
        })
    return out

# ---- /compact-analog (qwen2.5:7b full-history summary) ---------------------

def run_compact_qwen():
    summarizer = build_qwen()
    out = []
    for e in qa_entries:
        t0 = time.time()
        ctx = summarizer.summarize_excluding(e["source_pair_idx"], pairs,
                                              query=e.get("q"))
        build_secs = time.time() - t0
        if not ctx:
            out.append({"source_pair_idx": e["source_pair_idx"], "q": e["q"],
                        "context_chars": 0, "build_secs": build_secs,
                        "predicted": "<empty_context>", "judge": "no",
                        "judge_reason": "empty context",
                        "substring_pass": False})
            continue
        pred = ask_ollama(ctx, e["q"])
        sp = pair_by_idx.get(e["source_pair_idx"])
        judge = llm_judge(e["q"], e["a_truth"], pred, source_pair=sp)
        out.append({"source_pair_idx": e["source_pair_idx"], "q": e["q"],
                    "context_chars": len(ctx), "build_secs": build_secs,
                    "predicted": pred, "judge": judge.get("verdict"),
                    "judge_reason": judge.get("reasoning"),
                    "substring_pass": score(pred, e["a_truth"])})
    return out

# ---- claude-mem drivers (search-top-k and context-semantic) ----------------
#
# Asymmetry note (mirrored in docs/bench-vs-claude-mem.md):
# claude-mem has no public ingest-from-file API. It captures observations
# from live Claude Code hooks. This bench asks claude-mem to *retrieve*
# context for each question against its existing observation DB — i.e.
# whatever the user's worker has accumulated through normal use. That is
# the only public surface; treat the result as "what claude-mem returns
# when asked the same Q," not "what claude-mem would produce given the
# weighted-compact substrate."

def cm_search_topk(question, k=10, timeout=10):
    """GET /api/search/observations?query=...&limit=k — concat as markdown."""
    url = f"{CM_BASE}/api/search/observations"
    try:
        r = requests.get(url, params={"query": question, "limit": k},
                          timeout=timeout)
        data = r.json()
    except Exception as exc:
        return f"<claude_mem_error: {exc}>"
    obs = data.get("observations") or data.get("results") or []
    if not obs:
        return ""
    lines = ["## Retrieved observations (claude-mem search)\n"]
    for o in obs[:k]:
        title = o.get("title") or o.get("summary") or "Observation"
        narr  = o.get("narrative") or o.get("text") or ""
        lines.append(f"### {title}")
        if narr:
            lines.append(narr)
        lines.append("")
    return "\n".join(lines)

def cm_context_semantic(question, k=10, timeout=10):
    """POST /api/context/semantic — returns {context: str, count: int}.
    Requires query length >= 20; pad with a context phrase if too short."""
    url = f"{CM_BASE}/api/context/semantic"
    q = question
    if len(q) < 20:
        q = q + "  (context: weighted-compact bench question)"
    try:
        r = requests.post(url, json={"q": q, "limit": k}, timeout=timeout)
        data = r.json()
    except Exception as exc:
        return f"<claude_mem_error: {exc}>"
    return data.get("context", "") or ""

def run_claude_mem(driver_fn, name):
    out = []
    for e in qa_entries:
        t0 = time.time()
        ctx = driver_fn(e["q"])
        build_secs = time.time() - t0
        if not ctx or ctx.startswith("<claude_mem_error"):
            out.append({"source_pair_idx": e["source_pair_idx"], "q": e["q"],
                        "context_chars": len(ctx) if ctx else 0,
                        "build_secs": build_secs,
                        "predicted": "<empty_context>",
                        "judge": "no",
                        "judge_reason": ctx or "empty context",
                        "substring_pass": False,
                        "method": name})
            continue
        pred = ask_ollama(ctx, e["q"])
        sp = pair_by_idx.get(e["source_pair_idx"])
        judge = llm_judge(e["q"], e["a_truth"], pred, source_pair=sp)
        out.append({"source_pair_idx": e["source_pair_idx"], "q": e["q"],
                    "context_chars": len(ctx), "build_secs": build_secs,
                    "predicted": pred, "judge": judge.get("verdict"),
                    "judge_reason": judge.get("reasoning"),
                    "substring_pass": score(pred, e["a_truth"]),
                    "method": name})
    return out

# ---- run all methods --------------------------------------------------------

def summarize(rows):
    n = len(rows)
    yes = sum(1 for r in rows if r["judge"] == "yes")
    other = sum(1 for r in rows if r["judge"] == "other")
    chars = sum(r["context_chars"] for r in rows)
    build = sum(r["build_secs"] for r in rows)
    return {
        "n": n, "judge_yes": yes, "judge_other": other,
        "judge_yes_fraction": (yes / n) if n else 0.0,
        "mean_context_chars": (chars / n) if n else 0.0,
        "total_build_secs": build,
        "mean_build_secs": (build / n) if n else 0.0,
    }

methods = {}

print(f"[1/5] weighted-compact-importance ...")
methods["weighted-compact-importance"] = {
    "rows": run_wc_static("importance", load_importance()),
}
print(f"[2/5] weighted-compact-recency ...")
methods["weighted-compact-recency"] = {
    "rows": run_wc_static("recency", load_baseline_recency()),
}
print(f"[3/5] compact-qwen-analog (/compact full-history summary) ...")
methods["compact-qwen-analog"] = {"rows": run_compact_qwen()}
print(f"[4/5] claude-mem-search-topk ...")
methods["claude-mem-search-topk"] = {
    "rows": run_claude_mem(cm_search_topk, "claude-mem-search-topk"),
}
print(f"[5/5] claude-mem-context-semantic ...")
methods["claude-mem-context-semantic"] = {
    "rows": run_claude_mem(cm_context_semantic, "claude-mem-context-semantic"),
}

for name, m in methods.items():
    m["summary"] = summarize(m["rows"])

out_doc = {
    "config": {
        "seed": int(os.environ["BENCH_SEED"]),
        "n_pairs": int(os.environ["BENCH_N"]),
        "k_drop": K_DROP,
        "judge_model": JUDGE_MODEL,
        "claude_mem_base": CM_BASE,
    },
    "picked_idxs": sample["picked_idxs"],
    "methods": methods,
}
with open(OUT_FILE, "w") as f:
    json.dump(out_doc, f, indent=2, ensure_ascii=False)
print(f"\nwrote {OUT_FILE}")

# ---- print markdown summary ------------------------------------------------

print("\n## Bench results\n")
print("| method | n | judge_yes / n | mean_context_chars | mean_build_secs |")
print("|---|---|---|---|---|")
for name, m in methods.items():
    s = m["summary"]
    print(f"| {name} | {s['n']} | {s['judge_yes']}/{s['n']} "
          f"({s['judge_yes_fraction']:.1%}) | "
          f"{s['mean_context_chars']:.0f} | "
          f"{s['mean_build_secs']:.2f} |")
PY

step "done. results in $OUT_FILE"
