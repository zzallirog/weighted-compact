"""Manifesto hard-constraint: keep/skip labels as a deterministic SELECTION
guarantee, not a score nudge (Phase 4G).

The soft ``label`` signal (+0.15 in importance.py) can be overruled by a strong
density score — measured in docs/baselines.md, where the soft ranker only *ties*
recency on manifesto-honor. The hard manifesto applied here pins keep / banishes
skip at selection time, so it cannot be overruled. This is a control guarantee
over *what survives* compaction, NOT a reconstruction-fidelity improvement (the
importance mixture does not beat recency on fidelity — same doc).

Scoring in these fixtures deliberately works AGAINST the user's intent: the skip
pair scores highest, the keep pair lowest. If the manifesto were a soft boost it
could not rescue this; as a hard constraint it must.
"""
from __future__ import annotations

from weighted_compact.recon_qa.context import (
    build_compacted_context,
    build_compacted_context_with_meta,
    load_manifesto,
)


def _pairs():
    # pair_idx == list index; index 0 is the source pair (hidden), 1..4 mates.
    return [
        {"pair_idx": 0, "session_id": "s", "premise_text": "P0", "correction_text": "SRC"},
        {"pair_idx": 1, "session_id": "s", "premise_text": "P1", "correction_text": "KEEP_ME"},
        {"pair_idx": 2, "session_id": "s", "premise_text": "P2", "correction_text": "SKIP_ME"},
        {"pair_idx": 3, "session_id": "s", "premise_text": "P3", "correction_text": "N3"},
        {"pair_idx": 4, "session_id": "s", "premise_text": "P4", "correction_text": "N4"},
    ]


# skip pair scores highest, keep pair lowest — intent-hostile on purpose.
_SCORING = {1: 0.10, 2: 0.90, 3: 0.50, 4: 0.40}


def test_without_manifesto_score_wins_and_betrays_intent():
    # keep_n = int(4 * 0.5) = 2 → top-2 by score = pair2 (a SKIP!) + pair3.
    md = build_compacted_context(0, _pairs(), _SCORING, k_drop=0.5, topic_decay=1.0)
    assert "SKIP_ME" in md
    assert "KEEP_ME" not in md


def test_manifesto_pins_keep_and_banishes_skip():
    md = build_compacted_context(
        0, _pairs(), _SCORING, k_drop=0.5, topic_decay=1.0,
        manifesto={1: "keep", 2: "skip"},
    )
    assert "KEEP_ME" in md       # pinned despite lowest score
    assert "SKIP_ME" not in md   # banished despite highest score


def test_budget_is_unchanged_by_manifesto():
    base = build_compacted_context(0, _pairs(), _SCORING, k_drop=0.5, topic_decay=1.0)
    with_m = build_compacted_context(
        0, _pairs(), _SCORING, k_drop=0.5, topic_decay=1.0,
        manifesto={1: "keep", 2: "skip"},
    )
    # same number of chunk separators → same kept-pair count (manifesto only
    # reorders which pairs fill the identical budget).
    assert base.count("---") == with_m.count("---")


def test_budget_cap_drops_lowest_keeps_but_never_a_skip():
    # 3 keeps, budget 2 → the two highest-score keeps survive, the lowest keep is
    # dropped by budget, and the skip is still excluded.
    md = build_compacted_context(
        0, _pairs(), _SCORING, k_drop=0.5, topic_decay=1.0,
        manifesto={1: "keep", 3: "keep", 4: "keep", 2: "skip"},
    )
    assert "SKIP_ME" not in md          # a skip never sneaks in
    assert "N3" in md and "N4" in md    # two highest-score keeps
    assert "KEEP_ME" not in md          # lowest-score keep dropped by budget


def test_meta_reports_manifesto_honor(tmp_path):
    _, meta = build_compacted_context_with_meta(
        0, _pairs(), _SCORING, k_drop=0.5, topic_decay=1.0,
        manifesto={1: "keep", 2: "skip"},
        importance_path=tmp_path / "nope.npz",  # force signals_top3 = [] (no npz)
    )
    m = meta["manifesto"]
    assert m["active"] is True
    assert m["keeps_total"] == 1 and m["keeps_survived"] == 1
    assert m["skips_total"] == 1 and m["skips_dropped"] == 1


def test_meta_manifesto_inactive_when_none(tmp_path):
    _, meta = build_compacted_context_with_meta(
        0, _pairs(), _SCORING, k_drop=0.5, topic_decay=1.0,
        importance_path=tmp_path / "nope.npz",
    )
    assert meta["manifesto"] == {"active": False}


def test_load_manifesto_keeps_only_hard_tiers(tmp_path):
    p = tmp_path / "labels.jsonl"
    p.write_text(
        '{"pair_idx": 1, "label": "keep"}\n'
        '{"pair_idx": 2, "label": "skip"}\n'
        '{"pair_idx": 3, "label": "maybe"}\n'
        '{"pair_idx": 4, "label": "false_positive"}\n'
        '{"pair_idx": 1, "label": "skip"}\n'  # last-wins: pair 1 becomes skip
    )
    # maybe / false_positive carry no constraint; last label wins for pair 1.
    assert load_manifesto(labels_path=p) == {1: "skip", 2: "skip"}


def test_load_manifesto_missing_file(tmp_path):
    assert load_manifesto(labels_path=tmp_path / "absent.jsonl") == {}
