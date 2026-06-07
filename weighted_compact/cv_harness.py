"""k-fold cross-validation harness for WC importance mixture search.

Split strategy: GroupKFold by session_id — all pairs from one session
go into the same fold, preventing leakage through shared context.

Mock judge (judge="mock"):
    Tier-based proxy — no LLM calls.  Correlation with real Sonnet fidelity
    is unknown (WC Warning #5: AUC 0.46-0.51 for feature classifiers), but
    provides a relative ranking signal for CMA-ES exploration.

gemma3 judge ("judge=gemma3"):
    Reserved for final validation of top-3 CMA-ES candidates.
    NOT invoked during the search phase.

Honest caveats (surface in report):
    - subset_a = 264 pairs, 182 sessions → ~36 sessions per fold at k=5
    - ~53 pairs per validation fold → power adequate for Δ≥1pp, underpowered for <1pp
    - WC Warning #1: 3.8% real Sonnet pass rate → ~2 positives per fold
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Session-level GroupKFold split
# ---------------------------------------------------------------------------

def split_by_sessions(
    pairs_data: list[dict] | Path,
    k: int = 5,
    seed: int = 42,
) -> list[np.ndarray]:
    """Split pairs into k folds grouped by session_id.

    Args:
        pairs_data: Either a list of pair dicts (each must have 'pair_idx'
            and 'session_id'), or a Path to a JSON/JSONL file.  For
            subset_a.json the session_id comes from the matching fidelity
            record (injected by replay_eval.precompute_replay_store).
        k: Number of folds.
        seed: RNG seed for reproducible shuffling.

    Returns:
        List of k boolean arrays, each of length n_pairs.
        mask[i] = True means pair i is in the validation set for fold k.

    Guarantee:
        All pairs from one session_id land in the same fold (GroupKFold).
        If session_id is missing on a pair, it falls back to 'unknown'
        (all unknowns share one group — worst-case but not a crash).
    """
    if isinstance(pairs_data, Path):
        text = pairs_data.read_text()
        if text.strip().startswith("["):
            pairs = json.loads(text)
        else:
            pairs = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        pairs = list(pairs_data)

    n_pairs = len(pairs)

    # Group pair indices by session_id
    sessions: dict[str, list[int]] = {}
    for i, p in enumerate(pairs):
        sid = p.get("session_id") or p.get("source_session_id") or "unknown"
        sessions.setdefault(sid, []).append(i)

    session_ids = list(sessions.keys())
    rng = np.random.default_rng(seed)
    rng.shuffle(session_ids)

    # Assign sessions to k buckets (round-robin for balanced sizes)
    session_buckets: list[list[str]] = [[] for _ in range(k)]
    for i, sid in enumerate(session_ids):
        session_buckets[i % k].append(sid)

    folds: list[np.ndarray] = []
    for fold_idx in range(k):
        mask = np.zeros(n_pairs, dtype=bool)
        for sid in session_buckets[fold_idx]:
            for pidx in sessions[sid]:
                mask[pidx] = True
        folds.append(mask)

    return folds


def compute_fold_stats(
    folds: list[np.ndarray],
    pairs: list[dict] | None = None,
) -> dict:
    """Diagnostic: fold sizes and balance check.

    Returns a dict with per-fold counts and imbalance ratio.
    Call before search to verify the split is reasonable.
    """
    n_total = len(folds[0])
    fold_sizes = [int(m.sum()) for m in folds]
    result: dict = {
        "n_total": n_total,
        "k": len(folds),
        "fold_sizes": fold_sizes,
        "min_fold": min(fold_sizes),
        "max_fold": max(fold_sizes),
        "imbalance_ratio": max(fold_sizes) / max(min(fold_sizes), 1),
    }

    # Leakage check: each pair in exactly one fold
    pair_fold_counts = np.zeros(n_total, dtype=int)
    for m in folds:
        pair_fold_counts += m.astype(int)
    result["leakage_detected"] = bool((pair_fold_counts != 1).any())
    result["pairs_in_multiple_folds"] = int((pair_fold_counts > 1).sum())
    result["pairs_in_no_fold"] = int((pair_fold_counts == 0).sum())

    return result


# ---------------------------------------------------------------------------
# Mock metric (tier-based proxy, 0 LLM calls)
# ---------------------------------------------------------------------------

_SIGNAL_NAMES = ["misstep", "density", "label", "span_keep", "span_maybe", "span_skip", "span_think"]
_CANONICAL_ORDER = ["misstep", "density", "label", "span_keep", "span_maybe", "span_skip", "span_think"]


def _apply_weights(
    components: np.ndarray,
    weights: dict[str, float],
) -> np.ndarray:
    """Apply weights dict to component matrix [n_pairs × 7] → importance [n_pairs]."""
    w_vec = np.array([weights.get(name, 0.0) for name in _CANONICAL_ORDER], dtype=np.float64)
    importance = components.astype(np.float64) @ w_vec
    return np.clip(importance, 0.0, 1.0)


def _mock_fidelity(
    importance: np.ndarray,
    gt_fidelity: np.ndarray,
    fold_mask: np.ndarray,
) -> float:
    """GT-weighted tier proxy for held-out fidelity.

    Combines two signals:
      1. Tier score for pairs with gt_fidelity > 0 (pass pairs): reward KEEP assignment.
         These are the 54 control-positive pairs from subset_pass.
      2. Inverse tier for pairs with gt_fidelity == 0 (fail pairs): mildly reward lower
         tiers (don't over-KEEP retrieval/generator failures).

    Formula:
        score = α * pass_tier_mean + (1-α) * (1 - fail_tier_mean)
        α = 0.7 (weight on pass-pair correct assignment)

    When fold has no pass pairs (gt_fidelity all 0):
        falls back to plain tier-mean (less discriminating but not wrong).

    Correlation with Sonnet fidelity: partially grounded via 54 pass pairs.
    For subset_a-only folds (all gt=0): reduces to plain tier mean (WC Warning #5).
    """
    held_importance = importance[fold_mask]
    held_gt = gt_fidelity[fold_mask]

    # Tier assignment
    tier_scores = np.where(
        held_importance >= 0.50, 1.0,
        np.where(held_importance >= 0.25, 0.5, 0.0)
    )

    pass_mask = held_gt > 0
    n_pass = int(pass_mask.sum())

    if n_pass == 0:
        # No GT signal in this fold: pure tier mean
        return float(tier_scores.mean())

    # Pass pairs: reward KEEP (high tier = good)
    pass_tier_mean = float(tier_scores[pass_mask].mean())

    # Fail pairs: mild reward for NOT keeping (lower tier = more discriminating)
    fail_mask = ~pass_mask
    n_fail = int(fail_mask.sum())
    if n_fail > 0:
        fail_tier_mean = float(tier_scores[fail_mask].mean())
        # 1 - fail_tier = reward for assigning lower tiers to failures
        fail_score = 1.0 - fail_tier_mean
    else:
        fail_score = 0.5  # neutral

    alpha = 0.70  # weight on pass-pair correct assignment
    return alpha * pass_tier_mean + (1.0 - alpha) * fail_score


# ---------------------------------------------------------------------------
# Main evaluation function
# ---------------------------------------------------------------------------

def eval_held_out_fidelity(
    weights: dict[str, float],
    components: np.ndarray,
    gt_fidelity: np.ndarray,
    fold_mask: np.ndarray,
    judge: str = "mock",
) -> float:
    """Compute held-out fidelity metric for one fold.

    Args:
        weights: Signal weight dict {signal_name: weight}.
        components: [n_pairs × 7] signal matrix (from replay store).
        gt_fidelity: [n_pairs] ground-truth fidelity (from fidelity_v2.jsonl).
            Values ∈ [0, 1]; typically 3.8% non-zero.
        fold_mask: Boolean array [n_pairs]; True = held-out validation.
        judge: "mock" (default) or "gemma3" (not implemented in Box V2).

    Returns:
        float ∈ [0, 1], higher = better.
    """
    if judge != "mock":
        raise NotImplementedError(
            f"judge={judge!r} is not implemented in Box V2 (mock phase). "
            "Run gemma3 validation separately on top-3 candidates."
        )

    importance = _apply_weights(components, weights)
    return _mock_fidelity(importance, gt_fidelity, fold_mask)


# ---------------------------------------------------------------------------
# Cross-validation sweep (for diagnostics / β grid sweep)
# ---------------------------------------------------------------------------

def cross_validate(
    weights_list: Sequence[dict[str, float]],
    components: np.ndarray,
    gt_fidelity: np.ndarray,
    folds: list[np.ndarray],
    judge: str = "mock",
) -> list[dict]:
    """Run k-fold CV for a list of weight dicts.

    Returns a list of result dicts (one per weights entry), each with:
        mean, std, folds (list of per-fold scores)
    """
    results = []
    for weights in weights_list:
        fold_scores = [
            eval_held_out_fidelity(weights, components, gt_fidelity, mask, judge)
            for mask in folds
        ]
        results.append({
            "weights": dict(weights),
            "mean": float(np.mean(fold_scores)),
            "std": float(np.std(fold_scores)),
            "folds": [float(s) for s in fold_scores],
        })
    return results


# ---------------------------------------------------------------------------
# Overfit detector
# ---------------------------------------------------------------------------

def detect_overfit(
    train_scores: list[float],
    held_out_scores: list[float],
    gap_threshold: float = 0.05,
    std_threshold: float = 0.03,
) -> dict:
    """Detect overfitting from train vs held-out fold scores.

    A gap > gap_threshold on ≥2 folds signals overfit-to-judge.
    std(held_out) > std_threshold signals fold instability.

    Returns dict with:
        overfit_detected (bool)
        unstable (bool)
        mean_gap (float)
        std_held_out (float)
        fold_gaps (list[float])
    """
    gaps = [t - h for t, h in zip(train_scores, held_out_scores)]
    overfit_detected = sum(g > gap_threshold for g in gaps) >= 2
    std_held_out = float(np.std(held_out_scores))
    return {
        "overfit_detected": overfit_detected,
        "unstable": std_held_out > std_threshold,
        "mean_gap": float(np.mean(gaps)),
        "std_held_out": std_held_out,
        "fold_gaps": [float(g) for g in gaps],
    }
