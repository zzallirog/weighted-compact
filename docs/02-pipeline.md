# 02 — Eight black boxes

The pipeline is eight modules wired in order: raw session JSONLs in,
fidelity-scored compacted context out. Each module is a file under
`weighted_compact/` with a black-box contract — input artefact, output
artefact, entry point, and the dependencies it loads. Modules are
independently replaceable: swap one without touching the others as long
as the contract holds. Replaceability is what makes the substrate
Goodhart-resistant — no single signal source is structurally privileged.

Each box below opens with a contract block (file / input / output /
maturity), followed by prose on how it opens. Order is pipeline order;
Box 4 (`misstep_score`) is optional and skipped if the dependency is
missing, with the importance mixture re-weighting the remaining signals
automatically.

Maturity vocabulary used throughout:

```text
  stable      runs in production, contract locked, schema versioned
  optional    runs only if an external dependency is present
  scaffold    runs and returns correct output; downstream consumer not built yet
  MVP         runs end-to-end; numbers still accumulating baseline
```

---

## Box 1 — extract_pairs

```text
  file       weighted_compact/extract_pairs.py
  input      ~/.claude/projects/  (+ ~/.claude-work/projects/ if present)
  output     pairs.jsonl  —  one record per (premise, correction) pair
  maturity   stable
```

Output schema:

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

**How it opens.** Walks JSONL session files; extracts consecutive
(human-turn, assistant-turn) pairs. Inline markers in the correction text
(`(mark)`, `(подумать)`, `(маркер)`, etc.) are detected by regex in
`MARKER_PATTERNS` and stored in the `marker` field for the labeling queue.

**Maturity.** Schema changes between alpha releases are possible but the
extraction logic itself has been running since Phase 1.

---

## Box 2 — feature_extract

```text
  file       weighted_compact/feature_extract.py
  input      pairs.jsonl
  output     features.npz   shape (N, 3, 384)
  maturity   stable
```

For each pair, three e5-multilingual-small embeddings: the premise
window, the correction window, and a context window centered on the pair.

**How it opens.** `SentenceTransformer('intfloat/multilingual-e5-small')`
with `passage:` / `query:` prefixes per the e5 convention. The 3-vector
window is the choice point for importance scoring: premise and correction
are scored separately; context is used for topic segmentation.

**Maturity.** Model is pinned; re-embedding is only needed when new pairs
arrive or the model is swapped.

---

## Box 3 — density_features

```text
  file       weighted_compact/density_features.py
  input      pairs.jsonl
  output     features_density.npz   shape (M, 16)
  maturity   stable
```

Sixteen density signals per pair, covering: name-like tokens, numeric
literals, quoted strings, path-like strings, code spans, and several
entropy variants.

**How it opens.** Regex-based extraction with no model dependency. Fast
enough to re-run on every bootstrap. The 16-feature vector is averaged
to produce the scalar density signal that feeds the importance mixture.

**Maturity.** The 16 features are heuristic; the set is not expected to
grow significantly.

---

## Box 4 — misstep_score

```text
  file       weighted_compact/misstep_score.py
  input      features.npz  +  external misstep predictor (see below)
  output     features_misstep.npz   shape (N,)   —   P(stumble) per pair
  maturity   optional
```

**How it opens.** Calls the misstep predictor if installed. Misstep is a
separate per-user model — logistic regression on stumble events trained on
the user's own session corpus — that returns `P(stumble)` for each user
turn from its embedding. It is not yet published as a public repo; the
install path will land in `docs/install.md` when it ships. If misstep is
not present, this box is skipped and the importance mixture re-weights the
remaining signals automatically.

The hypothesis: a pair is load-bearing if the user stopped stumbling at
that correction. `misstep_score = 1 - P(stumble)`, giving high scores to
pairs where the correction resolved a stumble pattern.

**Maturity.** Functional but optional. AUC 0.665 on the maintainer's
substrate as of the `v0.2.0-beta.1` checkpoint. On a fresh install with
no prior sessions, this signal is absent until the misstep predictor has
enough data.

---

## Box 5 — span_features

```text
  file       weighted_compact/span_features.py
  input      inline_annotations.jsonl
  output     features_spans.npz   char-fraction matrix per tier (K/M/S/X)
  maturity   stable
```

**How it opens.** Reads char-range tombstones from `inline_annotations.jsonl`
(written by the labeler when you drag-select text). Converts ranges to
fractions of the turn length. Most pairs have no annotations; the matrix is
sparse and that is expected.

**Maturity.** The four-tier contract (KEEP / MAYBE / SKIP / THINK) is locked.

---

## Box 6 — topic_segments

```text
  file       weighted_compact/topic_segments.py
  input      features.npz  (uses the context-window embeddings)
  output     topic_segments.npz   per-pair topic_id integers
  maturity   stable
```

**How it opens.** Sliding-window cosine cohesion check — same idea as
TextTiling applied to e5 vectors instead of TF-IDF. Detects topic boundaries
from geometry alone; no classifier, nothing to train.

**Maturity.** The cohesion threshold is a single tunable parameter.

---

## Box 7 — importance.compose

```text
  file       weighted_compact/importance.py
  input      all features_*.npz  +  labels.jsonl
  output     importance.npz   one float per pair
  maturity   stable  (weights tunable, formula locked)
```

The composed score:

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

**How it opens.** Weighted sum of six signals (see
[`docs/importance-mixture.md`](importance-mixture.md) for the full formula
and the ablation data). Weights are heuristic defaults; adjust in
`importance.py:WEIGHTS` and re-run. The reconstruction-QA loop tells you
whether the adjustment helped.

**Maturity.** The formula is stable. The weights are tunable and expected
to differ per user.

---

## Box 8 — recon_qa

```text
  package    weighted_compact/recon_qa/
  layout     5 sub-modules — context → generator → judge → gate → fidelity
```

Each sub-module carries its own black-box docstring at the top of the
file. Sub-module contracts below.

### recon_qa/context.py

```text
  input      pair_idx  +  ranker scores  +  k_drop  +  topic_decay
  output     markdown string — compacted context with the source pair removed
  maturity   stable
```

**How it opens.** Loads `pairs.jsonl`, `importance.npz`, `features_density.npz`,
and `topic_segments.npz`. Applies the importance-times-decay ranking and
assembles a markdown context up to the budget. This is what gets passed to
the LLM for reconstruction.

### recon_qa/generator.py

```text
  input      source pair dict  +  n  +  optional focus highlight  +
             optional prior candidate list and mode
  output     list of {q, a_truth} dicts
  maturity   stable
```

**How it opens.** Calls Ollama with the source pair (default reconstruction
model: `qwen2.5:7b`). The generation prompt applies a two-axis quality bar:
specificity (question should be answerable from this pair and not easily
guessed without it) and answerability (the ground-truth answer must be
extractable from the correction). Multi-iter modes (`complement` / `refine`
/ `deepen`) extend a prior candidate list without paraphrasing.

### recon_qa/judge.py

```text
  input      question, a_truth, predicted, optional source_pair
  output     {verdict: 'yes'|'no'|'other', reasoning, model}
  maturity   stable
```

**How it opens.** `llm_judge` calls Ollama with the judge model (default
`gemma3:4b` — Gemma family vs Qwen reconstruction model `qwen2.5:7b`, to
limit shared bias from same-family agreement). `score` is a cheap
case-insensitive substring fallback — ~30% false-negative on paraphrase per
its own docstring, used as debug not primary. If `source_pair` is provided,
it gets appended to the judge prompt so the verdict can verify against
actual source instead of comparing two free-form strings.

`iter_chain_metrics` is separate telemetry over a generation chain: it
embeds candidate sets via e5 and returns the mean-vector cosine between
the new and prior step, plus an `in_range` boolean checked against
`ITER_MODE_RANGES`:

```text
  complement   expected cosine 0.45 – 0.78
  refine       expected cosine 0.78 – 0.93
  deepen       expected cosine 0.60 – 0.85
```

The e5 model is lazy-loaded (~120 MB) only when `iter_chain_metrics`
fires; the judge path itself does not pull it in.

Tri-value verdict policy: `'other'` is better than a guessed `'yes'` under
uncertainty. See [`docs/03-quality-driver.md`](03-quality-driver.md) §5.2
for why.

### recon_qa/gate.py

```text
  input      easy_k, hard_k, ranker, signal
  output     dict with four buckets — trivial, impossible, informative, inverted
  maturity   scaffold
```

**How it opens.** Runs `fidelity.run_eval` twice at different `k_drop`
values. Pairs that pass easy compaction but fail hard compaction are
`informative` — the most useful for calibrating the mixture. Pairs that
always fail or always pass carry less signal. Based on EvoEnv-style
difficulty filtering (arXiv:2605.14392).

**Maturity.** The difficulty bucketing logic works; the downstream use
(routing informative pairs into the labeling queue) is planned for W3.

### recon_qa/fidelity.py

```text
  input      k_drop, ranker, topic_decay
  output     list of per-QA-entry result dicts:
             {predicted, substring_pass, judge, context_chars}
  maturity   MVP — accumulating baseline
```

**How it opens.** Iterates over `load_qa_set()`, calls
`context.build_compacted_context` → `generator.ask_ollama` →
`judge.score` + `judge.llm_judge`. The orchestrator. Does not persist
results; the caller owns the journal.

---

## Maturity at a glance

| Module | Maturity |
|---|---|
| `extract_pairs` | stable |
| `feature_extract` | stable |
| `density_features` | stable |
| `topic_segments` | stable |
| `span_features` | stable |
| `importance.compose` | stable (weights tunable) |
| `misstep_score` | optional |
| `recon_qa/context` | stable |
| `recon_qa/generator` | stable |
| `recon_qa/judge` | stable |
| `recon_qa/fidelity` | MVP — accumulating baseline |
| `recon_qa/gate` | scaffold |

`scaffold` means the module runs and produces correct output, but the
downstream workflow that consumes its output has not been built yet.
`MVP` means the loop runs end-to-end but the numbers it produces are
still calibrating against the per-install ~50-sample baseline.

---

## See also

- [`docs/01-substrate.md`](01-substrate.md) — what lives in the substrate directory
- [`docs/architecture.md`](architecture.md) — layer diagram with file arrows
- [`docs/importance-mixture.md`](importance-mixture.md) — the compose function in detail + ablation data
- [`docs/reconstruction-qa.md`](reconstruction-qa.md) — the eval loop, failure modes, cross-model anti-bias
- [`docs/03-quality-driver.md`](03-quality-driver.md) — why fidelity is the right metric
