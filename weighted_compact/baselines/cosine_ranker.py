"""Cosine-retrieval baseline ranker — e5 dense similarity, query-aware.

Black box:
  input  — features.npz (windows (N, 3, 384) of e5-multilingual-small
           embeddings with the 'passage: ' prefix already baked in at
           build-time) + a runtime question string.
  output — dict pair_idx → cosine_similarity(pair_vec, query_vec) ∈ [-1, 1].
           Per-pair pair_vec = mean of three windows (prev_assistant,
           premise, correction).
  entry  — `CosineRanker()` constructs once (loads features + model);
           `ranker(query)` returns the score dict. Designed to be cached
           across many Qs.

Sense: tests whether dense retrieval alone, given the same e5 vector
substrate the mixture uses for graceful degradation, beats the seven-
signal weighted sum. If yes, the other six signals carry no marginal
information beyond cosine. If no, the mixture is doing something the
single-signal baseline cannot.
"""
from __future__ import annotations

import numpy as np

from weighted_compact import config


class CosineRanker:
    """Stateful query-aware ranker. Construct once, call per query."""

    def __init__(self):
        feats_path = config.features_path()
        if not feats_path.exists():
            raise FileNotFoundError(
                f'{feats_path} not found — run `weighted-compact bootstrap` '
                f'so that feature_extract.py emits the e5 windows',
            )
        npz = np.load(feats_path)
        # windows: (N, 3, EMBED_DIM) — passage: prefix baked in
        windows = npz['windows']
        # mean across [prev_assistant, premise, correction] → pair vector
        pair_vecs = windows.mean(axis=1)
        # L2-normalise so dot product == cosine
        norms = np.linalg.norm(pair_vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self.pair_vecs = (pair_vecs / norms).astype(np.float32)
        self.pair_indices = np.asarray(npz['pair_indices'], dtype=np.int32)

        # Lazy-import sentence_transformers to keep cold-start latency low
        # for users who only run static baselines.
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer('intfloat/multilingual-e5-small')

    def __call__(self, query: str) -> dict[int, float]:
        """Score all pairs against the query. Higher = closer match."""
        q_emb = self.model.encode(
            [f'query: {query}'],
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]
        sims = self.pair_vecs @ q_emb.astype(np.float32)
        return {int(self.pair_indices[i]): float(sims[i])
                for i in range(len(sims))}


def build() -> dict:
    """Smoke-construct the ranker so users can verify features.npz is wired.

    Unlike static rankers this does NOT write a .npz — query-aware rankers
    are stateful, so the artefact is the class itself. `qa-gate --ranker
    cosine` constructs it on demand inside fidelity.run_eval.
    """
    ranker = CosineRanker()
    return {
        'path': '<in-memory CosineRanker>',
        'n': int(len(ranker.pair_indices)),
        'min': 0.0,
        'max': 1.0,
        'mean': float('nan'),
    }


def main() -> None:
    """CLI smoke entry — `python -m weighted_compact.baselines.cosine_ranker`."""
    summary = build()
    print(f"CosineRanker constructed: {summary['path']}")
    print(f"  N pairs indexed = {summary['n']}")
    print('  (no npz written — query-aware ranker scores on demand)')


if __name__ == '__main__':
    main()
