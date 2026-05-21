"""Baseline ranker smoke tests — synthetic 6-pair substrate.

Each baseline must:
  - run on a substrate with no features_*.npz prerequisites (just pairs.jsonl)
  - emit baseline_<name>.npz with the importance.npz schema:
      pair_indices: (N,) int32
      importance:   (N,) float32 in [0, 1]
  - load via recon_qa.context.load_baseline_<name>() into a pair_idx → float dict
  - be reproducible: same seed → same output (random ranker)

These run under CI on an isolated substrate; no Ollama, no real corpus needed.
"""

from __future__ import annotations

import importlib
import json

import numpy as np
import pytest


@pytest.fixture
def baseline_fixture(monkeypatch, tmp_path):
    """Substrate dir with a synthetic pairs.jsonl across two sessions.

    Reloads the recon_qa subpackage modules so the `from ._constants import ...`
    snapshots in context.py / fidelity.py pick up the new substrate paths.
    """
    monkeypatch.setenv("WEIGHTED_COMPACT_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("WEIGHTED_COMPACT_CLAUDE_SOURCES", str(tmp_path / "claude"))

    from weighted_compact import config
    from weighted_compact.recon_qa import _constants as recon_const
    from weighted_compact.recon_qa import context as recon_context
    from weighted_compact.recon_qa import fidelity as recon_fidelity

    importlib.reload(config)
    importlib.reload(recon_const)
    importlib.reload(recon_context)
    importlib.reload(recon_fidelity)

    (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    pairs = [
        {"session_id": "s1", "correction_uuid": "c0", "correction_text": "fix",
         "premise_uuid": "p0", "premise_text": "alpha", "marker_type": "x",
         "marker_match": "x", "tier_hint": "keep"},
        {"session_id": "s1", "correction_uuid": "c1", "correction_text": "fix",
         "premise_uuid": "p1", "premise_text": "beta", "marker_type": "x",
         "marker_match": "x", "tier_hint": "keep"},
        {"session_id": "s1", "correction_uuid": "c2", "correction_text": "fix",
         "premise_uuid": "p2", "premise_text": "gamma", "marker_type": "x",
         "marker_match": "x", "tier_hint": "keep"},
        {"session_id": "s2", "correction_uuid": "c3", "correction_text": "fix",
         "premise_uuid": "p3", "premise_text": "delta", "marker_type": "x",
         "marker_match": "x", "tier_hint": "keep"},
        {"session_id": "s2", "correction_uuid": "c4", "correction_text": "fix",
         "premise_uuid": "p4", "premise_text": "epsilon", "marker_type": "x",
         "marker_match": "x", "tier_hint": "keep"},
        {"session_id": "s2", "correction_uuid": "c5", "correction_text": "fix",
         "premise_uuid": "p5", "premise_text": "zeta", "marker_type": "x",
         "marker_match": "x", "tier_hint": "keep"},
    ]
    with open(config.pairs_path(), "w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p) + "\n")
    return tmp_path


def test_random_ranker_builds_and_loads(baseline_fixture):
    from weighted_compact.baselines import random_ranker
    from weighted_compact.recon_qa import context

    summary = random_ranker.build(seed=42)

    assert summary["n"] == 6
    assert 0.0 <= summary["min"] <= summary["max"] <= 1.0

    scores = context.load_baseline_random()
    assert set(scores.keys()) == {0, 1, 2, 3, 4, 5}
    assert all(0.0 <= v <= 1.0 for v in scores.values())


def test_random_ranker_seed_reproducible(baseline_fixture):
    from weighted_compact.baselines import random_ranker
    from weighted_compact.recon_qa import context

    random_ranker.build(seed=42)
    first = dict(context.load_baseline_random())

    random_ranker.build(seed=42)
    second = dict(context.load_baseline_random())

    assert first == second


def test_recency_ranker_orders_within_session(baseline_fixture):
    from weighted_compact.baselines import recency_ranker
    from weighted_compact.recon_qa import context

    summary = recency_ranker.build()
    assert summary["n"] == 6
    assert summary["sessions"] == 2

    scores = context.load_baseline_recency()
    # Within session s1 (pair_idx 0, 1, 2): later pair_idx → higher score
    assert scores[0] < scores[1] < scores[2]
    # Within session s2 (pair_idx 3, 4, 5): same monotonic property
    assert scores[3] < scores[4] < scores[5]
    # Last pair of each session normalises to 1.0
    assert scores[2] == pytest.approx(1.0)
    assert scores[5] == pytest.approx(1.0)


def test_load_baseline_random_errors_when_missing(baseline_fixture):
    from weighted_compact.recon_qa import context

    with pytest.raises(FileNotFoundError):
        context.load_baseline_random()


def test_run_eval_dispatches_baseline_rankers(baseline_fixture, monkeypatch):
    """run_eval should accept 'random' and 'recency' as ranker names."""
    from weighted_compact.baselines import random_ranker, recency_ranker
    from weighted_compact.recon_qa import fidelity

    random_ranker.build(seed=42)
    recency_ranker.build()

    # Empty qa_set → run_eval returns []; we're only testing dispatch here.
    assert fidelity.run_eval(k_drop=0.5, ranker="random") == []
    assert fidelity.run_eval(k_drop=0.5, ranker="recency") == []


def test_run_eval_rejects_unknown_ranker(baseline_fixture):
    from weighted_compact.recon_qa import fidelity

    with pytest.raises(ValueError, match="unknown ranker"):
        fidelity.run_eval(ranker="nonexistent")


# ----- Query-aware rankers (Phase 2) ---------------------------------------


def test_bm25_ranker_scores_pairs_by_lexical_match(baseline_fixture):
    """Pair text containing the query token should score higher than pairs
    that do not. Synthetic — no LLM, no embedding."""
    pytest.importorskip("rank_bm25")
    from weighted_compact.baselines.bm25_ranker import Bm25Ranker

    ranker = Bm25Ranker()
    scores = ranker("alpha")
    # alpha appears only in pair 0's premise → should score highest
    assert scores[0] > scores[3]
    assert scores[0] > scores[5]
    # All pair indices present
    assert set(scores.keys()) == {0, 1, 2, 3, 4, 5}


def test_bm25_ranker_empty_query_returns_zero_scores(baseline_fixture):
    pytest.importorskip("rank_bm25")
    from weighted_compact.baselines.bm25_ranker import Bm25Ranker

    ranker = Bm25Ranker()
    scores = ranker("")
    assert all(v == 0.0 for v in scores.values())


def test_build_compacted_context_accepts_callable_scoring(baseline_fixture):
    """Phase 2 contract: scoring may be dict OR callable(query) -> dict.
    Verifies the refactor without invoking ollama."""
    from weighted_compact.recon_qa.context import (
        build_compacted_context,
        load_pairs,
    )

    pairs = load_pairs()

    def callable_scoring(query: str) -> dict[int, float]:
        # Score by query length match — deterministic stub
        return {p["pair_idx"]: float(len(query)) for p in pairs}

    ctx = build_compacted_context(
        source_pair_idx=0,
        pairs=pairs,
        scoring=callable_scoring,
        k_drop=0.5,
        topic_decay=1.0,
        query="hello",
    )
    # source_pair_idx=0 is in session s1 — context should include s1's other pairs
    assert ctx
    assert "PREMISE:" in ctx


def test_build_compacted_context_callable_requires_query(baseline_fixture):
    from weighted_compact.recon_qa.context import (
        build_compacted_context,
        load_pairs,
    )

    pairs = load_pairs()
    callable_scoring = lambda q: {p["pair_idx"]: 1.0 for p in pairs}

    with pytest.raises(ValueError, match="requires query"):
        build_compacted_context(
            source_pair_idx=0,
            pairs=pairs,
            scoring=callable_scoring,
            k_drop=0.5,
            topic_decay=1.0,
            query=None,
        )


# ----- /compact simulator (Phase 3) ----------------------------------------


def test_compact_simulator_constructs(baseline_fixture):
    """Constructor smoke — no API calls. Verifies backend validation."""
    from weighted_compact.baselines.compact_simulator import CompactSummarizer

    qwen = CompactSummarizer('qwen2.5:7b', backend='ollama')
    assert qwen.model == 'qwen2.5:7b'
    assert qwen.backend == 'ollama'
    assert qwen.is_compact_bypass is True

    son = CompactSummarizer('claude-sonnet-4-5', backend='anthropic')
    assert son.is_compact_bypass is True

    with pytest.raises(ValueError, match="unknown backend"):
        CompactSummarizer('x', backend='gpt')


def test_compact_summarizer_prompt_marks_hidden(baseline_fixture):
    """Verify the prompt marks the source pair as [HIDDEN] and keeps the rest."""
    from weighted_compact.baselines.compact_simulator import _build_prompt
    from weighted_compact.recon_qa.context import load_pairs

    pairs = load_pairs()
    source = pairs[0]
    session_pairs = [p for p in pairs if p['session_id'] == source['session_id']]
    prompt = _build_prompt(source, session_pairs)
    assert "[HIDDEN]" in prompt
    # Other pairs from same session should appear with real content
    assert "beta" in prompt or "gamma" in prompt
    # The source pair's actual text should NOT appear in place of HIDDEN
    assert "alpha" not in prompt or "[HIDDEN]" in prompt.split("alpha", 1)[0]


def test_compact_sonnet_requires_api_key(baseline_fixture, monkeypatch):
    """compact_sonnet must refuse to call out without ANTHROPIC_API_KEY."""
    from weighted_compact.baselines.compact_simulator import (
        CompactSummarizer,
        _build_prompt,
    )

    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)

    from weighted_compact.baselines.compact_simulator import _call_anthropic
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        _call_anthropic("test", model="claude-sonnet-4-5")


def test_fidelity_dispatches_compact_bypass(baseline_fixture, monkeypatch):
    """run_eval with ranker='compact_qwen' should invoke summarize_excluding,
    not build_compacted_context. Verified by stubbing the summarizer."""
    from weighted_compact.baselines.compact_simulator import CompactSummarizer
    from weighted_compact.recon_qa import context as recon_context
    from weighted_compact.recon_qa import fidelity

    calls = {'summarize': 0, 'build_context': 0}

    def fake_summarize(self, source_pair_idx, pairs, query=None):
        calls['summarize'] += 1
        return "[fake summary]"

    monkeypatch.setattr(
        CompactSummarizer,
        'summarize_excluding',
        fake_summarize,
    )

    original_build = recon_context.build_compacted_context

    def counting_build(*args, **kwargs):
        calls['build_context'] += 1
        return original_build(*args, **kwargs)

    monkeypatch.setattr(fidelity, 'build_compacted_context', counting_build)

    # Empty qa_set → no actual iteration; we only check that the loader
    # path is exercised. Add one synthetic entry to force dispatch.
    monkeypatch.setattr(
        fidelity,
        'load_qa_set',
        lambda: [{'source_pair_idx': 0, 'q': 'test', 'a_truth': 'x'}],
    )

    # Stub ask_ollama + llm_judge so we don't actually call LLMs
    monkeypatch.setattr(fidelity, 'ask_ollama', lambda ctx, q: 'stub answer')
    monkeypatch.setattr(
        fidelity,
        'llm_judge',
        lambda q, a_truth, pred, source_pair=None: {
            'verdict': 'no', 'reasoning': 'stub', 'model': 'stub',
        },
    )

    results = fidelity.run_eval(ranker='compact_qwen', k_drop=0.5)

    assert calls['summarize'] == 1
    assert calls['build_context'] == 0
    assert len(results) == 1


def test_cosine_ranker_smoke(baseline_fixture, tmp_path):
    """Synthesize a minimal features.npz and verify CosineRanker scores deterministically.

    Skips if sentence-transformers cannot load the e5 model (no network /
    cache miss in CI)."""
    pytest.importorskip("sentence_transformers")
    pytest.importorskip("torch")

    from weighted_compact import config

    # Synthetic features.npz: 6 pairs × 3 windows × 384 dims, normalized
    n, k, d = 6, 3, 384
    rng = np.random.default_rng(0)
    raw = rng.standard_normal(size=(n, k, d)).astype(np.float32)
    norms = np.linalg.norm(raw, axis=2, keepdims=True)
    norms[norms == 0] = 1.0
    windows = raw / norms
    np.savez(
        config.features_path(),
        windows=windows,
        pair_indices=np.array([0, 1, 2, 3, 4, 5], dtype=np.int32),
        labels_3tier=np.array([2] * 6, dtype=np.int8),
    )

    try:
        from weighted_compact.baselines.cosine_ranker import CosineRanker
        ranker = CosineRanker()
    except (OSError, RuntimeError) as exc:
        pytest.skip(f"e5 model unavailable: {exc}")

    scores = ranker("any test query")
    assert set(scores.keys()) == {0, 1, 2, 3, 4, 5}
    # Cosine scores must lie in [-1, 1]
    assert all(-1.0 <= v <= 1.0 for v in scores.values())
