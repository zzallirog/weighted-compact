#!/usr/bin/env python3
"""Phase 4A — span-density features per pair.

Reads inline_annotations.jsonl (respects tombstone soft-deletes), aggregates
per pair_idx into per-tier coverage fractions of the underlying side text.

Output features_spans.npz (N×8):
  cols (per pair, in order):
    0  keep_frac_corr   = sum(keep span chars on correction)   / len(correction_text)
    1  maybe_frac_corr  = sum(maybe span chars on correction)  / len(correction_text)
    2  skip_frac_corr   = sum(skip span chars on correction)   / len(correction_text)
    3  think_frac_corr  = sum(think span chars on correction)  / len(correction_text)
    4  keep_frac_prem   = same for premise side
    5  maybe_frac_prem
    6  skip_frac_prem
    7  think_frac_prem

Coverage is sparse: most pair_idx have zero spans → all-zero rows. Downstream
mixture in importance.py applies these only where signal exists.

Aligned with features.npz pair_indices for trivial join.

Usage: python3 span_features.py
"""
import json
from collections import defaultdict

import numpy as np

from weighted_compact import config

ANNOTATIONS = config.annotations_path()
PAIRS = config.pairs_path()
FEATURES = config.features_path()
OUT = config.features_spans_path()

MARKERS = ['keep', 'maybe', 'skip', 'think']
SIDES   = ['correction', 'premise']  # column-major order: corr first, then prem


def load_active_annotations():
    """Replay journal honoring tombstones. Returns list of live annotation dicts."""
    by_id = {}
    if not ANNOTATIONS.exists():
        return []
    with open(ANNOTATIONS, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            aid = rec.get('id')
            if aid is None:
                continue
            if rec.get('deleted'):
                by_id.pop(aid, None)
                continue
            by_id[aid] = rec
    return list(by_id.values())


def load_pairs_texts():
    """Return dict pair_idx → {'premise': str, 'correction': str}."""
    texts = {}
    with open(PAIRS, encoding='utf-8') as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            texts[idx] = {
                'premise': r.get('premise_text', '') or '',
                'correction': r.get('correction_text', '') or '',
            }
    return texts


def main():
    annotations = load_active_annotations()
    texts = load_pairs_texts()
    feats = np.load(FEATURES, allow_pickle=True)
    pair_indices = feats['pair_indices']

    # Aggregate char-spans per (pair_idx, side, marker)
    chars: defaultdict[tuple, int] = defaultdict(int)
    for a in annotations:
        pid = a.get('pair_idx')
        side = a.get('side')
        marker = a.get('marker')
        rng = a.get('char_range') or [0, 0]
        if pid is None or side not in SIDES or marker not in MARKERS:
            continue
        try:
            start, end = int(rng[0]), int(rng[1])
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        chars[(pid, side, marker)] += (end - start)

    # Build matrix aligned to pair_indices order
    n = len(pair_indices)
    out = np.zeros((n, 8), dtype=np.float32)
    coverage = 0
    for row, pid in enumerate(pair_indices):
        pid = int(pid)
        t = texts.get(pid)
        if not t:
            continue
        has_span = False
        for ci, (side, marker) in enumerate(
            [(s, m) for s in SIDES for m in MARKERS]
        ):
            denom = len(t[side]) or 1
            v = chars.get((pid, side, marker), 0) / denom
            if v > 0:
                has_span = True
            out[row, ci] = min(1.0, v)
        if has_span:
            coverage += 1

    np.savez(
        OUT,
        spans=out,
        pair_indices=pair_indices.astype(np.int32),
        cols=np.array([
            f'{m}_frac_{"corr" if s == "correction" else "prem"}'
            for s in SIDES for m in MARKERS
        ], dtype=object),
    )

    print(f'Output      : {OUT}')
    print(f'Shape       : {out.shape}')
    print(f'Coverage    : {coverage}/{n} pairs have at least one active span')
    print(f'Annotations : {len(annotations)} live (post-tombstone)')
    # Quick per-tier total
    totals = out.sum(axis=0)
    cols = [f'{m}_{"corr" if s == "correction" else "prem"}' for s in SIDES for m in MARKERS]
    print('Σ frac (per col):')
    for c, v in zip(cols, totals):
        print(f'  {c:18s}  {v:.4f}')


if __name__ == '__main__':
    main()
