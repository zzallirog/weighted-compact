# Importance mixture

The continuous importance score for each pair is a weighted sum of six
independent signals, clipped to `[0, 1]`. Each signal measures something
different about the underlying pair, so no single source can produce a
Goodhart artifact by itself.

## The formula

```
importance(i) =
    0.40 × misstep_score(i)        # vector-based backbone
  + 0.25 × density_score(i)        # content-bearing proxy
  + 0.15 × label_keep(i)           # human signal (noisy)
  + 0.20 × span_keep_frac(i)       # explicit "keep this span"
  + 0.10 × span_maybe_frac(i)      # explicit "maybe useful"
  − 0.15 × span_skip_frac(i)       # explicit "don't keep this"
  + 0.05 × span_think_frac(i)      # flag for re-examination
```

All terms are in `[0, 1]` before weighting, except `span_skip_frac` which
enters with a negative coefficient and is subtracted.

## Each signal in detail

### `misstep_score` — vector-based backbone (weight 0.40)

A logistic regression on stumble events from a per-user **misstep**
predictor (see [github.com/zzallirog/misstep](https://github.com/zzallirog/misstep)
when published). Misstep is trained on the user's own session corpus; it
predicts `P(stumble at this user turn)` from the embedding of the correction
turn.

Hypothesis (locked in `weighted_compact/misstep_score.py`):

> Important pair ≈ user STOPPED stumbling on this correction.
> Low stumble probability at correction = high load-bearing weight.

`misstep_score = 1 − P(stumble)`, clipped + rescaled to `[0, 1]`. If misstep
is not installed, this signal is absent and the mixture re-weights the
remaining five.

### `density_score` — content-bearing proxy (weight 0.25)

Sixteen features per pair: length, named-entity density, numbers/dates,
code fences, quoted strings, line count, unique-word ratio, etc. Mean
across the sixteen, rank-normalized to `[0, 1]`.

The intuition: dense content carries more retrievable signal than
filler. Dense turns are usually worth keeping verbatim.

### `label_keep` — noisy human signal (weight 0.15)

`1` if the pair has a label of `keep` or `maybe` in `labels.jsonl`; `0`
otherwise. Intentionally a low weight, because labels are sparse and
collected ad-hoc — a pair without a label should not be implicitly
penalized.

### `span_keep_frac`, `span_maybe_frac`, `span_skip_frac`, `span_think_frac` (weights 0.20 / 0.10 / −0.15 / 0.05)

Per-tier character-fraction coverage of the *correction* text. Computed
by `span_features.py` from the tombstone-replayed
`inline_annotations.jsonl`.

```
span_<tier>_frac(i) = sum(char ranges tagged <tier> on correction)
                      / len(correction_text)
```

Most pairs have zero spans (coverage is sparse — 2 / 484 in the original
target corpus). The mixture handles sparsity automatically: an all-zero
row contributes nothing, and the other signals carry the weight.

THINK is intentionally light positive: it preserves the span but flags it
for re-examination later. Downstream renderers (the W2 ambient render
layer, not yet implemented) can mark these visibly so future sessions
notice "here be open thread."

## Why these weights and not others

The defaults are **heuristic**, not optimized. They came from one
afternoon of looking at how the signals correlated with the user's manual
labels on a 484-pair corpus.

The labeler UI surfaces the components separately so you can see *which*
signal is firing on a given pair. The W3 reconstruction-QA loop measures
the downstream effect of changing weights — if you raise misstep to 0.60
and drop density to 0.05, recon-QA will tell you whether you broke
content preservation.

When the recon-QA gate has 50+ baseline samples, the weights should be
re-fit by a small grid search rather than left at the defaults. Until
then, the defaults are good enough to keep working.

## Graceful degradation

| Missing input | Result |
|---|---|
| `features_misstep.npz` | misstep dropped; remaining five re-weight |
| `features_density.npz` | density dropped; remaining five re-weight |
| `features_spans.npz` | all four span terms collapse to zero |
| `labels.jsonl` | label_keep dropped; remaining five re-weight |

The pipeline degrades to a vector baseline (top-K by recency-of-correction)
in the degenerate case where only `pairs.jsonl` and `features.npz` exist.
This is the failure mode the invariant 1 was written for.

## How to tune

```bash
# See current weights and provenance
weighted-compact importance --show-defaults

# Recompute importance.npz from scratch
weighted-compact importance

# A/B compare two weight sets via recon-QA
weighted-compact eval --weights-a defaults --weights-b experimental
```

The UI also surfaces a per-component bar next to each pair so you can see
why a particular score is what it is. This is the anti-Goodhart
scaffolding — when one signal dominates, you see it explicitly.

## Ablation: label-weight effect on recon-QA fidelity

How load-bearing is the `label` slot? The
[reconstruction-QA loop](reconstruction-qa.md) is the tool that
answers this — flip the weight, re-run, see the score move.

Setup (run 2026-05-19):

- Ablation grid: `label_weight ∈ {0.0, 0.15}` × `seed ∈ {1..5}` × three
  disjoint session corpora (78 / 61 / 74 eligible pair_idxs each — split
  by `session_id` so no session appears in two corpora).
- Sampling: per `(corpus, seed)`, draw 4 pair_idxs without replacement;
  the **same four** are evaluated under both weights to enable a paired
  comparison.
- Per pair: `evaluate_pair_fidelity(n_questions=3, k_drop=0.5,
  topic_decay=0.5)` — three auto-generated Qs targeting the hidden
  pair, answered by `qwen2.5:7b` against the compacted context, judged
  by `gemma3:4b`. Fidelity ∈ {0, 0.33, 0.67, 1.0} per pair.
- Total: 120 pair-evaluations (60 per weight), 360 question-evaluations.

Aggregate (judge-yes fraction, mean over pairs):

| weight | n | mean | sd | 95 % CI |
|---:|---:|---:|---:|---|
| `0.00` | 58 | 0.081 | 0.157 | ±0.040 |
| `0.15` | 58 | 0.132 | 0.197 | ±0.051 |

Per-corpus mean (label_active − label_off):

| corpus | sessions | label_off | label_base | Δ |
|---|---:|---:|---:|---:|
| A | 13 | 0.100 | 0.200 | **+0.100** |
| B | 13 | 0.105 | 0.133 | **+0.028** |
| C | 13 | 0.035 | 0.056 | **+0.021** |

Paired diff over the n=57 pairs where both weights produced a fidelity
value (one pair dropped on missing-context error in one config):

> **mean Δfidelity = +0.053**, 95 % CI **[−0.004, +0.109]**
> sign breakdown: 13 positive, 6 negative, 38 ties

Reading: the direction is **positive in all three corpora** and on the
non-tied paired pairs (13:6 in favour of `label_base`). The 95 % CI on
the paired mean just barely crosses zero on the lower bound, so this is
a **directionally consistent signal at marginal significance** for
N=57 — not a knockout, not noise. Ties dominate (38 / 57) because
fidelity is a 4-value discrete score on 3 questions; many pairs survive
or fail identically under both weights. The size of the effect
(roughly +5 percentage points on judge-yes) is what `weight = 0.15`
buys you over `weight = 0`.

Raw runs: `~/work/weighted-compact/ablation_label_weight_results.jsonl`
(120 rows) plus `ablation_label_weight_summary.json` (aggregates).
Bigger corpora and more seeds will tighten the CI; the harness for
that is `ablation_label_weight.py`, same shape as above.
