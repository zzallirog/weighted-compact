"""COM-shift probe — cheap geometric observable.

Motivation: docs/architecture.md#presence-profile (H1' extension, 2026-05-26).

Each pair lives in a 7D coordinate space (components matrix: misstep, density,
label, span_keep, span_maybe, span_skip, span_think). Adding annotations shifts
the pair from "intrinsic" (misstep+density only, axes 0-1) to "annotated" (full
mixture weights). The shift vector ranks pairs by intervention intensity; the
substrate-wide centroid operationalises the anti-drift invariant.

Prerequisites: `weighted-compact importance` → importance.npz.

--history limitation: full per-event span reconstruction is O(N×E); this
implementation emits a 2-row CSV (baseline vs current) instead. A full replay
requires a span-state helper (implement com_shift_history_full() once ready).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

from weighted_compact import config

# Intrinsic weights: only misstep (0) + density (1) carry mass — the rest are
# annotation-driven and thus zero in the absence of any user intervention.
INTRINSIC_WEIGHTS = np.array([0.40, 0.25, 0, 0, 0, 0, 0], dtype=np.float32)

AXIS_NAMES = [
    "misstep", "density", "label",
    "span_keep", "span_maybe", "span_skip", "span_think",
]


def compute_com_shift(importance_path: Path | None = None) -> dict:
    """Load importance.npz, compute per-pair COM-shift + substrate COM.

    Returns
    -------
    dict with keys:
        com_shift              : (N,) shift magnitude per pair
        intrinsic_coords       : (N,) scalar coords under intrinsic weights
        annotated_coords       : (N,) scalar coords under full mixture weights
        substrate_com_annotated: (7,) importance-weighted centroid, annotated basis
        substrate_com_intrinsic: (7,) importance-weighted centroid, intrinsic basis
        pair_indices           : (N,) pair indices
        components             : (N, 7) raw component matrix
        importance             : (N,) full mixture scores
    """
    p = importance_path or config.importance_path()
    npz = np.load(p, allow_pickle=True)
    components = npz["components"].astype(np.float32)   # (N, 7)
    importance = npz["importance"].astype(np.float32)   # (N,)
    weights    = npz["weights"].astype(np.float32)      # (7,)

    intrinsic_coords = components @ INTRINSIC_WEIGHTS   # (N,)
    annotated_coords = components @ weights             # (N,)
    com_shift = annotated_coords - intrinsic_coords     # (N,)

    total = importance.sum()
    if total > 0:
        substrate_com = (components * importance[:, None]).sum(axis=0) / total
    else:
        substrate_com = components.mean(axis=0)

    intrinsic_imp = np.clip(intrinsic_coords, 0.0, 1.0)
    total_i = intrinsic_imp.sum()
    if total_i > 0:
        substrate_com_intrinsic = (components * intrinsic_imp[:, None]).sum(0) / total_i
    else:
        substrate_com_intrinsic = components.mean(axis=0)

    return {
        "com_shift":               com_shift,
        "intrinsic_coords":        intrinsic_coords,
        "annotated_coords":        annotated_coords,
        "substrate_com_annotated": substrate_com,
        "substrate_com_intrinsic": substrate_com_intrinsic,
        "pair_indices":            npz["pair_indices"],
        "components":              components,
        "importance":              importance,
    }


def save(result: dict, out_path: Path | None = None) -> Path:
    """Save com_shift results to com_shift.npz alongside importance.npz."""
    p = out_path or config.importance_path().with_name("com_shift.npz")
    np.savez(
        p,
        com_shift=result["com_shift"],
        intrinsic_coords=result["intrinsic_coords"],
        annotated_coords=result["annotated_coords"],
        substrate_com_annotated=result["substrate_com_annotated"],
        substrate_com_intrinsic=result["substrate_com_intrinsic"],
        pair_indices=result["pair_indices"],
    )
    return p


def build_history_csv(out_path: Path | None = None) -> Path:
    """Emit com_shift_history.csv — substrate-COM trajectory over annotation events.

    Limitation: full per-event span reconstruction is deferred (see module
    docstring). This function emits a 2-row smoke-test CSV:
      row 0 — zero-annotation baseline (span columns zeroed out)
      row 1 — current state from importance.npz

    A full time-series replay requires reconstructing span_features per-event
    from inline_annotations.jsonl, which is O(N×E) and blocked on a span-replay
    helper. Implement com_shift_history_full() once that helper exists.
    """
    ann_path = config.annotations_path()
    if not ann_path.exists():
        print(f"inline_annotations.jsonl not found at {ann_path} — skipping history", file=sys.stderr)

    imp_path = config.importance_path()
    npz = np.load(imp_path, allow_pickle=True)
    components = npz["components"].astype(np.float32)
    importance = npz["importance"].astype(np.float32)
    weights    = npz["weights"].astype(np.float32)

    def _sub_com(comps: np.ndarray, imp: np.ndarray) -> np.ndarray:
        total = imp.sum()
        if total > 0:
            return (comps * imp[:, None]).sum(axis=0) / total
        return comps.mean(axis=0)

    # Row 0: zero out span columns (indices 2-6) → intrinsic baseline
    base_comps = components.copy()
    base_comps[:, 2:] = 0.0
    base_imp = np.clip(base_comps @ INTRINSIC_WEIGHTS, 0.0, 1.0)
    base_com = _sub_com(base_comps, base_imp)

    # Row 1: current state
    cur_com = _sub_com(components, importance)

    # Count annotations if the file exists
    n_ann = 0
    ts_last = ""
    if ann_path.exists():
        with open(ann_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    n_ann += 1
                    ts_last = r.get("ts") or r.get("timestamp") or ""
                except (json.JSONDecodeError, KeyError):
                    pass

    CSV_COLS = [
        "ts", "n_annotations_so_far",
        "sub_com_misstep", "sub_com_density", "sub_com_label",
        "sub_com_span_keep", "sub_com_span_maybe", "sub_com_span_skip", "sub_com_span_think",
    ]
    out = out_path or config.importance_path().with_name("com_shift_history.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLS)
        writer.writerow(["baseline", 0] + [f"{v:.6f}" for v in base_com])
        writer.writerow([ts_last or "current", n_ann] + [f"{v:.6f}" for v in cur_com])
    return out


def _print_stats(result: dict) -> None:
    cs = result["com_shift"]
    acs = np.abs(cs)
    print(f"N pairs: {len(cs)}")
    print(f"|com_shift| distribution:")
    print(f"  min={acs.min():.4f}  p25={np.percentile(acs, 25):.4f}  "
          f"median={np.median(acs):.4f}  p75={np.percentile(acs, 75):.4f}  max={acs.max():.4f}")
    print()
    print("substrate_com (annotated) per axis:")
    for name, val in zip(AXIS_NAMES, result["substrate_com_annotated"]):
        print(f"  {name:<12s}  {val:.4f}")
    print()
    print("substrate_com (intrinsic) per axis:")
    for name, val in zip(AXIS_NAMES, result["substrate_com_intrinsic"]):
        print(f"  {name:<12s}  {val:.4f}")


def _print_top(result: dict, n: int) -> None:
    cs = result["com_shift"]
    acs = np.abs(cs)
    pids = result["pair_indices"]
    top = np.argsort(-acs)[:n]
    print(f"\nTop {n} pairs by |com_shift|:")
    for row in top:
        pid = int(pids[row])
        comp = result["components"][row]
        print(f"  pair[{pid:3d}]  |shift|={acs[row]:.4f}  "
              f"shift={cs[row]:+.4f}  "
              f"mist={comp[0]:.2f} dens={comp[1]:.2f} "
              f"sk={comp[3]:.2f}/mb={comp[4]:.2f}/sp={comp[5]:.2f}/th={comp[6]:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="weighted-compact com-shift",
        description="COM-shift probe — geometric observable for the H1' anti-drift invariant.",
    )
    parser.add_argument("--top", type=int, default=0, metavar="N",
                        help="Print top-N pairs by |com_shift|.")
    parser.add_argument("--stats", action="store_true",
                        help="Print substrate-COM summary.")
    parser.add_argument("--history", action="store_true",
                        help="Emit com_shift_history.csv (2-row smoke-test; see module docstring).")
    parser.add_argument("--save", action="store_true",
                        help="Save results to com_shift.npz.")
    args = parser.parse_args()

    # Default: compute + save + stats if no flags given
    no_flags = not any([args.top, args.stats, args.history, args.save])

    imp_path = config.importance_path()
    if not imp_path.exists():
        print(f"importance.npz not found at {imp_path}", file=sys.stderr)
        print("Prerequisite: run `weighted-compact importance` first.", file=sys.stderr)
        sys.exit(1)

    result = compute_com_shift()

    if no_flags or args.stats:
        _print_stats(result)

    if no_flags:
        args.top = args.top or 10

    if args.top:
        _print_top(result, args.top)

    if no_flags or args.save:
        p = save(result)
        print(f"\nOutput: {p}")

    if args.history:
        p = build_history_csv()
        print(f"History CSV: {p}")


if __name__ == "__main__":
    main()
