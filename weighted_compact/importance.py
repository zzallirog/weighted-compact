#!/usr/bin/env python3
"""Phase 4C — combined continuous importance score.

Replaces marker-trained 3-tier classifier with a mixture of complementary
signals. Each signal is normalized to [0, 1]; final importance is a
weighted sum, clipped to [0, 1].

Signals (default weights — seven total):
  0.40  misstep_importance     = 1 - P(stumble at correction)   ← continuous backbone
  0.25  density_score          = mean of 16 content-density features (norm via rank)
  0.15  label_keep_indicator   = 1 if labels.jsonl says keep/maybe, else 0
  0.20  span_keep_corr_frac    = char-fraction of correction marked KEEP via UI
  0.10  span_maybe_corr_frac   = char-fraction marked MAYBE (bonus weight)
 -0.15  span_skip_corr_frac    = char-fraction marked SKIP (explicit penalty)
  0.05  span_think_corr_frac   = char-fraction marked THINK (preserve + flag for re-examination,
                                  lower than KEEP, not a drop)

Rationale (locked architectural invariant — vector-first, classifier-secondary):
  Per CLAUDE.md, classifier can degrade to vector baseline. Here misstep is
  the vector-based backbone (proxy from claw-session-substrate); density adds
  content-bearing proxy; pair labels (noisy per user) get smallest weight;
  span annotations get explicit-signal multiplier when present (sparse).

  No single signal can produce a Goodhart artifact alone — span coverage is
  sparse, misstep is independent corpus, density measures different axis,
  label is noisy. Mixture diffuses overfit risk.

  Graceful degradation: if `features_misstep.npz` is missing (misstep
  predictor not installed), the misstep column is set to zero and the
  remaining six signals carry the load. The invariant "vectors first,
  classifier as refinement" is preserved — density + spans + labels are
  enough to rank pairs, just less sharply.

Output importance.npz:
  importance        : (N,) ∈ [0, 1]
  pair_indices      : (N,)
  components        : (N, 7) — [misstep, density, label,
                                span_keep, span_maybe, span_skip, span_think]
  weights           : (7,)
  meta              : json dict of defaults + provenance
"""
import json
from typing import Protocol, runtime_checkable

import numpy as np

from weighted_compact import config


@runtime_checkable
class Signal(Protocol):
    """A signal contributing to the importance mixture.

    Public extension point. The seven default signals composed in
    :func:`main` below are not required to *be* ``Signal`` instances —
    they are stitched together as raw arrays for performance. ``Signal``
    documents the shape that *external* contributors should adopt when
    they want to add a new signal to a custom mixture or feed a custom
    ranker (see :mod:`weighted_compact.ranker`).

    Contract:

    - ``name`` is a short identifier (used as a column name in the
      mixture meta and as a key in :data:`WEIGHTS`).
    - ``compute(pair_indices)`` returns a ``numpy.ndarray`` of float
      scores in ``[0, 1]``, one per pair_idx in the input. The returned
      array's length MUST equal ``len(pair_indices)``. Missing data
      MUST be encoded as ``0.0``, never ``NaN`` — the mixture sums
      across columns and a single NaN poisons the row.

    The ``WEIGHTS`` dict below maps signal name → weight; a custom
    mixture that supplies its own ``Signal`` implementations should
    publish its own weights dict in the same shape.

    This Protocol is documentation, not enforcement. The default
    pipeline does not validate `compute` calls — `runtime_checkable` is
    set so third-party code can ``isinstance(x, Signal)`` opportunistically.
    """

    name: str

    def compute(self, pair_indices) -> "np.ndarray":  # pragma: no cover - Protocol
        ...

# Bump when the npz layout changes (new array, removed array, dtype change).
# Existing files predating the schema_ver field are treated as ver 0 by the
# loader in recon_qa/context.py — see `load_importance` for the migration
# directive. Keep at 1 until the first incompatible change.
SCHEMA_VER = 1

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
    """Map values to [0, 1] via average-rank percentile (numpy-only, ties → mean rank)."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n == 0:
        return x
    order = x.argsort(kind='stable')
    ranks = np.empty(n, dtype=float)
    ranks[order] = np.arange(1, n + 1, dtype=float)
    sorted_x = x[order]
    i = 0
    while i < n:
        j = i + 1
        while j < n and sorted_x[j] == sorted_x[i]:
            j += 1
        if j > i + 1:
            ranks[order[i:j]] = (i + 1 + j) / 2.0
        i = j
    return (ranks - 1) / max(1, n - 1)


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
    density = np.load(FEATURES_DENSITY, allow_pickle=True)
    spans   = np.load(FEATURES_SPANS, allow_pickle=True)
    pair_indices = density['pair_indices']
    assert np.array_equal(pair_indices, spans['pair_indices']), \
        "density ↔ spans pair_indices misalignment"

    # Signal 1: misstep importance (already 1 - stumble_prob). Optional:
    # if the misstep predictor was never installed, fall back to a zero
    # column. The architectural invariant ("vectors first, classifier as
    # refinement") permits this — density + spans + labels remain.
    misstep = None
    if FEATURES_MISSTEP.exists():
        misstep = np.load(FEATURES_MISSTEP, allow_pickle=True)
        assert np.array_equal(pair_indices, misstep['pair_indices']), \
            "density ↔ misstep pair_indices misalignment"
        sig_misstep = misstep['importance']
    else:
        sig_misstep = np.zeros(len(pair_indices), dtype=np.float32)

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

    misstep_auc: float | None = None
    if misstep is not None:
        try:
            misstep_auc = json.loads(str(misstep['meta'][0])).get('auc_held_out')
        except (KeyError, ValueError, IndexError):
            misstep_auc = None
    meta = {
        'weights': WEIGHTS,
        'misstep_held_out_auc': misstep_auc,
        'misstep_present': misstep is not None,
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
        schema_ver=np.array([SCHEMA_VER], dtype=np.int32),
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
