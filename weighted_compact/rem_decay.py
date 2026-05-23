"""REM-decay — daily importance refresh with wall-clock recency bias.

Black box:
  input  — pairs.jsonl + Claude source dirs + half-life parameter.
  output — rem_decay.npz: per-pair multiplier ∈ (0, 1] derived from
           exp(-ln(2) * age_days / half_life_days).
  entry  — `build()` writes the npz. `compute()` is the pure function.

Sense. Importance built from misstep/density/label/span is content-stable:
it does not know that the conversation is from three months ago. The REM
pass adds a wall-clock decay on top, so a nightly recompute (one
systemd-user timer firing at 04:00) yields a substrate where yesterday's
sessions outweigh last quarter's by the half-life curve. Default
half-life = 7 days, giving:

    yesterday  ≈ 0.91
    week ago   ≈ 0.50
    month ago  ≈ 0.05

The output is a multiplier, not a replacement: consumers compose it via
`effective = importance[pid] * rem_decay[pid]`. See
`recon_qa.context.build_compacted_context(rem_decay_map=...)`.

Session timestamp is derived from the mtime of the matching transcript at
`~/.claude/projects/<dashed_cwd>/<session_id>.jsonl`. The transcript is
appended-to during the session, so mtime tracks last activity. Sessions
whose transcript cannot be located fall back to ref_ts (today) — they
become weight-1.0 and remain visible.
"""
from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from weighted_compact import config
from weighted_compact.recon_qa.context import load_pairs

DEFAULT_HALF_LIFE_DAYS = 7.0

# Bump when the rem_decay.npz layout changes. Existing files predating
# the schema_ver field are treated as ver 0 by `load_rem_decay`; the
# guard fires on mismatch with a `weighted-compact rem-pass` directive.
SCHEMA_VER = 1


def _index_session_mtimes(source_dirs: list[Path]) -> dict[str, float]:
    """Walk Claude source dirs once; return {session_id: mtime_seconds}.

    session_id is the basename of the transcript jsonl (Claude Code's
    convention). Missing dirs are silently skipped.
    """
    out: dict[str, float] = {}
    for src in source_dirs:
        if not src.exists():
            continue
        for project_dir in src.iterdir():
            if not project_dir.is_dir():
                continue
            for f in project_dir.glob("*.jsonl"):
                sid = f.stem
                try:
                    mtime = f.stat().st_mtime
                except OSError:
                    continue
                # Keep latest mtime if same session_id appears under multiple
                # source roots (unlikely but possible when both ~/.claude and
                # ~/.claude-work hold mirrors).
                prev = out.get(sid)
                if prev is None or mtime > prev:
                    out[sid] = mtime
    return out


def compute(
    pairs: list[dict],
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    ref_ts: float | None = None,
    source_dirs: list[Path] | None = None,
) -> tuple[dict[int, float], dict]:
    """Pure-function REM decay.

    Returns (pair_idx → factor, summary dict). Factor is exp(-ln(2) * age_days /
    half_life_days), clipped to (0, 1]. Sessions in the future (ref_ts older
    than mtime — clock skew, manual edits) get factor 1.0.
    """
    if ref_ts is None:
        ref_ts = time.time()
    if source_dirs is None:
        source_dirs = config.claude_source_dirs()

    sid_mtime = _index_session_mtimes(source_dirs)
    lam = math.log(2.0) / max(half_life_days, 1e-6)

    factors: dict[int, float] = {}
    aged_session_count = 0
    missing_session_count = 0
    seen_sessions: set[str] = set()
    age_days_max = 0.0

    for p in pairs:
        sid = p["session_id"]
        ts = sid_mtime.get(sid)
        if ts is None:
            factor = 1.0
            if sid not in seen_sessions:
                missing_session_count += 1
        else:
            age_sec = max(0.0, ref_ts - ts)
            age_days = age_sec / 86400.0
            age_days_max = max(age_days_max, age_days)
            factor = math.exp(-lam * age_days)
            if sid not in seen_sessions:
                aged_session_count += 1
        seen_sessions.add(sid)
        factors[int(p["pair_idx"])] = float(factor)

    summary = {
        "ref_ts": ref_ts,
        "ref_iso": datetime.fromtimestamp(ref_ts, tz=timezone.utc).isoformat(),
        "half_life_days": half_life_days,
        "pair_count": len(factors),
        "session_count": len(seen_sessions),
        "aged_session_count": aged_session_count,
        "missing_session_count": missing_session_count,
        "max_age_days_seen": age_days_max,
        "factor_min": min(factors.values()) if factors else 0.0,
        "factor_mean": (sum(factors.values()) / len(factors)) if factors else 0.0,
        "factor_max": max(factors.values()) if factors else 0.0,
    }
    return factors, summary


def build(
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    ref_ts: float | None = None,
) -> dict:
    """Compute and atomically publish rem_decay.npz.

    Schema (parallel to baseline_*.npz so consumers can drop-in load):
      pair_indices : (N,) int32
      importance   : (N,) float32 — the multiplier (named `importance` for
                     schema-compatibility with the baseline ranker family)
      meta         : json blob with half-life, ref_ts, session counts

    Atomic publish via .tmp.npz → rename, mirroring importance.py's rotation.
    """
    pairs = load_pairs()
    if not pairs:
        raise RuntimeError("no pairs in substrate — run `weighted-compact bootstrap` first")

    factors, summary = compute(pairs, half_life_days=half_life_days, ref_ts=ref_ts)

    pair_indices = np.array(
        [int(p["pair_idx"]) for p in pairs], dtype=np.int32,
    )
    importance = np.array(
        [factors[int(pid)] for pid in pair_indices], dtype=np.float32,
    )

    out = config.rem_decay_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_base = out.with_name("rem_decay.tmp")
    tmp_path = out.with_name("rem_decay.tmp.npz")
    meta = {
        "ranker": "rem_decay",
        "rationale": "wall-clock half-life decay multiplier; product with importance",
        **summary,
    }
    np.savez(
        tmp_base,
        importance=importance,
        pair_indices=pair_indices,
        meta=np.array([json.dumps(meta)], dtype=object),
        schema_ver=np.array([SCHEMA_VER], dtype=np.int32),
    )

    if out.exists():
        ts_label = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        bak_path = out.with_name(f"rem_decay.npz.bak.{ts_label}")
        os.rename(out, bak_path)
    os.rename(tmp_path, out)

    return {"path": str(out), **summary}


def main() -> None:
    """CLI entry — `python -m weighted_compact.rem_decay`."""
    summary = build()
    print(f"Output: {summary['path']}")
    print(
        f"N={summary['pair_count']}  sessions={summary['session_count']}  "
        f"aged={summary['aged_session_count']}  missing={summary['missing_session_count']}",
    )
    print(
        f"half-life={summary['half_life_days']} days  "
        f"max_age_seen={summary['max_age_days_seen']:.1f} days  "
        f"ref={summary['ref_iso']}",
    )
    print(
        f"factor: min={summary['factor_min']:.3f}  "
        f"mean={summary['factor_mean']:.3f}  max={summary['factor_max']:.3f}",
    )


if __name__ == "__main__":
    main()
