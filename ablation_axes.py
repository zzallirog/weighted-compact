#!/usr/bin/env python3
"""Category-collapse ablation for the WC importance mixture.

Motivation: docs/architecture.md#presence-profile — four architectural
categories (internal / gravity / dynamics / membrane) contribute to the
seven-signal importance vector.  Zeroing each while holding others fixed
measures which axes actually move fidelity.

Cells: baseline (unmodified) | no_internal (misstep=0,density=0) |
       no_gravity (span_keep/maybe/skip=0) | no_dynamics (span_think=0) |
       no_membrane (label=0)

REM-decay note: span_think is zeroed by no_dynamics, but the wall-clock
rem_decay.npz multiplier is NOT controlled here — it operates outside the
weight vector and requires a separate run_eval(rem_decay=True) pass.

Outputs:
  ablation_axes_summary.json   per-cell {n_pairs, mean, sd, ci_95, delta, sign_agr}
  ablation_axes_results.jsonl  per-pair-per-cell raw scores + provenance
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

import numpy as np

from weighted_compact import config
from weighted_compact.importance import WEIGHTS
from weighted_compact.recon_qa.context import build_compacted_context, load_pairs, load_topic_map
from weighted_compact.recon_qa.fidelity import load_qa_set
from weighted_compact.recon_qa.generator import ask_ollama
from weighted_compact.recon_qa.judge import llm_judge, score

ALL_CELLS: dict[str, dict[str, float]] = {
    "baseline":    {},
    "no_internal": {"misstep": 0.0, "density": 0.0},
    "no_gravity":  {"span_keep": 0.0, "span_maybe": 0.0, "span_skip": 0.0},
    "no_dynamics": {"span_think": 0.0},
    "no_membrane": {"label": 0.0},
}

_COMPONENT_ORDER = ["misstep", "density", "label", "span_keep", "span_maybe", "span_skip", "span_think"]


def _cell_weights(overrides: dict[str, float]) -> dict[str, float]:
    w = dict(WEIGHTS)
    w.update(overrides)
    return w


def _load_components() -> tuple[np.ndarray, np.ndarray] | None:
    p = config.importance_path()
    if not p.exists():
        return None
    npz = np.load(p, allow_pickle=True)
    return npz["components"], npz["pair_indices"]


def _apply_weights(components: np.ndarray, pair_indices: np.ndarray,
                   weights: dict[str, float]) -> dict[int, float]:
    """Recompute importance from components [N×7] → dict pair_idx → score."""
    w_vec = np.array([weights.get(k, 0.0) for k in _COMPONENT_ORDER], dtype=np.float32)
    imp = np.clip(components @ w_vec, 0.0, 1.0).astype(np.float32)
    return {int(pair_indices[i]): float(imp[i]) for i in range(len(imp))}


def _stratified_sample(qa: list[dict], n: int, seed: int,
                        components: np.ndarray | None,
                        pair_indices: np.ndarray | None) -> list[dict]:
    """Seeded sample stratified by misstep tertile when components available."""
    rng = random.Random(seed)
    if components is None or pair_indices is None or not qa:
        shuffled = list(qa); rng.shuffle(shuffled); return shuffled[:n]

    col = components[:, 0].astype(float)
    t1, t2 = float(np.percentile(col, 33.3)), float(np.percentile(col, 66.7))

    def _t(e: dict) -> int:
        pid = e.get("source_pair_idx", -1)
        idx = np.where(pair_indices == pid)[0]
        if not len(idx):
            return 1
        v = float(components[idx[0], 0])
        return 0 if v <= t1 else (1 if v <= t2 else 2)

    buckets: list[list[dict]] = [[], [], []]
    for e in qa:
        buckets[_t(e)].append(e)

    per = n // 3
    result: list[dict] = []
    for b in buckets:
        rng.shuffle(b); result.extend(b[:per])

    seen_ids = {id(e) for e in result}
    rest = [e for e in qa if id(e) not in seen_ids]
    rng.shuffle(rest)
    result.extend(rest[:max(0, n - len(result))])
    return result[:n]


def _ci95(vals: list[float]) -> float:
    if len(vals) < 2:
        return float("nan")
    return 1.96 * float(np.std(vals, ddof=1)) / math.sqrt(len(vals))


def _eval_entry(entry: dict, pairs: list[dict], scoring: dict[int, float],
                topic_map: dict, k_drop: float, topic_decay: float) -> float:
    """Build compacted context, query ollama, judge; return fidelity ∈ {0, 1}."""
    ctx = build_compacted_context(
        entry["source_pair_idx"], pairs, scoring, k_drop,
        topic_decay=topic_decay,
        topic_map=topic_map if topic_decay < 1.0 else None,
        query=entry.get("q"),
    )
    if not ctx:
        return 0.0
    q, a = entry["q"], entry["a_truth"]
    pred = ask_ollama(ctx, q)
    sub = score(pred, a)
    src = pairs[entry["source_pair_idx"]] if 0 <= entry["source_pair_idx"] < len(pairs) else None
    verdict = llm_judge(q, a, pred, source_pair=src)
    return 1.0 if (verdict.get("verdict") == "yes" or sub) else 0.0


def run_ablation(cells: list[str], sample_size: int, seed: int,
                 k_drop: float, topic_decay: float,
                 out_summary: Path, out_results: Path) -> None:
    qa = load_qa_set()
    if not qa:
        print("ERROR: recon_qa_set.jsonl empty/missing — run `weighted-compact build-qa`",
              file=sys.stderr); sys.exit(1)

    pairs = load_pairs()
    topic_map = load_topic_map()
    comp_data = _load_components()
    components, pair_indices = comp_data if comp_data is not None else (None, None)

    sample = _stratified_sample(qa, sample_size, seed, components, pair_indices)
    n = len(sample)
    print(f"Sample: {n}/{len(qa)}  seed={seed}  stratified={'yes' if components is not None else 'no'}")
    if components is None:
        print("WARN: importance.npz missing — falling back to uniform scoring", file=sys.stderr)

    all_results: list[dict[str, Any]] = []
    aggregates: dict[str, dict[str, Any]] = {}

    for cell in cells:
        if cell not in ALL_CELLS:
            print(f"ERROR: unknown cell {cell!r}; valid: {sorted(ALL_CELLS)}", file=sys.stderr)
            sys.exit(1)
        overrides = ALL_CELLS[cell]
        weights = _cell_weights(overrides)
        scoring: dict[int, float] = (
            _apply_weights(components, pair_indices, weights)
            if components is not None
            else {e["source_pair_idx"]: 0.5 for e in sample}
        )
        print(f"[{cell}]  zeroed={list(overrides) or 'none'}")
        fids: list[float] = []
        for entry in sample:
            fid = _eval_entry(entry, pairs, scoring, topic_map, k_drop, topic_decay)
            fids.append(fid)
            all_results.append({
                "cell": cell,
                "source_pair_idx": entry.get("source_pair_idx"),
                "q_snippet": entry.get("q", "")[:80],
                "fidelity": fid,
                "zeroed_signals": list(overrides.keys()),
            })
        mean_f = float(np.mean(fids))
        sd_f = float(np.std(fids, ddof=1)) if n > 1 else float("nan")
        aggregates[cell] = {"n_pairs": n, "mean_fidelity": mean_f, "sd": sd_f,
                            "ci_95": _ci95(fids), "zeroed_signals": list(overrides.keys())}
        print(f"  mean={mean_f:.3f}  sd={sd_f:.3f}  ci95=±{_ci95(fids):.3f}")

    baseline_mean = aggregates.get("baseline", {}).get("mean_fidelity")
    baseline_map = {r["source_pair_idx"]: r["fidelity"]
                    for r in all_results if r["cell"] == "baseline"}

    summary: list[dict[str, Any]] = []
    for cell, agg in aggregates.items():
        delta = (agg["mean_fidelity"] - baseline_mean
                 if baseline_mean is not None and cell != "baseline" else None)
        if baseline_map and cell != "baseline":
            ces = [r for r in all_results if r["cell"] == cell]
            sign_agr = sum(1 for r in ces
                           if baseline_map.get(r["source_pair_idx"], 0.0) == r["fidelity"]
                           ) / len(ces) if ces else float("nan")
        else:
            sign_agr = None
        summary.append({"cell": cell, **agg,
                         "delta_vs_baseline": delta, "sign_agreement_with_baseline": sign_agr})

    out_summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    with out_results.open("w", encoding="utf-8") as f:
        for r in all_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nSummary  → {out_summary}")
    print(f"Results  → {out_results}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        description="Category-collapse ablation: zero one importance axis at a time.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Cost: 5 cells × 30 pairs × 1 judge call/pair ≈ 150 judge calls\n"
            "(n_questions caps stored Qs per entry — currently 1 per entry).\n"
            "With full multi-Q: 5×30×3 = 450 calls, ~2-4 min on gemma3:4b.\n"
        ),
    )
    p.add_argument("--sample-size", type=int, default=30, metavar="N")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--cells", default=",".join(ALL_CELLS),
                   help=f"Comma-separated cells (default: all)")
    p.add_argument("--k-drop", type=float, default=0.5)
    p.add_argument("--topic-decay", type=float, default=0.5)
    p.add_argument("--out-summary", type=Path, default=Path("ablation_axes_summary.json"))
    p.add_argument("--out-results", type=Path, default=Path("ablation_axes_results.jsonl"))
    args = p.parse_args(argv)
    run_ablation(
        cells=[c.strip() for c in args.cells.split(",") if c.strip()],
        sample_size=args.sample_size,
        seed=args.seed,
        k_drop=args.k_drop,
        topic_decay=args.topic_decay,
        out_summary=args.out_summary,
        out_results=args.out_results,
    )


if __name__ == "__main__":
    main()
