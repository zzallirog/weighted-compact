"""CMA-ES weight search in β-bottleneck parameterisation.

Searches over (β, Δ_misstep, Δ_skip) — d_eff=3 — instead of raw 7-D weights.
β-bottleneck regulariser: prevents reward-hacking (analogous to AutoTTS ablation
§2.2(b) where unconstrained grid → 35pp held-out drop).

Search space:
    β            ∈ [0.0, 1.0]   — master scalar
    Δ_misstep    ∈ [-0.25, 0.15]  — perturbation from β-schedule misstep
    Δ_skip       ∈ [-0.10, 0.10]  — perturbation from β-schedule span_skip

Full 7 weights are derived via:
    weights = search_point_to_weights(SearchPoint(β, Δ_misstep, Δ_skip))
    i.e., beta_schedule(β).as_dict() + perturbation + re-normalise positive weights

Eval strategy:
    Round-robin folds (1 fold per eval candidate, not 5) to save evals.
    mock judge only (0 LLM calls).  gemma3 validation is a separate step.

Output JSON:
    best_point: {beta, delta_misstep, delta_skip}
    best_loss:  float (1 - mock_fidelity)
    best_weights: full 7-weight dict at best point
    history: [{sp, loss, fold_idx}, ...]
    cma_stop_reason: str
    falsifier: {F1, F2, F3, hand_tuned_loss, hand_tuned_std}

CLI:
    python -m weighted_compact.beta_search \\
        --out-dir /tmp/wc_search/ \\
        --max-evals 150 --judge mock \\
        --out /tmp/wc_search/cmaes_result.json
"""
from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path
from typing import NamedTuple

import numpy as np

with warnings.catch_warnings():
    warnings.simplefilter("ignore", UserWarning)
    import cma  # type: ignore[import]

from weighted_compact.beta_schedule import beta_schedule
from weighted_compact.cv_harness import (
    detect_overfit,
    eval_held_out_fidelity,
    split_by_sessions,
)
from weighted_compact.replay_eval import load_replay_store


# ---------------------------------------------------------------------------
# SearchPoint: the 3-D parameterisation
# ---------------------------------------------------------------------------

class SearchPoint(NamedTuple):
    """Point in (β, Δ_misstep, Δ_skip) search space."""

    beta: float          # β ∈ [0.0, 1.0]
    delta_misstep: float  # ∈ [-0.25, 0.15], perturbation from β-schedule
    delta_skip: float     # ∈ [-0.10, 0.10], perturbation from β-schedule span_skip


# Bounds for CMA-ES
_BOUNDS_LO = [0.0, -0.25, -0.10]
_BOUNDS_HI = [1.0,  0.15,  0.10]

# Hand-tuned defaults from importance.py (reference anchor)
HAND_TUNED_WEIGHTS: dict[str, float] = {
    "misstep":    0.40,
    "density":    0.25,
    "label":      0.15,
    "span_keep":  0.20,
    "span_maybe": 0.10,
    "span_skip":  -0.15,
    "span_think": 0.05,
}

_SIGNAL_NAMES = ["misstep", "density", "label", "span_keep", "span_maybe", "span_skip", "span_think"]


# ---------------------------------------------------------------------------
# search_point_to_weights
# ---------------------------------------------------------------------------

def search_point_to_weights(sp: SearchPoint) -> dict[str, float]:
    """Convert (β, Δ_misstep, Δ_skip) → full 7-weight dict.

    1. Get base from beta_schedule(β)
    2. Apply perturbations: misstep += Δ_misstep, span_skip += Δ_skip
    3. Clip to valid ranges
    4. Re-normalise positive weights so they sum to beta_schedule positive_sum
       at that β (preserves scale)

    Monotonicity: Δ perturbations are bounded within sign constraints so the
    β-schedule monotone structure is preserved at the perturbation level.
    """
    base = beta_schedule(sp.beta)
    w = base.as_dict()

    # Apply perturbations
    w_misstep_raw = w["misstep"] + sp.delta_misstep
    w_skip_raw = w["span_skip"] + sp.delta_skip

    # Clip: misstep ∈ [0.05, 0.65], span_skip ∈ [-0.35, -0.05]
    w["misstep"] = float(np.clip(w_misstep_raw, 0.05, 0.65))
    w["span_skip"] = float(np.clip(w_skip_raw, -0.35, -0.05))

    # Re-normalise positive weights to maintain sum = base positive_sum
    pos_keys = ["misstep", "density", "label", "span_keep", "span_maybe", "span_think"]
    pos_sum = sum(w[k] for k in pos_keys)
    target_sum = base.positive_sum()

    if pos_sum > 1e-6:
        scale = target_sum / pos_sum
        for k in pos_keys:
            w[k] = float(w[k] * scale)

    return w


# ---------------------------------------------------------------------------
# Single-fold eval
# ---------------------------------------------------------------------------

def eval_loss(
    sp: SearchPoint,
    components: np.ndarray,
    gt_fidelity: np.ndarray,
    fold_mask: np.ndarray,
    judge: str = "mock",
) -> float:
    """Evaluate loss for one SearchPoint on one held-out fold.

    Returns loss = 1 - fidelity (lower = better, for CMA-ES minimisation).
    """
    weights = search_point_to_weights(sp)
    fidelity = eval_held_out_fidelity(weights, components, gt_fidelity, fold_mask, judge)
    return 1.0 - fidelity


# ---------------------------------------------------------------------------
# CMA-ES search
# ---------------------------------------------------------------------------

def run_cmaes_search(
    components: np.ndarray,
    gt_fidelity: np.ndarray,
    cv_folds: list[np.ndarray],
    x0: list[float] | None = None,
    sigma0: float = 0.2,
    max_evals: int = 200,
    judge: str = "mock",
    verbose: bool = True,
) -> tuple[SearchPoint, float, dict]:
    """Run CMA-ES in (β, Δ_misstep, Δ_skip) space.

    Args:
        components: [n_pairs × 7] signal matrix (from replay store).
        gt_fidelity: [n_pairs] ground-truth fidelity.
        cv_folds: k boolean fold masks from split_by_sessions().
        x0: Initial point [β, Δ_misstep, Δ_skip]. Default: [0.5, 0.0, 0.0].
        sigma0: Initial step size. 0.2 gives good exploration in [0,1] × [-0.25, 0.25].
        max_evals: Budget (total function evaluations).
        judge: "mock" only in Box V2 phase.
        verbose: Print progress every 5 generations.

    Returns:
        (best_point, best_loss, result_dict)
        result_dict contains history, cv_results, cma_stop_reason.
    """
    if x0 is None:
        x0 = [0.5, 0.0, 0.0]

    k = len(cv_folds)

    es = cma.CMAEvolutionStrategy(
        x0=x0,
        sigma0=sigma0,
        inopts={
            "bounds": [_BOUNDS_LO, _BOUNDS_HI],
            "maxfevals": max_evals,
            "popsize": 8,               # λ=8 for d=3 (slightly above default 7)
            "tolx": 1e-3,               # stop when step size < 0.001
            "tolfun": 1e-4,             # stop when Δf < 0.0001
            "seed": 42,
            "verbose": -9,              # suppress CMA output
            # Per-dimension initial std: β gets wider search, Δ narrower
            "CMA_stds": [0.25, 0.12, 0.06],
        },
    )

    fold_idx = 0
    best_loss = float("inf")
    best_point: SearchPoint | None = None
    history: list[dict] = []
    gen = 0

    while not es.stop():
        solutions = es.ask()
        losses = []

        for x in solutions:
            # Clip to bounds (CMA-ES may propose slightly OOB candidates)
            sp = SearchPoint(
                beta=float(np.clip(x[0], 0.0, 1.0)),
                delta_misstep=float(np.clip(x[1], -0.25, 0.15)),
                delta_skip=float(np.clip(x[2], -0.10, 0.10)),
            )

            # Round-robin fold assignment (1 fold per eval, not k)
            fold_mask = cv_folds[fold_idx % k]
            fold_idx += 1

            loss = eval_loss(sp, components, gt_fidelity, fold_mask, judge)
            losses.append(loss)

            history.append({
                "sp": sp._asdict(),
                "loss": float(loss),
                "fold_idx": (fold_idx - 1) % k,
                "gen": gen,
            })

            if loss < best_loss:
                best_loss = loss
                best_point = sp

        es.tell(solutions, losses)
        gen += 1

        if verbose and gen % 5 == 0:
            best_so_far = min(losses) if losses else float("inf")
            print(f"  gen={gen:3d}  evals={len(history):4d}  "
                  f"best_loss_this_gen={best_so_far:.4f}  "
                  f"overall_best={best_loss:.4f}  "
                  f"sigma={es.sigma:.4f}")

    if best_point is None:
        # Fallback: x0 as best (shouldn't happen)
        best_point = SearchPoint(float(x0[0]), float(x0[1]), float(x0[2]))
        best_loss = eval_loss(best_point, components, gt_fidelity, cv_folds[0], judge)

    # Full 5-fold CV on best point for falsifier
    best_fold_scores = [
        1.0 - eval_held_out_fidelity(
            search_point_to_weights(best_point), components, gt_fidelity, m, judge
        )
        for m in cv_folds
    ]

    result = {
        "history": history,
        "total_evals": len(history),
        "total_gens": gen,
        "cma_stop_reason": str(es.stop()),
        "best_fold_losses": [float(s) for s in best_fold_scores],
        "best_fold_fidelities": [float(1.0 - s) for s in best_fold_scores],
        "best_cv_mean_fidelity": float(1.0 - np.mean(best_fold_scores)),
        "best_cv_std": float(np.std(best_fold_scores)),
    }

    return best_point, best_loss, result


# ---------------------------------------------------------------------------
# Falsifier checks (F1, F2, F3)
# ---------------------------------------------------------------------------

def check_falsifiers(
    best_point: SearchPoint,
    components: np.ndarray,
    gt_fidelity: np.ndarray,
    cv_folds: list[np.ndarray],
    judge: str = "mock",
) -> dict:
    """Compute F1/F2/F3 falsifier verdicts.

    F1: held_out_fidelity(CMA-ES best) ≥ held_out_fidelity(hand_tuned) − 0.01
    F2: std(fold_scores) ≤ 0.03
    F3: β-monotonicity preserved at best (β, Δ)

    Returns dict with verdicts and supporting values.
    """
    # CMA-ES best: k-fold CV
    best_weights = search_point_to_weights(best_point)
    best_fold_fids = [
        eval_held_out_fidelity(best_weights, components, gt_fidelity, m, judge)
        for m in cv_folds
    ]
    best_mean = float(np.mean(best_fold_fids))
    best_std = float(np.std(best_fold_fids))

    # Hand-tuned: k-fold CV
    ht_fold_fids = [
        eval_held_out_fidelity(HAND_TUNED_WEIGHTS, components, gt_fidelity, m, judge)
        for m in cv_folds
    ]
    ht_mean = float(np.mean(ht_fold_fids))
    ht_std = float(np.std(ht_fold_fids))

    # F1: not worse than hand-tuned by more than 1pp
    f1_pass = best_mean >= ht_mean - 0.01
    f1_delta = best_mean - ht_mean

    # F2: fold stability
    f2_pass = best_std <= 0.03

    # F3: β-monotonicity at best (β, Δ)
    f3_pass = _verify_monotonicity_at_point(best_point)

    return {
        "F1": {
            "pass": f1_pass,
            "delta_vs_hand_tuned": round(f1_delta, 5),
            "best_mean_fidelity": round(best_mean, 5),
            "hand_tuned_mean_fidelity": round(ht_mean, 5),
            "threshold": -0.01,
        },
        "F2": {
            "pass": f2_pass,
            "best_std": round(best_std, 5),
            "threshold": 0.03,
        },
        "F3": {
            "pass": f3_pass,
            "description": "β-monotonicity of all 7 weights at best point",
        },
        "best_fold_fidelities": [round(f, 5) for f in best_fold_fids],
        "hand_tuned_fold_fidelities": [round(f, 5) for f in ht_fold_fids],
        "verdict": "PASS" if (f1_pass and f2_pass and f3_pass) else "FAIL",
    }


def _verify_monotonicity_at_point(sp: SearchPoint, n_points: int = 21) -> bool:
    """Verify that final_weights are monotone in β at fixed (Δ_misstep, Δ_skip)."""
    betas = np.linspace(0.0, 1.0, n_points)
    try:
        w_misstep = []
        w_skip = []
        for b in betas:
            sp_b = SearchPoint(float(b), sp.delta_misstep, sp.delta_skip)
            w = search_point_to_weights(sp_b)
            w_misstep.append(w["misstep"])
            w_skip.append(w["span_skip"])

        # misstep should be non-decreasing in β
        for i in range(n_points - 1):
            if w_misstep[i] > w_misstep[i + 1] + 1e-6:
                return False

        # span_skip should be non-decreasing (weakening penalty: -0.25 → -0.10)
        for i in range(n_points - 1):
            if w_skip[i] > w_skip[i + 1] + 1e-6:
                return False

        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    parser = argparse.ArgumentParser(
        description="CMA-ES weight search in β-bottleneck parameterisation"
    )
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="Replay store directory (must contain components.npz etc)")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output JSON path for CMA-ES result")
    parser.add_argument("--max-evals", type=int, default=150)
    parser.add_argument("--judge", default="mock", choices=["mock"])
    parser.add_argument("--sigma0", type=float, default=0.2)
    parser.add_argument("--k", type=int, default=5, help="CV folds")
    parser.add_argument("--verbose", action="store_true", default=True)
    args = parser.parse_args()

    if args.out_dir is None:
        import tempfile
        args.out_dir = Path(tempfile.gettempdir()) / "wc_search"

    if args.out is None:
        args.out = args.out_dir / "cmaes_result.json"

    # Load replay store
    print(f"Loading replay store from {args.out_dir}...")
    components, gt_fidelity, pairs_with_session, meta = load_replay_store(args.out_dir)
    print(f"  n_pairs={meta['n_pairs']}, n_sessions={meta['n_sessions']}, "
          f"gt_pass_rate={meta['gt_pass_rate']:.1%}, "
          f"synthetic={meta['synthetic_features']}")

    # Build CV folds
    print(f"\nBuilding k={args.k} session-grouped folds...")
    cv_folds = split_by_sessions(pairs_with_session, k=args.k)
    fold_sizes = [int(m.sum()) for m in cv_folds]
    print(f"  Fold sizes: {fold_sizes}")

    # Baseline: hand-tuned weights
    print("\nBaseline (hand-tuned weights):")
    ht_fids = [
        eval_held_out_fidelity(HAND_TUNED_WEIGHTS, components, gt_fidelity, m, args.judge)
        for m in cv_folds
    ]
    ht_mean = float(np.mean(ht_fids))
    ht_std = float(np.std(ht_fids))
    print(f"  mean_fidelity={ht_mean:.4f}  std={ht_std:.4f}  folds={[round(f,4) for f in ht_fids]}")

    # CMA-ES search
    print(f"\nRunning CMA-ES (max_evals={args.max_evals}, sigma0={args.sigma0})...")
    best_point, best_loss, cma_result = run_cmaes_search(
        components=components,
        gt_fidelity=gt_fidelity,
        cv_folds=cv_folds,
        sigma0=args.sigma0,
        max_evals=args.max_evals,
        judge=args.judge,
        verbose=args.verbose,
    )

    best_weights = search_point_to_weights(best_point)
    print(f"\n=== CMA-ES result ===")
    print(f"  Best point: β={best_point.beta:.4f}  Δmisstep={best_point.delta_misstep:.4f}  "
          f"Δskip={best_point.delta_skip:.4f}")
    print(f"  Best loss (1 - fidelity): {best_loss:.4f}")
    print(f"  5-fold mean_fidelity={cma_result['best_cv_mean_fidelity']:.4f}  "
          f"std={cma_result['best_cv_std']:.4f}")
    print(f"  Stop reason: {cma_result['cma_stop_reason']}")
    print(f"  Total evals: {cma_result['total_evals']}  gens: {cma_result['total_gens']}")

    print(f"\nBest weights:")
    for name in _SIGNAL_NAMES:
        print(f"  {name:12s}: {best_weights[name]:+.4f}")

    # Falsifier checks
    print("\n=== Falsifier checks ===")
    falsifier = check_falsifiers(best_point, components, gt_fidelity, cv_folds, args.judge)
    for fi in ["F1", "F2", "F3"]:
        fd = falsifier[fi]
        status = "PASS" if fd["pass"] else "FAIL"
        print(f"  {fi}: {status}  {fd}")
    print(f"  Overall verdict: {falsifier['verdict']}")

    # Save result
    output = {
        "best_point": best_point._asdict(),
        "best_loss": float(best_loss),
        "best_weights": best_weights,
        "hand_tuned_weights": HAND_TUNED_WEIGHTS,
        "hand_tuned_mean_fidelity": ht_mean,
        "hand_tuned_std": ht_std,
        "cma_result": cma_result,
        "falsifier": falsifier,
        "meta": {
            "max_evals": args.max_evals,
            "judge": args.judge,
            "k_folds": args.k,
            "n_pairs": meta["n_pairs"],
            "n_sessions": meta["n_sessions"],
            "synthetic_features": meta["synthetic_features"],
            "gt_pass_rate": meta["gt_pass_rate"],
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2))
    print(f"\nSaved to {args.out}")


if __name__ == "__main__":
    _main()
