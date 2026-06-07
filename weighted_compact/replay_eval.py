"""Replay store builder and eval runner for CMA-ES weight search.

AutoTTS §2.2(a) pattern: precompute the replay store ONCE, then each
CMA-ES eval is a cheap matrix multiply + threshold — 0 LLM calls.

Replay store layout (out_dir/):
    components.npz   — [n_pairs × 7] signal scores, row order = pair_idx
    gt.json          — {pair_idx: fidelity_score} from fidelity_v2.jsonl
    meta.json        — provenance (source files, n_pairs, session distribution)

Signal order in components[:, i]:
    0: misstep    (1 - P(stumble); 0 if misstep not installed)
    1: density    (rank-normalised mean of 16 features)
    2: label      (0/1 keep indicator)
    3: span_keep  (char-fraction KEEP on correction side)
    4: span_maybe (char-fraction MAYBE)
    5: span_skip  (char-fraction SKIP)
    6: span_think (char-fraction THINK)

For subset_a.json (264 retrieval-bottleneck pairs):
    - pair_idx values in 0..578 (non-contiguous)
    - session_id from fidelity_v2.jsonl (source_session_id field)
    - Signal values derived from corpus features if available, else synthetic
      proxy from subset_a metadata (n_entries, idk_ratio, sonnet_verdict)

Synthetic proxy fallback (when real feature npz are absent):
    Used for mock-metric CMA-ES only.  Not suitable for publication-grade eval.
    misstep  = 1.0 - idk_ratio          (lower IDK → more informative → higher misstep-proxy)
    density  = n_entries / max_entries   (normalised pair complexity proxy)
    label    = 0.0                       (no labels in q_split pairs)
    span_*   = 0.0                       (no span annotations)

CLI usage:
    python -m weighted_compact.replay_eval --precompute \\
        --pairs ~/weighted-compact-data/q_split_output/subset_a.json \\
        --gt-source ~/weighted-compact-data/fidelity_v2.jsonl \\
        --out-dir /tmp/wc_search/

    python -m weighted_compact.replay_eval --info \\
        --out-dir /tmp/wc_search/
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import numpy as np


# Canonical signal order — must match importance.py components layout
SIGNAL_NAMES = ["misstep", "density", "label", "span_keep", "span_maybe", "span_skip", "span_think"]


# ---------------------------------------------------------------------------
# Core precompute
# ---------------------------------------------------------------------------

def precompute_replay_store(
    pairs_source: Path,
    gt_source: Path,
    out_dir: Path,
    feature_dir: Path | None = None,
) -> dict[str, Any]:
    """Build the replay store from subset_a.json + fidelity_v2.jsonl.

    Args:
        pairs_source: Path to subset_a.json (264 pairs) or any q_split JSON.
        gt_source: Path to fidelity_v2.jsonl (Sonnet ground truth fidelity).
        out_dir: Output directory for components.npz, gt.json, meta.json.
        feature_dir: Optional directory containing features_density.npz,
            features_spans.npz, features_misstep.npz from the WC substrate.
            If None or files absent: synthetic proxy is used.

    Returns:
        Meta dict with provenance and diagnostics.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load pairs
    pairs_text = pairs_source.read_text()
    if pairs_text.strip().startswith("["):
        pairs: list[dict] = json.loads(pairs_text)
    else:
        pairs = [json.loads(line) for line in pairs_text.splitlines() if line.strip()]

    # Load GT fidelity
    gt_records: dict[int, dict] = {}
    with gt_source.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            gt_records[int(rec["pair_idx"])] = rec

    # Index pairs by pair_idx
    pair_idxs = [int(p["pair_idx"]) for p in pairs]
    n_pairs = len(pair_idxs)

    # Try loading real features
    components = _build_components(pairs, pair_idxs, feature_dir)

    # Build GT array (fidelity score per pair, 0.0 if not in fidelity_v2)
    gt_fidelity = np.zeros(n_pairs, dtype=np.float64)
    missing_gt = 0
    for i, pidx in enumerate(pair_idxs):
        rec = gt_records.get(pidx)
        if rec is not None:
            fid = rec.get("fidelity")
            gt_fidelity[i] = float(fid) if fid is not None else 0.0
        else:
            missing_gt += 1

    # Inject session_id into pairs for CV harness
    pairs_with_session = []
    for i, p in enumerate(pairs):
        pidx = int(p["pair_idx"])
        rec = gt_records.get(pidx, {})
        pairs_with_session.append({
            "pair_idx": pidx,
            "session_id": rec.get("source_session_id", "unknown"),
            "fidelity": float(gt_fidelity[i]),
            **{k: v for k, v in p.items() if k not in ("pair_idx",)},
        })

    # Save components
    np.savez(
        out_dir / "components.npz",
        components=components.astype(np.float32),
        pair_indices=np.array(pair_idxs, dtype=np.int32),
        gt_fidelity=gt_fidelity.astype(np.float32),
        signal_names=np.array(SIGNAL_NAMES, dtype=object),
    )

    # Save GT as JSON for easy loading
    gt_json = {str(pidx): float(gt_fidelity[i]) for i, pidx in enumerate(pair_idxs)}
    (out_dir / "gt.json").write_text(json.dumps(gt_json, indent=2))

    # Save pairs with session_id for CV harness
    (out_dir / "pairs_with_session.json").write_text(
        json.dumps(pairs_with_session, ensure_ascii=False, indent=2)
    )

    # Statistics
    nonzero_gt = int((gt_fidelity > 0).sum())
    sessions = set(p["session_id"] for p in pairs_with_session)

    meta = {
        "pairs_source": str(pairs_source),
        "gt_source": str(gt_source),
        "n_pairs": n_pairs,
        "n_sessions": len(sessions),
        "signal_names": SIGNAL_NAMES,
        "gt_nonzero": nonzero_gt,
        "gt_zero": n_pairs - nonzero_gt,
        "gt_mean": float(gt_fidelity.mean()),
        "gt_pass_rate": nonzero_gt / n_pairs,
        "missing_gt": missing_gt,
        "synthetic_features": feature_dir is None or not _has_real_features(feature_dir),
        "components_shape": list(components.shape),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    return meta


def load_replay_store(out_dir: Path) -> tuple[np.ndarray, np.ndarray, list[dict], dict]:
    """Load a precomputed replay store.

    Returns:
        (components, gt_fidelity, pairs_with_session, meta)
        components: [n_pairs × 7] float32
        gt_fidelity: [n_pairs] float32
        pairs_with_session: list of pair dicts (with session_id)
        meta: provenance dict
    """
    data = np.load(out_dir / "components.npz", allow_pickle=True)
    components = data["components"].astype(np.float64)
    gt_fidelity = data["gt_fidelity"].astype(np.float64)

    pairs_with_session = json.loads((out_dir / "pairs_with_session.json").read_text())
    meta = json.loads((out_dir / "meta.json").read_text())

    return components, gt_fidelity, pairs_with_session, meta


# ---------------------------------------------------------------------------
# Component builder: real features or synthetic proxy
# ---------------------------------------------------------------------------

def _has_real_features(feature_dir: Path) -> bool:
    return (
        (feature_dir / "features_density.npz").exists()
        or (feature_dir / "features_misstep.npz").exists()
    )


def _build_components(
    pairs: list[dict],
    pair_idxs: list[int],
    feature_dir: Path | None,
) -> np.ndarray:
    """Build [n_pairs × 7] component matrix.

    Falls back to synthetic proxy if real features are unavailable.
    """
    n = len(pairs)

    # Attempt real features
    if feature_dir is not None and _has_real_features(feature_dir):
        return _build_from_real_features(pairs, pair_idxs, n, feature_dir)

    # Synthetic proxy fallback
    return _build_synthetic(pairs, n)


def _build_from_real_features(
    pairs: list[dict],
    pair_idxs: list[int],
    n: int,
    feature_dir: Path,
) -> np.ndarray:
    """Extract signals from real feature npz files.

    Matches pairs by pair_idx; zero-fills any pair not found in features.
    """
    components = np.zeros((n, 7), dtype=np.float64)
    pidx_set = set(pair_idxs)
    pidx_to_row = {pidx: i for i, pidx in enumerate(pair_idxs)}

    # misstep (col 0)
    misstep_path = feature_dir / "features_misstep.npz"
    if misstep_path.exists():
        m = np.load(misstep_path, allow_pickle=True)
        for feat_i, pidx in enumerate(m["pair_indices"]):
            if int(pidx) in pidx_to_row:
                components[pidx_to_row[int(pidx)], 0] = float(m["importance"][feat_i])

    # density (col 1)
    density_path = feature_dir / "features_density.npz"
    if density_path.exists():
        d = np.load(density_path, allow_pickle=True)
        raw_density = d["density"].mean(axis=1)  # (N, 16) → (N,)
        # rank-normalise within available pairs
        ranked = _rank_normalize(raw_density)
        for feat_i, pidx in enumerate(d["pair_indices"]):
            if int(pidx) in pidx_to_row:
                components[pidx_to_row[int(pidx)], 1] = float(ranked[feat_i])

    # spans (cols 3-6: keep, maybe, skip, think — correction side = cols 1,3,5,7)
    spans_path = feature_dir / "features_spans.npz"
    if spans_path.exists():
        s = np.load(spans_path, allow_pickle=True)
        # tier_names: ['keep_premise','keep_correction','maybe_premise','maybe_correction',
        #              'skip_premise','skip_correction','think_premise','think_correction']
        span_mat = s["spans"]  # (N, 8)
        for feat_i, pidx in enumerate(s["pair_indices"]):
            if int(pidx) in pidx_to_row:
                row = pidx_to_row[int(pidx)]
                components[row, 3] = float(span_mat[feat_i, 1])  # keep_correction
                components[row, 4] = float(span_mat[feat_i, 3])  # maybe_correction
                components[row, 5] = float(span_mat[feat_i, 5])  # skip_correction
                components[row, 6] = float(span_mat[feat_i, 7])  # think_correction

    # label (col 2) — not available from q_split; stays 0
    return components


def _build_synthetic(pairs: list[dict], n: int) -> np.ndarray:
    """Synthetic proxy from q_split metadata (no real features needed).

    Columns:
        0 misstep: 1.0 - idk_ratio  (lower IDK → more informative)
        1 density: n_entries / max_n_entries (normalised)
        2 label: 0.0 (no labels)
        3-6 spans: 0.0 (no annotations)
    """
    components = np.zeros((n, 7), dtype=np.float64)

    n_entries_vals = [float(p.get("n_entries", 1)) for p in pairs]
    max_entries = max(n_entries_vals) if n_entries_vals else 1.0

    for i, p in enumerate(pairs):
        idk_ratio = float(p.get("idk_ratio", 0.0))
        n_entries = float(p.get("n_entries", 1))
        components[i, 0] = 1.0 - idk_ratio          # misstep proxy
        components[i, 1] = n_entries / max_entries    # density proxy

    return components


def _rank_normalize(arr: np.ndarray) -> np.ndarray:
    """Rank-normalise a 1-D array to [0, 1]."""
    n = len(arr)
    if n <= 1:
        return np.zeros_like(arr, dtype=np.float64)
    ranks = np.argsort(np.argsort(arr)).astype(np.float64)
    return ranks / (n - 1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    parser = argparse.ArgumentParser(description="Replay store builder for WC CMA-ES search")
    sub = parser.add_subparsers(dest="cmd")

    # --precompute
    pre = sub.add_parser("precompute", help="Build replay store from corpus")
    pre.add_argument("--pairs", type=Path, required=True,
                     help="Path to subset_a.json or pairs JSON/JSONL")
    pre.add_argument("--gt-source", type=Path, required=True,
                     help="Path to fidelity_v2.jsonl")
    pre.add_argument("--out-dir", type=Path, required=True,
                     help="Output directory for replay store")
    pre.add_argument("--feature-dir", type=Path, default=None,
                     help="Optional: dir with features_density.npz etc.")

    # --info
    info = sub.add_parser("info", help="Print meta.json from replay store")
    info.add_argument("--out-dir", type=Path, required=True)

    args = parser.parse_args()

    if args.cmd == "precompute":
        meta = precompute_replay_store(
            pairs_source=args.pairs,
            gt_source=args.gt_source,
            out_dir=args.out_dir,
            feature_dir=args.feature_dir,
        )
        print("Replay store built:")
        for k, v in meta.items():
            print(f"  {k}: {v}")
        print(f"\nOutput: {args.out_dir}")

    elif args.cmd == "info":
        meta_path = args.out_dir / "meta.json"
        if not meta_path.exists():
            print(f"No meta.json found at {args.out_dir}")
            return
        meta = json.loads(meta_path.read_text())
        print("Replay store meta:")
        for k, v in meta.items():
            print(f"  {k}: {v}")

    else:
        parser.print_help()


if __name__ == "__main__":
    _main()
