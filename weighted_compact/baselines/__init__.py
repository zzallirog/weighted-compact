"""Baseline rankers for fidelity comparison against the seven-signal mixture.

Two flavours:

**Static rankers** — produce a drop-in `importance.npz`-shaped artefact
on disk (pair_indices + importance ∈ [0, 1]). Loaded once into a dict
and fed to `recon_qa.run_eval(ranker=<name>)`:
    random_ranker   — seeded uniform; absolute lower bound
    recency_ranker  — position-in-session ascending; cheapest baseline

**Query-aware rankers** — stateful callable objects, construct once and
score per Q at fidelity.run_eval call time:
    cosine_ranker (CosineRanker)  — e5 dense similarity to query
    bm25_ranker   (Bm25Ranker)    — sparse-IR classical baseline

Naive `/compact` simulator (Phase 3, planned):
    compact_simulator — bypass pair selection entirely, summarize via LLM.

Each module exposes `build()` (writes npz for static, smoke-constructs
for query-aware) and `main()` for CLI dispatch via `weighted-compact
baseline build --ranker X`. Query-aware rankers are also imported lazily
by `recon_qa.fidelity` so cold-start cost of static rankers is unaffected.
"""

from weighted_compact.baselines import random_ranker, recency_ranker

__all__ = ['random_ranker', 'recency_ranker']
