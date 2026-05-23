"""REM-decay baseline wrapper.

Black box:
  input  — pairs.jsonl + Claude source dirs (session mtime probe).
  output — rem_decay.npz: wall-clock half-life decay per pair_idx.
  entry  — `build()` delegates to `weighted_compact.rem_decay.build()`.

Sense: lets `weighted-compact baseline build --ranker rem` and
`baseline run-all --include ...,rem` treat the REM pass as a registered
ranker for the fidelity harness. The output is the same npz schema as
other baselines (`pair_indices`, `importance`, `meta`), so the existing
loaders pick it up unchanged.
"""
from __future__ import annotations

from weighted_compact.rem_decay import (
    DEFAULT_HALF_LIFE_DAYS,
    SCHEMA_VER,  # noqa: F401 — re-exported for symmetry with peer baselines
    build as _build,
)


def build(half_life_days: float = DEFAULT_HALF_LIFE_DAYS) -> dict:
    summary = _build(half_life_days=half_life_days)
    return {
        "path": summary["path"],
        "n": summary["pair_count"],
        "sessions": summary["session_count"],
        "min": summary["factor_min"],
        "max": summary["factor_max"],
        "mean": summary["factor_mean"],
    }


def main() -> None:
    summary = build()
    print(f"Output: {summary['path']}")
    print(
        f"N={summary['n']}  sessions={summary['sessions']}  "
        f"min={summary['min']:.3f} mean={summary['mean']:.3f} max={summary['max']:.3f}",
    )


if __name__ == "__main__":
    main()
