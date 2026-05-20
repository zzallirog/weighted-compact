# 02 — n black boxes

The pipeline is a sequence of modules. Each module is a defined black box:
known input, known output, the relevant file named explicitly. You can open
any box, read it, and replace it without touching the others.

This document walks through each box in pipeline order and notes which ones
are mature, which are scaffolded, and which are optional.

---

## Box 1 — extract_pairs

**File:** `weighted_compact/extract_pairs.py`

**In:** `~/.claude/projects/` (and `~/.claude-work/projects/` if present)

**Out:** `pairs.jsonl` — one record per (premise, correction) pair:
```json
{
  "pair_idx": 42,
  "premise_text": "...",
  "correction_text": "...",
  "session_id": "...",
  "turn_idx": 7,
  "marker": "(mark)"
}
```

**How it opens:** Walks JSONL session files; extracts consecutive
(human-turn, assistant-turn) pairs. Inline markers in the correction text
(`(mark)`, `(подумать)`, `(маркер)`, etc.) are detected by regex in
`MARKER_PATTERNS` and stored in the `marker` field for the labeling queue.

**Maturity:** Stable. Schema changes between alpha releases are possible
but the extraction logic itself has been running since Phase 1.

---

## Box 2 — feature_extract

**File:** `weighted_compact/feature_extract.py`

**In:** `pairs.jsonl`

**Out:** `features.npz` — shape `(N, 3, 384)` — for each pair, three
e5-multilingual-small embeddings: the premise window, the correction window,
and a context window centered on the pair.

**How it opens:** `SentenceTransformer('intfloat/multilingual-e5-small')`
with `passage:` / `query:` prefixes per the e5 convention. The 3-vector
window is the choice point for importance scoring: premise and correction
are scored separately; context is used for topic segmentation.

**Maturity:** Stable. Model is pinned; re-embedding is only needed when
new pairs arrive or the model is swapped.

---

## Box 3 — density_features

**File:** `weighted_compact/density_features.py`

**In:** `pairs.jsonl`

**Out:** `features_density.npz` — shape `(M, 16)` — 16 density signals
per pair, covering: name-like tokens, numeric literals, quoted strings,
path-like strings, code spans, and several entropy variants.

**How it opens:** Regex-based extraction with no model dependency. Fast
enough to re-run on every bootstrap. The 16-feature vector is averaged
to produce the scalar density signal that feeds the importance mixture.

**Maturity:** Stable. The 16 features are heuristic; the set is not
expected to grow significantly.

---

## Box 4 — misstep_score (optional)

**File:** `weighted_compact/misstep_score.py`

**In:** `features.npz`, misstep substrate (separate install)

**Out:** `features_misstep.npz` — shape `(N,)` — `P(stumble)` per pair

**How it opens:** Calls the [misstep](https://github.com/zzallirog/misstep)
predictor if installed. If misstep is not present, this box is skipped and
the importance mixture re-weights the remaining signals automatically.

The hypothesis: a pair is load-bearing if the user stopped stumbling at
that correction. `misstep_score = 1 - P(stumble)`, giving high scores to
pairs where the correction resolved a stumble pattern.

**Maturity:** Functional but optional. The misstep predictor is calibrated
on the user's corpus; AUC 0.665 on the maintainer's substrate as of
`v0.1.0-alpha.2`. On a fresh install with no prior sessions, this signal
is absent until the misstep predictor has enough data.

---

## Box 5 — span_features

**File:** `weighted_compact/span_features.py`

**In:** `inline_annotations.jsonl`

**Out:** `features_spans.npz` — char-fraction matrix: for each pair, the
fraction of characters covered by each tier (KEEP / MAYBE / SKIP / THINK).

**How it opens:** Reads char-range tombstones from `inline_annotations.jsonl`
(written by the labeler when you drag-select text). Converts ranges to
fractions of the turn length. Most pairs have no annotations; the matrix is
sparse and that is expected.

**Maturity:** Stable. The four-tier contract (K/M/S/X) is locked.

---

## Box 6 — topic_segments

**File:** `weighted_compact/topic_segments.py`

**In:** `features.npz` (uses the context-window embeddings)

**Out:** `topic_segments.npz` — per-session topic boundary map, per-pair
`topic_id` integers

**How it opens:** Sliding-window cosine cohesion check — same idea as
TextTiling applied to e5 vectors instead of TF-IDF. Detects topic boundaries
from geometry alone; no classifier, nothing to train.

**Maturity:** Stable. The cohesion threshold is a single tunable parameter.

---

## Box 7 — importance.compose

**File:** `weighted_compact/importance.py`

**In:** All `features_*.npz` + `labels.jsonl`

**Out:** `importance.npz` — one float per pair, the composed importance score

**How it opens:** Weighted sum of six signals (see
[`docs/importance-mixture.md`](importance-mixture.md) for the full formula
and the ablation data). Weights are heuristic defaults; adjust in
`importance.py:WEIGHTS` and re-run. The reconstruction-QA loop tells you
whether the adjustment helped.

```python
importance = (
    0.40 * misstep
  + 0.25 * density
  + 0.15 * label_keep
  + 0.20 * span_keep
  + 0.10 * span_maybe
  - 0.15 * span_skip
  + 0.05 * span_think
)
```

**Maturity:** The formula is stable. The weights are tunable and expected
to differ per user.

---

## Box 8 — recon_qa

**Package:** `weighted_compact/recon_qa/`

This box has five sub-modules. Each carries its own black-box docstring
at the top of the file.

### recon_qa/context.py

**In:** `pair_idx` + ranker scores + `k_drop` + `topic_decay`

**Out:** Markdown string — the compacted context with the source pair
removed and the remaining pairs ranked and truncated.

**How it opens:** Loads `pairs.jsonl`, `importance.npz`, `features_density.npz`,
and `topic_segments.npz`. Applies the importance-times-decay ranking and
assembles a markdown context up to the budget. This is what gets passed to
the LLM for reconstruction.

### recon_qa/generator.py

**In:** Source pair dict, `n`, optional focus highlight, optional prior
candidate list and mode

**Out:** List of `{q, a_truth}` dicts

**How it opens:** Calls Ollama with the source pair. The generation prompt
applies a two-axis quality bar: specificity (question should be answerable
from this pair and not easily guessed without it) and answerability (the
ground-truth answer must be extractable from the correction). Multi-iter
modes (`complement` / `refine` / `deepen`) extend a prior candidate list
without paraphrasing.

### recon_qa/judge.py

**In:** `question`, `a_truth`, `predicted`, optional `source_pair`

**Out:** `{verdict: 'yes'|'no'|'other', reasoning, model}`

**How it opens:** `llm_judge` calls Ollama with the judge model (gemma3:4b
by default — different family from the reconstruction model, to limit shared
bias). `score` is a cheap substring fallback. `iter_chain_metrics` is
separate telemetry that uses e5 embeddings to measure semantic drift between
iter steps; it only loads the model when called.

Tri-value verdict policy: `'other'` is better than a guessed `'yes'` under
uncertainty. See [`docs/03-quality-driver.md`](03-quality-driver.md) §5.2
for why.

### recon_qa/gate.py

**In:** `easy_k`, `hard_k`, `ranker`, `signal`

**Out:** Dict with four buckets: `trivial`, `impossible`, `informative`,
`inverted`

**How it opens:** Runs `fidelity.run_eval` twice at different `k_drop`
values. Pairs that pass easy compaction but fail hard compaction are
`informative` — the most useful for calibrating the mixture. Pairs that
always fail or always pass carry less signal. Based on EvoEnv-style
difficulty filtering (arXiv:2605.14392).

**Maturity:** Scaffold. The difficulty bucketing logic works; the downstream
use (routing informative pairs into the labeling queue) is planned for W3.

### recon_qa/fidelity.py

**In:** `k_drop`, `ranker`, `topic_decay`

**Out:** List of result dicts per QA entry — `{predicted, substring_pass, judge, context_chars}` merged with the entry

**How it opens:** Iterates over `load_qa_set()`, calls
`context.build_compacted_context` → `generator.ask_ollama` →
`judge.score` + `judge.llm_judge`. The orchestrator. Does not persist
results; the caller owns the journal.

---

## Which boxes are mature, which are not

| Module | Maturity |
|---|---|
| `extract_pairs` | Stable |
| `feature_extract` | Stable |
| `density_features` | Stable |
| `topic_segments` | Stable |
| `span_features` | Stable |
| `importance.compose` | Stable (weights tunable) |
| `misstep_score` | Functional, optional |
| `recon_qa/context` | Stable |
| `recon_qa/generator` | Stable |
| `recon_qa/judge` | Stable |
| `recon_qa/fidelity` | MVP — accumulating baseline |
| `recon_qa/gate` | Scaffold |

"Scaffold" means the module runs and produces correct output, but the
downstream workflow that consumes its output has not been built yet.

---

## See also

- [`docs/01-substrate.md`](01-substrate.md) — what lives in the substrate directory
- [`docs/architecture.md`](architecture.md) — layer diagram with file arrows
- [`docs/importance-mixture.md`](importance-mixture.md) — the compose function in detail
- [`docs/reconstruction-qa.md`](reconstruction-qa.md) — the eval loop, failure modes, cross-model anti-bias
- [`docs/03-quality-driver.md`](03-quality-driver.md) — why fidelity is the right metric
