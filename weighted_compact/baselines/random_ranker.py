"""Random-uniform baseline ranker.

Black box:
  input  — pairs.jsonl (only pair_indices needed); seed.
  output — baseline_random.npz with two keys (pair_indices, importance) +
           meta. Seeded for reproducibility — same seed → same scores.
  entry  — `build(seed)` writes the npz. `main()` is the CLI entry.

Sense: this is the absolute lower bound. If random selection achieves
comparable fidelity to the seven-signal mixture, the signals carry no
information beyond chance.
"""
from __future__ import annotations

import json

import numpy as np

from weighted_compact import config
from weighted_compact.recon_qa.context import load_pairs

DEFAULT_SEED = 42


def build(seed: int = DEFAULT_SEED) -> dict:
    """Generate baseline_random.npz. Returns summary dict for logging."""
    pairs = load_pairs()
    n = len(pairs)
    if n == 0:
        raise RuntimeError('no pairs in substrate — run bootstrap first')
    pair_indices = np.array([p['pair_idx'] for p in pairs], dtype=np.int32)
    rng = np.random.default_rng(seed)
    importance = rng.uniform(0.0, 1.0, size=n).astype(np.float32)
    out = config.baseline_random_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        'ranker': 'random',
        'seed': int(seed),
        'pair_count': int(n),
        'rationale': 'uniform[0,1] seeded — absolute lower bound for fidelity comparison',
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
        'seed': seed,
        'min': float(importance.min()),
        'max': float(importance.max()),
        'mean': float(importance.mean()),
    }


def main() -> None:
    """CLI entry — `python -m weighted_compact.baselines.random_ranker`."""
    summary = build()
    print(f"Output: {summary['path']}")
    print(f"N={summary['n']}  seed={summary['seed']}  "
          f"min={summary['min']:.3f} mean={summary['mean']:.3f} max={summary['max']:.3f}")


if __name__ == '__main__':
    main()
