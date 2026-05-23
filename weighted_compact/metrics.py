"""Substrate metrics — on-demand footprint readout for the CLI.

Black box:
  input  — none (reads $WEIGHTED_COMPACT_DATA + Claude source dirs from config).
  output — dict with substrate path, size breakdown, pair/session counts,
           REM-pass freshness, and a warm-cache timing of the two hot loaders.
  entry  — `collect()` returns the structured dict; `format_text()` renders
           the plain-text view consumed by `weighted-compact metrics`.

Why this module exists: the operating guide quotes footprint numbers
(`docs/operating-guide.md`) measured on the maintainer's substrate. A user
on a fresh install had no way to print the same numbers for their own
substrate. This is the read-only diagnostic that closes that gap.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from weighted_compact import config


# Files we attribute to the substrate footprint. Anything matching the
# `*.bak.*` pattern is reported separately (cleanup target).
_FOOTPRINT_FILENAMES: tuple[str, ...] = (
    config.PAIRS_FILE,
    config.LABELS_FILE,
    config.QUEUE_FILE,
    config.ANNOTATIONS_FILE,
    config.INLINE_MARKERS_FILE,
    config.RECON_QA_SET_FILE,
    config.DISAGREEMENT_QUEUE,
    config.SUGGEST_AUDIT,
    config.FEATURES_FILE,
    config.FEATURES_DENSITY_FILE,
    config.FEATURES_MISSTEP_FILE,
    config.FEATURES_SPANS_FILE,
    config.TOPIC_SEGMENTS_FILE,
    config.IMPORTANCE_FILE,
    config.CLASSIFIER_FILE,
    config.BASELINE_RANDOM_FILE,
    config.BASELINE_RECENCY_FILE,
    config.REM_DECAY_FILE,
)


def _size_or_zero(p: Path) -> int:
    try:
        return p.stat().st_size
    except (FileNotFoundError, OSError):
        return 0


def _per_file_table(workdir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in _FOOTPRINT_FILENAMES:
        path = workdir / name
        rows.append({
            "name": name,
            "exists": path.exists(),
            "bytes": _size_or_zero(path),
        })
    return rows


def _backup_bytes(workdir: Path) -> tuple[int, int]:
    """Sum of `*.bak.*` overhead in the substrate. Returns (bytes, file_count)."""
    if not workdir.exists():
        return 0, 0
    total = 0
    count = 0
    for path in workdir.glob("*.bak.*"):
        try:
            total += path.stat().st_size
            count += 1
        except OSError:
            continue
    # rem_decay rotates to `rem_decay.npz.bak.<ts>` — same pattern catches it.
    return total, count


def _count_pairs_and_sessions(workdir: Path) -> tuple[int, int]:
    """Count pairs.jsonl line entries + unique session_ids. Tolerant to bad lines."""
    pairs_path = workdir / config.PAIRS_FILE
    if not pairs_path.exists():
        return 0, 0
    n_pairs = 0
    sessions: set[str] = set()
    with open(pairs_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            n_pairs += 1
            sid = r.get("session_id")
            if sid:
                sessions.add(sid)
    return n_pairs, len(sessions)


def _rem_decay_freshness(workdir: Path) -> str | None:
    """Return the `ref_iso` recorded in rem_decay.npz meta, or None if never built."""
    rem_path = workdir / config.REM_DECAY_FILE
    if not rem_path.exists():
        return None
    try:
        import numpy as np
        npz = np.load(rem_path, allow_pickle=True)
        meta = json.loads(str(npz["meta"][0]))
        return meta.get("ref_iso")
    except Exception:  # noqa: BLE001 — degrade silently
        return None


def _time_loader(fn) -> float:
    """Warm-cache wallclock microbenchmark — single call, returns seconds."""
    t0 = time.perf_counter()
    try:
        fn()
    except Exception:  # noqa: BLE001 — timing failures are still informative
        pass
    return time.perf_counter() - t0


def collect() -> dict[str, Any]:
    """Gather all metrics into a structured dict.

    Single read-only pass over the substrate. No state mutation. The
    microbenchmark warms both loaders once before timing so the reported
    numbers reflect steady-state cost, not cold-start NPZ mmap overhead.
    """
    workdir = config.workdir()
    files = _per_file_table(workdir)
    substrate_bytes = sum(row["bytes"] for row in files)
    bak_bytes, bak_count = _backup_bytes(workdir)
    n_pairs, n_sessions = _count_pairs_and_sessions(workdir)
    ref_iso = _rem_decay_freshness(workdir)

    # Microbenchmark: warm once, then time. Both loaders are pure reads.
    timings: dict[str, float | None] = {
        "load_pairs_seconds": None,
        "load_importance_seconds": None,
    }
    try:
        from weighted_compact.recon_qa.context import (
            load_importance,
            load_pairs,
        )
        # Warmup pass (mmap, page cache).
        try:
            load_pairs()
        except Exception:  # noqa: BLE001
            pass
        timings["load_pairs_seconds"] = _time_loader(load_pairs)
        try:
            load_importance()
        except Exception:  # noqa: BLE001
            pass
        timings["load_importance_seconds"] = _time_loader(load_importance)
    except ImportError:
        pass

    return {
        "substrate_path": str(workdir),
        "substrate_exists": workdir.exists(),
        "substrate_bytes": substrate_bytes,
        "backup_bytes": bak_bytes,
        "backup_file_count": bak_count,
        "pair_count": n_pairs,
        "session_count": n_sessions,
        "files": files,
        "rem_decay_ref_iso": ref_iso,
        "timings": timings,
    }


def _fmt_bytes(n: int) -> str:
    """Human-readable bytes — KiB/MiB/GiB."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KiB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MiB"
    return f"{n / (1024 * 1024 * 1024):.2f} GiB"


def _fmt_seconds(s: float | None) -> str:
    if s is None:
        return "n/a"
    if s < 1e-3:
        return f"{s * 1e6:.0f} µs"
    if s < 1.0:
        return f"{s * 1e3:.1f} ms"
    return f"{s:.2f} s"


def format_text(report: dict[str, Any]) -> str:
    """Render `collect()` output as the plain-text view for `weighted-compact metrics`."""
    lines: list[str] = []
    lines.append(f"Substrate: {report['substrate_path']}")
    if not report["substrate_exists"]:
        lines.append("  · not created yet — run `weighted-compact bootstrap`")
        return "\n".join(lines)

    lines.append(f"  size:     {_fmt_bytes(report['substrate_bytes'])}")
    if report["backup_file_count"] > 0:
        lines.append(
            f"  backups:  {_fmt_bytes(report['backup_bytes'])} "
            f"across {report['backup_file_count']} *.bak.* files (cleanup target)"
        )
    else:
        lines.append("  backups:  0 B (no *.bak.* files)")
    lines.append(f"  pairs:    {report['pair_count']}")
    lines.append(f"  sessions: {report['session_count']}")
    rem_iso = report["rem_decay_ref_iso"]
    lines.append(f"  rem-pass: {rem_iso if rem_iso else 'never run'}")

    lines.append("")
    lines.append("Per-file:")
    width = max(len(row["name"]) for row in report["files"])
    for row in report["files"]:
        mark = " " if row["exists"] else "·"
        size = _fmt_bytes(row["bytes"]) if row["exists"] else "absent"
        lines.append(f"  {mark} {row['name']:<{width}}  {size}")

    lines.append("")
    lines.append("Timings (warm cache, single call):")
    t = report["timings"]
    lines.append(f"  load_pairs       {_fmt_seconds(t.get('load_pairs_seconds'))}")
    lines.append(f"  load_importance  {_fmt_seconds(t.get('load_importance_seconds'))}")
    return "\n".join(lines)
