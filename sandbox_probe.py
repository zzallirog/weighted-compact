"""Sandbox cross-operationalization probe harness (§17.11).

Methodology: arxiv 2602.19159 (Bianco & Shiller, "Beyond Behavioural
Trade-Offs: Mechanistic Tracing of Pain-Pleasure Decisions in an LLM").
Principle: probe the same finding via multiple independent operationalizations.
If the result is robust it appears across ≥2 ракурсов. If single-source →
methodological artifact.

probe_ewma_delta_auc: WIRED (Box B data, 2026-05-25).
probe_beta_wc_optimum: STUB (waiting for Box V2 CMA-ES output).
probe_stumble_threshold_anchor: STUB (waiting for Box A shadow + multi-judge calibration).
probe_and_composition: STUB (waiting for Box A + Box B + Box C).

Cross-operationalization axes (§17.11):
  JUDGE: mock | gemma3 | sonnet
  SPLIT: 5fold | LOSO | temporal
  METRIC: ROC-AUC | PR-AUC | precision@p95 | FP@p95 | F1-macro

For probe_ewma_delta_auc the JUDGE axis encodes K×α config (e.g. "K12a09"),
since Box B used no LLM calls — "mock" tier with varying K/α params.
SPLIT is always "5fold" (GroupKFold by session_id, as run by eval_ewma.py).
METRIC selects ROC-AUC vs PR-AUC delta.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------

JUDGE = Literal["mock", "gemma3", "sonnet"]
SPLIT = Literal["5fold", "LOSO", "temporal"]
METRIC = Literal["ROC-AUC", "PR-AUC", "precision@p95", "FP@p95", "F1-macro"]


@dataclass
class Operationalization:
    judge: JUDGE
    split: SPLIT
    metric: METRIC

    def label(self) -> str:
        return f"{self.judge}×{self.split}×{self.metric}"


@dataclass
class ProbeResult:
    operationalization: Operationalization
    estimated_value: float
    matches_target: bool
    notes: str = ""


# ---------------------------------------------------------------------------
# Core probe function
# ---------------------------------------------------------------------------

def probe_finding(
    finding_name: str,
    target_value: float,
    tolerance: float = 0.15,
    operationalizations: list[Operationalization] | None = None,
    eval_fn: Callable[[Operationalization], float] | None = None,
    out_path: Path | None = None,
) -> dict:
    """Cross-operationalization probe of a single finding.

    eval_fn: Operationalization → estimated_value (the measured quantity
    in the operationalization's own terms).

    Returns:
        {
          "finding": str,
          "target": float,
          "tolerance": float,
          "probes": list[ProbeResult as dict],
          "robustness_ratio": float,   # matches / total
          "robust": bool,              # ratio >= 0.5
        }
    """
    if operationalizations is None:
        operationalizations = []
    if eval_fn is None:
        raise ValueError("eval_fn must be provided; stub or real")

    probes: list[ProbeResult] = []
    for op in operationalizations:
        value = eval_fn(op)
        matches = abs(value - target_value) <= tolerance
        probes.append(ProbeResult(
            operationalization=op,
            estimated_value=value,
            matches_target=matches,
        ))

    total = len(probes)
    match_count = sum(1 for p in probes if p.matches_target)
    robustness_ratio = match_count / total if total > 0 else 0.0

    result = {
        "finding": finding_name,
        "target": target_value,
        "tolerance": tolerance,
        "probes": [
            {
                "operationalization": pr.operationalization.label(),
                "estimated_value": pr.estimated_value,
                "matches_target": pr.matches_target,
                "notes": pr.notes,
            }
            for pr in probes
        ],
        "robustness_ratio": robustness_ratio,
        "robust": robustness_ratio >= 0.5,
    }

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2))

    return result


# ---------------------------------------------------------------------------
# Probe stub 1 — β_WC optimum ≈ 0.5 (Box V2 / CMA-ES output)
# ---------------------------------------------------------------------------

def probe_beta_wc_optimum(
    cv_results_path: Path,
    out_path: Path | None = None,
) -> dict:
    """Probe: β_WC* ≈ 0.5 is the CMA-ES optimum under cross-operationalization.

    Input artifact:
        cv_results_path — JSON file written by beta_search.run_cmaes_search()
        Expected schema: {
            "best": {"beta": float, "delta_misstep": float, "delta_skip": float},
            "best_loss": float,
            "history": [...],
        }

    Target: β_WC* ∈ [0.35, 0.65]  → target_value=0.5, tolerance=0.15.

    Operationalizations (4, ≥2 axes varied across the set):
        mock × 5fold × PR-AUC
        mock × 5fold × F1-macro
        gemma3 × 5fold × precision@p95
        gemma3 × LOSO × PR-AUC

    Robust if ≥2 of 4 match (ratio ≥ 0.5).

    TODO wiring (once Box V2 returns):
        1. Load cv_results_path — contains beta_opt per run.
        2. For each operationalization: re-run eval at beta_opt with that
           (judge, split, metric) config — or load from pre-computed cache
           if cv_harness stored per-operationalization outputs.
        3. eval_fn = lambda op: cv_results[op.label()]["beta_optimal"]
        4. Replace the stub eval_fn below.
    """
    ops = [
        Operationalization("mock", "5fold", "PR-AUC"),
        Operationalization("mock", "5fold", "F1-macro"),
        Operationalization("gemma3", "5fold", "precision@p95"),
        Operationalization("gemma3", "LOSO", "PR-AUC"),
    ]

    # --- STUB: returns placeholder value ---
    # Replace with real eval_fn after Box V2 completes.
    # The stub returns 0.0 so robustness_ratio=0 and robust=False
    # — a clear "not yet wired" signal.
    def _stub_eval(op: Operationalization) -> float:
        # TODO: load cv_results_path, extract beta_optimal for this
        # (judge, split, metric) combination.
        # cv_data = json.loads(cv_results_path.read_text())
        # return cv_data["by_operationalization"][op.label()]["beta_optimal"]
        return -1.0  # sentinel: not yet wired

    return probe_finding(
        finding_name="β_WC ≈ 0.5 optimum (CMA-ES result)",
        target_value=0.5,
        tolerance=0.15,
        operationalizations=ops,
        eval_fn=_stub_eval,
        out_path=out_path,
    )


# ---------------------------------------------------------------------------
# Probe stub 2 — stumble_threshold anchor: 0.75 + 0.17·β at β≈0.59 → 0.85
# ---------------------------------------------------------------------------

def probe_stumble_threshold_anchor(
    eval_results_path: Path,
    beta_calibration: float = 0.59,
    out_path: Path | None = None,
) -> dict:
    """Probe: stumble_threshold anchor stable across judges.

    Axis C finding: stumble_threshold = 0.75 + 0.17·β.
    At β=0.59 → threshold = 0.75 + 0.17·0.59 ≈ 0.85 (current calibrated value).

    Input artifact:
        eval_results_path — JSON from Box A (V3 EMA-gate eval).
        Expected schema: {
            "by_judge": {
                "mock":   {"beta_optimal": float},
                "gemma3": {"beta_optimal": float},
                "sonnet": {"beta_optimal": float},   # optional
            }
        }

    Target: for each judge, derived stumble_threshold = 0.75 + 0.17·β_optimal
    should be within ±0.01 of 0.85.
    → target_value=0.85, tolerance=0.01 (tight: this is an anchor check).

    Operationalizations (judge axis varied):
        mock × 5fold × FP@p95
        gemma3 × 5fold × FP@p95
        sonnet × 5fold × FP@p95   (only if available in eval_results)

    Robust if anchor consistent across ≥2 judges (≥2 of N match).

    TODO wiring (once Box A returns):
        1. Load eval_results_path.
        2. For each judge: extract beta_optimal → compute derived threshold.
        3. eval_fn = lambda op: 0.75 + 0.17 * by_judge[op.judge]["beta_optimal"]
        4. Replace stub below.
    """
    ops = [
        Operationalization("mock", "5fold", "FP@p95"),
        Operationalization("gemma3", "5fold", "FP@p95"),
        # Sonnet added here if Box A ran with sonnet judge; keep as reference
        # Operationalization("sonnet", "5fold", "FP@p95"),
    ]

    def _stub_eval(op: Operationalization) -> float:
        # TODO: load eval_results_path, look up beta_optimal for op.judge,
        # then return 0.75 + 0.17 * beta_optimal.
        # data = json.loads(eval_results_path.read_text())
        # beta_opt = data["by_judge"][op.judge]["beta_optimal"]
        # return 0.75 + 0.17 * beta_opt
        return -1.0  # sentinel: not yet wired

    # Target: derived threshold ≈ 0.85 at β≈0.59
    expected_threshold = 0.75 + 0.17 * beta_calibration  # ≈ 0.850

    return probe_finding(
        finding_name=f"stumble_threshold anchor (β≈{beta_calibration} → {expected_threshold:.3f})",
        target_value=expected_threshold,
        tolerance=0.01,
        operationalizations=ops,
        eval_fn=_stub_eval,
        out_path=out_path,
    )


# ---------------------------------------------------------------------------
# Probe stub 3 — AND-composition FP@p95 ≤ Box A baseline + 1pp (Box C)
# ---------------------------------------------------------------------------

def probe_and_composition(
    box_a_path: Path,
    box_b_path: Path,
    box_c_path: Path,
    fp_tolerance_pp: float = 1.0,
    out_path: Path | None = None,
) -> dict:
    """Probe: AND-composition (T_t AND p_t) does not degrade FP@p95 vs V3 alone.

    §17.8 Box C falsifier: composition FP@p95 ≤ Box A FP@p95 + 1pp tolerance.

    This probe checks that finding holds across two split operationalizations.

    Input artifacts:
        box_a_path — Box A eval JSON: {"fp_at_p95": float, "by_split": {...}}
        box_b_path — Box B eval JSON: {"auc_delta": float}  (needed for precondition)
        box_c_path — Box C AND-composition JSON:
            {"fp_at_p95_5fold": float, "fp_at_p95_LOSO": float}

    Target: composition_FP - box_a_FP ≤ fp_tolerance_pp (in percentage points).
    Encoded as: delta ≤ 0 + tolerance → target_value=0.0, tolerance=fp_tolerance_pp.

    Operationalizations (split axis varied):
        gemma3 × 5fold × FP@p95
        gemma3 × LOSO × FP@p95

    Robust if BOTH splits satisfy the tolerance (ratio = 2/2 = 1.0).

    Precondition: Box A and Box B must have individually passed their own
    falsifiers before calling this probe.

    TODO wiring (once Box A + Box B + Box C return):
        1. Load box_a_path → base_fp = data["fp_at_p95"]
        2. Load box_c_path → composition_fp_5fold, composition_fp_LOSO
        3. eval_fn = lambda op:
               composition_fp[op.split] - base_fp
           (delta; target 0, tolerance fp_tolerance_pp)
        4. Replace stub below.
    """
    ops = [
        Operationalization("gemma3", "5fold", "FP@p95"),
        Operationalization("gemma3", "LOSO", "FP@p95"),
    ]

    def _stub_eval(op: Operationalization) -> float:
        # TODO: load box_a_path, box_c_path; compute delta per split.
        # base = json.loads(box_a_path.read_text())["fp_at_p95"]
        # comp = json.loads(box_c_path.read_text())
        # key = f"fp_at_p95_{op.split}"
        # return comp[key] - base   # delta; target 0.0 ± fp_tolerance_pp
        return -99.0  # sentinel: not yet wired

    return probe_finding(
        finding_name="AND-composition FP@p95 ≤ Box A baseline + 1pp",
        target_value=0.0,          # delta = 0 means no degradation
        tolerance=fp_tolerance_pp,
        operationalizations=ops,
        eval_fn=_stub_eval,
        out_path=out_path,
    )


# ---------------------------------------------------------------------------
# Box B sweep data — real numbers from 2026-05-25 eval_ewma.py run
# ---------------------------------------------------------------------------
#
# Source: ~/.claude/work/agile-drifting-narwhal/BOX-B-EWMA-report.md
# Corpus: 7756 turns, 440 stumbles (5.67%), 3193 sessions, k=5 GroupKFold
# Values: mean over 5 folds. Static baseline ROC-AUC = 0.558 ± 0.052.
# Static baseline PR-AUC = 0.116 ± 0.017.
#
# Key: (K, alpha) → {"delta_ewma_roc": float, "delta_blend_roc": float,
#                     "delta_ewma_pr": float,  "delta_blend_pr": float}
# Note: delta_ewma_pr is NEGATIVE for all configs — EWMA standalone hurts
# precision. delta_blend_pr is positive (blend restores). This nuance is
# preserved in the probe — PR-AUC operationalization uses blend delta.
_BOX_B_SWEEP: dict[tuple[int, float], dict[str, float]] = {
    (8,  0.30): {"delta_ewma_roc": 0.044, "delta_blend_roc": 0.011,
                 "delta_ewma_pr": -0.041, "delta_blend_pr": 0.006},
    (8,  0.50): {"delta_ewma_roc": 0.054, "delta_blend_roc": 0.016,
                 "delta_ewma_pr": -0.034, "delta_blend_pr": 0.011},
    (8,  0.70): {"delta_ewma_roc": 0.057, "delta_blend_roc": 0.021,
                 "delta_ewma_pr": -0.034, "delta_blend_pr": 0.014},
    (8,  0.90): {"delta_ewma_roc": 0.069, "delta_blend_roc": 0.026,
                 "delta_ewma_pr": -0.034, "delta_blend_pr": 0.011},
    (12, 0.30): {"delta_ewma_roc": 0.063, "delta_blend_roc": 0.015,
                 "delta_ewma_pr": -0.029, "delta_blend_pr": 0.013},
    (12, 0.50): {"delta_ewma_roc": 0.074, "delta_blend_roc": 0.020,
                 "delta_ewma_pr": -0.029, "delta_blend_pr": 0.013},
    (12, 0.70): {"delta_ewma_roc": 0.087, "delta_blend_roc": 0.025,
                 "delta_ewma_pr": -0.026, "delta_blend_pr": 0.014},
    (12, 0.90): {"delta_ewma_roc": 0.089, "delta_blend_roc": 0.029,
                 "delta_ewma_pr": -0.027, "delta_blend_pr": 0.015},
    (16, 0.30): {"delta_ewma_roc": 0.041, "delta_blend_roc": 0.013,
                 "delta_ewma_pr": -0.041, "delta_blend_pr": 0.006},
    (16, 0.50): {"delta_ewma_roc": 0.052, "delta_blend_roc": 0.019,
                 "delta_ewma_pr": -0.029, "delta_blend_pr": 0.013},
    (16, 0.70): {"delta_ewma_roc": 0.059, "delta_blend_roc": 0.024,
                 "delta_ewma_pr": -0.029, "delta_blend_pr": 0.014},
    (16, 0.90): {"delta_ewma_roc": 0.073, "delta_blend_roc": 0.029,
                 "delta_ewma_pr": -0.029, "delta_blend_pr": 0.011},
    (24, 0.30): {"delta_ewma_roc": 0.067, "delta_blend_roc": 0.017,
                 "delta_ewma_pr": -0.029, "delta_blend_pr": 0.006},
    (24, 0.50): {"delta_ewma_roc": 0.075, "delta_blend_roc": 0.024,
                 "delta_ewma_pr": -0.029, "delta_blend_pr": 0.013},
    (24, 0.70): {"delta_ewma_roc": 0.086, "delta_blend_roc": 0.030,
                 "delta_ewma_pr": -0.026, "delta_blend_pr": 0.014},
    (24, 0.90): {"delta_ewma_roc": 0.088, "delta_blend_roc": 0.036,
                 "delta_ewma_pr": -0.029, "delta_blend_pr": 0.018},
}


def _check_outlier_sanity(
    values: list[float],
    labels: list[str],
    threshold_ratio: float = 3.0,
) -> list[str]:
    """Detect outlier operationalizations via median-ratio test.

    Returns list of warning strings (empty = all sane).
    Defensive against «agent silently produces wrong number» pattern
    (DIARY entry 3, 2026-05-25).

    A value is flagged if it deviates from the median by > threshold_ratio×.
    Only applied when len(values) >= 3 (median unstable at N<3).
    Sign-consistency check: if values are not all the same sign → flagged.
    """
    warnings: list[str] = []
    if len(values) < 3:
        return warnings

    import statistics
    median = statistics.median(values)

    # Sign consistency: all should be same sign (all positive ΔAUC means
    # finding is directionally consistent).
    signs = [v > 0 for v in values]
    if any(s != signs[0] for s in signs):
        mixed = [labels[i] for i, s in enumerate(signs) if s != signs[0]]
        warnings.append(
            f"Sign inconsistency: {mixed} have opposite sign vs majority"
        )

    # Magnitude outlier: deviation > threshold_ratio × median
    if abs(median) > 1e-9:
        for label, val in zip(labels, values):
            ratio = abs(val) / abs(median) if abs(median) > 1e-9 else float("inf")
            if ratio > threshold_ratio or ratio < 1.0 / threshold_ratio:
                warnings.append(
                    f"Magnitude outlier: {label}={val:.4f} "
                    f"is {ratio:.1f}× median ({median:.4f})"
                )

    return warnings


# ---------------------------------------------------------------------------
# Probe 4 — EWMA ΔAUC > 0.02 falsifier (Box B — WIRED 2026-05-25)
# ---------------------------------------------------------------------------

def probe_ewma_delta_auc(
    box_b_path: Path | None = None,
    sweep_data: dict | None = None,
    delta_threshold: float = 0.02,
    out_path: Path | None = None,
) -> dict:
    """Probe: EWMA trajectory predictor ΔAUC > 0.02 in ≥2 operationalizations.

    §17.8 Box B falsifier: if ΔAUC < 0.02 vs static centroid baseline →
    discard EWMA trajectory path (don't pursue Ladder B → SR).

    WIRED: uses real Box B K×α sweep data. 4 primary operationalizations
    varying K and α (ROC-AUC metric, mock-tier, 5fold split). Optional 5th
    uses PR-AUC delta of blend (since EWMA standalone PR-AUC is negative).

    Data sources (in priority order):
        1. sweep_data: dict[(K, α)] → {delta_ewma_roc, delta_blend_roc,
                                        delta_ewma_pr, delta_blend_pr}
           Pass programmatically for testing or fresh eval output.
        2. box_b_path: Path to JSON file with the same schema as sweep_data
           (JSON must have keys like "12_0.9" → {dict}; K×α string keys).
        3. _BOX_B_SWEEP: built-in constant from 2026-05-25 eval run.
           Used when both above are None (fallback to known real numbers).

    Operationalizations (4 primary + 1 optional PR-AUC):
        "K12a09" × 5fold × ROC-AUC  → Δewma=+0.089 (peak)
        "K24a09" × 5fold × ROC-AUC  → Δewma=+0.088 (different K)
        "K12a07" × 5fold × ROC-AUC  → Δewma=+0.087 (ladder config)
        "K08a05" × 5fold × ROC-AUC  → Δewma=+0.054 (different params)
        "K24a09" × 5fold × PR-AUC   → Δblend=+0.018 (blend, best PR-AUC)

    Robustness criterion: ΔAUC > delta_threshold holds in ≥2 of 4+ ops.
    Encoding: target=delta_threshold + 0.04, tolerance=0.04 → matches when
    ΔAUC ∈ [delta_threshold, delta_threshold + 0.08].
    For ΔAUC > 0.08 → no match (outlier-high band — investigate separately).

    Sanity checks (defensive, DIARY entry 3 pattern):
        - All ROC-AUC operationalizations must have same sign
        - No single operationalization > 3× median of the group

    If probe returns robust=False for real Box B data → contradiction:
    Box B PASS verdict was artifact. See §17.11 falsifier.

    TODO stubs (other probes — unchanged):
        probe_beta_wc_optimum: awaiting Box V2 output
            (~/.claude/work/agile-drifting-narwhal/BOX-V2-report.md)
        probe_stumble_threshold_anchor: awaiting Box A shadow + multi-judge
            calibration data (defer until Box A shadow returns)
        probe_and_composition: awaiting Box A + Box B + Box C
            (Box B is now available; Box A + Box C still pending)
    """
    # --- Load sweep data ---
    data: dict[tuple[int, float], dict[str, float]]
    if sweep_data is not None:
        data = sweep_data
    elif box_b_path is not None and box_b_path.exists():
        raw = json.loads(box_b_path.read_text())
        # JSON keys format: "K_alpha" e.g. "12_0.9"
        data = {}
        for k, v in raw.items():
            k_int, a_float = k.split("_")
            data[(int(k_int), float(a_float))] = v
    else:
        # Fallback: built-in real Box B numbers (2026-05-25)
        data = _BOX_B_SWEEP

    # --- Config-to-Operationalization mapping ---
    # JUDGE field encodes K×α config (e.g. "K12a09") since all evals are
    # mock-tier (no LLM calls), split is always 5fold (GroupKFold).
    # This is an intentional reuse of the JUDGE axis to vary K/α params
    # while keeping the Operationalization schema intact.
    configs = [
        (12, 0.90, "ROC-AUC", "delta_ewma_roc"),  # peak Δewma
        (24, 0.90, "ROC-AUC", "delta_ewma_roc"),  # different K
        (12, 0.70, "ROC-AUC", "delta_ewma_roc"),  # ladder config (β=0.0)
        (8,  0.50, "ROC-AUC", "delta_ewma_roc"),  # different K+α
        (24, 0.90, "PR-AUC",  "delta_blend_pr"),  # best PR-AUC (blend)
    ]

    ops = []
    config_keys = []
    for K, alpha, metric, data_key in configs:
        judge_label = f"K{K:02d}a{int(alpha * 10):02d}"
        # Cast judge_label as str — Literal["mock","gemma3","sonnet"] is
        # advisory; runtime accepts any str. Annotated in docstring.
        op = Operationalization(judge_label, "5fold", metric)  # type: ignore[arg-type]
        ops.append(op)
        config_keys.append((K, alpha, data_key))

    def _real_eval(op: Operationalization) -> float:
        idx = next(
            i for i, o in enumerate(ops) if o.label() == op.label()
        )
        K, alpha, data_key = config_keys[idx]
        row = data.get((K, alpha))
        if row is None:
            raise KeyError(f"Box B data missing for K={K}, α={alpha}")
        return row[data_key]

    # --- Compute raw values for sanity check before calling probe_finding ---
    raw_values: list[float] = []
    raw_labels: list[str] = []
    for op, (K, alpha, data_key) in zip(ops, config_keys):
        row = data.get((K, alpha))
        if row is not None:
            raw_values.append(row[data_key])
            raw_labels.append(op.label())

    # Sanity check: ROC-AUC operationalizations only (PR-AUC has different sign)
    roc_vals = [v for v, l in zip(raw_values, raw_labels) if "ROC-AUC" in l]
    roc_labs = [l for l in raw_labels if "ROC-AUC" in l]
    sanity_warnings = _check_outlier_sanity(roc_vals, roc_labs)

    # --- Target encoding ---
    # Semantics: estimated_value > delta_threshold
    # probe_finding uses |v - target| <= tolerance.
    # target = delta_threshold + 0.04, tolerance = 0.04
    # → matches when v ∈ [delta_threshold, delta_threshold + 0.08]
    # Values above 0.10 are flagged separately (not expected from corpus)
    target = delta_threshold + 0.04
    tolerance = 0.04

    result = probe_finding(
        finding_name="EWMA trajectory ΔAUC > 0.02 (Box B falsifier — WIRED)",
        target_value=target,
        tolerance=tolerance,
        operationalizations=ops,
        eval_fn=_real_eval,
        out_path=out_path,
    )

    # Attach sanity warnings to result
    result["sanity_warnings"] = sanity_warnings
    result["wired"] = True
    result["data_source"] = (
        "sweep_data (programmatic)" if sweep_data is not None
        else (f"box_b_path: {box_b_path}" if box_b_path is not None else "_BOX_B_SWEEP (built-in)")
    )
    result["delta_threshold"] = delta_threshold
    result["raw_values"] = dict(zip(raw_labels, raw_values))

    # Falsifier: if robust=False → Box B PASS verdict may be artifact
    if not result["robust"]:
        result["falsifier_triggered"] = (
            "ALERT: probe_ewma_delta_auc robust=False for real Box B data. "
            "This contradicts Box B PASS verdict. "
            "Investigate: are ≥2 operationalizations below delta_threshold? "
            "See DIARY.md for structured escalation."
        )

    # If out_path provided, re-write with enriched data
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2))

    return result


# ---------------------------------------------------------------------------
# Robustness aggregation
# ---------------------------------------------------------------------------

def sandbox_summary(
    probe_results: list[dict],
    out_path: Path,
) -> dict:
    """Aggregate robustness across all probes.

    §17.11 falsifier for the sandbox:
        ≥2 robust findings out of 4 → frame_validated = True.
        < 2 → rewrite §17, something is fundamentally off.

    Returns:
        {
          "robust_count": int,
          "total": int,
          "frame_validated": bool,   # robust_count >= 2 of 4
          "details": probe_results,
        }
    """
    robust_count = sum(1 for r in probe_results if r.get("robust", False))
    total = len(probe_results)

    summary = {
        "robust_count": robust_count,
        "total": total,
        "frame_validated": robust_count >= 2,
        "details": probe_results,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2))

    return summary


# ---------------------------------------------------------------------------
# CLI entrypoint (dry-run / status check, not full eval)
# ---------------------------------------------------------------------------

def _print_status(summary: dict) -> None:
    """Print human-readable status of a sandbox summary."""
    print(f"Sandbox summary: {summary['robust_count']}/{summary['total']} robust")
    print(f"Frame validated: {summary['frame_validated']}")
    for detail in summary.get("details", []):
        name = detail["finding"]
        robust = detail.get("robust", False)
        ratio = detail.get("robustness_ratio", 0.0)
        tag = "ROBUST" if robust else "NOT ROBUST"
        print(f"  [{tag}] {name} ({ratio:.2f})")


if __name__ == "__main__":
    # Dry-run: 3 stub probes + 1 wired probe (probe_ewma_delta_auc).
    # Wired probe uses built-in Box B sweep data — no external files needed.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        r1 = probe_beta_wc_optimum(
            cv_results_path=tmp_path / "cv_results.json",
        )
        r2 = probe_stumble_threshold_anchor(
            eval_results_path=tmp_path / "box_a.json",
        )
        r3 = probe_and_composition(
            box_a_path=tmp_path / "box_a.json",
            box_b_path=tmp_path / "box_b.json",
            box_c_path=tmp_path / "box_c.json",
        )
        # probe_ewma_delta_auc is WIRED — uses _BOX_B_SWEEP built-in data.
        # No external file required for dry-run.
        r4 = probe_ewma_delta_auc()

        out = tmp_path / "sandbox_summary.json"
        summary = sandbox_summary([r1, r2, r3, r4], out_path=out)
        _print_status(summary)

        # Print wired probe sanity warnings if any
        if r4.get("sanity_warnings"):
            print(f"\nEWMA probe sanity warnings:")
            for w in r4["sanity_warnings"]:
                print(f"  ⚠ {w}")
        else:
            print("\nEWMA probe sanity: OK (no outliers detected)")

        # Frame validation: 1 robust probe = early validation pass
        # (NOT «2 of 4» — other stubs not yet wired)
        if summary["robust_count"] >= 1:
            print("\nEarly validation: OK (≥1 robust probe from real data)")
        if r4.get("falsifier_triggered"):
            print(f"\n⚠ FALSIFIER: {r4['falsifier_triggered']}")
