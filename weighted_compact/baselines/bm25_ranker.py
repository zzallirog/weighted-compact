"""BM25-retrieval baseline ranker — sparse-IR classical baseline.

Black box:
  input  — pairs.jsonl (premise_text + correction_text tokenized) +
           a runtime question string.
  output — dict pair_idx → BM25 score (unbounded ≥ 0, higher = better
           match). NOT in [0, 1]; ranking is by relative order, not
           threshold.
  entry  — `Bm25Ranker()` constructs once (tokenizes + builds index);
           `ranker(query)` returns the score dict. Designed to be cached
           across many Qs.

Sense: classical sparse-IR baseline against the dense-cosine query-aware
ranker and the dense-signal mixture. If BM25 wins on this corpus, the
fidelity story is driven by lexical match (entity names, paths,
identifiers — which the §Headline 'anchor-rich content survives'
finding already suggests).

Tokenization: lowercase + split on non-alphanumeric. Sufficient for
identifier-heavy technical text; can be replaced with a smarter
tokenizer if results suggest it.

Dependency: rank-bm25 (optional extra). Install via
`pip install -e .[baselines]`.
"""
from __future__ import annotations

import re

from weighted_compact.recon_qa.context import load_pairs

_TOKEN_RE = re.compile(r'[A-Za-z0-9_]+')


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumeric. Stable for identifier-rich text."""
    if not text:
        return []
    return [tok.lower() for tok in _TOKEN_RE.findall(text)]


class Bm25Ranker:
    """Stateful query-aware ranker. Construct once, call per query."""

    def __init__(self):
        try:
            from rank_bm25 import BM25Okapi
        except ImportError as exc:
            raise ImportError(
                'rank-bm25 not installed — install via '
                '`pip install -e .[baselines]` or `pip install rank-bm25`',
            ) from exc

        pairs = load_pairs()
        if not pairs:
            raise RuntimeError('no pairs in substrate — run bootstrap first')

        # Corpus document = premise + correction tokens concatenated
        self.corpus_tokens: list[list[str]] = []
        self.pair_indices: list[int] = []
        for p in pairs:
            tokens = _tokenize(p.get('premise_text', '')) + _tokenize(
                p.get('correction_text', ''),
            )
            self.corpus_tokens.append(tokens)
            self.pair_indices.append(p['pair_idx'])

        # Empty docs cause BM25Okapi to misbehave; insert a sentinel token
        for tokens in self.corpus_tokens:
            if not tokens:
                tokens.append('__empty__')

        self.bm25 = BM25Okapi(self.corpus_tokens)

    def __call__(self, query: str) -> dict[int, float]:
        """Score all pairs against the query. Higher = better lexical match."""
        q_tokens = _tokenize(query)
        if not q_tokens:
            # No queryable tokens → zero scores everywhere
            return {pid: 0.0 for pid in self.pair_indices}
        scores = self.bm25.get_scores(q_tokens)
        return {int(self.pair_indices[i]): float(scores[i])
                for i in range(len(scores))}


def build() -> dict:
    """Smoke-construct the ranker so users can verify pairs.jsonl is wired.

    Like CosineRanker, BM25 is stateful and writes no npz; constructed on
    demand inside fidelity.run_eval.
    """
    ranker = Bm25Ranker()
    return {
        'path': '<in-memory Bm25Ranker>',
        'n': len(ranker.pair_indices),
        'min': 0.0,
        'max': float('inf'),
        'mean': float('nan'),
    }


def main() -> None:
    """CLI smoke entry — `python -m weighted_compact.baselines.bm25_ranker`."""
    summary = build()
    print(f"Bm25Ranker constructed: {summary['path']}")
    print(f"  N pairs indexed = {summary['n']}")
    print('  (no npz written — query-aware ranker scores on demand)')


if __name__ == '__main__':
    main()
