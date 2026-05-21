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
