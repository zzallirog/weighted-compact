"""Recency-only baseline ranker — score = position-in-session, normalized.

Black box:
  input  — pairs.jsonl with session_id + pair_idx (enumerate order = ingest order).
  output — baseline_recency.npz with (pair_indices, importance) + meta.
  entry  — `build()` writes the npz. `main()` is the CLI entry.

Sense: cheapest baseline that uses any session structure. Newer turns
score higher within each session. If recency-only matches the mixture,
the multi-signal weighting buys nothing over a single-line heuristic.

Ordering: pairs.jsonl is appended in extraction order. Within a session,
later pair_idx means later turn (assumes `extract_pairs.py` writes in
session-order; verified by manual inspection of substrate).
"""
from __future__ import annotations

import json
from collections import defaultdict

import numpy as np

from weighted_compact import config
from weighted_compact.recon_qa.context import load_pairs


def build() -> dict:
    """Generate baseline_recency.npz. Returns summary dict for logging."""
    pairs = load_pairs()
    n = len(pairs)
    if n == 0:
        raise RuntimeError('no pairs in substrate — run bootstrap first')

    by_session: dict[str, list[int]] = defaultdict(list)
    for p in pairs:
        by_session[p['session_id']].append(p['pair_idx'])
    for sess in by_session.values():
        sess.sort()

    pair_to_pos = {}
    for sess_pairs in by_session.values():
        m = len(sess_pairs)
        for rank, pid in enumerate(sess_pairs):
            pair_to_pos[pid] = (rank + 1) / m if m > 0 else 0.0

    pair_indices = np.array([p['pair_idx'] for p in pairs], dtype=np.int32)
    importance = np.array(
        [pair_to_pos[int(pid)] for pid in pair_indices],
        dtype=np.float32,
    )
    out = config.baseline_recency_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        'ranker': 'recency',
        'pair_count': int(n),
        'session_count': len(by_session),
        'rationale': 'normalized position-in-session — cheapest single-line heuristic',
    }
    np.savez(
        out,
        importance=importance,
        pair_indices=pair_indices,
        meta=np.array([json.dumps(meta)], dtype=object),
    )
    return {
        'path': str(out),
        'n': n,
        'sessions': len(by_session),
        'min': float(importance.min()),
        'max': float(importance.max()),
        'mean': float(importance.mean()),
    }


def main() -> None:
    """CLI entry — `python -m weighted_compact.baselines.recency_ranker`."""
    summary = build()
    print(f"Output: {summary['path']}")
    print(f"N={summary['n']}  sessions={summary['sessions']}  "
          f"min={summary['min']:.3f} mean={summary['mean']:.3f} max={summary['max']:.3f}")


if __name__ == '__main__':
    main()
