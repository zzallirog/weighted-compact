"""Baseline rankers for fidelity comparison against the seven-signal mixture.

Each ranker is a drop-in replacement for `importance.npz` — produces an
npz with two required keys (`pair_indices`, `importance`) plus optional
`meta`. Fed into `recon_qa.run_eval(ranker=<name>)`.

Static rankers (this module shipped first):
    random_ranker   — seeded uniform; absolute lower bound
    recency_ranker  — position-in-session ascending; cheapest baseline

Query-aware rankers (Phase 2, planned):
    cosine_ranker, bm25_ranker — see plan file.

Naive `/compact` simulator (Phase 3, planned):
    compact_simulator — bypass pair-selection entirely, summarize via LLM.

Each module exposes a `build()` entry point that writes its npz, plus a
top-level `main()` for CLI dispatch via `weighted-compact baseline build
--ranker X`.
"""

from weighted_compact.baselines import random_ranker, recency_ranker

__all__ = ['random_ranker', 'recency_ranker']
