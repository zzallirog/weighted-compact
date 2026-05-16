#!/usr/bin/env python3
"""Phase 4C — combined continuous importance score.

Replaces marker-trained 3-tier classifier with a mixture of complementary
signals. Each signal is normalized to [0, 1]; final importance is a
weighted sum, clipped to [0, 1].

Signals (default weights):
  0.40  misstep_importance     = 1 - P(stumble at correction)   ← continuous backbone
  0.25  density_score          = mean of 16 content-density features (norm via rank)
  0.15  label_keep_indicator   = 1 if labels.jsonl says keep/maybe, else 0
  0.20  span_keep_corr_frac    = char-fraction of correction marked KEEP via UI
        + 0.10 * span_maybe_corr_frac   ← bonus for MAYBE spans
        - 0.15 * span_skip_corr_frac    ← penalty for explicit SKIP

Rationale (locked architectural invariant — vector-first, classifier-secondary):
  Per CLAUDE.md, classifier can degrade to vector baseline. Here misstep is
  the vector-based backbone (proxy from claw-session-substrate); density adds
  content-bearing proxy; pair labels (noisy per user) get smallest weight;
  span annotations get explicit-signal multiplier when present (sparse).

  No single signal can produce a Goodhart artifact alone — span coverage is
  sparse, misstep is independent corpus, density measures different axis,
  label is noisy. Mixture diffuses overfit risk.

Output importance.npz:
  importance        : (N,) ∈ [0, 1]
  pair_indices      : (N,)
  components        : (N, 6) — [misstep, density, label, span_keep, span_maybe, span_skip]
  weights           : (6,)
  meta              : json dict of defaults + provenance
"""
import json

import numpy as np

from weighted_compact import config

FEATURES_DENSITY = config.features_density_path()
FEATURES_MISSTEP = config.features_misstep_path()
FEATURES_SPANS = config.features_spans_path()
LABELS = config.labels_path()
OUT = config.importance_path()

WEIGHTS = {
    'misstep':       0.40,
    'density':       0.25,
    'label':         0.15,
    'span_keep':     0.20,
    'span_maybe':    0.10,
    'span_skip':    -0.15,
    'span_think':    0.05,   # preserve + flag for re-examination (lower than KEEP, not drop)
}


def rank_normalize(x):
    """Map values to [0, 1] via average-rank percentile."""
    from scipy.stats import rankdata
    if len(x) == 0:
        return x
    return (rankdata(x, method='average') - 1) / max(1, len(x) - 1)


def load_labels_keep_mask(pair_indices):
    """Per pair_idx, return 1.0 if last label is keep, 0.5 if maybe, else 0."""
    LABEL_VAL = {'keep': 1.0, 'maybe': 0.5, 'skip': 0.0, 'false_positive': 0.0}
    last_label = {}
    if LABELS.exists():
        with open(LABELS, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                last_label[r['pair_idx']] = r.get('label', 'skip')
    out = np.zeros(len(pair_indices), dtype=np.float32)
    for i, pid in enumerate(pair_indices):
        lab = last_label.get(int(pid))
        if lab is not None:
            out[i] = LABEL_VAL.get(lab, 0.0)
    return out


def main():
    misstep = np.load(FEATURES_MISSTEP, allow_pickle=True)
    density = np.load(FEATURES_DENSITY, allow_pickle=True)
    spans   = np.load(FEATURES_SPANS, allow_pickle=True)

    pair_indices = misstep['pair_indices']
    assert np.array_equal(pair_indices, density['pair_indices']), \
        "misstep ↔ density pair_indices misalignment"
    assert np.array_equal(pair_indices, spans['pair_indices']), \
        "misstep ↔ spans pair_indices misalignment"

    # Signal 1: misstep importance (already 1 - stumble_prob)
    sig_misstep = misstep['importance']

    # Signal 2: density score (mean of 16 features, rank-normalized for scale safety)
    density_mean = density['density'].mean(axis=1)
    sig_density = rank_normalize(density_mean).astype(np.float32)

    # Signal 3: label-derived indicator
    sig_label = load_labels_keep_mask(pair_indices)

    # Signals 4-7: span fractions on correction side (cols 0..3 = keep/maybe/skip/think_corr)
    span_mat = spans['spans']
    sig_span_keep  = span_mat[:, 0]
    sig_span_maybe = span_mat[:, 1]
    sig_span_skip  = span_mat[:, 2]
    sig_span_think = span_mat[:, 3]

    components = np.stack([
        sig_misstep, sig_density, sig_label,
        sig_span_keep, sig_span_maybe, sig_span_skip, sig_span_think,
    ], axis=1).astype(np.float32)  # (N, 7)

    weight_vec = np.array([
        WEIGHTS['misstep'], WEIGHTS['density'], WEIGHTS['label'],
        WEIGHTS['span_keep'], WEIGHTS['span_maybe'], WEIGHTS['span_skip'], WEIGHTS['span_think'],
    ], dtype=np.float32)

    importance = components @ weight_vec
    importance = np.clip(importance, 0.0, 1.0).astype(np.float32)

    meta = {
        'weights': WEIGHTS,
        'misstep_held_out_auc': json.loads(str(misstep['meta'][0]))['auc_held_out'],
        'span_coverage_count': int((span_mat.sum(axis=1) > 0).sum()),
        'pair_count': int(len(pair_indices)),
        'rationale': 'vector-first/classifier-secondary; mixture diffuses Goodhart',
    }

    np.savez(
        OUT,
        importance=importance,
        pair_indices=pair_indices.astype(np.int32),
        components=components,
        weights=weight_vec,
        component_names=np.array([
            'misstep', 'density', 'label',
            'span_keep_corr', 'span_maybe_corr', 'span_skip_corr', 'span_think_corr',
        ], dtype=object),
        meta=np.array([json.dumps(meta)], dtype=object),
    )

    # Summary
    print(f'Output: {OUT}')
    print(f'N={len(importance)}  '
          f'min={importance.min():.3f} median={np.median(importance):.3f} '
          f'max={importance.max():.3f}  mean={importance.mean():.3f}')
    print('\nTop-10 importance pairs:')
    top = np.argsort(-importance)[:10]
    for row in top:
        pid = int(pair_indices[row])
        print(f'  pair[{pid:3d}]  importance={importance[row]:.3f}  '
              f'misstep={sig_misstep[row]:.2f} dens={sig_density[row]:.2f} '
              f'lab={sig_label[row]:.1f} '
              f'span_k={sig_span_keep[row]:.2f}/m={sig_span_maybe[row]:.2f}/t={sig_span_think[row]:.2f}')
    print('\nBottom-10 importance pairs:')
    bot = np.argsort(importance)[:10]
    for row in bot:
        pid = int(pair_indices[row])
        print(f'  pair[{pid:3d}]  importance={importance[row]:.3f}  '
              f'misstep={sig_misstep[row]:.2f} dens={sig_density[row]:.2f} '
              f'lab={sig_label[row]:.1f}')

    print('\nWeights:')
    for k, v in WEIGHTS.items():
        print(f'  {k:14s}  {v:+.2f}')


if __name__ == '__main__':
    main()
